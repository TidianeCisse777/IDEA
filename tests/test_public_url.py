"""TDD — helpers d'URL publique partagés par les outils."""


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
