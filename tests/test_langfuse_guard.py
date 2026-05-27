from __future__ import annotations

from urllib.error import HTTPError

import pytest

from core.langfuse_guard import LangfuseConfigurationError, validate_langfuse_configuration


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return 200


def test_validate_langfuse_configuration_accepts_matching_keys(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout=0):
        requests.append((request, timeout))
        assert request.full_url == "http://localhost:3001/api/public/projects"
        auth = request.headers.get("Authorization")
        assert auth is not None
        assert auth.startswith("Basic ")
        return _FakeResponse()

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3001")
    monkeypatch.setattr("core.langfuse_guard.urlopen", fake_urlopen)

    validate_langfuse_configuration()

    assert requests


def test_validate_langfuse_configuration_raises_when_keys_do_not_authenticate(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3001")

    def fake_urlopen(request, timeout=0):
        raise HTTPError(request.full_url, 401, "Unauthorized", hdrs=None, fp=None)

    monkeypatch.setattr("core.langfuse_guard.urlopen", fake_urlopen)

    with pytest.raises(LangfuseConfigurationError, match="do not authenticate"):
        validate_langfuse_configuration()
