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


def test_download_github_release_cache_uses_manifest_and_archive_assets(tmp_path):
    from core.ecotaxa_browser.cache.distribution import (
        build_cache_bundle,
        download_github_release_cache,
    )

    source = seeded_current_cache(tmp_path / "source.sqlite")
    manifest_path, archive_path = build_cache_bundle(source, tmp_path / "release")
    responses = {
        "https://api.github.com/repos/owner/repo/releases/tags/ecotaxa-cache-current": json.dumps(
            {
                "assets": [
                    {"name": "manifest.json", "url": "https://release.test/manifest"},
                    {"name": "ecotaxa_cache.sqlite.gz", "url": "https://release.test/archive"},
                ]
            }
        ).encode(),
        "https://release.test/manifest": manifest_path.read_bytes(),
        "https://release.test/archive": archive_path.read_bytes(),
    }
    requested_urls = []

    def opener(request):
        requested_urls.append(request.full_url)
        return io.BytesIO(responses[request.full_url])

    destination = tmp_path / "data" / "ecotaxa_cache.sqlite"
    installed = download_github_release_cache(
        "owner/repo", "ecotaxa-cache-current", None, destination, opener=opener
    )

    assert installed.samples_indexed == 1
    assert destination.read_bytes() == source.read_bytes()
    assert requested_urls == [
        "https://api.github.com/repos/owner/repo/releases/tags/ecotaxa-cache-current",
        "https://release.test/manifest",
        "https://release.test/archive",
    ]


def test_publish_github_release_uploads_archive_before_manifest(tmp_path):
    from core.ecotaxa_browser.cache.distribution import publish_github_release_cache

    source = seeded_current_cache(tmp_path / "source.sqlite")
    release_url = "https://api.github.com/repos/owner/repo/releases/tags/ecotaxa-cache-current"
    upload_url = "https://uploads.github.com/repos/owner/repo/releases/17/assets"
    requests = []

    def opener(request):
        requests.append((request.get_method(), request.full_url, request.data))
        if request.full_url == release_url:
            return io.BytesIO(
                json.dumps(
                    {
                        "upload_url": upload_url + "{?name,label}",
                        "assets": [
                            {"name": "manifest.json", "url": "https://api.test/assets/1"},
                            {"name": "ecotaxa_cache.sqlite.gz", "url": "https://api.test/assets/2"},
                        ],
                    }
                ).encode()
            )
        return io.BytesIO(b"{}")

    publish_github_release_cache(
        source, "owner/repo", "ecotaxa-cache-current", "test-token", opener=opener
    )

    methods_and_urls = [(method, url) for method, url, _ in requests]
    assert methods_and_urls == [
        ("GET", release_url),
        ("DELETE", "https://api.test/assets/2"),
        ("POST", upload_url + "?name=ecotaxa_cache.sqlite.gz"),
        ("DELETE", "https://api.test/assets/1"),
        ("POST", upload_url + "?name=manifest.json"),
    ]
