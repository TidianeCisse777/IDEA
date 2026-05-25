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
        self._r.delete(f"messages:{session_key}", f"last_active:{session_key}")

    def all_session_keys(self) -> list[str]:
        keys = self._r.keys("last_active:*")
        return [k.decode().removeprefix("last_active:") for k in keys]

    def get_session_mode(self, session_key: str) -> str:
        raw = self._r.get(f"session_mode:{session_key}")
        return raw.decode() if raw else "plan"

    def set_session_mode(self, session_key: str, mode: str) -> None:
        self._r.set(f"session_mode:{session_key}", mode)


class InMemorySessionStore(SessionStore):
    """In-memory implementation for tests and local development (no Redis needed)."""

    def __init__(self):
        self._messages: dict[str, list[dict]] = {}
        self._timestamps: dict[str, float] = {}
        self._modes: dict[str, str] = {}

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

    def all_session_keys(self) -> list[str]:
        return list(self._timestamps.keys())

    def get_session_mode(self, session_key: str) -> str:
        return self._modes.get(session_key, "plan")

    def set_session_mode(self, session_key: str, mode: str) -> None:
        self._modes[session_key] = mode


# Singleton — Railway injects REDIS_URL; local dev defaults to host=redis.
_redis_url = os.getenv("REDIS_URL", "")
if _redis_url:
    _parsed = urllib.parse.urlparse(_redis_url)
    session_store: SessionStore = RedisSessionStore(
        host=_parsed.hostname or "redis",
        port=_parsed.port or 6379,
    )
else:
    session_store: SessionStore = RedisSessionStore()
