"""LangChain tools for Bio-ORACLE."""
from __future__ import annotations

import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
from langchain_core.tools import tool

from core.bio_oracle_catalog import (
    list_catalog_scenarios,
    list_catalog_variables,
    validate_enrichment_selection,
)
from core.bio_oracle_client import (
    _ERDDAP_BASE,
    _find_dataset_id,
    _resolve_depth,
    _resolve_scenario,
    _resolve_var,
    _time_selector,
    preview_bio_oracle_point as _preview_bio_oracle_point,
)
from core.canonical_grid import snap_bbox
from core.erddap_cache import cache_get, cache_set
from core.scientific_result_cache import (
    build_result_cache_key,
    load_result as load_scientific_result,
    save_result as save_scientific_result,
)
from core.environment_resolver import (
    resolve_source_dataframe,
)
from tools.dataset_registry import (
    dataset_variable_name,
    resolved_enrichment_source_variable,
    store_dataset,
)
from tools.point_enrichment import (
    MatchResult,
    QueryPoints,
    RequiredCoords,
    run_point_enrichment,
)
from tools.session_store import default_store as _store
from tools.tool_result import blocked, empty, error, success


def _bio_result(factory, summary: str, **fields):
    provenance = {"source": "bio_oracle", **dict(fields.pop("provenance", {}))}
    return factory(summary, provenance=provenance, **fields)


def _bio_success(summary: str, **fields): return _bio_result(success, summary, **fields)
def _bio_empty(summary: str, **fields): return _bio_result(empty, summary, **fields)
def _bio_blocked(summary: str, **fields): return _bio_result(blocked, summary, **fields)
def _bio_error(summary: str, **fields): return _bio_result(error, summary, **fields)

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)


def _clean_label(value: str) -> str:
    return str(value).lower().replace(".", "_").replace("-", "_").replace(" ", "_")


def _snap_coordinate(value: float, bin_degrees: float) -> float:
    if bin_degrees <= 0:
        return float(value)
    return round(round(float(value) / float(bin_degrees)) * float(bin_degrees), 6)


def _canonical_tile_for(latitude: float, longitude: float, tile_degrees: float = 5.0) -> dict:
    """Return the 5° canonical tile containing the given lat/lon."""
    return snap_bbox(
        {
            "lat_min": float(latitude),
            "lat_max": float(latitude),
            "lon_min": float(longitude),
            "lon_max": float(longitude),
        },
        tile_degrees=tile_degrees,
    )


# Region mode: when a point set would need more than this many fine 5° tiles,
# fetch ONE bounding tile at a coarse stride instead (one download beats dozens).
_REGION_TILE_BUDGET = 6
_REGION_STRIDE = 4


def _fetch_bio_oracle_bbox(
    *,
    variable: str,
    scenario: str,
    depth_layer: str,
    target_year: int | None,
    tile: dict,
    stride: int = 1,
    statistic: str = "mean",
) -> pd.DataFrame:
    """Fetch all Bio-ORACLE grid points within a canonical tile (one HTTP call).

    Returns a DataFrame with columns: time, latitude, longitude, value, plus
    `dataset_id` available via `df.attrs['dataset_id']`. Cached on disk under
    the canonical (tile × variable × scenario × depth × year × stride) key so
    future enrichments touching the same tile cost ~milliseconds.

    `stride` is the ERDDAP grid subsampling step (1 = full ~0.05° resolution).
    A coarser stride (e.g. 4 ≈ 0.2°) is used for wide "region" tiles covering
    many dispersed points, where one coarse download beats dozens of fine ones —
    fine for smooth fields such as climatological temperature.
    """
    try:
        from core.bio_oracle_catalog import resolve_catalog_variable

        var = resolve_catalog_variable(variable).erddap_var
    except ValueError:
        var = _resolve_var(variable)
    scen = _resolve_scenario(scenario)
    depth = _resolve_depth(depth_layer)
    stride = max(1, int(stride))
    # Canonical tiles can extend one grid step beyond the antimeridian for
    # points close to -180°/180°. ERDDAP rejects those out-of-range bounds
    # with 404 instead of clipping them, so bound the request explicitly.
    query_tile = {
        "lat_min": max(-90.0, min(90.0, float(tile["lat_min"]))),
        "lat_max": max(-90.0, min(90.0, float(tile["lat_max"]))),
        "lon_min": max(-180.0, min(180.0, float(tile["lon_min"]))),
        "lon_max": max(-180.0, min(180.0, float(tile["lon_max"]))),
    }
    cache_key = {
        "tile": query_tile,
        "variable": var,
        "scenario": scen,
        "depth_layer": depth,
        "target_year": target_year,
        "stride": stride,
        "statistic": statistic,
    }
    cached = cache_get("bio_oracle_bbox", cache_key)
    if cached is not None:
        return cached

    dataset_id = _find_dataset_id(var, scen, depth)
    griddap_url = f"{_ERDDAP_BASE}/griddap/{dataset_id}"
    query_var = f"{var}_{statistic}"
    time_sel = _time_selector({"target_year": target_year}, scenario=scen)
    url = (
        f"{griddap_url}.csv?{query_var}"
        f"[({time_sel})]"
        f"[({query_tile['lat_min']:.4f}):{stride}:({query_tile['lat_max']:.4f})]"
        f"[({query_tile['lon_min']:.4f}):{stride}:({query_tile['lon_max']:.4f})]"
    )
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    lines = response.text.splitlines()
    body = "\n".join([lines[0]] + lines[2:]) if len(lines) > 2 else response.text
    raw = pd.read_csv(io.StringIO(body))
    # Normalize: ERDDAP returns columns like time, latitude, longitude, thetao_mean
    value_col = query_var if query_var in raw.columns else raw.columns[-1]
    result = raw.rename(columns={value_col: "value"}).copy()
    result.attrs["dataset_id"] = dataset_id
    cache_set("bio_oracle_bbox", cache_key, result)
    return result


def _lookup_in_tile(
    tile_df: pd.DataFrame, *, latitude: float, longitude: float
) -> dict:
    """Find the nearest grid point in a cached tile DataFrame.

    Returns {"dataset_id", "time", "value"}. Returns NaN value if the tile is
    empty or all values are masked.
    """
    if tile_df.empty:
        return {
            "dataset_id": tile_df.attrs.get("dataset_id"),
            "time": None,
            "value": None,
        }
    valid = tile_df.dropna(subset=["value"])
    if valid.empty:
        return {
            "dataset_id": tile_df.attrs.get("dataset_id"),
            "time": (
                tile_df["time"].iloc[0] if "time" in tile_df.columns else None
            ),
            "value": None,
        }
    dlat = valid["latitude"].to_numpy() - float(latitude)
    dlon = valid["longitude"].to_numpy() - float(longitude)
    idx = (dlat * dlat + dlon * dlon).argmin()
    nearest = valid.iloc[int(idx)]
    raw_value = nearest["value"]
    try:
        value = round(float(raw_value), 4) if raw_value is not None else None
    except (TypeError, ValueError):
        value = None
    return {
        "dataset_id": tile_df.attrs.get("dataset_id"),
        "time": nearest.get("time"),
        "value": value,
    }


def _fetch_bio_oracle_point(
    *,
    latitude: float,
    longitude: float,
    variable: str,
    scenario: str,
    depth_layer: str,
    target_year: int | None,
) -> dict:
    """Fetch a single Bio-ORACLE value at one point.

    Returns {"dataset_id", "time", "value"}.
    """
    preview = _preview_bio_oracle_point(
        {
            "latitude": latitude,
            "longitude": longitude,
            "variable": variable,
            "scenario": scenario,
            "depth_layer": depth_layer,
            "target_year": target_year,
        }
    )
    value_key = preview.get("variable", "")
    rows = preview.get("rows") or []
    first = rows[0] if rows else {}
    raw_value = first.get(value_key)
    try:
        value = round(float(raw_value), 4) if raw_value is not None else None
    except (TypeError, ValueError):
        value = None
    return {
        "dataset_id": preview.get("dataset_id"),
        "time": first.get("time"),
        "value": value,
    }


def _format_table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "Aucun résultat Bio-ORACLE."
    dataframe = pd.DataFrame(rows)
    available_columns = [column for column in columns if column in dataframe.columns]
    if available_columns:
        dataframe = dataframe.loc[:, available_columns]
    return dataframe.to_markdown(index=False)


class BioOracleMatcher:
    """PointMatcher adapter for Bio-ORACLE gridded point-value lookup.

    Unlike the CTD matchers this is a grid lookup, not a nearest-profile match:
    for each unique point (deduped on the coordinate-grid bin) it queries one
    value per (variable × scenario) and writes a column per pair. Rows with
    invalid / out-of-range coords are never queried and land as `no_value`
    (hence `no_coordinates_status = "no_value"`). Enforces the confirmation
    gate before any HTTP by returning a `MatchResult.error`.
    """

    prefix = "bio_oracle"
    label = "Bio-ORACLE"
    no_coordinates_status = "no_value"

    def __init__(
        self,
        *,
        variables: list[str],
        scenarios: list[str],
        scenario_display_names: list[str] | None = None,
        depth_layer: str,
        target_year: int | None,
        statistic: str,
        coordinate_bin_degrees: float,
        max_unique_queries: int,
        confirmed: bool,
        max_workers: int,
    ):
        # Preserve user-facing column labels. The underlying client normalizes
        # aliases (for example SSP4-4.5 -> ssp245) before the ERDDAP request.
        self.variables = variables
        self.scenarios = scenarios
        self.scenario_display_names = scenario_display_names or list(scenarios)
        self.depth_layer = depth_layer
        self.target_year = target_year
        self.statistic = statistic
        self.coordinate_bin_degrees = coordinate_bin_degrees
        self.max_unique_queries = max_unique_queries
        self.confirmed = confirmed
        self.max_workers = max_workers

    def required_coords(self) -> RequiredCoords:
        return RequiredCoords(lat=True, lon=True)

    def dedup_keys(self, coords) -> pd.Series:
        lat = coords.latitude.reset_index(drop=True)
        lon = coords.longitude.reset_index(drop=True)
        bin_deg = float(self.coordinate_bin_degrees)
        keys = []
        for i in range(len(lat)):
            try:
                lat_f = float(lat.iloc[i])
                lon_f = float(lon.iloc[i])
            except (TypeError, ValueError):
                keys.append(pd.NA)
                continue
            if (
                pd.isna(lat_f) or pd.isna(lon_f)
                or not (-90.0 <= lat_f <= 90.0)
                or not (-180.0 <= lon_f <= 180.0)
            ):
                keys.append(pd.NA)
                continue
            keys.append((_snap_coordinate(lat_f, bin_deg), _snap_coordinate(lon_f, bin_deg)))
        return pd.Series(keys)

    def match(self, points: QueryPoints) -> MatchResult:
        n_unique = len(points)
        unique_query_count = n_unique * len(self.variables) * len(self.scenarios)
        if unique_query_count > int(self.max_unique_queries) and not self.confirmed:
            return MatchResult(
                columns=pd.DataFrame(index=range(n_unique)),
                statuses=pd.Series(["no_value"] * n_unique),
                error=(
                    f"Confirmation required: {unique_query_count} unique Bio-ORACLE "
                    "queries would be sent "
                    f"({len(self.variables)} variable(s) × {len(self.scenarios)} scenario(s), "
                    f"coordinate_bin_degrees={float(self.coordinate_bin_degrees):g}). "
                    "Ask the user for confirmation, then call again with "
                    "`confirmed=true`, or reduce variables/scenarios/source rows."
                ),
            )

        bin_deg = float(self.coordinate_bin_degrees)
        snapped = [
            (
                _snap_coordinate(float(points.latitude.iloc[i]), bin_deg),
                _snap_coordinate(float(points.longitude.iloc[i]), bin_deg),
            )
            for i in range(n_unique)
        ]
        unique_query_keys = {
            (lat_f, lon_f, variable, scenario, self.depth_layer, self.statistic, self.target_year)
            for lat_f, lon_f in snapped
            for variable in self.variables
            for scenario in self.scenarios
        }

        from collections import defaultdict

        # Group query points per (variable, scenario, layer, year) to decide,
        # per group, between many fine 5° tiles or one coarse region tile.
        by_layer: dict[tuple, list[tuple]] = defaultdict(list)
        for key in unique_query_keys:
            lat_f, lon_f, variable, scenario, layer, statistic, year = key
            by_layer[(variable, scenario, layer, statistic, year)].append(key)

        tile_jobs: dict[tuple, dict] = {}
        point_to_tile_key: dict[tuple, tuple] = {}
        for (variable, scenario, layer, statistic, year), keys in by_layer.items():
            scenario_display = self.scenario_display_names[
                self.scenarios.index(scenario)
            ]
            fine = {key: _canonical_tile_for(key[0], key[1]) for key in keys}
            distinct_fine = {
                (t["lat_min"], t["lat_max"], t["lon_min"], t["lon_max"])
                for t in fine.values()
            }
            if len(distinct_fine) > _REGION_TILE_BUDGET:
                # Region mode: one coarse bounding tile for the whole group.
                lats = [key[0] for key in keys]
                lons = [key[1] for key in keys]
                pad = 1.0
                tile = {
                    "lat_min": min(lats) - pad, "lat_max": max(lats) + pad,
                    "lon_min": min(lons) - pad, "lon_max": max(lons) + pad,
                }
                tile_key = (
                    tile["lat_min"], tile["lat_max"], tile["lon_min"], tile["lon_max"],
                    variable, scenario, layer, statistic, year, _REGION_STRIDE,
                )
                tile_jobs.setdefault(tile_key, {
                    "tile": tile, "variable": variable, "scenario": scenario_display,
                    "depth_layer": layer, "target_year": year, "statistic": statistic,
                    "stride": _REGION_STRIDE,
                })
                for key in keys:
                    point_to_tile_key[key] = tile_key
            else:
                for key in keys:
                    tile = fine[key]
                    tile_key = (
                        tile["lat_min"], tile["lat_max"],
                        tile["lon_min"], tile["lon_max"],
                        variable, scenario, layer, statistic, year, 1,
                    )
                    point_to_tile_key[key] = tile_key
                    # Fine mode: omit `stride` (defaults to 1) so the payload stays
                    # backward-compatible with callers/mocks predating the stride arg.
                    tile_jobs.setdefault(tile_key, {
                        "tile": tile, "variable": variable, "scenario": scenario_display,
                        "depth_layer": layer, "target_year": year, "statistic": statistic,
                    })

        def _fetch_tile(args: tuple) -> tuple[tuple, pd.DataFrame | None, str | None]:
            tile_key, payload = args
            try:
                return tile_key, _fetch_bio_oracle_bbox(**payload), None
            except Exception as exc:
                return tile_key, None, str(exc)

        tile_dfs: dict[tuple, pd.DataFrame | None] = {}
        tile_failures: list[str] = []
        job_items = list(tile_jobs.items())
        effective_workers = max(1, min(int(self.max_workers), len(job_items) or 1))
        if effective_workers == 1 or len(job_items) <= 1:
            for item in job_items:
                tk, df, failure = _fetch_tile(item)
                tile_dfs[tk] = df
                if failure:
                    tile_failures.append(failure)
        else:
            with ThreadPoolExecutor(max_workers=effective_workers) as pool:
                for tk, df, failure in pool.map(_fetch_tile, job_items):
                    tile_dfs[tk] = df
                    if failure:
                        tile_failures.append(failure)

        if tile_jobs and len(tile_failures) == len(tile_jobs):
            detail = tile_failures[0].replace("\n", " ")[:240]
            return MatchResult(
                columns=pd.DataFrame(index=range(n_unique)),
                statuses=pd.Series(["no_value"] * n_unique),
                error=(
                    "Bio-ORACLE indisponible pour cette requête : toutes les "
                    f"{len(tile_jobs)} récupérations distantes ont échoué ({detail}). "
                    "Aucun enrichissement n'a été enregistré."
                ),
            )

        cache: dict[tuple, dict] = {}
        for key in unique_query_keys:
            lat_f, lon_f, *_ = key
            tile_df = tile_dfs.get(point_to_tile_key[key])
            if tile_df is None:
                cache[key] = {"value": None, "dataset_id": None, "time": None}
            else:
                cache[key] = _lookup_in_tile(tile_df, latitude=lat_f, longitude=lon_f)

        columns: dict[str, list] = {}
        point_has_value = [False] * n_unique
        for variable in self.variables:
            for scenario, display_scenario in zip(
                self.scenarios, self.scenario_display_names
            ):
                values: list[object] = []
                dataset_ids: list[object] = []
                times: list[object] = []
                for i in range(n_unique):
                    lat_f, lon_f = snapped[i]
                    fetched = cache[
                    (lat_f, lon_f, variable, scenario, self.depth_layer, self.statistic, self.target_year)
                    ]
                    value = fetched["value"]
                    is_real_value = value is not None and not pd.isna(value)
                    values.append(value if is_real_value else pd.NA)
                    dataset_ids.append(fetched.get("dataset_id") or pd.NA)
                    times.append(fetched.get("time") or pd.NA)
                    if is_real_value:
                        point_has_value[i] = True
                statistic_suffix = "" if self.statistic == "mean" else f"_{_clean_label(self.statistic)}"
                stub = (
                    f"bio_oracle_{_clean_label(variable)}_{_clean_label(display_scenario)}"
                    f"{statistic_suffix}"
                )
                columns[stub] = values
                columns[f"{stub}_dataset_id"] = dataset_ids
                columns[f"{stub}_time"] = times

        # The first explicitly selected scenario is the reference.  Each later
        # scenario receives its own row-level delta, but only where both
        # scenario values exist on that same source row.  This preserves every
        # row and makes missing coverage visible as a null delta instead of a
        # substituted value.
        if len(self.scenarios) > 1:
            reference_display = self.scenario_display_names[0]
            for variable in self.variables:
                statistic_suffix = (
                    "" if self.statistic == "mean"
                    else f"_{_clean_label(self.statistic)}"
                )
                reference_stub = (
                    f"bio_oracle_{_clean_label(variable)}_"
                    f"{_clean_label(reference_display)}{statistic_suffix}"
                )
                reference_values = pd.to_numeric(
                    pd.Series(columns[reference_stub]), errors="coerce"
                )
                for target_display in self.scenario_display_names[1:]:
                    target_stub = (
                        f"bio_oracle_{_clean_label(variable)}_"
                        f"{_clean_label(target_display)}{statistic_suffix}"
                    )
                    target_values = pd.to_numeric(
                        pd.Series(columns[target_stub]), errors="coerce"
                    )
                    calculable = reference_values.notna() & target_values.notna()
                    delta_stub = (
                        f"bio_oracle_{_clean_label(variable)}_"
                        f"{_clean_label(target_display)}_minus_"
                        f"{_clean_label(reference_display)}{statistic_suffix}"
                    )
                    columns[delta_stub] = target_values.sub(reference_values).where(
                        calculable, pd.NA
                    ).tolist()

        statuses = pd.Series(
            ["matched" if has_value else "no_value" for has_value in point_has_value]
        )
        return MatchResult(
            columns=pd.DataFrame(columns),
            statuses=statuses,
            n_matched=point_has_value.count(True),
            diagnostics={
                "unique_query_count": unique_query_count,
                "statistic": self.statistic,
            },
        )


def make_bio_oracle_tools(thread_id: str) -> list:
    """Create LangChain Bio-ORACLE tools for one thread."""

    def _source_dataframe_with_columns(
        latitude_column: str,
        longitude_column: str,
    ) -> tuple[pd.DataFrame | None, str | None]:
        """Find the current or named source table that has the requested coords."""
        session = _store.get(thread_id)
        current = session.get("df") if session else None
        if (
            isinstance(current, pd.DataFrame)
            and not current.empty
            and latitude_column in current.columns
            and longitude_column in current.columns
        ):
            return current, None

        candidates: list[tuple[str, pd.DataFrame]] = []
        for key in _store.keys(f"{thread_id}:dataset:"):
            named = _store.get(key)
            dataframe = named.get("df") if named else None
            if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
                continue
            if latitude_column in dataframe.columns and longitude_column in dataframe.columns:
                variable_name = (named.get("meta") or {}).get("variable_name") or key.rsplit(":", 1)[-1]
                candidates.append((variable_name, dataframe))

        if not candidates:
            return current if isinstance(current, pd.DataFrame) else None, None

        file_candidates = [
            candidate
            for candidate in candidates
            if str(candidate[0]).startswith("df_file_")
        ]
        variable_name, dataframe = (file_candidates or candidates)[0]
        return dataframe, variable_name







    @tool(response_format="content_and_artifact")
    def enrich_with_bio_oracle(
        variables: list[str] | None = None,
        scenarios: list[str] | None = None,
        depth_layer: str | None = None,
        statistic: str | None = None,
        target_year: int | None = None,
        latitude_column: str | None = None,
        longitude_column: str | None = None,
        source_variable: str | None = None,
        coordinate_bin_degrees: float = 1 / 12,
        max_unique_queries: int = 1000,
        confirmed: bool = True,
        max_workers: int = 8,
        zone_name: str | None = None,
        date_range: list | None = None,
    ) -> str:
        """Enrichit chaque ligne d'un DataFrame chargé avec Bio-ORACLE.

        Si un paramètre scientifique n'est pas précisé, le preset direct est
        `temperature`, `baseline`, `surface`, `mean` :
        - variables copépodes recommandées : `temperature`, `salinity`,
          `oxygen`, `nitrate`, `phosphate`, `silicate`, `chlorophyll`,
          `primary_productivity`, `mixed_layer_depth`, `par`,
          `diffuse_attenuation` ; catalogue complet : `sea_water_speed`,
          `sea_water_direction`, `iron`, `ph`, `sea_ice_thickness`,
          `sea_ice_cover`, `cloud_cover`, `air_temperature` ;
        - scénarios : `baseline`, `SSP1-1.9`, `SSP2-4.5`, `SSP3-7.0`,
          `SSP4-6.0`, `SSP5-8.5` ; couches : `surface`, `benthic_min`,
          `benthic_mean`, `benthic_max` ; statistiques : `mean`, `min`,
          `max`, `lt_min`, `lt_max`, `range`.
        Une année cible reste obligatoire pour un scénario SSP. Une sélection
        invalide est bloquée sans I/O distant. Le tool conserve toutes les lignes
        et n'agrège jamais par zone. Auto-détecte les colonnes
        latitude/longitude ; si plusieurs fichiers sont en session, passe
        `source_variable` pour cibler un dataset précis. Chaque variable et
        scénario possède un libellé, une unité ou un niveau d'émission et une
        description factuelle dans le catalogue ; les expliquer sans inventer
        d'effet biologique. Avec plusieurs scénarios, le premier est la
        référence : le tool ajoute un delta (scénario suivant − référence) sur
        les seules lignes où les deux valeurs sont numériques, et rapporte le
        dénominateur calculable ainsi que les valeurs manquantes.
        """
        variables = variables or ["temperature"]
        scenarios = scenarios or ["baseline"]
        depth_layer = depth_layer or "surface"
        statistic = statistic or "mean"
        selection = validate_enrichment_selection(
            variables=variables,
            scenarios=scenarios,
            depth_layer=depth_layer,
            statistic=statistic,
            target_year=target_year,
        )
        if not selection["ok"]:
            catalog = list_catalog_variables()
            recommended = [
                f"{item['key']} — {item['label']} ({item['unit']}) : {item['description']}"
                for item in catalog
                if item["recommended_for_copepods"]
            ]
            extras = [
                f"{item['key']} — {item['label']} ({item['unit']}) : {item['description']}"
                for item in catalog
                if not item["recommended_for_copepods"]
            ]
            scenarios = " ".join(
                f"{item['display_name']} : {item['description']}"
                for item in list_catalog_scenarios()
            )
            missing = ", ".join(selection.get("missing") or [])
            missing_line = f" Champs manquants : {missing}." if missing else ""
            return _bio_blocked(
                f"{selection['code']}: {selection['message']}{missing_line}\n"
                "Variables copépodes recommandées à choisir : "
                f"{' ; '.join(recommended)}.\n"
                "Variables supplémentaires du catalogue : "
                f"{' ; '.join(extras)}.\n"
                f"Scénarios : {scenarios}.\n"
                "Couches : surface, benthic_min, benthic_mean, benthic_max. "
                "Statistiques : mean, min, max, lt_min, lt_max, range."
            )

        variables = selection["variables"]
        scenarios = selection["scenarios"]
        scenario_display_names = selection["scenario_display_names"]
        depth_layer = selection["depth_layer"]
        depth_layer_display = selection["depth_layer_display"]
        statistic = selection["statistic"]
        target_year = selection["target_year"]

        source_for_cache = resolve_source_dataframe(
            _store, thread_id, source_variable
        )
        resolved_source_variable = resolved_enrichment_source_variable(
            _store, thread_id, source_variable
        )
        cache_key = None
        cache_parameters = {
            "variables": variables,
            "scenarios": scenarios,
            "scenario_display_names": scenario_display_names,
            "depth_layer": depth_layer,
            "statistic": statistic,
            "target_year": target_year,
            "latitude_column": latitude_column,
            "longitude_column": longitude_column,
            "coordinate_bin_degrees": coordinate_bin_degrees,
            "zone_name": zone_name,
            "date_range": date_range,
        }
        # Conservative upper bound: never let a cache hit bypass the existing
        # high-volume confirmation gate. Duplicate coordinates may make the
        # real query smaller; in that case the normal matcher remains the
        # authority and can still accept the request.
        cache_gate_safe = bool(
            source_for_cache is not None
            and (
                confirmed
                or len(source_for_cache) * len(variables) * len(scenarios)
                <= int(max_unique_queries)
            )
        )
        if cache_gate_safe:
            cache_key = build_result_cache_key(
                source_for_cache,
                cache_parameters,
            )
            cached = load_scientific_result(
                "bio_oracle_enrichment", cache_key
            )
            if cached is not None:
                enriched = cached.dataframe
                variable_name = dataset_variable_name(
                    "bio_oracle_enriched", uuid.uuid4().hex[:12]
                )
                store_dataset(
                    _store,
                    thread_id,
                    enriched,
                    variable_name=variable_name,
                    meta={
                        "source": "bio_oracle_enrichment",
                        "source_variable": resolved_source_variable,
                        "description": (
                            f"Table {resolved_source_variable or 'active'} enriched "
                            "with Bio-ORACLE variables and scenarios."
                        ),
                        "n_rows": len(enriched),
                        "cache_hit": True,
                        "cached_at": cached.cached_at,
                        "cache_provenance": cached.provenance,
                    },
                )
                status_counts = enriched[
                    "bio_oracle_match_status"
                ].value_counts().to_dict()
                n_matched = int(status_counts.get("matched", 0))
                n_no_value = int(status_counts.get("no_value", 0))
                return _bio_success(
                    f"Enrichissement Bio-ORACLE réutilisé depuis le cache exact "
                    f"({cached.cached_at}) : {len(enriched)} ligne(s), "
                    f"{n_matched} matchée(s), {n_no_value} no_value.\n"
                    f"Données disponibles dans `{variable_name}`. Toutes les "
                    "lignes du résultat original sont conservées.",
                    data_ref=variable_name,
                    persisted=True,
                    method="Bio-ORACLE exact scientific result cache",
                    metrics={
                        "rows": len(enriched),
                        "matched": n_matched,
                        "no_value": n_no_value,
                        "cache_hit": True,
                    },
                )

        matcher = BioOracleMatcher(
            variables=variables,
            scenarios=scenarios,
            scenario_display_names=scenario_display_names,
            depth_layer=depth_layer,
            target_year=target_year,
            statistic=statistic,
            coordinate_bin_degrees=coordinate_bin_degrees,
            max_unique_queries=max_unique_queries,
            confirmed=confirmed,
            max_workers=max_workers,
        )
        outcome = run_point_enrichment(
            _store,
            thread_id,
            matcher=matcher,
            source_variable=source_variable,
            latitude_column=latitude_column,
            longitude_column=longitude_column,
            zone_name=zone_name,
            date_range=date_range,
        )
        if outcome.error:
            return _bio_blocked(outcome.error)

        enriched = outcome.enriched
        cache_provenance = {
            **cache_parameters,
            "match_status_counts": enriched[
                "bio_oracle_match_status"
            ].value_counts().to_dict(),
            "dataset_ids": sorted(
                {
                    str(value)
                    for column in enriched.columns
                    if str(column).endswith("_dataset_id")
                    for value in enriched[column].dropna().unique()
                }
            ),
        }
        cached_at = None
        if cache_key is not None:
            cached_at = save_scientific_result(
                "bio_oracle_enrichment",
                cache_key,
                enriched,
                provenance=cache_provenance,
            ).cached_at
        variable_name = dataset_variable_name(
            "bio_oracle_enriched", uuid.uuid4().hex[:12]
        )
        store_dataset(
            _store,
            thread_id,
            enriched,
            variable_name=variable_name,
            meta={
                "source": "bio_oracle_enrichment",
                "source_variable": resolved_source_variable,
                "description": (
                    f"Table {resolved_source_variable or 'active'} enriched with "
                    "Bio-ORACLE variables and scenarios."
                ),
                "n_rows": len(enriched),
                "cache_hit": False,
                "cached_at": cached_at,
                "cache_provenance": cache_provenance,
            },
        )
        status_counts = enriched["bio_oracle_match_status"].value_counts().to_dict()
        n_matched = int(status_counts.get("matched", 0))
        n_no_value = int(status_counts.get("no_value", 0))
        unique_query_count = outcome.diagnostics.get("unique_query_count", 0)
        scenario_delta_lines: list[str] = []
        if len(scenarios) > 1:
            reference_display = scenario_display_names[0]
            statistic_suffix = "" if statistic == "mean" else f"_{_clean_label(statistic)}"
            denominator = len(enriched)
            for variable in variables:
                for target_display in scenario_display_names[1:]:
                    delta_column = (
                        f"bio_oracle_{_clean_label(variable)}_"
                        f"{_clean_label(target_display)}_minus_"
                        f"{_clean_label(reference_display)}{statistic_suffix}"
                    )
                    calculable = int(enriched[delta_column].notna().sum())
                    missing = denominator - calculable
                    scenario_delta_lines.append(
                        f"- Delta {variable} ({target_display} − {reference_display}) : "
                        f"calculable={calculable}/{denominator}; "
                        f"{missing} valeur manquante"
                        f"{'s' if missing != 1 else ''}."
                    )
        method_lines = [
            "Méthode :",
            *outcome.scoping_lines,
            (
                f"- Colonnes source détectées : latitude={outcome.lat_col!r}, "
                f"longitude={outcome.lon_col!r}"
            ),
            (
                "- Datasets Bio-ORACLE : un par (variable × scénario), "
                f"depth_layer={depth_layer_display!r} ({depth_layer!r}), "
                f"statistic={statistic!r}, "
                f"target_year={target_year!r}"
            ),
            f"- Variables : {', '.join(variables)}",
            f"- Scénarios : {', '.join(scenario_display_names)}",
            (
                f"- Dédup par point unique sur grille "
                f"{float(coordinate_bin_degrees):g}° pour économiser les appels ERDDAP"
            ),
            (
                f"- Requêtes Bio-ORACLE uniques : {unique_query_count} "
                f"(max_unique_queries={int(max_unique_queries)}, "
                f"confirmed={bool(confirmed)})"
            ),
            f"- Statuts : matched={n_matched}, no_value={n_no_value}",
            *scenario_delta_lines,
        ]
        if n_no_value:
            method_lines.append(
                f"- Note : {n_no_value} ligne(s) sans valeur — point hors "
                "couverture de la grille Bio-ORACLE (souvent terre ou bord)."
            )
        return _bio_success(
            f"Enrichissement Bio-ORACLE — {len(enriched)} ligne(s), "
            f"{n_matched} matchée(s).\n"
            f"{outcome.source_note}\n"
            f"Données disponibles dans `{variable_name}`.\n\n"
            + "\n".join(method_lines),
            data_ref=variable_name,
            persisted=True,
            method="Bio-ORACLE gridded point enrichment",
            metrics={"rows": len(enriched), "matched": n_matched},
        )

    return [enrich_with_bio_oracle]
