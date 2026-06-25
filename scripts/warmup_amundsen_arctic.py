"""Pre-fetch every Amundsen ERDDAP tile × month in the arctic zone.

Builds an exhaustive on-disk cache so any future `enrich_with_amundsen_ctd`
on an arctic file is served entirely from `data/erddap_cache.sqlite`.

Usage:
    PYTHONPATH=. python scripts/warmup_amundsen_arctic.py
    PYTHONPATH=. python scripts/warmup_amundsen_arctic.py --workers 8
    PYTHONPATH=. python scripts/warmup_amundsen_arctic.py --vars TE90,PSAL
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.canonical_grid import (
    canonicalize_amundsen_query,
    iter_arctic_tiles,
    iter_months,
)
from core.erddap_cache import cache_get, cache_path, cache_set
from tools.amundsen_sources import _fetch_amundsen_bbox

# Amundsen CTD operational range
_START_YEAR, _START_MONTH = 2014, 7
_END_YEAR, _END_MONTH = 2024, 10

_DEFAULT_VARIABLES = ["TE90", "PSAL", "SIGT", "OXYM", "pH", "NTRA", "FLOR"]
_DEFAULT_ZONE = {
    "lat_min": 50.0, "lat_max": 85.0,
    "lon_min": -170.0, "lon_max": -45.0,
}


def _build_jobs(variables: list[str]) -> list[tuple[dict, dict, list[str]]]:
    tiles = iter_arctic_tiles(**_DEFAULT_ZONE)
    months = iter_months(_START_YEAR, _START_MONTH, _END_YEAR, _END_MONTH)
    jobs: list[tuple[dict, dict, list[str]]] = []
    for tile in tiles:
        for month in months:
            jobs.append((tile, month, variables))
    return jobs


def _job_already_cached(tile: dict, month: dict, variables: list[str]) -> bool:
    canon_bbox, canon_time, canon_vars = canonicalize_amundsen_query(
        bbox=tile, time_window=month, variables=variables
    )
    cache_key = {
        "bbox": canon_bbox,
        "time_window": canon_time,
        "variables": canon_vars,
    }
    return cache_get("amundsen_bbox", cache_key) is not None


def _run_job(job: tuple[dict, dict, list[str]]) -> tuple[int, str | None]:
    tile, month, variables = job
    if _job_already_cached(tile, month, variables):
        return -1, None  # skipped
    try:
        df = _fetch_amundsen_bbox(
            bbox=tile,
            time_window=month,
            variables=variables,
            pres_range=None,
        )
        return len(df), None
    except Exception as exc:
        return 0, f"{tile}/{month['start'][:7]}: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--vars", type=str, default=",".join(_DEFAULT_VARIABLES))
    args = parser.parse_args()
    variables = [v.strip() for v in args.vars.split(",") if v.strip()]

    jobs = _build_jobs(variables)
    print(f"Cache file: {cache_path()}")
    print(f"Zone: lat [{_DEFAULT_ZONE['lat_min']}, {_DEFAULT_ZONE['lat_max']}] × "
          f"lon [{_DEFAULT_ZONE['lon_min']}, {_DEFAULT_ZONE['lon_max']}]")
    print(f"Months: {_START_YEAR}-{_START_MONTH:02d} → {_END_YEAR}-{_END_MONTH:02d}")
    print(f"Variables: {variables}")
    print(f"Total (tile × month) jobs: {len(jobs)}")
    print(f"Workers: {args.workers}")
    print("---", flush=True)

    t0 = time.perf_counter()
    done = 0
    cached = 0
    skipped = 0
    failed = 0
    total_rows = 0
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_run_job, job) for job in jobs]
        for fut in as_completed(futures):
            rows, error = fut.result()
            done += 1
            if rows == -1:
                skipped += 1
            elif error is not None:
                failed += 1
                errors.append(error)
            else:
                cached += 1
                total_rows += rows
            if done % 50 == 0 or done == len(jobs):
                elapsed = time.perf_counter() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(jobs) - done) / rate if rate > 0 else 0
                print(
                    f"[{done}/{len(jobs)}] cached={cached} skipped={skipped} "
                    f"failed={failed} rows={total_rows:,} "
                    f"elapsed={elapsed:.0f}s rate={rate:.1f}/s eta={eta:.0f}s",
                    flush=True,
                )

    elapsed = time.perf_counter() - t0
    print("---")
    print(f"Done in {elapsed:.0f}s")
    print(f"New cache entries:  {cached}")
    print(f"Already cached:     {skipped}")
    print(f"Failed:             {failed}")
    print(f"Total CTD rows:     {total_rows:,}")
    if cache_path().exists():
        size_mb = cache_path().stat().st_size / (1024 * 1024)
        print(f"Cache file size:    {size_mb:.1f} MB")
    if errors:
        print(f"\nFirst 5 errors:")
        for err in errors[:5]:
            print(f"  - {err}")


if __name__ == "__main__":
    main()
