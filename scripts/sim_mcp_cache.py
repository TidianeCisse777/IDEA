"""Simulate the MCP EcoTaxa cache under large projects / samples.

Builds a *throwaway* SQLite cache (never the real data/ecotaxa_cache.sqlite),
seeds N projects x M samples per project through the real repo write path
(replace_project_samples, i.e. the same transaction the sync engine uses),
then measures write time, on-disk size, and read latency for every cache
query path the MCP tools rely on.

Usage:
    python scripts/sim_mcp_cache.py                       # default scales
    python scripts/sim_mcp_cache.py 200 2500              # one scale: 200 projects x 2500 samples
    python scripts/sim_mcp_cache.py --keep 500 5000       # keep the DB file afterwards
"""

from __future__ import annotations

import os
import random
import sys
import tempfile
import time
from datetime import date, timedelta

from core.ecotaxa_browser.cache import repo

_INSTRUMENTS = ["UVP5", "UVP6", "Zooscan", "FlowCam", "IFCB"]
_RNG = random.Random(1234)


def _iso(day_offset: int) -> str:
    return (date(2015, 1, 1) + timedelta(days=day_offset)).isoformat()


def _make_samples(project_id: int, n: int, sample_base: int) -> list[dict]:
    """Generate n synthetic sample rows spread across a plausible arctic bbox."""
    instrument = _INSTRUMENTS[project_id % len(_INSTRUMENTS)]
    rows = []
    for i in range(n):
        lat = 45.0 + _RNG.random() * 35.0          # 45..80 N
        lon = -75.0 + _RNG.random() * 90.0         # -75..15
        d0 = _RNG.randint(0, 3650)
        rows.append(
            {
                "sample_id": sample_base + i,
                "lat_avg": round(lat, 4),
                "lon_avg": round(lon, 4),
                "date_min": _iso(d0),
                "date_max": _iso(d0 + _RNG.randint(0, 3)),
                "depth_min": round(_RNG.random() * 50, 1),
                "depth_max": round(50 + _RNG.random() * 950, 1),
                "original_id": f"P{project_id}_S{i}",
                "station_id": f"ST{_RNG.randint(1, 200)}",
                "profile_id": f"PR{_RNG.randint(1, 500)}",
                "object_count": _RNG.randint(100, 50_000),
                "instrument": instrument,
            }
        )
    return rows


def _time(fn, *, repeats: int = 3):
    """Return (median_ms, result_len) for a query callable."""
    best = []
    result_len = 0
    for _ in range(repeats):
        t0 = time.perf_counter()
        rows = list(fn())
        best.append((time.perf_counter() - t0) * 1000)
        result_len = len(rows)
    best.sort()
    return best[len(best) // 2], result_len


def build(conn, n_projects: int, samples_per_project: int) -> float:
    """Seed the cache; return total write wall-time in seconds."""
    repo.init_schema(conn)
    now = _iso(0)
    sample_base = 1
    t0 = time.perf_counter()
    for pid in range(1, n_projects + 1):
        samples = _make_samples(pid, samples_per_project, sample_base)
        sample_base += samples_per_project
        repo.replace_project_samples(
            conn, project_id=pid, samples=samples, last_synced=now
        )
        repo.upsert_project_signature(
            conn,
            project_id=pid,
            objcount=sum(s["object_count"] for s in samples),
            pctvalidated=_RNG.random(),
            pctclassified=_RNG.random(),
            last_synced=now,
        )
    return time.perf_counter() - t0


def read_paths(conn, n_projects: int, samples_per_project: int):
    """Exercise every cache read path used by MCP tools; return timing rows."""
    all_pids = list(range(1, n_projects + 1))
    subset_pids = all_pids[: max(1, n_projects // 10)]
    results = []

    ms, k = _time(lambda: repo.query_samples_in_bbox(
        conn, lat_min=55, lat_max=70, lon_min=-60, lon_max=-20))
    results.append(("bbox (mid arctic window)", ms, k))

    ms, k = _time(lambda: repo.query_samples_in_date_range(
        conn, date_from="2018-01-01", date_to="2019-12-31"))
    results.append(("date_range (2 years)", ms, k))

    ms, k = _time(lambda: repo.query_samples_filtered(
        conn,
        bbox=(55, 70, -60, -20),
        date_range=("2017-06-01", "2020-06-01"),
        instrument="UVP6",
        depth_max_gte=200.0))
    results.append(("filtered (bbox+date+instr+depth)", ms, k))

    ms, k = _time(lambda: [repo.query_project_envelopes(conn, subset_pids)])
    results.append((f"project_envelopes ({len(subset_pids)} projects)", ms, k))

    ms, k = _time(lambda: [repo.query_project_envelopes(conn, all_pids)])
    results.append((f"project_envelopes (all {n_projects})", ms, k))

    lookup_ids = list(range(1, min(1000, n_projects * samples_per_project)))
    ms, k = _time(lambda: [repo.lookup_sample_projects(conn, lookup_ids)])
    results.append((f"lookup_sample_projects ({len(lookup_ids)} ids)", ms, k))

    return results


def run_scale(n_projects: int, samples_per_project: int, keep: bool):
    path = os.path.join(
        tempfile.gettempdir() if not keep else "data",
        f"ecotaxa_cache_sim_{n_projects}x{samples_per_project}.sqlite",
    )
    if os.path.exists(path):
        os.remove(path)

    conn = repo.open_connection(path)
    write_s = build(conn, n_projects, samples_per_project)
    total_rows = conn.execute("SELECT COUNT(*) FROM samples_cache").fetchone()[0]
    conn.execute("ANALYZE")
    conn.commit()
    size_mb = os.path.getsize(path) / (1024 * 1024)

    print(f"\n{'='*70}")
    print(f"SCALE: {n_projects} projects x {samples_per_project} samples "
          f"= {total_rows:,} rows")
    print(f"{'='*70}")
    print(f"  write (sync path)   : {write_s:6.2f} s  "
          f"({total_rows / write_s:,.0f} rows/s)")
    print(f"  on-disk size        : {size_mb:6.1f} MB  "
          f"({size_mb * 1024 * 1024 / total_rows:,.0f} bytes/row)")
    print(f"  read paths (median of 3):")
    for label, ms, k in read_paths(conn, n_projects, samples_per_project):
        print(f"    {label:<40} {ms:8.2f} ms  -> {k:,} rows")

    conn.close()
    if not keep:
        os.remove(path)
    else:
        print(f"  kept DB at: {path}")


def _kept_db_path(n_projects, spp):
    return os.path.join("data", f"ecotaxa_cache_sim_{n_projects}x{spp}.sqlite")


def build_kept_db(n_projects, spp):
    """Build (or reuse) a persistent sim cache and return its path."""
    path = _kept_db_path(n_projects, spp)
    if not os.path.exists(path):
        conn = repo.open_connection(path)
        build(conn, n_projects, spp)
        conn.close()
    return path


def run_tool(n_projects, spp):
    """Drive the REAL cache tool (samples_in_region) on a big cache.

    Measures the full agent-facing path: SQL + Python post-processing +
    markdown assembly + result cap — not just the raw query.
    """
    path = build_kept_db(n_projects, spp)
    os.environ["ECOTAXA_CACHE_DB"] = path
    # Import AFTER setting the env var (path is read per-call, but be safe).
    from core.ecotaxa_browser.region import samples_in_region

    total = conn_count(path)
    print(f"\n{'='*70}")
    print(f"TOOL LAYER: samples_in_region on {total:,} rows "
          f"({n_projects} projects x {spp})")
    print(f"{'='*70}")

    calls = [
        ("wide bbox (whole arctic)",
         dict(bbox={"south": 45, "west": -75, "north": 80, "east": 15})),
        ("narrow bbox",
         dict(bbox={"south": 60, "west": -55, "north": 65, "east": -45})),
        ("bbox + 2-year window",
         dict(bbox={"south": 55, "west": -60, "north": 70, "east": -20},
              date_range={"from": "2018-01-01", "to": "2019-12-31"})),
        ("bbox + instrument + depth band",
         dict(bbox={"south": 55, "west": -60, "north": 70, "east": -20},
              instrument="UVP6", depth_min_gte=0, depth_max_lt=500)),
    ]
    for label, kwargs in calls:
        ms, n_out, note = _time_tool(samples_in_region, kwargs)
        print(f"  {label:<34} {ms:8.2f} ms  -> {n_out:>7} samples {note}")


def _time_tool(fn, kwargs, repeats=3):
    times = []
    n_out = 0
    note = ""
    for _ in range(repeats):
        t0 = time.perf_counter()
        try:
            res = fn(**kwargs)
            times.append((time.perf_counter() - t0) * 1000)
            if isinstance(res, dict):
                n_out = res.get("n_samples") or len(res.get("samples", []) or [])
                if res.get("sync_in_progress"):
                    note = "[STALE: sync running]"
                if res.get("truncated") or res.get("capped"):
                    note = "[CAPPED]"
        except Exception as exc:  # noqa: BLE001
            times.append((time.perf_counter() - t0) * 1000)
            note = f"[{type(exc).__name__}: {getattr(exc, 'code', exc)}]"
    times.sort()
    return times[len(times) // 2], n_out, note


def conn_count(path):
    conn = repo.open_connection(path)
    n = conn.execute("SELECT COUNT(*) FROM samples_cache").fetchone()[0]
    conn.close()
    return n


def run_concurrent(n_projects, spp, prepopulate):
    """Read the cache through the tool WHILE a sync writes to it.

    prepopulate=False -> first-ever fill: expect SYNC_IN_PROGRESS refusals.
    prepopulate=True  -> refresh: expect stale-but-served reads + maybe
    'database is locked' during each project's write transaction.
    """
    import sqlite3
    import threading
    from core.ecotaxa_browser.observations import EcoTaxaBrowserError

    path = os.path.join("data", "ecotaxa_cache_sim_concurrent.sqlite")
    _remove_db(path)
    os.environ["ECOTAXA_CACHE_DB"] = path
    from core.ecotaxa_browser.region import samples_in_region

    wconn = repo.open_connection(path)
    repo.init_schema(wconn)
    now = _iso(0)
    if prepopulate:
        # Seed one project so the cache is non-empty before the sync starts.
        seed = _make_samples(1, spp, 1)
        repo.replace_project_samples(wconn, project_id=1, samples=seed,
                                     last_synced=now)

    counters = {"ok": 0, "stale": 0, "sync_in_progress": 0,
                "locked": 0, "empty": 0, "other": 0}
    stop = threading.Event()

    def writer():
        c = repo.open_connection(path)
        repo.start_sync_run(c, started_at=now)
        base = spp + 1
        for pid in range(1, n_projects + 1):
            rows = _make_samples(pid, spp, base)
            base += spp
            repo.replace_project_samples(c, project_id=pid, samples=rows,
                                         last_synced=now)
        repo.finish_sync_run(c, run_id=1, ended_at=now, status="ok",
                             projects_synced=n_projects, samples_synced=base,
                             error_message=None)
        c.close()
        stop.set()

    t = threading.Thread(target=writer)
    t0 = time.perf_counter()
    t.start()
    reads = 0
    while not stop.is_set():
        reads += 1
        try:
            res = samples_in_region(
                bbox={"south": 45, "west": -75, "north": 80, "east": 15})
            if res.get("sync_in_progress"):
                counters["stale"] += 1
            else:
                counters["ok"] += 1
        except EcoTaxaBrowserError as exc:
            code = getattr(exc, "code", "")
            if code == "SYNC_IN_PROGRESS":
                counters["sync_in_progress"] += 1
            elif code == "CACHE_EMPTY":
                counters["empty"] += 1
            else:
                counters["other"] += 1
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc):
                counters["locked"] += 1
            else:
                counters["other"] += 1
    t.join()
    elapsed = time.perf_counter() - t0

    mode = "REFRESH (cache pre-populated)" if prepopulate else "FIRST FILL (empty cache)"
    print(f"\n{'='*70}")
    print(f"CONCURRENT — {mode}: sync {n_projects}x{spp} while reading")
    print(f"{'='*70}")
    print(f"  sync wall-time      : {elapsed:6.2f} s")
    print(f"  reads attempted     : {reads}")
    for k, v in counters.items():
        if v:
            print(f"    {k:<18}: {v}")
    wconn.close()
    _remove_db(path)


def _remove_db(path):
    """Remove a SQLite DB and any WAL/SHM sidecars."""
    for ext in ("", "-wal", "-shm"):
        try:
            os.remove(path + ext)
        except FileNotFoundError:
            pass


def main(argv):
    if argv and argv[0] == "tool":
        rest = [a for a in argv[1:]]
        n, s = (int(rest[0]), int(rest[1])) if len(rest) >= 2 else (200, 2500)
        run_tool(n, s)
        return
    if argv and argv[0] == "concurrent":
        rest = [a for a in argv[1:]]
        n, s = (int(rest[0]), int(rest[1])) if len(rest) >= 2 else (200, 2500)
        run_concurrent(n, s, prepopulate=False)
        run_concurrent(n, s, prepopulate=True)
        return

    keep = "--keep" in argv
    args = [a for a in argv if a != "--keep"]
    if len(args) == 2:
        scales = [(int(args[0]), int(args[1]))]
    else:
        # Default ladder: current -> big -> very big. Last one hits the
        # 50k object cap territory in row count (500 x 5000 = 2.5M rows).
        scales = [
            (6, 100),        # ~ current real cache
            (50, 1000),      # 50k rows
            (200, 2500),     # 500k rows
            (500, 5000),     # 2.5M rows
        ]
    for n_projects, spp in scales:
        run_scale(n_projects, spp, keep)


if __name__ == "__main__":
    main(sys.argv[1:])
