import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import RateLimitError


def _rate_limit_error(retry_after: str = "7") -> RateLimitError:
    request = httpx.Request("POST", "https://provider.invalid/chat")
    response = httpx.Response(
        429,
        headers={"retry-after": retry_after},
        request=request,
        json={"error": {"message": "rate limited"}},
    )
    return RateLimitError("rate limited", response=response, body=response.json())


@pytest.mark.asyncio
async def test_non_streaming_provider_rate_limit_returns_structured_429(monkeypatch):
    import serve as serve_module

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(side_effect=_rate_limit_error("9"))
    mock_agent.aget_state = AsyncMock(return_value=MagicMock(values={"messages": []}))
    monkeypatch.setattr(serve_module, "make_agent", lambda *args, **kwargs: mock_agent)

    request = MagicMock()
    request.headers = {}
    request.body = AsyncMock(return_value=b"{}")
    req = serve_module.ChatRequest(
        messages=[serve_module.Message(role="user", content="Analyse")],
        stream=False,
    )

    response = await serve_module.chat_completions(
        req,
        request,
        x_openwebui_chat_id=None,
        x_openwebui_message_id=None,
        x_openwebui_user_id=None,
        x_openwebui_user_name=None,
        x_openwebui_user_email=None,
        x_openwebui_user_role=None,
    )

    assert response.status_code == 429
    assert json.loads(response.body)["error"] == {
        "code": "provider_rate_limit",
        "retryable": True,
    }
    assert response.headers["retry-after"] == "9"


@pytest.mark.asyncio
async def test_streaming_provider_rate_limit_emits_structured_error_without_turn_log(monkeypatch):
    import serve as serve_module

    async def failing_stream(*args, **kwargs):
        raise _rate_limit_error("4")
        yield  # pragma: no cover

    agent = MagicMock()
    agent.astream = failing_stream
    logged = []
    monkeypatch.setattr(serve_module, "_log_turn", lambda *args, **kwargs: logged.append(args))

    chunks = [
        chunk
        async for chunk in serve_module._stream_agent_sse(
            agent, {}, {}, "rate-limit-thread"
        )
    ]
    payload = "".join(chunks)

    assert '"code": "provider_rate_limit"' in payload
    assert '"retryable": true' in payload
    assert '"retry_after": 4' in payload
    assert "[Erreur" not in payload
    assert logged == []
