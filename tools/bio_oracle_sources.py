"""LangChain tools for Bio-ORACLE."""
from __future__ import annotations

import json
import hashlib
import uuid
from pathlib import Path

import pandas as pd
from langchain_core.tools import tool

from core.bio_oracle_client import (
    describe_bio_oracle_source,
    list_bio_oracle_datasets as _list_bio_oracle_datasets,
    preview_bio_oracle_point as _preview_bio_oracle_point,
    query_bio_oracle as _query_bio_oracle,
)
from tools.dataset_registry import dataset_variable_name, store_dataset
from tools.public_url import download_url
from tools.session_store import default_store as _store

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)


def _format_table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "Aucun résultat Bio-ORACLE."
    dataframe = pd.DataFrame(rows)
    available_columns = [column for column in columns if column in dataframe.columns]
    if available_columns:
        dataframe = dataframe.loc[:, available_columns]
    return dataframe.to_markdown(index=False)


def make_bio_oracle_tools(thread_id: str) -> list:
    """Create LangChain Bio-ORACLE tools for one thread."""

    @tool
    def list_bio_oracle_datasets() -> str:
        """Liste les datasets Bio-ORACLE disponibles dans ERDDAP."""
        try:
            datasets = _list_bio_oracle_datasets()
        except Exception as exc:
            return f"Erreur lors de l'accès à Bio-ORACLE : {exc}"
        if not datasets:
            return "Aucun dataset Bio-ORACLE trouvé."
        return _format_table(datasets, ["dataset_id", "title", "griddap"])

    @tool
    def preview_bio_oracle_point(latitude: float, longitude: float, variable: str, scenario: str, depth_layer: str) -> str:
        """Prévisualise un point Bio-ORACLE pour une variable, un scénario et une couche de profondeur."""
        try:
            preview = _preview_bio_oracle_point(
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                }
            )
            return _format_table(preview["rows"], ["time", "latitude", "longitude", variable])
        except Exception as exc:
            return f"Erreur lors de l'accès à Bio-ORACLE : {exc}"

    @tool
    def query_bio_oracle(latitude: float, longitude: float, variable: str, scenario: str, depth_layer: str) -> str:
        """Extrait Bio-ORACLE pour un point et écrit un TSV téléchargeable."""
        try:
            file_id = uuid.uuid4().hex
            output_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
            result = _query_bio_oracle(
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                },
                output_path=output_path,
            )
            dataframe = pd.read_csv(output_path, sep="\t")
            variable_name = dataset_variable_name(
                "bio_oracle",
                variable,
                scenario,
                depth_layer,
                latitude,
                longitude,
            )
            store_dataset(
                _store,
                thread_id,
                dataframe,
                variable_name=variable_name,
                meta={
                    "source": f"bio_oracle:{result['dataset_id']}",
                    "dataset_id": result["dataset_id"],
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                    "latitude": latitude,
                    "longitude": longitude,
                    "n_rows": len(dataframe),
                },
                latest_alias="bio_oracle",
            )
            return (
                f"Bio-ORACLE chargé — {result['row_count']} lignes.\n"
                f"Données disponibles dans `{variable_name}` et `df_bio_oracle`.\n"
                f"Appelle run_pandas directement pour analyser.\n"
                f"Télécharger : {result['download_url']}"
            )
        except Exception as exc:
            return f"Erreur lors de l'accès à Bio-ORACLE : {exc}"

    @tool
    def couple_zooplankton_bio_oracle(rows_json: str) -> str:
        """Enrichit chaque ligne d'observations zooplancton avec UNE valeur Bio-ORACLE
        propre à son point géographique (lat/lon).

        Utilise CE tool — et pas `query_bio_oracle_zones` — dès que l'utilisateur
        veut une valeur Bio-ORACLE **par station** d'un fichier zooplancton chargé
        (fichier avec `latitude` / `longitude` par ligne). Le tool fait UN appel
        Bio-ORACLE par ligne ; deux stations à des coordonnées différentes
        recevront donc deux valeurs différentes.

        `rows_json` : JSON array, une entrée par station, par exemple :
          [{"latitude": 71.24, "longitude": -157.17, "station": "1040",
            "variable": "temperature", "scenario": "baseline",
            "depth_layer": "surface"}, ...]
        """
        try:
            rows = json.loads(rows_json)
            if not isinstance(rows, list) or not rows:
                return "Aucune ligne à coupler."

            # Dédup : un appel ERDDAP par (lat, lon, variable, scenario, depth_layer).
            # Deux lignes au même point recevront la même valeur via lookup.
            cache: dict[tuple, dict] = {}
            for row in rows:
                key = (
                    row["latitude"], row["longitude"],
                    row["variable"], row["scenario"], row["depth_layer"],
                )
                if key not in cache:
                    preview = _preview_bio_oracle_point(
                        {
                            "latitude": row["latitude"],
                            "longitude": row["longitude"],
                            "variable": row["variable"],
                            "scenario": row["scenario"],
                            "depth_layer": row["depth_layer"],
                        }
                    )
                    val_key = preview.get("variable", "")
                    preview_rows = preview.get("rows") or []
                    raw_value = preview_rows[0].get(val_key) if preview_rows else None
                    try:
                        value = round(float(raw_value), 4) if raw_value is not None else None
                    except (TypeError, ValueError):
                        value = None
                    cache[key] = {"value": value, "dataset_id": preview.get("dataset_id")}

            coupled_rows = []
            for row in rows:
                key = (
                    row["latitude"], row["longitude"],
                    row["variable"], row["scenario"], row["depth_layer"],
                )
                cached = cache[key]
                scenario_clean = str(row["scenario"]).lower().replace(".", "_").replace("-", "_")
                value_col = f"{row['variable']}_{scenario_clean}"
                coupled_rows.append(
                    {
                        **row,
                        value_col: cached["value"],
                        "dataset_id": cached["dataset_id"],
                    }
                )

            output_path = _DOWNLOADS_DIR / f"{uuid.uuid4().hex}.tsv"
            dataframe = pd.DataFrame(coupled_rows)
            dataframe.to_csv(output_path, sep="\t", index=False)
            query_id = hashlib.sha256(rows_json.encode("utf-8")).hexdigest()[:12]
            variable_name = dataset_variable_name("bio_oracle_coupling", query_id)
            store_dataset(
                _store,
                thread_id,
                dataframe,
                variable_name=variable_name,
                meta={"source": "bio_oracle_coupling", "query_id": query_id, "n_rows": len(coupled_rows)},
            )
            preview_md = dataframe.head(20).to_markdown(index=False)
            return (
                f"Couplage Bio-ORACLE chargé — {len(coupled_rows)} lignes.\n"
                f"Données disponibles dans `{variable_name}`.\n"
                f"Télécharger : {download_url(output_path.name)}\n\n"
                f"Aperçu (20 premières lignes) :\n\n{preview_md}"
            )
        except Exception as exc:
            return f"Erreur lors du couplage Bio-ORACLE : {exc}"

    @tool
    def query_bio_oracle_zones(
        zones: list[str],
        variable: str,
        scenario: str,
        depth_layer: str = "surface",
    ) -> str:
        """Extract Bio-ORACLE projected values for one or more named geographic zones.

        Use this tool ONLY when the user asks for Bio-ORACLE data **aggregated
        by zone name** (e.g. "température Bio-ORACLE dans Hawke Channel et mer
        du Labrador", "compare les zones"). The tool returns ONE row per zone,
        sampled at the zone's geographic centre.

        DO NOT use this tool to enrich a loaded zooplankton / sampling file
        with per-station environmental values — even if all stations happen to
        fall in one zone. For that case, use `couple_zooplankton_bio_oracle`
        instead: it calls Bio-ORACLE once per row (lat/lon) so two stations at
        different coordinates receive different values.

        Parameters
        ----------
        zones : list of zone names — any name accepted by get_zone_filter:
            "Hawke Channel", "Mer du Labrador", "Baie d'Hudson",
            "Détroit d'Hudson", "Baie d'Ungava", "Baie de Baffin",
            "Mer de Beaufort", "Arctique", "Nunavik", "Baie de James"
        variable : one of: "temperature", "salinity", "oxygen",
                   "chlorophyll", "nitrate"  — do NOT use ERDDAP internal names
        scenario : "SSP5-8.5", "SSP1-2.6", "SSP2-4.5", or "baseline"
        depth_layer : "surface" (default), "mean", "max", or "min"
        """
        from tools.geo_tools import get_zone_filter

        # Garde-fou : si une session contient déjà un DataFrame multi-lignes
        # avec lat/lon, signaler que le couple_zooplankton_bio_oracle est plus
        # approprié pour un enrichissement par station.
        per_station_warning = ""
        try:
            session = _store.get(thread_id)
            df_session = session.get("df") if session else None
            if isinstance(df_session, pd.DataFrame) and len(df_session) > 1:
                cols_lower = {str(c).lower(): c for c in df_session.columns}
                has_lat = any(c in cols_lower for c in ("latitude", "lat"))
                has_lon = any(c in cols_lower for c in ("longitude", "lon"))
                if has_lat and has_lon:
                    per_station_warning = (
                        f"⚠ Une table de {len(df_session)} lignes avec latitude/longitude "
                        "est active en session. `query_bio_oracle_zones` renvoie UNE valeur "
                        "agrégée par zone — ne pas réutiliser cette valeur unique pour chaque "
                        "station. Pour des valeurs par station, appelle "
                        "`couple_zooplankton_bio_oracle` avec une entrée par ligne.\n\n"
                    )
        except Exception:
            pass

        rows_out = []
        errors = []
        for zone_name in zones:
            zf = get_zone_filter.invoke({"zone_name": zone_name})
            if "error" in zf:
                errors.append(f"{zone_name}: {zf['error']}")
                continue
            lat_c = (zf["lat_min"] + zf["lat_max"]) / 2
            lon_c = (zf["lon_min"] + zf["lon_max"]) / 2
            try:
                preview = _preview_bio_oracle_point({
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                    "latitude": lat_c,
                    "longitude": lon_c,
                })
                val_key = preview.get("variable", "")
                val = preview["rows"][0].get(val_key) if preview.get("rows") else None
                rows_out.append({
                    "zone": zf["zone"],
                    "lat_centre": round(lat_c, 2),
                    "lon_centre": round(lon_c, 2),
                    "variable": variable,
                    "scenario": scenario,
                    "depth_layer": depth_layer,
                    "dataset": preview["dataset_id"],
                    f"{variable}_projected": round(float(val), 4) if val is not None else None,
                })
            except Exception as exc:
                errors.append(f"{zone_name}: {exc}")

        if not rows_out:
            return "Aucune valeur extraite. Erreurs : " + "; ".join(errors)

        df_out = pd.DataFrame(rows_out)
        variable_name = dataset_variable_name(
            "bio_oracle_zones", variable, scenario, depth_layer
        )
        store_dataset(
            _store, thread_id, df_out,
            variable_name=variable_name,
            meta={"source": "bio_oracle_zones", "variable": variable,
                  "scenario": scenario, "depth_layer": depth_layer},
            latest_alias="bio_oracle",
        )
        out = df_out.to_markdown(index=False)
        if errors:
            out += "\n\nAvertissements : " + "; ".join(errors)
        return per_station_warning + out

    return [list_bio_oracle_datasets, preview_bio_oracle_point, query_bio_oracle,
            couple_zooplankton_bio_oracle, query_bio_oracle_zones]
