"""Shared provider connection settings for OpenAI-compatible backends."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool


_OPENAI_MODEL_VERSION = re.compile(
    r"(?:^|/)gpt-(\d+)\.(\d+)(?:-|$)", re.IGNORECASE
)


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


def cached_tokens_from_metadata(
    response_metadata: object,
    usage_metadata: object,
) -> int:
    """Read cached-token usage from partial OpenAI/OpenRouter metadata safely."""

    response = response_metadata if isinstance(response_metadata, Mapping) else {}
    usage = usage_metadata if isinstance(usage_metadata, Mapping) else {}
    token_usage = response.get("token_usage")
    token_usage = token_usage if isinstance(token_usage, Mapping) else {}
    prompt_details = token_usage.get("prompt_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, Mapping) else {}
    input_details = usage.get("input_token_details")
    input_details = input_details if isinstance(input_details, Mapping) else {}
    value: Any = prompt_details.get("cached_tokens") or input_details.get(
        "cache_read", 0
    )
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def cache_creation_tokens_from_metadata(
    response_metadata: object,
    usage_metadata: object,
) -> int:
    """Read GPT-5.6 cache-write usage across OpenAI metadata variants."""

    response = response_metadata if isinstance(response_metadata, Mapping) else {}
    usage = usage_metadata if isinstance(usage_metadata, Mapping) else {}
    token_usage = response.get("token_usage")
    token_usage = token_usage if isinstance(token_usage, Mapping) else {}
    prompt_details = token_usage.get("prompt_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, Mapping) else {}
    input_details = usage.get("input_token_details")
    input_details = input_details if isinstance(input_details, Mapping) else {}
    value: Any = (
        prompt_details.get("cache_write_tokens")
        or prompt_details.get("cache_creation_tokens")
        or input_details.get("cache_creation")
        or input_details.get("cache_write")
        or input_details.get("cache_write_tokens")
        or 0
    )
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def explicit_prompt_cache_token_breakdown(
    *,
    enabled: bool,
    system_prompt_tokens: int,
    tool_schema_tokens: int,
    dynamic_context_tokens: int,
    history_tokens: int,
    current_turn_tool_tokens: int,
    estimated_request_tokens: int,
) -> dict[str, int | float | bool]:
    """Describe the explicit-cache boundary without counting tools as cached.

    The explicit breakpoint is attached to the permanent ``SystemMessage``.
    Tool schemas are part of the versioned cache key, but they are sent after
    that breakpoint and therefore belong to the variable suffix for accounting
    purposes.  Keeping those two concepts separate avoids reporting an
    optimistic cacheable-prefix share.
    """

    system = max(0, int(system_prompt_tokens))
    tools = max(0, int(tool_schema_tokens))
    dynamic = max(0, int(dynamic_context_tokens))
    history = max(0, int(history_tokens))
    current_tools = max(0, int(current_turn_tool_tokens))
    total = max(0, int(estimated_request_tokens))
    breakpoint = system if enabled else 0
    suffix = max(0, total - breakpoint)
    return {
        "prompt_cache_explicit_enabled": bool(enabled),
        "estimated_system_prompt_tokens": system,
        "estimated_cacheable_system_prefix_tokens": breakpoint,
        "estimated_tool_schema_suffix_tokens": tools,
        "estimated_dynamic_context_suffix_tokens": dynamic,
        "estimated_history_suffix_tokens": history,
        "estimated_current_turn_tool_tokens": current_tools,
        "estimated_variable_suffix_tokens": suffix,
        "estimated_cacheable_prefix_share": (
            breakpoint / total if total else 0.0
        ),
        "estimated_variable_suffix_share": suffix / total if total else 0.0,
    }


def with_explicit_prompt_cache_breakpoint(
    message: SystemMessage,
) -> SystemMessage:
    """Mark the permanent system instructions as the reusable GPT-5.6 prefix."""

    if not isinstance(message.content, str):
        return message
    return message.model_copy(
        update={
            "content": [
                {
                    "type": "input_text",
                    "text": message.content,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }
            ]
        }
    )


def openai_prompt_cache_key(
    *,
    model: str,
    system_prompt: str,
    tools: Sequence[Any],
) -> str:
    """Fingerprint one exact, privacy-safe provider prompt contract."""

    tool_schemas = [
        dict(item) if isinstance(item, Mapping) else convert_to_openai_tool(item)
        for item in tools
    ]
    contract = {
        "version": 1,
        "model": model,
        "system_prompt": system_prompt,
        "tools": tool_schemas,
    }
    encoded = json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:24]
    return f"idea-copepod-v1-{digest}"


def openai_prompt_cache_settings(
    *,
    model: str,
    system_prompt: str,
    tools: Sequence[Any],
) -> dict[str, Any]:
    """Build explicit-cache settings for one stable prompt/tool contract."""

    key = openai_prompt_cache_key(
        model=model,
        system_prompt=system_prompt,
        tools=tools,
    )
    return {
        "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        "model_kwargs": {"prompt_cache_key": key},
    }


def openai_explicit_prompt_cache_enabled(
    *,
    model: str,
    base_url: str | None,
    use_responses_api: bool,
) -> bool:
    """Gate GPT-5.6 cache-only fields away from unsupported providers/models."""

    if not use_responses_api:
        return False
    host = urlparse(base_url).hostname if base_url else "api.openai.com"
    if host != "api.openai.com":
        return False
    match = _OPENAI_MODEL_VERSION.search(str(model or "").strip())
    if match is None:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (5, 6)
