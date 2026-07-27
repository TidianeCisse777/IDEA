"""Distribution of the canonical EcoTaxa SQLite cache."""

from __future__ import annotations

import gzip
import io
import json
from datetime import datetime, timezone

import pytest

from core.ecotaxa_browser.cache.repo import (
    SCHEMA_VERSION,
    finish_sync_run,
    init_schema,
    open_connection,
    set_schema_version,
    start_sync_run,
    upsert_sample,
)


def seeded_current_cache(path):
    """Create the smallest cache that fulfils the live-cache contract."""
    conn = open_connection(str(path))
    init_schema(conn)
    now = datetime.now(timezone.utc).isoformat()
    upsert_sample(
        conn,
        sample_id=1,
        project_id=42,
        lat_avg=67.0,
        lon_avg=-63.0,
        date_min="2026-07-27",
        date_max="2026-07-27",
        object_count=1,
        instrument="UVP6",
        last_synced=now,
    )
    run_id = start_sync_run(conn, started_at=now)
    finish_sync_run(
        conn,
        run_id=run_id,
        ended_at=now,
        status="ok",
        projects_synced=1,
        samples_synced=1,
        error_message=None,
    )
    set_schema_version(conn, SCHEMA_VERSION)
    conn.close()
    return path


def test_build_cache_bundle_keeps_the_validated_sqlite_bytes(tmp_path):
    from core.ecotaxa_browser.cache.distribution import build_cache_bundle

    cache_path = seeded_current_cache(tmp_path / "ecotaxa_cache.sqlite")

    manifest_path, archive_path = build_cache_bundle(cache_path, tmp_path / "release")

    with gzip.open(archive_path, "rb") as stream:
        assert stream.read() == cache_path.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["samples_indexed"] == 1
    assert manifest["projects_indexed"] == 1


def test_build_cache_bundle_rejects_an_empty_or_unstamped_cache(tmp_path):
    from core.ecotaxa_browser.cache.distribution import (
        CacheValidationError,
        build_cache_bundle,
    )

    empty_cache = tmp_path / "empty.sqlite"
    conn = open_connection(str(empty_cache))
    init_schema(conn)
    conn.close()

    with pytest.raises(CacheValidationError, match="schema|empty|sync"):
        build_cache_bundle(empty_cache, tmp_path / "release")


def test_install_cache_release_replaces_destination_only_after_verification(tmp_path):
    from core.ecotaxa_browser.cache.distribution import (
        build_cache_bundle,
        install_cache_release,
    )

    destination = seeded_current_cache(tmp_path / "ecotaxa_cache.sqlite")
    replacement = seeded_current_cache(tmp_path / "replacement.sqlite")
    manifest_path, archive_path = build_cache_bundle(replacement, tmp_path / "release")

    installed = install_cache_release(
        manifest_path.read_bytes(), io.BytesIO(archive_path.read_bytes()), destination
    )

    assert destination.read_bytes() == replacement.read_bytes()
    assert installed.samples_indexed == 1
    assert not list(tmp_path.glob(".ecotaxa_cache.sqlite.*.tmp"))


def test_install_cache_release_preserves_existing_cache_when_hash_is_wrong(tmp_path):
    from core.ecotaxa_browser.cache.distribution import (
        CacheValidationError,
        build_cache_bundle,
        install_cache_release,
    )

    destination = seeded_current_cache(tmp_path / "ecotaxa_cache.sqlite")
    original_bytes = destination.read_bytes()
    replacement = seeded_current_cache(tmp_path / "replacement.sqlite")
    manifest_path, archive_path = build_cache_bundle(replacement, tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = "0" * 64

    with pytest.raises(CacheValidationError, match="integrity"):
        install_cache_release(
            json.dumps(manifest).encode(), io.BytesIO(archive_path.read_bytes()), destination
        )

    assert destination.read_bytes() == original_bytes
