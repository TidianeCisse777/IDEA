from __future__ import annotations


def _load_tools(tags):
    from core.tool_registry import registry
    from core.tool_registry.tools import core_tools  # noqa: F401 - triggers registration
    from core.tool_registry.tools import station_tools  # noqa: F401 - triggers registration
    from core.tool_registry.tools import web_tools  # noqa: F401 - triggers registration

    code = registry.render(tags)
    ns = {}
    exec(code, ns)
    return ns


def test_web_search_does_not_forward_unsupported_reasoning_param(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "LLM_MODEL", "custom/web-model")
    ns = _load_tools({"web"})
    captured = {}

    class DummyResponse:
        output = []

    def fake_responses(**kwargs):
        captured.update(kwargs)
        return DummyResponse()

    ns["responses"] = fake_responses

    result = ns["web_search"]("recent sea level news")

    assert "reasoning" not in captured
    assert captured["model"] == "custom/web-model"
    assert result == {"content": None, "urls": []}


def test_get_station_info_does_not_forward_unsupported_reasoning_param(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "LLM_MODEL", "custom/station-model")
    ns = _load_tools({"station"})
    captured = {}

    class DummyResponse:
        output = []

    def fake_responses(**kwargs):
        captured.update(kwargs)
        return DummyResponse()

    ns["responses"] = fake_responses

    result = ns["get_station_info"]("Honolulu, HI")

    assert "reasoning" not in captured
    assert captured["model"] == "custom/station-model"
    assert result is None
