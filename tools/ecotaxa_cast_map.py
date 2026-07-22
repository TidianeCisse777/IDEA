"""Deterministic rendering for standard EcoTaxa cast maps."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

import pandas as pd

from core.cartography import configure_offline_cartopy
from core.runtime_paths import graphs_dir
from tools.public_url import graph_url


@dataclass(frozen=True)
class CastMapRequest:
    zone_name: str
    group_by: str = "none"


@dataclass(frozen=True)
class RenderedCastMap:
    image_markdown: str
    cast_count: int
    excluded_missing_cast_ids: int
    cache_hit: bool
    timings_ms: dict[str, float]


_MAP_WORDS = frozenset({"map", "carte", "mapa", "karte", "地图"})
_PROJECT_WORDS = frozenset({"project", "projet", "proyecto", "projekt"})
_MAP_RENDERER_VERSION = "v2"
_ZONE_GENERIC_WORDS = frozenset({
    "baie", "bay", "gulf", "golfe", "sea", "mer", "strait", "detroit",
    "passage", "canal", "ocean", "oceano", "oceanique",
})


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _cache_db() -> str:
    return os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")


def _matching_zone(text: str, cache_db: str) -> str | None:
    """Resolve a named cache zone from its distinctive words in the request."""
    normal_text = set(_normalize(text).split())
    if not normal_text:
        return None
    try:
        with sqlite3.connect(cache_db) as connection:
            rows = connection.execute(
                "SELECT DISTINCT iho_zone FROM samples_cache "
                "WHERE iho_zone IS NOT NULL AND TRIM(iho_zone) <> ''"
            ).fetchall()
    except sqlite3.Error:
        return None
    matches: list[str] = []
    for (zone_name,) in rows:
        words = {
            word for word in _normalize(str(zone_name)).split()
            if len(word) >= 4 and word not in _ZONE_GENERIC_WORDS
        }
        if words and words.issubset(normal_text):
            matches.append(str(zone_name))
    return matches[0] if len(matches) == 1 else None


def parse_ecotaxa_cast_map_request(text: str) -> CastMapRequest | None:
    """Recognize only an explicit, standard EcoTaxa cast-map request.

    The named source and cast concept make this intentionally narrow; generic
    graphs and maps from loaded files continue through the agent workflow.
    """
    normalized = _normalize(text)
    words = set(normalized.split())
    if "ecotaxa" not in words or not any(word.startswith("cast") for word in words):
        return None
    if not words.intersection(_MAP_WORDS):
        return None
    zone_name = _matching_zone(text, _cache_db())
    if zone_name is None:
        return None
    group_by = "project" if words.intersection(_PROJECT_WORDS) else "none"
    return CastMapRequest(zone_name=zone_name, group_by=group_by)


def _load_cast_map_rows(
    request: CastMapRequest, cache_db: str
) -> tuple[pd.DataFrame, int, str, float]:
    started = time.perf_counter()
    where = "iho_zone = ?"
    params = (request.zone_name,)
    query = f"""
        SELECT profile_id AS cast_id, project_id,
               AVG(lon_avg) AS lon, AVG(lat_avg) AS lat,
               COUNT(DISTINCT sample_id) AS sample_count,
               MIN(date_min) AS date_min, MAX(date_max) AS date_max
        FROM samples_cache
        WHERE {where}
          AND profile_id IS NOT NULL AND TRIM(profile_id) <> ''
          AND lat_avg IS NOT NULL AND lon_avg IS NOT NULL
        GROUP BY profile_id, project_id
        ORDER BY project_id, cast_id
    """
    missing_query = f"""
        SELECT COUNT(*) FROM samples_cache
        WHERE {where} AND (profile_id IS NULL OR TRIM(profile_id) = '')
    """
    with sqlite3.connect(cache_db) as connection:
        frame = pd.read_sql_query(query, connection, params=params)
        excluded = int(connection.execute(missing_query, params).fetchone()[0])
        sync_row = connection.execute(
            "SELECT COALESCE(ended_at, started_at, '') FROM sync_runs "
            "ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
    fingerprint = str(sync_row[0]) if sync_row else "no-sync"
    elapsed = (time.perf_counter() - started) * 1000
    return frame, excluded, fingerprint, elapsed


def _map_path(request: CastMapRequest, sync_fingerprint: str) -> Path:
    key = hashlib.sha256(
        f"{_MAP_RENDERER_VERSION}|{request.zone_name}|{request.group_by}|{sync_fingerprint}".encode()
    ).hexdigest()[:16]
    return graphs_dir() / f"ecotaxa-casts-{_MAP_RENDERER_VERSION}-{key}.png"


def render_ecotaxa_cast_map(request: CastMapRequest) -> RenderedCastMap:
    """Render one point per cast, optionally color-coded by parent project."""
    rows, excluded, sync_fingerprint, query_ms = _load_cast_map_rows(request, _cache_db())
    if rows.empty:
        raise ValueError(f"Aucun cast géolocalisé disponible pour {request.zone_name}.")
    target = _map_path(request, sync_fingerprint)
    if target.exists():
        return RenderedCastMap(
            image_markdown=f"![graph]({graph_url(target.name)})",
            cast_count=len(rows),
            excluded_missing_cast_ids=excluded,
            cache_hit=True,
            timings_ms={"query": query_ms, "render": 0.0},
        )

    started = time.perf_counter()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import cartopy.feature as cfeature
    import cartopy.crs as ccrs

    configure_offline_cartopy()
    lon, lat = rows["lon"], rows["lat"]
    lon_padding = max(float(lon.max() - lon.min()) * 0.12, 0.25)
    lat_padding = max(float(lat.max() - lat.min()) * 0.12, 0.25)
    figure, axis = plt.subplots(figsize=(9, 7), subplot_kw={"projection": ccrs.PlateCarree()})
    axis.set_extent(
        [lon.min() - lon_padding, lon.max() + lon_padding, lat.min() - lat_padding, lat.max() + lat_padding],
        crs=ccrs.PlateCarree(),
    )
    axis.set_facecolor("#dceff6")
    axis.add_feature(cfeature.OCEAN, facecolor="#dceff6", zorder=0)
    axis.add_feature(
        cfeature.LAND,
        facecolor="#e8e1d5",
        edgecolor="#6e675e",
        linewidth=0.35,
        zorder=1,
    )
    axis.coastlines(resolution="110m", linewidth=0.5, zorder=2)
    if request.group_by == "project":
        colors = plt.get_cmap("tab10")
        for index, (project_id, project_rows) in enumerate(rows.groupby("project_id", sort=True)):
            axis.scatter(
                project_rows["lon"], project_rows["lat"], s=34,
                color=colors(index % 10), label=f"Projet {project_id}",
                transform=ccrs.PlateCarree(), edgecolors="white", linewidths=0.25,
            )
        axis.legend(title="Projet", loc="lower left", frameon=True)
    else:
        axis.scatter(lon, lat, s=34, color="tab:blue", transform=ccrs.PlateCarree(), edgecolors="white", linewidths=0.25)
    axis.set_title(f"EcoTaxa — casts dans {request.zone_name}")
    gridlines = axis.gridlines(draw_labels=True, linewidth=0.4, alpha=0.4, linestyle=":")
    gridlines.top_labels = False
    gridlines.right_labels = False
    figure.savefig(target, format="png", dpi=120)
    plt.close(figure)
    return RenderedCastMap(
        image_markdown=f"![graph]({graph_url(target.name)})",
        cast_count=len(rows),
        excluded_missing_cast_ids=excluded,
        cache_hit=False,
        timings_ms={"query": query_ms, "render": (time.perf_counter() - started) * 1000},
    )
