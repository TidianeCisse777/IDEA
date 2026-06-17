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

from core.geo import Registry, load_registry, resolve_zone


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
    gives BOTH:
    - bbox: lat/lon bounds (decimal degrees) for legacy bbox-based downstream
      tools (find_ecotaxa_samples_in_region, Bio-ORACLE bbox sampling,
      run_pandas filtering by latitude/longitude).
    - polygon_wkt: precise polygon (WKT, WGS84) for in-polygon post-filtering
      via run_pandas + shapely. Use polygon_wkt when station-level precision
      matters (e.g. distinguishing Baie d'Ungava from Détroit d'Hudson).

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

    return {
        "canonical": canonical,
        "source": zone["source"],
        "bbox": bbox,
        "polygon_wkt": polygon.wkt,
        "aliases": list(aliases),
        "pandas_filter": _pandas_filter(bbox),
    }
