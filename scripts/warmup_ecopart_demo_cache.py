"""Importe les TSV EcoPart locaux et préchauffe les liens EcoTaxa→EcoPart."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.ecopart_cache import import_ecopart_tsv, save_resolution
from core.ecopart_client import EcopartClient

_REQUIRED = {"Profile", "Depth [m]", "Sampled volume [L]"}


def _valid_tsvs(roots: list[Path]) -> tuple[list[Path], int]:
    valid: list[Path] = []
    invalid = 0
    for root in roots:
        for path in sorted(root.rglob("*.tsv")):
            try:
                columns = set(pd.read_csv(path, sep="\t", nrows=0).columns)
            except (OSError, UnicodeDecodeError, pd.errors.ParserError):
                invalid += 1
                continue
            if _REQUIRED.issubset(columns):
                valid.append(path)
            else:
                invalid += 1
    return valid, invalid


def _ecotaxa_project_ids(path: Path) -> list[int]:
    connection = sqlite3.connect(path)
    try:
        return [int(row[0]) for row in connection.execute("SELECT project_id FROM projects_cache ORDER BY project_id")]
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tsv-root", action="append", type=Path, default=[])
    parser.add_argument("--resolve-ecotaxa-cache", type=Path)
    parser.add_argument("--project-id", action="append", type=int, default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    missing = [root for root in args.tsv_root if not root.is_dir()]
    if missing:
        print("Répertoire TSV introuvable : " + ", ".join(map(str, missing)), file=sys.stderr)
        return 2
    valid, invalid = _valid_tsvs(args.tsv_root)
    project_ids = _ecotaxa_project_ids(args.resolve_ecotaxa_cache) if args.resolve_ecotaxa_cache else []
    if args.project_id:
        project_ids = [project_id for project_id in project_ids if project_id in set(args.project_id)]
    print(f"{len(valid)} TSV EcoPart valide(s), {invalid} ignoré(s), {len(project_ids)} projet(s) EcoTaxa.")
    if not args.apply:
        return 0
    for path in valid:
        import_ecopart_tsv(path, provenance="local_import")
    resolved = 0
    unresolved: list[str] = []
    if project_ids:
        client = EcopartClient()
        print("Connexion EcoPart…", flush=True)
        client.login()
        print("Connexion EcoPart établie.", flush=True)
        for project_id in project_ids:
            try:
                print(f"Résolution EcoTaxa {project_id}…", flush=True)
                samples = client.search_samples(
                    ecotaxa_project_id=project_id, timeout=15.0
                )
                if not samples:
                    unresolved.append(f"EcoTaxa {project_id}: aucun sample lié (filt_proj)")
                    continue
                metadata = client.get_sample_metadata(samples[0]["id"], timeout=15.0)
                ecopart_id = metadata.get("ecopart_project_id")
                if ecopart_id is None:
                    unresolved.append(f"EcoTaxa {project_id}: identifiant EcoPart absent du premier sample")
                    continue
                save_resolution(project_id, ecopart_project_id=int(ecopart_id),
                                resolution="lien serveur EcoTaxa↔EcoPart (filt_proj)",
                                status="resolved", ttl_seconds=2592000)
                resolved += 1
            except Exception as exc:
                unresolved.append(f"EcoTaxa {project_id}: {type(exc).__name__}: {exc}")
                continue
    print(f"Cache enrichi : {len(valid)} TSV importé(s), {resolved} correspondance(s) résolue(s).")
    for item in unresolved:
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
