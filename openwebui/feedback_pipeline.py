"""Sync Open WebUI feedback exports into the LangSmith feedback bridge."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

from openwebui.feedback_bridge import forward_feedback_record, normalize_feedback_record


def _load_seen_ids(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    if not isinstance(raw, list):
        return set()
    return {str(item) for item in raw if item is not None}


def _save_seen_ids(state_path: Path, seen_ids: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(sorted(seen_ids), ensure_ascii=False),
        encoding="utf-8",
    )


def _feedback_id(record: dict[str, Any]) -> str | None:
    value = record.get("id") or record.get("feedback_id")
    return str(value) if value else None


def sync_openwebui_feedback_export(
    records: list[dict[str, Any]],
    backend_base_url: str,
    *,
    state_path: Path,
    timeout: float = 10.0,
    forwarder=forward_feedback_record,
) -> dict[str, int]:
    """Forward unseen feedback export rows and persist the seen set."""
    seen_ids = _load_seen_ids(state_path)
    processed = forwarded = skipped = 0

    for record in records:
        processed += 1
        feedback_id = _feedback_id(record)
        if feedback_id is None or feedback_id in seen_ids:
            skipped += 1
            continue
        if normalize_feedback_record(record) is None:
            skipped += 1
            continue

        result = forwarder(record, backend_base_url, timeout=timeout)
        if result is None:
            skipped += 1
            continue

        forwarded += 1
        seen_ids.add(feedback_id)

    _save_seen_ids(state_path, seen_ids)
    return {
        "processed": processed,
        "forwarded": forwarded,
        "skipped": skipped,
        "seen_total": len(seen_ids),
    }


def fetch_openwebui_feedback_export(
    openwebui_base_url: str,
    *,
    auth_token: str | None = None,
    timeout: float = 10.0,
    opener=urllib_request.urlopen,
) -> list[dict[str, Any]]:
    """Fetch Open WebUI feedback records.

    Tries the REST API first (v0.10+). Falls back to reading the SQLite DB
    directly via `docker cp` when the API endpoint is absent (v0.9.x).
    """
    url = openwebui_base_url.rstrip("/") + "/api/v1/evaluations/feedbacks/all"
    headers = {"Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    try:
        req = urllib_request.Request(url, headers=headers, method="GET")
        with opener(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8").strip()
            if raw and not raw.startswith("<"):
                payload = json.loads(raw)
                if isinstance(payload, list):
                    return payload
                if isinstance(payload, dict):
                    for key in ("data", "items", "feedbacks", "results"):
                        value = payload.get(key)
                        if isinstance(value, list):
                            return value
    except Exception:
        pass

    # Fallback: read directly from the SQLite DB via docker cp
    return _fetch_via_sqlite()


def _fetch_via_sqlite(
    container: str = "open-webui",
    db_path: str = "/app/backend/data/webui.db",
) -> list[dict[str, Any]]:
    """Copy the Open WebUI SQLite DB from the container and read the feedback table."""
    import shutil
    import sqlite3
    import subprocess
    import tempfile

    if not shutil.which("docker"):
        return []

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["docker", "cp", f"{container}:{db_path}", tmp_path],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        # Copy WAL + SHM so recent unflushed writes are visible
        for ext in ("-wal", "-shm"):
            subprocess.run(
                ["docker", "cp", f"{container}:{db_path}{ext}", f"{tmp_path}{ext}"],
                capture_output=True, timeout=10,
            )

        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, data, meta, created_at FROM feedback ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
        conn.close()

        records = []
        for row in rows:
            try:
                data = json.loads(row["data"] or "{}")
                meta = json.loads(row["meta"] or "{}")
                records.append({
                    "id": row["id"],
                    "data": data,
                    "meta": meta,
                    "created_at": row["created_at"],
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return records
    except Exception:
        return []
    finally:
        for ext in ("", "-wal", "-shm"):
            Path(f"{tmp_path}{ext}").unlink(missing_ok=True)
