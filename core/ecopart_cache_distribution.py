"""Distribuer le cache EcoPart (manifest SQLite et TSV dédupliqués).

Le cache EcoPart est un répertoire : contrairement au cache EcoTaxa, il faut
livrer ensemble la base de métadonnées et les exports TSV auxquels elle pointe.
Les archives sont donc contrôlées avant une installation atomique dans un clone.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Callable
from urllib.request import Request, urlopen
from uuid import uuid4


_ARCHIVE_NAME = "ecopart_cache.tar.gz"
_MANIFEST_NAME = "ecopart_cache_manifest.json"
_ARCHIVE_ROOT = "ecopart_cache"


class CacheBundleValidationError(ValueError):
    """Raised when an EcoPart cache bundle is unsafe or inconsistent."""


@dataclass(frozen=True)
class CacheBundleManifest:
    """Integrity metadata for a released EcoPart cache directory."""

    schema_version: int
    archive_sha256: str
    files: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-safe representation stored beside the archive."""
        return asdict(self)

    @classmethod
    def from_json(cls, payload: bytes) -> "CacheBundleManifest":
        """Parse a manifest and reject malformed asset metadata."""
        try:
            raw = json.loads(payload.decode("utf-8"))
            files = tuple(str(item) for item in raw["files"])
            manifest = cls(
                schema_version=int(raw["schema_version"]),
                archive_sha256=str(raw["archive_sha256"]),
                files=files,
            )
        except (KeyError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise CacheBundleValidationError("manifest de cache EcoPart invalide") from exc
        if manifest.schema_version != 1:
            raise CacheBundleValidationError("version de cache EcoPart incompatible")
        if len(manifest.archive_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in manifest.archive_sha256.lower()
        ):
            raise CacheBundleValidationError("empreinte du cache EcoPart invalide")
        if "manifest.sqlite" not in manifest.files:
            raise CacheBundleValidationError("manifest SQLite EcoPart absent du paquet")
        if len(set(manifest.files)) != len(manifest.files) or any(
            not _is_safe_relative_path(Path(item)) for item in manifest.files
        ):
            raise CacheBundleValidationError("chemin de fichier EcoPart invalide")
        return manifest


def _is_safe_relative_path(path: Path) -> bool:
    return not path.is_absolute() and bool(path.parts) and ".." not in path.parts and "." not in path.parts


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _cache_files(cache_root: Path) -> tuple[Path, ...]:
    if not (cache_root / "manifest.sqlite").is_file():
        raise CacheBundleValidationError("manifest SQLite EcoPart introuvable")
    paths = tuple(sorted(path for path in cache_root.rglob("*") if path.is_file()))
    if not paths:
        raise CacheBundleValidationError("cache EcoPart vide")
    for path in paths:
        relative = path.relative_to(cache_root)
        if path.is_symlink() or not _is_safe_relative_path(relative):
            raise CacheBundleValidationError("fichier de cache EcoPart non distribuable")
    return paths


def build_cache_bundle(cache_root: Path, output_dir: Path) -> tuple[Path, Path]:
    """Archive a complete local cache for a release or an offline clone."""
    cache_root = Path(cache_root)
    files = _cache_files(cache_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / _ARCHIVE_NAME
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in files:
            relative = path.relative_to(cache_root)
            archive.add(path, arcname=str(Path(_ARCHIVE_ROOT) / relative), recursive=False)
    manifest = CacheBundleManifest(
        schema_version=1,
        archive_sha256=_sha256_bytes(archive_path.read_bytes()),
        files=tuple(str(path.relative_to(cache_root)) for path in files),
    )
    manifest_path = output_dir / _MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest.to_dict(), sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path, archive_path


def _validate_archive_members(archive: tarfile.TarFile, manifest: CacheBundleManifest) -> None:
    expected = {str(Path(_ARCHIVE_ROOT) / name) for name in manifest.files}
    actual: set[str] = set()
    for member in archive.getmembers():
        path = Path(member.name)
        if (
            path.is_absolute()
            or not path.parts
            or path.parts[0] != _ARCHIVE_ROOT
            or ".." in path.parts
            or member.issym()
            or member.islnk()
        ):
            raise CacheBundleValidationError("archive EcoPart non sûre")
        if member.isfile():
            actual.add(member.name)
        elif not member.isdir():
            raise CacheBundleValidationError("archive EcoPart contient un type de fichier non pris en charge")
    if actual != expected:
        raise CacheBundleValidationError("archive EcoPart incohérente avec son manifest")


def _validate_installed_directory(root: Path, manifest: CacheBundleManifest) -> None:
    if not (root / "manifest.sqlite").is_file():
        raise CacheBundleValidationError("cache EcoPart installé sans manifest SQLite")
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual != set(manifest.files):
        raise CacheBundleValidationError("cache EcoPart installé incomplet")


def install_cache_bundle(manifest_bytes: bytes, archive_bytes: bytes, destination: Path) -> CacheBundleManifest:
    """Validate then atomically replace the local EcoPart cache directory."""
    manifest = CacheBundleManifest.from_json(manifest_bytes)
    if _sha256_bytes(archive_bytes) != manifest.archive_sha256:
        raise CacheBundleValidationError("contrôle d'intégrité du cache EcoPart échoué")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    backup = destination.parent / f".{destination.name}.{uuid4().hex}.backup"
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{destination.name}.extract-", dir=destination.parent
        ) as temporary_directory:
            temporary_root = Path(temporary_directory)
            try:
                with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
                    _validate_archive_members(archive, manifest)
                    archive.extractall(temporary_root, filter="data")
            except (tarfile.TarError, OSError) as exc:
                raise CacheBundleValidationError("archive EcoPart illisible") from exc

            extracted = temporary_root / _ARCHIVE_ROOT
            if not extracted.is_dir():
                raise CacheBundleValidationError("racine du cache EcoPart absente de l'archive")
            extracted.replace(staged)
        _validate_installed_directory(staged, manifest)

        if destination.exists():
            destination.replace(backup)
        try:
            staged.replace(destination)
        except Exception:
            if backup.exists() and not destination.exists():
                backup.replace(destination)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        return manifest
    finally:
        if staged.exists():
            shutil.rmtree(staged, ignore_errors=True)
        if backup.exists() and not destination.exists():
            backup.replace(destination)


def _request_bytes(
    url: str,
    token: str | None,
    *,
    opener: Callable[[Request], BinaryIO],
    accept: str,
) -> bytes:
    headers = {"Accept": accept, "User-Agent": "idea-ecopart-cache"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with opener(Request(url, headers=headers)) as response:
            return response.read()
    except Exception as exc:
        raise CacheBundleValidationError("téléchargement du cache EcoPart impossible") from exc


def download_github_release_cache(
    repository: str,
    tag: str,
    token: str | None,
    destination: Path,
    *,
    opener: Callable[[Request], BinaryIO] = urlopen,
) -> CacheBundleManifest:
    """Download and safely install the two EcoPart cache release assets."""
    if not repository or "/" not in repository or not tag:
        raise CacheBundleValidationError("dépôt et tag de release EcoPart requis")
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
        assets = {str(asset["name"]): str(asset["url"]) for asset in release["assets"]}
        manifest_url = assets[_MANIFEST_NAME]
        archive_url = assets[_ARCHIVE_NAME]
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CacheBundleValidationError("release EcoPart sans les assets attendus") from exc
    manifest_bytes = _request_bytes(
        manifest_url,
        token,
        opener=opener,
        accept="application/octet-stream",
    )
    archive_bytes = _request_bytes(
        archive_url,
        token,
        opener=opener,
        accept="application/octet-stream",
    )
    return install_cache_bundle(manifest_bytes, archive_bytes, destination)


def bootstrap_consumer_cache(destination: Path) -> bool:
    """Install the shared cache in a consumer clone when no local cache exists.

    ``False`` means that a local cache is already present, publication mode is
    active, or no shared release was configured. Download errors intentionally
    propagate: callers choose whether remote EcoPart fallback is acceptable.
    """
    destination = Path(destination)
    if (destination / "manifest.sqlite").is_file():
        return False
    mode = os.getenv("ECOPART_CACHE_MODE", "consumer").strip().lower()
    if mode == "publisher":
        return False
    if mode != "consumer":
        raise CacheBundleValidationError("ECOPART_CACHE_MODE doit être consumer ou publisher")
    repository = os.getenv("ECOPART_CACHE_RELEASE_REPOSITORY", "").strip()
    tag = os.getenv("ECOPART_CACHE_RELEASE_TAG", "ecopart-cache-current").strip()
    if not repository or not tag:
        return False
    token = os.getenv("ECOPART_CACHE_RELEASE_TOKEN") or os.getenv("GITHUB_TOKEN") or None
    download_github_release_cache(repository, tag, token, destination)
    return True
