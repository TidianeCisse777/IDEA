"""TDD — polling loop: fetch Open WebUI feedbacks and forward to LangSmith."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── openwebui.feedback_pipeline ───────────────────────────────────────────────

def test_sync_skips_already_seen_ids(tmp_path):
    from openwebui.feedback_pipeline import sync_openwebui_feedback_export

    state = tmp_path / "seen.json"
    state.write_text(json.dumps(["fb-1"]))

    records = [
        {"id": "fb-1", "data": {"rating": 1}, "meta": {"chat_id": "c1"}},
        {"id": "fb-2", "data": {"rating": -1}, "meta": {"chat_id": "c2"}},
    ]
    forwarded_ids = []

    def fake_forwarder(record, url, **kw):
        forwarded_ids.append(record["id"])
        return {"status": "ok"}

    result = sync_openwebui_feedback_export(
        records,
        backend_base_url="http://localhost:8000",
        state_path=state,
        forwarder=fake_forwarder,
    )

    assert result["forwarded"] == 1
    assert result["skipped"] == 1
    assert forwarded_ids == ["fb-2"]
    seen = json.loads(state.read_text())
    assert "fb-1" in seen and "fb-2" in seen


def test_sync_skips_records_missing_required_fields(tmp_path):
    from openwebui.feedback_pipeline import sync_openwebui_feedback_export

    state = tmp_path / "seen.json"
    records = [
        {"id": "fb-1", "data": {}, "meta": {}},  # no rating, no chat_id
    ]
    forwarded = []

    def fake_forwarder(record, url, **kw):
        forwarded.append(record)
        return {"status": "ok"}

    result = sync_openwebui_feedback_export(
        records,
        backend_base_url="http://localhost:8000",
        state_path=state,
        forwarder=fake_forwarder,
    )

    assert result["forwarded"] == 0
    assert result["skipped"] == 1
    assert forwarded == []


def test_fetch_openwebui_feedback_export_parses_list(tmp_path):
    from openwebui.feedback_pipeline import fetch_openwebui_feedback_export

    payload = json.dumps([{"id": "fb-1"}, {"id": "fb-2"}]).encode()

    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = payload

    def fake_opener(req, timeout=10):
        return mock_response

    result = fetch_openwebui_feedback_export(
        "http://localhost:3000",
        auth_token="test-token",
        opener=fake_opener,
    )

    assert result == [{"id": "fb-1"}, {"id": "fb-2"}]


def test_fetch_openwebui_feedback_export_unwraps_data_key(tmp_path):
    from openwebui.feedback_pipeline import fetch_openwebui_feedback_export

    payload = json.dumps({"data": [{"id": "fb-3"}]}).encode()

    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = payload

    def fake_opener(req, timeout=10):
        return mock_response

    result = fetch_openwebui_feedback_export("http://localhost:3000", opener=fake_opener)

    assert result == [{"id": "fb-3"}]


# ── serve.py background polling ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_openwebui_feedbacks_calls_sync(tmp_path, monkeypatch):
    import serve as serve_module

    records = [{"id": "fb-10", "data": {"rating": 1}, "meta": {"chat_id": "c1"}}]
    fetched = []
    synced = []

    def fake_fetch(url, **kw):
        fetched.append(url)
        return records

    def fake_sync(recs, backend_url, *, state_path, **kw):
        synced.append((recs, backend_url))
        return {"forwarded": 1, "skipped": 0, "processed": 1, "seen_total": 1}

    monkeypatch.setenv("OPENWEBUI_URL", "http://localhost:3000")
    monkeypatch.setenv("OPENWEBUI_ADMIN_TOKEN", "admin-secret")
    monkeypatch.setattr(serve_module, "_owui_fetch", fake_fetch)
    monkeypatch.setattr(serve_module, "_owui_sync", fake_sync)

    await serve_module._poll_openwebui_feedbacks_once(state_path=tmp_path / "seen.json")

    assert fetched == ["http://localhost:3000"]
    assert synced[0][0] == records


@pytest.mark.asyncio
async def test_poll_skips_when_no_url_configured(tmp_path, monkeypatch):
    import serve as serve_module

    monkeypatch.delenv("OPENWEBUI_URL", raising=False)
    fetched = []

    def fake_fetch(url, **kw):
        fetched.append(url)
        return []

    monkeypatch.setattr(serve_module, "_owui_fetch", fake_fetch)

    await serve_module._poll_openwebui_feedbacks_once(state_path=tmp_path / "seen.json")

    assert fetched == []
