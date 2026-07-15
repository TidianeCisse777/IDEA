"""LangChain tools for EcoPart."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from langchain_core.tools import tool

from core.ecopart_client import EcopartClient, EcopartExportError
from core.ecotaxa_ecopart_join import (
    audit_ecotaxa_ecopart_dataframe,
    depth_bin_5m,
)
from core.environment_resolver import build_enrichment_provenance
from tools.dataset_registry import (
    ECOPART,
    ECOTAXA,
    ECOTAXA_ECOPART,
    dataset_variable_name,
    store_dataset,
)
from tools.ecotaxa_client import EcotaxaClient
from tools.session_store import default_store as _store

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)


def _format_ecopart_export_error(
    exc: EcopartExportError,
    *,
    project_id: int | None = None,
    ecotaxa_project_id: int | None = None,
) -> str:
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
    """Resolve the EcoTaxa dataset requested by project, not just the latest alias."""
    latest = _store.get(f"{thread_id}:ecotaxa")
    if project_id is None:
        return latest

    requested = int(project_id)
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

    if not candidates:
        return None

    # Prefer the canonical full-project variable when both a full export and a
    # scoped bulk export exist. Otherwise the sole/latest named dataset is safe.
    canonical = f"df_ecotaxa_{requested}"
    for session in candidates:
        if (session.get("meta") or {}).get("variable_name") == canonical:
            return session
    return candidates[-1]


def _session_for_variable(thread_id: str, variable_name: str | None) -> dict | None:
    """Resolve one explicitly named dataset from the session registry."""
    if variable_name is None:
        return None
    return _store.get(f"{thread_id}:dataset:{variable_name}")


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
        return (
            "Sélecteurs EcoPart incompatibles — utilise soit `project_id`, soit "
            "`ecopart_variable`, jamais les deux."
        )

    explicit_ecotaxa = _session_for_variable(thread_id, ecotaxa_variable)
    if ecotaxa_variable is not None and explicit_ecotaxa is None:
        return f"Variable EcoTaxa introuvable : `{ecotaxa_variable}`."
    explicit_ecopart = _session_for_variable(thread_id, ecopart_variable)
    if ecopart_variable is not None and explicit_ecopart is None:
        return f"Variable EcoPart introuvable : `{ecopart_variable}`."

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
        return f"Données manquantes — charge d'abord : {' et '.join(missing)}."

    df_et = session_et["df"].copy()
    df_ep = session_ep["df"].copy()
    selected_project_id = project_id or session_ep.get("meta", {}).get("project_id")

    if "Profile" not in df_ep.columns:
        return "Colonne 'Profile' absente du dataset EcoPart — relance `query_ecopart`."
    if "Depth [m]" not in df_ep.columns:
        return "Colonne 'Depth [m]' absente du dataset EcoPart — relance `query_ecopart`."
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
        return f"Colonne de jointure introuvable dans EcoTaxa. Colonnes disponibles : {available}"

    best_key, best_series, best_overlap = None, None, -1
    for name, series in candidates:
        overlap = int(series.isin(profile_values).sum())
        if overlap > best_overlap:
            best_key, best_series, best_overlap = name, series, overlap

    if best_overlap == 0:
        sample_et = ", ".join(sorted({str(v) for v in best_series.dropna().unique()})[:5])
        sample_ep = ", ".join(sorted({str(v) for v in profile_values})[:5])
        return (
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
        return (
            "Colonne de profondeur introuvable dans EcoTaxa "
            "(essayé : object_depth_min, obj_depth_min, depth_min, depth). "
            f"Colonnes disponibles : {available}"
        )

    depth_numeric = pd.to_numeric(df_et[depth_col], errors="coerce")
    df_et["_join_depth_bin"] = depth_bin_5m(depth_numeric)

    df_ep = df_ep.rename(columns={"Profile": "_join_sample_id", "Depth [m]": "_join_depth_bin"})
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
                return (
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
    source_lines = ["\nSources :"]
    ecotaxa_pid = None
    if session_et:
        ecotaxa_pid = (session_et.get("meta") or {}).get("project_id")
    if ecotaxa_pid is not None:
        source_lines.append(
            f"- EcoTaxa projet {ecotaxa_pid} : "
            f"https://ecotaxa.obs-vlfr.fr/prj/{ecotaxa_pid}"
        )
    if selected_project_id is not None:
        source_lines.append(
            f"- EcoPart projet {selected_project_id} : "
            f"https://ecopart.obs-vlfr.fr/prj/{selected_project_id}"
        )
    sources_block = "\n".join(source_lines) if len(source_lines) > 1 else ""

    return (
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
        f"appelle run_pandas directement pour analyser."
        f"{sources_block}\n"
        f"Source : {dataset_url}\n"
        "Provenance : "
        + json.dumps(provenance, ensure_ascii=False, sort_keys=True)
    )


def _candidate_ecotaxa_profile_labels(df_et: pd.DataFrame) -> list[str]:
    """Collect plausible profile/station labels from an EcoTaxa export."""
    labels: list[str] = []
    for col in ("sample_profileid", "sample_stationid", "sample_station_name", "sample_cruise"):
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
            if value not in labels:
                labels.append(value)
    return labels


# Global cache of resolved EcoTaxa project id -> resolution dict. The link is a
# stable server-side fact, so it is shared across threads/sessions. The user's
# workflow (find -> enrich -> density) otherwise re-resolves 2-3 times.
_ECOPART_RESOLUTION_CACHE: dict[int, dict] = {}


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
        cached = _ECOPART_RESOLUTION_CACHE.get(int(known_ecotaxa_pid))
        if cached is not None:
            return dict(cached)

    def _cache_and_return(result: dict) -> dict:
        if known_ecotaxa_pid is not None and "project_id" in result:
            _ECOPART_RESOLUTION_CACHE[int(known_ecotaxa_pid)] = dict(result)
        return result

    lat_col = next(
        (c for c in ("object_lat", "sample_lat", "latitude", "lat") if c in df_et.columns),
        None,
    )
    lon_col = next(
        (c for c in ("object_lon", "sample_long", "longitude", "lon") if c in df_et.columns),
        None,
    )

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
            linked = client.search_samples(ecotaxa_project_id=int(known_ecotaxa_pid))
        except Exception:
            linked = []
        for cand in sorted(linked, key=lambda c: int(c.get("id", 0))):
            try:
                meta = client.get_sample_metadata(cand["id"])
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
            })

    profile_labels = set(_candidate_ecotaxa_profile_labels(df_et))

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
        tally = votes.setdefault(ep_pid, [0, 0])
        if pf and pf in profile_labels:
            tally[0] += 1
        tally[1] += 1
        names.setdefault(ep_pid, meta.get("ecopart_project_name") or "")

    if not votes:
        return {"error": "Aucun sample EcoPart exploitable (project_id illisible)."}

    # No authoritative link found: prefer profile matches, then candidate count;
    # lowest project id breaks ties so the result is stable across runs.
    best_pid = max(votes, key=lambda pid: (votes[pid][0], votes[pid][1], -pid))
    mid, weak = votes[best_pid]
    if mid:
        how = f"correspondance de profil ({mid} sample(s) sur {weak})"
    else:
        how = f"proximité géographique par {search_note} ({weak} sample(s), aucun lien EcoTaxa direct)"
    return _cache_and_return({
        "project_id": best_pid,
        "project_name": names.get(best_pid) or None,
        "resolution": how,
    })


def make_ecopart_tools(thread_id: str) -> list:
    """Create LangChain EcoPart tools for one thread."""

    @tool
    def list_ecopart_samples(project_id: int = 105) -> str:
        """Liste les échantillons EcoPart disponibles pour un projet."""
        try:
            client = EcopartClient()
            client.login()
            samples = client.list_samples(project_id)
        except Exception as exc:
            return f"Erreur EcoPart : {exc}"
        if not samples:
            return "Aucun échantillon EcoPart trouvé."
        return pd.DataFrame(samples).to_markdown(index=False)

    @tool
    def preview_ecopart_sample(sample_id: int) -> str:
        """Prévisualise un échantillon EcoPart (popover texte)."""
        try:
            client = EcopartClient()
            client.login()
            preview = client.preview_sample(sample_id)
        except Exception as exc:
            return f"Erreur EcoPart : {exc}"
        if not preview["accessible"]:
            return f"Échantillon {sample_id} non accessible."
        return preview["text"] or f"Échantillon {sample_id} — aucun texte disponible."

    @tool
    def query_ecopart(
        project_id: int = 105,
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
            variable_name = dataset_variable_name("ecopart", project_id)
            meta = {
                "source": f"ecopart:{project_id}",
                "project_id": project_id,
                "n_rows": len(df),
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
            download_url = f"http://localhost:8000/downloads/{output_path.name}"
            return (
                f"EcoPart chargé — {len(df)} lignes.\n"
                f"Données disponibles dans `{variable_name}` "
                f"et `df_ecopart` (dernier projet chargé).\n"
                f"Appelle run_pandas directement pour analyser.\n"
                f"Télécharger : {download_url}"
            )
        except EcopartExportError as exc:
            return _format_ecopart_export_error(exc, project_id=project_id)
        except Exception as exc:
            return f"Erreur EcoPart : {exc}"

    @tool
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

    @tool
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
            return f"Variable de jointure introuvable : `{source_variable}`."

        audit = audit_ecotaxa_ecopart_dataframe(
            session["df"], session.get("meta") or {}
        )
        verdict = "VALIDÉ" if audit["verdict"] == "validated" else "REFUSÉ"
        anomalies = ", ".join(audit["anomalies"]) or "aucune"
        return (
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

    @tool
    def enrich_ecotaxa_with_ecopart_remote(
        ecotaxa_project_id: int | None = None,
        ecopart_project_id: int | None = None,
        confirmed: bool = False,
    ) -> str:
        """Enrichit l'EcoTaxa en session avec les variables EcoPart téléchargées **à distance**.

        Workflow : (1) télécharge les samples EcoPart liés au projet EcoTaxa donné via
        `filt_proj` (ou directement par `ecopart_project_id` via `filt_uproj`), (2) joint sur
        (sample_id, depth_bin) avec l'EcoTaxa déjà en session.

        Pré-requis : un EcoTaxa doit être en session (load_file UVP ou query_ecotaxa).
        Pré-requis ID : passer `ecotaxa_project_id` (recommandé) OU `ecopart_project_id`.
        Si aucun n'est fourni, l'outil tente de lire `meta.project_id` posé par `query_ecotaxa`.

        **Confirmation obligatoire (CT-AG-06)** : `confirmed=False` par défaut →
        renvoie un dry-run montrant le projet EcoPart résolu et le plan de
        jointure, sans rien télécharger. Pour lancer réellement le téléchargement
        et la jointure, rappeler avec `confirmed=True`.
        """
        session_et = _ecotaxa_session_for_project(thread_id, ecotaxa_project_id)
        if session_et is None:
            if not confirmed:
                if ecotaxa_project_id is None:
                    return (
                        "Données EcoTaxa manquantes — charge d'abord un fichier UVP "
                        "(`load_file`) ou `query_ecotaxa`."
                    )
                return (
                    "Plan d'enrichissement EcoPart (dry-run) — projet EcoTaxa "
                    f"{ecotaxa_project_id}.\n"
                    f"Le projet EcoTaxa {ecotaxa_project_id} sera exporté après "
                    "confirmation, puis le projet EcoPart correspondant sera "
                    "téléchargé et joint sur (sample_id, depth_bin). "
                    "Aucune donnée téléchargée pour l'instant.\n"
                    "Confirme pour lancer : rappelle "
                    "`enrich_ecotaxa_with_ecopart_remote` avec `confirmed=True`."
                )
            # Guard: the caller named an EcoTaxa project but no EcoTaxa is loaded
            # (query_ecotaxa was skipped). Auto-load it so this confirmed
            # enrichment is self-sufficient instead of failing the turn.
            if ecotaxa_project_id is not None:
                try:
                    _ensure_ecotaxa_project_loaded(thread_id, int(ecotaxa_project_id))
                except Exception as exc:
                    return (
                        f"Le projet EcoTaxa {ecotaxa_project_id} n'a pas pu être chargé "
                        f"automatiquement : {exc}"
                    )
                session_et = _ecotaxa_session_for_project(
                    thread_id,
                    ecotaxa_project_id,
                )
            if session_et is None:
                return "Données EcoTaxa manquantes — charge d'abord un fichier UVP (`load_file`) ou `query_ecotaxa`."

        if ecotaxa_project_id is None and ecopart_project_id is None:
            ecotaxa_project_id = session_et.get("meta", {}).get("project_id")

        try:
            client = EcopartClient()
            client.login()
        except Exception as exc:
            return f"Erreur EcoPart : {exc}"

        resolution_note = ""
        if ecotaxa_project_id is None and ecopart_project_id is None:
            # Same deterministic resolver as find_ecopart_project_for_ecotaxa, so
            # the preview and the actual enrichment always agree on the project.
            result = _lookup_ecopart_project_for_ecotaxa(session_et["df"])
            if "error" in result:
                return (
                    f"Résolution EcoPart automatique impossible — {result['error']} "
                    "Fournis `ecotaxa_project_id` ou `ecopart_project_id`."
                )
            ecopart_project_id = result["project_id"]
            resolution_note = (
                f"Projet EcoPart résolu automatiquement : {ecopart_project_id} "
                f"({result['resolution']})."
            )

        if not confirmed:
            scope = (
                f"projet EcoTaxa {ecotaxa_project_id}"
                if ecotaxa_project_id is not None
                else f"projet EcoPart {ecopart_project_id}"
            )
            ep_target = (
                str(ecopart_project_id)
                if ecopart_project_id is not None
                else "(résolu au lancement)"
            )
            prefix = f"{resolution_note}\n" if resolution_note else ""
            return (
                f"{prefix}Plan d'enrichissement EcoPart (dry-run) — {scope} → "
                f"EcoPart {ep_target}.\n"
                "Opération lourde : téléchargement de l'EcoPart puis jointure sur "
                "(sample_id, depth_bin). Aucune donnée téléchargée pour l'instant.\n"
                "Confirme pour lancer : rappelle `enrich_ecotaxa_with_ecopart_remote` "
                "avec `confirmed=True`."
            )

        try:
            links = client.start_export(
                project_id=ecopart_project_id,
                ecotaxa_project_id=ecotaxa_project_id,
            )
            df_ep = client.download_tsv(links)
        except EcopartExportError as exc:
            return _format_ecopart_export_error(
                exc,
                project_id=ecopart_project_id,
                ecotaxa_project_id=ecotaxa_project_id,
            )
        except Exception as exc:
            return f"Erreur EcoPart : {exc}"

        if df_ep.empty:
            return (
                f"Aucun sample EcoPart trouvé pour le projet EcoTaxa {ecotaxa_project_id} "
                f"— vérifie l'ID ou utilise `ecopart_project_id` directement."
            )

        file_id = uuid.uuid4().hex
        output_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
        df_ep.to_csv(output_path, sep="\t", index=False)

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
        download_url = f"http://localhost:8000/downloads/{output_path.name}"
        scope = (
            f"projet EcoTaxa {ecotaxa_project_id}"
            if ecotaxa_project_id is not None
            else f"projet EcoPart {ecopart_project_id}"
        )
        prefix = f"{resolution_note}\n" if resolution_note else ""
        return (
            f"{prefix}EcoPart téléchargé pour {scope} — {len(df_ep)} lignes "
            f"(`{variable_name}`, télécharger : {download_url}).\n\n{join_result}"
        )

    @tool
    def find_ecopart_project_for_ecotaxa() -> str:
        """Vérifie si un projet EcoPart correspond à l'EcoTaxa en session, sans télécharger.

        Utiliser cet outil quand l'utilisateur pose une question de type
        « est-ce qu'il existe un EcoPart pour ce fichier ? », « à quel projet
        EcoPart ce fichier est-il lié ? », « y a-t-il un EcoPart associé ? » —
        c'est-à-dire une question de disponibilité, PAS une demande
        d'enrichissement ou d'export. Utilise uniquement
        `search_samples_by_bbox` + `get_sample_metadata` sur quelques
        candidats : lecture seule, ~2-5s, aucune tâche serveur créée.
        Si l'utilisateur demande ensuite l'enrichissement, router alors vers
        `enrich_ecotaxa_with_ecopart_remote`.
        """
        session_et = _store.get(f"{thread_id}:ecotaxa")
        if session_et is None:
            return (
                "Aucun fichier EcoTaxa en session — charge d'abord un fichier "
                "UVP (`load_file`) ou lance `query_ecotaxa`."
            )
        df_et = session_et.get("df")
        if df_et is None or getattr(df_et, "empty", True):
            return "Le dataset EcoTaxa en session est vide."
        known_pid = session_et.get("meta", {}).get("project_id")
        result = _lookup_ecopart_project_for_ecotaxa(df_et, known_ecotaxa_pid=known_pid)
        if "error" in result:
            return f"Aucun projet EcoPart associé trouvé — {result['error']}"
        pid = result["project_id"]
        name = result.get("project_name") or "?"
        how = result.get("resolution", "?")
        return (
            f"Projet EcoPart associé trouvé : **{pid}**"
            f"{f' (« {name} »)' if name and name != '?' else ''}.\n"
            f"Résolution : {how}. "
            "Aucun export n'a été lancé — c'est juste un lookup. "
            "Pour enrichir, utiliser `enrich_ecotaxa_with_ecopart_remote`.\n\n"
            f"Source EcoPart : https://ecopart.obs-vlfr.fr/prj/{pid}"
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
