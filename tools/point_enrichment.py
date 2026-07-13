"""Deep shell for point enrichment (lat/lon → environmental value).

`run_point_enrichment` owns the single sequence shared by every lat/lon
enrichment source (Amundsen CTD, OGSL, Bio-ORACLE): resolve source table,
detect coord columns, scope by zone/date, validate, deduplicate query points,
delegate the MATCH to a `PointMatcher` adapter, remap the result back onto
every row, store the enriched dataset and render the method block with the
coverage line.

The `PointMatcher` at the seam carries only what genuinely varies per source:
the dedup key and the MATCH (ERDDAP batching / nearest-neighbour / grid
lookup). Error messages, guard ordering and the coverage-warning rule live
here, once. EcoPart is NOT a point enrichment (it joins on
`(sample_id, depth_bin)`), so it does not use this shell.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import pandas as pd

from core.enrich_scoping import scope_dataframe
from core.environment_resolver.column_detection import (
    DEFAULT_DEPTH_CANDIDATES,
    DEFAULT_LAT_CANDIDATES,
    DEFAULT_LON_CANDIDATES,
    DEFAULT_TIME_CANDIDATES,
    DEFAULT_TIME_END_CANDIDATES,
    detect_column,
)
from core.environment_resolver.coords import CoordsValidation, parse_source_coords
from core.environment_resolver.source import resolve_source_dataframe
from tools.dataset_registry import enrichment_source_note, store_dataset


@dataclass(frozen=True)
class RequiredCoords:
    """Which coordinate columns the shell must detect/parse for a matcher.

    Bio-ORACLE needs only lat/lon; Amundsen/OGSL add time and depth.
    """

    lat: bool = True
    lon: bool = True
    time: bool = False
    depth: bool = False


@dataclass(frozen=True)
class QueryPoints:
    """Deduplicated query points handed to a matcher.

    Every Series has length `n_unique`, index reset, and is positionally
    aligned. `time`/`time_end`/`depth` are None when the matcher did not
    request them via `required_coords()`.
    """

    latitude: pd.Series
    longitude: pd.Series
    time: pd.Series | None = None
    time_end: pd.Series | None = None
    depth: pd.Series | None = None

    def __len__(self) -> int:
        return len(self.latitude)


@dataclass
class MatchResult:
    """What a matcher returns for the unique points it was given.

    columns       DataFrame of length `n_unique`. Each column is appended to
                  the enriched table (remapped unique→row by the shell). Does
                  NOT include the status column — the shell owns that so rows
                  with invalid coords (never seen by the matcher) still get a
                  coherent status.
    statuses      Series[str] of length `n_unique`: per-unique-point status
                  ("matched", "no_match", "outside_range"…). The shell renames
                  it `<prefix>_match_status` and extends it to non-queried rows.
    method_lines  Source-specific detail lines for the method block (variables,
                  tolerances, dataset ids). The shell owns the coverage line.
    n_matched     Count of unique points that got a real match (drives the
                  coverage warning owned by the shell).
    """

    columns: pd.DataFrame
    statuses: pd.Series
    method_lines: list[str] = field(default_factory=list)
    n_matched: int = 0


@runtime_checkable
class PointMatcher(Protocol):
    """Adapter at the seam — one per lat/lon source."""

    prefix: str
    label: str

    def required_coords(self) -> RequiredCoords:
        """Which coords the shell must detect, parse and keep."""
        ...

    def dedup_keys(self, coords: CoordsValidation) -> pd.Series:
        """Per-row dedup key (Fork 1). Rows sharing a key collapse to one
        query point. Rows with invalid/absent coords must yield a null key
        (`pd.NA`/None) → excluded from the query, status set by the shell.
        """
        ...

    def match(self, points: QueryPoints) -> MatchResult:
        """Resolve the unique points → columns + statuses + method detail.
        All ERDDAP batching / nearest-neighbour / grid lookup lives here.
        """
        ...


# Status the shell assigns to rows the matcher never saw (invalid coords).
NO_COORDINATES_STATUS = "no_coordinates"


def _dedup_from_keys(keys: pd.Series) -> tuple[list[int], list[int | None]]:
    """Group rows by dedup key. Rows with a null key are not queryable.

    Returns `(unique_positions, row_to_unique)`:
      - `unique_positions` : first row position for each distinct non-null key,
        in first-seen order — these are the points handed to the matcher.
      - `row_to_unique` : per row, the index into `unique_positions`, or None
        when the row's key is null (invalid coords).
    """
    def _is_null(key) -> bool:
        return key is None or (not isinstance(key, tuple) and pd.isna(key))

    first_position: dict[object, int] = {}
    order: list[object] = []
    for position, key in enumerate(keys.tolist()):
        if _is_null(key):
            continue
        if key not in first_position:
            first_position[key] = position
            order.append(key)
    unique_positions = [first_position[key] for key in order]
    key_to_unique_index = {key: i for i, key in enumerate(order)}
    row_to_unique: list[int | None] = [
        None if _is_null(key) else key_to_unique_index[key]
        for key in keys.tolist()
    ]
    return unique_positions, row_to_unique


def _source_variable_name(store, thread_id: str, source_variable: str | None) -> str:
    if source_variable:
        return source_variable
    session = store.get(thread_id)
    name = (session.get("meta") or {}).get("variable_name") if session else None
    return name or "df_enriched"


def run_point_enrichment(
    store,
    thread_id: str,
    *,
    matcher: PointMatcher,
    source_variable: str | None = None,
    latitude_column: str | None = None,
    longitude_column: str | None = None,
    time_column: str | None = None,
    depth_column: str | None = None,
    zone_name: str | None = None,
    date_range: list | None = None,
) -> str:
    """Single, testable sequence for lat/lon point enrichment. See module doc."""
    label = matcher.label
    need = matcher.required_coords()

    # 1. resolve source + guard
    source = resolve_source_dataframe(store, thread_id, source_variable)
    if source is None:
        if source_variable:
            return (
                f"Variable source introuvable en session : `{source_variable}`. "
                "Vérifie les datasets actifs."
            )
        return "Aucune table chargée à enrichir."

    # 2. provenance note (before the new result overwrites active-df metadata)
    source_note = enrichment_source_note(store, thread_id, source, source_variable)

    # 3. detect coord columns per matcher.required_coords()
    lat_col = latitude_column or (
        detect_column(source.columns, DEFAULT_LAT_CANDIDATES) if need.lat else None
    )
    lon_col = longitude_column or (
        detect_column(source.columns, DEFAULT_LON_CANDIDATES) if need.lon else None
    )
    time_col = time_column or (
        detect_column(source.columns, DEFAULT_TIME_CANDIDATES) if need.time else None
    )
    time_end_col = (
        detect_column(source.columns, DEFAULT_TIME_END_CANDIDATES) if need.time else None
    )
    depth_col = depth_column or (
        detect_column(source.columns, DEFAULT_DEPTH_CANDIDATES) if need.depth else None
    )

    # 4. optional zone/date scoping + guards
    scoping_lines: list[str] = []
    if zone_name or date_range is not None:
        scoped = scope_dataframe(
            source,
            zone_name=zone_name,
            date_range=date_range,
            lat_col=lat_col or "latitude",
            lon_col=lon_col or "longitude",
            time_col=time_col,
        )
        if scoped.error:
            return f"Enrichissement {label} impossible : {scoped.error}"
        source = scoped.df
        scoping_lines = list(scoped.description_lines)
        if source.empty:
            return (
                f"Enrichissement {label} impossible : le filtre zone/date a "
                "éliminé toutes les lignes.\n" + "\n".join(scoping_lines)
            )

    # 5. missing-column guard (before parsing)
    missing = [
        name
        for name, needed, value in (
            ("latitude", need.lat, lat_col),
            ("longitude", need.lon, lon_col),
            ("time", need.time, time_col),
            ("depth", need.depth, depth_col),
        )
        if needed and value is None
    ]
    if missing:
        return (
            f"Enrichissement {label} impossible : colonnes manquantes dans la "
            f"table chargée — {', '.join(missing)}. Préciser via les paramètres "
            "de colonne."
        )

    # 6. parse coords + empty-groups guard
    coords = parse_source_coords(
        source,
        lat_col=lat_col,
        lon_col=lon_col,
        time_col=time_col,
        time_end_col=time_end_col,
        depth_col=depth_col,
    )
    if coords.empty_groups:
        return (
            f"Enrichissement {label} impossible : colonnes "
            f"{', '.join(coords.empty_groups)} entièrement vides dans la table "
            "chargée. Aucune coordonnée exploitable — vérifie le fichier source."
        )

    # 7. copy + 8. dedup (matcher declares the key, shell owns the mechanism)
    enriched = source.copy(deep=True).reset_index(drop=True)
    keys = matcher.dedup_keys(coords).reset_index(drop=True)
    unique_positions, row_to_unique = _dedup_from_keys(keys)

    n = len(enriched)
    status_col = f"{matcher.prefix}_match_status"

    if not unique_positions:
        enriched[status_col] = NO_COORDINATES_STATUS
        variable_name = _source_variable_name(store, thread_id, source_variable)
        store_dataset(
            store, thread_id, enriched,
            variable_name=variable_name,
            meta={"variable_name": variable_name, "source": f"enrich:{matcher.prefix}"},
        )
        return (
            f"Enrichissement {label} : 0 lignes matchées sur {n} — aucune "
            f"coordonnée exploitable.\n{source_note}"
        )

    def _at(series: pd.Series | None) -> pd.Series | None:
        if series is None:
            return None
        return series.reset_index(drop=True).iloc[unique_positions].reset_index(drop=True)

    points = QueryPoints(
        latitude=_at(coords.latitude),
        longitude=_at(coords.longitude),
        time=_at(coords.time),
        time_end=_at(coords.time_end),
        depth=_at(coords.depth),
    )

    # 9. delegate the MATCH to the adapter
    result = matcher.match(points)

    # 10. remap unique→row: append value columns + status column
    statuses = result.statuses.reset_index(drop=True)
    row_status = [
        statuses.iloc[u] if u is not None else NO_COORDINATES_STATUS
        for u in row_to_unique
    ]
    for column in result.columns.columns:
        unique_values = result.columns[column].reset_index(drop=True)
        enriched[column] = [
            unique_values.iloc[u] if u is not None else pd.NA
            for u in row_to_unique
        ]
    enriched[status_col] = row_status

    # 11. store enriched dataset back to session
    variable_name = _source_variable_name(store, thread_id, source_variable)
    store_dataset(
        store, thread_id, enriched,
        variable_name=variable_name,
        meta={"variable_name": variable_name, "source": f"enrich:{matcher.prefix}"},
    )

    # 12. method block with the coverage line (shell-owned invariant)
    lines = [
        f"Enrichissement {label} — {result.n_matched} lignes matchées sur {n}.",
        source_note,
        *scoping_lines,
        *result.method_lines,
    ]
    return "\n".join(line for line in lines if line)
