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

    assert key == "anonymous:chat-abc-123"


def test_conversation_key_generates_uuid_when_no_stable_id():
    from serve import _conversation_key
    import re

    # No chat_id/session_id → ephemeral UUID to avoid thread collisions
    key1 = _conversation_key(["yo"], chat_id=None, session_id=None)
    key2 = _conversation_key(["yo"], chat_id=None, session_id=None)

    assert re.match(r"[0-9a-f-]{36}", key1)
    # Each call produces a different UUID — no collision between conversations
    assert key1 != key2


def test_conversation_key_uses_session_id_when_chat_id_missing():
    from serve import _conversation_key

    key = _conversation_key(
        ["message"],
        chat_id=None,
        session_id="session-789",
    )

    assert key == "anonymous:session-789"


def test_conversation_key_includes_user_id():
    from serve import _conversation_key

    key_alice = _conversation_key(
        ["message"],
        chat_id="chat-abc",
        session_id=None,
        user_id="user-alice",
    )
    key_bob = _conversation_key(
        ["message"],
        chat_id="chat-abc",
        session_id=None,
        user_id="user-bob",
    )

    assert key_alice != key_bob


def test_two_users_same_chat_id_get_different_thread_ids():
    from serve import _thread_id, Message

    messages = [Message(role="user", content="Bonjour")]
    tid_alice = _thread_id(messages, chat_id="chat-shared", user_id="user-alice")
    tid_bob = _thread_id(messages, chat_id="chat-shared", user_id="user-bob")

    assert tid_alice != tid_bob


def test_thread_id_defaults_to_anonymous_when_no_user_header():
    from serve import _thread_id, Message

    messages = [Message(role="user", content="Bonjour")]
    tid_no_header = _thread_id(messages, chat_id="chat-xyz")
    tid_anonymous = _thread_id(messages, chat_id="chat-xyz", user_id="anonymous")

    assert tid_no_header == tid_anonymous


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
