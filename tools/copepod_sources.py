"""tools/copepod_sources.py — LangChain tools pour accès EcoTaxa/EcoPart."""
from __future__ import annotations

import os
import re
import unicodedata
import uuid
from pathlib import Path

import requests
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
from core.ecotaxa_browser.schema import get_project_schema
from core.ecotaxa_browser.search import search_projects
from core.ecotaxa_browser.taxa_stats import taxa_stats
from core.ecotaxa_browser.taxonomy import search_taxa
from core.ecotaxa_browser.cache.repo import (
    audit_ecotaxa_coverage,
    cache_progress,
    init_schema,
    open_connection,
    query_samples_filtered,
)
from tools.ecotaxa_client import EcotaxaClient, EcotaxaExportError
from tools.dataset_registry import ECOTAXA, dataset_variable_name, store_dataset
from tools.public_url import download_url
from tools.session_store import default_store as _store
from tools.data_tools import _uvp_skill_hint

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)

_ECOTAXA_UI_BASE = "https://ecotaxa.obs-vlfr.fr"


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
    ) -> str:
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
        summary = (
            f"{label} chargé — {len(df)} lignes, {len(df.columns)} colonnes.\n"
            f"Données disponibles dans `{variable_name}` et `df_ecotaxa`.\n"
            f"{year_note}"
            f"Appelle run_pandas directement pour analyser.\n"
            f"Télécharger : {download_url(f'{file_id}.tsv')}\n"
            f"Source EcoTaxa : {source_url}"
        )
        if hint:
            summary += f"\n{hint}"
        return summary

    @tool
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
            return f"Erreur lors de la recherche EcoTaxa : {exc}"

        if not projects:
            return "Aucun projet EcoTaxa ne correspond aux critères."

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
        return "\n".join(lines)

    @tool
    def list_ecotaxa_projects() -> str:
        """Liste les projets EcoTaxa accessibles au compte configuré."""
        try:
            client = EcotaxaClient()
            client.login()
            projects = sorted(client.list_projects(), key=lambda project: project["project_id"])
        except Exception as exc:
            return f"Erreur lors de l'accès à EcoTaxa : {exc}"

        if not projects:
            return "Aucun projet EcoTaxa accessible."

        lines = ["| project_id | name | url |", "|---:|---|---|"]
        lines.extend(
            f"| {project['project_id']} | {project['name']} | "
            f"{_ecotaxa_project_url(project['project_id'])} |"
            for project in projects
        )
        return "\n".join(lines)

    @tool
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
            return f"Erreur lors de la lecture du cache EcoTaxa : {exc}"

        if not rows:
            return "Aucun projet EcoTaxa dans le cache local."

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
            return (
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
        return "\n".join(lines)

    @tool
    def audit_ecotaxa_availability() -> str:
        """Audit de couverture des données EcoTaxa indexées (lecture seule).

        À utiliser pour les questions d'audit de disponibilité : quels projets
        ont **peu de samples**, quelles **périodes** sont couvertes ou manquantes,
        quels **samples** sont les plus pauvres en objets. Répond aux demandes du
        type « audit des zones/projets avec peu de samples », « quelles années
        couvre-t-on », « les samples avec le moins d'images ».

        Ne lance aucun export : tout vient du cache local. Renvoie les projets
        classés du plus pauvre au plus riche en samples, la distribution
        temporelle par année, et les samples les plus pauvres en objets. Ne
        fournit PAS les comptages validé/prédit par taxon (voir les tools de
        comptage taxonomique pour cela).
        """
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            audit = audit_ecotaxa_coverage(conn)
            conn.close()
        except Exception as exc:
            return f"Erreur lors de la lecture du cache EcoTaxa : {exc}"

        if not audit["per_project"]:
            return "Aucun sample indexé dans le cache local."

        def _bbox(box: dict) -> str:
            if box.get("south") is None:
                return "—"
            return (
                f"{_format_number(box['south'])}/{_format_number(box['west'])}/"
                f"{_format_number(box['north'])}/{_format_number(box['east'])}"
            )

        lines = [
            "# Audit de disponibilité EcoTaxa (cache local)",
            "",
            f"Total : {audit['total_samples']} samples, "
            f"{audit['total_projects']} projets.",
            "",
            "## Projets classés du plus pauvre au plus riche en samples",
            "",
            "| project_id | n_samples | période | instrument | bbox (S/W/N/E) |",
            "|---:|---:|---|---|---|",
        ]
        lines.extend(
            f"| {p['project_id']} | {p['n_samples']} | "
            f"{p['date_min'] or '—'} → {p['date_max'] or '—'} | "
            f"{', '.join(p['instruments']) or '—'} | {_bbox(p['bbox'])} |"
            for p in audit["per_project"]
        )
        lines += [
            "",
            "## Couverture temporelle",
            "",
            "| année | n_samples | n_projets |",
            "|---|---:|---:|",
        ]
        lines.extend(
            f"| {y['year']} | {y['n_samples']} | {y['n_projects']} |"
            for y in audit["per_year"]
        )
        lines += [
            "",
            "## Samples les plus pauvres en objets",
            "",
            "| sample_id | project_id | label | n_objects |",
            "|---:|---:|---|---:|",
        ]
        lines.extend(
            f"| {s['sample_id']} | {s['project_id']} | "
            f"{s['original_id'] or '—'} | {s['object_count']} |"
            for s in audit["sparsest_samples"]
        )
        lines.append("")
        lines.append(
            "Note : les comptages d'objets par projet sont plafonnés à la synchro ; "
            "le compte par sample est fiable. Les comptages validé/prédit par "
            "taxon ne sont pas inclus ici."
        )
        return "\n".join(lines)

    @tool
    def list_ecotaxa_project_samples(project_id: int) -> str:
        """Liste les samples d'un projet EcoTaxa avec leur `sample_id` numérique.

        À utiliser pour résoudre le `sample_id` numérique EcoTaxa (ex.
        `17498000023`) à partir du label / `original_id` d'un sample (ex.
        `am_leg4_RA76_1`). Les autres outils de présentation montrent le label,
        mais l'export et l'enrichissement exigent le numéro : cet outil fait le
        pont, sans deviner ni inventer d'identifiant.

        Renvoie un tableau : `sample_id` numérique, label (`original_id`),
        station, latitude, longitude, profondeur max. Lecture seule, depuis le
        cache local EcoTaxa.
        """
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            rows = list(query_samples_filtered(conn, project_ids=[int(project_id)]))
            conn.close()
        except Exception as exc:
            return f"Erreur lors de la lecture du cache EcoTaxa : {exc}"

        if not rows:
            return (
                f"Aucun sample dans le cache local pour le projet {project_id}. "
                "Le projet n'a peut-être pas encore été synchronisé."
            )

        rows.sort(key=lambda row: (row["original_id"] or "", row["sample_id"]))
        lines = [
            f"# Samples du projet EcoTaxa {project_id}",
            "",
            "| sample_id | label | station | latitude | longitude | profondeur max |",
            "|---:|---|---|---:|---:|---:|",
        ]
        lines.extend(
            f"| {row['sample_id']} | {row['original_id'] or '—'} | "
            f"{row['station_id'] or '—'} | {_format_number(row['lat_avg'])} | "
            f"{_format_number(row['lon_avg'])} | {_format_number(row['depth_max'])} |"
            for row in rows
        )
        lines.append("")
        lines.append(f"Source EcoTaxa : {_ecotaxa_project_url(project_id)}")
        return "\n".join(lines)

    @tool
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
            return f"Erreur lors de l'accès à EcoTaxa : {exc}"

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
            return "\n".join(lines)

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
        return "\n".join(lines)

    @tool
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
            return f"Erreur dans les paramètres EcoTaxa : {exc}"

        sample_suffix = f"_samples_{'_'.join(str(sample_id) for sample_id in normalized_sample_ids)}" if normalized_sample_ids else ""
        variable_name = dataset_variable_name("ecotaxa", f"{project_id}{sample_suffix}")
        label = f"Projet {project_id}"
        if normalized_sample_ids:
            label += f" — samples {','.join(str(sample_id) for sample_id in normalized_sample_ids)}"

        try:
            return _download_ecotaxa_export(
                project_id=project_id,
                filters=filters,
                variable_name=variable_name,
                meta={"sample_ids": normalized_sample_ids},
                label=label,
            )
        except Exception as exc:
            return _format_export_failure(project_id, exc)

    @tool
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
            return f"Erreur EcoTaxa ({exc.code}) : {exc}"
        except Exception as exc:
            return f"Erreur lors de l'accès au sample {sample_id} : {exc}"

        try:
            return _download_ecotaxa_export(
                project_id=project_id,
                filters=filters,
                variable_name=dataset_variable_name("ecotaxa", "sample", str(sample_id)),
                meta={"sample_id": sample_id, "original_id": sample.get("original_id")},
                label=f"Sample {sample_id} (projet {project_id})",
            )
        except Exception as exc:
            return _format_export_failure(project_id, exc, sample_id=sample_id)

    @tool
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
            return f"Erreur lors de l'accès au schéma EcoTaxa : {exc}"

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
        return "\n".join(lines)

    @tool
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
            return f"Erreur EcoTaxa ({exc.code}) : {exc}"
        except Exception as exc:
            return f"Erreur lors du comptage EcoTaxa : {exc}"

        if not result["rows"]:
            return "Aucun comptage retourné — vérifie les IDs de projet et taxon."

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
        return "\n".join(lines)

    @tool
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
            return "Erreur : `query` ne peut pas être vide."
        try:
            matches = search_taxa(query)
        except Exception as exc:
            return f"Erreur lors de la recherche taxonomique : {exc}"
        if not matches:
            return f"Aucun taxon EcoTaxa ne correspond à `{query}`."
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
        return "\n".join(lines)

    @tool
    def get_ecotaxa_cache_status() -> str:
        """Diagnostique l'état du cache local EcoTaxa.

        Routing requirement: appeler ce tool quand une recherche cache retourne
        `CACHE_EMPTY`, quand l'utilisateur demande « est-ce que le cache est à
        jour », ou avant une exploration zone+temps si l'agent doute de la
        fraîcheur des données.

        Retourne :
        - nombre de samples / projets / schémas indexés ;
        - timestamp et statut du dernier sync (`success`, `running`, `failed`) ;
        - fenêtres synchronisées (n samples, n projets) ;
        - chemin du fichier SQLite utilisé.
        """
        cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
        try:
            conn = open_connection(cache_db)
            init_schema(conn)
            progress = cache_progress(conn)
            last_sync = progress["last_sync"]
            conn.close()
        except Exception as exc:
            return f"Erreur lors de la lecture du cache EcoTaxa : {exc}"

        lines = [
            f"**Cache EcoTaxa** — `{cache_db}`",
            "",
            "| métrique | valeur |",
            "|---|---:|",
            f"| samples indexés | {progress['samples_indexed']} |",
            f"| projets indexés | {progress['projects_indexed']} |",
            f"| schémas indexés | {progress['schemas_indexed']} |",
            f"| sync en cours | {'oui' if progress['sync_running'] else 'non'} |",
            f"| projets déjà synchronisés | {progress['projects_synced']} |",
            f"| samples déjà synchronisés | {progress['samples_synced']} |",
            "| total projets estimé | inconnu |",
        ]
        if last_sync is None:
            lines.append("")
            lines.append(
                "Aucun sync enregistré (jamais synchronisé). "
                "Lancer `POST /admin/resync` sur le MCP server pour amorcer le cache."
            )
        else:
            lines.append("")
            lines.append(
                f"**Dernier sync** — `{last_sync.get('status', '?')}` "
                f"démarré à `{last_sync.get('started_at', '?')}`"
                + (
                    f", terminé à `{last_sync.get('ended_at', '?')}`"
                    if last_sync.get("ended_at")
                    else ""
                )
                + f". Projets synchronisés : {last_sync.get('projects_synced', '—')}, "
                f"samples : {last_sync.get('samples_synced', '—')}."
            )
            if progress["sync_running"]:
                lines.append(
                    "\nSync en cours : les recherches EcoTaxa peuvent retourner "
                    "des résultats partiels (`partial=True`) jusqu'à la fin du run."
                )
            if last_sync.get("error_message"):
                lines.append(f"\nErreur : {last_sync['error_message']}")
        return "\n".join(lines)

    @tool
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
            return f"Erreur EcoTaxa ({exc.code}) : {exc}{details}"
        except Exception as exc:
            return f"Erreur lors de l'analyse de la colonne EcoTaxa : {exc}"

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
        return header + body

    @tool
    def compare_ecotaxa_projects(project_ids: list[int]) -> str:
        """Compare les schémas de plusieurs projets EcoTaxa avant un export combiné.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Retourne les colonnes communes, les conflits de type, les conflits de
        niveau, et les colonnes uniques par projet.
        """
        if len(project_ids) < 2:
            return "Indique au moins 2 project_ids."
        try:
            result = compare_project_schemas(project_ids=project_ids)
        except Exception as exc:
            return f"Erreur lors de la comparaison EcoTaxa : {exc}"

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
        return "\n".join(lines)

    @tool
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
            return (
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
            return f"Erreur EcoTaxa ({exc.code}) : {exc}"
        except Exception as exc:
            return f"Erreur lors de la recherche EcoTaxa : {exc}"

        if not result["samples"]:
            return (
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
            f"# {result['total_matching']} samples (cap {len(result['samples'])})"
            + (" — tronqué" if result["truncated"] else "")
            + (" — résultat partiel" if result.get("partial") else ""),
            f"Sélection mémorisée : `{selection_name}`",
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
                f"{s['lat']:.3f} | {s['lon']:.3f} | "
                f"{s['date_min']} | {s['date_max']} | "
                f"{_format_number(s.get('depth_min'))} | "
                f"{_format_number(s.get('depth_max'))} | "
                f"{s.get('instrument') or '—'} | "
                f"{_ecotaxa_sample_url(s['project_id'], s['sample_id'])} |"
            )
        if len(result["samples"]) > max_rows:
            lines.append("")
            lines.append(
                f"({max_rows} premiers / {len(result['samples'])} affichés ; "
                "définir ECOTAXA_SAMPLE_RESULT_ROWS pour élargir l'aperçu)"
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
        return "\n".join(lines)

    @tool
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
            return (
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
            return f"Erreur EcoTaxa ({exc.code}) : {exc}"
        except Exception as exc:
            return f"Erreur lors du regroupement par année : {exc}"

        years = result["years"]
        if not years:
            return (
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
        return "\n".join(lines)

    @tool
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
            return (
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
            return f"Erreur EcoTaxa ({exc.code}) : {exc}"
        except Exception as exc:
            return f"Erreur lors de la recherche EcoTaxa : {exc}"

        if not result["projects"]:
            return (
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
        return "\n".join(lines)

    @tool
    def group_ecotaxa_project_samples_by_region(project_id: int) -> str:
        """Groupe tous les samples cache d'un projet EcoTaxa par zone IHO/NeoLab.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Utiliser quand l'utilisateur demande une vue « par mer », « par
        secteur », « par zone », ou « groupe les samples du projet X par
        région ». Le tool lit uniquement le cache local, teste chaque sample
        contre le registry NeoLab/IHO, et rend un récap compact :
        region -> sample_ids, avec buckets explicites `Hors zones IHO` et
        `Sans coordonnées`.
        """
        try:
            result = group_project_samples_by_region(project_id)
        except EcoTaxaBrowserError as exc:
            return f"Erreur EcoTaxa ({exc.code}) : {exc}"
        except Exception as exc:
            return f"Erreur lors du regroupement EcoTaxa : {exc}"

        summary = result.get("markdown_summary", "")
        if result.get("partial"):
            summary += _ecotaxa_partial_notice(result)
        return summary

    @tool
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
        Passer `include_empty=True` seulement si l'utilisateur demande
        explicitement les zones vides / lacunes d'échantillonnage.
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
            return f"Erreur EcoTaxa ({exc.code}) : {exc}"
        except Exception as exc:
            return f"Erreur lors du classement EcoTaxa par région : {exc}"

        summary = result.get("markdown_summary", "")
        if result.get("partial"):
            summary += _ecotaxa_partial_notice(result)
        return summary

    @tool
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
            raise EcoTaxaBrowserError(
                exc.code, f"{exc}{details}", candidates=exc.candidates,
            ) from exc

        if not result["samples"]:
            attested = result["attested_projects"]
            return (
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
                f"| {s['sample_id']} | {s['project_id']} | {s['lat']:.3f} | "
                f"{s['lon']:.3f} | {s['date_min']} | {s['date_max']} | "
                f"{_format_number(s.get('depth_min'))} | "
                f"{_format_number(s.get('depth_max'))} | "
                f"{_ecotaxa_sample_url(s['project_id'], s['sample_id'])} |"
            )
        if len(result["samples"]) > 50:
            lines.append("")
            lines.append(f"(50 premiers / {len(result['samples'])} affichés)")
        if result.get("partial"):
            lines.append(_ecotaxa_partial_notice(result).strip())
        return "\n".join(lines)

    @tool
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
            return f"Erreur EcoTaxa ({exc.code}) : {exc}"
        except Exception as exc:
            return f"Erreur lors de l'accès au sample {sample_id} : {exc}"

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
        return "\n".join(lines)

    @tool
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
            return f"Erreur lors du résumé déploiement EcoTaxa : {exc}"

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

        return "\n".join(lines)

    @tool
    def summarize_ecotaxa_samples(
        sample_ids: list[int] | None = None,
        selection_name: str | None = None,
    ) -> str:
        """Résume un batch de samples EcoTaxa sans télécharger les objets.

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Args:
            sample_ids: Liste explicite de sample_ids EcoTaxa.
            selection_name: Nom d'une sélection mémorisée par
                `find_ecotaxa_samples_in_region`, ou `"latest"` / `"cette sélection"`.

        Renvoie pour chaque `sample_id` un tableau markdown avec :
        - V (validés), P (prédits), D (douteux), U (non classés) — counts
          agrégés sur tous les taxa du sample
        - `total` = V + P + D + U
        - `projet`
        - `top taxa` — premiers taxa observés (jusqu'à 5 noms)

        Utiliser pour SCANNER une liste de samples (typiquement le résultat
        de `find_ecotaxa_samples_in_region`) avant de décider lesquels valent
        un export complet. Aucun download — appel léger sur l'endpoint
        EcoTaxa `/sample_set/taxo_stats`.

        Pour un seul sample, utilise plutôt `summarize_ecotaxa_sample`.
        """
        resolved_selection_name = None
        normalized = _normalize_sample_ids(sample_ids)
        if not normalized and selection_name:
            resolved_selection_name, normalized = _load_sample_selection(selection_name)
        if not normalized:
            if selection_name:
                return (
                    f"Erreur : sélection `{selection_name}` introuvable ou vide. "
                    "Relance une recherche EcoTaxa ou passe des sample_ids explicites."
                )
            return "Erreur : sample_ids vide."
        try:
            stats = summarize_samples(normalized)
        except Exception as exc:
            return f"Erreur lors du résumé EcoTaxa : {exc}"
        if not stats:
            return "Aucune statistique retournée par EcoTaxa pour ces samples."

        lines = []
        if resolved_selection_name:
            lines.extend([
                f"Sélection : {resolved_selection_name}",
                "",
            ])
        lines.extend([
            "| sample_id | projet | V | P | D | U | total | top taxa | url |",
            "|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ])
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
        return "\n".join(lines)

    @tool
    def summarize_ecotaxa_sample(sample_id: int) -> str:
        """Résume UN sample EcoTaxa (V/P/D/U counts + taxa observés).

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Variante mono-sample de `summarize_ecotaxa_samples`. Renvoie le même
        tableau réduit à une ligne. Pas de download.
        """
        return summarize_ecotaxa_samples.invoke({"sample_ids": [sample_id]})

    @tool
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
            return "Erreur : project_ids vide."
        try:
            stats = summarize_projects(project_ids)
        except Exception as exc:
            return f"Erreur lors du résumé EcoTaxa : {exc}"
        if not stats:
            return (
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
        return "\n".join(lines)

    @tool
    def summarize_ecotaxa_project(project_id: int) -> str:
        """Résume UN projet EcoTaxa (n_samples + envelope + V/P/D/U + taxa).

        Routing requirement: before calling this tool in an agent turn, call
        `load_skill("ecotaxa_navigation")` first unless it has already been
        called in the same turn.

        Variante mono-projet de `summarize_ecotaxa_projects`. Renvoie le
        même tableau réduit à une ligne. Pas de download.
        """
        return summarize_ecotaxa_projects.invoke({"project_ids": [project_id]})

    @tool
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
        if not normalized:
            if selection_name:
                return (
                    f"Erreur : sélection `{selection_name}` introuvable ou vide. "
                    "Relance une recherche EcoTaxa ou passe des sample_ids explicites."
                )
            return "Erreur : sample_ids vide."

        try:
            mapping = resolve_sample_projects(normalized)
        except Exception as exc:
            return f"Erreur lors de la résolution sample→projet : {exc}"

        unresolved = [s for s in normalized if s not in mapping]
        groups: dict[int, list[int]] = {}
        for sid, pid in mapping.items():
            groups.setdefault(pid, []).append(sid)

        if not groups:
            return (
                "Aucun des sample_ids fournis n'est présent dans le cache local. "
                f"Samples manquants : {unresolved}. "
                "Lancer un /admin/resync ou vérifier les IDs."
            )

        # Dry-run : montrer le plan, ne pas exécuter.
        if not confirmed:
            lines = [
                f"# Plan d'export — {len(normalized)} samples sur {len(groups)} projets",
            ]
            if resolved_selection_name:
                lines.extend(["", f"Sélection : `{resolved_selection_name}`"])
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
                "Pour lancer l'export, rappeler avec `confirmed=true`. "
                "Chaque projet déclenchera un `query_ecotaxa` indépendant ; "
                "un refus serveur sur un projet n'arrête pas les autres."
            )
            return "\n".join(lines)

        # Exécution réelle.
        successes: list[str] = []
        failures: list[str] = []
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
                summary = _download_ecotaxa_export(
                    project_id=pid,
                    filters=filters,
                    variable_name=variable_name,
                    meta={"sample_ids": sids, "bulk": True},
                    label=f"Projet {pid} ({len(sids)} samples)",
                )
                successes.append(f"### ✅ Projet {pid} ({len(sids)} samples)\n\n{summary}")
            except Exception as exc:
                failures.append(_format_export_failure(pid, exc))

        parts = [f"# Bulk export EcoTaxa — {len(groups)} projets traités"]
        if successes:
            parts.append("\n\n".join(successes))
        if failures:
            parts.append("## Échecs\n\n" + "\n\n---\n\n".join(failures))
        if unresolved:
            parts.append(f"⚠️ Samples absents du cache (non exportés) : {unresolved}")
        return "\n\n".join(parts)

    return [
        find_ecotaxa_projects,
        find_ecotaxa_samples_in_region,
        group_ecotaxa_samples_by_year,
        find_ecotaxa_projects_in_region,
        group_ecotaxa_project_samples_by_region,
        rank_ecotaxa_samples_by_region,
        find_ecotaxa_observations,
        get_ecotaxa_sample,
        summarize_ecotaxa_sample_deployment,
        inspect_ecotaxa_project_schema,
        inspect_ecotaxa_column,
        count_ecotaxa_taxa,
        search_ecotaxa_taxa,
        get_ecotaxa_cache_status,
        compare_ecotaxa_projects,
        list_ecotaxa_projects,
        list_ecotaxa_campaigns,
        list_ecotaxa_project_samples,
        audit_ecotaxa_availability,
        preview_ecotaxa_project,
        query_ecotaxa,
        query_ecotaxa_sample,
        summarize_ecotaxa_sample,
        summarize_ecotaxa_samples,
        summarize_ecotaxa_project,
        summarize_ecotaxa_projects,
        export_ecotaxa_samples,
    ]
