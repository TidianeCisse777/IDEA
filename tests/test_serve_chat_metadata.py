"""TDD — propagation metadata Open WebUI vers l'agent LangChain."""

from unittest.mock import MagicMock, AsyncMock

import pytest


@pytest.mark.asyncio
async def test_chat_completions_uses_openwebui_chat_id_as_stable_conversation_key(monkeypatch):
    import serve as serve_module

    serve_module._known_threads.clear()

    mock_msg = MagicMock()
    mock_msg.content = "réponse"
    mock_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    mock_msg.response_metadata = {}

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_msg]})
    mock_agent.aget_state = AsyncMock(return_value=MagicMock(values={"messages": []}))

    captured = {}

    def fake_make_agent(thread_id: str, user_id: str = "anonymous"):
        captured["thread_id"] = thread_id
        captured["user_id"] = user_id
        return mock_agent

    monkeypatch.setattr(serve_module, "make_agent", fake_make_agent)
    monkeypatch.setattr(serve_module.default_store, "clear", lambda thread_id: None)
    monkeypatch.setattr(serve_module, "_log_turn", lambda *args, **kwargs: None)

    req = serve_module.ChatRequest(
        messages=[serve_module.Message(role="user", content="Bonjour")],
        stream=False,
    )

    mock_request = MagicMock()
    mock_request.headers = {}

    result = await serve_module.chat_completions(
        req,
        mock_request,
        x_openwebui_chat_id="chat-123",
        x_openwebui_message_id="msg-999",
    )

    assert result["choices"][0]["message"]["content"] == "réponse"
    assert captured["thread_id"] == serve_module._thread_id(
        req.messages,
        chat_id="chat-123",
        session_id=None,
        metadata=None,
    )

    call_config = mock_agent.ainvoke.call_args.kwargs["config"]
    assert call_config["metadata"]["conversation_id"] == "chat-123"
    assert call_config["metadata"]["message_id"] == "msg-999"
    assert call_config["metadata"]["conversation_key"] == "anonymous:chat-123"


@pytest.mark.asyncio
async def test_chat_completions_uses_metadata_message_id_when_header_missing(monkeypatch):
    import serve as serve_module

    serve_module._known_threads.clear()

    mock_msg = MagicMock()
    mock_msg.content = "réponse"
    mock_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    mock_msg.response_metadata = {}

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_msg]})
    mock_agent.aget_state = AsyncMock(return_value=MagicMock(values={"messages": []}))

    captured = {}

    def fake_make_agent(thread_id: str, user_id: str = "anonymous"):
        captured["thread_id"] = thread_id
        captured["user_id"] = user_id
        return mock_agent

    monkeypatch.setattr(serve_module, "make_agent", fake_make_agent)
    monkeypatch.setattr(serve_module.default_store, "clear", lambda thread_id: None)
    monkeypatch.setattr(serve_module, "_log_turn", lambda *args, **kwargs: None)

    req = serve_module.ChatRequest(
        messages=[serve_module.Message(role="user", content="Bonjour")],
        stream=False,
        metadata={"message_id": "msg-body-123"},
    )

    mock_request = MagicMock()
    mock_request.headers = {}

    result = await serve_module.chat_completions(
        req,
        mock_request,
        x_openwebui_chat_id="chat-123",
        x_openwebui_message_id=None,
    )

    assert result["choices"][0]["message"]["content"] == "réponse"
    assert captured["thread_id"] == serve_module._thread_id(
        req.messages,
        chat_id="chat-123",
        session_id=None,
        metadata={"message_id": "msg-body-123"},
    )

    call_config = mock_agent.ainvoke.call_args.kwargs["config"]
    assert call_config["metadata"]["conversation_id"] == "chat-123"
    assert call_config["metadata"]["message_id"] == "msg-body-123"
    assert call_config["metadata"]["conversation_key"] == "anonymous:chat-123"


@pytest.mark.asyncio
async def test_chat_completions_propagates_user_headers_to_metadata(monkeypatch):
    import serve as serve_module

    serve_module._known_threads.clear()

    mock_msg = MagicMock()
    mock_msg.content = "réponse"
    mock_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    mock_msg.response_metadata = {}

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_msg]})
    mock_agent.aget_state = AsyncMock(return_value=MagicMock(values={"messages": []}))

    monkeypatch.setattr(serve_module, "make_agent", lambda tid, user_id="anonymous": mock_agent)
    monkeypatch.setattr(serve_module.default_store, "clear", lambda tid: None)
    monkeypatch.setattr(serve_module, "_log_turn", lambda *a, **kw: None)

    req = serve_module.ChatRequest(
        messages=[serve_module.Message(role="user", content="Bonjour")],
        stream=False,
    )
    mock_request = MagicMock()
    mock_request.headers = {}

    await serve_module.chat_completions(
        req,
        mock_request,
        x_openwebui_chat_id="chat-456",
        x_openwebui_message_id=None,
        x_openwebui_user_id="user-alice",
        x_openwebui_user_name="Alice",
        x_openwebui_user_email="alice@ulaval.ca",
        x_openwebui_user_role="user",
    )

    call_config = mock_agent.ainvoke.call_args.kwargs["config"]
    assert call_config["metadata"]["user_id"] == "user-alice"
    assert call_config["metadata"]["user_name"] == "Alice"
    assert call_config["metadata"]["user_email"] == "alice@ulaval.ca"
    assert call_config["metadata"]["user_role"] == "user"


@pytest.mark.asyncio
async def test_chat_completions_uses_anonymous_when_no_user_headers(monkeypatch):
    import serve as serve_module

    serve_module._known_threads.clear()

    mock_msg = MagicMock()
    mock_msg.content = "réponse"
    mock_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    mock_msg.response_metadata = {}

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_msg]})
    mock_agent.aget_state = AsyncMock(return_value=MagicMock(values={"messages": []}))

    monkeypatch.setattr(serve_module, "make_agent", lambda tid, user_id="anonymous": mock_agent)
    monkeypatch.setattr(serve_module.default_store, "clear", lambda tid: None)
    monkeypatch.setattr(serve_module, "_log_turn", lambda *a, **kw: None)

    req = serve_module.ChatRequest(
        messages=[serve_module.Message(role="user", content="Bonjour")],
        stream=False,
    )
    mock_request = MagicMock()
    mock_request.headers = {}

    await serve_module.chat_completions(
        req,
        mock_request,
        x_openwebui_chat_id="chat-789",
        x_openwebui_message_id=None,
    )

    call_config = mock_agent.ainvoke.call_args.kwargs["config"]
    assert call_config["metadata"]["user_id"] == "anonymous"
