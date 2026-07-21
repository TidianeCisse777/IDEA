"""EcoTaxa cache synchronization engine (M4).

Strategy: full sync (F1), per-project transaction (E3), 5 req/s aggregate
throttle, object cap 50k per project (P2). Pulls latitude/longitude plus
object date, time, and depth metadata
via ``POST /object_set/{id}/query`` paginated, aggregates time/depth metadata
and sample-level coordinate averages, and replaces the project's slice of
``samples_cache`` atomically.

Parallelism: HTTP fetches run in a ThreadPoolExecutor (default 8 workers);
SQLite writes stay in the main thread to avoid cross-thread connection
issues. A single ``_SharedRateLimiter`` caps the *aggregate* request rate across
all workers, so the last large project fetching alone uses the full budget
rather than the old per-worker ``rps / concurrency`` fraction. Incremental sync: each project carries a signature
(objcount, pctvalidated, pctclassified) read straight from `list_projects`;
projects whose signature did not change since the last sync are skipped.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from http.client import RemoteDisconnected
from collections.abc import Callable
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from contextlib import nullcontext

from core.ecotaxa_browser.cache.repo import (
    deferred_secondary_indexes,
    finish_sync_run,
    get_project_signature,
    is_samples_cache_empty,
    project_is_fully_unenriched,
    replace_project_samples,
    start_sync_run,
    upsert_project,
    upsert_project_schema,
    upsert_project_signature,
)
from core.ecotaxa_browser.schema import get_project_schema
from core.ecotaxa_browser.sample_metadata import normalize_sample_stats

_LOGGER = logging.getLogger(__name__)

_DEFAULT_WINDOW_SIZE = 5000   # kept for API backward-compat, no longer used
_DEFAULT_OBJECT_CAP = 50_000  # kept for API backward-compat, no longer used
_DEFAULT_RATE_LIMIT_RPS = 5.0
_DEFAULT_CONCURRENCY = 8
_DEFAULT_RETRY_ATTEMPTS = 3
_DEFAULT_RETRY_DELAY_SECONDS = 0.25
# Max sample ids per sample_taxo_stats GET. The endpoint takes the ids in the
# query string, so a whole large project (e.g. LOKI 2331, 2193 ids ≈ 26 KB URL)
# in one call trips the server's URI-length limit and silently drops the batch.
_TAXO_STATS_CHUNK = 150

_TRANSIENT_EXCEPTIONS = (
    requests.RequestException,
    ConnectionError,
    TimeoutError,
    RemoteDisconnected,
    OSError,
)


class _SharedRateLimiter:
    """Thread-safe aggregate rate limiter shared across all sync workers.

    Enforces at most ``rps`` acquisitions per second *across every thread*, so a
    single active worker uses the whole budget instead of the old static
    ``rps / worker_count`` split — where a lone straggler project (e.g. the
    largest one, still fetching after the others finished) crawled at 1/8 of the
    allowance while 7 workers sat idle. The aggregate cap still protects EcoTaxa.
    """

    def __init__(self, rps: float) -> None:
        self._min_interval = 1.0 / rps if rps and rps > 0 else 0.0
        self._lock = threading.Lock()
        self._next_time = 0.0

    def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = now if now >= self._next_time else self._next_time
            self._next_time = start + self._min_interval
            wait = start - now
        if wait > 0:
            time.sleep(wait)


def _with_retries(
    operation: Callable[[], Any],
    *,
    attempts: int = _DEFAULT_RETRY_ATTEMPTS,
    delay_seconds: float = _DEFAULT_RETRY_DELAY_SECONDS,
) -> Any:
    """Retry transient EcoTaxa HTTP failures a small number of times."""
    last_exc: BaseException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return operation()
        except _TRANSIENT_EXCEPTIONS as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            time.sleep(delay_seconds)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("unreachable retry state")


def _fetch_project_samples(
    client: Any,
    *,
    project_id: int,
    window_size: int = _DEFAULT_WINDOW_SIZE,   # unused, kept for API compat
    object_cap: int = _DEFAULT_OBJECT_CAP,     # unused, kept for API compat
    rate_limit_rps: float = _DEFAULT_RATE_LIMIT_RPS,
    rate_limiter: "_SharedRateLimiter | None" = None,
) -> tuple[list[dict], str | None]:
    """HTTP-only: fetch sample metadata + taxo stats. Returns (samples, instrument).

    No object download. Temporal data (date_min/date_max) comes from the
    ``sampledatetime`` free field retrieved via individual get_sample calls.
    depth_min/depth_max are not populated.
    """
    project_meta = _with_retries(lambda: client.get_project(project_id))
    instrument = project_meta.get("instrument")
    limiter = rate_limiter if rate_limiter is not None else _SharedRateLimiter(rate_limit_rps)
    sample_metadata = _fetch_project_sample_metadata(
        client, project_id=project_id, rate_limiter=limiter
    )
    taxo_stats = _fetch_project_taxo_stats(
        client, project_id=project_id, sample_ids=set(sample_metadata)
    )
    samples = []
    for sid, meta in sample_metadata.items():
        sample_lat = meta.pop("sample_lat", None)
        sample_lon = meta.pop("sample_lon", None)
        sample_date = meta.pop("sample_date", None)
        sample_time = meta.pop("sample_time", None)
        stat = taxo_stats.get(sid)
        authoritative_total = stat["object_count"] if stat is not None else None
        has_date = sample_date is not None
        has_time = sample_time is not None
        datetime_iso = f"{sample_date}T{sample_time}" if has_date and has_time else None
        if has_date and has_time:
            temporal_precision = "datetime"
        elif has_date:
            temporal_precision = "date"
        else:
            temporal_precision = "none"
        sample_row = {
            "sample_id": sid,
            "lat_avg": sample_lat,
            "lon_avg": sample_lon,
            "object_count": authoritative_total,
            "instrument": instrument,
            "date_min": sample_date,
            "date_max": sample_date,
            "time_min": sample_time,
            "time_max": sample_time,
            "datetime_min": datetime_iso,
            "datetime_max": datetime_iso,
            "depth_min": None,
            "depth_max": None,
            "missing_date_count": 0 if has_date else 1,
            "missing_time_count": 0 if has_time else 1,
            "missing_depth_min_count": 1,
            "missing_depth_max_count": 1,
            "metadata_objects_scanned": 0,
            "temporal_precision": temporal_precision,
            "metadata_complete": has_date,
            "metadata_coverage_pct": 100.0 if has_date else 0.0,
            "depth_complete": False,
            "query_total_objects": None,
            "count_discrepancy": False,
            **meta,
        }
        if stat is not None:
            sample_row["nb_validated"] = stat["nb_validated"]
            sample_row["nb_predicted"] = stat["nb_predicted"]
            sample_row["nb_dubious"] = stat["nb_dubious"]
            sample_row["nb_unclassified"] = stat["nb_unclassified"]
            sample_row["used_taxa"] = stat["used_taxa"]
        samples.append(sample_row)
    return samples, instrument


def _fetch_project_taxo_stats(
    client: Any, *, project_id: int, sample_ids: set[int]
) -> dict[int, dict]:
    """Per-sample V/P/D/U counts + taxa present, via ``sample_taxo_stats``.

    Batched EcoTaxa call — no object download, no object-scan cap. The ids are
    chunked (``_TAXO_STATS_CHUNK``) because the endpoint carries them in the
    query string: a whole large project in one GET trips the server URI-length
    limit and drops the batch. A failing chunk is skipped (its samples stay
    NULL) so one bad batch never voids the rest; the sync still succeeds on the
    scan-only path when the method is absent.
    """
    if not sample_ids or not hasattr(client, "sample_taxo_stats"):
        return {}
    ordered = sorted(sample_ids)
    stats: dict[int, dict] = {}
    for start in range(0, len(ordered), _TAXO_STATS_CHUNK):
        chunk = ordered[start : start + _TAXO_STATS_CHUNK]
        try:
            raw = _with_retries(lambda c=chunk: client.sample_taxo_stats(c))
        except Exception:  # noqa: BLE001 — stats are an enrichment, never fatal
            continue
        if not isinstance(raw, list):
            continue
        for row in raw:
            if not isinstance(row, dict):
                continue
            try:
                normalized = normalize_sample_stats(row)
                sid = int(normalized["sample_id"])
            except (KeyError, TypeError, ValueError):
                continue
            stats[sid] = {
                **normalized,
                "used_taxa": (
                    json.dumps(normalized["used_taxa"])
                    if normalized["used_taxa"] else None
                ),
            }
    return stats


def _fetch_project_sample_metadata(
    client: Any,
    *,
    project_id: int,
    rate_limiter: "_SharedRateLimiter | None" = None,  # unused, kept for API compat
) -> dict[int, dict]:
    """Fetch sample metadata via list_samples (one bulk call per project).

    list_samples provides lat/lon and orig_id. free_columns is always {} from
    this endpoint, so station/profile are derived from orig_id heuristics.
    date_min/date_max are not populated here (no object download, no per-sample
    date API at the sample level).
    """
    if not hasattr(client, "list_samples"):
        return {}
    raw_samples = _with_retries(lambda: client.list_samples(project_id))
    metadata: dict[int, dict] = {}
    for sample in raw_samples or []:
        try:
            sample_id = int(sample["sampleid"])
        except (KeyError, TypeError, ValueError):
            continue
        original_id = _as_optional_str(sample.get("orig_id"))
        free_fields: dict = {}  # list_samples always returns free_columns: {}
        station_id = _first_optional_str(
            free_fields,
            ("stationid", "station_id", "station", "sample_stationid"),
        )
        profile_id = _first_optional_str(
            free_fields,
            ("profileid", "profile_id", "profile", "sample_profileid"),
        )
        if original_id and profile_id is None:
            profile_id = _cast_from_orig_id(original_id)
        if original_id and station_id is None:
            station_id = _station_from_orig_id(original_id)
        metadata[sample_id] = {
            "original_id": original_id,
            "sample_lat": _as_float(sample.get("latitude")),
            "sample_lon": _as_float(sample.get("longitude")),
            "station_id": station_id,
            "profile_id": profile_id,
            "sample_date": None,
            "sample_time": None,
            "free_fields_json": json.dumps(free_fields, ensure_ascii=False, sort_keys=True),
        }
    return metadata


_CAST_SUFFIX_RE = re.compile(r"_\d+$")
# EcoTaxa appends a literal "Comments:" trailer to every project description.
_ECOTAXA_COMMENTS_TRAILER = re.compile(r"\s*Comments:\s*$", re.IGNORECASE)
# sampledatetime free-field format: "YYYYMMDD-HHMMSS" or "YYYYMMDD"
_SAMPLEDATETIME_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$")
_SAMPLEDATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def _parse_sample_datetime(raw: str | None) -> tuple[str | None, str | None]:
    """Parse EcoTaxa sampledatetime free field → (date_iso, time_iso).

    Accepts "YYYYMMDD-HHMMSS" (full datetime) or "YYYYMMDD" (date only).
    Returns (None, None) when the value is absent or unparseable.
    """
    if not raw:
        return None, None
    raw = raw.strip()
    m = _SAMPLEDATETIME_RE.match(raw)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return f"{y}-{mo}-{d}", f"{h}:{mi}:{s}"
    m = _SAMPLEDATE_RE.match(raw)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}", None
    return None, None


def _clean_ecotaxa_description(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = _ECOTAXA_COMMENTS_TRAILER.sub("", raw).strip()
    return cleaned or None
# Cruise prefix patterns: am_leg2_, amundsen2024_, gn2015_, uvp6_sn..._2024_am_leg2_, etc.
_CRUISE_PREFIX_RE = re.compile(
    r"^(?:uvp\d*_sn[^_]+_\d+_)?(?:[a-z]{1,6}\d{0,4}_(?:leg\d+_)?)",
    re.IGNORECASE,
)


def _cast_from_orig_id(orig_id: str) -> str:
    """Cast identity from orig_id: drop trailing ``_<n>`` sample index."""
    return _CAST_SUFFIX_RE.sub("", orig_id) or orig_id


def _station_from_orig_id(orig_id: str) -> str | None:
    """Best-effort station name from orig_id when EcoTaxa provides no station field.

    Strips known cruise prefixes (``am_leg2_``, ``gn2015_``, …) and the
    trailing cast-index suffix, returning the middle token as a normalized
    lowercase key. Returns None when the result is empty or looks like a
    bare numeric.
    Examples:
      am_leg2_tcaqf3_2  → tcaqf3   (matches NeoLabs TCA-QF3 after normalization)
      am_leg2_b5        → b5
      gn2015_l2_012     → l2
    """
    stripped = _CRUISE_PREFIX_RE.sub("", orig_id)
    station = _CAST_SUFFIX_RE.sub("", stripped).strip("_")
    if not station or station.isdigit():
        return None
    return station.lower()


def _first_optional_str(values: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _as_optional_str(values.get(key))
        if value is not None:
            return value
    return None


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sync_project(
    conn: sqlite3.Connection,
    client: Any,
    *,
    project_id: int,
    last_synced: str,
    window_size: int = _DEFAULT_WINDOW_SIZE,
    object_cap: int = _DEFAULT_OBJECT_CAP,
    rate_limit_rps: float = _DEFAULT_RATE_LIMIT_RPS,
) -> int:
    """Backward-compatible single-project sync (fetch + DB write)."""
    samples, _instrument = _fetch_project_samples(
        client,
        project_id=project_id,
        window_size=window_size,
        object_cap=object_cap,
        rate_limit_rps=rate_limit_rps,
    )
    replace_project_samples(
        conn,
        project_id=project_id,
        samples=samples,
        last_synced=last_synced,
    )
    return len(samples)


def _snapshot_project_schema(
    conn: sqlite3.Connection,
    client: Any,
    *,
    project_id: int,
    last_synced: str,
) -> None:
    """Cache the get_project_schema output for one project."""
    import core.ecotaxa_browser.schema as schema_module

    original_factory = schema_module.EcotaxaClient
    schema_module.EcotaxaClient = lambda: client  # type: ignore[assignment]
    try:
        schema = get_project_schema(project_id, client=client)
    finally:
        schema_module.EcotaxaClient = original_factory  # type: ignore[assignment]

    upsert_project_schema(
        conn,
        project_id=project_id,
        schema_json=json.dumps(schema),
        last_synced=last_synced,
    )


def _fetch_project_schema_json(client: Any, *, project_id: int) -> str:
    """HTTP-only schema snapshot for one project."""
    schema = _with_retries(lambda: get_project_schema(project_id, client=client))
    return json.dumps(schema)


def _project_signature(project_meta: dict) -> tuple | None:
    """Coarse change tag derived from list_projects payload (no extra HTTP call)."""
    signature_values = [
        project_meta.get(key)
        for key in ("objcount", "pctvalidated", "pctclassified")
    ]
    if all(value in (None, "") for value in signature_values):
        return None
    return (
        int(project_meta.get("objcount") or 0),
        round(float(project_meta.get("pctvalidated") or 0.0), 4),
        round(float(project_meta.get("pctclassified") or 0.0), 4),
    )


def _parse_extra_project_ids(raw: str | None) -> set[int]:
    """Parse the ECOTAXA_EXTRA_PROJECT_IDS allowlist (comma/space separated)."""
    ids: set[int] = set()
    for token in re.split(r"[,\s]+", (raw or "").strip()):
        if not token:
            continue
        try:
            ids.add(int(token))
        except ValueError:
            continue
    return ids


def _extra_syncable_project_ids(
    conn: sqlite3.Connection,
    listed_ids: set[int],
) -> list[int]:
    """Project IDs to sync beyond ``list_projects()``.

    The EcoTaxa account's project search is both narrow (it omits projects that
    are readable by ID) and unstable (its result set varies between calls), so a
    project can silently drop out of the nightly sync. To keep coverage stable we
    also sync every project already known locally (schema or samples cached) plus
    an explicit ``ECOTAXA_EXTRA_PROJECT_IDS`` operator allowlist.
    """
    known: set[int] = set(_parse_extra_project_ids(os.getenv("ECOTAXA_EXTRA_PROJECT_IDS")))
    for table in ("project_schemas_cache", "samples_cache"):
        try:
            for row in conn.execute(f"SELECT DISTINCT project_id FROM {table}"):
                known.add(int(row[0]))
        except sqlite3.Error:
            continue
    return sorted(known - listed_ids)


def run_full_sync(
    conn: sqlite3.Connection,
    client: Any,
    *,
    now_iso: str,
    window_size: int = _DEFAULT_WINDOW_SIZE,
    object_cap: int = _DEFAULT_OBJECT_CAP,
    rate_limit_rps: float = _DEFAULT_RATE_LIMIT_RPS,
    concurrency: int = _DEFAULT_CONCURRENCY,
    force: bool = False,
    client_factory: Callable[[], Any] | None = None,
) -> dict:
    """Full sync across every project the service account sees.

    - Parallel HTTP fetches via ThreadPoolExecutor (default 8 workers).
      When ``client_factory`` is supplied, each worker thread gets its own
      logged-in client/session; sqlite writes stay in the main thread
      (single connection).
    - Incremental: skip projects whose (objcount, pctvalidated, pctclassified)
      signature matches the cached value. Pass ``force=True`` to bypass.
    - Per-project transactional — a failure on one project records the error
      and leaves the others committed.
    """
    run_id = start_sync_run(conn, started_at=now_iso)

    client.login()
    projects = client.list_projects()

    projects_synced = 0
    projects_skipped = 0
    samples_synced = 0
    failures: list[str] = []

    pending: list[tuple[int, dict, tuple | None]] = []
    seen_ids: set[int] = set()

    def _consider(project_id: int, project_meta: dict) -> None:
        nonlocal projects_skipped
        seen_ids.add(project_id)
        signature = _project_signature(project_meta)
        if (
            signature is not None
            and not force
            and get_project_signature(conn, project_id) == signature
            # Self-heal: never skip a project whose local rows never got their
            # taxo stats (whole-batch drop, e.g. the pre-chunking 2193-id GET
            # for 2331). An unchanged EcoTaxa signature does not mean the local
            # cache is complete.
            and not project_is_fully_unenriched(conn, project_id)
        ):
            projects_skipped += 1
            return
        pending.append((project_id, project_meta, signature))

    for project_meta in projects:
        try:
            project_id = int(
                project_meta.get("projid")
                or project_meta.get("project_id")
            )
        except (TypeError, ValueError):
            continue
        _consider(project_id, project_meta)

    # Extend beyond the (narrow, unstable) project search: keep already-known and
    # operator-allowlisted projects in the sync even when list_projects() omits
    # them. Their metadata comes from a direct get_project call.
    extra_failures: list[str] = []
    for extra_id in _extra_syncable_project_ids(conn, seen_ids):
        try:
            extra_meta = client.get_project(extra_id)
        except Exception as exc:  # noqa: BLE001 — a known project we could not refresh
            # Soft failure: a previously-known project may have been removed or
            # made private. Record a note but never let it fail the whole run —
            # the reachable projects are still valid.
            extra_failures.append(f"{extra_id}: get_project {type(exc).__name__}: {exc}")
            _LOGGER.warning("sync extra project %s get_project failed: %s", extra_id, exc)
            continue
        if not isinstance(extra_meta, dict):
            continue
        extra_meta.setdefault("projid", extra_id)
        _consider(extra_id, extra_meta)

    worker_state = threading.local()

    def worker_client() -> Any:
        if client_factory is None:
            return client
        thread_client = getattr(worker_state, "client", None)
        if thread_client is None:
            thread_client = client_factory()
            thread_client.login()
            worker_state.client = thread_client
        return thread_client

    effective_concurrency = max(1, concurrency)
    # One aggregate limiter shared by all workers: the whole run stays under
    # rate_limit_rps, but any single active worker (notably the last, largest
    # project fetching alone) uses the full budget instead of rps/concurrency.
    shared_limiter = _SharedRateLimiter(rate_limit_rps)

    def fetch_one(args: tuple[int, dict, tuple | None]):
        project_id, _meta, _sig = args
        thread_client = worker_client()
        samples, _instrument = _fetch_project_samples(
            thread_client,
            project_id=project_id,
            window_size=window_size,
            object_cap=object_cap,
            rate_limit_rps=rate_limit_rps,
            rate_limiter=shared_limiter,
        )
        schema_json = _fetch_project_schema_json(thread_client, project_id=project_id)
        return project_id, samples, schema_json

    # First fill of an empty cache: defer secondary-index maintenance and
    # rebuild the indexes once at the end (~5x faster to fill a large cache
    # from scratch). An incremental refresh of a populated cache keeps its
    # indexes so concurrent reads stay fast — see deferred_secondary_indexes.
    first_fill = is_samples_cache_empty(conn)
    index_ctx = (
        deferred_secondary_indexes(conn) if first_fill else nullcontext()
    )

    if pending:
        with index_ctx, ThreadPoolExecutor(
            max_workers=effective_concurrency
        ) as executor:
            futures = {executor.submit(fetch_one, item): item for item in pending}
            for future in as_completed(futures):
                project_id, _meta, signature = futures[future]
                try:
                    pid, samples, schema_json = future.result()
                except Exception as exc:  # noqa: BLE001 — record per-project failure
                    failures.append(f"{project_id}: {type(exc).__name__}: {exc}")
                    _LOGGER.warning("sync project %s failed: %s", project_id, exc)
                    continue
                try:
                    replace_project_samples(
                        conn,
                        project_id=pid,
                        samples=samples,
                        last_synced=now_iso,
                    )
                    upsert_project_schema(
                        conn,
                        project_id=pid,
                        schema_json=schema_json,
                        last_synced=now_iso,
                    )
                    _contact = _meta.get("contact") or {}
                    upsert_project(
                        conn,
                        project_id=pid,
                        title=str(_meta.get("title") or pid),
                        instrument=_meta.get("instrument"),
                        description=_clean_ecotaxa_description(_meta.get("comments")),
                        status=_meta.get("status"),
                        contact_name=_contact.get("name") if isinstance(_contact, dict) else None,
                        objcount=int(_meta["objcount"]) if _meta.get("objcount") is not None else None,
                        pctvalidated=float(_meta["pctvalidated"]) if _meta.get("pctvalidated") is not None else None,
                        pctclassified=float(_meta["pctclassified"]) if _meta.get("pctclassified") is not None else None,
                        last_synced=now_iso,
                    )
                    if signature is not None:
                        upsert_project_signature(
                            conn,
                            project_id=pid,
                            objcount=signature[0],
                            pctvalidated=signature[1],
                            pctclassified=signature[2],
                            last_synced=now_iso,
                        )
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{pid}: {type(exc).__name__}: {exc}")
                    _LOGGER.warning("write project %s failed: %s", pid, exc)
                    continue
                samples_synced += len(samples)
                projects_synced += 1

    if failures:
        status = "partial" if projects_synced > 0 else "failed"
    else:
        # Reachable projects all synced/skipped cleanly; a stale extra project
        # downgrades to "partial" (with a note) but never to "failed".
        status = "partial" if extra_failures else "ok"
    error_message = "; ".join(failures + extra_failures) or None

    finish_sync_run(
        conn,
        run_id=run_id,
        ended_at=now_iso,
        status=status,
        projects_synced=projects_synced,
        samples_synced=samples_synced,
        error_message=error_message,
    )
    return {
        "run_id": run_id,
        "status": status,
        "projects_synced": projects_synced,
        "projects_skipped": projects_skipped,
        "samples_synced": samples_synced,
        "error_message": error_message,
    }
