from __future__ import annotations

from dataclasses import dataclass, field

COPEPOD_OBSERVABILITY_CODE = r'''
# ── IDEA Copepod runtime observability ───────────────────────────────────────
# This wrapper is best-effort: it must never change tool return values or raise.
import functools as _idea_functools
import os as _idea_os
import time as _idea_time

_IDEA_SENSITIVE_KEYS = {"auth_token", "token", "password", "secret", "api_key", "key"}


def _idea_compact_value(value, max_length=4000):
    try:
        import json as _idea_json
        text = _idea_json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = repr(value)
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    try:
        return _idea_json.loads(text)
    except Exception:
        return text


def _idea_redact_mapping(mapping):
    redacted = {}
    for key, value in dict(mapping).items():
        key_text = str(key).lower()
        if any(sensitive in key_text for sensitive in _IDEA_SENSITIVE_KEYS):
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = _idea_compact_value(value)
    return redacted


def _idea_observe_session_key(args, kwargs):
    if kwargs.get("session_key"):
        return kwargs.get("session_key")
    if args and isinstance(args[0], str) and args[0].count(":") >= 2:
        return args[0]
    return _idea_os.getenv("IDEA_RUNTIME_SESSION_KEY")


def _idea_trace_tool_call(tool_name, args, kwargs, output=None, error=None, elapsed_ms=None):
    try:
        from core.copepod_observability import trace_copepod_tool_call
        payload = {
            "args": [_idea_compact_value(arg) for arg in args],
            "kwargs": _idea_redact_mapping(kwargs),
        }
        result = {"error": str(error)} if error is not None else _idea_compact_value(output)
        trace_copepod_tool_call(
            tool_name,
            session_key=_idea_observe_session_key(args, kwargs),
            input=payload,
            output=result,
            metadata={
                "elapsed_ms": elapsed_ms,
                "round": _idea_os.getenv("IDEA_RUNTIME_ROUND"),
            },
        )
    except Exception:
        return


def _idea_wrap_tool(fn, tool_name):
    if getattr(fn, "__idea_traced__", False):
        return fn

    @_idea_functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        start = _idea_time.perf_counter()
        try:
            output = fn(*args, **kwargs)
            elapsed_ms = round((_idea_time.perf_counter() - start) * 1000, 2)
            _idea_trace_tool_call(tool_name, args, kwargs, output=output, elapsed_ms=elapsed_ms)
            return output
        except Exception as exc:
            elapsed_ms = round((_idea_time.perf_counter() - start) * 1000, 2)
            _idea_trace_tool_call(tool_name, args, kwargs, error=exc, elapsed_ms=elapsed_ms)
            raise

    _wrapped.__idea_traced__ = True
    return _wrapped


for _idea_tool_name in [
    "inspect_file",
    "infer_column_roles",
    "describe_column",
    "summarize_understanding",
    "create_data_understanding_draft",
    "activate_data_understanding",
    "create_graph_context_draft",
    "activate_graph_context",
    "get_active_data_understanding",
    "get_active_graph_context",
    "query_copepod_knowledge_base",
]:
    if _idea_tool_name in globals() and callable(globals()[_idea_tool_name]):
        globals()[_idea_tool_name] = _idea_wrap_tool(globals()[_idea_tool_name], _idea_tool_name)
'''


@dataclass
class Tool:
    name: str
    tags: frozenset
    code: str  # source Python (sera exécuté via computer.run)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def render(self, tags: set | None = None) -> str:
        """Retourne le code Python de tous les tools matchant les tags."""
        tools = list(self._tools.values())
        if tags:
            tools = [t for t in tools if t.tags & tags]
        rendered = "\n\n".join(t.code for t in tools)
        if tags and any(str(tag).startswith("copepod_") for tag in tags):
            return f"{rendered}\n\n{COPEPOD_OBSERVABILITY_CODE}"
        return rendered


registry = ToolRegistry()
