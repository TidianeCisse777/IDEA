"""tools/copepod_sources.py — LangChain tools pour accès EcoTaxa/EcoPart."""
from __future__ import annotations

import os
import re
import unicodedata
import uuid
from pathlib import Path

import requests
import pandas as pd
from langchain_core.tools import tool

from core.ecotaxa_browser.column_distribution import get_column_distribution
from core.ecotaxa_browser.compare_schemas import compare_project_schemas
from core.ecotaxa_browser.errors import EcoTaxaBrowserError
from core.ecotaxa_browser.observations import find_observations
from core.ecotaxa_browser.region import (
    group_project_samples_by_region,
    projects_in_region,
    rank_samples_by_region,
    resolve_sample_projects,
    samples_by_year,
    samples_in_region,
)
from core.ecotaxa_browser.project_summary import summarize_projects
from core.ecotaxa_browser.sample_summary import summarize_samples
from core.ecotaxa_browser.deployment_summary import summarize_sample_deployment
from core.ecotaxa_browser.samples import get_sample as core_get_sample
from core.ecotaxa_browser.objects import (
    list_sample_objects as core_list_sample_objects,
    get_object as core_get_object,
)
from core.ecotaxa_browser.schema import get_project_schema
from core.ecotaxa_browser.search import search_projects
from core.ecotaxa_browser.taxa_stats import taxa_stats
from core.ecotaxa_browser.taxonomy import search_taxa
from core.ecotaxa_browser.cache.repo import (
    init_schema,
    open_connection,
    project_cache_coverage,
    query_samples_filtered,
    resolve_samples,
)
from core.ecotaxa_browser.cache import sql_explorer as _sql_explorer
from core.geo import audit_zone_coverage, load_registry

_ZONES_REGISTRY_PATH = (
    Path(__file__).parent.parent / "data" / "geo" / "zones_registry.geojson"
)
from tools.ecotaxa_client import EcotaxaClient, EcotaxaExportError
from tools.dataset_registry import (
    ECOTAXA,
    dataset_variable_name,
    loaded_file_dataset,
    store_dataset,
)
from tools.public_url import download_url
from tools.session_store import default_store as _store
from tools.data_tools import _uvp_skill_hint
from tools.tool_result import blocked, empty, error, success, validate_tool_artifact

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)

_ECOTAXA_UI_BASE = "https://ecotaxa.obs-vlfr.fr"


def _ecotaxa_output(factory, summary: str, **fields):
    provenance = {"source": "ecotaxa", **dict(fields.pop("provenance", {}))}
    return factory(summary, provenance=provenance, **fields)


def _eco_success(summary: str, **fields):
    return _ecotaxa_output(success, summary, **fields)


def _eco_empty(summary: str, **fields):
    return _ecotaxa_output(empty, summary, **fields)


def _eco_blocked(summary: str, **fields):
    return _ecotaxa_output(blocked, summary, **fields)


def _eco_error(summary: str, **fields):
    return _ecotaxa_output(error, summary, **fields)


def _fmt_coord(value) -> str:
    """Format a latitude/longitude, tolerating NULL (coordinate-less samples)."""
    return f"{value:.3f}" if isinstance(value, (int, float)) else "—"


def _ecotaxa_project_url(project_id) -> str:
    """Return the canonical EcoTaxa project page URL, or empty if id missing."""
    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        return ""
    return f"{_ECOTAXA_UI_BASE}/prj/{pid}"


def _ecotaxa_sample_url(project_id, sample_id) -> str:
    """Return the EcoTaxa project page URL filtered on one sample."""
    try:
        pid = int(project_id)
        sid = int(sample_id)
    except (TypeError, ValueError):
        return ""
    return f"{_ECOTAXA_UI_BASE}/prj/{pid}?samples={sid}"


_YEAR_DATE_COLUMNS = (
    "object_date", "sample_date", "acq_date", "sample_sampledatetime",
    "object_annotation_date",
)


def _add_year_column(df):
    """Ajoute une colonne `year` à un export EcoTaxa, dérivée de la date.

    Cherche une colonne de date connue (``object_date`` = ``YYYYMMDD`` en
    priorité), en déduit l'année et l'expose comme colonne entière nullable
    ``year`` en tête de DataFrame. Permet un ``groupby("year")`` direct pour
    les analyses/​graphes interannuels sur un export consolidé multi-années.
    Si aucune colonne de date exploitable n'est trouvée, renvoie le DataFrame
    inchangé (l'année reste dérivable manuellement).
    """
    import pandas as pd

    if df is None or getattr(df, "empty", True):
        return df
    lower = {str(c).lower(): c for c in df.columns}
    date_col = next((lower[name] for name in _YEAR_DATE_COLUMNS if name in lower), None)
    if date_col is None:
        date_col = next((orig for low, orig in lower.items() if "date" in low), None)
    if date_col is None:
        return df

    raw = df[date_col].astype("string").str.strip()
    # object_date EcoTaxa = YYYYMMDD (8 chiffres) ; sinon parse générique.
    year = raw.str.extract(r"^(\d{4})", expand=False)
    parsed = pd.to_numeric(year, errors="coerce")
    if parsed.isna().all():
        parsed = pd.to_datetime(raw, errors="coerce").dt.year
    df = df.copy()
    df.insert(0, "year", parsed.astype("Int64"))
    return df


def _resolve_taxo_filter(taxon: str | int) -> dict:
    """Turn a taxon name or id into the EcoTaxa `taxo` filter fragment.

    Returns a dict ready to merge into `filters` for `start_export`:
      - `taxo` : stringified taxon id (single canonical taxon)
      - `taxochild` : `"Y"` when the input was a **name** — EcoTaxa then
        expands descendants server-side (e.g. Copepoda → includes Calanus,
        Paraeuchaeta, Calanoida). Without this flag, an export filtered by
        `taxo=25828` only returns objects directly classified as
        `Copepoda<Multicrustacea` (8 rows in a sample vs 77 with descent).

    Integer / int-like input is treated as an explicit id: no lookup, no
    descendant expansion — the caller stated exactly what they want.

    Name resolution prefers, in order:
      1. Exact case-insensitive match on display_name (e.g. `Copepoda<Multicrustacea`)
      2. Exact match on `name`
      3. Any hit with `aphia_id` set (WoRMS-mapped canonical taxon)
      4. Top autocomplete hit

    Preference (1)-(3) avoids landing on EcoTaxa's compound morphology-mix
    taxa like `copepoda + actinopterygii` (id 94987, aphia_id=None) that
    look like the query but include unrelated groups.
    """
    if isinstance(taxon, int):
        return {"taxo": str(taxon)}
    text = str(taxon).strip()
    if not text:
        raise ValueError("taxon is empty")
    if text.lstrip("-").isdigit():
        return {"taxo": text}
    hits = search_taxa(text)
    if not hits:
        raise ValueError(f"Taxon `{text}` introuvable dans EcoTaxa.")

    text_lc = text.lower()

    def _score(hit: dict) -> tuple:
        # Higher is better.
        name_lc = str(hit.get("name", "")).strip().lower()
        has_aphia = 1 if hit.get("aphia_id") else 0
        is_approved = 1 if hit.get("status") == "A" else 0
        # Exact case-insensitive match on `name` (bare canonical taxon).
        name_exact = 1 if name_lc == text_lc else 0
        # `name` starts with "text<" — EcoTaxa's compound canonical form
        # (e.g. `Copepoda<Multicrustacea`).
        display_exact = 1 if name_lc.startswith(text_lc + "<") else 0
        # Prefer approved WoRMS-mapped canonical taxa first, then exact name
        # matches, then compound canonical, then anything else.
        return (has_aphia, is_approved, name_exact, display_exact)

    chosen = max(hits, key=_score)
    return {"taxo": str(chosen["taxon_id"]), "taxochild": "Y"}


def make_source_tools(thread_id: str) -> list:
    def _format_number(value) -> str:
        if value is None:
            return "—"
        if isinstance(value, float) and not value.is_integer():
            return f"{value:.2f}".rstrip("0").rstrip(".")
        return f"{int(value):,}".replace(",", " ")

    def _format_export_failure(
        project_id: int | None,
        exc: Exception,
        *,
        sample_id: int | None = None,
    ) -> tuple[str, str, int]:
        """Message d'échec d'export EcoTaxa explicite — destiné au LLM ET à l'utilisateur.

        Le marqueur ``EXPORT_FAILED`` est consommé par le system prompt qui
        interdit à l'agent de retomber silencieusement sur une recherche
        (cf. règle « après EXPORT_FAILED, ne pas re-lister »).
        """
        status_code: int | None = None
        server = ""
        if isinstance(exc, EcotaxaExportError):
            target = f"projet {exc.project_id}"
            status_code = int(exc.status_code)
            status = f"HTTP {status_code}"
            server = exc.server_message
        elif isinstance(exc, requests.HTTPError) and exc.response is not None:
            target = f"projet {project_id}" if project_id is not None else "EcoTaxa"
            status_code = int(exc.response.status_code)
            status = f"HTTP {status_code}"
            server = str(exc) or "(pas de message serveur)"
        else:
            target = f"projet {project_id}" if project_id is not None else "EcoTaxa"
            status = type(exc).__name__
            server = str(exc) or "(pas de message serveur)"
        if sample_id is not None:
            target += f", sample {sample_id}"

        if status_code is not None and 500 <= status_code < 600:
            cause = (
                "Cause : serveur EcoTaxa temporairement indisponible "
                f"(HTTP {status_code}). Retenter dans quelques minutes — "
                "ce n'est pas un problème de droits ni de paramètres."
            )
            suggestion = "Diagnostic : aucun, attendre que le serveur EcoTaxa revienne."
        elif status_code in (401, 403):
            cause = (
                f"Cause : EcoTaxa a refusé l'accès (HTTP {status_code}) — "
                "droits Export manquants pour le compte configuré, projet "
                "privé, ou identifiants invalides."
            )
            diag = (
                f"preview_ecotaxa_project({project_id})"
                if project_id is not None
                else "list_ecotaxa_projects()"
            )
            suggestion = (
                f"Diagnostic suggéré : {diag} pour vérifier l'accès, puis "
                "proposer un projet alternatif si l'accès reste refusé."
            )
        elif status_code == 404:
            cause = (
                f"Cause : projet introuvable côté EcoTaxa (HTTP 404). "
                "Soit l'identifiant n'existe pas, soit il n'est plus exposé."
            )
            suggestion = (
                "Diagnostic suggéré : list_ecotaxa_projects() ou "
                "find_ecotaxa_projects(title=...) pour trouver un projet valide."
            )
        else:
            cause = (
                "Cause : erreur EcoTaxa inattendue — droits manquants, "
                "projet privé, identifiants invalides, ou paramètres refusés."
            )
            diag = (
                f"preview_ecotaxa_project({project_id})"
                if project_id is not None
                else "list_ecotaxa_projects()"
            )
            suggestion = f"Diagnostic suggéré : {diag} pour vérifier l'accès."

        return (
            f"EXPORT_FAILED — {target} ({status})\n"
            f"Message serveur : {server}\n"
            f"{cause}\n"
            f"{suggestion} "
            "NE PAS contourner avec find_ecotaxa_samples_in_region — ce serait "
            "une recherche, pas un export."
        )

    @tool(response_format="content_and_artifact")
    def compare_file_with_ecotaxa_cache() -> str:
        """Compare le fichier chargé aux vraies clés du cache EcoTaxa.

        Utiliser cet outil lorsqu'un fichier utilisateur doit être confronté à
        EcoTaxa, y compris après une requête `query_ecotaxa_cache`. Le fichier
        chargé est toujours la table de référence : l'outil le relit depuis son
        ancre de session stable et ne dépend jamais du DataFrame actif.

        L'outil inspecte les colonnes présentes, teste les correspondances
        réellement disponibles (`sample_id`, `original_id`, `object_id`,
        `profile_id`, `station_id`) et renvoie les lignes du fichier qui ont
        ou n'ont pas de correspondance. Il ne fabrique pas de jointure cache↔cache.
        """
        loaded = loaded_file_dataset(_store, thread_id)
        if not loaded or loaded.get("df") is None:
            return _eco_blocked(
                "Aucun fichier chargé dans cette conversation. Charge d'abord le fichier à comparer.",
                retryable=False,
            )

        file_df = loaded["df"].copy()
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        conn = None
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            cache_columns: dict[str, set[str]] = {}
            for table in ("samples_cache", "objects_cache"):
                if table in tables:
                    cache_columns[table] = {
                        str(row[1])
                        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                    }

            candidates = (
                ("sample_id", "samples_cache", "sample_id"),
                ("sample_id", "samples_cache", "original_id"),
                ("sample_id_internal", "samples_cache", "sample_id"),
                ("sample_id_internal", "samples_cache", "original_id"),
                ("object_id", "objects_cache", "object_id"),
                ("object_id", "objects_cache", "original_id"),
                ("sample_profileid", "samples_cache", "profile_id"),
                ("sample_stationid", "samples_cache", "station_id"),
            )
            comparison_rows: list[dict[str, object]] = []
            unmatched_examples: list[dict[str, object]] = []
            matched_examples: list[dict[str, object]] = []

            def _values(series: pd.Series) -> pd.Series:
                values = series.dropna().astype(str).str.strip()
                return values[values != ""]

            for file_column, table, cache_column in candidates:
                if file_column not in file_df.columns:
                    continue
                if cache_column not in cache_columns.get(table, set()):
                    continue
                cache_df = pd.read_sql_query(
                    f"SELECT CAST({cache_column} AS TEXT) AS key_value "
                    f"FROM {table} WHERE {cache_column} IS NOT NULL",
                    conn,
                )
                file_values = _values(file_df[file_column])
                cache_values = set(_values(cache_df["key_value"]))
                matched_mask = file_df[file_column].astype("string").str.strip().isin(cache_values)
                matched_rows = file_df.loc[matched_mask].copy()
                unmatched_rows = file_df.loc[~matched_mask & file_df[file_column].notna()].copy()
                comparison_rows.append(
                    {
                        "file_column": file_column,
                        "cache_table": table,
                        "cache_column": cache_column,
                        "file_values_tested": int(file_values.nunique()),
                        "cache_values_available": int(len(cache_values)),
                        "matched_file_rows": int(len(matched_rows)),
                        "unmatched_file_rows": int(len(unmatched_rows)),
                    }
                )
                for _, row in matched_rows.head(3).iterrows():
                    matched_examples.append(
                        {
                            "file_column": file_column,
                            "cache_table": table,
                            "cache_column": cache_column,
                            "value": str(row[file_column]),
                        }
                    )
                for _, row in unmatched_rows.head(3).iterrows():
                    unmatched_examples.append(
                        {
                            "file_column": file_column,
                            "cache_table": table,
                            "cache_column": cache_column,
                            "value": str(row[file_column]),
                        }
                    )
        except Exception as exc:
            return _eco_error(
                f"Impossible de comparer le fichier au cache EcoTaxa : {exc}",
                retryable=False,
            )
        finally:
            if conn is not None:
                conn.close()

        if not comparison_rows:
            return _eco_empty(
                "Aucune colonne de clé compatible trouvée entre le fichier et le schéma du cache EcoTaxa. "
                f"Colonnes du fichier : {', '.join(map(str, file_df.columns))}"
            )

        comparison = pd.DataFrame(comparison_rows)
        variable_name = "df_file_ecotaxa_comparison"
        store_dataset(
            _store,
            thread_id,
            comparison,
            variable_name=variable_name,
            meta={
                "source": "file_ecotaxa_comparison",
                "file_variable": (loaded.get("meta") or {}).get("variable_name"),
                "n_rows": len(comparison),
                "n_cols": len(comparison.columns),
            },
            set_active=False,
        )
        best_row = comparison.sort_values(
            ["matched_file_rows", "file_values_tested"],
            ascending=[False, False],
        ).iloc[0]
        total_matches = int(best_row["matched_file_rows"])
        total_unmatched = int(best_row["unmatched_file_rows"])
        lines = [
            "## Comparaison fichier → cache EcoTaxa",
            f"Fichier de référence : `{(loaded.get('meta') or {}).get('variable_name', 'loaded_file')}`",
            f"Lignes du fichier : {len(file_df)} ; colonnes inspectées : {len(file_df.columns)}",
            f"Meilleure correspondance réelle : {total_matches} ligne(s) ; lignes sans correspondance sur cette clé : {total_unmatched}",
            "",
            comparison.to_markdown(index=False),
        ]
        if matched_examples:
            lines += ["", "### Exemples correspondants", "", pd.DataFrame(matched_examples).to_markdown(index=False)]
        if unmatched_examples:
            lines += ["", "### Exemples sans correspondance", "", pd.DataFrame(unmatched_examples).to_markdown(index=False)]
        return _eco_success(
            "\n".join(lines),
            data_ref=variable_name,
            persisted=True,
            metrics={
                "file_rows": len(file_df),
                "candidate_keys": len(comparison_rows),
                "best_match_rows": total_matches,
            },
        )

    def _normalize_sample_ids(sample_ids) -> list[int]:
        if sample_ids is None:
            return []
        if isinstance(sample_ids, (int, str)):
            sample_ids = [sample_ids]
        normalized = []
        for sample_id in sample_ids:
            text = str(sample_id).strip()
            if text:
                normalized.append(int(text))
        return normalized

    def _slug_part(value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value).strip().lower())
        text = text.encode("ascii", "ignore").decode("ascii")
        text = re.sub(r"[^a-z0-9]+", "_", text)
        return text.strip("_")

    def _selection_name(
        *,
        zone_name: str | None = None,
        instrument: str | None = None,
        date_range: dict | None = None,
        month: int | None = None,
        project_ids: list[int] | None = None,
    ) -> str:
        parts = ["selection"]
        if zone_name:
            parts.append(_slug_part(zone_name))
        else:
            parts.extend(["ecotaxa", "samples"])
        if instrument:
            parts.append(_slug_part(instrument))
        if date_range:
            start = date_range.get("from")
            end = date_range.get("to")
            if start and end:
                parts.append(_slug_part(f"{start}_{end}"))
            elif start:
                parts.append(_slug_part(f"from_{start}"))
            elif end:
                parts.append(_slug_part(f"to_{end}"))
        if month is not None:
            parts.append(f"m{int(month):02d}")
        if project_ids:
            parts.append("projects_" + "_".join(str(int(pid)) for pid in project_ids[:4]))
        return "_".join(part for part in parts if part)

    def _store_sample_selection(
        *,
        name: str,
        samples: list[dict],
        filters: dict,
    ) -> None:
        import pandas as pd

        sample_ids = [int(sample["sample_id"]) for sample in samples]
        project_ids = sorted({int(sample["project_id"]) for sample in samples})
        meta = {
            "selection_name": name,
            "sample_ids": sample_ids,
            "project_ids": project_ids,
            "n_samples": len(sample_ids),
            "filters": filters,
            "source": "ecotaxa_selection",
        }
        _store.set(f"{thread_id}:selection:{name}", None, meta)
        _store.set(f"{thread_id}:ecotaxa_selection_latest", None, meta)

        # Keep the exploration result usable by run_pandas/run_graph without
        # starting an EcoTaxa export. Region searches already contain most
        # fields; annual groupings only carry IDs, so complete them from cache.
        cache_rows: dict[int, dict] = {}
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            cache_rows = {
                int(row["sample_id"]): dict(row)
                for row in query_samples_filtered(conn)
            }
            conn.close()
        except Exception:
            cache_rows = {}

        table_rows = []
        for sample in samples:
            cached = cache_rows.get(int(sample["sample_id"]), {})
            row = {**cached, **sample}
            table_rows.append({
                "sample_id": int(row["sample_id"]),
                "project_id": int(row["project_id"]),
                "latitude": row.get("latitude", row.get("lat", row.get("lat_avg"))),
                "longitude": row.get("longitude", row.get("lon", row.get("lon_avg"))),
                "station_id": row.get("station_id"),
                "original_id": row.get("original_id"),
                "profile_id": row.get("profile_id"),
                "date_min": row.get("date_min"),
                "date_max": row.get("date_max"),
                "depth_min": row.get("depth_min"),
                "depth_max": row.get("depth_max"),
                "instrument": row.get("instrument"),
                "object_count": row.get("object_count"),
            })

        if table_rows:
            variable_name = dataset_variable_name("ecotaxa", "selection", name)
            store_dataset(
                _store,
                thread_id,
                pd.DataFrame(table_rows),
                variable_name=variable_name,
                latest_alias=ECOTAXA,
                meta={**meta, "n_rows": len(table_rows), "source_scope": "local_cache"},
            )

    def _load_sample_selection(selection_name: str | None) -> tuple[str | None, list[int]]:
        if not selection_name:
            return None, []
        key = str(selection_name).strip()
        if key.lower() in {
            "latest", "last", "current", "cette sélection", "cette selection",
            "dernière sélection", "derniere selection",
        }:
            session = _store.get(f"{thread_id}:ecotaxa_selection_latest")
        else:
            session = _store.get(f"{thread_id}:selection:{key}")
        if not session:
            return key, []
        meta = session.get("meta") or {}
        resolved_name = str(meta.get("selection_name") or key)
        return resolved_name, _normalize_sample_ids(meta.get("sample_ids"))

    @tool(response_format="content_and_artifact")
    def combine_ecotaxa_selections(
        selection_names: list[str],
        zone_names: list[str] | None = None,
    ) -> str:
        """Combine plusieurs sélections EcoTaxa mémorisées en un DataFrame zoné.

        À utiliser avant une carte ou un tableau multi-zones lorsque plusieurs
        appels à `find_ecotaxa_samples_in_region` ont créé des sélections.
        Chaque ligne conserve son sample_id et reçoit une colonne `zone`; les
        doublons de sample_id sont supprimés. Le résultat complet est persisté
        sous `df_ecotaxa_zoned`, directement utilisable par `run_pandas` et
        `run_graph`. Les noms doivent être les noms exacts retournés par les
        recherches (par exemple `selection_baie_de_baffin`).
        """
        names = [str(name).strip() for name in (selection_names or []) if str(name).strip()]
        if not names:
            return _eco_blocked("Indique au moins deux sélections EcoTaxa à combiner.")
        frames: list[pd.DataFrame] = []
        labels = zone_names or []
        missing: list[str] = []
        for index, name in enumerate(names):
            selection = _store.get(f"{thread_id}:selection:{name}")
            if not selection:
                missing.append(name)
                continue
            meta = selection.get("meta") or {}
            variable_name = dataset_variable_name("ecotaxa", "selection", name)
            dataset = _store.get(f"{thread_id}:dataset:{variable_name}")
            frame = (dataset or {}).get("df") if dataset else None
            if not isinstance(frame, pd.DataFrame):
                missing.append(name)
                continue
            zone = labels[index] if index < len(labels) else (meta.get("filters") or {}).get("zone_name")
            if not zone:
                zone = name.removeprefix("selection_").replace("_", " ")
            copy = frame.copy()
            copy["zone"] = str(zone)
            frames.append(copy)
        if missing:
            return _eco_blocked(
                "Sélections introuvables ou non persistées : " + ", ".join(missing)
            )
        combined = pd.concat(frames, ignore_index=True)
        if "sample_id" in combined.columns:
            combined = combined.drop_duplicates(subset=["sample_id"], keep="first")
        store_dataset(
            _store,
            thread_id,
            combined,
            variable_name=dataset_variable_name("ecotaxa", "zoned"),
            latest_alias=ECOTAXA,
            meta={
                "source": "ecotaxa_combined_selections",
                "zone_column": "zone",
                "selection_names": names,
                "n_rows": int(len(combined)),
            },
        )
        counts = combined["zone"].value_counts().to_dict()
        lines = [
            "# EcoTaxa — sélections combinées par zone",
            f"DataFrame persistant : `df_ecotaxa_zoned` ({len(combined)} samples uniques)",
            "",
            "| Zone | Samples |",
            "|---|---:|",
        ]
        lines.extend(f"| {zone} | {count} |" for zone, count in counts.items())
        return _eco_success(
            "\n".join(lines),
            data_ref="df_ecotaxa_zoned",
            persisted=True,
            metrics={"rows": int(len(combined)), "zones": len(counts)},
        )

    def _selection_actions(name: str, sample_count: int, project_count: int) -> list[str]:
        return [
            f"résume cette sélection : `summarize_ecotaxa_samples(selection_name=\"{name}\")`",
            f"exporte cette sélection : d'abord `export_ecotaxa_samples(selection_name=\"{name}\", confirmed=false)`",
            "export représentatif : demander `exporte 1 sample par projet`",
            "filtrer davantage : ajouter une profondeur, une période, un instrument ou des projets",
            f"contexte : {sample_count} samples sur {project_count} projets",
        ]

    def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
        try:
            return max(minimum, int(os.getenv(name, str(default))))
        except (TypeError, ValueError):
            return default

    def _compact_instruments(samples: list[dict]) -> str:
        instruments = sorted({
            str(sample.get("instrument"))
            for sample in samples
            if sample.get("instrument")
        })
        if not instruments:
            return "—"
        suffix = f", +{len(instruments) - 8}" if len(instruments) > 8 else ""
        return ", ".join(instruments[:8]) + suffix

    def _sample_project_counts(samples: list[dict]) -> str:
        counts: dict[int, int] = {}
        for sample in samples:
            pid = int(sample["project_id"])
            counts[pid] = counts.get(pid, 0) + 1
        parts = [
            f"{pid}: {count}"
            for pid, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )[:8]
        ]
        if len(counts) > 8:
            parts.append(f"+{len(counts) - 8} projets")
        return ", ".join(parts) if parts else "—"

    def _ecotaxa_partial_notice(result: dict) -> str:
        if not result.get("partial"):
            return ""
        return (
            "\n\nNote : sync EcoTaxa en cours, résultat partiel "
            "(`partial=True`). Relancer la même question après la fin du sync "
            "peut ajouter des samples/projets."
        )

    def _download_ecotaxa_export(
        *,
        project_id: int,
        filters: dict,
        variable_name: str,
        meta: dict,
        label: str,
    ) -> str:
        client = EcotaxaClient()
        client.login()
        job_id = client.start_export(project_id, filters)
        client.wait_for_job(job_id)
        df = client.download_tsv(job_id)
        df = _add_year_column(df)

        store_dataset(
            _store,
            thread_id,
            df,
            variable_name=variable_name,
            meta={**meta, "source": f"ecotaxa:{project_id}", "project_id": project_id, "n_rows": len(df)},
            latest_alias=ECOTAXA,
        )

        file_id = uuid.uuid4().hex
        tsv_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
        df.to_csv(tsv_path, sep="\t", index=False)

        hint = _uvp_skill_hint(list(df.columns))
        # Prefer a sample-scoped URL when the export targets one sample.
        sample_id_from_meta = (meta or {}).get("sample_id")
        source_url = (
            _ecotaxa_sample_url(project_id, sample_id_from_meta)
            if sample_id_from_meta is not None
            else _ecotaxa_project_url(project_id)
        )
        year_note = (
            "Colonne `year` ajoutée (dérivée de la date) → `groupby(\"year\")` "
            "direct pour l'analyse/le graphe interannuel.\n"
            if "year" in df.columns else ""
        )
        artifact_url = download_url(f"{file_id}.tsv")
        summary = (
            f"{label} chargé — {len(df)} lignes, {len(df.columns)} colonnes.\n"
            f"Données disponibles dans `{variable_name}` et `df_ecotaxa`.\n"
            f"{year_note}"
            f"Appelle run_pandas directement pour analyser.\n"
            f"Télécharger : {artifact_url}\n"
            f"Source EcoTaxa : {source_url}"
        )
        if hint:
            summary += f"\n{hint}"
        return summary, artifact_url, len(df)

    @tool(response_format="content_and_artifact")
    def find_ecotaxa_projects(
        title: str | None = None,
        instrument: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> str:
        """Recherche des projets EcoTaxa par titre ou instrument avant un export.

        Utiliser cet outil pour découvrir un project_id pertinent. Il ne télécharge
        aucune donnée d'objet.
        """
        try:
            projects = search_projects(
                title=title,
                instrument=instrument,
                page=page,
                page_size=page_size,
            )
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la recherche EcoTaxa : {exc}", retryable=True
            )

        if not projects:
            return _eco_empty("Aucun projet EcoTaxa ne correspond aux critères.")

        lines = [
            "| project_id | name | instrument | status | objects | validated | url |",
            "|---:|---|---|---|---:|---:|---|",
        ]
        lines.extend(
            f"| {project['project_id']} | {project['name']} | "
            f"{project.get('instrument') or '—'} | {project.get('status') or '—'} | "
            f"{_format_number(project.get('object_count'))} | "
            f"{_format_number(project.get('percent_validated'))} % | "
            f"{_ecotaxa_project_url(project['project_id'])} |"
            for project in projects
        )
        return _eco_success("\n".join(lines), metrics={"projects": len(projects)})

    @tool(response_format="content_and_artifact")
    def list_ecotaxa_projects() -> str:
        """Liste les projets EcoTaxa accessibles au compte configuré."""
        try:
            client = EcotaxaClient()
            client.login()
            projects = sorted(client.list_projects(), key=lambda project: project["project_id"])
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de l'accès à EcoTaxa : {exc}", retryable=True
            )

        if not projects:
            return _eco_empty("Aucun projet EcoTaxa accessible.")

        lines = ["| project_id | name | url |", "|---:|---|---|"]
        lines.extend(
            f"| {project['project_id']} | {project['name']} | "
            f"{_ecotaxa_project_url(project['project_id'])} |"
            for project in projects
        )
        return _eco_success("\n".join(lines), metrics={"projects": len(projects)})

    @tool(response_format="content_and_artifact")
    def list_ecotaxa_campaigns(
        query: str | None = None,
        min_legs: int = 1,
        instrument: str | None = None,
    ) -> str:
        """Liste les campagnes EcoTaxa (regroupement de projets par titre-racine).

        Utiliser quand l'utilisateur pose une question sur les **campagnes**,
        **legs**, **missions**, ou **expéditions** — p.ex. « quelles campagnes
        sont dans EcoTaxa ? », « donne-moi les legs Amundsen 2024 »,
        « samples de la campagne ArcticNet 2015 », « combien de legs pour la
        mission GreenEdge ? ». Une campagne = ensemble de projets EcoTaxa
        partageant le même titre-racine (ex. `uvp6_sn000006hf_2024_am_leg5`,
        `uvp6_sn000006hf_2024_am_leg2` → racine `uvp6_sn000006hf_2024_am`,
        2 legs).

        Args:
            query: filtre par sous-chaîne insensible à la casse sur la racine
                ou un titre de projet (ex. "am 2024", "ArcticNet", "greenedge").
            min_legs: n'affiche que les campagnes avec au moins N legs (≥ 1).
            instrument: filtre par instrument (ex. "UVP6", "Loki", "UVP5SD").

        Renvoie un tableau par campagne avec : racine, nb de legs, instrument,
        project_ids (à passer ensuite à `find_ecotaxa_samples_in_region`
        pour drill dans les samples). Lecture du cache local — pas de download.
        """
        import json as _json
        import re as _re

        # Natural-name → in-title code aliases. Users type "Amundsen 2024" or
        # "GreenEdge" — titles carry the short codes ("am", "green_edge"…).
        _campaign_aliases: dict[str, list[str]] = {
            "amundsen": ["am"],
            "arcticnet": ["arctic_net", "arcticnet", "arctic"],
            "greenedge": ["green_edge", "green edge", "greenedge"],
            "green edge": ["green_edge", "greenedge"],
            "green_edge": ["greenedge"],
            "ge": ["green_edge", "greenedge"],
            "iaos": ["iaos"],
            "arctica": ["arctic"],
        }

        def _query_variants(raw: str) -> list[str]:
            base = (raw or "").strip().lower()
            variants = {base}
            for alias, syns in _campaign_aliases.items():
                if alias and alias in base:
                    for syn in syns:
                        variants.add(base.replace(alias, syn))
            return [v for v in variants if v]

        def _norm(text: str) -> str:
            return _re.sub(r"[\W_]+", "", (text or "").lower())

        def _matches_query(variants: list[str], *fields: str) -> bool:
            haystack_norm = " ".join(_norm(field) for field in fields if field)
            for variant in variants:
                tokens = _re.findall(r"\w+", variant.lower())
                if tokens and all(token in haystack_norm for token in tokens):
                    return True
            return False

        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            rows = conn.execute(
                "SELECT project_id, schema_json FROM project_schemas_cache"
            ).fetchall()
            sample_counts = {
                int(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT project_id, COUNT(*) FROM samples_cache GROUP BY project_id"
                ).fetchall()
            }
            conn.close()
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la lecture du cache EcoTaxa : {exc}", retryable=True
            )

        if not rows:
            return _eco_empty("Aucun projet EcoTaxa dans le cache local.")

        _leg_re = _re.compile(r"[_\-\s](leg|lg|l)\s*\d+\s*$", _re.IGNORECASE)

        campaigns: dict[str, dict] = {}
        query_variants = _query_variants(query) if query else []
        instrument_lc = (instrument or "").strip().lower()

        for pid, schema_json in rows:
            try:
                schema = _json.loads(schema_json)
            except Exception:
                continue
            title = str(schema.get("title") or "").strip()
            if not title:
                continue
            project_instrument = str(schema.get("instrument") or "").strip()
            if instrument_lc and project_instrument.lower() != instrument_lc:
                continue

            root = _leg_re.sub("", title).strip("_- ") or title
            root_key = root.lower()

            if query_variants and not _matches_query(query_variants, title, root):
                continue

            group = campaigns.setdefault(
                root_key,
                {
                    "root": root,
                    "example_title": title,
                    "project_ids": [],
                    "instruments": set(),
                    "n_samples": 0,
                },
            )
            group["project_ids"].append(int(pid))
            if project_instrument:
                group["instruments"].add(project_instrument)
            group["n_samples"] += int(sample_counts.get(int(pid), 0))

        campaigns = {
            key: value
            for key, value in campaigns.items()
            if len(value["project_ids"]) >= max(1, int(min_legs))
        }
        if not campaigns:
            return _eco_empty(
                "Aucune campagne EcoTaxa ne correspond aux critères "
                f"(query={query!r}, min_legs={min_legs}, instrument={instrument!r})."
            )

        # Sort: most legs first, then alphabetical root.
        ordered = sorted(
            campaigns.values(),
            key=lambda item: (-len(item["project_ids"]), item["root"].lower()),
        )

        lines = [
            f"# {len(ordered)} campagne(s) EcoTaxa",
            "",
            "| campagne (racine) | legs | instruments | samples | project_ids | exemple |",
            "|---|---:|---|---:|---|---|",
        ]
        for item in ordered:
            pids = sorted(item["project_ids"])
            pids_cell = (
                ", ".join(str(pid) for pid in pids[:8])
                + (f" +{len(pids) - 8}" if len(pids) > 8 else "")
            )
            lines.append(
                f"| `{item['root']}` | {len(pids)} | "
                f"{', '.join(sorted(item['instruments'])) or '—'} | "
                f"{item['n_samples']} | {pids_cell} | "
                f"{item['example_title']} |"
            )
        lines.extend([
            "",
            "Pour drill dans une campagne : "
            "`find_ecotaxa_samples_in_region(project_ids=[...], date_range=..., zone_name=...)` "
            "avec les project_ids de la ligne voulue.",
        ])
        return _eco_success("\n".join(lines), metrics={"campaigns": len(ordered)})

    @tool(response_format="content_and_artifact")
    def audit_ecotaxa_spatial_coverage() -> str:
        """Audit spatial de la couverture par zone nommée (lecture seule).

        À utiliser pour les questions d'audit spatial : « quelles zones sont
        couvertes / peu couvertes », « où sont les trous géographiques », « audit
        de couverture par zone ». Projette les samples indexés du cache sur les
        zones nommées (IHO / MEOW / composites NeoLab) et renvoie :
        - les zones couvertes, classées par nombre de samples ;
        - les lacunes : zones voisines des données mais sans aucun sample ;
        - les samples hors de toute zone connue.

        Ne lance aucun export. Les comptages viennent du cache local. Les zones
        composites (Arctique, Nunavik) chevauchent des zones plus fines, donc un
        sample peut compter dans plusieurs zones.
        """
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            rows = list(query_samples_filtered(conn))
            conn.close()
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la lecture du cache EcoTaxa : {exc}", retryable=True
            )

        points = [
            {"latitude": r["lat_avg"], "longitude": r["lon_avg"]}
            for r in rows
            if r["lat_avg"] is not None and r["lon_avg"] is not None
        ]
        if not points:
            return _eco_empty("Aucun sample géolocalisé dans le cache local.")

        import pandas as pd

        registry = load_registry(_ZONES_REGISTRY_PATH)
        audit = audit_zone_coverage(pd.DataFrame(points), registry)

        lines = [
            "# Audit spatial EcoTaxa par zone nommée (cache local)",
            "",
            f"{audit['n_points']} samples géolocalisés — "
            f"{len(audit['covered'])} zone(s) couverte(s), "
            f"{audit['n_unmatched']} sample(s) hors zone connue.",
            "",
            "## Zones couvertes (classées par nombre de samples)",
            "",
            "| zone | samples | source |",
            "|---|---:|---|",
        ]
        lines.extend(
            f"| {z['canonical']} | {z['n_samples']} | {z['source']} |"
            for z in audit["covered"]
        )
        lines += [
            "",
            "## Lacunes : zones voisines sans aucun sample",
            "",
        ]
        if audit["gaps"]:
            lines.append("| zone | source |")
            lines.append("|---|---|")
            lines.extend(
                f"| {z['canonical']} | {z['source']} |" for z in audit["gaps"]
            )
        else:
            lines.append("Aucune lacune pertinente : les zones voisines des "
                         "données sont toutes couvertes.")
        lines.append("")
        lines.append(
            "Note : zones composites (Arctique, Nunavik) incluses — un sample "
            "peut compter dans plusieurs zones."
        )
        return _eco_success(
            "\n".join(lines), metrics={"geolocated_samples": len(points)}
        )

    @tool(response_format="content_and_artifact")
    def resolve_ecotaxa_sample(
        reference: str,
        project_id: int | None = None,
    ) -> str:
        """Résout une référence de sample EcoTaxa dans tous les projets cachés.

        `reference` peut être un `sample_id` numérique, un label/original_id,
        une station, un profil ou une valeur de free field. La recherche est
        locale, insensible à la casse et aux espaces, et ne choisit jamais
        silencieusement un sample si plusieurs correspondances existent.
        Passe `project_id` uniquement pour lever une ambiguïté entre projets.
        Lecture seule ; ne synchronise pas EcoTaxa automatiquement.
        """
        if not str(reference or "").strip():
            return _eco_blocked("Erreur : reference est vide.")
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            rows = resolve_samples(conn, reference=reference, project_id=project_id)
            conn.close()
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la résolution du sample EcoTaxa : {exc}",
                retryable=True,
                provenance={"reference": str(reference), "project_id": project_id},
            )

        rows.sort(key=lambda row: (int(row["project_id"]), int(row["sample_id"])))
        if not rows:
            scope = f" dans le projet {project_id}" if project_id is not None else ""
            return _eco_empty(
                f"Aucun sample EcoTaxa correspondant à `{reference}`{scope} "
                "dans le cache local. Lancer `/admin/resync` si nécessaire.",
                provenance={"reference": str(reference), "project_id": project_id},
            )

        ambiguous = len(rows) > 1
        lines = [
            (
                f"# Correspondances EcoTaxa — `{reference}`\n\n"
                f"Plusieurs correspondances ({len(rows)}) : préciser `project_id`."
                if ambiguous
                else f"# Sample EcoTaxa résolu — `{reference}`"
            ),
            "",
            "| sample_id | project_id | label | station | profile | latitude | longitude | date_min | date_max | url |",
            "|---:|---:|---|---|---|---:|---:|---|---|---|",
        ]
        lines.extend(
            f"| {row['sample_id']} | {row['project_id']} | {row['original_id'] or '—'} | "
            f"{row['station_id'] or '—'} | {row['profile_id'] or '—'} | "
            f"{_format_number(row['lat_avg'])} | {_format_number(row['lon_avg'])} | "
            f"{row['date_min'] or '—'} | {row['date_max'] or '—'} | "
            f"{_ecotaxa_sample_url(row['project_id'], row['sample_id'])} |"
            for row in rows
        )
        return _eco_success(
            "\n".join(lines),
            provenance={
                "reference": str(reference),
                "project_id": project_id,
                "sample_ids": [int(row["sample_id"]) for row in rows],
            },
            metrics={"matches": len(rows), "ambiguous": ambiguous},
        )

    @tool(response_format="content_and_artifact")
    def preview_ecotaxa_project(project_id: int) -> str:
        """Aperçu LÉGER d'un projet EcoTaxa : metadata + 10 objets exemple.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Renvoie :
        - une fiche metadata (instrument, statut, droits du compte, objets,
          % validés / classifiés)
        - jusqu'à 10 objets exemple avec orig_id, date, profondeur, taxon

        À utiliser quand l'utilisateur veut **voir à quoi ressemble un projet**
        sans en demander les stats agrégées ni un export. Intents typiques :
        « présente-moi le projet X », « présente rapidement le projet X »,
        « à quoi ressemble le projet X », « montre-moi le projet X »,
        « aperçu du projet X », « preview », « combien d'objets + quelques
        exemples ».

        À NE PAS utiliser pour :
        - un résumé V/P/D/U / top taxa / bbox / envelope temporelle →
          `summarize_ecotaxa_project(s)`
        - la liste des colonnes / champs / free fields →
          `inspect_ecotaxa_project_schema`
        - la distribution d'une colonne → `inspect_ecotaxa_column`
        - un export → `query_ecotaxa` / `export_ecotaxa_samples`
        """
        try:
            client = EcotaxaClient()
            client.login()
            preview = client.preview_project(project_id, limit=10)
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de l'accès à EcoTaxa : {exc}",
                retryable=True,
                provenance={"project_id": int(project_id)},
            )

        metadata = preview["metadata"]
        summary = preview["summary"]
        lines = [
            f"# Projet EcoTaxa {metadata['project_id']} — {metadata['name']}",
            "",
            "| Champ | Valeur |",
            "|---|---|",
            f"| Instrument | {metadata.get('instrument') or '—'} |",
            f"| Statut | {metadata.get('status') or '—'} |",
            f"| Droit du compte | {metadata.get('access') or '—'} |",
            f"| Objets | {_format_number(summary.get('total_objects', metadata.get('object_count')))} |",
            f"| Classifiés | {_format_number(metadata.get('percent_classified'))} % |",
            f"| Validés | {_format_number(metadata.get('percent_validated'))} % |",
            f"| Objets validés | {_format_number(summary.get('validated_objects'))} |",
            f"| Objets douteux | {_format_number(summary.get('dubious_objects'))} |",
            f"| Objets prédits | {_format_number(summary.get('predicted_objects'))} |",
            "",
            "## Aperçu des objets",
        ]

        objects = preview["objects"]
        if not objects:
            lines.append("")
            lines.append("Aucun objet dans l'aperçu.")
            lines.append("")
            lines.append(f"Source EcoTaxa : {_ecotaxa_project_url(project_id)}")
            return _eco_success(
                "\n".join(lines),
                provenance={"project_id": int(project_id)},
                metrics={"objects_previewed": 0},
            )

        lines.extend([
            "",
            "| orig_id | date | profondeur min | taxon |",
            "|---|---|---:|---|",
        ])
        lines.extend(
            f"| {obj.get('orig_id') or '—'} | {obj.get('date') or '—'} | "
            f"{_format_number(obj.get('depth_min'))} | {obj.get('taxon') or '—'} |"
            for obj in objects
        )
        lines.append("")
        lines.append(f"Source EcoTaxa : {_ecotaxa_project_url(project_id)}")
        return _eco_success(
            "\n".join(lines),
            provenance={"project_id": int(project_id)},
            metrics={"objects_previewed": len(objects)},
        )

    @tool(response_format="content_and_artifact")
    def query_ecotaxa(
        project_id: int,
        taxon: str | None = None,
        status: str = "V",
        sample_ids: list[int] | None = None,
        obj_depth_gte: float | None = None,
        obj_depth_lte: float | None = None,
    ) -> str:
        """Interroge EcoTaxa et charge les données dans la session courante.

        Args:
            project_id: ID du projet EcoTaxa (ex: 1165, 2331).
            taxon: Filtre taxonomique optionnel (ex: "Copepoda").
            status: Statut des annotations — "V" (validé), "P" (prédit), "" (tous).
            sample_ids: IDs de samples EcoTaxa à exporter dans ce projet.
            obj_depth_gte: profondeur **objet** minimale en mètres
                (inclusif). Filtre côté serveur EcoTaxa
                (`ProjectFilter.depthmin`). Pour « objets à au moins 50 m »,
                `obj_depth_gte=50`.
            obj_depth_lte: profondeur **objet** maximale en mètres
                (inclusif). Filtre côté serveur EcoTaxa
                (`ProjectFilter.depthmax`). Combiner avec `obj_depth_gte`
                pour une bande, p.ex. « objets autour de 100 m »
                → `obj_depth_gte=95, obj_depth_lte=105`. Granularité
                **objet** (PAS sample) : utile quand on veut les objets
                à une profondeur précise, pas tout le sample.
        """
        try:
            filters = {"statusfilter": status}
            if taxon:
                filters.update(_resolve_taxo_filter(taxon))
            normalized_sample_ids = _normalize_sample_ids(sample_ids)
            if normalized_sample_ids:
                filters["samples"] = ",".join(str(sample_id) for sample_id in normalized_sample_ids)
            if obj_depth_gte is not None:
                filters["depthmin"] = float(obj_depth_gte)
            if obj_depth_lte is not None:
                filters["depthmax"] = float(obj_depth_lte)
        except Exception as exc:
            return _eco_blocked(
                f"Erreur dans les paramètres EcoTaxa : {exc}",
                provenance={"project_id": int(project_id)},
            )

        sample_suffix = f"_samples_{'_'.join(str(sample_id) for sample_id in normalized_sample_ids)}" if normalized_sample_ids else ""
        variable_name = dataset_variable_name("ecotaxa", f"{project_id}{sample_suffix}")
        label = f"Projet {project_id}"
        if normalized_sample_ids:
            label += f" — samples {','.join(str(sample_id) for sample_id in normalized_sample_ids)}"

        try:
            summary, artifact_url, row_count = _download_ecotaxa_export(
                project_id=project_id,
                filters=filters,
                variable_name=variable_name,
                meta={"sample_ids": normalized_sample_ids},
                label=label,
            )
            return _eco_success(
                summary,
                data_ref=variable_name,
                artifact_refs=(artifact_url,),
                provenance={"project_id": int(project_id)},
                persisted=True,
                method="EcoTaxa export",
                metrics={"rows": row_count},
            )
        except Exception as exc:
            return _eco_error(
                _format_export_failure(project_id, exc),
                retryable=True,
                provenance={"project_id": int(project_id)},
                method="EcoTaxa export",
            )

    @tool(response_format="content_and_artifact")
    def query_ecotaxa_sample(sample_id: int, taxon: str | None = None, status: str = "V") -> str:
        """Exporte les objets d'un sample EcoTaxa et charge le résultat en session.

        Utiliser quand l'utilisateur donne un `sample_id` ou veut télécharger /
        analyser un sample précis sans connaître son `project_id`.

        Args:
            sample_id: ID du sample EcoTaxa (ex: 42000002).
            taxon: Filtre taxonomique optionnel (ex: "Copepoda").
            status: Statut des annotations — "V" (validé), "P" (prédit), "" (tous).
        """
        try:
            sample = core_get_sample(sample_id)
            project_id = int(sample["project_id"])
            filters = {"statusfilter": status, "samples": str(sample_id)}
            if taxon:
                filters.update(_resolve_taxo_filter(taxon))
        except EcoTaxaBrowserError as exc:
            return _eco_error(
                f"Erreur EcoTaxa ({exc.code}) : {exc}",
                provenance={"sample_id": int(sample_id)},
            )
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de l'accès au sample {sample_id} : {exc}",
                retryable=True,
                provenance={"sample_id": int(sample_id)},
            )

        try:
            variable_name = dataset_variable_name("ecotaxa", "sample", str(sample_id))
            summary, artifact_url, row_count = _download_ecotaxa_export(
                project_id=project_id,
                filters=filters,
                variable_name=variable_name,
                meta={"sample_id": sample_id, "original_id": sample.get("original_id")},
                label=f"Sample {sample_id} (projet {project_id})",
            )
            return _eco_success(
                summary,
                data_ref=variable_name,
                artifact_refs=(artifact_url,),
                provenance={"project_id": project_id, "sample_id": int(sample_id)},
                persisted=True,
                method="EcoTaxa export",
                metrics={"rows": row_count},
            )
        except Exception as exc:
            return _eco_error(
                _format_export_failure(project_id, exc, sample_id=sample_id),
                retryable=True,
                provenance={"project_id": project_id, "sample_id": int(sample_id)},
                method="EcoTaxa export",
            )

    @tool(response_format="content_and_artifact")
    def inspect_ecotaxa_project_schema(
        project_id: int,
        verbose: bool = False,
        include_process: bool = False,
    ) -> str:
        """Liste les colonnes typées d'un projet EcoTaxa avant un export.

        Utiliser cet outil pour vérifier si un projet a les colonnes nécessaires
        (profondeur, station, taxon, mesures morphologiques…) sans rien
        télécharger. Renvoie 3 niveaux par défaut : sample, acquisition, object.
        """
        try:
            schema = get_project_schema(
                project_id,
                verbose=verbose,
                include_process=include_process,
            )
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de l'accès au schéma EcoTaxa : {exc}",
                retryable=True,
                provenance={"project_id": int(project_id)},
            )

        lines = [
            f"# Projet {schema['project_id']} — {schema['title']}",
            f"Instrument : {schema.get('instrument') or '—'}",
            "",
        ]
        for level_name, content in schema["levels"].items():
            max_columns = _env_int("ECOTAXA_SCHEMA_COLUMNS_PER_LEVEL", 12)
            fixed_columns = content["fixed"]
            free_columns = content["free"]
            lines.append(f"## {level_name}")
            lines.append(
                f"{len(fixed_columns)} colonnes fixes, "
                f"{len(free_columns)} colonnes libres."
            )
            lines.append("")
            lines.append("| colonne | type | catégorie |")
            lines.append("|---|---|---|")
            shown = 0
            for fixed in fixed_columns[:max_columns]:
                lines.append(f"| {fixed['name']} | {fixed['type']} | fixe |")
                shown += 1
            remaining_slots = max(0, max_columns - shown)
            for free in free_columns[:remaining_slots]:
                tag = f" `{free['code']}`" if verbose and "code" in free else ""
                lines.append(f"| {free['label']}{tag} | {free['type']} | libre |")
                shown += 1
            hidden = len(fixed_columns) + len(free_columns) - shown
            if hidden > 0:
                lines.append(
                    f"| ... | ... | {hidden} colonnes masquées ; utiliser "
                    "`inspect_ecotaxa_column` pour une colonne précise |"
                )
            lines.append("")
        return _eco_success(
            "\n".join(lines), provenance={"project_id": int(project_id)}
        )

    @tool(response_format="content_and_artifact")
    def count_ecotaxa_taxa(
        project_ids: list[int],
        taxa: list[int | str],
    ) -> str:
        """Compte les objets validés / prédits / douteux par projet et par taxon.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        `taxa` accepte des IDs entiers ou des noms scientifiques. Utile pour
        évaluer la confiance des annotations avant d'exporter. Les noms sont
        d'abord résolus en `taxon_id` EcoTaxa, puis les counts viennent de
        `/project_set/taxo_stats` avec `taxa_ids=<taxon_id>`.
        """
        try:
            result = taxa_stats(project_ids=project_ids, taxa=taxa)
        except EcoTaxaBrowserError as exc:
            return _eco_error(f"Erreur EcoTaxa ({exc.code}) : {exc}")
        except Exception as exc:
            return _eco_error(
                f"Erreur lors du comptage EcoTaxa : {exc}", retryable=True
            )

        if not result["rows"]:
            return _eco_empty(
                "Aucun comptage retourné — vérifie les IDs de projet et taxon."
            )

        lines = [
            "| project_id | taxon_id | taxon | validés | prédits | douteux | non classés | total |",
            "|---:|---:|---|---:|---:|---:|---:|---:|",
        ]
        lines.extend(
            f"| {row['project_id']} | {row['taxon_id']} | {row['taxon_name']} | "
            f"{row['count_V']} | {row['count_P']} | {row['count_D']} | "
            f"{row.get('count_U', 0)} | "
            f"{row['count_total']} |"
            for row in result["rows"]
        )
        if result["inaccessible_project_ids"]:
            lines.append("")
            lines.append(
                f"Projets non accessibles : {result['inaccessible_project_ids']}"
            )
        return _eco_success(
            "\n".join(lines),
            provenance={"project_ids": [int(pid) for pid in project_ids]},
            metrics={"rows": len(result["rows"])},
        )

    @tool(response_format="content_and_artifact")
    def search_ecotaxa_taxa(query: str) -> str:
        """Recherche par autocomplétion les taxons EcoTaxa qui matchent une chaîne.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Appeler ce tool AVANT `count_ecotaxa_taxa` ou
        `find_ecotaxa_observations` lorsque le nom de taxon est ambigu, mal
        orthographié, ou que l'agent retourne `AMBIGUOUS_TAXON`. Le résultat
        permet de désambiguïser en fournissant le `taxon_id` exact.

        Retourne un tableau markdown avec `taxon_id`, `nom`, statut EcoTaxa
        (`1` = validé, `0` = en attente), et indication si le taxon est utilisé
        dans au moins un projet (`in_project`). Inclut aussi l'`aphia_id`
        WoRMS quand disponible.
        """
        query = (query or "").strip()
        if not query:
            return _eco_blocked("Erreur : `query` ne peut pas être vide.")
        try:
            matches = search_taxa(query)
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la recherche taxonomique : {exc}", retryable=True
            )
        if not matches:
            return _eco_empty(f"Aucun taxon EcoTaxa ne correspond à `{query}`.")
        lines = [
            "| taxon_id | nom | statut | in_project | aphia_id |",
            "|---:|---|:---:|:---:|---:|",
        ]
        for match in matches[:25]:
            status = match.get("status") or "—"
            in_project = "✓" if match.get("in_project") else "—"
            aphia = match.get("aphia_id") or "—"
            lines.append(
                f"| {match['taxon_id']} | {match['name']} | {status} | "
                f"{in_project} | {aphia} |"
            )
        if len(matches) > 25:
            lines.append(f"\n_(et {len(matches) - 25} autres résultats tronqués)_")
        return _eco_success(
            "\n".join(lines), metrics={"matches": len(matches)}
        )

    @tool(response_format="content_and_artifact")
    def describe_ecotaxa_project_coverage(project_id: int) -> str:
        """Réconcilie la vérité RÉSEAU EcoTaxa et l'INDEX du cache local pour un projet.

        À utiliser AVANT de conclure à une absence EcoTaxa quand un `project_id`
        est connu. Les recherches par zone / période / taxon
        (`find_ecotaxa_samples_in_region`, `find_ecotaxa_observations`,
        `find_ecotaxa_projects_in_region`, `rank_ecotaxa_samples_by_region`,
        `audit_ecotaxa_*`) ne lisent QUE le cache local : un projet accessible
        sur EcoTaxa mais non encore synchronisé y apparaît vide. Sans cette
        réconciliation, un projet non indexé est confondu avec une absence
        scientifique réelle.

        Compare le nombre de samples côté EcoTaxa (réseau, autorisé au compte)
        au nombre de samples présents dans le cache local, et renvoie un verdict
        explicite qui distingue une vraie absence d'un défaut d'indexation :
        `indexe`, `partiel`, `non_indexe` (dans le périmètre du sync, resync
        utile), `hors_perimetre_sync` (lisible par ID mais absent de la
        recherche projet — resync ordinaire inefficace), `non_geolocalise`
        (samples sans coordonnées, jamais indexable spatialement), `vide_source`
        (vraie absence), `inaccessible`, ou `reseau_indisponible`. Lecture
        seule, aucun export.
        """
        pid = int(project_id)
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            coverage = project_cache_coverage(conn, pid)
            conn.close()
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la lecture du cache EcoTaxa : {exc}", retryable=True
            )

        n_cached = int(coverage["n_samples_cached"])
        last_sync = coverage["last_sync"] or {}
        sync_line = (
            f"{last_sync.get('status', '?')} — {last_sync.get('ended_at') or last_sync.get('started_at') or '?'}"
            if last_sync
            else "jamais synchronisé"
        )

        n_network: int | None = None
        n_geoloc: int | None = None
        in_sync_scope: bool | None = None
        title: str | None = None
        network_error: str | None = None
        try:
            client = EcotaxaClient()
            client.login()
            project = client.get_project(pid)
            title = str(project.get("title") or project.get("name") or "").strip() or None
            samples = client.list_samples(pid) or []
            n_network = len(samples)
            n_geoloc = sum(
                1
                for s in samples
                if s.get("latitude") is not None and s.get("longitude") is not None
            )
            # The full sync only iterates projects returned by list_projects();
            # a project readable by ID but absent from that search is out of the
            # sync's reach, so a plain resync will never index it.
            try:
                syncable = {
                    int(p.get("project_id") or p.get("projid"))
                    for p in (client.list_projects() or [])
                }
                in_sync_scope = pid in syncable
            except Exception:
                in_sync_scope = None
        except Exception as exc:  # réseau indisponible ou projet inaccessible
            network_error = str(exc)

        if network_error is not None:
            if n_cached > 0:
                verdict = "reseau_indisponible"
                headline = (
                    f"Réseau EcoTaxa indisponible ({network_error}). Le cache local "
                    f"contient {n_cached} sample(s) pour le projet {pid} : l'exploration "
                    "locale reste possible, mais la fraîcheur ne peut pas être confirmée."
                )
            else:
                verdict = "inaccessible"
                headline = (
                    f"Projet {pid} inaccessible côté réseau ({network_error}) ET absent du "
                    "cache local. Impossible d'affirmer qu'il existe ou qu'il est vide : "
                    "ni le réseau ni le cache ne le connaissent."
                )
        elif n_network == 0:
            verdict = "vide_source"
            headline = (
                f"Projet {pid} accessible sur EcoTaxa mais vide côté source (0 sample). "
                "Absence réelle, pas un défaut de cache."
            )
        elif n_cached == 0 and in_sync_scope is False:
            verdict = "hors_perimetre_sync"
            headline = (
                f"Projet {pid} lisible par identifiant ({n_network} sample(s) sur EcoTaxa) "
                "mais absent de la recherche projet du compte : le sync du cache n'itère que "
                "les projets renvoyés par cette recherche, donc un resync ordinaire ne "
                "l'indexera pas. L'exploration locale (zone / période / taxon) ne le couvre "
                "pas. Ne pas présenter ce projet comme une absence de données."
            )
        elif n_cached == 0 and n_geoloc == 0:
            verdict = "non_geolocalise"
            headline = (
                f"Projet {pid} accessible sur EcoTaxa ({n_network} sample(s)) mais sans "
                "aucune coordonnée au niveau sample : l'index spatial du cache restera vide "
                "même après resync. Les recherches par zone ne le trouveront pas ; ce n'est "
                "pas une absence de données mais une absence de géolocalisation."
            )
        elif n_cached == 0:
            verdict = "non_indexe"
            headline = (
                f"Projet {pid} accessible sur EcoTaxa ({n_network} sample(s)) mais NON "
                "indexé dans le cache local. Les recherches zone / période / taxon ne le "
                "verront pas : un resync du cache est nécessaire avant de l'explorer. "
                "Ne pas présenter ce projet comme une absence de données."
            )
        elif n_network is not None and n_cached < n_network:
            verdict = "partiel"
            headline = (
                f"Projet {pid} indexé partiellement : {n_cached}/{n_network} sample(s) en "
                "cache. L'exploration locale est incomplète ; un resync est recommandé."
            )
        else:
            verdict = "indexe"
            headline = (
                f"Projet {pid} indexé et cohérent : {n_cached} sample(s) en cache "
                f"(réseau : {n_network}). L'exploration locale est fiable."
            )

        lines = [
            f"# Couverture EcoTaxa — projet {pid}"
            + (f" · {title}" if title else ""),
            "",
            headline,
            "",
            "| dimension | valeur |",
            "|---|---:|",
            f"| samples côté EcoTaxa (réseau) | {n_network if n_network is not None else '—'} |",
            f"| dont géolocalisés (niveau sample) | {n_geoloc if n_geoloc is not None else '—'} |",
            f"| samples dans le cache local | {n_cached} |",
            f"| dans le périmètre du sync | {'oui' if in_sync_scope else ('non' if in_sync_scope is False else '—')} |",
            f"| schéma du projet en cache | {'oui' if coverage['in_schema_cache'] else 'non'} |",
            f"| période en cache | {coverage['date_min'] or '—'} → {coverage['date_max'] or '—'} |",
            f"| dernier sync du cache | {sync_line} |",
            f"| {_ecotaxa_project_url(pid)} | |",
        ]
        return _eco_success(
            "\n".join(lines),
            provenance={"project_id": pid, "verdict": verdict},
            metrics={
                "n_samples_cached": n_cached,
                "n_samples_network": int(n_network) if n_network is not None else -1,
                "n_samples_geolocated": int(n_geoloc) if n_geoloc is not None else -1,
            },
        )

    @tool(response_format="content_and_artifact")
    def inspect_ecotaxa_column(
        project_id: int,
        column_name: str,
        level: str | None = None,
    ) -> str:
        """Inspecte la distribution d'une colonne d'un projet EcoTaxa.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Pour les colonnes numériques : min/max/mean/median/p25/p75. Pour les
        colonnes texte : top valeurs + nombre de distinctes. Précise `level`
        si l'agent renvoie une erreur d'ambiguïté.

        Si l'utilisateur a fourni un `column_name` clair et que ce tool
        retourne un résultat, ne pas appeler ensuite
        `inspect_ecotaxa_project_schema` pour la même question.
        """
        try:
            result = get_column_distribution(
                project_id, column_name, level=level
            )
        except EcoTaxaBrowserError as exc:
            details = ""
            if exc.candidates:
                details = " — candidats : " + ", ".join(
                    f"{c['level']}.{c['kind']}({c['type']})" for c in exc.candidates
                )
            return _eco_error(f"Erreur EcoTaxa ({exc.code}) : {exc}{details}")
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de l'analyse de la colonne EcoTaxa : {exc}",
                retryable=True,
                provenance={"project_id": int(project_id)},
            )

        header = (
            f"# Colonne `{result['column']}` — projet {project_id}\n"
            f"Niveau : {result['level']} · Type : {result['type']} · "
            f"Source : {result['source']}"
        )
        stats = result["stats"]
        if result["type"] == "number":
            body = (
                f"\n\n| min | max | moy | médiane | p25 | p75 | n |\n"
                f"|---:|---:|---:|---:|---:|---:|---:|\n"
                f"| {stats.get('min')} | {stats.get('max')} | {stats.get('mean')} | "
                f"{stats.get('median')} | {stats.get('p25')} | {stats.get('p75')} | "
                f"{stats.get('n')} |"
            )
        else:
            top = stats.get("top_values", [])
            body = (
                f"\n\nÉchantillon : {stats.get('sample_size', 0)} valeurs · "
                f"Distinctes : {stats.get('total_distinct', 0)}\n\n"
                "| valeur | count |\n|---|---:|\n"
                + "\n".join(f"| {item['value']} | {item['count']} |" for item in top)
            )
        return _eco_success(
            header + body,
            provenance={"project_id": int(project_id)},
            metrics={"column": str(result["column"])},
        )

    @tool(response_format="content_and_artifact")
    def compare_ecotaxa_projects(project_ids: list[int]) -> str:
        """Compare les schémas de plusieurs projets EcoTaxa avant un export combiné.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Retourne les colonnes communes, les conflits de type, les conflits de
        niveau, et les colonnes uniques par projet.
        """
        if len(project_ids) < 2:
            return _eco_blocked("Indique au moins 2 project_ids.")
        try:
            result = compare_project_schemas(project_ids=project_ids)
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la comparaison EcoTaxa : {exc}", retryable=True
            )

        lines = [f"# Comparaison projets {project_ids}"]
        lines.append("")
        lines.append(f"## Colonnes communes ({len(result['common_columns'])})")
        for col in result["common_columns"]:
            lines.append(f"- `{col['label_normalized']}` ({len(col['matched_in'])} matches)")
        lines.append("")
        lines.append(f"## Conflits de type ({len(result['type_conflicts'])})")
        for conflict in result["type_conflicts"]:
            lines.append(
                f"- `{conflict['label_normalized']}` [{conflict['severity']}] : "
                f"{conflict['types_seen']}"
            )
        lines.append("")
        lines.append(f"## Conflits de niveau ({len(result['level_conflicts'])})")
        for conflict in result["level_conflicts"]:
            lines.append(
                f"- `{conflict['label_normalized']}` : {conflict['levels_seen']}"
            )
        lines.append("")
        lines.append("## Colonnes uniques par projet")
        for pid, cols in result["unique_to_project"].items():
            lines.append(f"- projet {pid} : {cols if cols else '(aucune)'}")
        lines.append("")
        lines.append("## Sources")
        for pid in project_ids:
            lines.append(f"- projet {pid} : {_ecotaxa_project_url(pid)}")
        return _eco_success(
            "\n".join(lines),
            provenance={"project_ids": [int(pid) for pid in project_ids]},
            metrics={"projects": len(project_ids)},
        )

    @tool(response_format="content_and_artifact")
    def find_ecotaxa_samples_in_region(
        bbox: dict | None = None,
        date_range: dict | None = None,
        instrument: str | None = None,
        polygon_wkt: str | None = None,
        zone_name: str | None = None,
        project_ids: list[int] | None = None,
        depth_max_lt: float | None = None,
        depth_max_gte: float | None = None,
        depth_min_lt: float | None = None,
        depth_min_gte: float | None = None,
        month: int | None = None,
    ) -> str:
        """Cherche les samples EcoTaxa dans une bbox géo et/ou une période.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Do NOT use this tool when the user names a taxon/group (Copepoda,
        Calanus, copepods, etc.). This tool has no `taxon` argument. For
        taxon + region/date questions, call `find_ecotaxa_observations`.

        `bbox` : `{"south": float, "west": float, "north": float, "east": float}`.
        `date_range` : `{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}`.
        `instrument` : nom exact ("UVP6", "UVP5SD", "Loki", ...).
        `zone_name` : nom d'une zone NeoLab (ex. "Baie de Baffin",
        "Baie d'Ungava", "Hudson Bay", "Hawke Channel", ...). Le tool
        résout le polygone précis IHO/NeoLab en interne et applique un
        post-filtre in-polygon — utiliser ça **par défaut** quand
        l'utilisateur nomme une zone, même si la précision n'est pas
        explicitement demandée. Évite de passer un `polygon_wkt` géant via
        le LLM.
        `polygon_wkt` : polygone précis (WKT WGS84) — réservé aux cas où
        l'utilisateur fournit son propre polygone (pas une zone nommée).
        `project_ids` : restreint la recherche à une liste de projets
        EcoTaxa. Utile pour « samples du projet X dans la zone Y » en un
        seul appel (filtre côté SQL, pas post-process).
        `depth_max_lt` / `depth_max_gte` : filtre la profondeur **maximale**
        atteinte par le sample (en mètres). Pour « n'ont pas atteint 100 m »,
        `depth_max_lt=100` ; pour « descendent à plus de 200 m » /
        « descendent en-dessous de 200 m », `depth_max_gte=200`.
        `depth_min_lt` / `depth_min_gte` : filtre la profondeur **minimale**
        du sample (où le cast démarre). Pour « ne touche pas la surface,
        depth_min ≥ 50 m », `depth_min_gte=50` ; pour « passe dans les 10
        premiers mètres », `depth_min_lt=10`. Combiner
        `depth_min_gte=A, depth_max_lt=B` pour « cast contenu dans la tranche
        A–B m ».
        Les samples sans profondeur connue ne matchent pas ces filtres.
        `month` : mois calendaire 1-12, toutes années confondues. Pour
        « samples du mois de juillet », utiliser `month=7`.
        Réponse plafonnée à 500 samples avec un summary par projet.
        Lecture du cache local — pas de download.

        Au moins UN filtre est requis (bbox, date_range, instrument,
        zone_name, polygon_wkt, project_ids, depth_*_lt/gte ou month).
        """
        if (bbox is None and date_range is None and instrument is None
                and polygon_wkt is None and zone_name is None
                and not project_ids and depth_max_lt is None
                and depth_max_gte is None and depth_min_lt is None
                and depth_min_gte is None and month is None):
            return _eco_blocked(
                "Erreur : au moins un filtre requis (bbox, date_range, instrument, zone_name, polygon_wkt, project_ids, profondeur ou month). "
                "Pour explorer sans filtre, précise une bbox large, une période, ou un instrument."
            )
        try:
            result = samples_in_region(
                bbox=bbox, date_range=date_range, instrument=instrument,
                polygon_wkt=polygon_wkt, zone_name=zone_name,
                project_ids=project_ids,
                depth_max_lt=depth_max_lt,
                depth_max_gte=depth_max_gte,
                depth_min_lt=depth_min_lt,
                depth_min_gte=depth_min_gte,
                month=month,
            )
        except EcoTaxaBrowserError as exc:
            return _eco_error(f"Erreur EcoTaxa ({exc.code}) : {exc}")
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la recherche EcoTaxa : {exc}", retryable=True
            )

        if not result["samples"]:
            return _eco_empty(
                "Aucun sample dans cette zone / période."
                + _ecotaxa_partial_notice(result)
            )

        max_rows = _env_int("ECOTAXA_SAMPLE_RESULT_ROWS", 15)
        max_ids = _env_int("ECOTAXA_SAMPLE_ID_LIST_LIMIT", 120)
        shown_samples = result["samples"][:max_rows]
        shown_ids = [str(sample["sample_id"]) for sample in result["samples"][:max_ids]]
        selection_name = _selection_name(
            zone_name=zone_name,
            instrument=instrument,
            date_range=date_range,
            month=month,
            project_ids=project_ids,
        )
        _store_sample_selection(
            name=selection_name,
            samples=result["samples"],
            filters={
                "bbox": bbox,
                "date_range": date_range,
                "instrument": instrument,
                "polygon_wkt": bool(polygon_wkt),
                "zone_name": zone_name,
                "project_ids": project_ids,
                "depth_max_lt": depth_max_lt,
                "depth_max_gte": depth_max_gte,
                "depth_min_lt": depth_min_lt,
                "depth_min_gte": depth_min_gte,
                "month": month,
            },
        )
        project_count = len({int(sample["project_id"]) for sample in result["samples"]})
        lines = [
            f"# Résultat EcoTaxa — {result['total_matching']} samples sélectionnés"
            + (" — résultat tronqué par la source" if result["truncated"] else "")
            + (" — résultat partiel" if result.get("partial") else ""),
            f"Sélection mémorisée : `{selection_name}`",
            "",
            "## Résumé de la sélection",
            "",
            "| total sélectionné | lignes affichées | projets | statut |",
            "|---:|---:|---:|---|",
            f"| {len(result['samples'])} | {len(shown_samples)} | {project_count} | "
            f"{'partiel' if result.get('partial') else 'complet'} |",
            f"Projets principaux : {_sample_project_counts(result['samples'])}",
            f"Instruments : {_compact_instruments(result['samples'])}",
            "sample_ids visibles : "
            + ", ".join(shown_ids)
            + (
                f", ... (+{len(result['samples']) - max_ids})"
                if len(result["samples"]) > max_ids
                else ""
            ),
            "",
            (
                f"## Tableau des samples — aperçu ({len(shown_samples)} sur "
                f"{len(result['samples'])})"
                if len(result["samples"]) > len(shown_samples)
                else "## Tableau des samples"
            ),
            "",
            "| sample_id | projet | station | lat | lon | date_min | date_max | depth_min | depth_max | instrument | url |",
            "|---:|---:|---|---:|---:|---|---|---:|---:|---|---|",
        ]
        for s in shown_samples:
            station_label = (
                s.get("station_id")
                or s.get("original_id")
                or s.get("profile_id")
                or "—"
            )
            lines.append(
                f"| {s['sample_id']} | {s['project_id']} | {station_label} | "
                f"{_fmt_coord(s.get('lat'))} | {_fmt_coord(s.get('lon'))} | "
                f"{s['date_min']} | {s['date_max']} | "
                f"{_format_number(s.get('depth_min'))} | "
                f"{_format_number(s.get('depth_max'))} | "
                f"{s.get('instrument') or '—'} | "
                f"{_ecotaxa_sample_url(s['project_id'], s['sample_id'])} |"
            )
        if len(result["samples"]) > max_rows:
            lines.append("")
            lines.append(
                f"Aperçu : {max_rows} premières lignes affichées sur "
                f"{len(result['samples'])}. La sélection complète reste mémorisée "
                "pour les questions suivantes, les tableaux et les graphes."
            )
        lines.extend([
            "",
            "## Actions possibles",
        ])
        lines.extend(f"- {action}" for action in _selection_actions(
            selection_name, len(result["samples"]), project_count,
        ))
        if result.get("partial"):
            lines.append(_ecotaxa_partial_notice(result).strip())
        return _eco_success(
            "\n".join(lines),
            data_ref=f"selection:{selection_name}",
            persisted=True,
            metrics={
                "samples": int(result["total_matching"]),
                "projects": project_count,
            },
        )

    @tool(response_format="content_and_artifact")
    def group_ecotaxa_samples_by_year(
        zone_name: str | None = None,
        station: str | None = None,
        bbox: dict | None = None,
        polygon_wkt: str | None = None,
        date_range: dict | None = None,
        instrument: str | None = None,
        project_ids: list[int] | None = None,
        depth_max_lt: float | None = None,
        depth_max_gte: float | None = None,
        depth_min_lt: float | None = None,
        depth_min_gte: float | None = None,
        month: int | None = None,
    ) -> str:
        """Regroupe par ANNÉE les samples EcoTaxa d'un lieu suivi dans la durée.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        À utiliser quand l'utilisateur veut une vue **interannuelle** d'un
        même endroit : « couverture par année à la station X », « combien de
        samples par année dans la Baie de Baffin », « quelles années sont
        échantillonnées ici », avant un export étalé sur plusieurs années.
        Une zone peut couvrir **plusieurs stations** ; le tool compte les
        stations distinctes par année.

        `zone_name` : nom d'une zone NeoLab/IHO (ex. "Baie de Baffin"). Résolu
        en polygone précis en interne (post-filtre in-polygon).
        `station` : nom/identifiant d'une station précise (ex. "St-27",
        "ice-camp"). Ne garde que les samples dont un identifiant
        (station_id / original_id / profile_id) contient cette chaîne.
        `bbox` / `polygon_wkt` : alternatives géographiques (voir
        `find_ecotaxa_samples_in_region`).
        `date_range` : `{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}` pour borner
        la fenêtre d'années.
        `instrument`, `project_ids`, `month` : mêmes sémantiques que
        `find_ecotaxa_samples_in_region`.
        `depth_max_lt` / `depth_max_gte` : filtre la profondeur **maximale**
        atteinte par le sample (objet le plus profond). Pour « couverture
        interannuelle des casts qui descendent sous 200 m », `depth_max_gte=200`.
        `depth_min_lt` / `depth_min_gte` : filtre la profondeur **minimale** du
        sample (objet le moins profond). Pour restreindre la vue interannuelle
        à une tranche précise, combiner `depth_min_gte=A, depth_max_lt=B` →
        ne garde que les samples dont le cast est contenu dans [A, B[ m (utile
        pour un profil vertical d'abondance sur une bande de profondeur donnée).
        Les samples sans profondeur connue ne matchent pas ces filtres.

        Renvoie un tableau année × (n_samples, n_stations, dates, instruments,
        projets) et **mémorise la sélection multi-années** pour un export
        ultérieur via `export_ecotaxa_samples(selection_name=...)`. Lecture du
        cache local — pas de download.

        Au moins UN filtre de lieu/temps/profondeur est requis (zone_name,
        station, bbox, polygon_wkt, date_range, instrument, project_ids,
        depth_*_lt/gte ou month).
        """
        if (zone_name is None and station is None and bbox is None
                and polygon_wkt is None and date_range is None
                and instrument is None and not project_ids and month is None
                and depth_max_lt is None and depth_max_gte is None
                and depth_min_lt is None and depth_min_gte is None):
            return _eco_blocked(
                "Erreur : au moins un filtre requis (zone_name, station, bbox, "
                "polygon_wkt, date_range, instrument, project_ids, profondeur "
                "ou month)."
            )
        try:
            result = samples_by_year(
                bbox=bbox, date_range=date_range, instrument=instrument,
                polygon_wkt=polygon_wkt, zone_name=zone_name, station=station,
                project_ids=project_ids,
                depth_max_lt=depth_max_lt, depth_max_gte=depth_max_gte,
                depth_min_lt=depth_min_lt, depth_min_gte=depth_min_gte,
                month=month,
            )
        except EcoTaxaBrowserError as exc:
            return _eco_error(f"Erreur EcoTaxa ({exc.code}) : {exc}")
        except Exception as exc:
            return _eco_error(
                f"Erreur lors du regroupement par année : {exc}", retryable=True
            )

        years = result["years"]
        if not years:
            return _eco_empty(
                "Aucun sample pour ce lieu / cette période."
                + _ecotaxa_partial_notice(result)
            )

        location = station or zone_name or "sélection EcoTaxa"
        selection_name = _selection_name(
            zone_name=(station or zone_name),
            instrument=instrument,
            date_range=date_range,
            month=month,
            project_ids=project_ids,
        )
        # Réutilise la sélection : un "sample" minimal (sample_id + project_id)
        # par sample, sur toutes les années, pour l'export multi-années.
        selection_samples = [
            {"sample_id": sid, "project_id": year["project_ids"][0] if year["project_ids"] else 0}
            for year in years
            for sid in year["sample_ids"]
        ]
        _store_sample_selection(
            name=selection_name,
            samples=selection_samples,
            filters={
                "zone_name": zone_name, "station": station, "bbox": bbox,
                "polygon_wkt": bool(polygon_wkt), "date_range": date_range,
                "instrument": instrument, "project_ids": project_ids,
                "depth_max_lt": depth_max_lt, "depth_max_gte": depth_max_gte,
                "depth_min_lt": depth_min_lt, "depth_min_gte": depth_min_gte,
                "month": month, "grouped_by": "year",
            },
        )

        real_years = [y for y in years if y["year"] is not None]
        year_span = (
            f"{real_years[0]['year']}–{real_years[-1]['year']}"
            if real_years else "années inconnues"
        )
        lines = [
            f"# {location} — {result['total_matching']} samples sur "
            f"{result['n_years']} année(s) ({year_span})",
            f"Sélection mémorisée : `{selection_name}`",
            "",
            "| année | n_samples | n_stations | date_min | date_max | instruments | projets |",
            "|---:|---:|---:|---|---|---|---|",
        ]
        for y in years:
            year_label = y["year"] if y["year"] is not None else "sans date"
            instruments = ", ".join(y["instruments"]) or "—"
            projects = ", ".join(str(p) for p in y["project_ids"][:6]) or "—"
            if len(y["project_ids"]) > 6:
                projects += f", … (+{len(y['project_ids']) - 6})"
            lines.append(
                f"| {year_label} | {y['n_samples']} | {y['n_stations']} | "
                f"{y['date_min'] or '—'} | {y['date_max'] or '—'} | "
                f"{instruments} | {projects} |"
            )
        lines.extend([
            "",
            "## Actions possibles",
            f"- exporter cette sélection multi-années : "
            f"`export_ecotaxa_samples(selection_name=\"{selection_name}\", confirmed=false)`",
            "- l'export consolide toutes les années ; regrouper ensuite par "
            "année avec `run_pandas` (colonne de date → année) pour l'analyse "
            "interannuelle",
        ])
        if result.get("partial"):
            lines.append(_ecotaxa_partial_notice(result).strip())
        return _eco_success(
            "\n".join(lines),
            data_ref=f"selection:{selection_name}",
            persisted=True,
            metrics={
                "samples": int(result["total_matching"]),
                "years": int(result["n_years"]),
            },
        )

    @tool(response_format="content_and_artifact")
    def find_ecotaxa_projects_in_region(
        bbox: dict | None = None,
        date_range: dict | None = None,
        polygon_wkt: str | None = None,
        zone_name: str | None = None,
        project_ids: list[int] | None = None,
        depth_max_lt: float | None = None,
        depth_max_gte: float | None = None,
        depth_min_lt: float | None = None,
        depth_min_gte: float | None = None,
    ) -> str:
        """Liste les projets EcoTaxa avec au moins un sample dans une zone / période.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Même format que `find_ecotaxa_samples_in_region` :
        - `zone_name` (recommandé pour les zones nommées NeoLab) : le tool
          résout le polygone IHO en interne.
        - `polygon_wkt` : polygone WKT fourni explicitement.
        - `bbox` / `date_range` : filtres classiques.
        - `project_ids` : restreint à une sous-liste de projets EcoTaxa.
        - `depth_max_lt` / `depth_max_gte` / `depth_min_lt` / `depth_min_gte` :
          filtres profondeur sample-level appliqués AVANT l'agrégation par
          projet. Pour « projets avec samples descendant à plus de 1000 m »,
          `depth_max_gte=1000`. Pour « projets dont les samples ne touchent
          pas la surface (depth_min ≥ 50 m) », `depth_min_gte=50`. Un projet
          est exclu si aucun de ses samples ne matche.
        Quand un polygone (résolu ou explicite) est appliqué, les counts par
        projet excluent les samples hors zone.
        Réponse agrégée au niveau projet : nombre de samples, total objets,
        instruments, plage de dates.

        Au moins UN filtre (bbox, date_range, zone_name, polygon_wkt,
        project_ids ou depth_*_lt/gte) est requis.
        """
        if (bbox is None and date_range is None
                and polygon_wkt is None and zone_name is None
                and not project_ids and depth_max_lt is None
                and depth_max_gte is None and depth_min_lt is None
                and depth_min_gte is None):
            return _eco_blocked(
                "Erreur : au moins un filtre requis (bbox, date_range, zone_name, polygon_wkt, project_ids ou profondeur). "
                "Pour la liste de tous les projets, utilise list_ecotaxa_projects."
            )
        try:
            result = projects_in_region(
                bbox=bbox, date_range=date_range,
                polygon_wkt=polygon_wkt, zone_name=zone_name,
                project_ids=project_ids,
                depth_max_lt=depth_max_lt,
                depth_max_gte=depth_max_gte,
                depth_min_lt=depth_min_lt,
                depth_min_gte=depth_min_gte,
            )
        except EcoTaxaBrowserError as exc:
            return _eco_error(f"Erreur EcoTaxa ({exc.code}) : {exc}")
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la recherche EcoTaxa : {exc}", retryable=True
            )

        if not result["projects"]:
            return _eco_empty(
                "Aucun projet dans cette zone / période."
                + _ecotaxa_partial_notice(result)
            )

        lines = [
            f"# {result['total_projects']} projets, {result['total_samples']} samples"
            + (" — résultat partiel" if result.get("partial") else ""),
            "",
            "| project_id | samples | objets | instruments | date_min | date_max | url |",
            "|---:|---:|---:|---|---|---|---|",
        ]
        for p in result["projects"]:
            lines.append(
                f"| {p['project_id']} | {p['sample_count']} | "
                f"{p['object_count']} | {', '.join(p['instruments']) or '—'} | "
                f"{p['date_min'] or '—'} | {p['date_max'] or '—'} | "
                f"{_ecotaxa_project_url(p['project_id'])} |"
            )
        if result.get("partial"):
            lines.append(_ecotaxa_partial_notice(result).strip())
        return _eco_success(
            "\n".join(lines),
            metrics={
                "projects": int(result["total_projects"]),
                "samples": int(result["total_samples"]),
            },
        )

    @tool(response_format="content_and_artifact")
    def group_ecotaxa_project_samples_by_region(project_id: int) -> str:
        """Groupe tous les samples cache d'un projet EcoTaxa par zone IHO/NeoLab.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Utiliser quand l'utilisateur demande une vue « par mer », « par
        secteur », « par zone », ou « groupe les samples du projet X par
        région ». Le tool lit uniquement le cache local, teste chaque sample
        contre le registry NeoLab/IHO, et rend un récap compact :
        region -> sample_ids, avec buckets explicites `Hors zone référencée` et
        `Sans coordonnées`.
        """
        try:
            result = group_project_samples_by_region(project_id)
        except EcoTaxaBrowserError as exc:
            return _eco_error(
                f"Erreur EcoTaxa ({exc.code}) : {exc}",
                provenance={"project_id": int(project_id)},
            )
        except Exception as exc:
            return _eco_error(
                f"Erreur lors du regroupement EcoTaxa : {exc}",
                retryable=True,
                provenance={"project_id": int(project_id)},
            )

        summary = result.get("markdown_summary", "")
        if result.get("partial"):
            summary += _ecotaxa_partial_notice(result)
        if not summary:
            return _eco_empty(
                f"Aucun sample groupé pour le projet {project_id}.",
                provenance={"project_id": int(project_id)},
            )
        return _eco_success(
            summary, provenance={"project_id": int(project_id)}
        )

    @tool(response_format="content_and_artifact")
    def rank_ecotaxa_samples_by_region(
        include_empty: bool = False,
        sort_by: str = "sample_count",
        sort_order: str = "asc",
    ) -> str:
        """Classe les régions / mers EcoTaxa par nombre ou ancienneté des samples.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Utiliser quand l'utilisateur demande les zones, mers, secteurs ou
        régions les moins / plus échantillonnés dans le cache EcoTaxa, ou un
        classement global par couverture d'échantillonnage. Le tool lit
        uniquement le cache local, agrège tous les samples indexés par
        polygone NeoLab/IHO/MEOW, puis retourne un tableau avec nombre de
        samples, nombre de projets, `date_min` et `date_max` par région.

        `include_empty=False` par défaut exclut les zones à 0 sample pour
        éviter de noyer la réponse dans les régions mondiales hors périmètre.
        Passer `include_empty=True` quand l'utilisateur demande explicitement
        les zones **vides** / **lacunes** / **zones sans sample** /
        **zones non échantillonnées** / **zones voisines vides** — c'est la
        réponse canonique pour « montre les zones sans données EcoTaxa ».
        `sort_order="asc"` classe du moins au plus échantillonné. Utiliser
        `sort_order="desc"` pour "le plus échantillonné", "décroissant",
        "top zones", ou "du plus au moins".
        `sort_by="sample_count"` trie par nombre de samples. Utiliser
        `sort_by="date_min", sort_order="asc"` pour "les plus anciennes
        zones échantillonnées", "ancienneté", "premières zones
        échantillonnées". Utiliser `sort_by="date_max", sort_order="desc"`
        pour les zones les plus récemment échantillonnées.

        Limite : le cache indexe les coordonnées des samples, mais pas les
        noms de stations; ce tool classe donc les régions / mers, pas les
        stations nominales.
        """
        try:
            result = rank_samples_by_region(
                include_empty=include_empty,
                sort_by=sort_by,
                sort_order=sort_order,
            )
        except EcoTaxaBrowserError as exc:
            return _eco_error(f"Erreur EcoTaxa ({exc.code}) : {exc}")
        except Exception as exc:
            return _eco_error(
                f"Erreur lors du classement EcoTaxa par région : {exc}",
                retryable=True,
            )

        summary = result.get("markdown_summary", "")
        if result.get("partial"):
            summary += _ecotaxa_partial_notice(result)
        if not summary:
            return _eco_empty("Aucune région EcoTaxa à classer.")
        return _eco_success(summary)

    @tool(response_format="content_and_artifact")
    def find_ecotaxa_observations(
        taxon: str,
        bbox: dict | None = None,
        date_range: dict | None = None,
        instrument: str | None = None,
        status: str = "V",
        polygon_wkt: str | None = None,
        zone_name: str | None = None,
        project_ids: list[int] | None = None,
        depth_max_lt: float | None = None,
        depth_max_gte: float | None = None,
        depth_min_lt: float | None = None,
        depth_min_gte: float | None = None,
        month: int | None = None,
    ) -> str:
        """Trouve les samples EcoTaxa dont le projet a le taxon attesté.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Granularité projet-filtrée : retourne les samples (bbox/date/instrument)
        appartenant à un projet où le taxon a au moins un objet du statut
        demandé (`V` validé, `P` prédit, `D` douteux, `all`). Pour des counts
        précis par projet, enchaîner sur `count_ecotaxa_taxa`.

        `zone_name` (recommandé pour zones nommées) : le tool résout en
        interne le polygone IHO/NeoLab. Le filtre est appliqué AVANT
        l'attestation projet — un projet qui n'a que des samples hors
        polygone est exclu.
        `polygon_wkt` (alternative) : polygone WKT fourni explicitement.
        `project_ids` : restreint à une sous-liste de projets avant
        l'attestation taxon. Pour « taxon X dans la zone Y du projet Z ».
        `depth_max_lt` / `depth_max_gte` : filtre la profondeur **maximale**
        atteinte par les samples avant l'attestation taxon. Pour « samples
        avec Calanus qui n'ont pas atteint 100 m », `depth_max_lt=100` ;
        pour « samples qui descendent à plus de 200 m », `depth_max_gte=200`.
        `depth_min_lt` / `depth_min_gte` : filtre la profondeur **minimale**
        du sample. Pour « ne touche pas la surface (depth_min ≥ 50 m) »,
        `depth_min_gte=50`. Combiner `depth_min_gte=A, depth_max_lt=B` pour
        « cast contenu dans la tranche A–B m ».
        `month` : mois calendaire 1-12, toutes années confondues.
        """
        try:
            result = find_observations(
                taxon=taxon, bbox=bbox, date_range=date_range,
                instrument=instrument, status=status,
                polygon_wkt=polygon_wkt, zone_name=zone_name,
                project_ids=project_ids,
                depth_max_lt=depth_max_lt,
                depth_max_gte=depth_max_gte,
                depth_min_lt=depth_min_lt,
                depth_min_gte=depth_min_gte,
                month=month,
            )
        except EcoTaxaBrowserError as exc:
            details = ""
            if exc.candidates:
                details = " — candidats : " + ", ".join(
                    f"{c.get('taxon_id')}={c.get('display_name')}"
                    for c in exc.candidates[:5]
                )
            return _eco_error(f"Erreur EcoTaxa ({exc.code}) : {exc}{details}")
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la recherche EcoTaxa : {exc}", retryable=True
            )

        if not result["samples"]:
            attested = result["attested_projects"]
            return _eco_empty(
                f"Aucun sample (cache local) dans un projet attestant "
                f"{result['taxon']['matched_name']} au statut {status} — "
                f"projets attestés : {attested or 'aucun'}."
                + _ecotaxa_partial_notice(result)
            )

        lines = [
            f"# {result['total_matching']} samples × {result['taxon']['matched_name']}"
            + (" — tronqué" if result["truncated"] else "")
            + (" — résultat partiel" if result.get("partial") else ""),
            f"Statut filtré : {result['status_filter']} · "
            f"Projets attestés : {result['attested_projects']}",
            "",
            "| sample_id | projet | lat | lon | date_min | date_max | depth_min | depth_max | url |",
            "|---:|---:|---:|---:|---|---|---:|---:|---|",
        ]
        for s in result["samples"][:50]:
            lines.append(
                f"| {s['sample_id']} | {s['project_id']} | {_fmt_coord(s.get('lat'))} | "
                f"{_fmt_coord(s.get('lon'))} | {s['date_min']} | {s['date_max']} | "
                f"{_format_number(s.get('depth_min'))} | "
                f"{_format_number(s.get('depth_max'))} | "
                f"{_ecotaxa_sample_url(s['project_id'], s['sample_id'])} |"
            )
        if len(result["samples"]) > 50:
            lines.append("")
            lines.append(f"(50 premiers / {len(result['samples'])} affichés)")
        if result.get("partial"):
            lines.append(_ecotaxa_partial_notice(result).strip())
        return _eco_success(
            "\n".join(lines), metrics={"samples": int(result["total_matching"])}
        )

    @tool(response_format="content_and_artifact")
    def get_ecotaxa_sample(sample_id: int) -> str:
        """Renvoie les métadonnées complètes d'un sample (déploiement) EcoTaxa.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        `sample_id` est l'identifiant EcoTaxa du sample (entier, ex. 42000002).
        Réponse : identifiants, lat/lon, original_id (nom de station lisible),
        et tous les `free_fields` exposés par le projet (volume filtré, station,
        leg, mesh, etc. — varie par projet). Pas de download d'objets.
        """
        try:
            sample = core_get_sample(sample_id)
        except EcoTaxaBrowserError as exc:
            return _eco_error(
                f"Erreur EcoTaxa ({exc.code}) : {exc}",
                provenance={"sample_id": int(sample_id)},
            )
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de l'accès au sample {sample_id} : {exc}",
                retryable=True,
                provenance={"sample_id": int(sample_id)},
            )

        lat = sample.get("latitude")
        lon = sample.get("longitude")
        lines = [
            f"# Sample EcoTaxa {sample['sample_id']} (projet {sample['project_id']})",
            "",
            "| Champ | Valeur |",
            "|---|---|",
            f"| sample_id | {sample['sample_id']} |",
            f"| project_id | {sample['project_id']} |",
            f"| original_id | {sample.get('original_id') or '—'} |",
            f"| latitude | {f'{lat:.3f}' if isinstance(lat, (int, float)) else '—'} |",
            f"| longitude | {f'{lon:.3f}' if isinstance(lon, (int, float)) else '—'} |",
        ]

        free_fields = sample.get("free_fields") or {}
        if free_fields:
            lines.extend([
                "",
                "## Free fields",
                "",
                "| Champ | Valeur |",
                "|---|---|",
            ])
            for key in sorted(free_fields):
                lines.append(f"| {key} | {free_fields[key]} |")
        else:
            lines.append("")
            lines.append("(Aucun free field exposé par le projet pour ce sample.)")

        lines.append("")
        lines.append(
            f"Source EcoTaxa : {_ecotaxa_sample_url(sample['project_id'], sample['sample_id'])}"
        )
        return _eco_success(
            "\n".join(lines),
            provenance={
                "project_id": int(sample["project_id"]),
                "sample_id": int(sample["sample_id"]),
            },
        )

    @tool(response_format="content_and_artifact")
    def list_ecotaxa_sample_objects(
        sample_id: int,
        taxon_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> str:
        """Liste les objets contenus DANS un sample EcoTaxa, à partir de son
        `sample_id`, en lecture seule et SANS export.

        Quand l'utiliser : c'est LE point d'entrée pour explorer le contenu d'un
        sample. Réponds avec ce tool à « montre / liste les objets du sample X »,
        « quels objets / taxons dans le sample X », « feuillette le contenu du
        sample X », « qu'y a-t-il dans le sample X ». Il prend un `sample_id`
        (11 chiffres, ex. 17498000001) et renvoie PLUSIEURS objets. Utilise-le
        avant tout export pour décider si le sample vaut un téléchargement.

        Ne pas confondre avec `get_ecotaxa_object`, qui ne montre qu'UN objet à
        partir d'un `object_id` déjà connu — pas d'un sample.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Requête objet paginée légère (`object_set/query`) — aucun job d'export,
        aucune image.

        Args:
            sample_id: ID du sample EcoTaxa (ex. 42000002).
            taxon_id: filtre optionnel par `taxon_id` EcoTaxa (résous d'abord un
                nom avec `search_ecotaxa_taxa`).
            status: filtre optionnel — "V" (validé), "P" (prédit), "D" (douteux).
            page: numéro de page (défaut 1).
            page_size: objets par page (défaut 50, plafonné à 200).

        Renvoie un tableau : object_id, taxon, statut, date, depth_min/max.
        Pour le détail complet d'un objet, enchaîner sur `get_ecotaxa_object`.
        """
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 200))
        try:
            objects = core_list_sample_objects(
                sample_id=int(sample_id),
                taxon=taxon_id,
                status=status,
                page=page,
                page_size=page_size,
            )
        except EcoTaxaBrowserError as exc:
            return _eco_error(
                f"Erreur EcoTaxa ({exc.code}) : {exc}",
                provenance={"sample_id": int(sample_id)},
            )
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la lecture des objets du sample {sample_id} : {exc}",
                retryable=True,
                provenance={"sample_id": int(sample_id)},
            )

        if not objects:
            return _eco_empty(
                f"Aucun objet pour le sample {sample_id} "
                f"(page {page}, filtres taxon_id={taxon_id}, status={status}).",
                provenance={"sample_id": int(sample_id)},
            )

        def _fmt(value) -> str:
            if value is None:
                return "—"
            if isinstance(value, float):
                return f"{value:.1f}".rstrip("0").rstrip(".")
            return str(value)

        lines = [
            f"# Objets du sample {sample_id} — page {page} ({len(objects)} objets, lecture seule)",
            "",
            "| object_id | taxon | statut | date | depth_min | depth_max |",
            "|---:|---|---|---|---:|---:|",
        ]
        for obj in objects:
            taxon = obj.get("taxon") or obj.get("taxon_id") or "—"
            lines.append(
                f"| {obj.get('object_id')} | {taxon} | "
                f"{obj.get('classification_status') or '—'} | "
                f"{obj.get('date') or '—'} | {_fmt(obj.get('depth_min'))} | "
                f"{_fmt(obj.get('depth_max'))} |"
            )
        lines.append("")
        lines.append(
            f"Page suivante : page={page + 1}. Détail d'un objet : "
            "`get_ecotaxa_object(object_id=...)`. Export complet : "
            "`query_ecotaxa_sample`."
        )
        return _eco_success(
            "\n".join(lines),
            provenance={"sample_id": int(sample_id)},
            metrics={"objects": len(objects), "page": page},
        )

    @tool(response_format="content_and_artifact")
    def get_ecotaxa_object(object_id: int) -> str:
        """Fiche détaillée d'UN objet EcoTaxa déjà identifié (un `object_id`).

        Quand l'utiliser : uniquement en second temps, après
        `list_ecotaxa_sample_objects`, pour zoomer sur UN objet précis dont tu
        as l'`object_id` exact (13 chiffres, ex. 1749800000001) et vouloir son
        contexte complet — acquisition, instrument, free fields, lat/lon.

        Quand NE PAS l'utiliser : pour « montre / liste les objets du sample X »,
        « quels objets dans le sample X », « le contenu du sample X ». Ces
        demandes partent d'un `sample_id` (11 chiffres) et renvoient PLUSIEURS
        objets → c'est `list_ecotaxa_sample_objects(sample_id=...)`. Ne jamais
        passer un `sample_id` à ce tool-ci.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Lecture seule, aucun export, aucune image.

        Args:
            object_id: ID d'un OBJET EcoTaxa (ex. 1749800000001), jamais un
                sample_id.
        """
        try:
            payload = core_get_object(int(object_id))
        except EcoTaxaBrowserError as exc:
            return _eco_error(
                f"Erreur EcoTaxa ({exc.code}) : {exc}. Si `{object_id}` est un "
                "sample_id et non un object_id, utilise "
                "`list_ecotaxa_sample_objects(sample_id=...)`.",
                provenance={"object_id": int(object_id)},
            )
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de l'accès à l'objet {object_id} : {exc}",
                retryable=True,
                provenance={"object_id": int(object_id)},
            )

        obj = payload.get("object") or {}
        sample = payload.get("sample") or {}
        acquisition = payload.get("acquisition") or {}
        project = payload.get("project") or {}

        def _fmt(value) -> str:
            if value is None:
                return "—"
            if isinstance(value, float):
                return f"{value:.3f}".rstrip("0").rstrip(".")
            return str(value)

        lines = [
            f"# Objet EcoTaxa {obj.get('object_id')} "
            f"(sample {sample.get('sample_id')}, projet {project.get('project_id')})",
            "",
            "| Champ | Valeur |",
            "|---|---|",
            f"| object_id | {obj.get('object_id')} |",
            f"| original_id | {obj.get('original_id') or '—'} |",
            f"| taxon_id | {_fmt(obj.get('taxon_id'))} |",
            f"| statut | {obj.get('classification_status') or '—'} |",
            f"| date | {obj.get('date') or '—'} |",
            f"| depth_min | {_fmt(obj.get('depth_min'))} |",
            f"| depth_max | {_fmt(obj.get('depth_max'))} |",
            f"| latitude | {_fmt(obj.get('latitude'))} |",
            f"| longitude | {_fmt(obj.get('longitude'))} |",
            "",
            "## Contexte",
            "",
            "| Niveau | Champ | Valeur |",
            "|---|---|---|",
            f"| sample | original_id | {sample.get('original_id') or '—'} |",
            f"| acquisition | acquisition_id | {_fmt(acquisition.get('acquisition_id'))} |",
            f"| acquisition | instrument | {acquisition.get('instrument') or '—'} |",
        ]

        obj_free = obj.get("free_fields") or {}
        if obj_free:
            lines.extend(["", "## Free fields objet", "", "| Champ | Valeur |", "|---|---|"])
            for key in sorted(obj_free):
                lines.append(f"| {key} | {obj_free[key]} |")

        return _eco_success(
            "\n".join(lines),
            provenance={
                "object_id": int(object_id),
                "sample_id": sample.get("sample_id"),
                "project_id": project.get("project_id"),
            },
        )

    @tool(response_format="content_and_artifact")
    def summarize_ecotaxa_sample_deployment(sample_id: int) -> str:
        """Résume le déploiement d'un sample EcoTaxa sans export complet.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Utiliser pour répondre aux questions sur date/lieu/profondeur de
        déploiement, acquisition_id, instrument, cast/profile/station ids et
        métadonnées UVP. Le tool lit les métadonnées sample + acquisitions,
        puis calcule date_min/date_max et depth_min/depth_max depuis les
        objets du sample via une requête légère paginée. Pas de job export,
        pas d'images.
        """
        try:
            deployment = summarize_sample_deployment(sample_id)
        except Exception as exc:
            return _eco_error(
                f"Erreur lors du résumé déploiement EcoTaxa : {exc}",
                retryable=True,
                provenance={"sample_id": int(sample_id)},
            )

        sample = deployment["sample"]
        summary = deployment["object_summary"]
        acquisitions = deployment["acquisitions"]

        def _fmt(value) -> str:
            if value is None:
                return "—"
            if isinstance(value, float):
                return f"{value:.3f}".rstrip("0").rstrip(".")
            return str(value)

        lines = [
            f"# Déploiement EcoTaxa — sample {sample['sample_id']} (projet {sample['project_id']})",
            "",
            "| Champ | Valeur |",
            "|---|---|",
            f"| sample_id | {sample['sample_id']} |",
            f"| project_id | {sample['project_id']} |",
            f"| original_id | {sample.get('original_id') or '—'} |",
            f"| latitude | {_fmt(sample.get('latitude'))} |",
            f"| longitude | {_fmt(sample.get('longitude'))} |",
            f"| date_min objets | {_fmt(summary.get('date_min'))} |",
            f"| date_max objets | {_fmt(summary.get('date_max'))} |",
            f"| depth_min objets | {_fmt(summary.get('depth_min'))} |",
            f"| depth_max objets | {_fmt(summary.get('depth_max'))} |",
            f"| objets scannés | {summary.get('objects_scanned')} / {summary.get('total_objects')} |",
            f"| résumé tronqué | {'oui' if summary.get('truncated') else 'non'} |",
        ]

        sample_free = sample.get("free_fields") or {}
        if sample_free:
            lines.extend(["", "## Free fields sample", "", "| Champ | Valeur |", "|---|---|"])
            for key in sorted(sample_free):
                lines.append(f"| {key} | {sample_free[key]} |")

        lines.extend(["", "## Acquisitions", ""])
        if acquisitions:
            lines.extend([
                "| acquisition_id | sample_id | original_id | instrument | free_fields |",
                "|---:|---:|---|---|---|",
            ])
            for acquisition in acquisitions:
                free_fields = acquisition.get("free_fields") or {}
                free_cell = (
                    ", ".join(f"{key}={free_fields[key]}" for key in sorted(free_fields))
                    if free_fields else "—"
                )
                lines.append(
                    f"| {acquisition['acquisition_id']} | {acquisition['sample_id']} | "
                    f"{acquisition.get('original_id') or '—'} | "
                    f"{acquisition.get('instrument') or '—'} | {free_cell} |"
                )
        else:
            lines.append("Aucune acquisition associée retournée par EcoTaxa.")

        return _eco_success(
            "\n".join(lines),
            provenance={
                "project_id": int(sample["project_id"]),
                "sample_id": int(sample["sample_id"]),
            },
            metrics={
                "objects_scanned": int(summary.get("objects_scanned") or 0),
                "acquisitions": len(acquisitions),
            },
        )

    @tool(response_format="content_and_artifact")
    def summarize_ecotaxa_samples(
        sample_ids: list[int] | None = None,
        selection_name: str | None = None,
    ) -> str:
        """Résume un batch de samples EcoTaxa sans télécharger les objets.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        À utiliser IMPÉRATIVEMENT pour calculer les totaux V/P/D/U d'une
        sélection EcoTaxa (ex. « donne les totaux validés/prédits »,
        « quels taxons dans cette sélection »). NE PAS relancer une
        recherche régionale pour obtenir ces totaux : la sélection mémorisée
        par `find_ecotaxa_samples_in_region` couvre L'ENSEMBLE de la
        sélection, pas uniquement les lignes affichées dans l'aperçu tronqué.

        Args:
            sample_ids: Liste explicite de sample_ids EcoTaxa.
            selection_name: Nom d'une sélection mémorisée par
                `find_ecotaxa_samples_in_region`, ou `"latest"` / `"cette sélection"`.

        Renvoie :
        - Scope complet : N samples demandés vs N retournés par l'API
        - Tableau par sample : V / P / D / U / total / top taxa
        - Section agrégée par projet : totaux V/P/D/U pour chaque projet

        Aucun download — appel léger sur l'endpoint EcoTaxa `/sample_set/taxo_stats`.
        Pour un seul sample, utilise plutôt `summarize_ecotaxa_sample`.
        """
        resolved_selection_name = None
        normalized = _normalize_sample_ids(sample_ids)
        if not normalized and selection_name:
            resolved_selection_name, normalized = _load_sample_selection(selection_name)
        selection_meta: dict = {}
        if resolved_selection_name:
            selection_entry = _store.get(f"{thread_id}:selection:{resolved_selection_name}")
            selection_meta = dict((selection_entry or {}).get("meta") or {})
        if not normalized:
            if selection_name:
                return _eco_blocked(
                    f"Erreur : sélection `{selection_name}` introuvable ou vide. "
                    "Relance une recherche EcoTaxa ou passe des sample_ids explicites."
                )
            return _eco_blocked("Erreur : sample_ids vide.")
        try:
            stats = summarize_samples(normalized)
        except Exception as exc:
            return _eco_error(
                f"Erreur lors du résumé EcoTaxa : {exc}", retryable=True
            )
        if not stats:
            return _eco_empty(
                "Aucune statistique retournée par EcoTaxa pour ces samples."
            )

        n_requested = len(normalized)
        n_returned = len(stats)

        lines = []
        if resolved_selection_name:
            lines.append(f"Sélection : {resolved_selection_name}")
        lines.extend([
            f"Scope : {n_requested} samples demandés → {n_returned} retournés par l'API"
            + (" (subset — totaux ci-dessous portent sur l'ensemble)"
               if n_returned < n_requested else ""),
            "",
            "## Détail par sample",
            "",
            "| sample_id | projet | V | P | D | U | total | top taxa | url |",
            "|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ])
        project_totals: dict[int, dict] = {}
        for entry in stats:
            v = entry["nb_validated"]
            p = entry["nb_predicted"]
            d = entry["nb_dubious"]
            u = entry["nb_unclassified"]
            total = v + p + d + u
            names = [t["name"] for t in entry.get("per_taxon", [])[:5]]
            top = ", ".join(names) if names else "—"
            lines.append(
                f"| {entry['sample_id']} | {entry['projid']} | {v} | {p} | {d} | {u} | {total} | {top} | "
                f"{_ecotaxa_sample_url(entry['projid'], entry['sample_id'])} |"
            )
            pid = int(entry["projid"])
            pt = project_totals.setdefault(pid, {"V": 0, "P": 0, "D": 0, "U": 0})
            pt["V"] += v
            pt["P"] += p
            pt["D"] += d
            pt["U"] += u

        lines.extend([
            "",
            "## Totaux par projet",
            "",
            "| projet | V | P | D | U | total |",
            "|---:|---:|---:|---:|---:|---:|",
        ])
        grand = {"V": 0, "P": 0, "D": 0, "U": 0}
        for pid in sorted(project_totals):
            pt = project_totals[pid]
            tot = pt["V"] + pt["P"] + pt["D"] + pt["U"]
            lines.append(f"| {pid} | {pt['V']} | {pt['P']} | {pt['D']} | {pt['U']} | {tot} |")
            for key in grand:
                grand[key] += pt[key]
        grand_total = sum(grand.values())
        lines.append(
            f"| **TOTAL** | **{grand['V']}** | **{grand['P']}** | **{grand['D']}** | **{grand['U']}** | **{grand_total}** |"
        )
        return _eco_success(
            "\n".join(lines),
            provenance={"sample_ids": normalized},
            metrics={"samples": n_returned, "samples_requested": n_requested},
        )

    @tool(response_format="content_and_artifact")
    def summarize_ecotaxa_sample(sample_id: int) -> str:
        """Résume UN sample EcoTaxa (V/P/D/U counts + taxa observés).

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Variante mono-sample de `summarize_ecotaxa_samples`. Renvoie le même
        tableau réduit à une ligne. Pas de download.
        """
        message = summarize_ecotaxa_samples.invoke({
            "type": "tool_call",
            "id": f"forward-sample-{uuid.uuid4().hex}",
            "name": summarize_ecotaxa_samples.name,
            "args": {"sample_ids": [sample_id]},
        })
        artifact = validate_tool_artifact(message.artifact)
        return message.content, artifact.model_dump(mode="json")

    @tool(response_format="content_and_artifact")
    def summarize_ecotaxa_projects(project_ids: list[int]) -> str:
        """Résume un batch de projets EcoTaxa sans télécharger les objets.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Pour chaque `project_id`, renvoie un tableau avec :
        - `n_samples` (depuis le cache local)
        - envelope temporelle `date_min` → `date_max` (cache)
        - envelope géographique `bbox` (cache)
        - `instruments` distincts (cache)
        - V (validés), P (prédits), D (douteux), U (non classés) — counts
          project-level via l'endpoint EcoTaxa `/project_set/taxo_stats`
          (1 appel aggregate + 1 appel `taxa_ids=all` pour les top taxa)
        - `top taxa` (jusqu'à 5 noms scientifiques)

        Pendant projet de `summarize_ecotaxa_samples` : utiliser pour
        SCANNER les projets candidats (typiquement le résultat de
        `find_ecotaxa_projects_in_region` ou `list_ecotaxa_projects`) avant
        de drill dans leurs samples ou de lancer un export.

        Projets absents du cache local sont signalés dans la réponse (lancer
        un /admin/resync si nécessaire). Pour un seul projet, utilise
        `summarize_ecotaxa_project`.
        """
        if not project_ids:
            return _eco_blocked("Erreur : project_ids vide.")
        try:
            stats = summarize_projects(project_ids)
        except Exception as exc:
            return _eco_error(
                f"Erreur lors du résumé EcoTaxa : {exc}", retryable=True
            )
        if not stats:
            return _eco_empty(
                "Aucun des projets n'est présent dans le cache local. "
                "Lancer un /admin/resync ou vérifier les IDs."
            )

        lines = [
            "| project_id | n_samples | date_min | date_max | bbox (S/W/N/E) | instruments | V | P | D | U | top taxa | url |",
            "|---:|---:|---|---|---|---|---:|---:|---:|---:|---|---|",
        ]
        for entry in stats:
            bbox = entry.get("bbox") or {}

            def _fmt(value) -> str:
                if isinstance(value, (int, float)):
                    return f"{value:.2f}"
                return "—"

            bbox_cell = (
                f"{_fmt(bbox.get('south'))} / {_fmt(bbox.get('west'))} / "
                f"{_fmt(bbox.get('north'))} / {_fmt(bbox.get('east'))}"
            )
            instruments = ", ".join(entry.get("instruments") or []) or "—"
            names = [t["name"] for t in entry.get("per_taxon", [])[:5]]
            top = ", ".join(names) if names else "—"
            lines.append(
                f"| {entry['project_id']} | {entry['n_samples']} | "
                f"{entry.get('date_min') or '—'} | {entry.get('date_max') or '—'} | "
                f"{bbox_cell} | {instruments} | "
                f"{entry['nb_validated']} | {entry['nb_predicted']} | "
                f"{entry['nb_dubious']} | {entry['nb_unclassified']} | {top} | "
                f"{_ecotaxa_project_url(entry['project_id'])} |"
            )
        returned_ids = {int(entry["project_id"]) for entry in stats}
        missing_ids = [int(pid) for pid in project_ids if int(pid) not in returned_ids]
        if missing_ids:
            lines.extend([
                "",
                "Projets absents du cache local : "
                + ", ".join(str(pid) for pid in missing_ids)
                + ". Lancer `/admin/resync` ou vérifier les IDs si ces projets devraient être indexés.",
            ])
        return _eco_success(
            "\n".join(lines),
            provenance={"project_ids": [int(pid) for pid in project_ids]},
            metrics={"projects": len(stats)},
        )

    @tool(response_format="content_and_artifact")
    def summarize_ecotaxa_project(project_id: int) -> str:
        """Résume UN projet EcoTaxa (n_samples + envelope + V/P/D/U + taxa).

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Variante mono-projet de `summarize_ecotaxa_projects`. Renvoie le
        même tableau réduit à une ligne. Pas de download.
        """
        message = summarize_ecotaxa_projects.invoke({
            "type": "tool_call",
            "id": f"forward-project-{uuid.uuid4().hex}",
            "name": summarize_ecotaxa_projects.name,
            "args": {"project_ids": [project_id]},
        })
        artifact = validate_tool_artifact(message.artifact)
        return message.content, artifact.model_dump(mode="json")

    @tool(response_format="content_and_artifact")
    def export_ecotaxa_samples(
        sample_ids: list[int] | None = None,
        selection_name: str | None = None,
        confirmed: bool = False,
        status: str = "V",
        taxon: str | None = None,
    ) -> str:
        """Exporte une sélection de samples EcoTaxa, multi-projets en 1 appel.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Groupe automatiquement les `sample_ids` par projet (via le cache
        local — pas d'appel API supplémentaire) et lance UN `query_ecotaxa`
        par projet avec le bon sous-ensemble de sample_ids. L'utilisateur
        n'a donc pas besoin de FOURNIR les project_id en entrée — mais ils
        sont systématiquement listés dans la réponse (plan dry-run et
        résumé d'exécution) pour traçabilité.

        `selection_name` peut référencer une sélection mémorisée par
        `find_ecotaxa_samples_in_region` ; `"latest"` / `"cette sélection"`
        reprend la dernière sélection EcoTaxa du fil.

        **Confirmation obligatoire (CT-AG-06)** : `confirmed=False` par
        défaut → renvoie un dry-run montrant le grouping projet → samples
        et demande confirmation. Pour exécuter réellement les exports,
        rappeler avec `confirmed=True`.

        `status` : statut des annotations à exporter — `"V"` (validé),
        `"P"` (prédit), `""` (tous).
        `taxon` : filtre taxonomique optionnel propagé à chaque export.

        Résultat avec `confirmed=True` :
        - succès par projet (n_rows, chemin de téléchargement)
        - échec par projet (réutilise le marker `EXPORT_FAILED` du flux
          single-project, avec code HTTP + message serveur)
        - samples non résolus (absents du cache) listés à part
        """
        resolved_selection_name = None
        normalized = _normalize_sample_ids(sample_ids)
        if not normalized and selection_name:
            resolved_selection_name, normalized = _load_sample_selection(selection_name)
        selection_meta: dict = {}
        if resolved_selection_name:
            selection_entry = _store.get(f"{thread_id}:selection:{resolved_selection_name}")
            selection_meta = dict((selection_entry or {}).get("meta") or {})
        if not normalized:
            if selection_name:
                return _eco_blocked(
                    f"Erreur : sélection `{selection_name}` introuvable ou vide. "
                    "Relance une recherche EcoTaxa ou passe des sample_ids explicites."
                )
            return _eco_blocked("Erreur : sample_ids vide.")

        try:
            mapping = resolve_sample_projects(normalized)
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de la résolution sample→projet : {exc}", retryable=True
            )

        unresolved = [s for s in normalized if s not in mapping]
        groups: dict[int, list[int]] = {}
        for sid, pid in mapping.items():
            groups.setdefault(pid, []).append(sid)

        if not groups:
            return _eco_empty(
                "Aucun des sample_ids fournis n'est présent dans le cache local. "
                f"Samples manquants : {unresolved}. "
                "Lancer un /admin/resync ou vérifier les IDs."
            )

        # Dry-run : montrer le plan, ne pas exécuter.
        if not confirmed:
            try:
                sample_stats = summarize_samples(normalized[:3])
            except Exception:
                sample_stats = []
            _store.update_meta(
                thread_id,
                {
                    "pending_ecotaxa_export_plan": {
                        "sample_ids": normalized,
                        "status": status,
                        "taxon": taxon,
                    }
                },
            )
            lines = [
                f"# Plan d'export — {len(normalized)} samples sur {len(groups)} projets",
            ]
            if resolved_selection_name:
                lines.extend(["", f"Sélection : `{resolved_selection_name}`"])
            if sample_stats:
                lines.extend(["", "Aperçu représentatif de 3 samples ; l'export portera sur toute la sélection.", "", "| sample_id | projet | V | P | D | U | total | taxons dominants |", "|---:|---:|---:|---:|---:|---:|---:|---|"])
                grand = {"V": 0, "P": 0, "D": 0, "U": 0}
                for item in sample_stats:
                    values = {"V": item["nb_validated"], "P": item["nb_predicted"], "D": item["nb_dubious"], "U": item["nb_unclassified"]}
                    total = sum(values.values())
                    top = ", ".join(t["name"] for t in item.get("per_taxon", [])[:3]) or "—"
                    lines.append(f"| {item['sample_id']} | {item['projid']} | {values['V']} | {values['P']} | {values['D']} | {values['U']} | {total} | {top} |")
                    for key, value in values.items(): grand[key] += value
                lines.append(f"| **TOTAL** | — | **{grand['V']}** | **{grand['P']}** | **{grand['D']}** | **{grand['U']}** | **{sum(grand.values())}** | — |")
            lines.extend([
                "",
                "| project_id | nb_samples | sample_ids |",
                "|---:|---:|---|",
            ])
            for pid in sorted(groups):
                sids = groups[pid]
                preview = ", ".join(str(s) for s in sids[:5])
                if len(sids) > 5:
                    preview += f", … (+{len(sids) - 5})"
                lines.append(f"| {pid} | {len(sids)} | {preview} |")
            if unresolved:
                lines.append("")
                lines.append(f"⚠️ {len(unresolved)} samples absents du cache : {unresolved}")
            lines.append("")
            lines.append(
                "Confirmez pour lancer l'export de cette sélection."
            )
            return _eco_blocked(
                "\n".join(lines),
                provenance={"sample_ids": normalized},
                metrics={"projects": len(groups), "samples": len(normalized)},
            )

        # Exécution réelle.
        _store.update_meta(thread_id, {"pending_ecotaxa_export_plan": None})
        successes: list[str] = []
        failures: list[str] = []
        artifact_refs: list[str] = []
        data_refs: list[str] = []
        campaign_frames: list[pd.DataFrame] = []
        total_rows = 0
        for pid in sorted(groups):
            sids = groups[pid]
            filters: dict = {"statusfilter": status}
            if taxon:
                filters.update(_resolve_taxo_filter(taxon))
            filters["samples"] = ",".join(str(s) for s in sids)
            variable_name = dataset_variable_name(
                "ecotaxa", f"{pid}_bulk_{'_'.join(str(s) for s in sids[:3])}"
            )
            try:
                summary, artifact_url, row_count = _download_ecotaxa_export(
                    project_id=pid,
                    filters=filters,
                    variable_name=variable_name,
                    meta={"sample_ids": sids, "bulk": True},
                    label=f"Projet {pid} ({len(sids)} samples)",
                )
                successes.append(f"### ✅ Projet {pid} ({len(sids)} samples)\n\n{summary}")
                artifact_refs.append(artifact_url)
                data_refs.append(variable_name)
                raw_export = _store.get(f"{thread_id}:dataset:{variable_name}")
                if raw_export is not None and isinstance(raw_export.get("df"), pd.DataFrame):
                    campaign_frame = raw_export["df"].copy()
                    # The raw TSV stays unchanged in its project-specific table.
                    # The consolidated analysis table always carries the project
                    # that supplied each object, even when the export schema omits it.
                    campaign_frame["export_project_id"] = int(pid)
                    campaign_frames.append(campaign_frame)
                total_rows += row_count
            except Exception as exc:
                failures.append(_format_export_failure(pid, exc))

        parts = [f"# Bulk export EcoTaxa — {len(groups)} projets traités"]
        if successes:
            parts.append("\n\n".join(successes))
        if failures:
            parts.append("## Échecs\n\n" + "\n\n---\n\n".join(failures))
        if unresolved:
            parts.append(f"⚠️ Samples absents du cache (non exportés) : {unresolved}")
        summary = "\n\n".join(parts)
        if not successes:
            return _eco_error(
                summary,
                provenance={"sample_ids": normalized},
                retryable=True,
                method="EcoTaxa bulk export",
                metrics={"projects_failed": len(failures)},
            )
        campaign_label = resolved_selection_name or "samples_" + "_".join(
            str(sample_id) for sample_id in normalized[:3]
        )
        campaign_variable = dataset_variable_name(
            "ecotaxa", "campaign", campaign_label, uuid.uuid4().hex[:8]
        )
        campaign_df = pd.concat(campaign_frames, ignore_index=True, sort=False)
        store_dataset(
            _store,
            thread_id,
            campaign_df,
            variable_name=campaign_variable,
            latest_alias=ECOTAXA,
            meta={
                "source": "ecotaxa_export_campaign",
                "selection_name": resolved_selection_name,
                "selection_filters": selection_meta.get("filters") or {},
                "export_project_ids": sorted(groups),
                "raw_export_variables": data_refs,
                "n_rows": len(campaign_df),
                "n_projects": len(campaign_frames),
                "description": (
                    f"Export EcoTaxa consolidé : {len(normalized)} samples, "
                    f"projets={','.join(str(project) for project in sorted(groups))}, "
                    f"statut={status or 'tous'}, "
                    f"taxon={taxon or 'tous'}"
                    + (", " + ", ".join(
                        f"{key}={value}"
                        for key, value in (selection_meta.get("filters") or {}).items()
                    ) if selection_meta.get("filters") else "")
                ),
            },
        )
        summary += (
            f"\n\nTable de campagne consolidée : `{campaign_variable}` "
            f"({len(campaign_df)} lignes, {len(campaign_frames)} projets) — "
            "table active pour l'analyse et les graphes."
        )
        return _eco_success(
            summary,
            data_ref=campaign_variable,
            artifact_refs=tuple(artifact_refs),
            provenance={"sample_ids": normalized},
            persisted=True,
            method="EcoTaxa bulk export",
            metrics={
                "projects_succeeded": len(successes),
                "projects_failed": len(failures),
                "rows": total_rows,
            },
        )

    @tool(response_format="content_and_artifact")
    def list_ecotaxa_cache_tables() -> str:
        """Liste les tables du cache SQLite EcoTaxa avec leur nombre de lignes.

        Point d'entrée de l'exploration SQL : appeler en premier pour savoir
        quelles tables sont disponibles. Retourne nom, nombre de lignes indexées
        et description de chaque table.

        Suivi naturel : `describe_ecotaxa_cache_table` pour le schéma exact,
        puis `query_ecotaxa_cache` pour un SELECT libre.
        """
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            tables = _sql_explorer.list_tables(conn)
            conn.close()
        except Exception as exc:
            return _eco_error(f"Erreur lecture cache : {exc}", retryable=True)

        lines = [
            "## Tables du cache EcoTaxa",
            "",
            "| table | lignes | description |",
            "|---|---:|---|",
        ]
        for t in tables:
            count = t["rows"] if t["rows"] is not None else "—"
            lines.append(f"| `{t['table']}` | {count} | {t['description']} |")
        lines += [
            "",
            "Utiliser `describe_ecotaxa_cache_table` pour le schéma, "
            "puis `query_ecotaxa_cache(sql=...)` pour un SELECT libre.",
        ]
        return _eco_success("\n".join(lines), metrics={"tables": len(tables)})

    @tool(response_format="content_and_artifact")
    def describe_ecotaxa_cache_table(table_name: str) -> str:
        """Retourne le schéma complet (colonnes, types, index) d'une table du cache EcoTaxa.

        À utiliser avant un SELECT précis pour vérifier les noms exacts de
        colonnes et leurs types. `table_name` est l'un des noms retournés par
        `list_ecotaxa_cache_tables`.

        Paire naturelle avec `list_ecotaxa_cache_tables` et `query_ecotaxa_cache`.
        """
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            result = _sql_explorer.describe_table(conn, table_name)
            conn.close()
        except Exception as exc:
            return _eco_error(f"Erreur lecture cache : {exc}", retryable=True)

        if not result.get("ok"):
            return _eco_blocked(result.get("error", "Table inconnue."))

        lines = [
            f"## Table `{table_name}`",
            "",
            result["description"],
            "",
            "### Colonnes",
            "",
            "| # | colonne | type | not null | PK |",
            "|---:|---|---|:---:|:---:|",
        ]
        for col in result["columns"]:
            nn = "✓" if col["notnull"] else ""
            pk = "✓" if col["pk"] else ""
            lines.append(
                f"| {col['cid']} | `{col['name']}` | {col['type']} | {nn} | {pk} |"
            )
        if result["indexes"]:
            lines += ["", "### Index", "", "| nom | unique |", "|---|:---:|"]
            for idx in result["indexes"]:
                lines.append(f"| `{idx['name']}` | {'✓' if idx['unique'] else ''} |")
        return _eco_success(
            "\n".join(lines), metrics={"columns": len(result["columns"])}
        )

    @tool(response_format="content_and_artifact")
    def query_ecotaxa_cache(sql: str) -> str:
        """Exécute un SELECT libre sur le cache SQLite EcoTaxa local.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Outil central d'exploration : écrire directement le SELECT voulu.
        Remplace tout pattern nécessitant plusieurs appels ou un export pour
        un comptage, regroupement ou filtrage arbitraire.

        Explorer les objets : la table `objects_cache` (indexée dans les caches
        enrichis) permet d'agréger les objets par taxon, statut, sample, date ou
        profondeur en SQL — vérifie sa présence avec `describe_ecotaxa_cache_table`
        avant, car elle est absente d'un cache non enrichi. Si elle est absente,
        le cache ne connaît des objets que des agrégats (`samples_cache.object_count`,
        `project_signatures_cache.pctvalidated`), et le détail objet par objet passe
        par le chemin live `list_ecotaxa_sample_objects` / `get_ecotaxa_object`.

        Seuls les SELECT sont autorisés. Aucun LIMIT n'est ajouté par défaut :
        le résultat complet est conservé dans `df_ecotaxa_cache_query`. Ajouter
        un LIMIT uniquement si l'utilisateur demande explicitement un aperçu,
        un top ou une pagination.

        Zones nommées — règle stricte : pour une baie / mer / détroit / zone
        nommée, tu DOIS d'abord appeler `get_zone_info(zone_name=...)` et
        réutiliser sa `bbox` dans `WHERE lat_avg BETWEEN … AND lon_avg BETWEEN
        …`. N'écris JAMAIS de bornes lat/lon littérales de mémoire : des
        coordonnées inventées donnent des comptages faux ou vides. Sans nom de
        zone (bbox numérique déjà fournie), filtre directement.

        Utiliser `list_ecotaxa_cache_tables` pour découvrir les tables
        et `describe_ecotaxa_cache_table` pour leur schéma exact.

        ## Tables disponibles

        **samples_cache** — index spatio-temporel principal
        | colonne | type | contenu |
        |---|---|---|
        | sample_id | INTEGER PK | identifiant EcoTaxa |
        | project_id | INTEGER | projet parent |
        | lat_avg / lon_avg | REAL | centre du sample |
        | date_min / date_max | TEXT | YYYY-MM-DD |
        | depth_min / depth_max | REAL | profondeurs (m) |
        | original_id | TEXT | label complet (ex. am_leg4_RA76_1) |
        | station_id | TEXT | station (ex. RA76, St-27), jamais le cast |
        | profile_id | TEXT | identifiant du cast/profil |
        | object_count | INTEGER | objets imagés |
        | instrument | TEXT | UVP6, UVP5SD, Loki, … |

        **objects_cache** — index objet optionnel pour les agrégations détaillées
        | colonne | contenu |
        |---|---|
        | object_id / sample_id / project_id | identifiants objet et parent |
        | taxon / classification_status | classification et statut d'annotation (`V` = validé) |
        | date / depth | date et profondeur objet |

        **project_schemas_cache** — schémas JSON des projets
        | project_id PK | schema_json (title, instrument, levels, free fields) |

        **project_signatures_cache** — stats de classification
        | project_id PK | objcount | pctvalidated | pctclassified |

        **sync_runs** — historique des synchronisations
        | run_id PK | started_at | ended_at | status | projects_synced | samples_synced | error_message |

        ## Exemples
        ```sql
        -- Samples par station (cross-project)
        SELECT sample_id, project_id, original_id, station_id, date_min, depth_max
        FROM samples_cache WHERE station_id LIKE '%RA76%' ORDER BY date_min

        -- Casts : toujours profile_id, jamais station_id
        SELECT profile_id AS cast_id, COUNT(DISTINCT sample_id) AS n_samples
        FROM samples_cache
        WHERE profile_id IS NOT NULL AND TRIM(profile_id) <> ''
        GROUP BY profile_id ORDER BY n_samples DESC, cast_id

        -- Instruments dans une bbox
        SELECT instrument, COUNT(*) AS n, COUNT(DISTINCT project_id) AS n_projets
        FROM samples_cache
        WHERE lat_avg BETWEEN 60 AND 80 AND lon_avg BETWEEN -80 AND -40
        GROUP BY instrument ORDER BY n DESC

        -- Tableau croisé projet × année
        SELECT project_id, substr(date_min,1,4) AS year, COUNT(*) AS n
        FROM samples_cache GROUP BY project_id, year ORDER BY project_id, year

        -- Statut du dernier sync
        SELECT status, started_at, ended_at, samples_synced
        FROM sync_runs ORDER BY run_id DESC LIMIT 1

        -- Projets avec % validé
        SELECT project_id, objcount, pctvalidated, pctclassified
        FROM project_signatures_cache ORDER BY pctvalidated DESC
        ```
        """
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            # Keep the complete SELECT result in the persisted DataFrame. The
            # response below may show a compact preview, but it is not data loss.
            result = _sql_explorer.run_select(conn, sql, cap=None)
            conn.close()
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de l'exécution SQL sur le cache EcoTaxa : {exc}",
                retryable=False,
            )

        if not result.get("ok"):
            return _eco_blocked(result["error"])

        rows = result["rows"]
        columns = result["columns"]
        truncated = result["truncated"]

        if not rows:
            return _eco_empty("La requête n'a retourné aucune ligne.")

        dataframe = pd.DataFrame.from_records(rows, columns=columns)
        variable_name = "df_ecotaxa_cache_query"
        store_dataset(
            _store,
            thread_id,
            dataframe,
            variable_name=variable_name,
            meta={
                "source": "ecotaxa_cache",
                "sql": sql,
                "n_rows": len(dataframe),
                "n_cols": len(dataframe.columns),
                "truncated": truncated,
            },
        )

        # Campagne → export : dès qu'une exploration SQL renvoie des `sample_id`,
        # la mémoriser comme sélection exportable (`latest`). N'importe quelle
        # campagne (zone + temps + taxon…) devient ainsi exportable directement
        # via `export_ecotaxa_samples(selection_name="latest")`, sans que le
        # modèle ait à ré-extraire les identifiants à la main.
        selection_note = ""
        if "sample_id" in dataframe.columns:
            id_series = pd.to_numeric(dataframe["sample_id"], errors="coerce").dropna()
            sids = [int(s) for s in dict.fromkeys(id_series.tolist())]
            selection_samples: list[dict] = []
            if sids and "project_id" in dataframe.columns:
                pairs = dataframe[["sample_id", "project_id"]].dropna().drop_duplicates()
                for row in pairs.itertuples(index=False):
                    try:
                        selection_samples.append(
                            {"sample_id": int(row.sample_id), "project_id": int(row.project_id)}
                        )
                    except (TypeError, ValueError):
                        continue
            elif sids:
                # project_id absent du SELECT → le résoudre depuis le cache.
                try:
                    mapping = resolve_sample_projects(sids)
                except Exception:
                    mapping = {}
                selection_samples = [
                    {"sample_id": int(s), "project_id": int(p)} for s, p in mapping.items()
                ]
            if selection_samples:
                try:
                    # Register only the selection METADATA (sample/project ids)
                    # for export — never rebuild/overwrite the active dataframe,
                    # which must stay the exact SQL result the campaign returned.
                    sel_sample_ids = [int(s["sample_id"]) for s in selection_samples]
                    sel_project_ids = sorted({int(s["project_id"]) for s in selection_samples})
                    sel_name = _selection_name()
                    sel_meta = {
                        "selection_name": sel_name,
                        "sample_ids": sel_sample_ids,
                        "project_ids": sel_project_ids,
                        "n_samples": len(sel_sample_ids),
                        "filters": {"sql": sql},
                        "source": "ecotaxa_selection",
                    }
                    _store.set(f"{thread_id}:selection:{sel_name}", None, sel_meta)
                    _store.set(f"{thread_id}:ecotaxa_selection_latest", None, sel_meta)
                    selection_note = (
                        f"\n\nLa sélection complète de {len(sel_sample_ids)} samples est conservée "
                        "pour l’analyse ou l’export."
                    )
                except Exception:
                    selection_note = ""

        header = "| " + " | ".join(columns) + " |"
        separator = "|" + "|".join("---" for _ in columns) + "|"
        preview_rows = rows[:10] if "sample_id" in columns else rows[:50]
        data_lines = [
            "| " + " | ".join(
                str(row[c]) if row[c] is not None else "—" for c in columns
            ) + " |"
            for row in preview_rows
        ]
        note = (
            f"\n_(aperçu de 50 lignes sur {len(rows)} ; résultat complet dans "
            "`df_ecotaxa_cache_query`)_"
            if len(rows) > len(preview_rows) else ""
        )
        if truncated:
            note += "\n_(le plafond explicite du lecteur SQL a tronqué ce résultat)_"
        displayed = len(preview_rows)
        display_label = (
            f"toutes les {displayed} lignes"
            if displayed == len(rows)
            else f"aperçu : {displayed} sur {len(rows)} lignes"
        )
        selection_overview: list[str] = []
        if "sample_id" in dataframe.columns:
            projects = dataframe["project_id"].dropna().nunique() if "project_id" in dataframe.columns else "—"
            dates = (
                pd.to_datetime(dataframe["date_min"], errors="coerce")
                if "date_min" in dataframe.columns
                else pd.Series(dtype="datetime64[ns]")
            )
            depth_series = [
                pd.to_numeric(dataframe[column], errors="coerce")
                for column in ("depth_min", "depth_max")
                if column in dataframe.columns
            ]
            depths = pd.concat(depth_series).dropna() if depth_series else pd.Series(dtype=float)
            instruments = ", ".join(sorted(map(str, dataframe.get("instrument", pd.Series(dtype=str)).dropna().unique()))) or "—"
            zones = ", ".join(sorted(map(str, dataframe.get("iho_zone", pd.Series(dtype=str)).dropna().unique()))) or "—"
            selection_overview = [
                "## Synthèse de la sélection complète", "",
                f"{dataframe['sample_id'].nunique()} samples · {projects} projets · zones : {zones}.",
                f"Période : {dates.min().date() if not dates.dropna().empty else '—'} → {dates.max().date() if not dates.dropna().empty else '—'} · instruments : {instruments}.",
                f"Profondeur couverte : {depths.min():.2f} → {depths.max():.2f} m." if not depths.empty else "Profondeur : —.",
                "",
            ]
        summary = [
            "## Résultat SQL EcoTaxa",
            "",
            "| lignes retournées | colonnes | affichage |",
            "|---:|---:|---|",
            f"| {len(rows)} | {len(columns)} | {display_label} |",
            "",
        ]
        body = "\n".join([*selection_overview, *summary, header, separator, *data_lines]) + note + selection_note
        return _eco_success(
            body,
            data_ref=variable_name,
            persisted=True,
            metrics={"rows": len(rows), "truncated": truncated},
        )

    return [
        find_ecotaxa_projects,
        find_ecotaxa_samples_in_region,
        combine_ecotaxa_selections,
        group_ecotaxa_samples_by_year,
        find_ecotaxa_projects_in_region,
        group_ecotaxa_project_samples_by_region,
        rank_ecotaxa_samples_by_region,
        find_ecotaxa_observations,
        get_ecotaxa_sample,
        list_ecotaxa_sample_objects,
        get_ecotaxa_object,
        summarize_ecotaxa_sample_deployment,
        inspect_ecotaxa_project_schema,
        inspect_ecotaxa_column,
        count_ecotaxa_taxa,
        search_ecotaxa_taxa,
        describe_ecotaxa_project_coverage,
        compare_ecotaxa_projects,
        list_ecotaxa_projects,
        list_ecotaxa_campaigns,
        resolve_ecotaxa_sample,
        audit_ecotaxa_spatial_coverage,
        preview_ecotaxa_project,
        query_ecotaxa,
        query_ecotaxa_sample,
        summarize_ecotaxa_sample,
        summarize_ecotaxa_samples,
        summarize_ecotaxa_project,
        summarize_ecotaxa_projects,
        export_ecotaxa_samples,
        list_ecotaxa_cache_tables,
        describe_ecotaxa_cache_table,
        query_ecotaxa_cache,
    ]
