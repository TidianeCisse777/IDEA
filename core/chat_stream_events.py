from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any


PLAN_READY_TAG = "[PLAN_READY]"

VALIDATE_PLAN_ACTION = {
    "start": True,
    "end": True,
    "role": "computer",
    "type": "action_button",
    "action": "validate_plan",
    "label": "Passer en Mode Analyse",
}


def chat_stream_events(
    interpreter_chunks: Iterable[Any],
    *,
    user_turns: int,
    session_mode: str | None,
) -> Iterator[Any]:
    """Transform interpreter chunks into UI stream events."""
    plan_ready_emitted = False
    message_buffers: dict[str, str] = {}

    for chunk in interpreter_chunks:
        # Drop raw LLM tool_call chunks that open-interpreter failed to execute.
        # Chunks may be dicts or Pydantic models — use getattr/get to handle both.
        _get = chunk.get if isinstance(chunk, dict) else lambda k, d=None: getattr(chunk, k, d)
        if _get("tool_calls") is not None and _get("type") is None:
            continue

        event = chunk

        if isinstance(chunk, dict) and chunk.get("type") == "message":
            role = chunk.get("role", "assistant")
            content = chunk.get("content", "")

            if isinstance(content, str):
                if chunk.get("start"):
                    message_buffers[role] = content
                else:
                    message_buffers[role] = message_buffers.get(role, "") + content

                if PLAN_READY_TAG in content and not plan_ready_emitted:
                    event = dict(chunk)
                    event["content"] = content.replace(PLAN_READY_TAG, "").rstrip()
                    plan_ready_emitted = True
                elif chunk.get("end") and not plan_ready_emitted:
                    if PLAN_READY_TAG in message_buffers.get(role, ""):
                        plan_ready_emitted = True
                        yield event
                        yield {"type": "strip_tail", "text": PLAN_READY_TAG}
                        message_buffers.pop(role, None)
                        continue

                if chunk.get("end"):
                    message_buffers.pop(role, None)

        yield event

    if plan_ready_emitted and user_turns >= 3 and session_mode != "analyse":
        yield dict(VALIDATE_PLAN_ACTION)
