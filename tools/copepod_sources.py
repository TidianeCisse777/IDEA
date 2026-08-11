"""tools/copepod_sources.py — LangChain tools pour accès EcoTaxa/EcoPart."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import unicodedata
import uuid
from pathlib import Path

import pandas as pd
import requests
from langchain_core.tools import tool

from core.ecotaxa_browser.region import (
    resolve_sample_projects,
)
from core.ecotaxa_browser.sample_summary import summarize_samples
from core.ecotaxa_browser.taxonomy import search_taxa
from core.ecotaxa_browser.cache.repo import (
    init_schema,
    open_connection,
    open_readonly_connection,
    query_samples_filtered,
)
from core.ecotaxa_browser.cache import sql_explorer as _sql_explorer
from core.ecotaxa_browser.cache.dataframe_bridge import (
    DATAFRAME_TABLE_PATTERN,
    open_dataframe_cache_workspace,
)
from core.scientific_result_cache import (
    build_result_cache_key,
    load_result,
    save_result,
)

_ZONES_REGISTRY_PATH = (
    Path(__file__).parent.parent / "data" / "geo" / "zones_registry.geojson"
)
from tools.ecotaxa_client import EcotaxaClient, EcotaxaExportError
from tools.dataset_registry import (
    ECOTAXA,
    dataset_variable_name,
    store_dataset,
)
from tools.public_url import download_url
from tools.session_store import default_store as _store
from tools.data_tools import _uvp_skill_hint
from tools.tool_result import blocked, empty, error, success

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)

_LOGGER = logging.getLogger(__name__)

_ECOTAXA_UI_BASE = "https://ecotaxa.obs-vlfr.fr"


def _net_dataframe_fingerprint(dataframe: pd.DataFrame) -> str:
    """Return a stable content-and-schema identity for a persisted net table."""
    schema = repr(
        (
            dataframe.shape,
            tuple(map(str, dataframe.columns)),
            tuple(map(str, dataframe.dtypes)),
            str(dataframe.index.dtype),
        )
    )
    row_hashes = pd.util.hash_pandas_object(
        dataframe,
        index=True,
        categorize=False,
        hash_key="copepodnetfp0001",
    )
    digest = hashlib.sha256()
    digest.update(schema.encode("utf-8"))
    digest.update(b"\x1e")
    for row_hash in row_hashes:
        digest.update(int(row_hash).to_bytes(8, byteorder="big", signed=False))
    return f"sha256:{digest.hexdigest()}"


def _zone_grouping_requires_reference(sql: str) -> bool:
    """True when a cache aggregation would mix IHO and MEOW zone labels."""
    group_by = re.search(
        r"\bgroup\s+by\s+(.*?)(?:\border\s+by\b|\blimit\b|;|$)",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if group_by is None:
        return False
    grouped_columns = group_by.group(1).lower()
    return "iho_zone" in grouped_columns and "zone_reference" not in grouped_columns


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
            suggestion = (
                "Diagnostic suggéré : vérifier l'identifiant du projet et les "
                "droits d'export du compte EcoTaxa configuré."
            )
        elif status_code == 404:
            cause = (
                f"Cause : projet introuvable côté EcoTaxa (HTTP 404). "
                "Soit l'identifiant n'existe pas, soit il n'est plus exposé."
            )
            suggestion = "Diagnostic suggéré : vérifier l'identifiant dans le cache EcoTaxa local."
        else:
            cause = (
                "Cause : erreur EcoTaxa inattendue — droits manquants, "
                "projet privé, identifiants invalides, ou paramètres refusés."
            )
            suggestion = "Diagnostic suggéré : vérifier l'identifiant et les droits EcoTaxa."

        return (
            f"EXPORT_FAILED — {target} ({status})\n"
            f"Message serveur : {server}\n"
            f"{cause}\n"
            f"{suggestion} Une recherche dans le cache ne remplace pas un export."
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

    def _persistent_cache_selection_identity(
        *,
        sql: str,
        sample_ids: list[int],
        requested_name: str | None,
    ) -> tuple[str, str, str]:
        """Return stable selection, dataframe and human label identifiers."""

        compact_sql = " ".join(str(sql).split())
        label = str(requested_name or "samples").strip() or "samples"
        slug = _slug_part(label)[:48] or "samples"
        digest_source = compact_sql + "\n" + ",".join(
            str(int(sample_id)) for sample_id in sample_ids
        )
        short_id = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:8]
        selection_key = f"selection_{slug}_{short_id}"
        variable_name = dataset_variable_name(
            "ecotaxa", "selection", slug, short_id
        )
        return selection_key, variable_name, label

    def _persistent_cache_result_identity(
        *,
        sql: str,
        requested_name: str | None,
        description: str | None,
        dataframe_refs: tuple[str, ...],
    ) -> tuple[str, str]:
        """Return a stable name for one non-exportable SQL result shape."""

        compact_sql = " ".join(str(sql).split())
        label = str(requested_name or description or "query").strip() or "query"
        slug = _slug_part(label)[:48] or "query"
        digest_source = compact_sql + "\n" + ",".join(dataframe_refs)
        short_id = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:8]
        variable_name = dataset_variable_name(
            "ecotaxa", "cache", "result", slug, short_id
        )
        return variable_name, label

    def _store_sample_selection(
        *,
        name: str,
        samples: list[dict],
        filters: dict,
        source: str = "ecotaxa_selection",
        extra_meta: dict | None = None,
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
            "source": source,
            **(extra_meta or {}),
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

        def _sample_ids_from_dataframe(dataframe: object) -> list[int]:
            if not isinstance(dataframe, pd.DataFrame):
                return []
            if "sample_id" in dataframe.columns:
                return _normalize_sample_ids(dataframe["sample_id"].tolist())
            if "profile_id" not in dataframe.columns:
                return []

            profiles = [
                str(value).strip()
                for value in dataframe["profile_id"].dropna().tolist()
                if str(value).strip()
            ]
            profiles = list(dict.fromkeys(profiles))
            if not profiles:
                return []

            cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
            placeholders = ", ".join("?" for _ in profiles)
            conn = None
            try:
                conn = open_readonly_connection(cache_db)
                rows = conn.execute(
                    f"SELECT sample_id FROM samples_cache "
                    f"WHERE TRIM(profile_id) IN ({placeholders}) "
                    "ORDER BY sample_id",
                    profiles,
                ).fetchall()
                return _normalize_sample_ids([row["sample_id"] for row in rows])
            except Exception:
                return []
            finally:
                if conn is not None:
                    conn.close()

        def _dataset_sample_ids(dataframe: object) -> list[int]:
            return _sample_ids_from_dataframe(dataframe)

        if key.lower() in {
            "latest", "last", "current", "cette sélection", "cette selection",
            "dernière sélection", "derniere selection",
        }:
            session = _store.get(f"{thread_id}:ecotaxa_selection_latest")
        else:
            session = _store.get(f"{thread_id}:selection:{key}")
            # Cache queries expose a canonical key prefixed with ``selection_``.
            # Models occasionally preserve the stable slug and digest but omit
            # that mechanical prefix. Resolve that exact, unambiguous alias from
            # the current selection instead of discarding a persisted scope.
            if not session and not key.startswith("selection_"):
                latest = _store.get(f"{thread_id}:ecotaxa_selection_latest")
                latest_meta = (latest or {}).get("meta") or {}
                latest_name = str(latest_meta.get("selection_name") or "")
                latest_alias = latest_name.removeprefix("selection_")
                # The user-facing name is the stable slug.  The digest only
                # disambiguates storage; requiring the model to reproduce it
                # makes an otherwise valid current selection impossible to
                # export.  Resolve a slug prefix only against *latest*, so it
                # cannot select an older or unrelated scope.
                if (
                    latest_alias == key
                    or latest_alias.startswith(f"{key}_")
                ):
                    session = latest
            # A saved selection is the current export scope.  Do not make a
            # generated storage name a user-facing precondition: when a name
            # is stale, shortened or otherwise unresolvable, reuse `latest`.
            # The returned resolved name still records exactly what was used.
            if not session:
                latest = _store.get(f"{thread_id}:ecotaxa_selection_latest")
                latest_ids = ((latest or {}).get("meta") or {}).get("sample_ids")
                if latest_ids:
                    session = latest
        if not session:
            # A transparent pandas subset is a valid export scope when it
            # explicitly carries EcoTaxa sample identifiers.  This keeps a
            # user-selected/derived subset reusable without requiring a second
            # source search merely to turn it back into a named selection.
            dataset = _store.get(f"{thread_id}:dataset:{key}")
            dataframe = (dataset or {}).get("df")
            dataset_ids = _dataset_sample_ids(dataframe)
            if dataset_ids:
                return key, dataset_ids

            # A profile map or a pandas subset may be the current export scope
            # even though the model supplied a display label rather than the
            # generated dataframe variable.  Resolve it from the active table
            # when it exposes EcoTaxa profile identifiers.
            for active_key in (
                f"{thread_id}:ecotaxa",
                thread_id,
                f"{thread_id}:last_plot_df",
            ):
                active = _store.get(active_key)
                active_ids = _dataset_sample_ids((active or {}).get("df"))
                if active_ids:
                    active_name = str(
                        ((active or {}).get("meta") or {}).get("variable_name")
                        or key
                    )
                    return active_name, active_ids
            return key, []
        meta = session.get("meta") or {}
        resolved_name = str(meta.get("selection_name") or key)
        return resolved_name, _normalize_sample_ids(meta.get("sample_ids"))


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
            meta={
                **meta,
                "source": f"ecotaxa:{project_id}",
                "project_id": project_id,
                "n_rows": len(df),
                "grain": "one row per exported EcoTaxa object",
                "description": (
                    f"{label}: object-level EcoTaxa export preserving sample, "
                    "profile, taxonomy and acquisition fields."
                ),
            },
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
    def export_ecotaxa_samples(
        sample_ids: list[int] | None = None,
        selection_name: str | None = None,
        confirmed: bool = True,
        status: str = "V",
        taxon: str | None = None,
    ) -> str:
        """Exporte une sélection de samples EcoTaxa, multi-projets en 1 appel.

        EcoTaxa navigation is already pre-activated with this source family;
        call this tool directly and never reload the skill in a later turn.

        Groupe automatiquement les `sample_ids` par projet (via le cache
        local — pas d'appel API supplémentaire) et lance UN `query_ecotaxa`
        par projet avec le bon sous-ensemble de sample_ids. L'utilisateur
        n'a donc pas besoin de FOURNIR les project_id en entrée — mais ils
        sont systématiquement listés dans la réponse (plan dry-run et
        résumé d'exécution) pour traçabilité.

        `selection_name` peut référencer une sélection EcoTaxa persistée ;
        `"latest"` / `"cette sélection"` reprend la dernière sélection du fil.
        Un DataFrame persistant
        contenant `sample_id` ou `profile_id` est également accepté ; les
        profils sont résolus automatiquement vers leurs samples dans le cache.

        L'export démarre directement par défaut. `confirmed=False` reste
        disponible uniquement pour demander un préflight explicite, sans
        télécharger les objets.

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
                latest_selection = _store.get(f"{thread_id}:ecotaxa_selection_latest")
                latest_meta = dict((latest_selection or {}).get("meta") or {})
                if latest_meta.get("source") == "net_uvp_empty_selection":
                    return _eco_blocked(
                        "Aucune correspondance validée à exporter : l’audit n’a trouvé "
                        "aucun match utilisable pour la jointure."
                    )
                return _eco_blocked(
                    f"Erreur : la sélection `{selection_name}` ne contient aucun "
                    "sample EcoTaxa exportable."
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
                # One light batch request covers the complete selection.  A
                # three-sample preview cannot certify that every requested
                # project actually contains objects for the requested status.
                sample_stats = summarize_samples(normalized)
            except Exception:
                sample_stats = []
            stats_by_sample = {
                int(item["sample_id"]): item for item in sample_stats
                if item.get("sample_id") is not None
            }
            status_code = str(status or "").strip().upper()
            status_field = {
                "V": "nb_validated",
                "P": "nb_predicted",
                "D": "nb_dubious",
                "U": "nb_unclassified",
                "N": "nb_unclassified",
            }.get(status_code)
            status_label = {
                "V": "validé",
                "P": "prédit",
                "D": "douteux",
                "U": "non classé",
                "N": "non classé",
            }.get(status_code, "tous statuts")
            project_preflight: dict[int, dict[str, object]] = {}
            for pid, sids in groups.items():
                available = [stats_by_sample[sid] for sid in sids if sid in stats_by_sample]
                if status_field is None:
                    object_count = sum(
                        int(item.get(field) or 0)
                        for item in available
                        for field in (
                            "nb_validated", "nb_predicted", "nb_dubious",
                            "nb_unclassified",
                        )
                    )
                else:
                    object_count = sum(
                        int(item.get(status_field) or 0) for item in available
                    )
                if len(available) != len(sids):
                    verdict = "PARTIEL"
                    diagnostic = (
                        f"statut vérifié pour {len(available)}/{len(sids)} samples"
                    )
                elif object_count <= 0:
                    verdict = "BLOQUÉ"
                    diagnostic = f"aucun objet {status_label} à exporter"
                else:
                    verdict = "PRÊT"
                    diagnostic = f"{object_count} objet(s) {status_label}(s) exportable(s)"
                project_preflight[int(pid)] = {
                    "verdict": verdict,
                    "object_count": int(object_count),
                    "diagnostic": diagnostic,
                }
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
                f"# Préflight d'export — {len(normalized)} samples sur {len(groups)} projets",
            ]
            if resolved_selection_name:
                lines.extend(["", f"Sélection : `{resolved_selection_name}`"])
            if sample_stats:
                lines.extend(["", "Contrôle de tous les samples de la sélection.", "", "| sample_id | projet | V | P | D | U | total | taxons dominants |", "|---:|---:|---:|---:|---:|---:|---:|---|"])
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
                "| project_id | statut | nb_samples | objets demandés | diagnostic | sample_ids |",
                "|---:|---|---:|---:|---|---|",
            ])
            for pid in sorted(groups):
                sids = groups[pid]
                preflight = project_preflight[pid]
                preview = ", ".join(str(s) for s in sids[:5])
                if len(sids) > 5:
                    preview += f", … (+{len(sids) - 5})"
                lines.append(
                    f"| {pid} | {preflight['verdict']} | {len(sids)} | "
                    f"{preflight['object_count']} | {preflight['diagnostic']} | {preview} |"
                )
            if unresolved:
                lines.append("")
                lines.append(f"⚠️ {len(unresolved)} samples absents du cache : {unresolved}")
            lines.append("")
            ready_projects = sum(
                item["verdict"] == "PRÊT" for item in project_preflight.values()
            )
            lines.append(
                f"Préflight : {ready_projects}/{len(groups)} projets exportables."
            )
            if ready_projects:
                lines.append("Confirmez pour lancer l'export des projets indiqués.")
            else:
                lines.append("Export non confirmable : aucun projet n'est prêt.")
            return _eco_blocked(
                "\n".join(lines),
                provenance={"sample_ids": normalized},
                metrics={
                    "projects": len(groups),
                    "projects_ready": ready_projects,
                    "projects_blocked": sum(
                        item["verdict"] == "BLOQUÉ"
                        for item in project_preflight.values()
                    ),
                    "samples": len(normalized),
                },
            )

        # Exécution réelle.
        _store.update_meta(thread_id, {"pending_ecotaxa_export_plan": None})
        cache_source = pd.DataFrame(
            [
                {
                    "sample_id": int(sample_id),
                    "project_id": int(mapping[sample_id]) if sample_id in mapping else None,
                    "resolved": sample_id in mapping,
                }
                for sample_id in normalized
            ]
        )
        cache_key = build_result_cache_key(
            cache_source,
            {
                "status": status,
                "taxon": taxon,
                "selection_name": resolved_selection_name,
                "selection_filters": selection_meta.get("filters") or {},
                "requested_projects": sorted(groups),
            },
        )
        cached = load_result("ecotaxa_export", cache_key)
        if cached is not None:
            campaign_label = resolved_selection_name or "samples_" + "_".join(
                str(sample_id) for sample_id in normalized[:3]
            )
            campaign_variable = dataset_variable_name(
                "ecotaxa", "campaign", campaign_label, uuid.uuid4().hex[:8]
            )
            cached_df = cached.dataframe
            meta = {
                "source": "ecotaxa_export_campaign",
                "selection_name": resolved_selection_name,
                "selection_filters": selection_meta.get("filters") or {},
                "export_project_ids": sorted(groups),
                "requested_project_ids": sorted(groups),
                "failed_project_ids": [],
                "requested_samples": len(normalized),
                "exported_samples": len(normalized),
                "partial_export": False,
                "raw_export_variables": [],
                "n_rows": len(cached_df),
                "n_cols": len(cached_df.columns),
                "n_projects": len(groups),
                "grain": "one row per exported EcoTaxa object",
                "cache_hit": True,
                "cached_at": cached.cached_at,
                "cache_provenance": cached.provenance,
                "description": (
                    "Export EcoTaxa complet restauré depuis le cache exact; "
                    f"statut={status or 'tous'}, taxon={taxon or 'tous'}"
                ),
            }
            store_dataset(
                _store,
                thread_id,
                cached_df,
                variable_name=campaign_variable,
                latest_alias=ECOTAXA,
                meta=meta,
            )
            return _eco_success(
                "Export EcoTaxa restauré depuis le cache exact — "
                f"{len(cached_df)} lignes, {len(normalized)} samples et "
                f"{len(groups)} projets; aucune ligne écartée. "
                f"Table active : `{campaign_variable}` (récupérée le {cached.cached_at}).",
                data_ref=campaign_variable,
                provenance={"sample_ids": normalized, **cached.provenance},
                persisted=True,
                method="Cached exact EcoTaxa bulk export",
                metrics={
                    "projects_succeeded": len(groups),
                    "projects_failed": 0,
                    "samples_requested": len(normalized),
                    "samples_exported": len(normalized),
                    "partial_export": False,
                    "rows": len(cached_df),
                    "cache_hit": True,
                },
            )
        successes: list[str] = []
        failures: list[str] = []
        artifact_refs: list[str] = []
        data_refs: list[str] = []
        campaign_frames: list[pd.DataFrame] = []
        succeeded_project_ids: list[int] = []
        failed_project_ids: list[int] = []
        exported_samples = 0
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
                succeeded_project_ids.append(pid)
                exported_samples += len(sids)
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
                failed_project_ids.append(pid)
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
        partial_export = bool(failures or unresolved)
        coverage = (
            f"Export EcoTaxa {'partiel' if partial_export else 'complet'} : "
            f"{exported_samples}/{len(normalized)} samples, "
            f"projets réussis={','.join(str(project) for project in succeeded_project_ids) or 'aucun'}"
        )
        if failed_project_ids:
            coverage += ", projets en échec=" + ",".join(
                str(project) for project in failed_project_ids
            )
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
                "export_project_ids": succeeded_project_ids,
                "requested_project_ids": sorted(groups),
                "failed_project_ids": failed_project_ids,
                "requested_samples": len(normalized),
                "exported_samples": exported_samples,
                "partial_export": partial_export,
                "raw_export_variables": data_refs,
                "n_rows": len(campaign_df),
                "n_cols": len(campaign_df.columns),
                "n_projects": len(campaign_frames),
                "grain": "one row per exported EcoTaxa object",
                "cache_hit": False,
                "cached_at": None,
                "description": (
                    coverage + "; "
                    f"statut={status or 'tous'}, "
                    f"taxon={taxon or 'tous'}"
                    + (", " + ", ".join(
                        f"{key}={value}"
                        for key, value in (selection_meta.get("filters") or {}).items()
                    ) if selection_meta.get("filters") else "")
                ),
            },
        )
        if not partial_export:
            saved = save_result(
                "ecotaxa_export",
                cache_key,
                campaign_df,
                provenance={
                    "source": "EcoTaxa",
                    "project_ids": succeeded_project_ids,
                    "sample_ids": normalized,
                    "status": status,
                    "taxon": taxon,
                },
            )
            cache_meta = {
                "cache_hit": False,
                "cached_at": saved.cached_at,
                "cache_provenance": saved.provenance,
            }
            for store_key in (
                thread_id,
                f"{thread_id}:{ECOTAXA}",
                f"{thread_id}:dataset:{campaign_variable}",
            ):
                _store.update_meta(store_key, cache_meta)
        summary += (
            f"\n\nTable de campagne consolidée : `{campaign_variable}` "
            f"({len(campaign_df)} lignes, {len(campaign_frames)}/{len(groups)} projets réussis) — "
            "table active pour l'analyse et les graphes."
        )
        audit_lines = [
            "## État des lieux d'export",
            "",
            (
                f"- portée demandée : {len(normalized)} samples sur {len(groups)} projets "
                f"(statut={status or 'tous'}, taxon={taxon or 'tous'})"
            ),
            (
                f"- portée exportée : {exported_samples}/{len(normalized)} samples, "
                f"{len(succeeded_project_ids)}/{len(groups)} projets, {len(campaign_df)} lignes objet"
            ),
            f"- campagne : {'PARTIELLE' if partial_export else 'COMPLÈTE'}",
            "",
            "## Audit de couverture",
        ]
        if partial_export:
            if failed_project_ids:
                audit_lines.append(
                    "- projets non couverts : "
                    + ", ".join(str(project_id) for project_id in failed_project_ids)
                    + " (causes détaillées dans les échecs ci-dessus)"
                )
            if unresolved:
                audit_lines.append(
                    "- samples non couverts (absents du cache) : "
                    + ", ".join(str(sample_id) for sample_id in unresolved)
                )
            audit_lines.append(
                "- toute analyse suivante décrit uniquement la couverture effectivement exportée"
            )
        else:
            audit_lines.append("- aucun sample ni projet demandé n'a été exclu")
        summary += "\n\n" + "\n".join(audit_lines)
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
                "samples_requested": len(normalized),
                "samples_exported": exported_samples,
                "partial_export": partial_export,
                "rows": total_rows,
            },
        )

    @tool(response_format="content_and_artifact")
    def list_ecotaxa_cache_tables() -> str:
        """Cartographie complète des tables réellement présentes dans le cache EcoTaxa.

        Retourne en un appel le nom, le grain, le nombre de lignes, les colonnes,
        clés primaires, index et relations de chaque table non interne. Inclut
        les tables d'extension locales lorsqu'elles existent.

        À utiliser quand le schéma est inconnu, avant une jointure, ou après une
        erreur de colonne. Si le schéma utile est déjà connu, interroger le cache
        directement sans rappeler cette carte.
        """
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_readonly_connection(cache_db)
            tables = [
                table for table in _sql_explorer.list_tables(conn)
                if table["table"] != "objects_cache"
            ]
            conn.close()
        except Exception as exc:
            return _eco_error(f"Erreur lecture cache : {exc}", retryable=True)

        lines = ["## Carte du cache EcoTaxa", ""]
        total_columns = 0
        for t in tables:
            count = t["rows"] if t["rows"] is not None else "—"
            columns = []
            for column in t["columns"]:
                suffix = " PK" if column["pk"] else ""
                columns.append(f"`{column['name']}` {column['type'] or 'ANY'}{suffix}")
            total_columns += len(columns)
            relations = [
                f"`{item['from_column']}` → "
                f"`{item['to_table']}.{item['to_column']}` ({item['kind']})"
                for item in t["relations"]
            ]
            index_names = [f"`{item['name']}`" for item in t["indexes"]]
            lines += [
                f"### `{t['table']}` — {count} lignes",
                f"- Grain : {t['grain']}",
                f"- Rôle : {t['description']}",
                f"- Colonnes : {', '.join(columns) or 'aucune'}",
                f"- Relations : {', '.join(relations) or 'aucune déclarée'}",
                f"- Index : {', '.join(index_names) or 'aucun'}",
                "",
            ]
        lines += [
            "La carte reflète le fichier actuellement ouvert. Utiliser ensuite "
            "un SELECT ou WITH read-only pour l'exploration.",
        ]
        return _eco_success(
            "\n".join(lines),
            metrics={"tables": len(tables), "columns": total_columns},
        )

    @tool(response_format="content_and_artifact")
    def describe_ecotaxa_cache_table(table_name: str) -> str:
        """Retourne le schéma complet (colonnes, types, index) d'une table du cache EcoTaxa.

        À utiliser avant un SELECT précis pour vérifier les noms exacts de
        colonnes et leurs types. `table_name` est l'un des noms retournés par
        `list_ecotaxa_cache_tables`.

        Paire naturelle avec `list_ecotaxa_cache_tables` et `query_ecotaxa_cache`.
        """
        if str(table_name).strip().lower() == "objects_cache":
            return _eco_blocked(
                "Le niveau objet se traite uniquement avec un export EcoTaxa confirmé."
            )
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_readonly_connection(cache_db)
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
            f"Grain : {result['grain']}",
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
            lines += ["", "### Index", "", "| nom | colonnes | unique |", "|---|---|:---:|"]
            for idx in result["indexes"]:
                index_columns = ", ".join(f"`{name}`" for name in idx["columns"])
                lines.append(
                    f"| `{idx['name']}` | {index_columns} | "
                    f"{'✓' if idx['unique'] else ''} |"
                )
        if result["relations"]:
            lines += ["", "### Relations"]
            for relation in result["relations"]:
                lines.append(
                    f"- `{relation['from_column']}` → "
                    f"`{relation['to_table']}.{relation['to_column']}` "
                    f"({relation['kind']})"
                )
        return _eco_success(
            "\n".join(lines), metrics={"columns": len(result["columns"])}
        )

    @tool(response_format="content_and_artifact")
    def query_ecotaxa_cache(
        sql: str,
        selection_name: str | None = None,
        description: str | None = None,
        dataframe_refs: list[str] | None = None,
    ) -> str:
        """Exécute un SELECT ou WITH/CTE libre sur le cache SQLite EcoTaxa local.

        Args:
            sql: Requête SQLite read-only à exécuter.
            selection_name: Nom descriptif facultatif du résultat
                (ex. `baffin_2024` ou `station_counts`). Une requête retournant
                `sample_id` devient une sélection exportable unique. Tout autre
                SELECT devient aussi un DataFrame persistant unique, mais pas
                une sélection exportable. Si absent, un nom stable est dérivé
                du SQL et de la description. Ce paramètre nomme le résultat
                produit : il ne charge ni ne filtre une sélection existante et
                ne doit jamais être utilisé comme table dans le SQL.
            description: Phrase courte destinée à l'inventaire des DataFrames.
                Décrire la source et les filtres SQL, le grain des lignes, le
                rôle analytique du résultat et ses familles de colonnes utiles.
                Ne décrire que ce que la requête établit. Si absent, une
                description technique minimale est générée automatiquement.
            dataframe_refs: Noms exacts des DataFrames persistants à monter
                comme tables dans une base SQLite temporaire, par exemple
                `["df_file_neolabs_sample"]`. Seuls ces DataFrames deviennent
                accessibles dans le SQL, sous leur nom exact. Le cache EcoTaxa
                reste attaché en lecture seule et les tables temporaires
                disparaissent après la requête.

        Un nom persistant `df_*` peut être utilisé dans `FROM` ou `JOIN`
        uniquement s'il est également déclaré dans `dataframe_refs`. Sans cette
        déclaration, il reste une variable Python invisible à SQLite. Utiliser
        les noms exacts présentés dans l'inventaire des DataFrames ; ne jamais
        inventer un alias de table de session.

        ## Jointure directe DataFrame ↔ cache EcoTaxa

        Utiliser `dataframe_refs` quand le résultat demandé dépend à la fois de
        lignes d'un DataFrame de session et de tables du cache. C'est notamment
        la route normale pour chercher des samples/profils EcoTaxa correspondant
        à des stations, identifiants ou dates d'un fichier chargé. Ne pas
        extraire une longue liste avec `run_pandas`, ne pas fabriquer un
        `IN (...)` volumineux et ne pas refaire ensuite la même jointure dans
        pandas : réaliser la jointure directement dans ce SELECT.

        Procédure obligatoire :
        1. choisir dans l'inventaire le DataFrame source exact d'après sa
           description, son grain et ses colonnes ; ne jamais utiliser `df` ni
           un ancien dérivé par commodité ;
        2. vérifier les vrais noms de colonnes. Le montage conserve exactement
           leur casse et leurs caractères ; entourer de guillemets doubles les
           noms contenant espaces, parenthèses ou symboles ;
        3. mettre chaque nom de table `df_*` utilisé par le SQL dans
           `dataframe_refs`. Une référence déclarée mais inutilisée est inutile ;
           une référence utilisée mais non déclarée produit `no such table` ;
        4. établir le grain dans une CTE. Conserver une ligne par identifiant
           réel (`sample_id`, déploiement, profil, etc.) et ne jamais dédupliquer
           seulement sur station + cast si ces valeurs peuvent être réutilisées ;
        5. joindre cette CTE aux vraies tables EcoTaxa (`samples_cache`,
           `projects_cache`, etc.) avec une clé explicitement vérifiée ;
        6. retourner les identifiants des deux côtés et les indicateurs de
           qualité de jointure. Si le résultat doit devenir une sélection
           EcoTaxa exportable, la colonne UVP/EcoTaxa doit être nommée exactement
           `sample_id`; conserver l'identifiant local sous un autre nom comme
           `net_sample_id` ;
        7. fournir `description` avec les DataFrames montés, les filtres, le
           grain de sortie, le rôle analytique et les familles de colonnes.

        Pour une correspondance filet/NeoLabs ↔ UVP, utiliser la table sample au
        grain prélèvement plutôt qu'une table abundance au grain taxon/analyse.
        La même station normalisée est la condition spatiale ; aucun seuil de
        distance n'est requis. La fenêtre temporelle vient de l'utilisateur et
        se calcule en SQLite avec `julianday`. Exemple pour un seuil de 10 h :

        ```sql
        WITH net AS (
          SELECT DISTINCT
                 sample_id AS net_sample_id,
                 TRIM(station_name) AS net_station,
                 deployment_datetime_start AS net_datetime
          FROM df_file_neolabs_sample
          WHERE sample_id IS NOT NULL
            AND station_name IS NOT NULL
            AND deployment_datetime_start IS NOT NULL
        ),
        candidates AS (
          SELECT net.net_sample_id,
                 uvp.sample_id AS sample_id,
                 uvp.project_id,
                 uvp.profile_id,
                 net.net_station,
                 uvp.station_id AS uvp_station,
                 net.net_datetime,
                 uvp.datetime_min AS uvp_datetime,
                 ABS(
                   (julianday(uvp.datetime_min) - julianday(net.net_datetime))
                   * 24.0
                 ) AS time_delta_h
          FROM net
          JOIN samples_cache AS uvp
            ON LOWER(TRIM(uvp.station_id)) = LOWER(net.net_station)
          WHERE uvp.instrument LIKE 'UVP%'
            AND uvp.datetime_min IS NOT NULL
        )
        SELECT *
        FROM candidates
        WHERE time_delta_h <= 10.0
        ORDER BY net_sample_id, time_delta_h, sample_id
        ```

        Cet exemple exige
        `dataframe_refs=["df_file_neolabs_sample"]`. Remplacer `10.0` par le
        seuil demandé ; ne jamais en faire une constante globale. Plusieurs
        candidats dans la fenêtre restent plusieurs lignes : ne pas choisir le
        premier silencieusement. Préserver aussi les non-correspondances avec un
        `LEFT JOIN` lorsque la demande porte sur la couverture complète.

        La base en mémoire est un espace d'exécution éphémère : elle copie
        uniquement les DataFrames déclarés, attache le cache en lecture seule,
        puis disparaît. Les DataFrames sources et le cache ne sont jamais
        modifiés. Seul le résultat et sa lignée persistent dans la session.

        EcoTaxa navigation is already pre-activated with this source family;
        call this tool directly rather than loading it again.

        Outil central d'exploration : écrire directement le SELECT voulu.
        Remplace tout pattern nécessitant plusieurs appels ou un export pour
        un comptage, regroupement ou filtrage arbitraire.

        Les comptes sample-level sont directement disponibles dans `samples_cache` :
        `object_count`, `nb_validated`, `nb_predicted`, `nb_dubious` et
        `nb_unclassified` proviennent des statistiques EcoTaxa autoritatives. Ne
        jamais dériver un statut depuis `object_count`. Le détail d'un objet
        nécessite un export confirmé.

        Les SELECT et WITH/CTE read-only sont autorisés, y compris jointures,
        sous-requêtes et agrégations. La connexion SQLite est ouverte en mode
        lecture seule et `query_only`; toute écriture reste impossible. Aucun
        LIMIT n'est ajouté par défaut :
        le résultat complet est conservé sous un nom unique quand il contient
        `sample_id`; `df_ecotaxa_cache_query` reste l'alias de la dernière
        requête. Ajouter un LIMIT uniquement si l'utilisateur demande
        explicitement un aperçu, un top ou une pagination.

        Zones nommées — règle stricte : utiliser la colonne `iho_zone`
        pré-calculée par point-in-polygon. Ne jamais écrire de bornes lat/lon
        littérales de mémoire — des coordonnées inventées donnent des comptages
        faux ou vides. For an exact named zone, use exact equality such as
        `WHERE iho_zone = 'Baie de Baffin'`; never merge an IHO label with an
        overlapping MEOW label. Use `LIKE` only when the user explicitly asks
        to search all zone labels containing a word, and keep every returned
        label separate. `zone_reference` classifies cache labels as `IHO`,
        `MEOW`, `OUTSIDE`, or `MISSING_COORDINATES`: every zone ranking must
        select and group by both `zone_reference` and `iho_zone`. A grouping
        by `iho_zone` alone is refused.
        `get_zone_info` reste utile uniquement pour afficher la description
        d'une zone à l'utilisateur, pas pour construire une bbox de filtrage.

        Utiliser `list_ecotaxa_cache_tables` lorsque le schéma est inconnu,
        avant une jointure ou après une erreur de colonne. Ne pas rappeler la
        carte si le schéma nécessaire est déjà connu. Utiliser
        `describe_ecotaxa_cache_table` pour approfondir une seule table.

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
        | object_count | INTEGER | total autoritatif des objets du sample |
        | nb_validated / nb_predicted | INTEGER | comptes V/P autoritatifs au grain sample |
        | nb_dubious / nb_unclassified | INTEGER | comptes D/U autoritatifs au grain sample |
        | instrument | TEXT | UVP6, UVP5SD, Loki, … |
        | iho_zone | TEXT | zone IHO/MEOW assignée par point-in-polygon (ex. "Baie de Baffin") — égalité exacte pour une zone nommée |
        | zone_reference | TEXT | référentiel du label : IHO, MEOW, OUTSIDE ou MISSING_COORDINATES — obligatoire dans un regroupement de zones |
        | datetime_min / datetime_max | TEXT | enveloppe ISO date-heure dérivée des objets |
        | time_min / time_max | TEXT | enveloppe horaire HH:MM:SS dérivée des objets |
        | temporal_precision | TEXT | `datetime`, `date`, `partial` ou `none` |
        | missing_date_count / missing_time_count | INTEGER | objets sans date / heure exploitable |
        | missing_depth_min_count / missing_depth_max_count | INTEGER | objets sans borne de profondeur |
        | depth_complete | INTEGER | 1 si le scan et toutes les bornes de profondeur sont complets |
        | metadata_objects_scanned | INTEGER | nombre d'objets inspectés pour les enveloppes |
        | metadata_complete | INTEGER | 1 si le scan couvre le total autoritatif sans écart |
        | metadata_coverage_pct | REAL | pourcentage du total autoritatif inspecté |

        **project_schemas_cache** — schémas JSON des projets
        | project_id PK | schema_json (title, instrument, levels, free fields) |

        **project_signatures_cache** — stats de classification
        | project_id PK | objcount | pctvalidated | pctclassified |

        **sync_runs** — historique des synchronisations
        | run_id PK | started_at | ended_at | status | projects_synced | samples_synced | error_message |

        ## Exemples
        ```sql
        -- Date envelope overlap, complete metadata only
        SELECT sample_id, project_id, date_min, date_max, iho_zone
        FROM samples_cache
        WHERE metadata_complete = 1
          AND missing_date_count = 0
          AND date_min <= '2015-05-22'
          AND date_max >= '2015-05-20'

        -- Date-time envelope overlap, complete timestamp metadata only
        SELECT sample_id, project_id, datetime_min, datetime_max, iho_zone
        FROM samples_cache
        WHERE metadata_complete = 1
          AND temporal_precision = 'datetime'
          AND datetime_min <= '2015-05-22T16:00:00'
          AND datetime_max >= '2015-05-22T14:00:00'

        -- Hour envelope overlap, normal same-day range
        SELECT sample_id, project_id, time_min, time_max, iho_zone
        FROM samples_cache
        WHERE metadata_complete = 1
          AND missing_time_count = 0
          AND time_min <= '16:00:00'
          AND time_max >= '14:00:00'

        -- Hour envelope overlap across midnight
        SELECT sample_id, project_id, time_min, time_max, iho_zone
        FROM samples_cache
        WHERE metadata_complete = 1
          AND missing_time_count = 0
          AND (time_max >= '22:00:00' OR time_min <= '02:00:00')

        -- Complete depth-envelope overlap
        SELECT sample_id, project_id, depth_min, depth_max, iho_zone
        FROM samples_cache
        WHERE depth_complete = 1
          AND depth_min <= 300
          AND depth_max >= 100

        -- Samples par station (cross-project)
        SELECT sample_id, project_id, original_id, station_id, date_min, depth_max
        FROM samples_cache WHERE station_id LIKE '%RA76%' ORDER BY date_min

        -- Casts : toujours profile_id, jamais station_id
        SELECT profile_id AS cast_id, COUNT(DISTINCT sample_id) AS n_samples
        FROM samples_cache
        WHERE profile_id IS NOT NULL AND TRIM(profile_id) <> ''
        GROUP BY profile_id ORDER BY n_samples DESC, cast_id

        -- Samples par zone : références IHO et MEOW séparées
        SELECT zone_reference, iho_zone, COUNT(*) AS n_samples,
               MIN(date_min) AS date_min, MAX(date_max) AS date_max,
               GROUP_CONCAT(DISTINCT instrument) AS instruments
        FROM samples_cache
        GROUP BY zone_reference, iho_zone
        ORDER BY zone_reference, n_samples DESC

        -- Samples d'une zone nommée (égalité exacte, jamais de bbox inventée)
        SELECT sample_id, project_id, original_id, lat_avg, lon_avg, iho_zone,
               date_min, depth_max, instrument
        FROM samples_cache
        WHERE iho_zone = 'Baie de Baffin'
        ORDER BY date_min

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

        Rows excluded by completeness guards are unknown, not non-matches.
        Count and report incomplete or partial rows with a second query that
        preserves the same project and/or `iho_zone` scope. For one resolved
        incomplete sample, inspect its cache row explicitly; do not launch live
        detail calls silently for a large batch.
        """
        if re.search(r"\bobjects_cache\b", sql, flags=re.IGNORECASE):
            return _eco_blocked(
                "Le niveau objet se traite uniquement avec un export EcoTaxa confirmé."
            )
        if _zone_grouping_requires_reference(sql):
            return _eco_blocked(
                "Agrégation de zones refusée : groupe par zone_reference et iho_zone "
                "pour garder les référentiels IHO et MEOW séparés."
            )
        requested_dataframe_refs = tuple(
            dict.fromkeys(str(name).strip() for name in (dataframe_refs or []))
        )
        mounted_dataframes: dict[str, pd.DataFrame] = {}
        for variable_name in requested_dataframe_refs:
            if not DATAFRAME_TABLE_PATTERN.fullmatch(variable_name):
                return _eco_blocked(
                    f"Référence DataFrame invalide : `{variable_name}`. "
                    "Utilise un nom persistant exact commençant par `df_`."
                )
            entry = _store.get(f"{thread_id}:dataset:{variable_name}")
            dataframe = (entry or {}).get("df")
            if not isinstance(dataframe, pd.DataFrame):
                available = []
                for key in _store.keys(f"{thread_id}:dataset:"):
                    candidate = _store.get(key) or {}
                    if isinstance(candidate.get("df"), pd.DataFrame):
                        available.append(key.rsplit(":", 1)[-1])
                available_text = ", ".join(f"`{name}`" for name in sorted(available))
                return _eco_error(
                    f"DataFrame `{variable_name}` introuvable dans la session. "
                    f"DataFrames disponibles : {available_text or 'aucun'}.",
                    retryable=True,
                    metrics={
                        "dependency_recovery": True,
                        "missing_names": [variable_name],
                        "recovery_source": "dataframe",
                        "recovery_tools": ["run_pandas", "load_file"],
                    },
                )
            mounted_dataframes[variable_name] = dataframe

        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        conn = None
        try:
            conn = (
                open_dataframe_cache_workspace(cache_db, mounted_dataframes)
                if mounted_dataframes
                else open_readonly_connection(cache_db)
            )
            # Keep the complete SELECT result in the persisted DataFrame. The
            # response below may show a compact preview, but it is not data loss.
            result = _sql_explorer.run_select(conn, sql, cap=None)
        except Exception as exc:
            return _eco_error(
                f"Erreur lors de l'exécution SQL sur le cache EcoTaxa : {exc}",
                retryable=False,
            )
        finally:
            if conn is not None:
                conn.close()

        if not result.get("ok"):
            sql_error = str(result["error"])
            dataframe_table = re.search(
                r"no such table:\s*(?P<name>df_[A-Za-z0-9_]+)",
                sql_error,
                flags=re.IGNORECASE,
            )
            if dataframe_table:
                variable_name = dataframe_table.group("name")
                candidate = _store.get(
                    f"{thread_id}:dataset:{variable_name}"
                )
                candidate_names = (
                    [variable_name]
                    if isinstance((candidate or {}).get("df"), pd.DataFrame)
                    else []
                )
                diagnostic = (
                    f"`{variable_name}` est un DataFrame de session qui n'a pas "
                    "été monté dans cette requête SQLite. Ne change pas son nom "
                    f"et relance `query_ecotaxa_cache` avec "
                    f"`dataframe_refs=['{variable_name}']`. Le SQL pourra alors "
                    "l'utiliser directement dans `FROM` ou `JOIN` avec les "
                    "tables du cache comme `samples_cache`."
                )
                return _eco_error(
                    diagnostic,
                    retryable=True,
                    metrics={
                        "dependency_recovery": True,
                        "execution_namespace_mismatch": True,
                        "missing_names": [variable_name],
                        "recovery_source": "ecotaxa",
                        "recovery_tools": ["query_ecotaxa_cache"],
                        "dependency_requirement": {
                            "kind": "table",
                            "name": variable_name,
                            "canonical_name": variable_name,
                            "source_hint": "ecotaxa",
                            "candidate_resources": candidate_names,
                            "diagnostic": sql_error[:2_000],
                            "description": (
                                "Monter le DataFrame de session dans la base "
                                "SQLite temporaire via dataframe_refs."
                            ),
                        },
                    },
                )
            return _eco_blocked(sql_error)

        rows = result["rows"]
        columns = result["columns"]
        truncated = result["truncated"]

        if not rows:
            return _eco_empty("La requête n'a retourné aucune ligne.")

        dataframe = pd.DataFrame.from_records(rows, columns=columns)
        latest_variable = "df_ecotaxa_cache_query"
        provided_description = str(description or "").strip()[:500]
        id_series = (
            pd.to_numeric(dataframe["sample_id"], errors="coerce").dropna()
            if "sample_id" in dataframe.columns
            else pd.Series(dtype="int64")
        )
        sample_ids = [int(value) for value in dict.fromkeys(id_series.tolist())]
        net_sample_count = (
            int(dataframe["net_sample_id"].nunique(dropna=True))
            if "net_sample_id" in dataframe.columns
            else None
        )
        base_meta = {
            "source": (
                "ecotaxa_cache+session_dataframes"
                if requested_dataframe_refs
                else "ecotaxa_cache"
            ),
            "sql": sql,
            "n_rows": len(dataframe),
            "n_cols": len(dataframe.columns),
            "truncated": truncated,
            "input_dataframes": list(requested_dataframe_refs),
            **(
                {"n_ecotaxa_samples": len(sample_ids)}
                if "sample_id" in dataframe.columns
                else {}
            ),
            **(
                {"n_net_samples": net_sample_count}
                if net_sample_count is not None
                else {}
            ),
            **(
                {"description": provided_description}
                if provided_description
                else {}
            ),
        }

        # Every sample-level SQL result becomes its own persistent sandbox table.
        # The legacy variable remains a moving alias to the latest query.
        selection_note = ""
        persisted_variable = latest_variable
        if sample_ids:
            project_ids: list[int] = []
            if "project_id" in dataframe.columns:
                project_series = pd.to_numeric(
                    dataframe["project_id"], errors="coerce"
                ).dropna()
                project_ids = sorted({int(value) for value in project_series.tolist()})
            if not project_ids:
                try:
                    project_ids = sorted(
                        {int(value) for value in resolve_sample_projects(sample_ids).values()}
                    )
                except Exception:
                    project_ids = []

            selection_key, persisted_variable, label = (
                _persistent_cache_selection_identity(
                    sql=sql,
                    sample_ids=sample_ids,
                    requested_name=selection_name,
                )
            )
            compact_sql = " ".join(str(sql).split())
            generated_description = (
                f"Sélection EcoTaxa « {label} » · {len(sample_ids)} samples "
                "EcoTaxa distincts (`sample_id`) · "
                f"{len(project_ids)} projets · SQL: {compact_sql[:180]}"
            )
            dataset_description = provided_description or generated_description
            selection_meta = {
                **base_meta,
                "source": "ecotaxa_selection",
                "selection_name": selection_key,
                "sample_ids": sample_ids,
                "project_ids": project_ids,
                "n_samples": len(sample_ids),
                "filters": {"sql": sql},
                "description": dataset_description,
            }
            store_dataset(
                _store,
                thread_id,
                dataframe,
                variable_name=persisted_variable,
                meta=selection_meta,
            )
            store_dataset(
                _store,
                thread_id,
                dataframe,
                variable_name=latest_variable,
                meta={
                    **base_meta,
                    "alias_of": persisted_variable,
                    "description": dataset_description,
                },
                set_active=False,
            )
            stored_selection_meta = {
                **selection_meta,
                "variable_name": persisted_variable,
            }
            _store.set(
                f"{thread_id}:selection:{selection_key}",
                None,
                stored_selection_meta,
            )
            _store.set(
                f"{thread_id}:ecotaxa_selection_latest",
                None,
                stored_selection_meta,
            )
            selection_note = (
                "\n\nLa sélection EcoTaxa complète de "
                f"{len(sample_ids)} `sample_id` distincts est "
                f"conservée dans `{persisted_variable}` sous le nom "
                f"`{selection_key}` ; `latest` pointe vers cette sélection."
            )
        else:
            persisted_variable, label = _persistent_cache_result_identity(
                sql=sql,
                requested_name=selection_name,
                description=provided_description,
                dataframe_refs=requested_dataframe_refs,
            )
            compact_sql = " ".join(str(sql).split())
            dataset_description = provided_description or (
                f"Résultat SQL EcoTaxa « {label} » · {len(dataframe)} lignes × "
                f"{len(dataframe.columns)} colonnes · SQL: {compact_sql[:220]}"
            )
            store_dataset(
                _store,
                thread_id,
                dataframe,
                variable_name=persisted_variable,
                meta={
                    **base_meta,
                    "source": "ecotaxa_cache_result",
                    "result_name": label,
                    "filters": {"sql": sql},
                    "description": dataset_description,
                },
            )
            store_dataset(
                _store,
                thread_id,
                dataframe,
                variable_name=latest_variable,
                meta={
                    **base_meta,
                    "alias_of": persisted_variable,
                    "description": dataset_description,
                },
                set_active=False,
            )
            selection_note = (
                "\n\nLe résultat SQL complet est conservé dans "
                f"`{persisted_variable}` ; `df_ecotaxa_cache_query` pointe "
                "vers la dernière requête."
            )

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
            f"\n_(aperçu de {len(preview_rows)} lignes sur {len(rows)} ; "
            f"résultat complet dans `{persisted_variable}` ; "
            "`df_ecotaxa_cache_query` pointe vers la dernière requête)_"
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
            sample_count_parts = [
                f"{len(sample_ids)} samples EcoTaxa distincts (`sample_id`)"
            ]
            if net_sample_count is not None:
                sample_count_parts.append(
                    f"{net_sample_count} net samples NeoLabs distincts (`net_sample_id`)"
                )
            selection_overview = [
                "## Synthèse de la sélection complète", "",
                f"{' · '.join(sample_count_parts)} · {projects} projets · zones : {zones}.",
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
            data_ref=persisted_variable,
            persisted=True,
            metrics={
                "rows": len(rows),
                "truncated": truncated,
                **(
                    {"n_ecotaxa_samples": len(sample_ids)}
                    if "sample_id" in dataframe.columns
                    else {}
                ),
                **(
                    {"n_net_samples": net_sample_count}
                    if net_sample_count is not None
                    else {}
                ),
            },
        )

    return [
        query_ecotaxa,
        export_ecotaxa_samples,
        list_ecotaxa_cache_tables,
        describe_ecotaxa_cache_table,
        query_ecotaxa_cache,
    ]
