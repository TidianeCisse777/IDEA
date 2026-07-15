from core.llm_config import chat_openai_connection_kwargs


def test_openrouter_key_takes_precedence(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")

    assert chat_openai_connection_kwargs() == {
        "api_key": "openrouter-key",
        "base_url": "https://openrouter.ai/api/v1",
    }


def test_openai_key_remains_the_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    assert chat_openai_connection_kwargs() == {"api_key": "openai-key"}
