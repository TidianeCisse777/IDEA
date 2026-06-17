"""Geographic zone tool for NeoLab copepod data.

Backed by core.geo + the polygon registry built from IHO Marine Regions v3 +
NeoLab cuts (Cap Henrietta Maria → Pointe Louis-XIV for James/Hudson; Cap
Hopes Advance → Cape Chidley for Ungava/Hudson Strait).

Replaces the old `get_zone_filter` (hand-typed bboxes) — bbox values are now
derived from the actual polygons so they are tight and accurate. The polygon
WKT is also returned so downstream tools (or run_pandas) can apply a precise
in-polygon filter rather than a loose bbox filter.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from langchain_core.tools import tool
from shapely.geometry.base import BaseGeometry

from core.geo import Registry, filter_by_zone as _core_filter_by_zone, load_registry, resolve_zone
from tools.dataset_registry import dataset_variable_name, store_dataset
from tools.session_store import SessionStore, default_store


_REGISTRY_PATH = Path(__file__).parent.parent / "data" / "geo" / "zones_registry.geojson"


@lru_cache(maxsize=1)
def _registry() -> Registry:
    return load_registry(_REGISTRY_PATH)


def _normalise(text: str) -> str:
    return re.sub(r"[''`]", "'", text.lower().strip())


def _match_canonical(zone_name: str) -> str | None:
    """Résout un nom utilisateur vers le canonical du registry, via aliases.

    Stratégie : match exact (normalisé) sur canonical ou aliases, puis
    fallback substring (tolérant aux fautes courantes type 'baie ungava').
    """
    key = _normalise(zone_name)
    reg = _registry()
    for zone in reg.zones:
        if key == _normalise(zone.canonical):
            return zone.canonical
        for alias in zone.aliases:
            if key == _normalise(alias):
                return zone.canonical
    for zone in reg.zones:
        candidates = [zone.canonical, *zone.aliases]
        for cand in candidates:
            n = _normalise(cand)
            if key in n or n in key:
                return zone.canonical
    return None


def _bbox_from_polygon(polygon: BaseGeometry) -> dict[str, float]:
    minx, miny, maxx, maxy = polygon.bounds
    return {"south": miny, "west": minx, "north": maxy, "east": maxx}


def _pandas_filter(bbox: dict[str, float]) -> str:
    return (
        "df["
        f"(df['latitude'] >= {bbox['south']}) & (df['latitude'] <= {bbox['north']}) & "
        f"(df['longitude'] >= {bbox['west']}) & (df['longitude'] <= {bbox['east']})"
        "]"
    )


@tool
def get_zone_info(zone_name: str) -> dict:
    """Return the canonical polygon, bbox, and metadata for a named NeoLab
    geographic zone.

    Use this tool whenever the user mentions a named zone (e.g. "Baie d'Ungava",
    "mer du Labrador", "Hudson Bay", "Hawke Channel", "Arctique"). The result
    gives:
    - bbox: lat/lon bounds (decimal degrees) for legacy bbox-based downstream
      tools.
    - canonical / aliases : confirm the resolved zone (use for display).
    - polygon_wkt_preview : truncated preview of the WKT (debug only). For
      precise in-polygon queries, DO NOT copy this — pass
      `zone_name="<canonical>"` directly to the downstream tool
      (find_ecotaxa_*_in_region, query_bio_oracle_zones), which will
      resolve the polygon internally.

    Parameters
    ----------
    zone_name : str
        French, English, or common name of the zone (case-insensitive, aliases
        accepted). Supported zones:
        - Nord QC: Baie d'Hudson, Baie de James, Détroit d'Hudson,
                   Baie d'Ungava, Nunavik, Hawke Channel
        - Arctique canadien: Baie de Baffin, Détroit de Davis, Mer du Labrador
        - Saint-Laurent: Golfe du Saint-Laurent
        - Arctique élargi: Mer de Beaufort, Mer des Tchouktches,
                           Mer du Groenland, Mer de Lincoln, Arctique

    Returns
    -------
    dict with keys:
        - canonical     : canonical zone name (FR)
        - source        : where the polygon comes from (IHO v3, NeoLab cut,
                          NeoLab composite, etc.)
        - bbox          : {south, west, north, east} in decimal degrees
                          (longitude negative for West, latitude positive N)
        - polygon_wkt   : precise polygon as WKT (WGS84)
        - aliases       : list of accepted alternate names
        - pandas_filter : ready-to-use df expression based on bbox
                          (e.g. df[(df['latitude'] >= ...) & ...])
    """
    canonical = _match_canonical(zone_name)
    if canonical is None:
        return {
            "error": f"Zone '{zone_name}' not recognised.",
            "available_zones": [z.canonical for z in _registry().zones],
        }

    zone = resolve_zone(canonical, registry=_registry())
    polygon = zone["polygon"]
    bbox = _bbox_from_polygon(polygon)

    aliases = next(
        (z.aliases for z in _registry().zones if z.canonical == canonical),
        (),
    )

    # Le WKT complet d'une zone IHO peut atteindre 480 KB (Baie d'Hudson),
    # ce qui sature le contexte LLM et se fait tronquer par MAX_TOOL_RESULT_CHARS.
    # On expose seulement un preview pour log / debug ; les tools aval
    # (find_ecotaxa_*_in_region, query_bio_oracle_zones) prennent `zone_name`
    # directement et résolvent le polygone côté Python sans passer par le LLM.
    full_wkt = polygon.wkt
    preview = full_wkt[:160] + (
        f"... ({len(full_wkt)} chars total — pass zone_name to downstream tools)"
        if len(full_wkt) > 160 else ""
    )

    return {
        "canonical": canonical,
        "source": zone["source"],
        "bbox": bbox,
        "polygon_wkt_preview": preview,
        "aliases": list(aliases),
        "pandas_filter": _pandas_filter(bbox),
        "usage_hint": (
            f"For EcoTaxa / Bio-ORACLE queries, pass zone_name='{canonical}' "
            "to the downstream tool — do NOT copy the polygon_wkt through the LLM."
        ),
    }


def make_geo_tools(thread_id: str, *, store: SessionStore | None = None) -> list:
    """Session-aware geo tools (filter_dataframe_by_zone).

    Returned alongside the stateless module-level ``get_zone_info`` in
    ``agent.py``. The filter tool needs the per-thread SessionStore to read
    the latest loaded DataFrame and persist the filtered subset under a new
    variable name.
    """
    _store = store or default_store

    @tool
    def filter_dataframe_by_zone(
        zone_name: str,
        lat_col: str = "latitude",
        lon_col: str = "longitude",
    ) -> dict:
        """Filtre le DataFrame chargé pour ne garder que les lignes dont
        (lat, lon) tombent **strictement dans le polygone IHO** de la zone.

        Précision polygone (point-in-polygon shapely) — pas un filtre bbox.
        Utilise ce tool dès que l'utilisateur demande de filtrer / découper /
        garder uniquement les stations d'une zone nommée sur un fichier
        chargé. N'utilise PAS run_pandas + shapely.wkt à la main : ce tool
        résout le polygone côté Python sans transporter le WKT par le LLM.

        Parameters
        ----------
        zone_name : str
            Nom de la zone (FR/EN/alias). Mêmes zones supportées que
            ``get_zone_info``.
        lat_col, lon_col : str
            Noms des colonnes lat/lon dans le df. Défaut : 'latitude'
            / 'longitude' (convention NeoLab EcoTaxa/Amundsen).

        Returns
        -------
        dict : {zone_canonical, variable_name, n_in, n_out, lat_col, lon_col}
            ``variable_name`` est le nom du df filtré dans la session
            (accessible via run_pandas / run_graph).
        """
        session = _store.get(thread_id)
        if not session or session.get("df") is None:
            return "Aucun fichier chargé. Utilise load_file d'abord."

        df = session["df"]

        canonical = _match_canonical(zone_name)
        if canonical is None:
            raise ValueError(
                f"Zone '{zone_name}' inconnue du registry. "
                f"Zones disponibles : {[z.canonical for z in _registry().zones]}"
            )

        missing = [c for c in (lat_col, lon_col) if c not in df.columns]
        if missing:
            raise KeyError(
                f"Colonnes absentes du DataFrame : {missing}. "
                f"Colonnes disponibles : {list(df.columns)}. "
                "Passe lat_col / lon_col explicites."
            )

        kept = _core_filter_by_zone(
            df, canonical, lat_col=lat_col, lon_col=lon_col, registry=_registry(),
        )

        source_meta = (session.get("meta") or {}).get("source", "df")
        source_stem = source_meta.split(":", 1)[-1]
        variable_name = dataset_variable_name(
            "in", canonical, source_stem,
        )
        store_dataset(
            _store, thread_id, kept,
            variable_name=variable_name,
            meta={
                "source": f"filter_by_zone:{canonical}",
                "parent_source": source_meta,
                "zone_canonical": canonical,
                "lat_col": lat_col,
                "lon_col": lon_col,
                "n_rows": int(len(kept)),
            },
            latest_alias=variable_name,
        )

        return {
            "zone_canonical": canonical,
            "variable_name": variable_name,
            "n_in": int(len(kept)),
            "n_out": int(len(df) - len(kept)),
            "lat_col": lat_col,
            "lon_col": lon_col,
        }

    return [filter_dataframe_by_zone]
