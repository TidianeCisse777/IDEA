from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any, Iterable, Iterator

from core.copepod_observability import _configure_local_langfuse_host, should_enable_langfuse


def _safe_json(data: Any, max_length: int = 12000) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except Exception:
        text = str(data)
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def _event_value(event: Any, key: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


def _is_error_content(content: str) -> bool:
    lowered = content.lower()
    return (
        "traceback" in lowered
        or "error:" in lowered
        or "exception" in lowered
        or "failed" in lowered
        or "échec" in lowered
    )


class ChatRuntimeTracer:
    """Best-effort Langfuse tracing for a streamed Open Interpreter chat turn.

    This class is intentionally defensive: every public method swallows tracing
    failures so observability can never change runtime behavior.
    """

    def __init__(
        self,
        trace: Any = None,
        *,
        metadata: dict[str, Any] | None = None,
        round_index: int = 1,
    ):
        self.trace = trace
        self.metadata = metadata or {}
        self.round_index = round_index
        self.metadata.setdefault("round", round_index)
        self._buffers: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        self._closed = False

    @classmethod
    def from_env(
        cls,
        *,
        session_key: str,
        user_id: str,
        agent_type: str,
        model: str,
        user_input: dict[str, Any] | None = None,
        round_index: int = 1,
    ) -> "ChatRuntimeTracer":
        if not should_enable_langfuse():
            return cls()

        metadata = {
            "session_key": session_key,
            "agent_type": agent_type,
            "model": model,
            "round": round_index,
        }
        try:
            from langfuse import Langfuse

            _configure_local_langfuse_host()
            lf = Langfuse()
            trace = lf.trace(
                name="idea-chat-runtime",
                user_id=str(user_id),
                session_id=session_key,
                input=user_input or {},
                metadata=metadata,
                tags=["runtime", "chat", agent_type],
            )
            return cls(trace, metadata=metadata, round_index=round_index)
        except Exception:
            return cls(metadata=metadata, round_index=round_index)

    @property
    def enabled(self) -> bool:
        return self.trace is not None

    def observe_stream(self, events: Iterable[Any]) -> Iterator[Any]:
        try:
            for event in events:
                self.record_event(event)
                yield event
        finally:
            self.close()

    def record_mcp_tool_run(self, run: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            connection = run.get("connection")
            tool = run.get("tool") or {}
            arguments = run.get("arguments") or {}
            result = run.get("result")
            name = tool.get("name") or "unknown"
            self._span(
                f"round-{self.round_index}/mcp/{name}",
                input={
                    "connection": getattr(connection, "name", None),
                    "tool": tool,
                    "arguments": arguments,
                },
                output=result,
                metadata={"observation_type": "mcp_tool_call"},
            )
        except Exception:
            return

    def record_route_error(self, error: str) -> None:
        if not self.enabled:
            return
        try:
            self._span(
                f"round-{self.round_index}/runtime/error",
                input={},
                output={"error": error},
                metadata={"observation_type": "runtime_error"},
            )
        except Exception:
            return

    def record_event(self, event: Any) -> None:
        if not self.enabled:
            return
        try:
            if not isinstance(event, dict):
                self._span(
                    f"round-{self.round_index}/runtime/raw_event",
                    input={},
                    output={"event": str(event)},
                    metadata={"observation_type": "raw_event"},
                )
                return

            if event.get("error") is not None:
                self.record_route_error(str(event["error"]))
                return

            event_type = str(event.get("type") or "message")
            role = str(event.get("role") or "unknown")
            fmt = str(event.get("format") or "")
            content = event.get("content")

            if event_type == "action_button":
                self._span(
                    f"round-{self.round_index}/ui/action_button",
                    input={},
                    output=event,
                    metadata={"observation_type": "ui_action"},
                )
                return

            if event_type == "strip_tail":
                self._span(
                    f"round-{self.round_index}/ui/strip_tail",
                    input={},
                    output=event,
                    metadata={"observation_type": "ui_event"},
                )
                return

            if event_type == "message" and fmt == "tool_status":
                self._span(
                    f"round-{self.round_index}/runtime/tool_status",
                    input={},
                    output=event,
                    metadata={"observation_type": "tool_status"},
                )
                return

            if event_type in {"message", "code", "console"} and isinstance(content, str):
                key = (role, event_type, fmt)
                if event.get("start"):
                    self._buffers[key] = []
                self._buffers[key].append(content)
                if event.get("end"):
                    joined = "".join(self._buffers.pop(key, []))
                    self._record_buffer(role, event_type, fmt, joined)
                return

            self._span(
                f"round-{self.round_index}/runtime/{event_type}",
                input={},
                output=event,
                metadata={"observation_type": event_type},
            )
        except Exception:
            return

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self.enabled:
            return
        try:
            for (role, event_type, fmt), parts in list(self._buffers.items()):
                self._record_buffer(role, event_type, fmt, "".join(parts))
            self._buffers.clear()
            if hasattr(self.trace, "update"):
                self.trace.update(output={"status": "completed"})
            # Avoid blocking teardown on network flushes.
            # Eval runners can still opt into an explicit flush if they need it.
            if os.getenv("IDEA_LANFUSE_FLUSH_ON_CLOSE") == "1":
                langfuse_client = getattr(self.trace, "client", None)
                if langfuse_client is not None and hasattr(langfuse_client, "flush"):
                    langfuse_client.flush()
        except Exception:
            return

    def _record_buffer(self, role: str, event_type: str, fmt: str, content: str) -> None:
        if not content:
            return
        observation_type = self._observation_type(role, event_type, fmt, content)
        name = f"round-{self.round_index}/runtime/{observation_type}"
        payload = {
            "role": role,
            "type": event_type,
            "format": fmt or None,
            "content": content,
        }
        if observation_type == "assistant_message" and hasattr(self.trace, "generation"):
            try:
                self.trace.generation(
                    name=f"round-{self.round_index}",
                    input={},
                    output=content,
                    metadata={**self.metadata, "observation_type": observation_type},
                )
                return
            except Exception:
                pass
        self._span(
            name,
            input={},
            output=payload,
            metadata={"observation_type": observation_type},
        )

    def _observation_type(self, role: str, event_type: str, fmt: str, content: str) -> str:
        if event_type == "code":
            return "generated_code"
        if event_type == "console" or fmt in {"console", "execution", "active_line"}:
            return "code_output_error" if _is_error_content(content) else "code_output"
        if role == "assistant":
            return "assistant_message"
        if role == "computer":
            return "computer_message_error" if _is_error_content(content) else "computer_message"
        return event_type

    def _span(
        self,
        name: str,
        *,
        input: Any,
        output: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            span = self.trace.span(
                name=name,
                input=input,
                output=output if isinstance(output, (dict, list, str, int, float, bool, type(None))) else _safe_json(output),
                metadata={**self.metadata, **(metadata or {})},
            )
            if hasattr(span, "end"):
                span.end()
        except Exception:
            return
