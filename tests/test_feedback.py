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
