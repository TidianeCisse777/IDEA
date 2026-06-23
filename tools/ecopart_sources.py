"""LangChain tools for EcoPart."""
from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
from langchain_core.tools import tool

from core.ecopart_client import EcopartClient, EcopartExportError
from tools.dataset_registry import dataset_variable_name, store_dataset
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


def _perform_enrichment(thread_id: str, project_id: int | None) -> str:
    """Run the (sample_id, depth_bin) join from the session-resolved EcoTaxa/EcoPart."""
    session_et = _store.get(f"{thread_id}:ecotaxa")
    if project_id is None:
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

    if "sample_id" in df_et.columns and df_et["sample_id"].iloc[0] in df_ep["Profile"].values:
        df_et["_join_sample_id"] = df_et["sample_id"]
    elif "obj_orig_id" in df_et.columns:
        df_et["_join_sample_id"] = df_et["obj_orig_id"].str.replace(r"_\d+$", "", regex=True)
    elif "sample_id" in df_et.columns:
        df_et["_join_sample_id"] = df_et["sample_id"]
    else:
        available = ", ".join(df_et.columns[:20].tolist())
        return f"Colonne de jointure introuvable dans EcoTaxa. Colonnes disponibles : {available}"

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
    df_et["_join_depth_bin"] = (depth_numeric // 5) * 5 + 2.5

    df_ep = df_ep.rename(columns={"Profile": "_join_sample_id", "Depth [m]": "_join_depth_bin"})
    df_ep = df_ep.rename(
        columns={
            c: f"ecopart_{c}"
            for c in df_ep.columns
            if c not in ("_join_sample_id", "_join_depth_bin")
        }
    )
    df_ep = df_ep.drop_duplicates(subset=["_join_sample_id", "_join_depth_bin"])

    merged = df_et.merge(df_ep, on=["_join_sample_id", "_join_depth_bin"], how="left")

    sentinel = next((c for c in merged.columns if c.startswith("ecopart_")), None)
    n_matched = int(merged[sentinel].notna().sum()) if sentinel else 0

    merged = merged.drop(columns=["_join_sample_id", "_join_depth_bin"], errors="ignore")

    source = "join:ecotaxa+ecopart"
    if selected_project_id is not None:
        source = f"{source}:{selected_project_id}"
    joined_variable_name = (
        dataset_variable_name("ecotaxa_ecopart", selected_project_id)
        if selected_project_id is not None
        else dataset_variable_name("ecotaxa_ecopart")
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
            "depth_col_used": depth_col,
        },
        latest_alias="ecotaxa_ecopart",
    )
    project_note = (
        f" avec EcoPart {selected_project_id}" if selected_project_id is not None else ""
    )
    return (
        f"Enrichissement terminé{project_note} — {len(merged)} lignes "
        f"({n_matched} matchées sur un bin EcoPart), {len(merged.columns)} colonnes.\n"
        f"Clé de jointure : (sample_id, depth_bin) calculé depuis `{depth_col}`.\n"
        f"Colonnes EcoPart préfixées `ecopart_` — notamment `ecopart_Sampled volume [L]` "
        f"pour les calculs d'abondance (nb objets / volume filtré).\n"
        f"Données disponibles dans `{joined_variable_name}` et `df_ecotaxa_ecopart` — "
        f"appelle run_pandas directement pour analyser."
    )


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
                latest_alias="ecopart",
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
    def join_ecotaxa_ecopart(project_id: int | None = None) -> str:
        """Enrichit EcoTaxa avec EcoPart par (sample_id, depth_bin) — chaque objet récupère le Sampled volume et les variables EcoPart de son bin de 5 m. Exige que EcoTaxa et EcoPart soient déjà chargés en session."""
        return _perform_enrichment(thread_id, project_id)

    @tool
    def enrich_ecotaxa_with_ecopart_remote(
        ecotaxa_project_id: int | None = None,
        ecopart_project_id: int | None = None,
    ) -> str:
        """Enrichit l'EcoTaxa en session avec les variables EcoPart téléchargées **à distance**.

        Workflow : (1) télécharge les samples EcoPart liés au projet EcoTaxa donné via
        `filt_proj` (ou directement par `ecopart_project_id` via `filt_uproj`), (2) joint sur
        (sample_id, depth_bin) avec l'EcoTaxa déjà en session.

        Pré-requis : un EcoTaxa doit être en session (load_file UVP ou query_ecotaxa).
        Pré-requis ID : passer `ecotaxa_project_id` (recommandé) OU `ecopart_project_id`.
        Si aucun n'est fourni, l'outil tente de lire `meta.project_id` posé par `query_ecotaxa`.
        """
        session_et = _store.get(f"{thread_id}:ecotaxa")
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
            df_et = session_et["df"]
            lat_col = next((c for c in ("object_lat", "latitude", "lat") if c in df_et.columns), None)
            lon_col = next((c for c in ("object_lon", "longitude", "lon") if c in df_et.columns), None)
            if lat_col is None or lon_col is None:
                return (
                    "Projet EcoTaxa inconnu et coordonnées absentes du fichier — "
                    "fournis `ecotaxa_project_id` ou `ecopart_project_id`."
                )
            lat = pd.to_numeric(df_et[lat_col], errors="coerce").dropna()
            lon = pd.to_numeric(df_et[lon_col], errors="coerce").dropna()
            if lat.empty or lon.empty:
                return "Coordonnées du fichier EcoTaxa illisibles — fournis `ecotaxa_project_id`."
            margin = 0.05
            try:
                candidates = client.search_samples_by_bbox(
                    north=float(lat.max()) + margin,
                    south=float(lat.min()) - margin,
                    west=float(lon.min()) - margin,
                    east=float(lon.max()) + margin,
                )
            except Exception as exc:
                return f"Erreur de recherche EcoPart par bbox : {exc}"
            if not candidates:
                return (
                    "Aucun sample EcoPart trouvé dans la zone du fichier EcoTaxa — "
                    "fournis `ecopart_project_id` manuellement."
                )
            sample_ids_et = set()
            if "sample_id" in df_et.columns:
                sample_ids_et = set(df_et["sample_id"].astype(str).head(50).unique())
            elif "obj_orig_id" in df_et.columns:
                sample_ids_et = set(
                    df_et["obj_orig_id"].astype(str).str.replace(r"_\d+$", "", regex=True).head(50).unique()
                )
            found_ecopart_pid = None
            for cand in candidates[:10]:
                meta_ep = client.get_sample_metadata(cand["id"])
                pf = meta_ep.get("profile_id")
                ep_pid = meta_ep.get("ecopart_project_id")
                if ep_pid is None:
                    continue
                if not sample_ids_et or pf in sample_ids_et:
                    found_ecopart_pid = ep_pid
                    resolution_note = (
                        f"Projet EcoPart résolu automatiquement : {ep_pid} "
                        f"(via sample `{pf}` à {cand['lat']:.3f}/{cand['lon']:.3f})."
                    )
                    break
            if found_ecopart_pid is None:
                found_ecopart_pid = candidates[0] and client.get_sample_metadata(candidates[0]["id"]).get("ecopart_project_id")
                if found_ecopart_pid is not None:
                    resolution_note = (
                        f"Projet EcoPart résolu par fallback géographique : {found_ecopart_pid}."
                    )
            if found_ecopart_pid is None:
                return (
                    "Impossible de résoudre le projet EcoPart depuis la bbox EcoTaxa — "
                    "fournis `ecopart_project_id`."
                )
            ecopart_project_id = found_ecopart_pid

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
            latest_alias="ecopart",
        )
        if ecopart_project_id is not None:
            _store.set(f"{thread_id}:ecopart:{ecopart_project_id}", df_ep, meta)

        join_result = _perform_enrichment(thread_id, ecopart_project_id)
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

    return [
        list_ecopart_samples,
        preview_ecopart_sample,
        query_ecopart,
        join_ecotaxa_ecopart,
        enrich_ecotaxa_with_ecopart_remote,
    ]
