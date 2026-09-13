"""Langfuse-managed system prompt with a safe local fallback."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def load_system_prompt(local_prompt: str) -> tuple[str, dict[str, Any] | None]:
    """Load the production prompt from Langfuse when enabled.

    The local prompt remains the fallback so a Langfuse outage cannot prevent
    the agent from serving requests.
    """
    enabled = os.getenv("IDEA_LANGFUSE_PROMPT_ENABLED", "true").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return local_prompt, None

    name = os.getenv("IDEA_LANGFUSE_PROMPT_NAME", "neolab-terminal-agent-system")
    label = os.getenv("IDEA_LANGFUSE_PROMPT_LABEL", "production")
    fetch_timeout = int(os.getenv("IDEA_LANGFUSE_PROMPT_FETCH_TIMEOUT_SECONDS", "3"))
    try:
        from langfuse import Langfuse

        prompt = Langfuse().get_prompt(
            name,
            label=label,
            type="text",
            fallback=local_prompt,
            max_retries=0,
            fetch_timeout_seconds=fetch_timeout,
        )
        compiled = prompt.compile()
        if not isinstance(compiled, str) or not compiled.strip():
            raise ValueError("Langfuse returned an empty system prompt")
        return compiled, {
            "name": name,
            "label": label,
            "version": getattr(prompt, "version", None),
        }
    except Exception as exc:  # pragma: no cover - depends on remote service
        logger.warning("Using local system prompt; Langfuse lookup failed: %s", exc)
        return local_prompt, None
