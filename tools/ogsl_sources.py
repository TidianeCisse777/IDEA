"""LangChain tools for OGSL environmental profiles."""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
from langchain_core.tools import tool

from core.ogsl_client import OGSL_DATASET_ID
from tools.dataset_registry import (
    OGSL_ENRICHED,
    dataset_variable_name,
    store_dataset,
)
from tools.ctd_matcher import CtdProfileMatcher
from tools.point_enrichment import format_method_block, run_point_enrichment
from tools.session_store import default_store as _store
from tools.tool_result import blocked, success

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)


def _ogsl_result(factory, summary: str, **fields):
    provenance = {"source": "ogsl", **dict(fields.pop("provenance", {}))}
    return factory(summary, provenance=provenance, **fields)


def _ogsl_success(summary: str, **fields): return _ogsl_result(success, summary, **fields)
def _ogsl_blocked(summary: str, **fields): return _ogsl_result(blocked, summary, **fields)

_OGSL_TABLEDAP_URL = (
    f"https://erddap.ogsl.ca/erddap/tabledap/{OGSL_DATASET_ID}.csvp"
)
_OGSL_CORE_COLUMNS = (
    "time",
    "latitude",
    "longitude",
    "cruiseID",
    "stationID",
    "cast_number",
    "PRES",
)
# Friendly-name → OGSL-native mapping (Bio-ORACLE-style names → ERDDAP cols).
_OGSL_FRIENDLY_VARS: dict[str, str] = {
    "temperature": "TE90", "temp": "TE90", "température": "TE90",
    "te90": "TE90",
    "salinity": "PSAL", "salinité": "PSAL", "salinite": "PSAL", "sal": "PSAL",
    "psal": "PSAL",
    "oxygen": "OXYM", "oxygène": "OXYM", "oxygene": "OXYM", "o2": "OXYM",
    "oxym": "OXYM",
    "ph": "PHPH", "phph": "PHPH",
    "nitrate": "NTRA", "no3": "NTRA", "ntra": "NTRA",
    "chlorophyll": "FLOR", "chlorophylle": "FLOR", "chl": "FLOR",
    "fluorescence": "FLOR", "flor": "FLOR",
    "density": "SIGT", "densité": "SIGT", "sigma": "SIGT", "sigt": "SIGT",
    "turbidity": "TRB", "trb": "TRB",
    "iron": "FLOR",
    "dfe": "FLOR",
}


def _normalize_ogsl_var(value: str) -> str:
    if not isinstance(value, str):
        return str(value)
    return _OGSL_FRIENDLY_VARS.get(value.strip().lower(), value)


class OgslMatcher(CtdProfileMatcher):
    """CTD nearest-profile matcher for OGSL ISMER ERDDAP.

    Uses the shared CtdProfileMatcher machinery with the default query policy
    (no fixed time-range gate) and adds OGSL's station/cruise/oxygen columns.
    """

    prefix = "ogsl"
    label = "OGSL"
    dataset_id = OGSL_DATASET_ID

    def _fetch(self, **kwargs):
        return _fetch_ogsl_bbox(**kwargs)

    def _extra_columns(self, matched, n_unique):
        station_id: list = [pd.NA] * n_unique
        cruise_id: list = [pd.NA] * n_unique
        cast: list = [pd.NA] * n_unique
        oxym: list = [pd.NA] * n_unique
        for position, item in enumerate(matched):
            if item is None:
                continue
            best, _ = item
            station_id[position] = best.get("stationID")
            cruise_id[position] = best.get("cruiseID")
            cast[position] = best.get("cast_number")
            oxym[position] = best.get("OXYM")
        return {
            "ogsl_station_id": station_id,
            "ogsl_cruise_id": cruise_id,
            "ogsl_cast_number": cast,
            "ogsl_oxym_umol_kg": oxym,
        }


def _fetch_ogsl_bbox(
    *,
    bbox: dict,
    time_window: dict,
    variables: list[str],
    pres_range: dict | None = None,
) -> pd.DataFrame:
    """Fetch OGSL CTD rows within a bbox + time window from ERDDAP tabledap."""
    columns = list(dict.fromkeys([*_OGSL_CORE_COLUMNS, *variables]))
    constraints = [
        f"latitude>={float(bbox['lat_min']):.4f}",
        f"latitude<={float(bbox['lat_max']):.4f}",
        f"longitude>={float(bbox['lon_min']):.4f}",
        f"longitude<={float(bbox['lon_max']):.4f}",
        f"time>={time_window['start']}",
        f"time<={time_window['end']}",
    ]
    if pres_range is not None:
        constraints.extend(
            [
                f"PRES>={float(pres_range['min']):.3f}",
                f"PRES<={float(pres_range['max']):.3f}",
            ]
        )
    query = ",".join(columns) + "&" + "&".join(
        quote(c, safe="><=:-T.Z") for c in constraints
    )
    url = f"{_OGSL_TABLEDAP_URL}?{query}"
    response = requests.get(url, timeout=60)
    if response.status_code == 404:
        return pd.DataFrame(columns=columns)
    response.raise_for_status()
    dataframe = pd.read_csv(io.StringIO(response.text))
    # ERDDAP .csvp suffixes columns with units, e.g. "PRES (decibars)".
    import re
    dataframe = dataframe.rename(
        columns={c: re.sub(r"\s+\([^)]*\)$", "", str(c)) for c in dataframe.columns}
    )
    return dataframe


def make_ogsl_tools(thread_id: str) -> list:
    """Create LangChain OGSL tools for one thread."""


    @tool(response_format="content_and_artifact")
    def enrich_with_ogsl(
        latitude_column: str | None = None,
        longitude_column: str | None = None,
        time_column: str | None = None,
        depth_column: str | None = None,
        variables: list[str] | None = None,
        spatial_tolerance_km: float = 25.0,
        time_tolerance_hours: float = 24.0,
        source_variable: str | None = None,
        initial_batch_spatial_degrees: float = 5.0,
        batch_spatial_degrees: float = 5.0,
        max_source_points_per_batch: int = 50,
        max_ctd_rows_per_batch: int = 20000,
        depth_padding_dbar: float = 25.0,
        max_workers: int = 6,
        zone_name: str | None = None,
        date_range: list | None = None,
    ) -> str:
        """Enrichit la table chargée avec OGSL ISMER CTD par lat/lon/time.

        Auto-détecte les colonnes lat/lon/time/depth. Interroge OGSL ERDDAP
        par lots bbox + fenêtre temps en parallèle, puis matche localement au
        plus proche voisin. Si plusieurs fichiers sont en session, passe
        `source_variable` (ex. `df_file_filet_arctic_2018`) pour cibler un
        dataset précis.
        """
        raw_variables = list(
            variables or ["TE90", "PSAL", "SIGT", "OXYM", "PHPH", "NTRA", "FLOR"]
        )
        selected_variables: list[str] = []
        for v in raw_variables:
            translated = _normalize_ogsl_var(v)
            if translated not in selected_variables:
                selected_variables.append(translated)

        matcher = OgslMatcher(
            selected_variables=selected_variables,
            spatial_tolerance_km=spatial_tolerance_km,
            time_tolerance_hours=time_tolerance_hours,
            initial_batch_spatial_degrees=initial_batch_spatial_degrees,
            batch_spatial_degrees=batch_spatial_degrees,
            max_source_points_per_batch=max_source_points_per_batch,
            max_ctd_rows_per_batch=max_ctd_rows_per_batch,
            depth_padding_dbar=depth_padding_dbar,
            max_workers=max_workers,
        )
        outcome = run_point_enrichment(
            _store,
            thread_id,
            matcher=matcher,
            source_variable=source_variable,
            latitude_column=latitude_column,
            longitude_column=longitude_column,
            time_column=time_column,
            depth_column=depth_column,
            zone_name=zone_name,
            date_range=date_range,
        )
        if outcome.error:
            return _ogsl_blocked(outcome.error)

        enriched = outcome.enriched
        n = outcome.n_rows
        n_unique = outcome.n_unique
        diag = outcome.diagnostics

        variable_name = dataset_variable_name("ogsl_enriched", uuid.uuid4().hex[:12])
        status_counts = enriched["ogsl_match_status"].value_counts().to_dict()
        n_matched = int(status_counts.get("matched", 0))
        n_no_value = int(status_counts.get("matched_no_value", 0))
        n_no_match = int(status_counts.get("no_match", 0))
        store_dataset(
            _store, thread_id, enriched,
            variable_name=variable_name,
            meta={
                "source": "ogsl_enrichment",
                "n_rows": n,
                "matched_rows": n_matched,
            },
            latest_alias=OGSL_ENRICHED,
        )
        plural = "matchées" if n_matched > 1 else "matchée"
        method_lines = format_method_block(outcome) + [
            (
                f"- Colonnes source détectées : latitude={outcome.lat_col!r}, "
                f"longitude={outcome.lon_col!r}, time={outcome.time_col!r}"
                + (f", depth={outcome.depth_col!r}" if outcome.depth_col else "")
            ),
            f"- Dataset interrogé : OGSL ERDDAP `{OGSL_DATASET_ID}`",
            (
                f"- Tolérances : spatial={spatial_tolerance_km:g} km, "
                f"temps={time_tolerance_hours:g} h"
            ),
            f"- Variables récupérées : {', '.join(selected_variables)}",
            (
                f"- Points source uniques interrogés : {n_unique} sur "
                f"{n} ligne(s)"
            ),
            (
                f"- Bornes batch : max_source_points={int(max_source_points_per_batch)}, "
                f"max_ctd_rows={int(max_ctd_rows_per_batch)}, "
                f"depth_padding_dbar={float(depth_padding_dbar):g}"
            ),
            (
                f"- Requêtes ERDDAP : {diag['erddap_calls']} lot(s) temps-espace "
                f"({diag['batch_count']} lot(s) initiaux par mois/grille "
                f"{float(initial_batch_spatial_degrees):g}°, "
                f"{diag['fallback_months']} lot(s) splitté(s) en "
                f"{diag['fallback_subbatches']} sous-lot(s) grille "
                f"{float(batch_spatial_degrees):g}°)"
            ),
            (
                f"- Statuts : matched={n_matched}, "
                f"matched_no_value={n_no_value}, no_match={n_no_match}"
            ),
        ]
        matched_mask = enriched["ogsl_match_status"].isin(
            ["matched", "matched_no_value"]
        )
        if matched_mask.any():
            dist_series = pd.to_numeric(
                enriched.loc[matched_mask, "ogsl_distance_km"], errors="coerce"
            ).dropna()
            time_series = pd.to_numeric(
                enriched.loc[matched_mask, "ogsl_time_delta_min"], errors="coerce"
            ).dropna()
            if len(dist_series) or len(time_series):
                quality_bits: list[str] = []
                if len(dist_series):
                    quality_bits.append(
                        f"distance_km min={dist_series.min():.2f} "
                        f"med={dist_series.median():.2f} max={dist_series.max():.2f}"
                    )
                if len(time_series):
                    quality_bits.append(
                        f"time_delta_min min={time_series.min():.1f} "
                        f"med={time_series.median():.1f} max={time_series.max():.1f}"
                    )
                method_lines.append(
                    "- Qualité d'appariement (sur lignes matched) : "
                    + " ; ".join(quality_bits)
                )
        fetch_failures = diag.get("fetch_failures", [])
        if fetch_failures:
            method_lines.append(
                f"- Avertissement : {len(fetch_failures)} lot(s) ERDDAP en erreur, "
                "lignes conservées avec `no_match`."
            )
        if n_no_match:
            method_lines.append(
                f"- Note : {n_no_match} ligne(s) sans match — la zone-date "
                "n'est probablement pas couverte par OGSL ISMER CTD."
            )
        if n_no_value:
            method_lines.append(
                f"- Note : {n_no_value} ligne(s) avec profil trouvé mais "
                "valeurs CTD manquantes à l'origine."
            )
        return _ogsl_success(
            f"Enrichissement OGSL — {n} ligne(s), {n_matched} {plural}.\n"
            f"{outcome.source_note}\n"
            f"Données disponibles dans `{variable_name}`.\n\n"
            + "\n".join(method_lines),
            data_ref=variable_name,
            persisted=True,
            method="OGSL spatiotemporal nearest-neighbor enrichment",
            metrics={"rows": n, "matched": n_matched, "unique_points": n_unique},
        )

    return [enrich_with_ogsl]
