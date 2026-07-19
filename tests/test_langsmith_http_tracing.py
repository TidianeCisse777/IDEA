"""The HTTP entrypoint must attach the LangSmith tracer to every agent turn."""
from unittest.mock import MagicMock, patch


def test_http_request_callbacks_include_langsmith_tracer_when_enabled():
    import serve

    tracer = MagicMock()
    with patch("serve._make_tracer", return_value=tracer) as make_tracer:
        callbacks = serve._request_callbacks(
            "thread-12345678",
            chat_id="chat-1",
            user_id="student-1",
            user_email="student@ulaval.ca",
        )

    make_tracer.assert_called_once_with(
        "thread-12345678", user_id="student-1", user_email="student@ulaval.ca"
    )
    assert tracer in callbacks
    assert any(type(callback).__name__ == "_RunIdCaptureCallback" for callback in callbacks)
