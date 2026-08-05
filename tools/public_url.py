"""Helpers for public-facing URLs used in tool outputs."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
from typing import Iterator, Protocol
from urllib.parse import urlsplit


class _RequestLike(Protocol):
    """Small request boundary needed to derive a public origin."""

    headers: object
    url: object


_request_origin: ContextVar[str | None] = ContextVar(
    "copepod_request_public_origin", default=None
)
_SAFE_HOST = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?|"
    r"\[[0-9A-Fa-f:.]+\])(?::[0-9]{1,5})?$"
)
_INTERNAL_AGENT_HOSTS = frozenset({"copepod-agent", "copepod_agent"})
_DEFAULT_RUNTIME_ORIGIN_FILE = "data/public_origin.txt"


def _first_header_value(request: _RequestLike, name: str) -> str:
    value = getattr(request.headers, "get")(name, "")
    return str(value).split(",", 1)[0].strip()


def _safe_host(value: str) -> str | None:
    """Return a host[:port] only when it cannot alter the generated URL."""
    return value if value and _SAFE_HOST.fullmatch(value) else None


def _is_internal_agent_host(host: str) -> bool:
    """Whether ``host`` is Docker-only and therefore not browser-visible."""
    hostname = host.removeprefix("[").split("]", 1)[0].split(":", 1)[0].lower()
    return hostname in _INTERNAL_AGENT_HOSTS


def _valid_public_origin(value: str) -> str | None:
    """Validate a complete public origin read from local runtime state."""
    candidate = value.strip().rstrip("/")
    if not candidate:
        return None
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not _safe_host(parsed.netloc)
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _runtime_public_origin() -> str | None:
    """Return the current tunnel origin when ``start.sh`` has published one.

    Quick-tunnel hostnames change at every launch.  Reading this tiny file for
    each generated URL lets a containerized or pre-existing local agent use
    the current public hostname without a restart.
    """
    path = os.getenv("SERVE_PUBLIC_ORIGIN_FILE", _DEFAULT_RUNTIME_ORIGIN_FILE)
    try:
        with open(path, encoding="utf-8") as origin_file:
            return _valid_public_origin(origin_file.readline())
    except OSError:
        return None


def _configured_origin() -> str:
    return (os.getenv("SERVE_BASE_URL") or "http://localhost:8000").rstrip("/")


def request_public_origin(request: _RequestLike) -> str:
    """Derive the browser-facing origin for one HTTP request.

    Cloudflare and reverse proxies provide ``X-Forwarded-*``.  Those values
    are preferred only if the host has a safe host[:port] form; otherwise the
    actual HTTP request stays the authoritative fallback.
    """
    forwarded_host = _safe_host(_first_header_value(request, "x-forwarded-host"))
    forwarded_proto = _first_header_value(request, "x-forwarded-proto").lower()
    if forwarded_host and forwarded_proto in {"http", "https"}:
        return f"{forwarded_proto}://{forwarded_host}"

    host = _safe_host(_first_header_value(request, "host"))
    scheme = str(getattr(request.url, "scheme", "http")).lower()
    if host and not _is_internal_agent_host(host) and scheme in {"http", "https"}:
        return f"{scheme}://{host}"
    return _runtime_public_origin() or _configured_origin()


@contextmanager
def activate_request_origin(origin: str) -> Iterator[None]:
    """Make an origin available to graph/download tools during one request."""
    token = _request_origin.set(origin.rstrip("/"))
    try:
        yield
    finally:
        _request_origin.reset(token)


def serve_base_url() -> str:
    """Return request, current-tunnel, then configured/default API origin."""
    active_origin = _request_origin.get()
    if active_origin:
        return active_origin
    return _runtime_public_origin() or _configured_origin()


def download_url(filename: str) -> str:
    """Return the public download URL for a generated file."""
    return f"{serve_base_url()}/downloads/{filename.lstrip('/')}"


def graph_url(filename: str) -> str:
    """Return the public graph URL for a generated image."""
    return f"{serve_base_url()}/graphs/{filename.lstrip('/')}"
