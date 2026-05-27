from __future__ import annotations

import base64
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.copepod_observability import _configure_local_langfuse_host


class LangfuseConfigurationError(RuntimeError):
    """Raised when the local Langfuse project keys do not match the configured env."""

    pass


def _langfuse_basic_auth_header(public_key: str, secret_key: str) -> str:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def validate_langfuse_configuration(*, timeout_seconds: float = 2.0) -> None:
    """Fail fast when Langfuse is enabled but the configured keys do not authenticate.

    This is a guardrail for local development and eval runs:
    - it keeps the configured host aligned with the local Docker host if needed;
    - it verifies that the current `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`
      actually authenticate against the running Langfuse instance.

    If Langfuse is disabled, this function is a no-op.
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        return

    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or ""
    if not host:
        return

    _configure_local_langfuse_host()
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or host

    request = Request(f"{host.rstrip('/')}/api/public/projects", method="GET")
    request.add_header("Authorization", _langfuse_basic_auth_header(public_key, secret_key))

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", response.getcode())
            if status != 200:
                raise LangfuseConfigurationError(
                    f"Langfuse responded with HTTP {status} for /api/public/projects. "
                    "Check that the configured keys belong to the project on this instance."
                )
    except HTTPError as exc:
        raise LangfuseConfigurationError(
            "Configured Langfuse keys do not authenticate against the running instance. "
            "Open Langfuse UI → Project Settings → API Keys and copy the current pair into .env."
        ) from exc
    except URLError as exc:
        raise LangfuseConfigurationError(
            f"Unable to reach Langfuse at {host}. Ensure the local container is running."
        ) from exc
