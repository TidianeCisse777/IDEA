"""TDD — helpers d'URL publique partagés par les outils."""

from fastapi import Request


def _request(*headers: tuple[bytes, bytes], scheme: str = "http") -> Request:
    return Request(
        {"type": "http", "scheme": scheme, "path": "/", "headers": list(headers)}
    )


def test_graph_url_uses_serve_base_url(monkeypatch):
    from tools.public_url import graph_url

    monkeypatch.setenv("SERVE_BASE_URL", "http://example.org:9000")

    assert graph_url("abc123.png") == "http://example.org:9000/graphs/abc123.png"


def test_graph_url_defaults_when_serve_base_url_is_empty(monkeypatch):
    from tools.public_url import graph_url

    monkeypatch.setenv("SERVE_BASE_URL", "")

    assert graph_url("abc123.png") == "http://localhost:8000/graphs/abc123.png"


def test_download_url_uses_serve_base_url(monkeypatch):
    from tools.public_url import download_url

    monkeypatch.setenv("SERVE_BASE_URL", "http://example.org:9000")

    assert download_url("sample.tsv") == "http://example.org:9000/downloads/sample.tsv"


def test_request_origin_overrides_stale_serve_base_url_with_forwarded_proxy(monkeypatch):
    """A fresh proxy host must win over an expired tunnel configured at startup."""
    from tools.public_url import activate_request_origin, graph_url, request_public_origin

    monkeypatch.setenv("SERVE_BASE_URL", "https://expired.trycloudflare.com")
    request = _request(
        (b"host", b"copepod_agent:8000"),
        (b"x-forwarded-host", b"fresh.trycloudflare.com"),
        (b"x-forwarded-proto", b"https"),
    )

    with activate_request_origin(request_public_origin(request)):
        assert graph_url("map.png") == "https://fresh.trycloudflare.com/graphs/map.png"
        assert graph_url("other.png") == "https://fresh.trycloudflare.com/graphs/other.png"


def test_internal_docker_host_falls_back_to_configured_public_origin(monkeypatch):
    """Open WebUI reaches the agent by Docker DNS, not a browser-visible host."""
    from tools.public_url import activate_request_origin, graph_url, request_public_origin

    monkeypatch.setenv("SERVE_BASE_URL", "http://localhost:8000")
    request = _request((b"host", b"copepod-agent:8000"))

    with activate_request_origin(request_public_origin(request)):
        assert graph_url("map.png") == "http://localhost:8000/graphs/map.png"


def test_request_origin_rejects_malformed_forwarded_host(monkeypatch):
    """Forwarded host injection must fall back to the actual request host."""
    from tools.public_url import activate_request_origin, graph_url, request_public_origin

    monkeypatch.setenv("SERVE_BASE_URL", "")
    request = _request(
        (b"host", b"agent.example.test"),
        (b"x-forwarded-host", b"bad.example/path"),
        (b"x-forwarded-proto", b"https"),
        scheme="http",
    )

    with activate_request_origin(request_public_origin(request)):
        assert graph_url("map.png") == "http://agent.example.test/graphs/map.png"


def test_request_origin_does_not_leak_to_the_next_call(monkeypatch):
    """A request-scoped origin is reset once its response is complete."""
    from tools.public_url import activate_request_origin, graph_url, request_public_origin

    monkeypatch.setenv("SERVE_BASE_URL", "")
    request = _request((b"host", b"first.example.test"), scheme="https")

    with activate_request_origin(request_public_origin(request)):
        assert graph_url("map.png") == "https://first.example.test/graphs/map.png"
    assert graph_url("map.png") == "http://localhost:8000/graphs/map.png"
