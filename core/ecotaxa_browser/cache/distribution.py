"""Package and validate the canonical EcoTaxa SQLite cache for distribution."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from core.ecotaxa_browser.cache.repo import (
    SCHEMA_VERSION,
    cache_counts,
    get_schema_version,
    latest_sync_status,
    open_readonly_connection,
)


class CacheValidationError(ValueError):
    """Raised when a cache cannot safely be distributed or installed."""


@dataclass(frozen=True)
class CacheManifest:
    """Integrity and compatibility metadata for a released SQLite cache."""

    schema_version: int
    sha256: str
    size_bytes: int
    projects_indexed: int
    samples_indexed: int
    synced_at: str

    def to_dict(self) -> dict[str, int | str]:
        """Return the stable JSON representation stored beside the archive."""
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_installed_cache(cache_path: Path) -> CacheManifest:
    """Validate an existing cache without changing its schema or contents."""
    try:
        conn = open_readonly_connection(str(cache_path))
    except Exception as exc:
        raise CacheValidationError("cache SQLite unreadable") from exc
    try:
        schema_version = get_schema_version(conn)
        counts = cache_counts(conn)
        last_sync = latest_sync_status(conn)
    except Exception as exc:
        raise CacheValidationError("cache schema invalid") from exc
    finally:
        conn.close()

    if schema_version != SCHEMA_VERSION:
        raise CacheValidationError(
            f"cache schema mismatch: expected {SCHEMA_VERSION}, got {schema_version}"
        )
    if not counts["samples_indexed"] or not counts["projects_indexed"]:
        raise CacheValidationError("cache is empty")
    if not last_sync or last_sync.get("status") != "ok" or not last_sync.get("ended_at"):
        raise CacheValidationError("cache has no successful completed sync")

    return CacheManifest(
        schema_version=schema_version,
        sha256=_sha256_file(cache_path),
        size_bytes=cache_path.stat().st_size,
        projects_indexed=counts["projects_indexed"],
        samples_indexed=counts["samples_indexed"],
        synced_at=str(last_sync["ended_at"]),
    )


def build_cache_bundle(cache_path: Path, output_dir: Path) -> tuple[Path, Path]:
    """Create a gzip archive and manifest from a validated SQLite cache."""
    manifest = validate_installed_cache(cache_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / "ecotaxa_cache.sqlite.gz"
    with cache_path.open("rb") as source, gzip.open(archive_path, "wb") as target:
        shutil.copyfileobj(source, target)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path, archive_path
