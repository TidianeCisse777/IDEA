"""Shared provider connection settings for OpenAI-compatible backends."""

from __future__ import annotations

import os


def chat_openai_connection_kwargs() -> dict[str, str]:
    """Prefer an OpenRouter key while preserving direct OpenAI fallback."""
    kwargs: dict[str, str] = {}
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return kwargs
