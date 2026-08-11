"""Single-flight ownership and fencing for LangGraph conversation runs.

The LangGraph checkpointer can safely persist concurrent database writes, but
two graph runs must never advance the same logical conversation concurrently.
This coordinator gives each accepted user message one run generation, cancels
an older run in the same process, and uses a PostgreSQL advisory lock plus a
generation row when several API workers share the deployment.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger("copepod.thread_runs")


class RunSuperseded(asyncio.CancelledError):
    """Raised when a newer user message owns the conversation generation."""


@dataclass
class ThreadRunLease:
    """Ownership token checked at graph/model/tool boundaries."""

    coordinator: "ThreadRunCoordinator"
    thread_id: str
    message_id: str
    run_id: str
    generation: int = 0
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    postgres_connection: Any = field(default=None, repr=False)

    async def ensure_current(self) -> None:
        """Fail before more work is emitted when this run was superseded."""
        if self.cancel_event.is_set():
            raise RunSuperseded(
                f"run {self.run_id} superseded for thread {self.thread_id}"
            )
        if not await self.coordinator.is_current(self):
            self.cancel_event.set()
            raise RunSuperseded(
                f"generation {self.generation} is stale for thread {self.thread_id}"
            )

    def bind_config(self, config: dict) -> dict:
        """Attach stable run ownership metadata without mutating the caller."""
        metadata = {
            **(config.get("metadata") or {}),
            "agent_run_id": self.run_id,
            "run_generation": self.generation,
            "message_id": self.message_id,
        }
        return {**config, "metadata": metadata}


@dataclass
class _ActiveRun:
    lease: ThreadRunLease
    task: asyncio.Task


class ThreadRunCoordinator:
    """Serialize runs per thread while allowing distinct threads in parallel."""

    _DDL = """
        CREATE TABLE IF NOT EXISTS agent_thread_runs (
            thread_id TEXT PRIMARY KEY,
            generation BIGINT NOT NULL,
            run_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """

    def __init__(self) -> None:
        self._registry_lock = asyncio.Lock()
        self._active: dict[str, _ActiveRun] = {}
        self._local_generations: dict[str, int] = {}
        self._postgres_dsn: str | None = None

    async def configure_postgres(self, dsn: str | None) -> None:
        """Enable cross-worker fencing; degrade to process-local ownership."""
        self._postgres_dsn = None
        if not dsn:
            return
        try:
            import psycopg

            conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
            try:
                await conn.execute(self._DDL)
            finally:
                await conn.close()
        except Exception as exc:  # noqa: BLE001 - startup must still degrade
            logger.warning("Postgres run fencing unavailable: %s", exc)
            return
        self._postgres_dsn = dsn
        logger.info("Postgres thread-run fencing ready")

    async def _claim_generation(self, lease: ThreadRunLease) -> int:
        if not self._postgres_dsn:
            generation = self._local_generations.get(lease.thread_id, 0) + 1
            self._local_generations[lease.thread_id] = generation
            return generation

        import psycopg

        conn = await psycopg.AsyncConnection.connect(
            self._postgres_dsn, autocommit=True
        )
        try:
            cursor = await conn.execute(
                """
                INSERT INTO agent_thread_runs
                    (thread_id, generation, run_id, message_id, status, updated_at)
                VALUES (%s, 1, %s, %s, 'waiting', NOW())
                ON CONFLICT (thread_id) DO UPDATE
                SET generation = agent_thread_runs.generation + 1,
                    run_id = EXCLUDED.run_id,
                    message_id = EXCLUDED.message_id,
                    status = 'waiting',
                    updated_at = NOW()
                RETURNING generation
                """,
                (lease.thread_id, lease.run_id, lease.message_id),
            )
            row = await cursor.fetchone()
            return int(row[0])
        finally:
            await conn.close()

    @staticmethod
    def _advisory_key(thread_id: str) -> int:
        digest = hashlib.blake2b(thread_id.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, byteorder="big", signed=True)

    async def _acquire_postgres_lock(self, lease: ThreadRunLease):
        if not self._postgres_dsn:
            return None
        import psycopg

        conn = await psycopg.AsyncConnection.connect(
            self._postgres_dsn, autocommit=True
        )
        try:
            await conn.execute(
                "SELECT pg_advisory_lock(%s)",
                (self._advisory_key(lease.thread_id),),
            )
            cursor = await conn.execute(
                """
                UPDATE agent_thread_runs
                SET status = 'running', updated_at = NOW()
                WHERE thread_id = %s AND generation = %s AND run_id = %s
                RETURNING generation
                """,
                (lease.thread_id, lease.generation, lease.run_id),
            )
            if await cursor.fetchone() is None:
                raise RunSuperseded(
                    f"run {lease.run_id} lost ownership before execution"
                )
            return conn
        except BaseException:
            with suppress(Exception):
                await conn.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (self._advisory_key(lease.thread_id),),
                )
            await conn.close()
            raise

    async def _release_postgres_lock(
        self,
        lease: ThreadRunLease,
        conn,
        *,
        status: str,
    ) -> None:
        if conn is None:
            return
        with suppress(Exception):
            await conn.execute(
                """
                UPDATE agent_thread_runs
                SET status = %s, updated_at = NOW()
                WHERE thread_id = %s AND generation = %s AND run_id = %s
                """,
                (status, lease.thread_id, lease.generation, lease.run_id),
            )
        with suppress(Exception):
            await conn.execute(
                "SELECT pg_advisory_unlock(%s)",
                (self._advisory_key(lease.thread_id),),
            )
        await conn.close()

    async def is_current(self, lease: ThreadRunLease) -> bool:
        """Check local ownership and, when configured, the DB generation."""
        async with self._registry_lock:
            active = self._active.get(lease.thread_id)
            local_current = active is not None and active.lease is lease
        if not local_current:
            return False
        if not self._postgres_dsn:
            return self._local_generations.get(lease.thread_id) == lease.generation

        if lease.postgres_connection is not None:
            cursor = await lease.postgres_connection.execute(
                """
                SELECT 1 FROM agent_thread_runs
                WHERE thread_id = %s AND generation = %s AND run_id = %s
                """,
                (lease.thread_id, lease.generation, lease.run_id),
            )
            return await cursor.fetchone() is not None

        import psycopg

        conn = await psycopg.AsyncConnection.connect(
            self._postgres_dsn, autocommit=True
        )
        try:
            cursor = await conn.execute(
                """
                SELECT 1 FROM agent_thread_runs
                WHERE thread_id = %s AND generation = %s AND run_id = %s
                """,
                (lease.thread_id, lease.generation, lease.run_id),
            )
            return await cursor.fetchone() is not None
        finally:
            await conn.close()

    @asynccontextmanager
    async def run(
        self,
        thread_id: str,
        message_id: str | None,
    ) -> AsyncIterator[ThreadRunLease]:
        """Cancel the prior local owner, then acquire exclusive run ownership."""
        owner = asyncio.current_task()
        if owner is None:  # pragma: no cover - asyncio always supplies one here
            raise RuntimeError("ThreadRunCoordinator requires an asyncio task")
        lease = ThreadRunLease(
            coordinator=self,
            thread_id=str(thread_id),
            message_id=str(message_id or f"message-{uuid.uuid4().hex}"),
            run_id=f"agent-run-{uuid.uuid4().hex}",
        )
        active = _ActiveRun(lease=lease, task=owner)
        previous: _ActiveRun | None = None
        postgres_lock = None
        completed = False

        try:
            async with self._registry_lock:
                previous = self._active.get(lease.thread_id)
                self._active[lease.thread_id] = active
                if previous is not None and previous.task is not owner:
                    previous.lease.cancel_event.set()
                    previous.task.cancel()

            if previous is not None and previous.task is not owner:
                with suppress(asyncio.CancelledError):
                    await previous.task

            lease.generation = await self._claim_generation(lease)
            postgres_lock = await self._acquire_postgres_lock(lease)
            lease.postgres_connection = postgres_lock
            await lease.ensure_current()
            logger.info(
                "run_start thread=%s run=%s generation=%s message=%s",
                lease.thread_id,
                lease.run_id,
                lease.generation,
                lease.message_id,
            )
            yield lease
            completed = True
        finally:
            lease.cancel_event.set()
            await self._release_postgres_lock(
                lease,
                postgres_lock,
                status="complete" if completed else "cancelled",
            )
            async with self._registry_lock:
                if self._active.get(lease.thread_id) is active:
                    self._active.pop(lease.thread_id, None)
            logger.info(
                "run_end thread=%s run=%s generation=%s status=%s",
                lease.thread_id,
                lease.run_id,
                lease.generation,
                "complete" if completed else "cancelled",
            )


default_thread_run_coordinator = ThreadRunCoordinator()
