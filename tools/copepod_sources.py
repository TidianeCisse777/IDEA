"""tools/copepod_sources.py — LangChain tools pour accès EcoTaxa/EcoPart."""
from __future__ import annotations

import uuid
from pathlib import Path

from langchain_core.tools import tool

from tools.ecotaxa_client import EcotaxaClient
from tools.public_url import download_url
from tools.session_store import default_store as _store
from tools.data_tools import _uvp_skill_hint

_DOWNLOADS_DIR = Path("/tmp/copepod_downloads")
_DOWNLOADS_DIR.mkdir(exist_ok=True)


def make_source_tools(thread_id: str) -> list:

    def _format_number(value) -> str:
        if value is None:
            return "—"
        if isinstance(value, float) and not value.is_integer():
            return f"{value:.2f}".rstrip("0").rstrip(".")
        return f"{int(value):,}".replace(",", " ")

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

        lines = ["| project_id | name |", "|---:|---|"]
        lines.extend(f"| {project['project_id']} | {project['name']} |" for project in projects)
        return "\n".join(lines)

    @tool
    def preview_ecotaxa_project(project_id: int) -> str:
        """Présente rapidement un projet EcoTaxa sans lancer d'export complet."""
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
        return "\n".join(lines)

    @tool
    def query_ecotaxa(project_id: int, taxon: str | None = None, status: str = "V") -> str:
        """Interroge EcoTaxa et charge les données dans la session courante.

        Args:
            project_id: ID du projet EcoTaxa (ex: 1165, 2331).
            taxon: Filtre taxonomique optionnel (ex: "Copepoda").
            status: Statut des annotations — "V" (validé), "P" (prédit), "" (tous).
        """
        try:
            client = EcotaxaClient()
            client.login()
            filters = {"statusfilter": status}
            if taxon:
                filters["taxo"] = taxon

            job_id = client.start_export(project_id, filters)
            client.wait_for_job(job_id)
            df = client.download_tsv(job_id)
        except Exception as exc:
            return f"Erreur lors de l'accès à EcoTaxa : {exc}"

        _store.set(thread_id, df, {"source": f"ecotaxa:{project_id}", "n_rows": len(df)})

        file_id = uuid.uuid4().hex
        tsv_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
        df.to_csv(tsv_path, sep="\t", index=False)

        hint = _uvp_skill_hint(list(df.columns))
        summary = (
            f"Projet {project_id} chargé — {len(df)} lignes, {len(df.columns)} colonnes.\n"
            f"Données en session — appelle run_pandas directement pour analyser.\n"
            f"Télécharger : {download_url(f'{file_id}.tsv')}"
        )
        if hint:
            summary += f"\n{hint}"
        return summary

    return [list_ecotaxa_projects, preview_ecotaxa_project, query_ecotaxa]
