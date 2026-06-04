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


class SessionStore(ABC):
    """Interface for session-scoped message and activity storage."""

    @abstractmethod
    def read_messages(self, session_key: str) -> list[dict] | None: ...

    @abstractmethod
    def write_messages(self, session_key: str, messages: list[dict]) -> None: ...

    @abstractmethod
    def touch(self, session_key: str) -> None: ...

    @abstractmethod
    def get_last_active(self, session_key: str) -> float | None: ...

    @abstractmethod
    def evict(self, session_key: str) -> None: ...

    @abstractmethod
    def all_session_keys(self) -> list[str]: ...

    @abstractmethod
    def get_online_mode(self, session_key: str) -> bool: ...

    @abstractmethod
    def set_online_mode(self, session_key: str, enabled: bool) -> None: ...

    @abstractmethod
    def read_working_set(self, session_key: str) -> dict | None: ...

    @abstractmethod
    def write_working_set(self, session_key: str, working_set: dict) -> None: ...

    @abstractmethod
    def store_inspection_report(self, session_key: str, filename: str, report: str) -> None: ...

    @abstractmethod
    def read_inspection_report(self, session_key: str, filename: str) -> str | None: ...

    @abstractmethod
    def list_inspection_reports(self, session_key: str) -> list[str]: ...

    @abstractmethod
    def store_inspection_data(self, session_key: str, filename: str, data: dict) -> None: ...

    @abstractmethod
    def read_inspection_data(self, session_key: str, filename: str) -> dict | None: ...


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
        self._r.delete(
            f"messages:{session_key}",
            f"last_active:{session_key}",
            f"online_mode:{session_key}",
            f"working_set:{session_key}",
            f"inspection_reports:{session_key}",
        )

    def all_session_keys(self) -> list[str]:
        keys = self._r.keys("last_active:*")
        return [k.decode().removeprefix("last_active:") for k in keys]

    def get_online_mode(self, session_key: str) -> bool:
        raw = self._r.get(f"online_mode:{session_key}")
        return raw.decode() == "1" if raw else False

    def set_online_mode(self, session_key: str, enabled: bool) -> None:
        self._r.set(f"online_mode:{session_key}", "1" if enabled else "0")

    def read_working_set(self, session_key: str) -> dict | None:
        raw = self._r.get(f"working_set:{session_key}")
        return json.loads(raw) if raw else None

    def write_working_set(self, session_key: str, working_set: dict) -> None:
        self._r.set(f"working_set:{session_key}", json.dumps(working_set))

    def store_inspection_report(self, session_key: str, filename: str, report: str) -> None:
        self._r.hset(f"inspection_reports:{session_key}", filename, report)

    def read_inspection_report(self, session_key: str, filename: str) -> str | None:
        raw = self._r.hget(f"inspection_reports:{session_key}", filename)
        return raw.decode() if raw else None

    def list_inspection_reports(self, session_key: str) -> list[str]:
        keys = self._r.hkeys(f"inspection_reports:{session_key}")
        return [k.decode() for k in keys]

    def store_inspection_data(self, session_key: str, filename: str, data: dict) -> None:
        self._r.hset(f"inspection_data:{session_key}", filename, json.dumps(data, default=str))

    def read_inspection_data(self, session_key: str, filename: str) -> dict | None:
        raw = self._r.hget(f"inspection_data:{session_key}", filename)
        return json.loads(raw) if raw else None


class InMemorySessionStore(SessionStore):
    """In-memory implementation for tests and local development (no Redis needed)."""

    def __init__(self):
        self._messages: dict[str, list[dict]] = {}
        self._timestamps: dict[str, float] = {}
        self._online_modes: dict[str, bool] = {}
        self._working_sets: dict[str, dict] = {}
        self._inspection_reports: dict[str, dict[str, str]] = {}
        self._inspection_data: dict[str, dict[str, dict]] = {}

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
        self._online_modes.pop(session_key, None)
        self._working_sets.pop(session_key, None)
        self._inspection_reports.pop(session_key, None)
        self._inspection_data.pop(session_key, None)

    def all_session_keys(self) -> list[str]:
        return list(self._timestamps.keys())

    def get_online_mode(self, session_key: str) -> bool:
        return self._online_modes.get(session_key, False)

    def set_online_mode(self, session_key: str, enabled: bool) -> None:
        self._online_modes[session_key] = bool(enabled)

    def read_working_set(self, session_key: str) -> dict | None:
        return self._working_sets.get(session_key)

    def write_working_set(self, session_key: str, working_set: dict) -> None:
        self._working_sets[session_key] = working_set

    def store_inspection_report(self, session_key: str, filename: str, report: str) -> None:
        self._inspection_reports.setdefault(session_key, {})[filename] = report

    def read_inspection_report(self, session_key: str, filename: str) -> str | None:
        return self._inspection_reports.get(session_key, {}).get(filename)

    def list_inspection_reports(self, session_key: str) -> list[str]:
        return list(self._inspection_reports.get(session_key, {}).keys())

    def store_inspection_data(self, session_key: str, filename: str, data: dict) -> None:
        self._inspection_data.setdefault(session_key, {})[filename] = data

    def read_inspection_data(self, session_key: str, filename: str) -> dict | None:
        return self._inspection_data.get(session_key, {}).get(filename)


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
