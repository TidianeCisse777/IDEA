"""TDD — Open WebUI feedback bridge: normalize and forward feedback records."""


def test_normalize_feedback_record_extracts_backend_payload():
    from openwebui.feedback_bridge import normalize_feedback_record

    record = {
        "type": "rating",
        "data": {
            "rating": -1,
            "comment": "Trop vague",
            "reason": "Manque la profondeur",
        },
        "meta": {
            "chat_id": "chat-123",
            "message_id": "msg-456",
        },
    }

    assert normalize_feedback_record(record) == {
        "chat_id": "chat-123",
        "score": -1,
        "comment": "Trop vague",
        "reason": "Manque la profondeur",
    }


def test_forward_feedback_record_posts_json_payload():
    from openwebui.feedback_bridge import forward_feedback_record

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"status":"ok","run_id":"run-1"}'

    def fake_opener(req, timeout=10.0):
        captured["url"] = req.full_url
        captured["body"] = req.data.decode("utf-8")
        captured["content_type"] = req.headers.get("Content-type")
        captured["timeout"] = timeout
        return FakeResponse()

    result = forward_feedback_record(
        {
            "data": {"rating": 1, "comment": "Great"},
            "meta": {"chat_id": "chat-abc"},
        },
        "http://localhost:8000",
        opener=fake_opener,
        timeout=3.0,
    )

    import json
    assert result == {"status": "ok", "run_id": "run-1"}
    assert captured["url"] == "http://localhost:8000/feedback"
    assert captured["content_type"] == "application/json"
    assert captured["timeout"] == 3.0
    assert json.loads(captured["body"]) == {"chat_id": "chat-abc", "score": 1, "comment": "Great"}


def test_sync_feedback_records_forwards_valid_entries_and_counts():
    from openwebui.feedback_bridge import sync_feedback_records

    forwarded = []

    def fake_forward(record, backend_base_url, *, timeout=10.0, opener=None):
        forwarded.append((record, backend_base_url, timeout))
        return {"status": "ok"}

    result = sync_feedback_records(
        [
            {
                "data": {"rating": 1, "comment": "Great"},
                "meta": {"chat_id": "chat-abc"},
            },
            {
                "data": {"comment": "Missing rating"},
                "meta": {"chat_id": "chat-def"},
            },
        ],
        "http://localhost:8000",
        forwarder=fake_forward,
        timeout=2.5,
    )

    assert result == {"processed": 2, "forwarded": 1, "skipped": 1}
    assert forwarded == [
        (
            {
                "data": {"rating": 1, "comment": "Great"},
                "meta": {"chat_id": "chat-abc"},
            },
            "http://localhost:8000",
            2.5,
        )
    ]
