"""Package and validate the canonical EcoTaxa SQLite cache for distribution."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Callable
from urllib.request import Request, urlopen
from uuid import uuid4

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

    @classmethod
    def from_json(cls, payload: bytes) -> "CacheManifest":
        """Parse a release manifest and reject incomplete or malformed data."""
        try:
            raw = json.loads(payload.decode("utf-8"))
            manifest = cls(
                schema_version=int(raw["schema_version"]),
                sha256=str(raw["sha256"]),
                size_bytes=int(raw["size_bytes"]),
                projects_indexed=int(raw["projects_indexed"]),
                samples_indexed=int(raw["samples_indexed"]),
                synced_at=str(raw["synced_at"]),
            )
        except (KeyError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise CacheValidationError("release manifest is invalid") from exc
        if len(manifest.sha256) != 64 or any(c not in "0123456789abcdef" for c in manifest.sha256.lower()):
            raise CacheValidationError("release manifest has an invalid sha256")
        if manifest.size_bytes <= 0 or manifest.projects_indexed <= 0 or manifest.samples_indexed <= 0:
            raise CacheValidationError("release manifest has invalid cache counts")
        return manifest


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


def install_cache_release(
    manifest_bytes: bytes,
    archive_stream: BinaryIO,
    destination: Path,
) -> CacheManifest:
    """Verify a released archive and atomically replace the local cache."""
    manifest = CacheManifest.from_json(manifest_bytes)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        try:
            with gzip.GzipFile(fileobj=archive_stream, mode="rb") as source:
                with temporary.open("wb") as target:
                    shutil.copyfileobj(source, target)
        except (OSError, EOFError) as exc:
            raise CacheValidationError("release archive is unreadable") from exc

        if temporary.stat().st_size != manifest.size_bytes:
            raise CacheValidationError("release archive integrity check failed")
        if _sha256_file(temporary) != manifest.sha256:
            raise CacheValidationError("release archive integrity check failed")

        installed = validate_installed_cache(temporary)
        if (
            installed.schema_version != manifest.schema_version
            or installed.projects_indexed != manifest.projects_indexed
            or installed.samples_indexed != manifest.samples_indexed
            or installed.synced_at != manifest.synced_at
        ):
            raise CacheValidationError("release manifest does not match cache")
        temporary.replace(destination)
        return installed
    finally:
        temporary.unlink(missing_ok=True)


def _request_bytes(
    url: str,
    token: str | None,
    *,
    opener: Callable[[Request], BinaryIO],
    accept: str,
) -> bytes:
    headers = {"Accept": accept, "User-Agent": "idea-ecotaxa-cache"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with opener(Request(url, headers=headers)) as response:
            return response.read()
    except Exception as exc:
        raise CacheValidationError("unable to download shared cache release") from exc


def download_github_release_cache(
    repository: str,
    tag: str,
    token: str | None,
    destination: Path,
    *,
    opener: Callable[[Request], BinaryIO] = urlopen,
) -> CacheManifest:
    """Download the named GitHub release and install its verified cache assets."""
    if not repository or "/" not in repository or not tag:
        raise CacheValidationError("release repository and tag are required")
    release_url = f"https://api.github.com/repos/{repository}/releases/tags/{tag}"
    try:
        release = json.loads(
            _request_bytes(
                release_url,
                token,
                opener=opener,
                accept="application/vnd.github+json",
            ).decode("utf-8")
        )
        assets = {asset["name"]: asset["url"] for asset in release["assets"]}
        manifest_url = assets["manifest.json"]
        archive_url = assets["ecotaxa_cache.sqlite.gz"]
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CacheValidationError("shared cache release has invalid assets") from exc
    manifest = _request_bytes(
        manifest_url,
        token,
        opener=opener,
        accept="application/octet-stream",
    )
    archive = _request_bytes(
        archive_url,
        token,
        opener=opener,
        accept="application/octet-stream",
    )
    return install_cache_release(manifest, io.BytesIO(archive), destination)
