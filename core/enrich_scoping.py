"""Apply zone + date filters to a source DataFrame before enrichment.

Lets `enrich_with_amundsen_ctd`, `enrich_with_ogsl` and `enrich_with_bio_oracle`
accept `zone_name` and `date_range` parameters and apply them in Python
deterministically, instead of relying on the agent to chain
`filter_dataframe_by_zone` → enrich. The agent is unreliable on multi-step
chains; doing the scoping inside the tool removes that risk entirely.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

from core.geo import filter_by_zone as _core_filter_by_zone, load_registry, resolve_zone


def _registry_path():
    from pathlib import Path
    return Path(__file__).parent.parent / "data" / "geo" / "zones_registry.geojson"


def _match_canonical(name: str) -> str | None:
    """Resolve a user-supplied zone name to its canonical name."""
    if not name:
        return None
    target = str(name).strip().lower()
    registry = load_registry(_registry_path())
    for zone in registry.zones:
        candidates = [zone.canonical] + list(getattr(zone, "aliases", []) or [])
        for candidate in candidates:
            if candidate and candidate.strip().lower() == target:
                return zone.canonical
    return None


@dataclass
class ScopedFrame:
    """Result of applying optional zone/date filters to a source DataFrame."""

    df: pd.DataFrame
    zone_canonical: str | None = None
    date_start: pd.Timestamp | None = None
    date_end: pd.Timestamp | None = None
    n_in_zone: int | None = None
    n_in_date: int | None = None
    error: str | None = None
    description_lines: list[str] = field(default_factory=list)


def scope_dataframe(
    df: pd.DataFrame,
    *,
    zone_name: str | None = None,
    date_range: tuple | list | None = None,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    time_col: str | None = None,
) -> ScopedFrame:
    """Apply zone and/or date filters to `df` in this exact order.

    Parameters
    ----------
    df : the source DataFrame (already resolved from the session store).
    zone_name : canonical or alias of an IHO/MEOW zone — applied via
        `core.geo.filter_by_zone` (shapely point-in-polygon).
    date_range : 2-element [start, end] ISO date strings (or pd.Timestamp) —
        applied via `pd.Series.between(start, end, inclusive='both')` on the
        detected time column.
    lat_col, lon_col, time_col : column names. Caller is responsible for
        detecting them upstream and passing them in.

    Returns
    -------
    ScopedFrame with the filtered df and provenance info.
    """
    result = ScopedFrame(df=df.copy())
    n_initial = len(df)

    if zone_name:
        canonical = _match_canonical(zone_name)
        if canonical is None:
            result.error = (
                f"zone_name='{zone_name}' inconnue du registry. "
                "Vérifie le nom (ex. 'Baie de Baffin', 'Hudson Complex', "
                "'MEOW: Beaufort Sea - continental coast and shelf')."
            )
            return result
        if lat_col not in df.columns or lon_col not in df.columns:
            result.error = (
                f"Colonnes lat/lon manquantes pour filtrer par zone : "
                f"requis lat_col='{lat_col}', lon_col='{lon_col}', "
                f"trouvé {[c for c in df.columns if c.lower() in ('lat','latitude','lon','longitude')]}"
            )
            return result
        registry = load_registry(_registry_path())
        result.df = _core_filter_by_zone(
            result.df, canonical, lat_col=lat_col, lon_col=lon_col, registry=registry
        )
        result.zone_canonical = canonical
        result.n_in_zone = int(len(result.df))
        result.description_lines.append(
            f"- Filtre zone : zone='{canonical}' → "
            f"{result.n_in_zone}/{n_initial} ligne(s) gardée(s)"
        )

    if date_range is not None and time_col is not None:
        if not isinstance(date_range, (list, tuple)) or len(date_range) != 2:
            result.error = (
                f"date_range doit être un [start, end] de 2 dates ISO, reçu "
                f"{date_range!r}."
            )
            return result
        start = pd.Timestamp(date_range[0]).tz_localize("UTC") if pd.Timestamp(date_range[0]).tz is None else pd.Timestamp(date_range[0]).tz_convert("UTC")
        end = pd.Timestamp(date_range[1]).tz_localize("UTC") if pd.Timestamp(date_range[1]).tz is None else pd.Timestamp(date_range[1]).tz_convert("UTC")
        if time_col not in result.df.columns:
            result.error = (
                f"date_range fourni mais colonne time_col='{time_col}' absente "
                f"du df."
            )
            return result
        n_before = len(result.df)
        time_series = pd.to_datetime(result.df[time_col], errors="coerce", utc=True)
        mask = time_series.between(start, end, inclusive="both")
        result.df = result.df.loc[mask].copy()
        result.date_start = start
        result.date_end = end
        result.n_in_date = int(len(result.df))
        result.description_lines.append(
            f"- Filtre date : {start.date().isoformat()} → "
            f"{end.date().isoformat()} sur '{time_col}' → "
            f"{result.n_in_date}/{n_before} ligne(s) gardée(s)"
        )

    return result
