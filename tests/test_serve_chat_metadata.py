"""TDD — propagation metadata Open WebUI vers l'agent LangChain."""

from unittest.mock import MagicMock, AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metadata", "accept_language", "expected"),
    [
        ({"locale": "en-CA"}, "fr-CA", "en"),
        (None, "en-US,en;q=0.9", "en"),
        (None, "de-DE", "fr"),
    ],
)
async def test_chat_completions_passes_user_language_to_stream(
    monkeypatch,
    metadata,
    accept_language,
    expected,
):
    import serve as serve_module

    mock_agent = MagicMock()
    mock_agent.aget_state = AsyncMock(
        return_value=MagicMock(values={"messages": []})
    )
    captured = {}

    async def empty_stream():
        if False:
            yield ""

    def fake_stream(*args, **kwargs):
        captured["language"] = kwargs["language"]
        return empty_stream()

    monkeypatch.setattr(
        serve_module,
        "make_agent",
        lambda thread_id, user_id="anonymous": mock_agent,
    )
    monkeypatch.setattr(serve_module, "_stream_agent_sse", fake_stream)
    request = MagicMock()
    request.headers = {"accept-language": accept_language}
    req = serve_module.ChatRequest(
        messages=[serve_module.Message(role="user", content="Hello")],
        stream=True,
        metadata=metadata,
    )

    await serve_module.chat_completions(
        req,
        request,
        x_openwebui_chat_id=None,
        x_openwebui_message_id=None,
    )

    assert captured["language"] == expected


@pytest.mark.asyncio
async def test_chat_completions_resumes_persisted_dataframe_after_restart(
    monkeypatch, tmp_path
):
    import pandas as pd
    import serve as serve_module
    from tools.session_store import SessionStore

    req = serve_module.ChatRequest(
        messages=[serve_module.Message(role="user", content="Continue l'analyse")],
        stream=False,
    )
    chat_id = "restart-chat-123"
    thread_id = serve_module._thread_id(
        req.messages,
        chat_id=chat_id,
        session_id=None,
        metadata=None,
    )
    store_dir = tmp_path / "sessions"
    before_restart = SessionStore(store_dir)
    dataframe = pd.DataFrame({"sample_id": [101], "depth": [12.5]})
    alias = f"{thread_id}:dataset:df_ecotaxa"
    before_restart.set(thread_id, dataframe, {"variable_name": "df"})
    before_restart.set(alias, dataframe, {"variable_name": "df_ecotaxa"})

    restarted_store = SessionStore(store_dir)

    mock_msg = MagicMock()
    mock_msg.content = "réponse"
    mock_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    mock_msg.response_metadata = {}
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_msg]})
    mock_agent.aget_state = AsyncMock(
        return_value=MagicMock(values={"messages": []})
    )

    monkeypatch.setattr(serve_module, "default_store", restarted_store)
    monkeypatch.setattr(
        serve_module,
        "make_agent",
        lambda thread_id, user_id="anonymous": mock_agent,
    )
    monkeypatch.setattr(serve_module, "_log_turn", lambda *args, **kwargs: None)
    request = MagicMock()
    request.headers = {}

    await serve_module.chat_completions(
        req,
        request,
        x_openwebui_chat_id=chat_id,
    )

    active = restarted_store.get(thread_id)
    derived = restarted_store.get(alias)
    assert active is not None and active["df"].equals(dataframe)
    assert derived is not None and derived["df"].equals(dataframe)


@pytest.mark.asyncio
async def test_generic_cast_map_request_reaches_react_agent(monkeypatch):
    """Only explicit EcoTaxa cast maps use the deterministic route."""
    import serve as serve_module

    mock_msg = MagicMock()
    mock_msg.content = "carte générée"
    mock_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    mock_msg.response_metadata = {}
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_msg]})

    monkeypatch.setattr(serve_module, "make_agent", lambda *args, **kwargs: mock_agent)
    monkeypatch.setattr(serve_module, "arepair_invalid_tool_history", AsyncMock())
    monkeypatch.setattr(serve_module, "_log_turn", lambda *args, **kwargs: None)
    request = MagicMock()
    request.headers = {}
    req = serve_module.ChatRequest(
        messages=[serve_module.Message(
            role="user",
            content="Affiche une carte des casts de mon fichier chargé.",
        )],
        stream=False,
    )

    await serve_module.chat_completions(
        req,
        request,
        x_openwebui_chat_id=None,
        x_openwebui_message_id=None,
    )

    mock_agent.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Affiche les échantillons de l’export sur une carte.",
        "Dans EcoTaxa, exporte les samples de la Mer de Beaufort.",
    ],
)
async def test_export_wording_reaches_react_agent_when_no_plan_is_pending(
    monkeypatch, message
):
    """References and new requests stay in the LLM's contextual workflow."""
    import serve as serve_module
    import tools.copepod_sources as sources_module

    class StoreWithLatestSelection:
        def get(self, key):
            if str(key).endswith(":ecotaxa_selection_latest"):
                return {"meta": {"sample_ids": [14622000039]}}
            return {"meta": {}}

    export_tool = MagicMock()
    export_tool.name = "export_ecotaxa_samples"
    export_tool.invoke.return_value = MagicMock(content="Plan d'export — 1 samples sur 1 projets")
    reply = MagicMock()
    reply.content = "réponse de l'agent"
    reply.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    reply.response_metadata = {}
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [reply]})

    monkeypatch.setattr(serve_module, "default_store", StoreWithLatestSelection())
    monkeypatch.setattr(sources_module, "make_source_tools", lambda thread_id: [export_tool])
    monkeypatch.setattr(serve_module, "make_agent", lambda *args, **kwargs: mock_agent)
    monkeypatch.setattr(serve_module, "arepair_invalid_tool_history", AsyncMock())
    monkeypatch.setattr(serve_module, "_log_turn", lambda *args, **kwargs: None)

    await serve_module.chat_completions(
        serve_module.ChatRequest(
            messages=[serve_module.Message(role="user", content=message)],
            stream=False,
        ),
        MagicMock(headers={}),
        x_openwebui_chat_id="export-context-chat",
        x_openwebui_message_id=None,
    )

    mock_agent.ainvoke.assert_awaited_once()
    export_tool.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_pending_export_confirmation_reaches_react_agent(monkeypatch):
    """Confirmation language is interpreted by the agent, not HTTP regexes."""
    import serve as serve_module
    import tools.copepod_sources as sources_module

    class StoreWithPendingExport:
        def get(self, key):
            return {
                "meta": {
                    "pending_ecotaxa_export_plan": {
                        "sample_ids": [14622000039],
                    }
                }
            }

    export_tool = MagicMock()
    export_tool.name = "export_ecotaxa_samples"
    export_tool.invoke.return_value = MagicMock(
        content="Table de campagne consolidée (3 lignes, 1 projets)"
    )
    reply = MagicMock()
    reply.content = "export confirmé"
    reply.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    reply.response_metadata = {}
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [reply]})
    monkeypatch.setattr(serve_module, "default_store", StoreWithPendingExport())
    monkeypatch.setattr(sources_module, "make_source_tools", lambda thread_id: [export_tool])
    monkeypatch.setattr(serve_module, "make_agent", lambda *args, **kwargs: mock_agent)
    monkeypatch.setattr(serve_module, "arepair_invalid_tool_history", AsyncMock())
    monkeypatch.setattr(serve_module, "_log_turn", lambda *args, **kwargs: None)

    await serve_module.chat_completions(
        serve_module.ChatRequest(
            messages=[serve_module.Message(role="user", content="Yes, I confirm the export.")],
            stream=False,
        ),
        MagicMock(headers={}),
        x_openwebui_chat_id="export-confirmation-chat",
        x_openwebui_message_id=None,
    )

    mock_agent.ainvoke.assert_awaited_once()
    export_tool.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_chat_completions_uses_openwebui_chat_id_as_stable_conversation_key(monkeypatch):
    import serve as serve_module

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

    mock_msg = MagicMock()
    mock_msg.content = "réponse"
    mock_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    mock_msg.response_metadata = {}

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_msg]})
    mock_agent.aget_state = AsyncMock(return_value=MagicMock(values={"messages": []}))

    monkeypatch.setattr(serve_module, "make_agent", lambda tid, user_id="anonymous": mock_agent)
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

    mock_msg = MagicMock()
    mock_msg.content = "réponse"
    mock_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    mock_msg.response_metadata = {}

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_msg]})
    mock_agent.aget_state = AsyncMock(return_value=MagicMock(values={"messages": []}))

    monkeypatch.setattr(serve_module, "make_agent", lambda tid, user_id="anonymous": mock_agent)
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
