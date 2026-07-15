"""Politique de rétention des données de session.

- data/session_store/ : les paires .pkl/.json non touchées depuis N jours
  (défaut 30) sont supprimées. Ne concerne que le fallback fichiers — en
  Docker le session store vit dans PostgreSQL.
- data/checkpoints.sqlite : au-delà du seuil (défaut 500 Mo), le fichier est
  archivé dans data/archive/<date>/. L'agent doit être arrêté d'abord
  (`docker stop copepod_agent`), sinon le déplacement corrompt les écritures
  en cours — le script refuse si le fichier a bougé dans les 60 dernières
  secondes.

Dry-run par défaut ; passer --apply pour exécuter.

    python scripts/dev/prune_data.py                 # rapport seul
    python scripts/dev/prune_data.py --apply         # purge + archive
    python scripts/dev/prune_data.py --days 7 --apply
"""

from __future__ import annotations

import argparse
import shutil
import time
from datetime import date
from pathlib import Path

SESSION_STORE_DIR = Path("data/session_store")
CHECKPOINTS_DB = Path("data/checkpoints.sqlite")
ARCHIVE_DIR = Path("data/archive")


def prune_session_store(days: int, apply: bool) -> tuple[int, int]:
    """Supprime les entrées plus vieilles que `days`. Retourne (fichiers, octets)."""
    if not SESSION_STORE_DIR.is_dir():
        return 0, 0
    cutoff = time.time() - days * 86400
    count = 0
    freed = 0
    for path in sorted(SESSION_STORE_DIR.iterdir()):
        if path.suffix not in {".pkl", ".json"}:
            continue
        stat = path.stat()
        if stat.st_mtime >= cutoff:
            continue
        count += 1
        freed += stat.st_size
        if apply:
            path.unlink()
    return count, freed


def archive_checkpoints(max_mb: int, apply: bool) -> Path | None:
    """Archive checkpoints.sqlite s'il dépasse `max_mb`. Retourne la destination."""
    if not CHECKPOINTS_DB.is_file():
        return None
    stat = CHECKPOINTS_DB.stat()
    if stat.st_size <= max_mb * 1024 * 1024:
        return None
    if time.time() - stat.st_mtime < 60:
        raise SystemExit(
            f"{CHECKPOINTS_DB} a été modifié il y a moins de 60 s — l'agent écrit "
            "probablement dedans. Arrêter d'abord : docker stop copepod_agent"
        )
    dest = ARCHIVE_DIR / date.today().isoformat() / CHECKPOINTS_DB.name
    if apply:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(CHECKPOINTS_DB), str(dest))
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, help="rétention session_store en jours (défaut 30)")
    parser.add_argument("--max-checkpoints-mb", type=int, default=500, help="seuil d'archivage de checkpoints.sqlite (défaut 500)")
    parser.add_argument("--apply", action="store_true", help="exécute réellement (défaut : dry-run)")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    count, freed = prune_session_store(args.days, args.apply)
    print(f"[{mode}] session_store : {count} fichiers > {args.days} j ({freed / 1e6:.0f} Mo)")

    dest = archive_checkpoints(args.max_checkpoints_mb, args.apply)
    if dest is None:
        print(f"[{mode}] checkpoints.sqlite : sous le seuil de {args.max_checkpoints_mb} Mo, rien à faire")
    else:
        print(f"[{mode}] checkpoints.sqlite : archivé vers {dest}")
        print(f"[{mode}] redémarrer ensuite : docker start copepod_agent")


if __name__ == "__main__":
    main()
