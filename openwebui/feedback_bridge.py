"""Normalize Open WebUI feedback records and forward them to the backend."""
from __future__ import annotations

import json
from typing import Any
from urllib import request as urllib_request


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_feedback_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Return the backend payload expected by `POST /feedback`.

    The helper accepts the feedback record shape used by Open WebUI exports and
    trims it down to the fields our backend consumes.
    """
    if not isinstance(record, dict):
        return None

    data = _as_dict(record.get("data"))
    meta = _as_dict(record.get("meta"))

    chat_id = (
        record.get("chat_id")
        or meta.get("chat_id")
        or data.get("chat_id")
        or meta.get("conversation_id")
    )
    score = data.get("score")
    if score is None:
        score = data.get("rating")
    if score is None:
        score = record.get("score")
    if score is None:
        score = record.get("rating")

    if not chat_id or score is None:
        return None

    payload: dict[str, Any] = {
        "chat_id": str(chat_id),
        "score": int(score),
    }

    comment = data.get("comment") or record.get("comment")
    reason = data.get("reason") or record.get("reason")
    if comment:
        payload["comment"] = str(comment)
    if reason:
        payload["reason"] = str(reason)

    return payload


def forward_feedback_record(
    record: dict[str, Any],
    backend_base_url: str,
    *,
    timeout: float = 10.0,
    opener=urllib_request.urlopen,
) -> dict[str, Any] | None:
    """POST a normalized record to the backend feedback endpoint."""
    payload = normalize_feedback_record(record)
    if payload is None:
        return None

    url = backend_base_url.rstrip("/") + "/feedback"
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with opener(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8").strip()
        if not raw:
            return None
        return json.loads(raw)


def sync_feedback_records(
    records: list[dict[str, Any]],
    backend_base_url: str,
    *,
    timeout: float = 10.0,
    forwarder=forward_feedback_record,
) -> dict[str, int]:
    """Forward all usable records and return a small summary."""
    processed = 0
    forwarded = 0
    skipped = 0

    for record in records:
        processed += 1
        if normalize_feedback_record(record) is None:
            skipped += 1
            continue

        result = forwarder(record, backend_base_url, timeout=timeout)
        if result is None:
            skipped += 1
            continue
        forwarded += 1

    return {
        "processed": processed,
        "forwarded": forwarded,
        "skipped": skipped,
    }
