"""tools/copepod_sources.py — LangChain tools pour accès EcoTaxa/EcoPart."""
from __future__ import annotations

import uuid
from pathlib import Path

from langchain_core.tools import tool

from core.ecotaxa_browser.column_distribution import get_column_distribution
from core.ecotaxa_browser.compare_schemas import compare_project_schemas
from core.ecotaxa_browser.errors import EcoTaxaBrowserError
from core.ecotaxa_browser.observations import find_observations
from core.ecotaxa_browser.region import projects_in_region, samples_in_region
from core.ecotaxa_browser.schema import get_project_schema
from core.ecotaxa_browser.search import search_projects
from core.ecotaxa_browser.taxa_stats import taxa_stats
from tools.ecotaxa_client import EcotaxaClient
from tools.dataset_registry import dataset_variable_name, store_dataset
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
            "| project_id | name | instrument | status | objects | validated |",
            "|---:|---|---|---|---:|---:|",
        ]
        lines.extend(
            f"| {project['project_id']} | {project['name']} | "
            f"{project.get('instrument') or '—'} | {project.get('status') or '—'} | "
            f"{_format_number(project.get('object_count'))} | "
            f"{_format_number(project.get('percent_validated'))} % |"
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

        variable_name = dataset_variable_name("ecotaxa", project_id)
        store_dataset(
            _store,
            thread_id,
            df,
            variable_name=variable_name,
            meta={"source": f"ecotaxa:{project_id}", "project_id": project_id, "n_rows": len(df)},
            latest_alias="ecotaxa",
        )

        file_id = uuid.uuid4().hex
        tsv_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
        df.to_csv(tsv_path, sep="\t", index=False)

        hint = _uvp_skill_hint(list(df.columns))
        summary = (
            f"Projet {project_id} chargé — {len(df)} lignes, {len(df.columns)} colonnes.\n"
            f"Données disponibles dans `{variable_name}` et `df_ecotaxa`.\n"
            f"Appelle run_pandas directement pour analyser.\n"
            f"Télécharger : {download_url(f'{file_id}.tsv')}"
        )
        if hint:
            summary += f"\n{hint}"
        return summary

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
            lines.append(f"## {level_name}")
            lines.append("")
            lines.append("| colonne | type | catégorie |")
            lines.append("|---|---|---|")
            for fixed in content["fixed"]:
                lines.append(f"| {fixed['name']} | {fixed['type']} | fixe |")
            for free in content["free"]:
                tag = f" `{free['code']}`" if verbose and "code" in free else ""
                lines.append(f"| {free['label']}{tag} | {free['type']} | libre |")
            lines.append("")
        return "\n".join(lines)

    @tool
    def count_ecotaxa_taxa(
        project_ids: list[int],
        taxa: list[int | str],
    ) -> str:
        """Compte les objets validés / prédits / douteux par projet et par taxon.

        `taxa` accepte des IDs entiers ou des noms scientifiques. Utile pour
        évaluer la confiance des annotations avant d'exporter.
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
            "| project_id | taxon | validés | prédits | douteux | total |",
            "|---:|---|---:|---:|---:|---:|",
        ]
        lines.extend(
            f"| {row['project_id']} | {row['taxon_name']} | "
            f"{row['count_V']} | {row['count_P']} | {row['count_D']} | "
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
    def inspect_ecotaxa_column(
        project_id: int,
        column_name: str,
        level: str | None = None,
    ) -> str:
        """Inspecte la distribution d'une colonne d'un projet EcoTaxa.

        Pour les colonnes numériques : min/max/mean/median/p25/p75. Pour les
        colonnes texte : top valeurs + nombre de distinctes. Précise `level`
        si l'agent renvoie une erreur d'ambiguïté.
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
        return "\n".join(lines)

    @tool
    def find_ecotaxa_samples_in_region(
        bbox: dict | None = None,
        date_range: dict | None = None,
        instrument: str | None = None,
    ) -> str:
        """Cherche les samples EcoTaxa dans une bbox géo et/ou une période.

        `bbox` : `{"south": float, "west": float, "north": float, "east": float}`.
        `date_range` : `{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}`.
        Réponse plafonnée à 500 samples avec un summary par projet.
        Lecture du cache local — pas de download.
        """
        try:
            result = samples_in_region(
                bbox=bbox, date_range=date_range, instrument=instrument,
            )
        except EcoTaxaBrowserError as exc:
            return f"Erreur EcoTaxa ({exc.code}) : {exc}"
        except Exception as exc:
            return f"Erreur lors de la recherche EcoTaxa : {exc}"

        if not result["samples"]:
            return "Aucun sample dans cette zone / période."

        lines = [
            f"# {result['total_matching']} samples (cap {len(result['samples'])})"
            + (" — tronqué" if result["truncated"] else ""),
            "",
            "| sample_id | projet | lat | lon | date_min | date_max | instrument |",
            "|---:|---:|---:|---:|---|---|---|",
        ]
        for s in result["samples"][:50]:
            lines.append(
                f"| {s['sample_id']} | {s['project_id']} | {s['lat']:.3f} | "
                f"{s['lon']:.3f} | {s['date_min']} | {s['date_max']} | "
                f"{s.get('instrument') or '—'} |"
            )
        if len(result["samples"]) > 50:
            lines.append("")
            lines.append(f"(50 premiers / {len(result['samples'])} affichés)")
        return "\n".join(lines)

    @tool
    def find_ecotaxa_projects_in_region(
        bbox: dict | None = None,
        date_range: dict | None = None,
    ) -> str:
        """Liste les projets EcoTaxa avec au moins un sample dans une zone / période.

        Même format `bbox` et `date_range` que `find_ecotaxa_samples_in_region`.
        Réponse agrégée au niveau projet : nombre de samples, total objets,
        instruments, plage de dates.
        """
        try:
            result = projects_in_region(bbox=bbox, date_range=date_range)
        except EcoTaxaBrowserError as exc:
            return f"Erreur EcoTaxa ({exc.code}) : {exc}"
        except Exception as exc:
            return f"Erreur lors de la recherche EcoTaxa : {exc}"

        if not result["projects"]:
            return "Aucun projet dans cette zone / période."

        lines = [
            f"# {result['total_projects']} projets, {result['total_samples']} samples",
            "",
            "| project_id | samples | objets | instruments | date_min | date_max |",
            "|---:|---:|---:|---|---|---|",
        ]
        for p in result["projects"]:
            lines.append(
                f"| {p['project_id']} | {p['sample_count']} | "
                f"{p['object_count']} | {', '.join(p['instruments']) or '—'} | "
                f"{p['date_min'] or '—'} | {p['date_max'] or '—'} |"
            )
        return "\n".join(lines)

    @tool
    def find_ecotaxa_observations(
        taxon: str,
        bbox: dict | None = None,
        date_range: dict | None = None,
        instrument: str | None = None,
        status: str = "V",
    ) -> str:
        """Trouve les samples EcoTaxa dont le projet a le taxon attesté.

        Granularité projet-filtrée : retourne les samples (bbox/date/instrument)
        appartenant à un projet où le taxon a au moins un objet du statut
        demandé (`V` validé, `P` prédit, `D` douteux, `all`). Pour des counts
        précis par projet, enchaîner sur `count_ecotaxa_taxa`.
        """
        try:
            result = find_observations(
                taxon=taxon, bbox=bbox, date_range=date_range,
                instrument=instrument, status=status,
            )
        except EcoTaxaBrowserError as exc:
            details = ""
            if exc.candidates:
                details = " — candidats : " + ", ".join(
                    f"{c.get('taxon_id')}={c.get('display_name')}"
                    for c in exc.candidates[:5]
                )
            return f"Erreur EcoTaxa ({exc.code}) : {exc}{details}"
        except Exception as exc:
            return f"Erreur lors de la recherche EcoTaxa : {exc}"

        if not result["samples"]:
            attested = result["attested_projects"]
            return (
                f"Aucun sample (cache local) dans un projet attestant "
                f"{result['taxon']['matched_name']} au statut {status} — "
                f"projets attestés : {attested or 'aucun'}."
            )

        lines = [
            f"# {result['total_matching']} samples × {result['taxon']['matched_name']}"
            + (" — tronqué" if result["truncated"] else ""),
            f"Statut filtré : {result['status_filter']} · "
            f"Projets attestés : {result['attested_projects']}",
            "",
            "| sample_id | projet | lat | lon | date_min | date_max |",
            "|---:|---:|---:|---:|---|---|",
        ]
        for s in result["samples"][:50]:
            lines.append(
                f"| {s['sample_id']} | {s['project_id']} | {s['lat']:.3f} | "
                f"{s['lon']:.3f} | {s['date_min']} | {s['date_max']} |"
            )
        if len(result["samples"]) > 50:
            lines.append("")
            lines.append(f"(50 premiers / {len(result['samples'])} affichés)")
        return "\n".join(lines)

    return [
        find_ecotaxa_projects,
        find_ecotaxa_samples_in_region,
        find_ecotaxa_projects_in_region,
        find_ecotaxa_observations,
        inspect_ecotaxa_project_schema,
        inspect_ecotaxa_column,
        count_ecotaxa_taxa,
        compare_ecotaxa_projects,
        list_ecotaxa_projects,
        preview_ecotaxa_project,
        query_ecotaxa,
    ]
