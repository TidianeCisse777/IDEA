"""HTTP facade for the EcoTaxa browser MCP server."""

from __future__ import annotations

import asyncio
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import partial
from typing import Any

import anyio
from fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from core.ecotaxa_browser.acquisitions import (
    get_acquisition,
    list_project_acquisitions,
)
from core.ecotaxa_browser.cache.repo import (
    cache_counts,
    cache_progress,
    init_schema,
    latest_sync_status,
    open_connection,
)
from core.ecotaxa_browser.cache.sync import run_full_sync
from core.ecotaxa_browser.objects import get_object, list_sample_objects
from core.ecotaxa_browser.projects import get_project
from core.ecotaxa_browser.samples import get_sample, list_project_samples
from core.ecotaxa_browser.column_distribution import get_column_distribution
from core.ecotaxa_browser.compare_schemas import compare_project_schemas
from core.ecotaxa_browser.errors import EcoTaxaBrowserError
from core.ecotaxa_browser.deployment_summary import summarize_sample_deployment
from core.ecotaxa_browser.observations import find_observations
from core.ecotaxa_browser.preview import preview_project
from core.ecotaxa_browser.region import (
    group_project_samples_by_region,
    projects_in_region,
    samples_in_region,
)
from core.ecotaxa_browser.project_summary import summarize_projects
from core.ecotaxa_browser.sample_summary import summarize_samples
from core.ecotaxa_browser.schema import get_project_schema
from core.ecotaxa_browser.search import search_projects
from core.ecotaxa_browser.taxa_stats import taxa_stats
from core.ecotaxa_browser.taxonomy import search_taxa, taxonomy_node
from tools.ecotaxa_client import EcotaxaClient

_MCP_PATHS = {"/mcp", "/mcp/"}
_ADMIN_PREFIX = "/admin/"
_DEFAULT_CACHE_DB = "data/ecotaxa_cache.sqlite"
_DEFAULT_SYNC_HOUR = 3


def build_nightly_scheduler(
    *,
    cache_db: str,
    runner,
    cron_hour: int = _DEFAULT_SYNC_HOUR,
):
    """Build an AsyncIOScheduler registering one daily sync job.

    Caller is responsible for starting/stopping the scheduler. Exposed at
    module level so tests can construct one without spinning up FastMCP.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        runner,
        "cron",
        hour=cron_hour,
        minute=0,
        args=[cache_db],
        id="ecotaxa-nightly-sync",
        replace_existing=True,
    )
    return scheduler


class BearerAuthMiddleware:
    """Protect the MCP transport and /admin endpoints with a Bearer token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path") or ""
            if path in _MCP_PATHS or path.startswith(_ADMIN_PREFIX):
                authorization = _header_value(scope, b"authorization")
                expected = f"Bearer {self.token}"
                if authorization is None or not secrets.compare_digest(
                    authorization, expected,
                ):
                    response = JSONResponse(
                        {"error": "unauthorized"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                    await response(scope, receive, send)
                    return

        await self.app(scope, receive, send)


def _header_value(scope: Scope, name: bytes) -> str | None:
    for header_name, value in scope.get("headers", []):
        if header_name.lower() == name:
            return value.decode("latin-1")
    return None


def _cache_db_path() -> str:
    return os.getenv("ECOTAXA_CACHE_DB", _DEFAULT_CACHE_DB)


def _open_cache() -> sqlite3.Connection:
    conn = open_connection(_cache_db_path())
    init_schema(conn)
    return conn


def _run_full_sync_with_real_client(cache_db: str) -> None:
    """Default sync runner — overridable in tests via monkeypatch."""
    client = EcotaxaClient()
    conn = open_connection(cache_db)
    try:
        init_schema(conn)
        now = datetime.now(timezone.utc).isoformat()
        run_full_sync(conn, client, now_iso=now, client_factory=EcotaxaClient)
    finally:
        conn.close()


def _compute_cache_age_hours(last_sync: dict | None) -> float | None:
    if not last_sync or not last_sync.get("ended_at"):
        return None
    try:
        ended = datetime.fromisoformat(last_sync["ended_at"])
    except (TypeError, ValueError):
        return None
    if ended.tzinfo is None:
        ended = ended.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ended
    return delta.total_seconds() / 3600.0


def create_app() -> ASGIApp:
    """Build the authenticated EcoTaxa MCP ASGI application."""
    token = os.getenv("MCP_AUTH_TOKEN")
    if not token:
        raise RuntimeError("MCP_AUTH_TOKEN must be configured")

    mcp = create_mcp()

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Any) -> JSONResponse:
        cache_payload: dict | None = None
        try:
            conn = _open_cache()
            try:
                counts = cache_counts(conn)
                last_sync = latest_sync_status(conn)
                cache_payload = {
                    "samples_indexed": counts["samples_indexed"],
                    "projects_indexed": counts["projects_indexed"],
                    "schemas_indexed": counts["schemas_indexed"],
                    "last_sync_status": (last_sync or {}).get("status"),
                    "cache_age_hours": _compute_cache_age_hours(last_sync),
                }
            finally:
                conn.close()
        except Exception:
            cache_payload = None
        return JSONResponse({"status": "ok", "cache": cache_payload})

    @mcp.custom_route("/admin/resync", methods=["POST"])
    async def admin_resync(request: Any) -> JSONResponse:
        cache_db = _cache_db_path()
        # Resolve runner lazily so tests can monkeypatch the module-level fn.
        import core.mcp.ecotaxa_server as _server_module
        runner = _server_module._run_full_sync_with_real_client

        loop = asyncio.get_running_loop()

        def _runner() -> None:
            try:
                runner(cache_db)
            except Exception:  # noqa: BLE001 — background task
                pass

        loop.run_in_executor(None, _runner)
        return JSONResponse(
            {"run_id": "pending", "status": "started"},
            status_code=202,
        )

    @mcp.custom_route("/admin/sync_runs/{run_id}", methods=["GET"])
    async def admin_sync_run_status(request: Any) -> JSONResponse:
        try:
            run_id = int(request.path_params["run_id"])
        except (KeyError, TypeError, ValueError):
            return JSONResponse({"error": "invalid run_id"}, status_code=400)
        try:
            conn = _open_cache()
            try:
                row = conn.execute(
                    "SELECT * FROM sync_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            finally:
                conn.close()
        except Exception:
            return JSONResponse({"error": "cache unavailable"}, status_code=503)
        if row is None:
            return JSONResponse({"error": "run not found"}, status_code=404)
        return JSONResponse(dict(row))

    http_app = mcp.http_app(path="/mcp")

    if os.getenv("ECOTAXA_NIGHTLY_SYNC", "true").lower() != "false":
        cache_db = _cache_db_path()
        cron_hour = int(os.getenv("ECOTAXA_SYNC_HOUR", str(_DEFAULT_SYNC_HOUR)))
        scheduler = build_nightly_scheduler(
            cache_db=cache_db,
            runner=_run_full_sync_with_real_client,
            cron_hour=cron_hour,
        )
        original_lifespan = http_app.router.lifespan_context

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _wrapped_lifespan(app):
            scheduler.start()
            try:
                async with original_lifespan(app) as state:
                    # Premier démarrage / cache vide → déclenche un sync
                    # immédiat en arrière-plan. Non bloquant : le serveur
                    # devient `healthy` tout de suite, le sync se termine
                    # quand il se termine.
                    try:
                        conn = _open_cache()
                        try:
                            counts = cache_counts(conn)
                            cache_empty = (
                                counts.get("samples_indexed", 0) == 0
                                and counts.get("projects_indexed", 0) == 0
                            )
                        finally:
                            conn.close()
                        if cache_empty:
                            loop = asyncio.get_running_loop()
                            loop.run_in_executor(
                                None, _run_full_sync_with_real_client, cache_db,
                            )
                    except Exception:
                        # On ne bloque pas le boot sur un sync auto-trigger
                        pass
                    yield state
            finally:
                scheduler.shutdown(wait=False)

        http_app.router.lifespan_context = _wrapped_lifespan

    return BearerAuthMiddleware(http_app, token)


def create_mcp() -> FastMCP:
    """Build the EcoTaxa MCP tool registry."""
    mcp = FastMCP("EcoTaxa Browser")

    @mcp.tool(name="search_projects")
    async def search_projects_tool(
        title: str | None = None,
        instrument: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        """Search accessible EcoTaxa projects before choosing data to export."""
        call = partial(
            search_projects,
            title=title,
            instrument=instrument,
            page=page,
            page_size=page_size,
        )
        return await anyio.to_thread.run_sync(call)

    @mcp.tool(name="get_project")
    async def get_project_tool(project_id: int) -> dict:
        """Return project metadata, stats, and a compact schema summary."""
        return await _run_sync(get_project, project_id=project_id)

    @mcp.tool(name="get_project_schema")
    async def get_project_schema_tool(
        project_id: int,
        verbose: bool = False,
        include_process: bool = False,
    ) -> dict:
        """Inspect the typed columns of a project before exporting.

        Returns sample/acquisition/object levels with fixed and free fields
        plus a flat ``labels_index`` for resolving ambiguous column names.
        """
        return await _run_sync(
            get_project_schema,
            project_id=project_id,
            verbose=verbose,
            include_process=include_process,
        )

    @mcp.tool(name="list_project_samples")
    async def list_project_samples_tool(
        project_id: int,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        """List one page of samples from a project."""
        return await _run_sync(
            list_project_samples,
            project_id=project_id,
            page=page,
            page_size=page_size,
        )

    @mcp.tool(name="get_sample")
    async def get_sample_tool(sample_id: int) -> dict:
        """Return one sample."""
        return await _run_sync(get_sample, sample_id=sample_id)

    @mcp.tool(name="list_project_acquisitions")
    async def list_project_acquisitions_tool(project_id: int) -> list[dict]:
        """List acquisitions from a project."""
        return await _run_sync(list_project_acquisitions, project_id=project_id)

    @mcp.tool(name="get_acquisition")
    async def get_acquisition_tool(acquisition_id: int) -> dict:
        """Return one acquisition."""
        return await _run_sync(get_acquisition, acquisition_id=acquisition_id)

    @mcp.tool(name="list_sample_objects")
    async def list_sample_objects_tool(
        sample_id: int,
        taxon: int | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        """List one page of objects from a sample."""
        return await _run_sync(
            list_sample_objects,
            sample_id=sample_id,
            taxon=taxon,
            status=status,
            page=page,
            page_size=page_size,
        )

    @mcp.tool(name="get_object")
    async def get_object_tool(object_id: int) -> dict:
        """Return an object with sample and acquisition context."""
        return await _run_sync(get_object, object_id=object_id)

    @mcp.tool(name="taxonomy_node")
    async def taxonomy_node_tool(taxon_id: int | None = None) -> dict | list[dict]:
        """Return taxonomy roots or one detailed node."""
        return await _run_sync(taxonomy_node, taxon_id=taxon_id)

    @mcp.tool(name="search_taxa")
    async def search_taxa_tool(query: str) -> list[dict]:
        """Autocomplete EcoTaxa taxonomy names."""
        return await _run_sync(search_taxa, query=query)

    @mcp.tool(name="taxa_stats")
    async def taxa_stats_tool(
        project_ids: list[int],
        taxa: list[int | str],
    ) -> dict:
        """Return V/P/D classification counts per (project_id, taxon).

        ``taxa`` accepts integer taxon IDs or scientific names — names are
        resolved via the taxonomy autocomplete, then sent to
        ``/project_set/taxo_stats`` as ``taxa_ids=<id>``. Inaccessible
        projects are skipped silently and listed in
        ``inaccessible_project_ids``.
        """
        try:
            return await _run_sync(taxa_stats, project_ids=project_ids, taxa=taxa)
        except EcoTaxaBrowserError as exc:
            return {"ok": False, "error": exc.as_dict()}

    @mcp.tool(name="get_column_distribution")
    async def get_column_distribution_tool(
        project_id: int,
        column_name: str,
        level: str | None = None,
    ) -> dict:
        """Inspect the value distribution of a column before exporting.

        Numeric columns return min/max/mean/median/p25/p75/n; text columns
        return top values + total_distinct + sample_size. The ``source``
        field tells whether the response came from the EcoTaxa pre-aggregated
        column_stats endpoint or from a first-window sample fallback.
        """
        try:
            return await _run_sync(
                get_column_distribution,
                project_id=project_id,
                column_name=column_name,
                level=level,
            )
        except EcoTaxaBrowserError as exc:
            return {"ok": False, "error": exc.as_dict()}

    @mcp.tool(name="compare_project_schemas")
    async def compare_project_schemas_tool(project_ids: list[int]) -> dict:
        """Identify shared columns, type and level conflicts across projects.

        Use before a multi-project export to spot blockers (type mismatches)
        and warnings (datetime vs text). Returns ``common_columns``,
        ``type_conflicts`` (severity), ``level_conflicts`` and
        ``unique_to_project`` lists.
        """
        return await _run_sync(compare_project_schemas, project_ids=project_ids)

    @mcp.tool(name="samples_in_region")
    async def samples_in_region_tool(
        bbox: dict | None = None,
        date_range: dict | None = None,
        instrument: str | None = None,
        polygon_wkt: str | None = None,
        zone_name: str | None = None,
        project_ids: list[int] | None = None,
        depth_max_lt: float | None = None,
        depth_max_gte: float | None = None,
        month: int | None = None,
    ) -> dict:
        """Return cached samples matching a bbox / date range / instrument.

        ``bbox`` is a dict ``{"south", "west", "north", "east"}`` in decimal
        degrees. ``date_range`` is ``{"from", "to"}`` in ISO format. All
        filters are optional. Two ways to get in-polygon precision:
        - ``zone_name``: a NeoLab zone (e.g. "Baie de Baffin") resolved
          internally; preferred, keeps the large polygon off the channel.
        - ``polygon_wkt``: an explicit WGS84 WKT polygon.
        ``project_ids`` restricts to a subset of EcoTaxa projects (SQL ``IN``
        on the cache index); pair with zone/date to scope « samples du
        projet X dans la zone Y » in one shot.
        Capped at 500 samples with a ``truncated`` flag and a ``summary``
        aggregating project_breakdown + date range seen. Reads the local
        cache only — call ``/admin/resync`` first if empty.
        ``depth_max_lt`` / ``depth_max_gte`` filter the cached sample-level
        maximum object depth in metres.
        ``month`` filters calendar month 1-12 across years.
        """
        try:
            return await _run_sync(
                samples_in_region,
                bbox=bbox, date_range=date_range, instrument=instrument,
                polygon_wkt=polygon_wkt, zone_name=zone_name,
                project_ids=project_ids,
                depth_max_lt=depth_max_lt,
                depth_max_gte=depth_max_gte,
                month=month,
            )
        except EcoTaxaBrowserError as exc:
            return {"ok": False, "error": exc.as_dict()}

    @mcp.tool(name="projects_in_region")
    async def projects_in_region_tool(
        bbox: dict | None = None,
        date_range: dict | None = None,
        polygon_wkt: str | None = None,
        zone_name: str | None = None,
        project_ids: list[int] | None = None,
    ) -> dict:
        """Aggregate cached samples per project for a region / time window.

        Same filters as ``samples_in_region`` (``bbox``, ``date_range``,
        ``zone_name``, ``polygon_wkt``, ``project_ids``). When a polygon is
        applied, samples outside it are excluded before project aggregation.
        Returns one row per project with ``sample_count``, ``object_count``,
        ``instruments``, ``date_min``, ``date_max``.
        """
        try:
            return await _run_sync(
                projects_in_region,
                bbox=bbox, date_range=date_range,
                polygon_wkt=polygon_wkt, zone_name=zone_name,
                project_ids=project_ids,
            )
        except EcoTaxaBrowserError as exc:
            return {"ok": False, "error": exc.as_dict()}

    @mcp.tool(name="group_project_samples_by_region")
    async def group_project_samples_by_region_tool(project_id: int) -> dict:
        """Group one project's cached samples by NeoLab/IHO region.

        Returns ``groups`` as ``region_name -> [sample_id, ...]`` plus a
        compact ``markdown_summary`` for LLM display. Includes explicit
        ``Hors zones IHO`` and ``Sans coordonnées`` buckets. Reads the local
        cache only.
        """
        try:
            return await _run_sync(
                group_project_samples_by_region,
                project_id=project_id,
            )
        except EcoTaxaBrowserError as exc:
            return {"ok": False, "error": exc.as_dict()}

    @mcp.tool(name="summarize_projects")
    async def summarize_projects_tool(project_ids: list[int]) -> list[dict]:
        """Per-project overview without downloading objects.

        Combines local cache envelopes (n_samples, date range, bbox,
        instruments) with ``/project_set/taxo_stats`` project-level V/P/D/U
        counts and per-taxon stats. Resolves taxon IDs to names. Light,
        read-only.
        """
        return await _run_sync(summarize_projects, project_ids=project_ids)

    @mcp.tool(name="summarize_samples")
    async def summarize_samples_tool(sample_ids: list[int]) -> list[dict]:
        """Per-sample classification breakdown without downloading objects.

        Hits ``GET /sample_set/taxo_stats`` once for the whole batch. For each
        sample returns ``nb_validated``, ``nb_predicted``, ``nb_dubious``,
        ``nb_unclassified``, ``used_taxa`` (taxon IDs) and ``per_taxon``
        (taxon IDs resolved to names). Light, read-only — use to scan a
        list of samples (typically the output of ``samples_in_region``)
        before deciding which ones are worth a full export.
        """
        return await _run_sync(summarize_samples, sample_ids=sample_ids)

    @mcp.tool(name="find_observations")
    async def find_observations_tool(
        taxon: int | str,
        bbox: dict | None = None,
        date_range: dict | None = None,
        instrument: str | None = None,
        status: str = "V",
        polygon_wkt: str | None = None,
        zone_name: str | None = None,
        project_ids: list[int] | None = None,
        depth_max_lt: float | None = None,
        depth_max_gte: float | None = None,
        month: int | None = None,
    ) -> dict:
        """Find cached samples whose project has the taxon attested.

        Project-level filter (G1 granularity): samples in bbox/date that
        belong to a project where ``taxon`` has at least one object of the
        requested status (``V``, ``P``, ``D``, ``all``). Per-sample taxon
        counts are out of scope for V1 — use ``count_ecotaxa_taxa`` (taxa
        stats) on the returned ``attested_projects`` for finer numbers.

        ``zone_name`` (preferred): NeoLab zone resolved internally; filter
        applied BEFORE project attestation, so projects with only
        out-of-polygon samples are correctly excluded.
        ``polygon_wkt`` (alternative): explicit WGS84 WKT polygon.
        ``project_ids``: optional subset of EcoTaxa projects to consider
        before taxon attestation lookup.
        ``depth_max_lt`` / ``depth_max_gte`` and ``month`` filter cached
        samples before project taxon attestation lookup.
        """
        try:
            return await _run_sync(
                find_observations,
                taxon=taxon, bbox=bbox, date_range=date_range,
                instrument=instrument, status=status,
                polygon_wkt=polygon_wkt, zone_name=zone_name,
                project_ids=project_ids,
                depth_max_lt=depth_max_lt,
                depth_max_gte=depth_max_gte,
                month=month,
            )
        except EcoTaxaBrowserError as exc:
            return {"ok": False, "error": exc.as_dict()}

    @mcp.tool(name="preview_project")
    async def preview_project_tool(
        project_id: int, limit: int = 10,
    ) -> dict:
        """Quick metadata + a small sample of objects from a project.

        Returns ``{metadata, summary, objects}`` — same payload as the IDEA
        ``preview_ecotaxa_project`` @tool. Light, read-only, no export.
        Use when the user asks « aperçu / preview / présente-moi le projet ».
        """
        return await _run_sync(
            preview_project, project_id=project_id, limit=limit,
        )

    @mcp.tool(name="summarize_project")
    async def summarize_project_tool(project_id: int) -> dict:
        """Single-project overview (sugar over summarize_projects)."""
        rows = await _run_sync(summarize_projects, project_ids=[project_id])
        return rows[0] if rows else {}

    @mcp.tool(name="summarize_sample")
    async def summarize_sample_tool(sample_id: int) -> dict:
        """Single-sample classification breakdown (sugar over summarize_samples)."""
        rows = await _run_sync(summarize_samples, sample_ids=[sample_id])
        return rows[0] if rows else {}

    @mcp.tool(name="summarize_sample_deployment")
    async def summarize_sample_deployment_tool(sample_id: int) -> dict:
        """Per-sample deployment summary: lat/lon, dates, depths, free fields, objects scanned.

        Reads sample metadata + a window of objects to compute the actual
        date/depth envelopes. Returns identifiers, position, acquisition
        details, and the free fields exposed by the parent project.
        """
        return await _run_sync(
            summarize_sample_deployment, sample_id=sample_id,
        )

    @mcp.tool(name="cache_status")
    async def cache_status_tool() -> dict:
        """Diagnose the local EcoTaxa cache.

        Returns ``{samples_indexed, projects_indexed, schemas_indexed,
        sync_running, projects_synced, samples_synced,
        projects_total_estimated, last_sync, cache_age_hours, cache_db}``.
        ``last_sync`` is the row from ``sync_runs`` (run_id, started_at,
        ended_at, status, projects_synced, samples_synced, error_message) or null if the
        cache has never been synchronised. Use when a region/observation
        call returns ``CACHE_EMPTY`` or the user asks whether the cache
        is fresh. Read-only — operators must call ``POST /admin/resync``
        to trigger a refresh.
        """
        cache_db = _cache_db_path()
        conn = _open_cache()
        try:
            progress = cache_progress(conn)
            last_sync = progress["last_sync"]
        finally:
            conn.close()
        return {
            "samples_indexed": progress["samples_indexed"],
            "projects_indexed": progress["projects_indexed"],
            "schemas_indexed": progress["schemas_indexed"],
            "sync_running": progress["sync_running"],
            "projects_synced": progress["projects_synced"],
            "samples_synced": progress["samples_synced"],
            "projects_total_estimated": progress["projects_total_estimated"],
            "last_sync": last_sync,
            "cache_age_hours": _compute_cache_age_hours(last_sync),
            "cache_db": cache_db,
        }

    return mcp


async def _run_sync(function, **kwargs):
    return await anyio.to_thread.run_sync(partial(function, **kwargs))
