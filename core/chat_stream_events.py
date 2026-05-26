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
    plan_ready_allowed: bool = True,
) -> Iterator[Any]:
    """Transform interpreter chunks into UI stream events."""
    plan_ready_emitted = False
    message_buffers: dict[str, str] = {}
    # Partial PLAN_READY_TAG prefix withheld from the previous chunk to prevent
    # visible tag fragments when the tag is split across multiple stream tokens.
    held: dict[str, str] = {}

    for chunk in interpreter_chunks:
        # Drop raw LLM tool_call chunks that open-interpreter failed to execute.
        # Chunks may be dicts or Pydantic models — use getattr/get to handle both.
        _get = chunk.get if isinstance(chunk, dict) else lambda k, d=None: getattr(chunk, k, d)
        if _get("tool_calls") is not None and _get("type") is None:
            continue

        event = chunk

        if isinstance(chunk, dict) and chunk.get("type") == "message":
            role = chunk.get("role", "assistant")
            raw_content = chunk.get("content", "")

            if isinstance(raw_content, str):
                if chunk.get("start"):
                    held.pop(role, None)
                    content = raw_content
                    message_buffers[role] = content
                else:
                    held_prefix = held.pop(role, "")
                    content = held_prefix + raw_content
                    # Buffer tracks raw_content only — held was already buffered by the
                    # chunk that produced it.
                    message_buffers[role] = message_buffers.get(role, "") + raw_content
                    if held_prefix:
                        event = dict(chunk)
                        event["content"] = content

                if PLAN_READY_TAG in content and not plan_ready_emitted:
                    if event is chunk:
                        event = dict(chunk)
                    event["content"] = content.replace(PLAN_READY_TAG, "").rstrip()
                    plan_ready_emitted = True
                elif chunk.get("end") and not plan_ready_emitted:
                    if PLAN_READY_TAG in message_buffers.get(role, ""):
                        plan_ready_emitted = True
                        yield event
                        yield {"type": "strip_tail", "text": PLAN_READY_TAG}
                        message_buffers.pop(role, None)
                        held.pop(role, None)
                        continue
                elif not plan_ready_emitted and not chunk.get("end"):
                    for prefix_len in range(len(PLAN_READY_TAG) - 1, 0, -1):
                        if content.endswith(PLAN_READY_TAG[:prefix_len]):
                            held[role] = content[-prefix_len:]
                            if event is chunk:
                                event = dict(chunk)
                            event["content"] = content[:-prefix_len]
                            break

                if chunk.get("end"):
                    message_buffers.pop(role, None)
                    held.pop(role, None)

        yield event

    if (
        plan_ready_emitted
        and plan_ready_allowed
        and user_turns >= 3
        and session_mode != "analyse"
    ):
        yield dict(VALIDATE_PLAN_ACTION)
