"""Geographic zone filter tool for NeoLab copepod data.

Returns lat/lon bounds and a ready-to-use pandas filter string for named
northern Quebec / Arctic geographic zones.
"""
from __future__ import annotations
import re
from langchain_core.tools import tool


# ---------------------------------------------------------------------------
# Zone registry — each entry: (lat_min, lat_max, lon_min, lon_max, canonical)
# lon values are negative (West), stored as negative floats for direct use
# ---------------------------------------------------------------------------
_ZONES: dict[str, dict] = {
    "baie_hudson": {
        "canonical": "Baie d'Hudson",
        "lat_min": 51, "lat_max": 65,
        "lon_min": -95, "lon_max": -77,
        "aliases": [
            "baie d'hudson", "baie hudson", "hudson bay", "hudson",
            "bay of hudson",
        ],
    },
    "baie_james": {
        "canonical": "Baie de James",
        "lat_min": 51, "lat_max": 55,
        "lon_min": -82, "lon_max": -79,
        "aliases": [
            "baie de james", "baie james", "james bay", "james",
            "eeyou istchee",
        ],
    },
    "detroit_hudson": {
        "canonical": "Détroit d'Hudson",
        "lat_min": 60, "lat_max": 63,
        "lon_min": -80, "lon_max": -64,
        "aliases": [
            "détroit d'hudson", "detroit d'hudson", "detroit hudson",
            "hudson strait", "hudson strait",
        ],
    },
    "baie_ungava": {
        "canonical": "Baie d'Ungava",
        "lat_min": 58, "lat_max": 62,
        "lon_min": -74, "lon_max": -67,
        "aliases": [
            "baie d'ungava", "baie ungava", "ungava bay", "ungava",
        ],
    },
    "mer_labrador": {
        "canonical": "Mer du Labrador",
        "lat_min": 53, "lat_max": 65,
        "lon_min": -64, "lon_max": -42,
        "aliases": [
            "mer du labrador", "mer labrador", "labrador sea", "labrador",
        ],
    },
    "hawke_channel": {
        "canonical": "Hawke Channel",
        "lat_min": 52, "lat_max": 56,
        "lon_min": -57, "lon_max": -53,
        "aliases": [
            "hawke channel", "hawke", "hc", "chenal hawke",
        ],
    },
    "baie_baffin": {
        "canonical": "Baie de Baffin",
        "lat_min": 66, "lat_max": 83,
        "lon_min": -80, "lon_max": -60,
        "aliases": [
            "baie de baffin", "baie baffin", "baffin bay", "baffin",
        ],
    },
    "mer_beaufort": {
        "canonical": "Mer de Beaufort",
        "lat_min": 68, "lat_max": 80,
        "lon_min": -165, "lon_max": -120,
        "aliases": [
            "mer de beaufort", "mer beaufort", "beaufort sea", "beaufort",
        ],
    },
    "arctique": {
        "canonical": "Arctique / Amundsen",
        "lat_min": 65, "lat_max": 90,
        "lon_min": -180, "lon_max": 180,
        "aliases": [
            "arctique", "arctic", "amundsen", "polaire",
        ],
    },
    "nunavik": {
        "canonical": "Nunavik",
        "lat_min": 55, "lat_max": 63,
        "lon_min": -82, "lon_max": -64,
        "aliases": [
            "nunavik", "nord québécois", "nord quebecois",
            "québec nordique", "quebec nordique",
        ],
    },
}


def _build_filter(z: dict) -> str:
    lat_min = z["lat_min"]
    lat_max = z["lat_max"]
    lon_min = z["lon_min"]
    lon_max = z["lon_max"]
    return (
        f"df["
        f"(df['latitude'] >= {lat_min}) & (df['latitude'] <= {lat_max}) & "
        f"(df['longitude'] >= {lon_min}) & (df['longitude'] <= {lon_max})"
        f"]"
    )


def _normalise(text: str) -> str:
    return re.sub(r"[''`]", "'", text.lower().strip())


def _match_zone(zone_name: str) -> dict | None:
    key = _normalise(zone_name)
    # Exact alias match
    for z in _ZONES.values():
        if key in [_normalise(a) for a in z["aliases"]]:
            return z
    # Substring match
    for z in _ZONES.values():
        for alias in z["aliases"]:
            if key in _normalise(alias) or _normalise(alias) in key:
                return z
    return None


@tool
def get_zone_filter(zone_name: str) -> dict:
    """Return bounding-box coordinates and a pandas filter string for a named
    NeoLab geographic zone.

    Use this tool whenever the user asks to filter, select, or subset stations
    or observations by geographic zone (e.g. "all Labrador Sea stations",
    "filter to Hawke Channel", "stations in Hudson Bay").

    Parameters
    ----------
    zone_name : str
        French, English, or common name of the zone. Supported zones:
        Hawke Channel, Mer du Labrador, Détroit d'Hudson, Baie d'Ungava,
        Baie d'Hudson, Baie de James, Baie de Baffin, Mer de Beaufort,
        Arctique / Amundsen, Nunavik.

    Returns
    -------
    dict with keys:
        - zone        : canonical zone name
        - lat_min/max : latitude bounds (decimal degrees N)
        - lon_min/max : longitude bounds (decimal degrees, negative = W)
        - filter      : ready-to-use pandas expression, e.g.
                        df[(df['latitude'] >= 53) & ...]
        - usage_hint  : short note on which columns are expected
    """
    match = _match_zone(zone_name)
    if match is None:
        available = ", ".join(z["canonical"] for z in _ZONES.values())
        return {
            "error": f"Zone '{zone_name}' not recognised.",
            "available_zones": available,
        }

    return {
        "zone": match["canonical"],
        "lat_min": match["lat_min"],
        "lat_max": match["lat_max"],
        "lon_min": match["lon_min"],
        "lon_max": match["lon_max"],
        "filter": _build_filter(match),
        "usage_hint": (
            "Apply the filter expression to any DataFrame that has 'latitude' "
            "and 'longitude' columns (decimal degrees, longitude negative for West). "
            "Example: zone_df = " + _build_filter(match)
        ),
    }
