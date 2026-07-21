"""Preflight cache validation used by start.sh to gate agent startup."""

from __future__ import annotations

import sqlite3

import pytest

from scripts.check_ecotaxa_cache import (
    _EXPECTED_SCHEMA_VERSION,
    _REQUIRED_TABLES,
    validate_cache_health,
    validate_cache_schema,
)


def _payload(**overrides):
    base = {
        "samples_indexed": 2441,
        "projects_indexed": 6,
        "schemas_indexed": 6,
        "last_sync_status": "ok",
        "cache_age_hours": 2.0,
        "schema_version": 3,
        "schema_current": True,
    }
    base.update(overrides)
    return {"status": "ok", "cache": base}


def test_healthy_cache_passes_without_warnings():
    result = validate_cache_health(_payload())
    assert result.ok is True
    assert result.errors == []
    assert result.warnings == []


def test_missing_cache_payload_blocks():
    result = validate_cache_health({"status": "ok", "cache": None})
    assert result.ok is False
    assert any("cache" in e.lower() for e in result.errors)


@pytest.mark.parametrize("schema_current", [None, False])
def test_missing_or_stale_schema_blocks(schema_current):
    payload = _payload()
    if schema_current is None:
        payload["cache"].pop("schema_current")
    else:
        payload["cache"]["schema_current"] = schema_current

    result = validate_cache_health(payload)

    assert result.ok is False
    assert any("schéma" in e.lower() for e in result.errors)


def test_empty_samples_blocks():
    result = validate_cache_health(_payload(samples_indexed=0))
    assert result.ok is False
    assert any("sample" in e.lower() for e in result.errors)


def test_zero_projects_blocks():
    result = validate_cache_health(_payload(projects_indexed=0))
    assert result.ok is False
    assert any("proj" in e.lower() for e in result.errors)


def test_below_custom_minimum_blocks():
    result = validate_cache_health(_payload(samples_indexed=5), min_samples=100)
    assert result.ok is False


def test_failed_last_sync_warns_but_does_not_block():
    # Usable data from a previous sync must not be gated by a later failed run.
    result = validate_cache_health(_payload(last_sync_status="failed"))
    assert result.ok is True
    assert any("sync" in w.lower() for w in result.warnings)


def test_stale_cache_warns_but_does_not_block():
    result = validate_cache_health(_payload(cache_age_hours=1000.0), max_age_hours=168.0)
    assert result.ok is True
    assert any("stale" in w.lower() or "old" in w.lower() or "âg" in w.lower() or "age" in w.lower()
               for w in result.warnings)


def test_partial_sync_is_acceptable():
    # A partial sync (e.g. one 404 project among many) is a healthy outcome.
    result = validate_cache_health(_payload(last_sync_status="partial"))
    assert result.ok is True
    assert result.warnings == []


def test_none_age_does_not_crash():
    result = validate_cache_health(_payload(cache_age_hours=None))
    assert result.ok is True


def test_malformed_top_level_blocks():
    result = validate_cache_health({"unexpected": True})
    assert result.ok is False


# ---------------------------------------------------------------------------
# validate_cache_schema — format checks (structure, not content)
# ---------------------------------------------------------------------------

def _make_valid_db(path, *, schema_version=_EXPECTED_SCHEMA_VERSION):
    """Create a minimal but structurally valid EcoTaxa cache at *path*."""
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {schema_version}")
    for table, cols in _REQUIRED_TABLES.items():
        col_defs = ", ".join(f"{c} TEXT" for c in cols)
        conn.execute(f"CREATE TABLE {table} ({col_defs})")
    conn.commit()
    conn.close()


def test_valid_schema_passes(tmp_path):
    db = tmp_path / "cache.sqlite"
    _make_valid_db(str(db))
    result = validate_cache_schema(db)
    assert result.ok is True
    assert result.errors == []


def test_missing_file_blocks(tmp_path):
    result = validate_cache_schema(tmp_path / "nonexistent.sqlite")
    assert result.ok is False
    assert any("introuvable" in e for e in result.errors)


def test_wrong_schema_version_blocks(tmp_path):
    db = tmp_path / "cache.sqlite"
    _make_valid_db(str(db), schema_version=99)
    result = validate_cache_schema(db)
    assert result.ok is False
    assert any("version" in e.lower() for e in result.errors)


def test_missing_table_blocks(tmp_path):
    db = tmp_path / "cache.sqlite"
    _make_valid_db(str(db))
    conn = sqlite3.connect(str(db))
    conn.execute("DROP TABLE sync_runs")
    conn.commit()
    conn.close()
    result = validate_cache_schema(db)
    assert result.ok is False
    assert any("sync_runs" in e for e in result.errors)


def test_missing_column_blocks(tmp_path):
    db = tmp_path / "cache.sqlite"
    _make_valid_db(str(db))
    conn = sqlite3.connect(str(db))
    # Recreate samples_cache without iho_zone
    cols_without = [c for c in _REQUIRED_TABLES["samples_cache"] if c != "iho_zone"]
    col_defs = ", ".join(f"{c} TEXT" for c in cols_without)
    conn.execute("DROP TABLE samples_cache")
    conn.execute(f"CREATE TABLE samples_cache ({col_defs})")
    conn.commit()
    conn.close()
    result = validate_cache_schema(db)
    assert result.ok is False
    assert any("iho_zone" in e for e in result.errors)


def test_not_a_sqlite_file_blocks(tmp_path):
    db = tmp_path / "garbage.sqlite"
    db.write_bytes(b"not a sqlite database at all")
    result = validate_cache_schema(db)
    assert result.ok is False
