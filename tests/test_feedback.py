"""TDD — feedback endpoint: store run_id per thread, submit to LangSmith."""
from unittest.mock import MagicMock, patch

import pytest


def test_run_store_set_and_get():
    from tools.run_store import RunStore
    store = RunStore()
    store.set("thread_abc", "run-uuid-123")
    assert store.get("thread_abc") == "run-uuid-123"


def test_run_store_get_missing_returns_none():
    from tools.run_store import RunStore
    store = RunStore()
    assert store.get("nonexistent") is None


def test_run_store_overwrite_keeps_latest():
    from tools.run_store import RunStore
    store = RunStore()
    store.set("thread_abc", "run-uuid-1")
    store.set("thread_abc", "run-uuid-2")
    assert store.get("thread_abc") == "run-uuid-2"


def test_submit_feedback_calls_langsmith(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")

    mock_client = MagicMock()
    mock_class = MagicMock(return_value=mock_client)

    with patch("tools.feedback.Client", mock_class):
        from tools.feedback import submit_feedback
        submit_feedback(run_id="run-uuid-123", score=1, comment="great answer")

    mock_client.create_feedback.assert_called_once_with(
        "run-uuid-123",
        key="user_feedback",
        score=1,
        comment="great answer",
    )


def test_submit_feedback_negative_score(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")

    mock_client = MagicMock()
    mock_class = MagicMock(return_value=mock_client)

    with patch("tools.feedback.Client", mock_class):
        from tools.feedback import submit_feedback
        submit_feedback(run_id="run-uuid-456", score=-1)

    mock_client.create_feedback.assert_called_once_with(
        "run-uuid-456",
        key="user_feedback",
        score=-1,
        comment=None,
    )


def test_submit_feedback_no_api_key_does_nothing(monkeypatch):
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    mock_class = MagicMock()

    with patch("tools.feedback.Client", mock_class):
        from tools.feedback import submit_feedback
        submit_feedback(run_id="run-uuid-789", score=1)

    mock_class.assert_not_called()


def test_list_feedback_for_run_filters_by_run_id(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "fake-key")

    mock_feedback = MagicMock(id="fb-1", score=1, comment="great")
    mock_client = MagicMock()
    mock_client.list_feedback.return_value = iter([mock_feedback])

    with patch("tools.feedback.Client", return_value=mock_client):
        from tools.feedback import list_feedback_for_run
        result = list_feedback_for_run("run-uuid-123")

    assert result == [mock_feedback]
    mock_client.list_feedback.assert_called_once_with(
        run_ids=["run-uuid-123"],
        feedback_key=["user_feedback"],
        limit=10,
    )


@pytest.mark.asyncio
async def test_feedback_accepts_openwebui_payload_and_keeps_comment(tmp_path, monkeypatch):
    import serve as serve_module

    thread_id = serve_module._thread_id(
        [serve_module.Message(role="user", content="Bonjour")],
        chat_id="chat-123",
        session_id=None,
        metadata=None,
    )
    serve_module.default_run_store.set(thread_id, "run-uuid-999")
    feedback_log_dir = tmp_path / "feedback-logs"
    feedback_log_dir.mkdir()
    monkeypatch.setattr(serve_module, "FEEDBACK_LOGS_DIR", feedback_log_dir)

    mock_submit = MagicMock()
    monkeypatch.setattr(serve_module, "submit_feedback", mock_submit)

    req = serve_module.FeedbackRequest(
        type="rating",
        data={
            "rating": 1,
            "comment": "Great answer",
            "reason": "Helpful",
        },
        meta={
            "chat_id": "chat-123",
            "message_id": "msg-456",
        },
    )

    result = await serve_module.feedback(req)

    assert result == {"status": "ok", "run_id": "run-uuid-999"}
    mock_submit.assert_called_once_with(
        run_id="run-uuid-999",
        score=1,
        comment="Great answer\nReason: Helpful",
    )
    log_lines = (feedback_log_dir / "feedback_events.jsonl").read_text().strip().splitlines()
    assert any('"event": "lookup"' in line for line in log_lines)
    assert any('"event": "submitted"' in line for line in log_lines)


@pytest.mark.asyncio
async def test_feedback_prefers_message_id_over_thread_id(tmp_path, monkeypatch):
    from tools.run_store import RunStore
    import serve as serve_module

    monkeypatch.setattr(serve_module, "default_run_store", RunStore())
    feedback_log_dir = tmp_path / "feedback-logs"
    feedback_log_dir.mkdir()
    monkeypatch.setattr(serve_module, "FEEDBACK_LOGS_DIR", feedback_log_dir)

    thread_id = serve_module._thread_id(
        [serve_module.Message(role="user", content="Bonjour")],
        chat_id="chat-123",
        session_id=None,
        metadata=None,
    )
    serve_module.default_run_store.set(thread_id, "run-thread-old")
    serve_module.default_run_store.set_for_message("msg-456", "run-message-new")

    mock_submit = MagicMock()
    monkeypatch.setattr(serve_module, "submit_feedback", mock_submit)

    result = await serve_module.feedback(
        serve_module.FeedbackRequest(
            chat_id="chat-123",
            message_id="msg-456",
            score=1,
            comment="Great answer",
        )
    )

    assert result == {"status": "ok", "run_id": "run-message-new"}
    mock_submit.assert_called_once_with(
        run_id="run-message-new",
        score=1,
        comment="Great answer",
    )

    log_lines = (feedback_log_dir / "feedback_events.jsonl").read_text().strip().splitlines()
    lookup_lines = [line for line in log_lines if '"event": "lookup"' in line]
    submitted_lines = [line for line in log_lines if '"event": "submitted"' in line]
    assert lookup_lines and '"source": "message_id"' in lookup_lines[-1]
    assert submitted_lines and '"source": "message_id"' in submitted_lines[-1]


@pytest.mark.asyncio
async def test_feedback_tap_ping_is_logged(tmp_path, monkeypatch):
    import serve as serve_module

    feedback_log_dir = tmp_path / "feedback-logs"
    feedback_log_dir.mkdir()
    monkeypatch.setattr(serve_module, "FEEDBACK_LOGS_DIR", feedback_log_dir)

    result = await serve_module.feedback_tap_ping({"event": "tap_installed", "href": "http://localhost:3000"})

    assert result == {"status": "ok"}
    log_lines = (feedback_log_dir / "feedback_events.jsonl").read_text().strip().splitlines()
    assert any('"event": "tap_ping"' in line for line in log_lines)
    assert any('"tap_installed"' in line for line in log_lines)


def test_debug_openwebui_feedback_tap_route_serves_js():
    import serve as serve_module

    response = serve_module.debug_openwebui_feedback_tap()

    assert response.media_type == "application/javascript"
    assert response.path.name == "feedback_tap.js"


@pytest.mark.asyncio
async def test_stream_chat_completions_captures_run_id_for_feedback(monkeypatch):
    from tools.run_store import RunStore
    import serve as serve_module

    serve_module._known_threads.clear()
    monkeypatch.setattr(serve_module, "default_run_store", RunStore())
    monkeypatch.setattr(serve_module, "submit_feedback", MagicMock())
    monkeypatch.setattr(serve_module.default_store, "clear", lambda thread_id: None)
    monkeypatch.setattr(serve_module, "_log_turn", lambda *args, **kwargs: None)

    thread_id = serve_module._thread_id(
        [serve_module.Message(role="user", content="Bonjour")],
        chat_id="chat-123",
        session_id=None,
        metadata=None,
    )

    mock_msg = MagicMock()
    mock_msg.content = "réponse"
    mock_msg.tool_calls = []
    mock_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    mock_msg.response_metadata = {}

    run_id = "019eb2d0-ffff-7fff-bfff-aaaaaaaaaaaa"

    async def fake_astream(messages, config, stream_mode="updates"):
        for callback in config["callbacks"]:
            callback.on_chain_start(
                {},
                {},
                run_id=__import__("uuid").UUID(run_id),
                parent_run_id=None,
            )
        yield {"agent": {"messages": [mock_msg]}}

    mock_agent = MagicMock()
    mock_agent.astream = fake_astream
    monkeypatch.setattr(serve_module, "make_agent", lambda thread_id, user_id="anonymous": mock_agent)

    req = serve_module.ChatRequest(
        messages=[serve_module.Message(role="user", content="Bonjour")],
        stream=True,
    )

    mock_request = MagicMock()
    mock_request.headers = {}

    response = await serve_module.chat_completions(
        req,
        mock_request,
        x_openwebui_chat_id="chat-123",
        x_openwebui_message_id="msg-999",
    )

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)

    assert serve_module.default_run_store.get(thread_id) == run_id
    assert serve_module.default_run_store.get_for_message("msg-999") == run_id

    feedback_result = await serve_module.feedback(
        serve_module.FeedbackRequest(
            chat_id="chat-123",
            message_id="msg-999",
            score=1,
            comment="Great answer",
        )
    )

    assert feedback_result == {"status": "ok", "run_id": run_id}
    serve_module.submit_feedback.assert_called_once_with(
        run_id=run_id,
        score=1,
        comment="Great answer",
    )
