#!/usr/bin/env python3
"""Package le cache EcoPart et publie ses assets validés sur une release GitHub."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.ecopart_cache_distribution import CacheBundleValidationError, build_cache_bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=Path("data/ecopart_cache"),
        help="répertoire cache EcoPart (manifest.sqlite et files/)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist/ecopart-cache"),
        help="répertoire recevant le manifest et l'archive",
    )
    parser.add_argument("--repository", help="dépôt GitHub owner/repo")
    parser.add_argument("--tag", help="tag de release GitHub")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="publie avec la session GitHub CLI authentifiée",
    )
    return parser.parse_args()


def publish(repository: str, tag: str, manifest: Path, archive: Path) -> None:
    """Create or update the release assets without ever handling a token."""
    if shutil.which("gh") is None:
        raise RuntimeError("GitHub CLI `gh` est requis pour publier le cache")
    view = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repository],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if view.returncode:
        subprocess.run(
            [
                "gh", "release", "create", tag,
                "--repo", repository,
                "--title", f"EcoPart cache {tag}",
                "--notes", "Cache EcoPart validé (mappings, aperçus et TSV) pour IDEA.",
            ],
            check=True,
        )
    subprocess.run(
        [
            "gh", "release", "upload", tag, str(manifest), str(archive),
            "--clobber", "--repo", repository,
        ],
        check=True,
    )


def main() -> int:
    args = parse_args()
    if args.publish and (not args.repository or not args.tag):
        print("--publish requiert --repository et --tag", file=sys.stderr)
        return 2
    try:
        manifest, archive = build_cache_bundle(args.cache_path, args.output_dir)
        if args.publish:
            publish(args.repository, args.tag, manifest, archive)
    except (CacheBundleValidationError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[ecopart-cache] échec : {exc}", file=sys.stderr)
        return 1
    print(f"[ecopart-cache] manifest : {manifest}")
    print(f"[ecopart-cache] archive : {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
