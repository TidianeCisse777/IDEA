"""A/B the EcoTaxa cache *write* path under different bulk-load strategies.

Throwaway benchmark (never touches the real cache). Seeds the same 500k-row
project ladder through the real write path (repo.replace_project_samples) under
several PRAGMA / index strategies and reports write wall-time + rows/s, so we
can decide what to land in repo.open_connection before touching prod.

    python scripts/exp_write_pragmas.py            # 200 x 2500 = 500k rows
    python scripts/exp_write_pragmas.py 500 5000   # 2.5M rows

Baseline == current prod behaviour (synchronous=FULL default, all secondary
indexes present, one commit per project).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

from core.ecotaxa_browser.cache import repo
from scripts.sim_mcp_cache import _make_samples, _iso

_SECONDARY_INDEXES = {
    "idx_samples_project": "ON samples_cache(project_id)",
    "idx_samples_bbox": "ON samples_cache(lat_avg, lon_avg)",
    "idx_samples_date": "ON samples_cache(date_min, date_max)",
    "idx_samples_depth_max": "ON samples_cache(depth_max)",
}


def _fresh_path(tag: str) -> str:
    path = os.path.join(tempfile.gettempdir(), f"ecotaxa_write_exp_{tag}.sqlite")
    for ext in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(path + ext):
            os.remove(path + ext)
    return path


def _load(conn, n_projects: int, spp: int) -> None:
    now = _iso(0)
    base = 1
    for pid in range(1, n_projects + 1):
        samples = _make_samples(pid, spp, base)
        base += spp
        repo.replace_project_samples(
            conn, project_id=pid, samples=samples, last_synced=now
        )


def _drop_secondary_indexes(conn) -> None:
    for name in _SECONDARY_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    conn.commit()


def _create_secondary_indexes(conn) -> None:
    for name, cols in _SECONDARY_INDEXES.items():
        conn.execute(f"CREATE INDEX IF NOT EXISTS {name} {cols}")
    conn.commit()


def _report(tag: str, path: str, write_s: float, index_s: float, rows: int) -> None:
    size_mb = os.path.getsize(path) / (1024 * 1024)
    total = write_s + index_s
    line = (
        f"  {tag:<26} write {write_s:7.2f}s"
        f"{('  +idx ' + format(index_s, '5.2f') + 's') if index_s else '':<14}"
        f"  total {total:7.2f}s  ({rows / total:>8,.0f} rows/s)  {size_mb:6.1f} MB"
    )
    print(line)


def strat_baseline(path, n, spp):
    conn = repo.open_connection(path)          # busy_timeout only, sync=FULL
    repo.init_schema(conn)
    t0 = time.perf_counter()
    _load(conn, n, spp)
    w = time.perf_counter() - t0
    conn.close()
    return w, 0.0


def _tuned_conn(path, synchronous):
    conn = repo.open_connection(path)
    conn.execute(f"PRAGMA synchronous={synchronous}")
    conn.execute("PRAGMA cache_size=-65536")   # 64 MB page cache
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def strat_sync_normal(path, n, spp):
    conn = _tuned_conn(path, "NORMAL")
    repo.init_schema(conn)
    t0 = time.perf_counter()
    _load(conn, n, spp)
    w = time.perf_counter() - t0
    conn.close()
    return w, 0.0


def strat_sync_off(path, n, spp):
    conn = _tuned_conn(path, "OFF")
    repo.init_schema(conn)
    t0 = time.perf_counter()
    _load(conn, n, spp)
    w = time.perf_counter() - t0
    conn.close()
    return w, 0.0


def _deferred(path, n, spp, synchronous):
    conn = _tuned_conn(path, synchronous)
    repo.init_schema(conn)
    _drop_secondary_indexes(conn)
    t0 = time.perf_counter()
    _load(conn, n, spp)
    w = time.perf_counter() - t0
    t1 = time.perf_counter()
    _create_secondary_indexes(conn)
    idx = time.perf_counter() - t1
    conn.close()
    return w, idx


def strat_deferred_index(path, n, spp):
    """Load with only the PK, then build secondary indexes once at the end."""
    return _deferred(path, n, spp, "NORMAL")


def strat_deferred_off(path, n, spp):
    """Deferred index + synchronous=OFF — the combined best case."""
    return _deferred(path, n, spp, "OFF")


STRATS = {
    "baseline": ("baseline (prod)", strat_baseline),
    "normal": ("sync=NORMAL +cache", strat_sync_normal),
    "off": ("sync=OFF +cache", strat_sync_off),
    "deferred": ("deferred index (NORMAL)", strat_deferred_index),
    "deferred-off": ("deferred +sync=OFF", strat_deferred_off),
}


def main(argv):
    # Optional trailing "--only=key1,key2" filters which strategies run.
    only = None
    args = []
    for a in argv:
        if a.startswith("--only="):
            only = a.split("=", 1)[1].split(",")
        else:
            args.append(a)
    n = int(args[0]) if len(args) >= 1 else 200
    spp = int(args[1]) if len(args) >= 2 else 2500
    rows = n * spp
    keys = only or list(STRATS)
    print(f"\nWrite-path A/B — {n} projects x {spp} samples = {rows:,} rows\n")
    for key in keys:
        tag, fn = STRATS[key]
        path = _fresh_path(tag.split()[0])
        w, idx = fn(path, n, spp)
        _report(tag, path, w, idx, rows)
        os.remove(path)


if __name__ == "__main__":
    main(sys.argv[1:])
