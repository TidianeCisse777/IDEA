"""TDD — identité de conversation Open WebUI → LangGraph/LangSmith."""

from types import SimpleNamespace

from langchain_core.messages import AIMessage


def test_conversation_key_prefers_openwebui_chat_id():
    from serve import _conversation_key

    key = _conversation_key(
        ["first message", "second message"],
        chat_id="chat-abc-123",
        session_id=None,
    )

    assert key == "chat-abc-123"


def test_conversation_key_falls_back_to_first_user_message():
    from serve import _conversation_key

    key = _conversation_key(
        ["premier message", "deuxième message"],
        chat_id=None,
        session_id=None,
    )

    assert key == "premier message"


def test_conversation_key_uses_session_id_when_chat_id_missing():
    from serve import _conversation_key

    key = _conversation_key(
        ["message"],
        chat_id=None,
        session_id="session-789",
    )

    assert key == "session-789"


def test_find_invalid_tool_history_cut_index_trims_orphan_tool_call():
    from agent import _find_invalid_tool_history_cut_index

    messages = [
        AIMessage(content="ok", id="ai-1"),
        AIMessage(
            content="",
            id="ai-2",
            tool_calls=[{"name": "query_amundsen_ctd", "args": {}, "id": "tc-1", "type": "tool_call"}],
        ),
    ]

    assert _find_invalid_tool_history_cut_index(messages) == 1


def test_repair_invalid_tool_history_removes_dangling_messages():
    from agent import repair_invalid_tool_history

    class FakeAgent:
        def __init__(self):
            self.messages = [
                AIMessage(content="ok", id="ai-1"),
                AIMessage(
                    content="",
                    id="ai-2",
                    tool_calls=[{"name": "query_amundsen_ctd", "args": {}, "id": "tc-1", "type": "tool_call"}],
                ),
            ]
            self.updated = None

        def get_state(self, config):
            return SimpleNamespace(values={"messages": self.messages})

        def update_state(self, config, values):
            self.updated = values
            return config

    fake = FakeAgent()
    repaired = repair_invalid_tool_history(fake, {"configurable": {"thread_id": "tid"}})

    assert repaired is True
    assert fake.updated is not None
    removal_ids = [msg.id for msg in fake.updated["messages"]]
    assert "ai-2" in removal_ids
