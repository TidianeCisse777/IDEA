"""LangChain tools for EcoPart."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from langchain_core.tools import tool

try:
    from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError
except ImportError:  # SQLAlchemy is optional outside the PostgreSQL session store.
    _SQLALCHEMY_OPERATIONAL_ERRORS: tuple[type[Exception], ...] = ()
else:
    _SQLALCHEMY_OPERATIONAL_ERRORS = (SQLAlchemyOperationalError,)

from core.ecopart_client import (
    EcopartClient,
    EcopartDownloadError,
    EcopartExportError,
)
from core.ecopart_cache import (
    CachedEcopartTsv,
    cache_root,
    find_ecopart_tsv,
    import_ecopart_tsv,
    load_ecopart_tsv,
    load_resolution,
    load_sample_preview,
    save_resolution,
    save_sample_preview,
)
from core.ecopart_cache_distribution import (
    CacheBundleValidationError,
    bootstrap_consumer_cache,
)
from core.ecotaxa_ecopart_join import (
    audit_ecotaxa_ecopart_dataframe,
    depth_bin_5m,
)
from core.ecotaxa_browser.cache.repo import open_readonly_connection
from core.environment_resolver import build_enrichment_provenance
from core.scientific_result_cache import (
    build_result_cache_key,
    dataframe_fingerprint,
    load_result,
    save_result,
)
from tools.source_renderer import render_sources, source_urls
from tools.dataset_registry import (
    ECOPART,
    ECOTAXA,
    ECOTAXA_ECOPART,
    CTD_ENRICHED,
    dataset_variable_name,
    store_dataset,
)
from tools.ecotaxa_client import EcotaxaClient
from tools.public_url import download_url
from tools.session_store import default_store as _store
from tools.tool_result import blocked, empty, error, success, validate_tool_artifact

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)
_LOGGER = logging.getLogger(__name__)

_RECOVERABLE_PARTITION_ERRORS = (
    EcopartDownloadError,
    OSError,
    requests.RequestException,
    pd.errors.EmptyDataError,
    pd.errors.InvalidIndexError,
    pd.errors.MergeError,
    pd.errors.ParserError,
) + _SQLALCHEMY_OPERATIONAL_ERRORS


def _ecopart_preflight_timeout() -> float:
    """Allow EcoPart's slow profile registry to return a real availability result."""
    return max(1.0, float(os.getenv("ECOPART_PREFLIGHT_TIMEOUT_SECONDS", "60")))


def _ecopart_cache_ttl() -> float:
    return max(60.0, float(os.getenv("ECOPART_PREFLIGHT_CACHE_TTL_SECONDS", "86400")))


def _ecopart_resolution_cache_ttl() -> float:
    return max(60.0, float(os.getenv("ECOPART_RESOLUTION_CACHE_TTL_SECONDS", "2592000")))


def _fresh_cache_meta(meta: dict) -> bool:
    try:
        return float(meta.get("expires_at", 0)) > time.time()
    except (TypeError, ValueError):
        return False


def _ep_result(factory, summary: str, **fields):
    provenance = {"source": "ecopart", **dict(fields.pop("provenance", {}))}
    return factory(summary, provenance=provenance, **fields)


def _ep_success(summary: str, **fields): return _ep_result(success, summary, **fields)
def _ep_empty(summary: str, **fields): return _ep_result(empty, summary, **fields)
def _ep_blocked(summary: str, **fields): return _ep_result(blocked, summary, **fields)
def _ep_error(summary: str, **fields): return _ep_result(error, summary, **fields)


def _format_ecopart_export_error(
    exc: EcopartExportError,
    *,
    project_id: int | None = None,
    ecotaxa_project_id: int | None = None,
) -> tuple:
    """Render an EcopartExportError as a clean French message for the LLM."""
    scope = []
    if project_id is not None:
        scope.append(f"EcoPart {project_id}")
    if ecotaxa_project_id is not None:
        scope.append(f"EcoTaxa {ecotaxa_project_id}")
    scope_text = f" pour {', '.join(scope)}" if scope else ""
    task_note = f" (tâche #{exc.task_id})" if exc.task_id else ""
    return f"Export EcoPart échoué{scope_text}{task_note} — {exc.message}"


def _ecotaxa_session_for_project(
    thread_id: str,
    project_id: int | None,
) -> dict | None:
    """Resolve an EcoTaxa project while preserving a compatible CTD enrichment."""
    latest = _store.get(f"{thread_id}:ecotaxa")
    if project_id is None:
        return latest

    requested = int(project_id)

    # Chained enrichments must be cumulative.  When Amundsen has already
    # enriched the same EcoTaxa export, start the EcoPart join from that table
    # rather than silently returning to the raw ``ecotaxa`` alias.  A campaign
    # may contain several projects, hence the explicit line-level partition.
    ctd_enriched = _store.get(f"{thread_id}:{CTD_ENRICHED}")
    ctd_df = (ctd_enriched or {}).get("df")
    if (
        isinstance(ctd_df, pd.DataFrame)
        and "amundsen_match_status" in ctd_df.columns
        and "export_project_id" in ctd_df.columns
    ):
        ctd_projects = pd.to_numeric(
            ctd_df["export_project_id"], errors="coerce"
        )
        ctd_partition = ctd_df.loc[ctd_projects == requested].copy()
        if not ctd_partition.empty:
            return {
                "df": ctd_partition,
                "meta": {
                    **dict((ctd_enriched or {}).get("meta") or {}),
                    "project_id": requested,
                    "upstream_enrichment": "amundsen",
                },
            }

    if latest is not None:
        latest_project = (latest.get("meta") or {}).get("project_id")
        if latest_project is not None and int(latest_project) == requested:
            return latest

    candidates: list[dict] = []
    prefix = f"{thread_id}:dataset:df_ecotaxa_"
    for key in _store.keys(prefix):
        session = _store.get(key)
        if session is None:
            continue
        candidate_project = (session.get("meta") or {}).get("project_id")
        if candidate_project is not None and int(candidate_project) == requested:
            candidates.append(session)

    if candidates:
        # Prefer the canonical full-project variable when both a full export and a
        # scoped bulk export exist. Otherwise the sole/latest named dataset is safe.
        canonical = f"df_ecotaxa_{requested}"
        for session in candidates:
            if (session.get("meta") or {}).get("variable_name") == canonical:
                return session
        return candidates[-1]

    # A consolidated campaign retains the raw project provenance line by line.
    # An explicit EcoTaxa project therefore remains a mono-project request even
    # when no raw per-project export slot was kept in the current session.
    if latest is not None and isinstance(latest.get("df"), pd.DataFrame):
        campaign = latest["df"]
        if "export_project_id" in campaign.columns:
            project_values = pd.to_numeric(
                campaign["export_project_id"], errors="coerce"
            )
            partition = campaign.loc[project_values == requested].copy()
            if not partition.empty:
                return {
                    "df": partition,
                    "meta": {
                        **dict(latest.get("meta") or {}),
                        "project_id": requested,
                    },
                }
    return None


def _session_for_variable(thread_id: str, variable_name: str | None) -> dict | None:
    """Resolve one explicitly named dataset from the session registry."""
    if variable_name is None:
        return None
    return _store.get(f"{thread_id}:dataset:{variable_name}")


def _store_cached_ecopart_dataset(
    thread_id: str,
    entry: CachedEcopartTsv,
    *,
    ecotaxa_project_id: int | None,
    ecopart_project_id: int | None,
) -> str:
    """Load a durable EcoPart TSV into the current session for local joining."""
    dataframe = load_ecopart_tsv(entry)
    ep_key = ecopart_project_id or entry.ecopart_project_id or "cached"
    variable_name = dataset_variable_name("ecopart", ep_key)
    meta = {
        "source": f"ecopart_cache:{entry.provenance}",
        "project_id": ecopart_project_id or entry.ecopart_project_id,
        "ecotaxa_project_id": ecotaxa_project_id or entry.ecotaxa_project_id,
        "n_rows": len(dataframe),
        "cache_hit": True,
        "cache_path": str(entry.path),
        "content_sha256": entry.content_sha256,
        "cache_provenance": entry.provenance,
    }
    store_dataset(
        _store,
        thread_id,
        dataframe,
        variable_name=variable_name,
        meta=meta,
        latest_alias=ECOPART,
    )
    if ep_key != "cached":
        _store.set(f"{thread_id}:ecopart:{ep_key}", dataframe, meta)
    return variable_name


def _perform_enrichment(
    thread_id: str,
    project_id: int | None,
    *,
    ecotaxa_session: dict | None = None,
    ecotaxa_variable: str | None = None,
    ecopart_variable: str | None = None,
) -> str:
    """Run the (sample_id, depth_bin) join from the session-resolved EcoTaxa/EcoPart."""
    if project_id is not None and ecopart_variable is not None:
        return _ep_blocked(
            "Sélecteurs EcoPart incompatibles — utilise soit `project_id`, soit "
            "`ecopart_variable`, jamais les deux."
        )

    explicit_ecotaxa = _session_for_variable(thread_id, ecotaxa_variable)
    if ecotaxa_variable is not None and explicit_ecotaxa is None:
        return _ep_blocked(f"Variable EcoTaxa introuvable : `{ecotaxa_variable}`.")
    explicit_ecopart = _session_for_variable(thread_id, ecopart_variable)
    if ecopart_variable is not None and explicit_ecopart is None:
        return _ep_blocked(f"Variable EcoPart introuvable : `{ecopart_variable}`.")

    session_et = ecotaxa_session or explicit_ecotaxa or _store.get(f"{thread_id}:ecotaxa")
    if ecopart_variable is not None:
        session_ep = explicit_ecopart
    elif project_id is None:
        session_ep = _store.get(f"{thread_id}:ecopart")
    else:
        variable_name = dataset_variable_name("ecopart", project_id)
        session_ep = (
            _store.get(f"{thread_id}:dataset:{variable_name}")
            or _store.get(f"{thread_id}:ecopart:{project_id}")
        )

    missing = []
    if session_et is None:
        missing.append("EcoTaxa (`query_ecotaxa`)")
    if session_ep is None:
        if project_id is None:
            missing.append("EcoPart (`query_ecopart`)")
        else:
            missing.append(f"EcoPart (`query_ecopart(project_id={project_id})`)")
    if missing:
        return _ep_blocked(f"Données manquantes — charge d'abord : {' et '.join(missing)}.")

    df_et = session_et["df"].copy()
    df_ep = session_ep["df"].copy()
    selected_project_id = project_id or session_ep.get("meta", {}).get("project_id")

    if "Profile" not in df_ep.columns:
        return _ep_blocked("Colonne 'Profile' absente du dataset EcoPart — relance `query_ecopart`.")
    if "Depth [m]" not in df_ep.columns:
        return _ep_blocked("Colonne 'Depth [m]' absente du dataset EcoPart — relance `query_ecopart`.")
    ecopart_variables = [
        str(column) for column in df_ep.columns
        if column not in {"Profile", "Depth [m]"}
    ]

    # Candidate join keys, compared on real overlap with EcoPart profiles rather
    # than on the first row only — a single non-matching first row must not pick
    # the wrong key when other rows would match. We try several EcoTaxa shapes:
    # raw sample_id, sample_id/obj_orig_id stripped of the object suffix `_NNN`,
    # and the profile/station labels used by the remote resolver.
    profile_values = set(df_ep["Profile"].astype("string").dropna())
    candidates: list[tuple[str, pd.Series]] = []
    if "sample_id" in df_et.columns:
        sample_id = df_et["sample_id"].astype("string")
        candidates.append(("sample_id", sample_id))
        candidates.append(("sample_id (profil)", sample_id.str.replace(r"_\d+$", "", regex=True)))
    if "obj_orig_id" in df_et.columns:
        candidates.append((
            "obj_orig_id",
            df_et["obj_orig_id"].astype("string").str.replace(r"_\d+$", "", regex=True),
        ))
    for label_col in ("sample_profileid", "sample_stationid", "sample_station_name", "sample_cruise"):
        if label_col in df_et.columns:
            candidates.append((label_col, df_et[label_col].astype("string").str.strip()))

    if not candidates:
        available = ", ".join(df_et.columns[:20].tolist())
        return _ep_blocked(f"Colonne de jointure introuvable dans EcoTaxa. Colonnes disponibles : {available}")

    best_key, best_series, best_overlap = None, None, -1
    for name, series in candidates:
        overlap = int(series.isin(profile_values).sum())
        if overlap > best_overlap:
            best_key, best_series, best_overlap = name, series, overlap

    if best_overlap == 0:
        sample_et = ", ".join(sorted({str(v) for v in best_series.dropna().unique()})[:5])
        sample_ep = ", ".join(sorted({str(v) for v in profile_values})[:5])
        return _ep_empty(
            "Aucune correspondance entre les identifiants EcoTaxa et les profils EcoPart "
            f"(clé EcoTaxa essayée : `{best_key}`). "
            f"{len(profile_values)} profil(s) EcoPart vs {best_series.nunique()} clé(s) EcoTaxa. "
            f"Exemples EcoTaxa : {sample_et or '—'} · Exemples EcoPart : {sample_ep or '—'}. "
            "Vérifie que les deux jeux proviennent de la même campagne / du même projet."
        )

    df_et["_join_sample_id"] = best_series

    depth_col = next(
        (c for c in ("object_depth_min", "obj_depth_min", "depth_min", "depth") if c in df_et.columns),
        None,
    )
    if depth_col is None:
        available = ", ".join(df_et.columns[:20].tolist())
        return _ep_blocked(
            "Colonne de profondeur introuvable dans EcoTaxa "
            "(essayé : object_depth_min, obj_depth_min, depth_min, depth). "
            f"Colonnes disponibles : {available}"
        )

    depth_numeric = pd.to_numeric(df_et[depth_col], errors="coerce")
    df_et["_join_depth_bin"] = depth_bin_5m(depth_numeric)

    df_ep = df_ep.rename(columns={"Profile": "_join_sample_id"})
    # EcoPart can expose raw depth edges (e.g. 10 m) while EcoTaxa objects are
    # normalized to documented 5 m bin centres (12.5 m). Apply the same contract
    # on both sides before merging; pre-binned centres remain unchanged.
    df_ep["_join_depth_bin"] = depth_bin_5m(df_ep["Depth [m]"])
    df_ep = df_ep.drop(columns=["Depth [m]"])
    # Match the stringified EcoTaxa key so an int/str dtype mismatch never silently
    # zeroes the join.
    df_ep["_join_sample_id"] = df_ep["_join_sample_id"].astype("string")
    df_ep = df_ep.rename(
        columns={
            c: f"ecopart_{c}"
            for c in df_ep.columns
            if c not in ("_join_sample_id", "_join_depth_bin")
        }
    )
    df_ep = df_ep.drop_duplicates(subset=["_join_sample_id", "_join_depth_bin"])

    merged = df_et.merge(df_ep, on=["_join_sample_id", "_join_depth_bin"], how="left")
    if "sample_id" not in merged.columns:
        merged["sample_id"] = merged["_join_sample_id"]

    sentinel = next((c for c in merged.columns if c.startswith("ecopart_")), None)
    n_matched = int(merged[sentinel].notna().sum()) if sentinel else 0

    # Preserve sampled EcoPart bins that contain no EcoTaxa object. They become
    # explicit zero-object rows so the canonical sample-depth table can retain
    # true sampled zeros instead of silently dropping those bins.
    object_keys = df_et[["_join_sample_id", "_join_depth_bin"]].drop_duplicates()
    matched_profiles = set(best_series.dropna())
    missing_bins = df_ep.loc[
        df_ep["_join_sample_id"].isin(matched_profiles)
    ].merge(
        object_keys,
        on=["_join_sample_id", "_join_depth_bin"],
        how="left",
        indicator=True,
    )
    missing_bins = missing_bins.loc[missing_bins["_merge"] == "left_only"].drop(
        columns="_merge"
    )
    n_zero_object_bins = int(len(missing_bins))
    if n_zero_object_bins:
        if "sample_id" in df_et.columns:
            sample_map = df_et[["_join_sample_id", "sample_id"]].drop_duplicates()
            ambiguous = sample_map.groupby("_join_sample_id")["sample_id"].nunique()
            if (ambiguous > 1).any():
                return _ep_blocked(
                    "Bins EcoPart sans objet non conservés — plusieurs `sample_id` "
                    "correspondent à une même clé de profil."
                )
            missing_bins = missing_bins.merge(
                sample_map, on="_join_sample_id", how="left"
            )
        else:
            missing_bins["sample_id"] = missing_bins["_join_sample_id"]

        missing_bins = missing_bins.reset_index(drop=True)
        zero_rows = merged.iloc[:0].copy().reindex(range(n_zero_object_bins))
        for column in missing_bins.columns:
            if column in zero_rows.columns:
                zero_rows[column] = missing_bins[column].values
        merged = pd.concat([merged, zero_rows], ignore_index=True, sort=False)

    # Keep the 5 m bin used for the join as a first-class `depth_bin` column — the
    # m5/m6 density templates (skill uvp_ecotaxa) group by (sample_id, depth_bin,
    # sampled volume). Only the internal sample-key helper is dropped.
    merged = merged.rename(columns={"_join_depth_bin": "depth_bin"})
    merged = merged.drop(columns=["_join_sample_id"], errors="ignore")

    # A direct, mono-project enrichment can synthesize EcoPart bins with no
    # object row.  Those rows cannot inherit the export project from EcoTaxa,
    # yet they must remain attributable to the same project for the canonical
    # Filet↔UVP join.
    ecotaxa_project_id = (session_et.get("meta") or {}).get("project_id")
    if ecotaxa_project_id is not None:
        try:
            ecotaxa_project_id = int(ecotaxa_project_id)
        except (TypeError, ValueError):
            ecotaxa_project_id = None
    if ecotaxa_project_id is not None:
        if "export_project_id" in merged.columns:
            merged["export_project_id"] = pd.to_numeric(
                merged["export_project_id"], errors="coerce"
            ).fillna(ecotaxa_project_id).astype("Int64")
        else:
            merged["export_project_id"] = ecotaxa_project_id

    source = "join:ecotaxa+ecopart"
    if selected_project_id is not None:
        source = f"{source}:{selected_project_id}"
    joined_variable_name = (
        dataset_variable_name("ecotaxa_ecopart", selected_project_id)
        if selected_project_id is not None
        else dataset_variable_name("ecotaxa_ecopart")
    )
    dataset_id = (
        f"ecopart:{selected_project_id}"
        if selected_project_id is not None
        else "ecopart:session"
    )
    dataset_url = (
        f"https://ecopart.obs-vlfr.fr/prj/{selected_project_id}"
        if selected_project_id is not None
        else "https://ecopart.obs-vlfr.fr/searchsample"
    )
    n_unmatched = len(df_et) - n_matched
    provenance = build_enrichment_provenance(
        source="EcoTaxa + EcoPart",
        dataset_id=dataset_id,
        dataset_url=dataset_url,
        completed_at=datetime.now(timezone.utc),
        parameters={
            "join_type": "left",
            "depth_bin_width_m": 5.0,
            "depth_bin_center_offset_m": 2.5,
            "duplicate_policy": "first_by_sample_depth",
            "sampled_zero_object_bins": n_zero_object_bins,
        },
        resolved_schema={
            "columns": {
                "sample": best_key,
                "depth": depth_col,
                "ecopart_sample": "Profile",
                "ecopart_depth": "Depth [m]",
            },
            "resolution": {
                "sample": "maximum_overlap",
                "depth": "documented_alias_priority",
                "ecopart_sample": "required",
                "ecopart_depth": "required",
            },
        },
        variables=ecopart_variables,
        coverage={
            "total_rows": len(df_et),
            "matched_rows": n_matched,
            "match_rate": n_matched / len(df_et) if len(df_et) else 0.0,
            "status_counts": {
                "matched": n_matched,
                "unmatched": n_unmatched,
            },
        },
    )
    store_dataset(
        _store,
        thread_id,
        merged,
        variable_name=joined_variable_name,
        meta={
            "source": source,
            "ecopart_project_id": selected_project_id,
            "ecotaxa_project_id": ecotaxa_project_id,
            "n_rows": len(merged),
            "n_matched": n_matched,
            "n_zero_object_bins": n_zero_object_bins,
            "depth_col_used": depth_col,
            "provenance": provenance,
        },
        latest_alias=ECOTAXA_ECOPART,
    )
    project_note = (
        f" avec EcoPart {selected_project_id}" if selected_project_id is not None else ""
    )
    et_source_meta = dict((session_et or {}).get("meta") or {})
    ep_source_meta = dict((session_ep or {}).get("meta") or {})
    sources_block = "\nSources :\n" + render_sources(
        {"sources": [et_source_meta, ep_source_meta]}
    )
    proven_ep_urls = source_urls(ep_source_meta)
    canonical_source_line = (
        f"\nSource : {proven_ep_urls[0]}" if proven_ep_urls else ""
    )

    return _ep_success(
        f"Enrichissement terminé{project_note} — {len(merged)} lignes "
        f"({n_matched} matchées sur un bin EcoPart ; "
        f"{n_zero_object_bins} bin EcoPart sans objet conservé), "
        f"{len(merged.columns)} colonnes.\n"
        f"Clé de jointure : (sample_id, depth_bin) calculé depuis `{depth_col}`. "
        f"Bin conservé dans la colonne `depth_bin` (centre du bin 5 m).\n"
        f"Colonnes EcoPart préfixées `ecopart_` — `ecopart_Sampled volume [L]` est le volume "
        f"filtré du bin. Pour l'abondance/densité (m5/m6), grouper par bin "
        f"(`sample_id`, `depth_bin`) : densité = nb objets du bin / volume du bin, jamais "
        f"sum(objets)/sum(volume) global — voir skill `uvp_ecotaxa`.\n"
        f"Données disponibles dans `{joined_variable_name}` et `df_ecotaxa_ecopart` — "
        "une comparaison filet↔UVP auditée passe maintenant par la jointure "
        "certifiée locale ; les autres analyses peuvent continuer sur cette table."
        f"{sources_block}{canonical_source_line}\n"
        "Provenance : "
        + json.dumps(provenance, ensure_ascii=False, sort_keys=True),
        data_ref=joined_variable_name,
        persisted=True,
        method="EcoTaxa-EcoPart sample-depth join",
        metrics={
            "rows": len(merged),
            "matched": n_matched,
            "sampled_zero_object_bins": n_zero_object_bins,
        },
    )


def _candidate_ecotaxa_profile_labels(df_et: pd.DataFrame) -> list[str]:
    """Collect plausible profile/station labels from an EcoTaxa export."""
    labels: list[str] = []
    for col in (
        "sample_profileid", "sample_stationid", "sample_station_name", "sample_cruise",
        "sample_id", "obj_orig_id",
    ):
        if col not in df_et.columns:
            continue
        values = (
            df_et[col]
            .dropna()
            .astype("string")
            .str.strip()
            .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )
        for value in values:
            candidates = [value]
            if col in {"sample_id", "obj_orig_id"}:
                candidates.append(re.sub(r"_\d+$", "", value))
            for candidate in candidates:
                if candidate and candidate not in labels:
                    labels.append(candidate)
    return labels


def _preflight_ecopart_partition(
    dataframe: pd.DataFrame,
    *,
    client: EcopartClient,
    ecotaxa_project_id: int,
    ecopart_project_id: int,
    thread_id: str | None = None,
    request_timeout: float | None = None,
) -> dict[str, object]:
    """Check EcoPart exportability at the profile grain without exporting."""
    fingerprint = dataframe_fingerprint(dataframe)
    cache_key = (
        f"{thread_id}:ecopart_preflight:v5-profile:{ecotaxa_project_id}:{ecopart_project_id}"
        if thread_id else None
    )
    if cache_key:
        cached = _store.get(cache_key)
        cached_meta = dict((cached or {}).get("meta") or {})
        if (
            _fresh_cache_meta(cached_meta)
            and cached_meta.get("partition_fingerprint") == fingerprint
            and isinstance(cached_meta.get("result"), dict)
        ):
            return {**cached_meta["result"], "cache_hit": True}

    reasons: list[str] = []
    uncertain: list[str] = []

    key_columns = (
        "sample_id", "obj_orig_id", "sample_profileid", "sample_stationid",
        "sample_station_name", "sample_cruise",
    )
    if not any(
        column in dataframe.columns and dataframe[column].notna().any()
        for column in key_columns
    ):
        reasons.append("aucun identifiant de profil exploitable dans EcoTaxa")

    depth_column = next(
        (
            column for column in (
                "object_depth_min", "obj_depth_min", "depth_min", "depth"
            )
            if column in dataframe.columns
        ),
        None,
    )
    if depth_column is None:
        reasons.append("colonne de profondeur EcoTaxa absente")
    elif not pd.to_numeric(dataframe[depth_column], errors="coerce").notna().any():
        reasons.append(f"colonne `{depth_column}` sans profondeur numérique")

    # The actual join is EcoPart Profile ↔ EcoTaxa profile + depth bin.  Do not
    # turn a profile match into a requirement for ``filt_proj``: that endpoint
    # only returns samples explicitly linked to the EcoTaxa project and can be
    # empty for a valid profile-based campaign.
    profiles_checked = True
    try:
        search_kwargs = {"project_id": int(ecopart_project_id)}
        if request_timeout is not None:
            search_kwargs["timeout"] = float(request_timeout)
        project_profiles = client.search_samples(**search_kwargs)
    except Exception as exc:
        project_profiles = []
        profiles_checked = False
        uncertain.append(
            "liste des profils EcoPart indisponible "
            f"après {request_timeout or _ecopart_preflight_timeout():g} s : {type(exc).__name__}"
        )

    local_profiles: set[str] = set(_candidate_ecotaxa_profile_labels(dataframe))
    if "sample_id" in dataframe.columns:
        local_profiles.update(
            dataframe["sample_id"].dropna().astype("string")
            .str.replace(r"_\d+$", "", regex=True).astype(str)
        )
    if "obj_orig_id" in dataframe.columns:
        local_profiles.update(
            dataframe["obj_orig_id"].dropna().astype("string")
            .str.replace(r"_\d+$", "", regex=True).astype(str)
        )
    matching_profiles = [
        profile for profile in project_profiles
        if str(profile.get("name") or "").strip() in local_profiles
    ]
    if not matching_profiles and not uncertain:
        if project_profiles:
            # A profile label is a useful fast signal, but it is not the data
            # itself.  EcoTaxa and EcoPart can expose the same acquisition
            # under differently formatted identifiers.  Keep the check visible
            # without declaring the whole pair impossible before the actual
            # EcoPart table has been read and the canonical join attempted.
            uncertain.append(
                "aucun libellé de profil strictement identique au préflight : "
                f"0/{len(local_profiles)} identifiant(s) de profil EcoTaxa "
                f"retrouvé(s) parmi {len(project_profiles)} profil(s) accessibles "
                f"du projet EcoPart {ecopart_project_id}; les données EcoPart "
                "restent accessibles et la jointure réelle vérifiera les clés"
            )
        else:
            reasons.append(
                f"le projet EcoPart {ecopart_project_id} ne retourne aucun profil "
                "accessible pour le compte configuré"
            )

    visibility = [
        str(profile.get("visibility") or "").strip().upper()
        for profile in matching_profiles
    ]
    known_visibility = [value for value in visibility if value]
    exportable = [value for value in known_visibility if value.endswith("Y")]
    if known_visibility and not exportable:
        reasons.append(
            "aucun sample EcoPart exportable; statuts="
            + ",".join(sorted(set(known_visibility)))
        )
    elif matching_profiles and not known_visibility:
        uncertain.append("statut de validation EcoPart non communiqué")

    if reasons:
        verdict = "BLOQUÉ"
    elif uncertain:
        verdict = "PARTIEL"
    else:
        verdict = "PRÊT"
    result = {
        "verdict": verdict,
        "reason": "; ".join([*reasons, *uncertain]) or "export et jointure prévalidés",
        "matching_profiles": len(matching_profiles),
        "exportable_profiles": len(exportable),
        "ecotaxa_profile_candidates": len(local_profiles),
        "ecopart_project_profiles": len(project_profiles),
        "profiles_checked": profiles_checked,
        "cache_hit": False,
    }
    if cache_key:
        ttl = _ecopart_cache_ttl() if verdict != "PARTIEL" else 60.0
        _store.set(
            cache_key,
            None,
            {
                "source": "ecopart_preflight_cache",
                "partition_fingerprint": fingerprint,
                "cached_at": time.time(),
                "expires_at": time.time() + ttl,
                "result": result,
            },
        )
    return result


def _preflight_profile_status(preflight: dict[str, object]) -> str:
    """Describe profile availability without mistaking a timeout for zero rows."""
    if not bool(preflight.get("profiles_checked", True)):
        return "liste des profils EcoPart non obtenue (préflight non conclusif)"
    return (
        f"{preflight['exportable_profiles']}/{preflight['matching_profiles']} "
        "profils EcoPart correspondants exportables; "
        f"{preflight.get('ecopart_project_profiles', '?')} profils EcoPart examinés"
    )


# Global cache of resolved EcoTaxa project id -> resolution dict. The link is a
# stable server-side fact, so it is shared across threads/sessions. The user's
# workflow (find -> enrich -> density) otherwise re-resolves 2-3 times.
_ECOPART_RESOLUTION_CACHE: dict[int, dict] = {}


def _ecopart_id_from_project_title(title: object) -> int | None:
    """Extract only an explicitly labelled EcoPart id from an EcoTaxa title."""
    text = str(title or "").strip()
    if not text:
        return None
    match = re.search(
        r"\beco[\s_-]*part\b[^0-9]{0,24}(?:id|project|projet|#)\s*[:=#-]?\s*(\d+)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    project_id = int(match.group(1))
    return project_id if project_id > 0 else None


def _ensure_ecotaxa_project_loaded(thread_id: str, project_id: int) -> None:
    """Guard: load an EcoTaxa project into session if it is not already there.

    Makes `enrich_ecotaxa_with_ecopart_remote` self-sufficient when the caller
    named an EcoTaxa project but skipped `query_ecotaxa` first — a routing lapse
    that otherwise fails the whole turn. Loading the EcoTaxa source is a
    prerequisite of the enrichment the user has already confirmed. No-op if an
    EcoTaxa dataset is already in session.
    """
    if _store.get(f"{thread_id}:ecotaxa") is not None:
        return
    client = EcotaxaClient()
    client.login()
    job_id = client.start_export(project_id, {"statusfilter": "V"})
    client.wait_for_job(job_id)
    df = client.download_tsv(job_id)
    store_dataset(
        _store,
        thread_id,
        df,
        variable_name=dataset_variable_name("ecotaxa", project_id),
        meta={"source": f"ecotaxa:{project_id}", "project_id": project_id, "n_rows": len(df)},
        latest_alias=ECOTAXA,
    )


def _lookup_ecopart_project_for_ecotaxa(
    df_et: pd.DataFrame,
    *,
    known_ecotaxa_pid: int | None = None,
    bbox_margin: float = 0.05,
    max_candidates: int = 30,
    client: EcopartClient | None = None,
    thread_id: str | None = None,
    request_timeout: float | None = None,
) -> dict:
    """Resolve the EcoPart project matching an EcoTaxa dataframe **without** starting
    any export. Returns a dict `{project_id, project_name, resolution, error}`.

    Deterministic. Resolution order:
      1. cached result for `known_ecotaxa_pid` (instant, no HTTP);
      2. server `filt_proj=known_ecotaxa_pid` — the authoritative EcoTaxa↔EcoPart
         link (same one `start_export` uses), one search + one popover;
      3. fallback bbox scan (no project id known): candidates ordered by distance
         to the EcoTaxa centroid, first authoritative link wins, else profile /
         geographic majority with a lowest-id tie-break.
    """
    if known_ecotaxa_pid is not None:
        durable = load_resolution(int(known_ecotaxa_pid))
        if durable is not None and durable.status == "resolved" and durable.ecopart_project_id:
            result = {
                "project_id": durable.ecopart_project_id,
                "resolution": durable.resolution,
            }
            _ECOPART_RESOLUTION_CACHE[int(known_ecotaxa_pid)] = dict(result)
            return {**result, "cache_hit": True}
        persistent_key = (
            f"{thread_id}:ecopart_resolution:{int(known_ecotaxa_pid)}"
            if thread_id else None
        )
        if persistent_key:
            persisted = _store.get(persistent_key)
            persisted_meta = dict((persisted or {}).get("meta") or {})
            if (
                _fresh_cache_meta(persisted_meta)
                and isinstance(persisted_meta.get("result"), dict)
            ):
                result = dict(persisted_meta["result"])
                _ECOPART_RESOLUTION_CACHE[int(known_ecotaxa_pid)] = dict(result)
                return {**result, "cache_hit": True}
        cached = _ECOPART_RESOLUTION_CACHE.get(int(known_ecotaxa_pid))
        if cached is not None:
            if persistent_key:
                _store.set(
                    persistent_key,
                    None,
                    {
                        "source": "ecopart_resolution_cache",
                        "cached_at": time.time(),
                        "expires_at": time.time() + _ecopart_cache_ttl(),
                        "result": dict(cached),
                    },
                )
            return {**cached, "cache_hit": True}

    def _cache_and_return(result: dict) -> dict:
        if known_ecotaxa_pid is not None and "project_id" in result:
            save_resolution(
                int(known_ecotaxa_pid),
                ecopart_project_id=int(result["project_id"]),
                resolution=str(result.get("resolution") or "lien résolu"),
                status="resolved",
                ttl_seconds=_ecopart_resolution_cache_ttl(),
            )
            _ECOPART_RESOLUTION_CACHE[int(known_ecotaxa_pid)] = dict(result)
            if thread_id:
                _store.set(
                    f"{thread_id}:ecopart_resolution:{int(known_ecotaxa_pid)}",
                    None,
                    {
                        "source": "ecopart_resolution_cache",
                        "cached_at": time.time(),
                        "expires_at": time.time() + _ecopart_cache_ttl(),
                        "result": dict(result),
                    },
                )
        return result

    def _cache_transient_error(message: str) -> dict:
        result = {"error": message, "verdict": "PARTIEL"}
        if known_ecotaxa_pid is not None and thread_id:
            _store.set(
                f"{thread_id}:ecopart_resolution:{int(known_ecotaxa_pid)}",
                None,
                {
                    "source": "ecopart_resolution_cache",
                    "cached_at": time.time(),
                    "expires_at": time.time() + 60.0,
                    "result": result,
                },
            )
        return result

    lat_col = next(
        (c for c in ("object_lat", "sample_lat", "latitude", "lat") if c in df_et.columns),
        None,
    )
    lon_col = next(
        (c for c in ("object_lon", "sample_long", "longitude", "lon") if c in df_et.columns),
        None,
    )

    if client is None:
        try:
            client = EcopartClient()
            client.login()
        except Exception as exc:
            return {"error": f"Erreur EcoPart : {exc}"}

    # Fast, authoritative path: ask the server directly for the EcoPart samples
    # linked to this EcoTaxa project (filt_proj), then read one popover for the
    # EcoPart project id. Avoids the bbox scan and its per-sample popovers.
    if known_ecotaxa_pid is not None:
        try:
            search_kwargs = {"ecotaxa_project_id": int(known_ecotaxa_pid)}
            if request_timeout is not None:
                search_kwargs["timeout"] = float(request_timeout)
            linked = client.search_samples(**search_kwargs)
        except Exception as exc:
            # A dry-run must not turn one unavailable remote endpoint into a
            # long fallback chain (EcoTaxa title, bbox scan, multiple popovers).
            # The caller can retry later; no export has started at this stage.
            if request_timeout is not None:
                return _cache_transient_error(
                    "EcoPart n'a pas répondu pendant la vérification du lien "
                    f"après {request_timeout:g} s ({type(exc).__name__})"
                )
            linked = []
        ordered_linked = sorted(linked, key=lambda c: int(c.get("id", 0)))
        if request_timeout is not None:
            ordered_linked = ordered_linked[:3]
        for cand in ordered_linked:
            try:
                metadata_kwargs = {}
                if request_timeout is not None:
                    metadata_kwargs["timeout"] = float(request_timeout)
                meta = client.get_sample_metadata(cand["id"], **metadata_kwargs)
            except Exception:
                continue
            ep_pid = meta.get("ecopart_project_id")
            if ep_pid is None:
                continue
            return _cache_and_return({
                "project_id": int(ep_pid),
                "project_name": meta.get("ecopart_project_name") or None,
                "resolution": (
                    f"lien serveur EcoTaxa↔EcoPart (filt_proj, projet EcoTaxa "
                    f"{known_ecotaxa_pid}, profil `{meta.get('profile_id') or '?'}`)"
                ),
                "linked_samples": linked,
            })

        # Some EcoTaxa projects publish the corresponding EcoPart id directly
        # in their title, e.g. ``(Ecopart id 86)``. This remains deterministic:
        # only an explicitly labelled id is accepted, and its accessibility is
        # verified on EcoPart before it is returned or cached.
        try:
            ecotaxa_client = EcotaxaClient()
            ecotaxa_client.login()
            project_kwargs = (
                {"timeout": float(request_timeout)}
                if request_timeout is not None else {}
            )
            project = ecotaxa_client.get_project(
                int(known_ecotaxa_pid), **project_kwargs
            )
            project_title = project.get("title") or project.get("name")
            titled_ep_pid = _ecopart_id_from_project_title(project_title)
        except Exception:
            project_title = None
            titled_ep_pid = None
        if titled_ep_pid is not None:
            try:
                titled_search_kwargs = {"project_id": int(titled_ep_pid)}
                if request_timeout is not None:
                    titled_search_kwargs["timeout"] = float(request_timeout)
                titled_samples = client.search_samples(**titled_search_kwargs)
            except Exception:
                titled_samples = []
            if titled_samples:
                return _cache_and_return({
                    "project_id": int(titled_ep_pid),
                    "project_name": None,
                    "resolution": (
                        "ID EcoPart explicite dans le titre EcoTaxa "
                        f"`{project_title}`; accessibilité vérifiée"
                    ),
                    "linked_samples": titled_samples,
                })
        # A timed-out project-wide lookup must not prevent the much smaller
        # profile/position fallback below.  This matters for large UVP projects:
        # the exact profile is a stronger join key than a slow project listing.

    profile_labels = set(_candidate_ecotaxa_profile_labels(df_et))
    station_labels = set()
    for station_column in ("sample_stationid", "sample_station_name", "station_id"):
        if station_column in df_et.columns:
            station_labels.update(
                str(value).strip()
                for value in df_et[station_column].dropna().tolist()
                if str(value).strip()
            )

    if lat_col is None or lon_col is None:
        if not profile_labels:
            return {"error": "Pas de coordonnées ni de labels de profil dans le fichier EcoTaxa."}
        try:
            candidates = client.search_samples()
        except Exception as exc:
            return {"error": f"Erreur de recherche EcoPart par profil : {exc}"}
        search_note = "profil"
    else:
        lat = pd.to_numeric(df_et[lat_col], errors="coerce").dropna()
        lon = pd.to_numeric(df_et[lon_col], errors="coerce").dropna()
        if lat.empty or lon.empty:
            return {"error": "Coordonnées lat/lon illisibles dans le fichier EcoTaxa."}
        try:
            candidates = client.search_samples_by_bbox(
                north=float(lat.max()) + bbox_margin,
                south=float(lat.min()) - bbox_margin,
                west=float(lon.min()) - bbox_margin,
                east=float(lon.max()) + bbox_margin,
            )
        except Exception as exc:
            return {"error": f"Erreur de recherche EcoPart par bbox : {exc}"}
        search_note = "bbox"

    if not candidates:
        return {"error": "Aucun sample EcoPart trouvé pour le fichier EcoTaxa."}

    # Order candidates closest-to-centroid first: an EcoTaxa's own EcoPart
    # profiles sit at its coordinates, so the authoritative link surfaces within
    # a few candidates even when its sample ids are high. Plain id order would
    # bury it and scan only unrelated low-id projects sharing the bbox (the bug
    # where 14853 resolved to 59 instead of its real project 1063). Id breaks
    # ties; falls back to id order when candidates carry no coordinates.
    if lat_col is not None and lon_col is not None:
        clat = float(pd.to_numeric(df_et[lat_col], errors="coerce").dropna().mean())
        clon = float(pd.to_numeric(df_et[lon_col], errors="coerce").dropna().mean())

        def _dist_key(c: dict) -> tuple:
            try:
                return (
                    (float(c.get("lat", 0.0)) - clat) ** 2
                    + (float(c.get("lon", 0.0)) - clon) ** 2,
                    int(c.get("id", 0)),
                )
            except Exception:
                return (float("inf"), int(c.get("id", 0)))

        ordered = sorted(candidates, key=_dist_key)[: int(max_candidates)]
    else:
        ordered = sorted(candidates, key=lambda c: int(c.get("id", 0)))[: int(max_candidates)]

    # Per EcoPart project, tally profile matches and candidate count as fallback.
    votes: dict[int, list[int]] = {}
    names: dict[int, str] = {}
    for cand in ordered:
        try:
            meta = client.get_sample_metadata(cand["id"])
        except Exception:
            continue
        ep_pid = meta.get("ecopart_project_id")
        if ep_pid is None:
            continue
        ep_pid = int(ep_pid)
        pf = str(meta.get("profile_id") or "").strip()
        station = str(meta.get("station_id") or "").strip()
        et_pid = meta.get("ecotaxa_project_id")
        # Authoritative EcoTaxa↔EcoPart link: definitive — return immediately.
        if known_ecotaxa_pid is not None and et_pid is not None and int(et_pid) == int(known_ecotaxa_pid):
            return _cache_and_return({
                "project_id": ep_pid,
                "project_name": meta.get("ecopart_project_name") or None,
                "resolution": (
                    f"lien EcoTaxa↔EcoPart (projet EcoTaxa {known_ecotaxa_pid}, profil `{pf}`)"
                ),
            })
        tally = votes.setdefault(ep_pid, [0, 0, 0])
        if pf and pf in profile_labels:
            tally[1] += 1
            if station and station in station_labels:
                tally[0] += 1
        tally[2] += 1
        names.setdefault(ep_pid, meta.get("ecopart_project_name") or "")

    if not votes:
        return {"error": "Aucun sample EcoPart exploitable (project_id illisible)."}

    # No authoritative link found: prefer profile matches, then candidate count;
    # lowest project id breaks ties so the result is stable across runs.
    best_pid = max(votes, key=lambda pid: (votes[pid][0], votes[pid][1], votes[pid][2], -pid))
    exact, mid, weak = votes[best_pid]
    if mid:
        how = (
            f"correspondance profil+station ({exact} sample(s))"
            if exact
            else f"correspondance de profil ({mid} sample(s) sur {weak})"
        )
    else:
        how = f"proximité géographique par {search_note} ({weak} sample(s), aucun lien EcoTaxa direct)"
    return _cache_and_return({
        "project_id": best_pid,
        "project_name": names.get(best_pid) or None,
        "resolution": how,
    })


def _enrich_ecotaxa_campaign_with_ecopart(
    thread_id: str,
    session_et: dict,
    client: EcopartClient,
    *,
    confirmed: bool,
) -> tuple:
    """Resolve and enrich each project partition of a consolidated campaign."""
    campaign_df = session_et["df"]
    source_variable = (session_et.get("meta") or {}).get("variable_name")
    numeric_project_ids = pd.to_numeric(
        campaign_df["export_project_id"], errors="coerce"
    )
    valid_project_ids = (
        numeric_project_ids.notna()
        & numeric_project_ids.mod(1).eq(0)
        & numeric_project_ids.gt(0)
    )
    project_ids = numeric_project_ids.loc[valid_project_ids]
    normalized_project_ids = sorted({int(project_id) for project_id in project_ids})
    n_invalid_project_rows = int((~valid_project_ids).sum())
    if not normalized_project_ids:
        invalid_note = (
            f" {n_invalid_project_rows} ligne(s) avec `export_project_id` invalide."
            if n_invalid_project_rows
            else ""
        )
        return _ep_blocked(
            "Campagne EcoTaxa invalide — `export_project_id` ne contient aucun "
            f"identifiant de projet exploitable.{invalid_note}"
        )

    campaign_cache_key = build_result_cache_key(
        campaign_df,
        {
            "ecotaxa_project_ids": normalized_project_ids,
            "operation": "ecotaxa_campaign_ecopart_join",
        },
    )
    if confirmed:
        cached = load_result("ecopart_campaign_enrichment", campaign_cache_key)
        if cached is not None:
            campaign_variable = dataset_variable_name(
                "ecotaxa_ecopart", "campaign", "cached", uuid.uuid4().hex[:8]
            )
            cached_df = cached.dataframe
            meta = {
                "source": "join:ecotaxa_campaign+ecopart",
                "source_variable": source_variable,
                "partial_enrichment": False,
                "project_failures": [],
                "failed_project_ids": [],
                "projects_failed": 0,
                "invalid_export_project_rows": 0,
                "n_rows": len(cached_df),
                "cache_hit": True,
                "cached_at": cached.cached_at,
                "cache_provenance": cached.provenance,
            }
            store_dataset(
                _store,
                thread_id,
                cached_df,
                variable_name=campaign_variable,
                meta=meta,
                latest_alias=ECOTAXA_ECOPART,
            )
            return _ep_success(
                "Enrichissement EcoTaxa–EcoPart de campagne restauré depuis le "
                f"cache exact — {len(cached_df)} lignes et "
                f"{len(normalized_project_ids)} projets; aucune ligne écartée. "
                f"Table active : `{campaign_variable}` (récupérée le {cached.cached_at}).",
                data_ref=campaign_variable,
                persisted=True,
                provenance=cached.provenance,
                method="Cached exact partitioned EcoTaxa-EcoPart enrichment",
                metrics={
                    "rows": len(cached_df),
                    "projects": len(normalized_project_ids),
                    "projects_succeeded": len(normalized_project_ids),
                    "projects_failed": 0,
                    "cache_hit": True,
                },
            )

    resolved: list[tuple[int, int, pd.DataFrame, str]] = []
    failures: list[str] = []
    failed_project_ids: set[int] = set()
    resolution_partial_count = 0
    if n_invalid_project_rows:
        failures.append(
            f"BLOQUÉ — {n_invalid_project_rows} ligne(s) avec `export_project_id` invalide "
            "ignorée(s)."
        )
    for ecotaxa_pid in normalized_project_ids:
        partition = campaign_df.loc[numeric_project_ids == ecotaxa_pid].copy()
        resolution = _lookup_ecopart_project_for_ecotaxa(
            partition,
            known_ecotaxa_pid=ecotaxa_pid,
            client=client,
            thread_id=thread_id,
            request_timeout=(
                _ecopart_preflight_timeout() if not confirmed else None
            ),
        )
        if "error" in resolution:
            failed_project_ids.add(ecotaxa_pid)
            is_partial = resolution.get("verdict") == "PARTIEL"
            resolution_partial_count += int(is_partial)
            cache_note = " (cache court)" if resolution.get("cache_hit") else ""
            failures.append(
                f"{'PARTIEL' if is_partial else 'BLOQUÉ'} — EcoTaxa "
                f"{ecotaxa_pid} : {resolution['error']}{cache_note}"
            )
            continue
        ecopart_pid = int(resolution["project_id"])
        resolved.append((
            ecotaxa_pid,
            ecopart_pid,
            partition,
            str(resolution.get("resolution") or "lien résolu"),
        ))

    if not confirmed:
        preflights = [
            (
                ecotaxa_pid,
                ecopart_pid,
                resolution,
                _preflight_ecopart_partition(
                    partition,
                    client=client,
                    ecotaxa_project_id=ecotaxa_pid,
                    ecopart_project_id=ecopart_pid,
                    thread_id=thread_id,
                    request_timeout=_ecopart_preflight_timeout(),
                ),
            )
            for ecotaxa_pid, ecopart_pid, partition, resolution in resolved
        ]
        mappings = [
            f"- EcoTaxa {ecotaxa_pid} → EcoPart {ecopart_pid} : "
            f"{preflight['verdict']} — {preflight['reason']} "
            f"({_preflight_profile_status(preflight)}; "
            f"{resolution})"
            for ecotaxa_pid, ecopart_pid, resolution, preflight in preflights
        ]
        failure_lines = [f"- {failure}" for failure in failures]
        ready_count = sum(
            preflight["verdict"] == "PRÊT"
            for _ecotaxa_pid, _ecopart_pid, _resolution, preflight in preflights
        )
        partial_count = resolution_partial_count + sum(
            preflight["verdict"] == "PARTIEL"
            for _ecotaxa_pid, _ecopart_pid, _resolution, preflight in preflights
        )
        blocked_count = len(normalized_project_ids) - ready_count - partial_count
        coverage = f"{ready_count}/{len(normalized_project_ids)} projets prêts"
        return _ep_blocked(
            "Préflight d'enrichissement EcoPart de campagne (dry-run) — "
            f"{coverage}.\n"
            + "\n".join([*mappings, *failure_lines])
            + "\nOpération lourde : un export EcoPart et une jointure "
            "(sample_id, depth_bin) seront exécutés par projet. "
            "Aucune donnée téléchargée pour l'instant.\n"
            + (
                "Confirme pour lancer avec `confirmed=True`."
                if ready_count == len(normalized_project_ids)
                else "Ne confirme pas tant que les verdicts PARTIEL/BLOQUÉ ne sont pas résolus."
            ),
            metrics={
                "projects": len(normalized_project_ids),
                "projects_resolved": len(resolved),
                "projects_failed": len(failed_project_ids),
                "projects_ready": ready_count,
                "projects_partial": partial_count,
                "projects_blocked": blocked_count,
                "invalid_export_project_rows": n_invalid_project_rows,
            },
        )

    joined_frames: list[pd.DataFrame] = []
    artifact_refs: list[str] = []
    successes: list[str] = []
    successful_pairs: list[tuple[int, int]] = []
    partition_provenance: dict[str, dict] = {}
    n_matched = 0
    for ecotaxa_pid, ecopart_pid, partition, _resolution in resolved:
        try:
            cached_tsv = find_ecopart_tsv(
                ecopart_project_id=ecopart_pid,
                profile_labels=set(_candidate_ecotaxa_profile_labels(partition)),
            )
            artifact_url: str | None = None
            if cached_tsv is not None:
                df_ep = load_ecopart_tsv(cached_tsv)
                source_label = "cache local"
            else:
                # A resolved EcoPart project is exported at its profile grain;
                # the local canonical join keeps only matching EcoTaxa profiles.
                links = client.start_export(project_id=ecopart_pid)
                df_ep = client.download_tsv(links)
                if df_ep.empty:
                    failed_project_ids.add(ecotaxa_pid)
                    failures.append(
                        f"EcoTaxa {ecotaxa_pid} → EcoPart {ecopart_pid} — "
                        "aucun profil EcoPart exporté."
                    )
                    continue
                file_id = uuid.uuid4().hex
                output_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
                df_ep.to_csv(output_path, sep="\t", index=False)
                artifact_url = download_url(output_path.name)
                try:
                    import_ecopart_tsv(
                        output_path,
                        provenance="remote_export",
                        ecopart_project_id=ecopart_pid,
                        ecotaxa_project_id=ecotaxa_pid,
                    )
                except ValueError:
                    pass
                source_label = "export EcoPart"
            if df_ep.empty:
                failed_project_ids.add(ecotaxa_pid)
                failures.append(
                    f"EcoTaxa {ecotaxa_pid} → EcoPart {ecopart_pid} — "
                    "aucun profil EcoPart exporté."
                )
                continue

            variable_name = dataset_variable_name("ecopart", ecopart_pid)
            meta = {
                "source": (
                    f"ecopart_cache:{cached_tsv.provenance}"
                    if cached_tsv is not None else f"ecopart:{ecopart_pid}"
                ),
                "project_id": ecopart_pid,
                "ecotaxa_project_id": ecotaxa_pid,
                "n_rows": len(df_ep),
                "cache_hit": cached_tsv is not None,
                "content_sha256": (
                    cached_tsv.content_sha256 if cached_tsv is not None else None
                ),
            }
            store_dataset(
                _store,
                thread_id,
                df_ep,
                variable_name=variable_name,
                meta=meta,
                latest_alias=ECOPART,
            )
            _store.set(f"{thread_id}:ecopart:{ecopart_pid}", df_ep, meta)

            join_result = _perform_enrichment(
                thread_id,
                ecopart_pid,
                ecotaxa_session={
                    "df": partition,
                    "meta": session_et.get("meta") or {},
                },
            )
            join_artifact = validate_tool_artifact(join_result[1])
            if join_artifact.status != "success":
                failed_project_ids.add(ecotaxa_pid)
                failures.append(
                    f"EcoTaxa {ecotaxa_pid} → EcoPart {ecopart_pid} — "
                    f"{join_result[0]}"
                )
                continue

            joined_session = _store.get(f"{thread_id}:{ECOTAXA_ECOPART}")
            if joined_session is None or joined_session.get("df") is None:
                failed_project_ids.add(ecotaxa_pid)
                failures.append(
                    f"EcoTaxa {ecotaxa_pid} → EcoPart {ecopart_pid} — "
                    "la jointure annoncée n'a pas été persistée."
                )
                continue
            joined = joined_session["df"].copy()
            # Zero-object EcoPart bins are synthesized by the join and therefore do
            # not inherit EcoTaxa columns. Re-attach both project identifiers to
            # every output row, including those explicit sampled-zero bins.
            joined["export_project_id"] = ecotaxa_pid
            joined["ecopart_project_id"] = ecopart_pid
            joined_frames.append(joined)
            successful_pairs.append((ecotaxa_pid, ecopart_pid))
            partition_provenance[f"{ecotaxa_pid}:{ecopart_pid}"] = dict(
                (joined_session.get("meta") or {}).get("provenance") or {}
            )
            if artifact_url:
                artifact_refs.append(artifact_url)
            partition_matched = int(join_artifact.metrics.get("matched", 0))
            n_matched += partition_matched
            successes.append(
                f"EcoTaxa {ecotaxa_pid} → EcoPart {ecopart_pid} : "
                f"{len(joined)} lignes, {partition_matched} matchées ({source_label})"
            )
        except EcopartExportError as exc:
            failed_project_ids.add(ecotaxa_pid)
            failures.append(
                _format_ecopart_export_error(
                    exc,
                    project_id=ecopart_pid,
                    ecotaxa_project_id=ecotaxa_pid,
                )
            )
            continue
        except _RECOVERABLE_PARTITION_ERRORS as exc:
            failed_project_ids.add(ecotaxa_pid)
            failures.append(
                f"EcoTaxa {ecotaxa_pid} → EcoPart {ecopart_pid} — "
                f"échec de la partition : {exc}"
            )
            continue

    if not joined_frames:
        detail = "\n".join(f"- {failure}" for failure in failures)
        return _ep_error(
            "Enrichissement EcoPart de campagne échoué — "
            f"0/{len(normalized_project_ids)} projets enrichis.\n{detail}",
            retryable=True,
            metrics={
                "projects": len(normalized_project_ids),
                "projects_succeeded": 0,
                "projects_failed": len(failed_project_ids),
                "invalid_export_project_rows": n_invalid_project_rows,
            },
        )

    combined = pd.concat(joined_frames, ignore_index=True, sort=False)
    campaign_variable = dataset_variable_name("ecotaxa_ecopart", "campaign")
    project_pairs = [
        {
            "ecotaxa_project_id": ecotaxa_pid,
            "ecopart_project_id": ecopart_pid,
        }
        for ecotaxa_pid, ecopart_pid in successful_pairs
    ]
    partial = bool(failures)
    meta = {
        "source": "join:ecotaxa_campaign+ecopart",
        "source_variable": source_variable,
        "project_pairs": project_pairs,
        "partial_enrichment": partial,
        "project_failures": failures,
        "failed_project_ids": sorted(failed_project_ids),
        "projects_failed": len(failed_project_ids),
        "invalid_export_project_rows": n_invalid_project_rows,
        "partition_provenance": partition_provenance,
        "n_rows": len(combined),
        "n_matched": n_matched,
    }
    store_dataset(
        _store,
        thread_id,
        combined,
        variable_name=campaign_variable,
        meta=meta,
        latest_alias=ECOTAXA_ECOPART,
    )
    if not partial:
        cache_provenance = {
            "source": "EcoPart",
            "project_pairs": project_pairs,
            "join_method": "partitioned sample_id+depth_bin",
        }
        saved = save_result(
            "ecopart_campaign_enrichment",
            campaign_cache_key,
            combined,
            provenance=cache_provenance,
        )
        cache_meta = {
            "cache_hit": False,
            "cached_at": saved.cached_at,
            "cache_provenance": cache_provenance,
        }
        for store_key in (
            thread_id,
            f"{thread_id}:{ECOTAXA_ECOPART}",
            f"{thread_id}:dataset:{campaign_variable}",
        ):
            _store.update_meta(store_key, cache_meta)

    status = "partiel" if partial else "terminé"
    lines = [
        f"Enrichissement EcoPart de campagne {status} — "
        f"{len(joined_frames)}/{len(normalized_project_ids)} projets enrichis, "
        f"{len(combined)} lignes consolidées.",
        *[f"- Succès : {item}" for item in successes],
        *[f"- Échec : {failure}" for failure in failures],
        f"Données disponibles dans `{campaign_variable}` et `df_ecotaxa_ecopart`.",
    ]
    return _ep_success(
        "\n".join(lines),
        data_ref=campaign_variable,
        artifact_refs=artifact_refs,
        persisted=True,
        method="Partitioned EcoTaxa campaign-EcoPart export and join",
        metrics={
            "rows": len(combined),
            "matched": n_matched,
            "projects": len(normalized_project_ids),
            "projects_succeeded": len(joined_frames),
            "projects_failed": len(failed_project_ids),
            "invalid_export_project_rows": n_invalid_project_rows,
        },
    )


def make_ecopart_tools(thread_id: str) -> list:
    """Create LangChain EcoPart tools for one thread."""
    try:
        bootstrap_consumer_cache(cache_root())
    except CacheBundleValidationError as exc:
        _LOGGER.warning("Cache EcoPart partagé indisponible : %s", exc)

    @tool(response_format="content_and_artifact")
    def list_ecopart_samples(project_id: int) -> str:
        """Liste les échantillons EcoPart disponibles pour un projet."""
        try:
            client = EcopartClient()
            client.login()
            samples = client.list_samples(project_id)
        except Exception as exc:
            return _ep_error(f"Erreur EcoPart : {exc}", retryable=True)
        if not samples:
            return _ep_empty("Aucun échantillon EcoPart trouvé.")
        return _ep_success(
            pd.DataFrame(samples).to_markdown(index=False),
            provenance={"project_id": int(project_id)},
            metrics={"samples": len(samples)},
        )

    @tool(response_format="content_and_artifact")
    def preview_ecopart_sample(sample_id: int) -> str:
        """Prévisualise un échantillon EcoPart, depuis le cache si disponible."""
        cached_preview = load_sample_preview(sample_id)
        if cached_preview is not None:
            if not cached_preview.accessible:
                return _ep_blocked(f"Échantillon {sample_id} non accessible (cache local).")
            summary = cached_preview.text or f"Échantillon {sample_id} — aucun texte disponible."
            return _ep_success(
                f"{summary}\n\n_Aperçu issu du cache local partagé._",
                provenance={"sample_id": int(sample_id), "cache_hit": True},
            )
        try:
            client = EcopartClient()
            client.login()
            preview = client.preview_sample(sample_id)
        except Exception as exc:
            return _ep_error(f"Erreur EcoPart : {exc}", retryable=True)
        save_sample_preview(
            sample_id,
            accessible=bool(preview["accessible"]),
            text=str(preview.get("text") or ""),
        )
        if not preview["accessible"]:
            return _ep_blocked(f"Échantillon {sample_id} non accessible.")
        summary = preview["text"] or f"Échantillon {sample_id} — aucun texte disponible."
        return _ep_success(summary, provenance={"sample_id": int(sample_id)})

    @tool(response_format="content_and_artifact")
    def query_ecopart(
        project_id: int,
        ctd_vars: list[str] | None = None,
        gpr_vars: list[str] | None = None,
    ) -> str:
        """Exporte un projet EcoPart complet et écrit un TSV téléchargeable."""
        try:
            client = EcopartClient()
            client.login()
            links = client.start_export(project_id, ctd_vars, gpr_vars)
            df = client.download_tsv(links)
            file_id = uuid.uuid4().hex
            output_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
            df.to_csv(output_path, sep="\t", index=False)
            try:
                cached_export = import_ecopart_tsv(
                    output_path,
                    provenance="remote_export",
                    ecopart_project_id=project_id,
                )
            except ValueError:
                cached_export = None
            variable_name = dataset_variable_name("ecopart", project_id)
            meta = {
                "source": f"ecopart:{project_id}",
                "project_id": project_id,
                "n_rows": len(df),
                **(
                    {
                        "content_sha256": cached_export.content_sha256,
                        "cache_provenance": cached_export.provenance,
                    }
                    if cached_export is not None
                    else {}
                ),
            }
            store_dataset(
                _store,
                thread_id,
                df,
                variable_name=variable_name,
                meta=meta,
                latest_alias=ECOPART,
            )
            # Keep the pre-registry project key readable by existing sessions/tools.
            _store.set(f"{thread_id}:ecopart:{project_id}", df, meta)
            artifact_url = download_url(output_path.name)
            summary = (
                f"EcoPart chargé — {len(df)} lignes.\n"
                f"Données disponibles dans `{variable_name}` "
                f"et `df_ecopart` (dernier projet chargé).\n"
                f"Appelle run_pandas directement pour analyser.\n"
                f"Télécharger : {artifact_url}"
            )
            return _ep_success(
                summary,
                data_ref=variable_name,
                artifact_refs=(artifact_url,),
                provenance={"project_id": int(project_id)},
                persisted=True,
                method="EcoPart export",
                metrics={"rows": len(df)},
            )
        except EcopartExportError as exc:
            return _ep_error(
                _format_ecopart_export_error(exc, project_id=project_id),
                provenance={"project_id": int(project_id)},
                retryable=True,
            )
        except Exception as exc:
            return _ep_error(f"Erreur EcoPart : {exc}", retryable=True)

    @tool(response_format="content_and_artifact")
    def join_ecotaxa_ecopart(
        project_id: int | None = None,
        ecotaxa_variable: str | None = None,
        ecopart_variable: str | None = None,
    ) -> str:
        """Enrichit localement EcoTaxa avec EcoPart par (sample_id, depth_bin).

        Les deux datasets doivent déjà être chargés. Pour deux fichiers locaux,
        passe leurs variables persistées dans ``ecotaxa_variable`` et
        ``ecopart_variable`` et omets ``project_id``. Utilise ``project_id``
        seulement pour sélectionner un projet EcoPart numérique déjà chargé.
        """
        return _perform_enrichment(
            thread_id,
            project_id,
            ecotaxa_variable=ecotaxa_variable,
            ecopart_variable=ecopart_variable,
        )

    @tool(response_format="content_and_artifact")
    def audit_ecotaxa_ecopart_join(
        source_variable: str = "df_ecotaxa_ecopart",
    ) -> str:
        """Contrôle une jointure EcoTaxa–EcoPart persistée sans la reconstruire.

        Utilise cet outil après ``join_ecotaxa_ecopart`` pour vérifier la colonne
        de profondeur officielle, les identifiants objet, les volumes, les clés
        sample–bin et la distance au centre des bins de 5 m.
        """
        session = _session_for_variable(thread_id, source_variable)
        if session is None and source_variable == "df_ecotaxa_ecopart":
            session = _store.get(f"{thread_id}:ecotaxa_ecopart")
        if session is None:
            return _ep_blocked(f"Variable de jointure introuvable : `{source_variable}`.")

        audit = audit_ecotaxa_ecopart_dataframe(
            session["df"], session.get("meta") or {}
        )
        verdict = "VALIDÉ" if audit["verdict"] == "validated" else "REFUSÉ"
        anomalies = ", ".join(audit["anomalies"]) or "aucune"
        summary = (
            f"Verdict : {verdict}\n"
            f"Variable contrôlée : `{source_variable}`\n"
            f"Colonne de profondeur : `{audit['depth_column']}`\n"
            f"Lignes : {audit['n_rows']} ; appariées : {audit['n_matched']}\n"
            f"Clés sample–bin : {audit['n_sample_depth_bins']}\n"
            f"Doublons object_id : {audit['duplicate_object_ids']}\n"
            f"Bins échantillonnés sans objet : {audit['sampled_zero_object_bins']}\n"
            f"Volumes manquants : {audit['missing_volume_rows']} ; "
            f"non positifs : {audit['non_positive_volume_rows']} ; "
            f"bins contradictoires : {audit['conflicting_volume_bins']}\n"
            f"Objets hors bin 5 m : {audit['objects_outside_5m_bin']} ; "
            f"écart maximal au centre : {audit['max_depth_distance_m']} m\n"
            f"Anomalies : {anomalies}"
        )
        factory = _ep_success if audit["verdict"] == "validated" else _ep_blocked
        return factory(
            summary,
            data_ref=source_variable,
            persisted=True,
            method="EcoTaxa-EcoPart join audit",
            metrics={"rows": int(audit["n_rows"]), "matched": int(audit["n_matched"])},
        )

    @tool(response_format="content_and_artifact")
    def enrich_ecotaxa_with_ecopart_remote(
        ecotaxa_project_id: int | None = None,
        ecopart_project_id: int | None = None,
        confirmed: bool = True,
    ) -> str:
        """Enrichit l'EcoTaxa en session avec les variables EcoPart téléchargées **à distance**.

        Workflow : (1) résout puis télécharge le projet EcoPart au grain profil,
        (2) joint les profils communs sur (sample_id, depth_bin) avec l'EcoTaxa
        déjà en session.

        Pré-requis : un EcoTaxa doit être en session (load_file UVP ou query_ecotaxa).
        Pré-requis ID : passer `ecotaxa_project_id` (recommandé) OU `ecopart_project_id`.
        Si aucun n'est fourni, l'outil tente de lire `meta.project_id` posé par `query_ecotaxa`.

        L'enrichissement démarre directement par défaut. `confirmed=False` →
        préflight explicite sans téléchargement : lien EcoTaxa→EcoPart, accessibilité et
        validation des profils EcoPart, identifiant de profil et profondeur
        nécessaires à la jointure, avec verdict PRÊT / PARTIEL / BLOQUÉ par
        projet. La vérification distante de la liste des profils peut prendre
        jusqu'à 60 secondes.
        """
        session_et = _ecotaxa_session_for_project(thread_id, ecotaxa_project_id)
        if session_et is None:
            if not confirmed:
                if ecotaxa_project_id is None:
                    return _ep_blocked(
                        "Données EcoTaxa manquantes — charge d'abord un fichier UVP "
                        "(`load_file`) ou `query_ecotaxa`."
                    )
                return _ep_blocked(
                    "Préflight d'enrichissement EcoPart (dry-run) — BLOQUÉ.\n"
                    f"Le projet EcoTaxa {ecotaxa_project_id} n'est pas chargé : "
                    "impossible de vérifier les objets, les profondeurs et la clé "
                    "de jointure. Charge d'abord le projet EcoTaxa, puis relance "
                    "le dry-run. Aucune donnée téléchargée."
                )
            # Guard: the caller named an EcoTaxa project but no EcoTaxa is loaded
            # (query_ecotaxa was skipped). Auto-load it so this confirmed
            # enrichment is self-sufficient instead of failing the turn.
            if ecotaxa_project_id is not None:
                try:
                    _ensure_ecotaxa_project_loaded(thread_id, int(ecotaxa_project_id))
                except Exception as exc:
                    return _ep_error(
                        f"Le projet EcoTaxa {ecotaxa_project_id} n'a pas pu être chargé "
                        f"automatiquement : {exc}",
                        retryable=True,
                    )
                session_et = _ecotaxa_session_for_project(
                    thread_id,
                    ecotaxa_project_id,
                )
            if session_et is None:
                return _ep_blocked("Données EcoTaxa manquantes — charge d'abord un fichier UVP (`load_file`) ou `query_ecotaxa`.")

        if ecotaxa_project_id is None and ecopart_project_id is None:
            ecotaxa_project_id = session_et.get("meta", {}).get("project_id")

        campaign_df = session_et.get("df")
        is_campaign = (
            ecotaxa_project_id is None
            and ecopart_project_id is None
            and isinstance(campaign_df, pd.DataFrame)
            and "export_project_id" in campaign_df.columns
        )
        # Avoid an upstream request when neither an explicit/recorded project
        # nor enough local metadata exists to resolve one. This produces a
        # useful local diagnostic even while EcoPart is unavailable.
        if not is_campaign and ecotaxa_project_id is None and ecopart_project_id is None:
            candidate_labels = _candidate_ecotaxa_profile_labels(session_et["df"])
            has_coordinates = any(
                column in session_et["df"].columns
                for column in (
                    "object_lat", "sample_lat", "latitude", "lat",
                    "object_lon", "sample_long", "longitude", "lon",
                )
            )
            if not candidate_labels and not has_coordinates:
                return _ep_blocked(
                    "Résolution EcoPart automatique impossible — aucun projet EcoTaxa "
                    "ni métadonnée locale (coordonnées ou profil) n'est disponible. "
                    "Fournis `ecotaxa_project_id` ou `ecopart_project_id`."
                )

        try:
            client = EcopartClient()
            client.login()
        except Exception as exc:
            return _ep_error(f"Erreur EcoPart : {exc}", retryable=True)

        if is_campaign:
            return _enrich_ecotaxa_campaign_with_ecopart(
                thread_id,
                session_et,
                client,
                confirmed=confirmed,
            )

        resolution_note = ""
        if ecotaxa_project_id is None and ecopart_project_id is None:
            # Same deterministic resolver as find_ecopart_project_for_ecotaxa, so
            # the preview and the actual enrichment always agree on the project.
            result = _lookup_ecopart_project_for_ecotaxa(
                session_et["df"],
                thread_id=thread_id,
                request_timeout=_ecopart_preflight_timeout(),
            )
            if "error" in result:
                transient = result.get("verdict") == "PARTIEL"
                factory = _ep_error if transient else _ep_blocked
                return factory(
                    f"Résolution EcoPart automatique {'PARTIEL' if transient else 'BLOQUÉ'} — "
                    f"{result['error']}\nAucune donnée téléchargée.",
                    retryable=transient,
                )
            ecopart_project_id = result["project_id"]
            resolution_note = (
                f"Projet EcoPart résolu automatiquement : {ecopart_project_id} "
                f"({result['resolution']})."
            )

        if not confirmed:
            if ecopart_project_id is None and ecotaxa_project_id is not None:
                resolution = _lookup_ecopart_project_for_ecotaxa(
                    session_et["df"],
                    known_ecotaxa_pid=int(ecotaxa_project_id),
                    client=client,
                    thread_id=thread_id,
                    request_timeout=_ecopart_preflight_timeout(),
                )
                if "error" in resolution:
                    transient = resolution.get("verdict") == "PARTIEL"
                    factory = _ep_error if transient else _ep_blocked
                    return factory(
                        "Préflight d'enrichissement EcoPart (dry-run) — "
                        f"{'PARTIEL' if transient else 'BLOQUÉ'}.\n"
                        f"Projet EcoTaxa {ecotaxa_project_id} : "
                        f"{resolution['error']}\nAucune donnée téléchargée.",
                        retryable=transient,
                    )
                ecopart_project_id = int(resolution["project_id"])
                resolution_note = str(resolution.get("resolution") or "lien résolu")

            if ecotaxa_project_id is None or ecopart_project_id is None:
                return _ep_blocked(
                    "Préflight d'enrichissement EcoPart (dry-run) — PARTIEL.\n"
                    "La paire EcoTaxa→EcoPart n'a pas pu être résolue avec certitude. "
                    "Aucune donnée téléchargée."
                )

            preflight = _preflight_ecopart_partition(
                session_et["df"],
                client=client,
                ecotaxa_project_id=int(ecotaxa_project_id),
                ecopart_project_id=int(ecopart_project_id),
                thread_id=thread_id,
                request_timeout=_ecopart_preflight_timeout(),
            )
            return _ep_blocked(
                "Préflight d'enrichissement EcoPart (dry-run ; la vérification des "
                "profils peut prendre jusqu'à 60 s).\n"
                f"EcoTaxa {ecotaxa_project_id} → EcoPart {ecopart_project_id} : "
                f"{preflight['verdict']} — {preflight['reason']} "
                f"({_preflight_profile_status(preflight)}).\n"
                f"Résolution : {resolution_note or 'identifiants explicites'}.\n"
                "Aucune donnée téléchargée. "
                + (
                    "Confirme pour lancer l'export et la jointure."
                    if preflight["verdict"] == "PRÊT"
                    else "Ne confirme pas tant que le blocage n'est pas résolu."
                ),
                metrics={
                    "projects": 1,
                    "projects_ready": int(preflight["verdict"] == "PRÊT"),
                    "projects_partial": int(preflight["verdict"] == "PARTIEL"),
                    "projects_blocked": int(preflight["verdict"] == "BLOQUÉ"),
                    "matching_profiles": preflight["matching_profiles"],
                    "exportable_profiles": preflight["exportable_profiles"],
                },
            )

        cache_key = build_result_cache_key(
            session_et["df"],
            {
                "ecotaxa_project_id": ecotaxa_project_id,
                "ecopart_project_id": ecopart_project_id,
                "operation": "ecotaxa_ecopart_join",
            },
        )
        cached = load_result("ecopart_enrichment", cache_key)
        if cached is not None:
            cached_df = cached.dataframe
            variable_name = dataset_variable_name(
                "ecotaxa_ecopart", "cached", uuid.uuid4().hex[:8]
            )
            meta = {
                "source": "join:ecotaxa+ecopart",
                "ecotaxa_project_id": ecotaxa_project_id,
                "ecopart_project_id": ecopart_project_id,
                "n_rows": len(cached_df),
                "cache_hit": True,
                "cached_at": cached.cached_at,
                "cache_provenance": cached.provenance,
            }
            store_dataset(
                _store,
                thread_id,
                cached_df,
                variable_name=variable_name,
                meta=meta,
                latest_alias=ECOTAXA_ECOPART,
            )
            return _ep_success(
                "Enrichissement EcoTaxa–EcoPart restauré depuis le cache exact — "
                f"{len(cached_df)} lignes; aucune ligne écartée. "
                f"Table active : `{variable_name}` (récupérée le {cached.cached_at}).",
                data_ref=variable_name,
                persisted=True,
                provenance=cached.provenance,
                method="Cached exact EcoTaxa-EcoPart enrichment",
                metrics={"rows": len(cached_df), "cache_hit": True},
            )

        cached_tsv = find_ecopart_tsv(
            ecopart_project_id=ecopart_project_id,
            profile_labels=set(_candidate_ecotaxa_profile_labels(session_et["df"])),
        )
        if cached_tsv is not None:
            cached_variable = _store_cached_ecopart_dataset(
                thread_id,
                cached_tsv,
                ecotaxa_project_id=ecotaxa_project_id,
                ecopart_project_id=ecopart_project_id,
            )
            join_result = _perform_enrichment(
                thread_id,
                ecopart_project_id,
                ecotaxa_session=session_et,
            )
            join_artifact = validate_tool_artifact(join_result[1])
            cache_summary = (
                "EcoPart restauré depuis le cache local — "
                f"{cached_tsv.n_rows} lignes (`{cached_variable}`).\n\n{join_result[0]}"
            )
            if join_artifact.status != "success":
                factory = {
                    "empty": _ep_empty,
                    "blocked": _ep_blocked,
                    "error": _ep_error,
                    "cancelled": _ep_blocked,
                }[join_artifact.status]
                return factory(cache_summary, retryable=join_artifact.retryable)
            return _ep_success(
                cache_summary,
                data_ref=join_artifact.data_ref,
                persisted=True,
                provenance={
                    "source": "ecopart_persistent_cache",
                    "cache_hit": True,
                    "content_sha256": cached_tsv.content_sha256,
                    "cache_provenance": cached_tsv.provenance,
                },
                method="Persistent EcoPart TSV cache and local join",
                metrics={"ecopart_rows": cached_tsv.n_rows, **dict(join_artifact.metrics)},
            )

        try:
            export_kwargs: dict[str, int] = {}
            if ecopart_project_id is not None:
                export_kwargs["project_id"] = int(ecopart_project_id)
            else:
                export_kwargs["ecotaxa_project_id"] = int(ecotaxa_project_id)
            links = client.start_export(**export_kwargs)
            df_ep = client.download_tsv(links)
        except EcopartExportError as exc:
            return _ep_error(
                _format_ecopart_export_error(
                    exc,
                    project_id=ecopart_project_id,
                    ecotaxa_project_id=ecotaxa_project_id,
                ),
                retryable=True,
            )
        except Exception as exc:
            return _ep_error(f"Erreur EcoPart : {exc}", retryable=True)

        if df_ep.empty:
            return _ep_empty(
                f"Aucun profil EcoPart trouvé pour le projet {ecopart_project_id or ecotaxa_project_id}."
            )

        file_id = uuid.uuid4().hex
        output_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
        df_ep.to_csv(output_path, sep="\t", index=False)
        try:
            import_ecopart_tsv(
                output_path,
                provenance="remote_export",
                ecopart_project_id=ecopart_project_id,
                ecotaxa_project_id=ecotaxa_project_id,
            )
        except ValueError:
            # A caller may deliberately request a reduced EcoPart export without
            # the sampled-volume field; it remains usable for inspection but not
            # for the abundance cache.
            pass

        ep_key = ecopart_project_id if ecopart_project_id is not None else f"via_ecotaxa_{ecotaxa_project_id}"
        variable_name = dataset_variable_name("ecopart", ep_key)
        meta = {
            "source": f"ecopart:{ep_key}",
            "project_id": ecopart_project_id,
            "ecotaxa_project_id": ecotaxa_project_id,
            "n_rows": len(df_ep),
        }
        store_dataset(
            _store,
            thread_id,
            df_ep,
            variable_name=variable_name,
            meta=meta,
            latest_alias=ECOPART,
        )
        if ecopart_project_id is not None:
            _store.set(f"{thread_id}:ecopart:{ecopart_project_id}", df_ep, meta)

        join_result = _perform_enrichment(
            thread_id,
            ecopart_project_id,
            ecotaxa_session=session_et,
        )
        artifact_url = download_url(output_path.name)
        scope = (
            f"projet EcoPart {ecopart_project_id} (jointure sur profils)"
            if ecopart_project_id is not None
            else f"projet EcoTaxa {ecotaxa_project_id}"
        )
        prefix = f"{resolution_note}\n" if resolution_note else ""
        join_artifact = validate_tool_artifact(join_result[1])
        summary = (
            f"{prefix}EcoPart téléchargé pour {scope} — {len(df_ep)} lignes "
            f"(`{variable_name}`, télécharger : {artifact_url}).\n\n{join_result[0]}"
        )
        if join_artifact.status != "success":
            factory = {
                "empty": _ep_empty,
                "blocked": _ep_blocked,
                "error": _ep_error,
                "cancelled": _ep_blocked,
            }[join_artifact.status]
            return factory(summary, retryable=join_artifact.retryable)
        joined_session = _session_for_variable(thread_id, join_artifact.data_ref)
        if joined_session is not None and isinstance(joined_session.get("df"), pd.DataFrame):
            saved = save_result(
                "ecopart_enrichment",
                cache_key,
                joined_session["df"],
                provenance={
                    "source": "EcoPart",
                    "ecotaxa_project_id": ecotaxa_project_id,
                    "ecopart_project_id": ecopart_project_id,
                    "join_method": "sample_id+depth_bin",
                },
            )
            cache_meta = {
                "cache_hit": False,
                "cached_at": saved.cached_at,
                "cache_provenance": saved.provenance,
            }
            for store_key in (
                thread_id,
                f"{thread_id}:{ECOTAXA_ECOPART}",
                f"{thread_id}:dataset:{join_artifact.data_ref}",
            ):
                _store.update_meta(store_key, cache_meta)
        return _ep_success(
            summary,
            data_ref=join_artifact.data_ref,
            artifact_refs=(artifact_url,),
            persisted=True,
            method="EcoPart export and EcoTaxa-EcoPart join",
            metrics={"ecopart_rows": len(df_ep), **dict(join_artifact.metrics)},
        )

    @tool(response_format="content_and_artifact")
    def find_ecopart_project_for_ecotaxa(
        ecotaxa_project_id: int | None = None,
    ) -> str:
        """Vérifie un lien EcoTaxa→EcoPart et la disponibilité des profils, sans exporter les objets.

        Utiliser cet outil quand l'utilisateur pose une question de type
        « est-ce qu'il existe un EcoPart pour ce fichier ? », « à quel projet
        EcoPart ce fichier est-il lié ? », « y a-t-il un EcoPart associé ? » —
        c'est-à-dire une question de disponibilité, PAS une demande
        d'enrichissement ou d'export. Vérifie ensuite les profils accessibles
        du projet EcoPart résolu : lecture seule, aucune tâche serveur créée.
        Avec `ecotaxa_project_id`, lit les profils et positions depuis le cache
        EcoTaxa local : aucun export EcoTaxa n'est requis.
        Si l'utilisateur demande ensuite l'enrichissement, router alors vers
        `enrich_ecotaxa_with_ecopart_remote`.
        """
        session_et = _ecotaxa_session_for_project(thread_id, ecotaxa_project_id)
        if session_et is not None:
            df_et = session_et.get("df")
            known_pid = (session_et.get("meta") or {}).get("project_id")
        elif ecotaxa_project_id is not None:
            cache_db = os.getenv("ECOTAXA_CACHE_DB", "data/ecotaxa_cache.sqlite")
            try:
                conn = open_readonly_connection(cache_db)
                df_et = pd.read_sql_query(
                    """
                    SELECT sample_id, original_id, station_id,
                           profile_id AS sample_profileid,
                           lat_avg AS object_lat, lon_avg AS object_lon
                    FROM samples_cache
                    WHERE project_id = ?
                    """,
                    conn,
                    params=(int(ecotaxa_project_id),),
                )
            except Exception as exc:
                return _ep_error(
                    f"Lecture du cache EcoTaxa impossible pour le projet "
                    f"{ecotaxa_project_id} : {exc}",
                    retryable=True,
                )
            finally:
                if "conn" in locals():
                    conn.close()
            if df_et.empty:
                return _ep_empty(
                    f"Aucun profil EcoTaxa en cache pour le projet {ecotaxa_project_id}."
                )
            known_pid = int(ecotaxa_project_id)
        else:
            return _ep_blocked(
                "Indiquer `ecotaxa_project_id` ou charger une table EcoTaxa. "
                "Aucun export n'est nécessaire pour ce lookup."
            )
        if df_et is None or getattr(df_et, "empty", True):
            return _ep_empty("Le dataset EcoTaxa en session est vide.")
        result = _lookup_ecopart_project_for_ecotaxa(
            df_et,
            known_ecotaxa_pid=known_pid,
            thread_id=thread_id,
            request_timeout=_ecopart_preflight_timeout(),
        )
        if "error" in result:
            return _ep_empty(f"Aucun projet EcoPart associé trouvé — {result['error']}")
        pid = result["project_id"]
        name = result.get("project_name") or "?"
        how = result.get("resolution", "?")
        linked_profiles = result.get("linked_samples") or []
        availability_note = (
            f"Données EcoPart liées au projet EcoTaxa : {len(linked_profiles)} "
            "profil(s) signalé(s) directement par le serveur."
            if linked_profiles
            else (
                "Lien EcoTaxa→EcoPart déjà vérifié côté serveur (cache de résolution) ; "
                "rafraîchissement de la liste des profils en cours."
                if result.get("cache_hit")
                else "Disponibilité des profils EcoPart non vérifiée."
            )
        )
        try:
            # ``filt_proj`` already returned real, server-linked EcoPart
            # profiles on the authoritative path.  Reuse that evidence rather
            # than making a second project-wide request just to prove data
            # exists.  Only a fallback resolution needs the bounded listing.
            if linked_profiles:
                profiles = linked_profiles
            else:
                client = EcopartClient()
                client.login()
                # When an EcoTaxa project id is known, ``filt_proj`` asks for
                # its directly linked profiles.  It is both more relevant and
                # markedly smaller than scanning the whole EcoPart project.
                search_kwargs = (
                    {"ecotaxa_project_id": int(known_pid)}
                    if known_pid is not None
                    else {"project_id": int(pid)}
                )
                profiles = client.search_samples(
                    timeout=min(3.0, _ecopart_preflight_timeout()),
                    **search_kwargs,
                )
            exportable = sum(
                str(profile.get("visibility") or "").strip().upper().endswith("Y")
                for profile in profiles
            )
            local_labels = set(_candidate_ecotaxa_profile_labels(df_et))
            matching_names = sum(
                str(profile.get("name") or "").strip() in local_labels
                for profile in profiles
            )
            if profiles:
                availability_note = (
                    f"Données EcoPart accessibles : {len(profiles)} profil(s) "
                    f"listé(s), dont {exportable} exportable(s). "
                    + (
                        f"{matching_names} nom(s) de profil déjà identique(s) côté EcoTaxa."
                        if matching_names
                        else "Aucun nom de profil identique à ce stade ; "
                        "ce n'est pas un refus, la jointure réelle vérifiera les clés."
                    )
                )
            else:
                availability_note = (
                    "Le projet EcoPart est résolu mais ne retourne actuellement "
                    "aucun profil accessible pour le compte configuré."
                )
        except Exception as exc:
            availability_note += (
                " La liste actuelle des profils EcoPart liés n'a pas pu être lue "
                f"maintenant ({type(exc).__name__})."
            )
        return _ep_success(
            f"Projet EcoPart associé trouvé : **{pid}**"
            f"{f' (« {name} »)' if name and name != '?' else ''}.\n"
            f"Résolution : {how}.\n{availability_note}\n"
            "Aucun export n'a été lancé — c'est juste un lookup. "
            "Pour enrichir, utiliser `enrich_ecotaxa_with_ecopart_remote`.\n\n"
            f"Source EcoPart : https://ecopart.obs-vlfr.fr/prj/{pid}",
            provenance={"project_id": int(pid)},
        )

    return [
        list_ecopart_samples,
        preview_ecopart_sample,
        query_ecopart,
        join_ecotaxa_ecopart,
        audit_ecotaxa_ecopart_join,
        enrich_ecotaxa_with_ecopart_remote,
        find_ecopart_project_for_ecotaxa,
    ]
