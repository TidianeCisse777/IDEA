from __future__ import annotations

from core.chat_stream_events import chat_stream_events


def test_single_chunk_plan_ready_strips_tag_and_emits_button_after_three_user_turns():
    chunks = [
        {
            "start": True,
            "end": True,
            "role": "assistant",
            "type": "message",
            "content": "Le plan est valide. [PLAN_READY]",
        }
    ]

    events = list(chat_stream_events(chunks, user_turns=3, session_mode="plan"))

    assert events == [
        {
            "start": True,
            "end": True,
            "role": "assistant",
            "type": "message",
            "content": "Le plan est valide.",
        },
        {
            "start": True,
            "end": True,
            "role": "computer",
            "type": "action_button",
            "action": "validate_plan",
            "label": "Passer en Mode Analyse",
        },
    ]


def test_split_plan_ready_tag_reconstructed_without_visible_fragment():
    # Tag split across two chunks: "[PLA" held back, "[PLAN_READY]" assembled on next chunk.
    chunks = [
        {"start": True, "role": "assistant", "type": "message", "content": "Le plan est valide. [PLA"},
        {"end": True, "role": "assistant", "type": "message", "content": "N_READY]"},
    ]

    events = list(chat_stream_events(chunks, user_turns=3, session_mode="plan"))

    # First chunk: partial tag prefix held back, safe content emitted without "[PLA".
    assert events[0] == {"start": True, "role": "assistant", "type": "message", "content": "Le plan est valide. "}
    # Second chunk: held "[PLA" + "N_READY]" = "[PLAN_READY]" reconstructed and stripped.
    assert events[1] == {"end": True, "role": "assistant", "type": "message", "content": ""}
    # No strip_tail event — tag was stripped in-flight, not retroactively.
    assert not any(e.get("type") == "strip_tail" for e in events if isinstance(e, dict))
    # Button still emitted.
    assert events[-1]["type"] == "action_button"


def test_plan_ready_does_not_emit_button_before_three_user_turns():
    chunks = [
        {
            "start": True,
            "end": True,
            "role": "assistant",
            "type": "message",
            "content": "Le plan est valide. [PLAN_READY]",
        }
    ]

    events = list(chat_stream_events(chunks, user_turns=2, session_mode="plan"))

    assert events == [
        {
            "start": True,
            "end": True,
            "role": "assistant",
            "type": "message",
            "content": "Le plan est valide.",
        }
    ]


def test_plan_ready_does_not_emit_button_when_session_already_in_analysis():
    chunks = [
        {
            "start": True,
            "end": True,
            "role": "assistant",
            "type": "message",
            "content": "Le plan est valide. [PLAN_READY]",
        }
    ]

    events = list(chat_stream_events(chunks, user_turns=3, session_mode="analyse"))

    assert events == [
        {
            "start": True,
            "end": True,
            "role": "assistant",
            "type": "message",
            "content": "Le plan est valide.",
        }
    ]


def test_chunks_without_plan_ready_pass_through_unchanged():
    text_chunk = {"role": "assistant", "type": "message", "content": "Bonjour"}
    non_message_chunk = {"role": "computer", "type": "tool_status", "content": "done"}
    raw_chunk = "raw event"

    events = list(chat_stream_events([text_chunk, non_message_chunk, raw_chunk], user_turns=3, session_mode="plan"))

    assert events == [text_chunk, non_message_chunk, raw_chunk]
