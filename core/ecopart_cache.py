"""Cache local persistant des correspondances et TSV EcoPart.

Le module est volontairement indépendant des clients HTTP : il indexe seulement
des fichiers déjà obtenus et des résolutions déjà vérifiées par le caller.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


_REQUIRED_COLUMNS = {"Profile", "Depth [m]", "Sampled volume [L]"}


@dataclass(frozen=True)
class CachedEcopartTsv:
    content_sha256: str
    path: Path
    profiles: tuple[str, ...]
    provenance: str
    ecopart_project_id: int | None
    ecotaxa_project_id: int | None
    n_rows: int
    imported_at: float


@dataclass(frozen=True)
class CachedEcopartResolution:
    ecotaxa_project_id: int
    ecopart_project_id: int | None
    resolution: str
    status: str
    cached_at: float
    expires_at: float


@dataclass(frozen=True)
class CachedEcopartSamplePreview:
    sample_id: int
    accessible: bool
    text: str
    cached_at: float


def cache_root() -> Path:
    return Path(os.getenv("ECOPART_CACHE_DIR", "data/ecopart_cache"))


def _files_dir() -> Path:
    return cache_root() / "files"


def _manifest_path() -> Path:
    return cache_root() / "manifest.sqlite"


def _connection() -> sqlite3.Connection:
    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_manifest_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tsv_entries ("
        "content_sha256 TEXT PRIMARY KEY, path TEXT NOT NULL, profiles_json TEXT NOT NULL, "
        "columns_json TEXT NOT NULL, provenance TEXT NOT NULL, "
        "ecopart_project_id INTEGER, ecotaxa_project_id INTEGER, n_rows INTEGER NOT NULL, "
        "imported_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS project_resolutions ("
        "ecotaxa_project_id INTEGER PRIMARY KEY, ecopart_project_id INTEGER, "
        "resolution TEXT NOT NULL, status TEXT NOT NULL, cached_at REAL NOT NULL, "
        "expires_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sample_previews ("
        "sample_id INTEGER PRIMARY KEY, accessible INTEGER NOT NULL, text TEXT NOT NULL, "
        "cached_at REAL NOT NULL)"
    )
    return conn


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_entry(row: sqlite3.Row) -> CachedEcopartTsv:
    return CachedEcopartTsv(
        content_sha256=str(row["content_sha256"]),
        path=Path(str(row["path"])),
        profiles=tuple(json.loads(row["profiles_json"])),
        provenance=str(row["provenance"]),
        ecopart_project_id=(
            int(row["ecopart_project_id"])
            if row["ecopart_project_id"] is not None
            else None
        ),
        ecotaxa_project_id=(
            int(row["ecotaxa_project_id"])
            if row["ecotaxa_project_id"] is not None
            else None
        ),
        n_rows=int(row["n_rows"]),
        imported_at=float(row["imported_at"]),
    )


def import_ecopart_tsv(
    source: Path,
    *,
    provenance: str,
    ecopart_project_id: int | None = None,
    ecotaxa_project_id: int | None = None,
) -> CachedEcopartTsv:
    """Validate and persist one already-downloaded EcoPart TSV.

    The header is validated before creating the cache directory, so malformed
    input leaves no persistent cache state behind.
    """
    source = Path(source)
    header = pd.read_csv(source, sep="\t", nrows=0)
    columns = [str(column) for column in header.columns]
    missing = sorted(_REQUIRED_COLUMNS.difference(columns))
    if missing:
        raise ValueError("TSV EcoPart invalide : colonnes absentes " + ", ".join(missing))
    if provenance not in {"remote_export", "local_import"}:
        raise ValueError("Provenance EcoPart invalide.")

    dataframe = pd.read_csv(source, sep="\t", usecols=["Profile"])
    profiles = tuple(sorted(dataframe["Profile"].dropna().astype(str).unique()))
    n_rows = len(dataframe)
    digest = _sha256_file(source)
    target = _files_dir() / f"{digest}.tsv"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(source, target)

    imported_at = time.time()
    conn = _connection()
    try:
        existing = conn.execute(
            "SELECT * FROM tsv_entries WHERE content_sha256=?", (digest,)
        ).fetchone()
        stored_provenance = (
            "remote_export"
            if provenance == "remote_export" or (existing and existing["provenance"] == "remote_export")
            else "local_import"
        )
        stored_ep = ecopart_project_id or (existing["ecopart_project_id"] if existing else None)
        stored_et = ecotaxa_project_id or (existing["ecotaxa_project_id"] if existing else None)
        conn.execute(
            "INSERT OR REPLACE INTO tsv_entries "
            "(content_sha256,path,profiles_json,columns_json,provenance,ecopart_project_id,"
            "ecotaxa_project_id,n_rows,imported_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                digest, str(target), json.dumps(profiles), json.dumps(columns), stored_provenance,
                stored_ep, stored_et, n_rows, imported_at,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM tsv_entries WHERE content_sha256=?", (digest,)
        ).fetchone()
    finally:
        conn.close()
    return _as_entry(row)


def load_ecopart_tsv(entry: CachedEcopartTsv) -> pd.DataFrame:
    """Load a cached TSV into an isolated dataframe for a caller session."""
    return pd.read_csv(entry.path, sep="\t")


def find_ecopart_tsv(
    *, ecopart_project_id: int | None, profile_labels: set[str]
) -> CachedEcopartTsv | None:
    """Return the strongest cache candidate compatible with requested profiles."""
    if not _manifest_path().exists():
        return None
    normalized = {str(label).strip() for label in profile_labels if str(label).strip()}
    conn = _connection()
    try:
        rows = conn.execute("SELECT * FROM tsv_entries").fetchall()
    finally:
        conn.close()
    candidates = []
    for row in rows:
        entry = _as_entry(row)
        overlap = len(normalized.intersection(entry.profiles))
        if not overlap:
            continue
        project_match = int(
            ecopart_project_id is not None
            and entry.ecopart_project_id == int(ecopart_project_id)
        )
        candidates.append((project_match, overlap, int(entry.provenance == "remote_export"), entry.imported_at, entry.content_sha256, entry))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[:-1])[-1]


def save_resolution(
    ecotaxa_project_id: int,
    *,
    ecopart_project_id: int | None,
    resolution: str,
    status: str,
    ttl_seconds: float,
) -> None:
    """Persist one already-verified EcoTaxa to EcoPart resolution."""
    now = time.time()
    conn = _connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO project_resolutions "
            "(ecotaxa_project_id,ecopart_project_id,resolution,status,cached_at,expires_at) "
            "VALUES (?,?,?,?,?,?)",
            (int(ecotaxa_project_id), ecopart_project_id, resolution, status, now, now + float(ttl_seconds)),
        )
        conn.commit()
    finally:
        conn.close()


def load_resolution(
    ecotaxa_project_id: int, *, now: float | None = None
) -> CachedEcopartResolution | None:
    """Return a fresh persisted resolution, never a stale one."""
    if not _manifest_path().exists():
        return None
    now = time.time() if now is None else float(now)
    conn = _connection()
    try:
        row = conn.execute(
            "SELECT * FROM project_resolutions WHERE ecotaxa_project_id=? AND expires_at>?",
            (int(ecotaxa_project_id), now),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return CachedEcopartResolution(
        ecotaxa_project_id=int(row["ecotaxa_project_id"]),
        ecopart_project_id=(int(row["ecopart_project_id"]) if row["ecopart_project_id"] is not None else None),
        resolution=str(row["resolution"]),
        status=str(row["status"]),
        cached_at=float(row["cached_at"]),
        expires_at=float(row["expires_at"]),
    )


def save_sample_preview(sample_id: int, *, accessible: bool, text: str) -> None:
    """Persist the text shown by an already-authorized EcoPart sample preview."""
    conn = _connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sample_previews (sample_id,accessible,text,cached_at) "
            "VALUES (?,?,?,?)",
            (int(sample_id), int(bool(accessible)), str(text), time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def load_sample_preview(sample_id: int) -> CachedEcopartSamplePreview | None:
    """Return an existing durable preview without an EcoPart network request."""
    if not _manifest_path().exists():
        return None
    conn = _connection()
    try:
        row = conn.execute(
            "SELECT * FROM sample_previews WHERE sample_id=?", (int(sample_id),)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return CachedEcopartSamplePreview(
        sample_id=int(row["sample_id"]),
        accessible=bool(row["accessible"]),
        text=str(row["text"]),
        cached_at=float(row["cached_at"]),
    )
