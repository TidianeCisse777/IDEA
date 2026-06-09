"""TDD — identité de conversation Open WebUI → LangGraph/LangSmith."""


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
