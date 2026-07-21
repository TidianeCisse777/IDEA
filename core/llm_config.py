"""Shared provider connection settings for OpenAI-compatible backends."""

from __future__ import annotations

import os
from urllib.parse import urlparse


def chat_openai_connection_kwargs() -> dict[str, str]:
    """Select the credential that matches the configured provider endpoint."""
    kwargs: dict[str, str] = {}
    base_url = os.getenv("OPENAI_BASE_URL")
    endpoint_host = urlparse(base_url).hostname if base_url else None
    if endpoint_host == "api.openai.com":
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    else:
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return kwargs
