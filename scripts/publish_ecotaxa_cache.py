#!/usr/bin/env python3
"""Package a validated EcoTaxa cache and optionally upload it to GitHub."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Support direct execution from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.ecotaxa_browser.cache.distribution import (
    CacheValidationError,
    build_cache_bundle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=Path("data/ecotaxa_cache.sqlite"),
        help="validated SQLite cache to package",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist/ecotaxa-cache"),
        help="directory receiving manifest.json and the gzip archive",
    )
    parser.add_argument("--repository", help="GitHub repository, e.g. owner/repo")
    parser.add_argument("--tag", help="immutable GitHub release tag")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="upload the generated assets using the authenticated GitHub CLI",
    )
    return parser.parse_args()


def publish(repository: str, tag: str, manifest: Path, archive: Path) -> None:
    """Create or update a release using the maintainer's GitHub CLI session."""
    if shutil.which("gh") is None:
        raise RuntimeError("GitHub CLI `gh` is required to publish a cache release")
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
                "--title", f"EcoTaxa cache {tag}",
                "--notes", "Validated EcoTaxa SQLite cache for IDEA consumers.",
            ],
            check=True,
        )
    subprocess.run(
        ["gh", "release", "upload", tag, str(manifest), str(archive), "--clobber", "--repo", repository],
        check=True,
    )


def main() -> int:
    args = parse_args()
    if args.publish and (not args.repository or not args.tag):
        raise RuntimeError("--publish requires --repository and --tag")
    try:
        manifest, archive = build_cache_bundle(args.cache_path, args.output_dir)
        if args.publish:
            publish(args.repository, args.tag, manifest, archive)
    except (CacheValidationError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[ecotaxa-cache] failed: {exc}", file=sys.stderr)
        return 1
    print(f"[ecotaxa-cache] manifest: {manifest}")
    print(f"[ecotaxa-cache] archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
