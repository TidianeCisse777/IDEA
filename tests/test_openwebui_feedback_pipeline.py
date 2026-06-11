"""TDD — Open WebUI feedback sync pipeline to LangSmith."""


def test_sync_openwebui_feedback_export_skips_seen_and_persists_new_ids(tmp_path):
    from openwebui.feedback_pipeline import sync_openwebui_feedback_export

    state_path = tmp_path / "synced.json"
    state_path.write_text('["fb-1"]', encoding="utf-8")

    forwarded = []

    def fake_forward(record, backend_base_url, *, timeout=10.0, opener=None):
        forwarded.append((record["id"], backend_base_url, timeout))
        return {"status": "ok"}

    summary = sync_openwebui_feedback_export(
        [
            {
                "id": "fb-1",
                "data": {"rating": 1, "comment": "old"},
                "meta": {"chat_id": "chat-1"},
            },
            {
                "id": "fb-2",
                "data": {"rating": -1, "comment": "new"},
                "meta": {"chat_id": "chat-2"},
            },
        ],
        "http://localhost:8000",
        state_path=state_path,
        forwarder=fake_forward,
        timeout=2.0,
    )

    assert summary == {"processed": 2, "forwarded": 1, "skipped": 1, "seen_total": 2}
    assert forwarded == [("fb-2", "http://localhost:8000", 2.0)]
    assert state_path.read_text(encoding="utf-8") == '["fb-1", "fb-2"]'


def test_fetch_openwebui_feedback_export_uses_bearer_token():
    from openwebui.feedback_pipeline import fetch_openwebui_feedback_export

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'[{"id":"fb-1"}]'

    def fake_opener(req, timeout=10.0):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        captured["timeout"] = timeout
        return FakeResponse()

    result = fetch_openwebui_feedback_export(
        "http://openwebui.local",
        auth_token="token-123",
        opener=fake_opener,
        timeout=4.0,
    )

    assert result == [{"id": "fb-1"}]
    assert captured == {
        "url": "http://openwebui.local/api/v1/evaluations/feedbacks/all",
        "auth": "Bearer token-123",
        "timeout": 4.0,
    }
