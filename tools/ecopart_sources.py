"""LangChain tools for EcoPart."""
from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
from langchain_core.tools import tool

from core.ecopart_client import EcopartClient
from tools.session_store import default_store as _store

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)


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
            meta = {
                "source": f"ecopart:{project_id}",
                "project_id": project_id,
                "n_rows": len(df),
            }
            _store.set(thread_id, df, meta)
            _store.set(f"{thread_id}:ecopart", df, meta)
            _store.set(f"{thread_id}:ecopart:{project_id}", df, meta)
            download_url = f"http://localhost:8000/downloads/{output_path.name}"
            return (
                f"EcoPart chargé — {len(df)} lignes.\n"
                f"Données disponibles dans `df_ecopart_{project_id}` "
                f"et `df_ecopart` (dernier projet chargé).\n"
                f"Appelle run_pandas directement pour analyser.\n"
                f"Télécharger : {download_url}"
            )
        except Exception as exc:
            return f"Erreur EcoPart : {exc}"

    @tool
    def join_ecotaxa_ecopart() -> str:
        """Joint les données EcoTaxa et EcoPart déjà chargées dans la session."""
        session_et = _store.get(f"{thread_id}:ecotaxa")
        session_ep = _store.get(f"{thread_id}:ecopart")

        missing = []
        if session_et is None:
            missing.append("EcoTaxa (`query_ecotaxa`)")
        if session_ep is None:
            missing.append("EcoPart (`query_ecopart`)")
        if missing:
            return f"Données manquantes — charge d'abord : {' et '.join(missing)}."

        df_et = session_et["df"].copy()
        df_ep = session_ep["df"].copy()

        df_et["profile_id"] = df_et["obj_orig_id"].str.replace(r"_\d+$", "", regex=True)
        merged = df_et.merge(df_ep, left_on="profile_id", right_on="Profile", how="left")
        merged = merged.drop(columns=["profile_id"], errors="ignore")

        _store.set(thread_id, merged, {"source": "join:ecotaxa+ecopart", "n_rows": len(merged)})
        return (
            f"Jointure terminée — {len(merged)} lignes, {len(merged.columns)} colonnes.\n"
            f"Données en session — appelle run_pandas directement pour analyser."
        )

    return [list_ecopart_samples, preview_ecopart_sample, query_ecopart, join_ecotaxa_ecopart]
