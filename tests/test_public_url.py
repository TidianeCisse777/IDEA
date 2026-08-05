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


def test_internal_docker_host_uses_current_cloudflare_origin_file(monkeypatch, tmp_path):
    """An internal Open WebUI request must still emit browser-visible links."""
    from tools.public_url import (
        activate_request_origin,
        download_url,
        graph_url,
        request_public_origin,
    )

    origin_file = tmp_path / "public_origin.txt"
    origin_file.write_text("https://current.trycloudflare.com\n", encoding="utf-8")
    monkeypatch.setenv("SERVE_PUBLIC_ORIGIN_FILE", str(origin_file))
    monkeypatch.setenv("SERVE_BASE_URL", "http://localhost:8000")
    request = _request((b"host", b"copepod-agent:8000"))

    with activate_request_origin(request_public_origin(request)):
        assert graph_url("map.png") == "https://current.trycloudflare.com/graphs/map.png"
        assert (
            download_url("export.tsv")
            == "https://current.trycloudflare.com/downloads/export.tsv"
        )


def test_forwarded_cloudflare_origin_wins_over_runtime_origin_file(monkeypatch, tmp_path):
    """The current browser request is newer than the startup tunnel state."""
    from tools.public_url import activate_request_origin, graph_url, request_public_origin

    origin_file = tmp_path / "public_origin.txt"
    origin_file.write_text("https://startup.trycloudflare.com\n", encoding="utf-8")
    monkeypatch.setenv("SERVE_PUBLIC_ORIGIN_FILE", str(origin_file))
    request = _request(
        (b"host", b"copepod-agent:8000"),
        (b"x-forwarded-host", b"request.trycloudflare.com"),
        (b"x-forwarded-proto", b"https"),
    )

    with activate_request_origin(request_public_origin(request)):
        assert graph_url("map.png") == "https://request.trycloudflare.com/graphs/map.png"


def test_invalid_runtime_origin_file_is_ignored(monkeypatch, tmp_path):
    """A malformed file cannot turn generated links into arbitrary URLs."""
    from tools.public_url import graph_url

    origin_file = tmp_path / "public_origin.txt"
    origin_file.write_text("javascript:alert(1)\n", encoding="utf-8")
    monkeypatch.setenv("SERVE_PUBLIC_ORIGIN_FILE", str(origin_file))
    monkeypatch.setenv("SERVE_BASE_URL", "https://configured.example.test")

    assert graph_url("map.png") == "https://configured.example.test/graphs/map.png"


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
