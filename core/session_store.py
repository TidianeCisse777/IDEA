"""
SessionStore — abstraction layer over the Redis session backend.

Provides a SessionStore ABC and two concrete implementations:
- RedisSessionStore: production backend (wraps redis-py)
- InMemorySessionStore: test/dev backend (pure Python dict)

The module-level ``session_store`` singleton is the object imported by routers.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import redis
from abc import ABC, abstractmethod
from time import time
from uuid import uuid4


ARTIFACT_VERSION_PREFIXES = {
    "data_understanding": "du",
    "graph_context": "gc",
}


def _active_copepod_artifacts_are_consistent(
    active_data: dict | None, active_graph: dict | None
) -> bool:
    if active_data is None or active_graph is None:
        return False
    graph_payload = active_graph.get("payload") or {}
    return (
        graph_payload.get("data_understanding_version_id")
        == active_data.get("version_id")
    )


def _new_artifact_version(artifact_type: str, payload: dict) -> dict:
    prefix = ARTIFACT_VERSION_PREFIXES[artifact_type]
    return {
        "version_id": f"{prefix}-{uuid4().hex}",
        "artifact_type": artifact_type,
        "status": "draft",
        "created_at": time(),
        "activated_at": None,
        "payload": payload,
    }


class SessionStore(ABC):
    """Interface for session-scoped message and activity storage."""

    @abstractmethod
    def read_messages(self, session_key: str) -> list[dict] | None:
        """Return the stored message list for *session_key*, or None if absent."""
        ...

    @abstractmethod
    def write_messages(self, session_key: str, messages: list[dict]) -> None:
        """Persist *messages* for *session_key*, overwriting any previous value."""
        ...

    @abstractmethod
    def touch(self, session_key: str) -> None:
        """Record the current wall-clock time as the last-active timestamp."""
        ...

    @abstractmethod
    def get_last_active(self, session_key: str) -> float | None:
        """Return the last-active UNIX timestamp, or None if never touched."""
        ...

    @abstractmethod
    def evict(self, session_key: str) -> None:
        """Remove all stored data (messages + timestamp) for *session_key*."""
        ...

    @abstractmethod
    def all_session_keys(self) -> list[str]:
        """Return every session key that has a recorded last-active timestamp."""
        ...

    @abstractmethod
    def get_session_mode(self, session_key: str) -> str:
        """Return the current session mode ('plan' or 'analyse'). Defaults to 'plan'."""
        ...

    @abstractmethod
    def set_session_mode(self, session_key: str, mode: str) -> None:
        """Persist the session mode for session_key."""
        ...

    @abstractmethod
    def create_artifact_version(
        self, session_key: str, artifact_type: str, payload: dict
    ) -> dict:
        """Create and store a draft artifact version for session_key."""
        ...

    @abstractmethod
    def get_artifact_versions(self, session_key: str, artifact_type: str) -> list[dict]:
        """Return stored artifact versions for session_key and artifact_type."""
        ...

    @abstractmethod
    def get_active_artifact(self, session_key: str, artifact_type: str) -> dict | None:
        """Return the active artifact version, if any."""
        ...

    @abstractmethod
    def activate_artifact_version(
        self, session_key: str, artifact_type: str, version_id: str
    ) -> dict:
        """Activate one artifact version and supersede any prior active version."""
        ...

    @abstractmethod
    def has_active_copepod_plan_artifacts(self, session_key: str) -> bool:
        """Return whether required copepod plan artifacts are active."""
        ...


class RedisSessionStore(SessionStore):
    """Production implementation backed by a Redis server."""

    def __init__(self, host: str = "redis", port: int = 6379, db: int = 0):
        self._r = redis.Redis(host=host, port=port, db=db)

    def read_messages(self, session_key: str) -> list[dict] | None:
        raw = self._r.get(f"messages:{session_key}")
        return json.loads(raw) if raw else None

    def write_messages(self, session_key: str, messages: list[dict]) -> None:
        self._r.set(f"messages:{session_key}", json.dumps(messages))

    def touch(self, session_key: str) -> None:
        self._r.set(f"last_active:{session_key}", time())

    def get_last_active(self, session_key: str) -> float | None:
        raw = self._r.get(f"last_active:{session_key}")
        return float(raw) if raw else None

    def evict(self, session_key: str) -> None:
        keys = [
            f"messages:{session_key}",
            f"last_active:{session_key}",
            f"session_mode:{session_key}",
            *self._r.keys(f"artifacts:{session_key}:*"),
        ]
        self._r.delete(*keys)

    def all_session_keys(self) -> list[str]:
        keys = self._r.keys("last_active:*")
        return [k.decode().removeprefix("last_active:") for k in keys]

    def get_session_mode(self, session_key: str) -> str:
        raw = self._r.get(f"session_mode:{session_key}")
        return raw.decode() if raw else "plan"

    def set_session_mode(self, session_key: str, mode: str) -> None:
        self._r.set(f"session_mode:{session_key}", mode)

    def _artifact_key(self, session_key: str, artifact_type: str) -> str:
        return f"artifacts:{session_key}:{artifact_type}"

    def create_artifact_version(
        self, session_key: str, artifact_type: str, payload: dict
    ) -> dict:
        artifact = _new_artifact_version(artifact_type, payload)
        versions = self.get_artifact_versions(session_key, artifact_type)
        versions.append(artifact)
        self._r.set(self._artifact_key(session_key, artifact_type), json.dumps(versions))
        return artifact

    def get_artifact_versions(self, session_key: str, artifact_type: str) -> list[dict]:
        raw = self._r.get(self._artifact_key(session_key, artifact_type))
        return json.loads(raw) if raw else []

    def get_active_artifact(self, session_key: str, artifact_type: str) -> dict | None:
        for artifact in self.get_artifact_versions(session_key, artifact_type):
            if artifact["status"] == "active":
                return artifact
        return None

    def activate_artifact_version(
        self, session_key: str, artifact_type: str, version_id: str
    ) -> dict:
        versions = self.get_artifact_versions(session_key, artifact_type)
        if not any(artifact["version_id"] == version_id for artifact in versions):
            raise KeyError(version_id)
        selected = None
        activated_at = time()
        for artifact in versions:
            if artifact["status"] == "active":
                artifact["status"] = "superseded"
            if artifact["version_id"] == version_id:
                artifact["status"] = "active"
                artifact["activated_at"] = activated_at
                selected = artifact
        self._r.set(self._artifact_key(session_key, artifact_type), json.dumps(versions))
        return selected

    def has_active_copepod_plan_artifacts(self, session_key: str) -> bool:
        return _active_copepod_artifacts_are_consistent(
            self.get_active_artifact(session_key, "data_understanding"),
            self.get_active_artifact(session_key, "graph_context"),
        )


class InMemorySessionStore(SessionStore):
    """In-memory implementation for tests and local development (no Redis needed)."""

    def __init__(self):
        self._messages: dict[str, list[dict]] = {}
        self._timestamps: dict[str, float] = {}
        self._modes: dict[str, str] = {}
        self._artifacts: dict[tuple[str, str], list[dict]] = {}

    def read_messages(self, session_key: str) -> list[dict] | None:
        return self._messages.get(session_key)

    def write_messages(self, session_key: str, messages: list[dict]) -> None:
        self._messages[session_key] = messages

    def touch(self, session_key: str) -> None:
        self._timestamps[session_key] = time()

    def get_last_active(self, session_key: str) -> float | None:
        return self._timestamps.get(session_key)

    def evict(self, session_key: str) -> None:
        self._messages.pop(session_key, None)
        self._timestamps.pop(session_key, None)
        self._modes.pop(session_key, None)
        for key in list(self._artifacts):
            if key[0] == session_key:
                self._artifacts.pop(key, None)

    def all_session_keys(self) -> list[str]:
        return list(self._timestamps.keys())

    def get_session_mode(self, session_key: str) -> str:
        return self._modes.get(session_key, "plan")

    def set_session_mode(self, session_key: str, mode: str) -> None:
        self._modes[session_key] = mode

    def create_artifact_version(
        self, session_key: str, artifact_type: str, payload: dict
    ) -> dict:
        artifact = _new_artifact_version(artifact_type, payload)
        self._artifacts.setdefault((session_key, artifact_type), []).append(artifact)
        return artifact

    def get_artifact_versions(self, session_key: str, artifact_type: str) -> list[dict]:
        return self._artifacts.get((session_key, artifact_type), [])

    def get_active_artifact(self, session_key: str, artifact_type: str) -> dict | None:
        for artifact in self.get_artifact_versions(session_key, artifact_type):
            if artifact["status"] == "active":
                return artifact
        return None

    def activate_artifact_version(
        self, session_key: str, artifact_type: str, version_id: str
    ) -> dict:
        versions = self.get_artifact_versions(session_key, artifact_type)
        if not any(artifact["version_id"] == version_id for artifact in versions):
            raise KeyError(version_id)
        selected = None
        activated_at = time()
        for artifact in versions:
            if artifact["status"] == "active":
                artifact["status"] = "superseded"
            if artifact["version_id"] == version_id:
                artifact["status"] = "active"
                artifact["activated_at"] = activated_at
                selected = artifact
        return selected

    def has_active_copepod_plan_artifacts(self, session_key: str) -> bool:
        return _active_copepod_artifacts_are_consistent(
            self.get_active_artifact(session_key, "data_understanding"),
            self.get_active_artifact(session_key, "graph_context"),
        )


# Singleton — selection strategy:
#   REDIS_URL set        → Redis at that URL (Railway / any hosted env)
#   LOCAL_DEV env set    → Redis at host=redis (Docker Compose service name)
#   LOCAL_DEV not set    → InMemorySessionStore (bare local Python, no Docker)
_redis_url = os.getenv("REDIS_URL", "")
if _redis_url:
    _parsed = urllib.parse.urlparse(_redis_url)
    session_store: SessionStore = RedisSessionStore(
        host=_parsed.hostname or "redis",
        port=_parsed.port or 6379,
    )
elif os.getenv("LOCAL_DEV") is not None:
    session_store: SessionStore = RedisSessionStore()
else:
    session_store: SessionStore = InMemorySessionStore()
