"""Install or update the IDEA Open WebUI file-bridge filter idempotently."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


FUNCTION_ID = "idea_file_bridge"
DB_PATH = Path("/app/backend/data/webui.db")
SOURCE_PATH = Path("/bootstrap/idea_file_bridge_filter.py")
MAX_ATTEMPTS = 30


def _admin_id(connection: sqlite3.Connection) -> str | None:
    row = connection.execute(
        "SELECT id FROM user WHERE role = 'admin' ORDER BY created_at LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def install(*, db_path: Path = DB_PATH, source_path: Path = SOURCE_PATH) -> None:
    """Write the active, global Open WebUI filter to the persistent database."""
    source = source_path.read_text(encoding="utf-8")
    now = int(time.time())
    connection = sqlite3.connect(db_path, timeout=10)
    try:
        user_id = _admin_id(connection)
        metadata = json.dumps({"title": "IDEA file bridge", "description": "Avoid native RAG for IDEA uploads."})
        connection.execute(
            """
            INSERT INTO function (id, user_id, name, type, content, meta, valves, is_active, is_global, updated_at, created_at)
            VALUES (?, ?, ?, 'filter', ?, ?, '{}', 1, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                user_id=excluded.user_id,
                name=excluded.name,
                type=excluded.type,
                content=excluded.content,
                meta=excluded.meta,
                is_active=1,
                is_global=1,
                updated_at=excluded.updated_at
            """,
            (FUNCTION_ID, user_id, "IDEA file bridge", source, metadata, now, now),
        )
        connection.commit()
    finally:
        connection.close()


def main() -> None:
    for attempt in range(MAX_ATTEMPTS):
        try:
            install()
        except (FileNotFoundError, sqlite3.OperationalError) as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise SystemExit(f"IDEA Open WebUI filter installation failed: {exc}") from exc
            time.sleep(1)
        else:
            print("IDEA Open WebUI file-bridge filter installed.")
            return


if __name__ == "__main__":
    main()
