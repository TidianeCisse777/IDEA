#!/usr/bin/env python3
"""Bootstrap and validate the local EcoPart and Amundsen caches for start.sh."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# ``python3 scripts/check_source_caches.py`` puts only ``scripts/`` on
# sys.path; make the repository package importable without a virtualenv.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ecopart_cache_distribution import CacheBundleValidationError, bootstrap_consumer_cache


def _sqlite_integrity(path: Path, *, expected_table: str) -> sqlite3.Connection:
    if not path.is_file():
        raise RuntimeError(f"fichier absent : {path}")
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise RuntimeError(f"intégrité SQLite invalide : {integrity!r}")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if expected_table not in tables:
            raise RuntimeError(f"table attendue absente : {expected_table}")
        return connection
    except sqlite3.Error as exc:
        raise RuntimeError(f"SQLite illisible : {exc}") from exc


def check_ecopart_cache(*, bootstrap: bool) -> None:
    root = Path(os.getenv("ECOPART_CACHE_DIR", "data/ecopart_cache"))
    manifest = root / "manifest.sqlite"
    if bootstrap and not manifest.is_file():
        try:
            downloaded = bootstrap_consumer_cache(root)
        except CacheBundleValidationError as exc:
            raise RuntimeError(f"téléchargement de la release EcoPart impossible : {exc}") from exc
        if downloaded:
            print("Cache EcoPart téléchargé depuis la release partagée.")

    connection = _sqlite_integrity(manifest, expected_table="tsv_entries")
    try:
        rows = connection.execute("SELECT path FROM tsv_entries").fetchall()
    finally:
        connection.close()
    missing = [str(path) for (path,) in rows if not Path(path).is_file()]
    if missing:
        raise RuntimeError(
            f"{len(missing)} TSV référencé(s) absent(s), par exemple : {missing[0]}"
        )
    print(f"Cache EcoPart : OK ({len(rows)} TSV indexé(s)).")


def check_amundsen_cache() -> None:
    path = Path(os.getenv("ERDDAP_CACHE_PATH", "data/erddap_cache.sqlite"))
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE cache (namespace TEXT NOT NULL, key TEXT NOT NULL, "
                "value BLOB NOT NULL, ts REAL NOT NULL, PRIMARY KEY (namespace, key))"
            )
            connection.commit()
        finally:
            connection.close()
        print("Cache Amundsen initialisé (il sera rempli à la demande).")

    connection = _sqlite_integrity(path, expected_table="cache")
    try:
        rows = connection.execute(
            "SELECT COUNT(*) FROM cache WHERE namespace LIKE 'amundsen%'"
        ).fetchone()[0]
    finally:
        connection.close()
    print(f"Cache Amundsen : OK ({rows} entrée(s) Amundsen).")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap-ecopart", action="store_true")
    args = parser.parse_args()
    try:
        check_ecopart_cache(bootstrap=args.bootstrap_ecopart)
        check_amundsen_cache()
    except RuntimeError as exc:
        print(f"Cache externe invalide : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
