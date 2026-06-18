"""tools/copepod_sources.py — LangChain tools pour accès EcoTaxa/EcoPart."""
from __future__ import annotations

import uuid
from pathlib import Path

from langchain_core.tools import tool

from core.ecotaxa_browser.column_distribution import get_column_distribution
from core.ecotaxa_browser.compare_schemas import compare_project_schemas
from core.ecotaxa_browser.errors import EcoTaxaBrowserError
from core.ecotaxa_browser.observations import find_observations
from core.ecotaxa_browser.region import (
    projects_in_region,
    resolve_sample_projects,
    samples_in_region,
)
from core.ecotaxa_browser.project_summary import summarize_projects
from core.ecotaxa_browser.sample_summary import summarize_samples
from core.ecotaxa_browser.samples import get_sample as core_get_sample
from core.ecotaxa_browser.schema import get_project_schema
from core.ecotaxa_browser.search import search_projects
from core.ecotaxa_browser.taxa_stats import taxa_stats
from tools.ecotaxa_client import EcotaxaClient, EcotaxaExportError
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
        if isinstance(exc, EcotaxaExportError):
            target = f"projet {exc.project_id}"
            status = f"HTTP {exc.status_code}"
            server = exc.server_message
        else:
            target = f"projet {project_id}" if project_id is not None else "EcoTaxa"
            status = type(exc).__name__
            server = str(exc) or "(pas de message serveur)"
        if sample_id is not None:
            target += f", sample {sample_id}"

        diagnostic = (
            f"preview_ecotaxa_project({project_id})"
            if project_id is not None
            else "list_ecotaxa_projects()"
        )

        return (
            f"EXPORT_FAILED — {target} ({status})\n"
            f"Message serveur : {server}\n"
            "Causes probables : droits Export manquants sur ce projet pour le "
            "compte configuré, projet privé, ou identifiants invalides.\n"
            f"Diagnostic suggéré : {diagnostic} pour vérifier l'accès, puis "
            "proposer un projet alternatif si l'accès est refusé. "
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

        store_dataset(
            _store,
            thread_id,
            df,
            variable_name=variable_name,
            meta={**meta, "source": f"ecotaxa:{project_id}", "project_id": project_id, "n_rows": len(df)},
            latest_alias="ecotaxa",
        )

        file_id = uuid.uuid4().hex
        tsv_path = _DOWNLOADS_DIR / f"{file_id}.tsv"
        df.to_csv(tsv_path, sep="\t", index=False)

        hint = _uvp_skill_hint(list(df.columns))
        summary = (
            f"{label} chargé — {len(df)} lignes, {len(df.columns)} colonnes.\n"
            f"Données disponibles dans `{variable_name}` et `df_ecotaxa`.\n"
            f"Appelle run_pandas directement pour analyser.\n"
            f"Télécharger : {download_url(f'{file_id}.tsv')}"
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
    def query_ecotaxa(
        project_id: int,
        taxon: str | None = None,
        status: str = "V",
        sample_ids: list[int] | None = None,
    ) -> str:
        """Interroge EcoTaxa et charge les données dans la session courante.

        Args:
            project_id: ID du projet EcoTaxa (ex: 1165, 2331).
            taxon: Filtre taxonomique optionnel (ex: "Copepoda").
            status: Statut des annotations — "V" (validé), "P" (prédit), "" (tous).
            sample_ids: IDs de samples EcoTaxa à exporter dans ce projet.
        """
        try:
            filters = {"statusfilter": status}
            if taxon:
                filters["taxo"] = taxon
            normalized_sample_ids = _normalize_sample_ids(sample_ids)
            if normalized_sample_ids:
                filters["samples"] = ",".join(str(sample_id) for sample_id in normalized_sample_ids)
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
                filters["taxo"] = taxon
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
        polygon_wkt: str | None = None,
        zone_name: str | None = None,
        project_ids: list[int] | None = None,
    ) -> str:
        """Cherche les samples EcoTaxa dans une bbox géo et/ou une période.

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
        Réponse plafonnée à 500 samples avec un summary par projet.
        Lecture du cache local — pas de download.

        Au moins UN filtre est requis (bbox, date_range, instrument,
        zone_name, polygon_wkt ou project_ids).
        """
        if (bbox is None and date_range is None and instrument is None
                and polygon_wkt is None and zone_name is None
                and not project_ids):
            return (
                "Erreur : au moins un filtre requis (bbox, date_range, instrument, zone_name, polygon_wkt ou project_ids). "
                "Pour explorer sans filtre, précise une bbox large, une période, ou un instrument."
            )
        try:
            result = samples_in_region(
                bbox=bbox, date_range=date_range, instrument=instrument,
                polygon_wkt=polygon_wkt, zone_name=zone_name,
                project_ids=project_ids,
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
        polygon_wkt: str | None = None,
        zone_name: str | None = None,
        project_ids: list[int] | None = None,
    ) -> str:
        """Liste les projets EcoTaxa avec au moins un sample dans une zone / période.

        Même format que `find_ecotaxa_samples_in_region` :
        - `zone_name` (recommandé pour les zones nommées NeoLab) : le tool
          résout le polygone IHO en interne.
        - `polygon_wkt` : polygone WKT fourni explicitement.
        - `bbox` / `date_range` : filtres classiques.
        - `project_ids` : restreint à une sous-liste de projets EcoTaxa.
        Quand un polygone (résolu ou explicite) est appliqué, les counts par
        projet excluent les samples hors zone.
        Réponse agrégée au niveau projet : nombre de samples, total objets,
        instruments, plage de dates.

        Au moins UN filtre (bbox, date_range, zone_name, polygon_wkt ou
        project_ids) est requis.
        """
        if (bbox is None and date_range is None
                and polygon_wkt is None and zone_name is None
                and not project_ids):
            return (
                "Erreur : au moins un filtre requis (bbox, date_range, zone_name, polygon_wkt ou project_ids). "
                "Pour la liste de tous les projets, utilise list_ecotaxa_projects."
            )
        try:
            result = projects_in_region(
                bbox=bbox, date_range=date_range,
                polygon_wkt=polygon_wkt, zone_name=zone_name,
                project_ids=project_ids,
            )
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
        polygon_wkt: str | None = None,
        zone_name: str | None = None,
        project_ids: list[int] | None = None,
    ) -> str:
        """Trouve les samples EcoTaxa dont le projet a le taxon attesté.

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
        """
        try:
            result = find_observations(
                taxon=taxon, bbox=bbox, date_range=date_range,
                instrument=instrument, status=status,
                polygon_wkt=polygon_wkt, zone_name=zone_name,
                project_ids=project_ids,
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

    @tool
    def get_ecotaxa_sample(sample_id: int) -> str:
        """Renvoie les métadonnées complètes d'un sample (déploiement) EcoTaxa.

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

        return "\n".join(lines)

    @tool
    def summarize_ecotaxa_samples(sample_ids: list[int]) -> str:
        """Résume un batch de samples EcoTaxa sans télécharger les objets.

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
        normalized = _normalize_sample_ids(sample_ids)
        if not normalized:
            return "Erreur : sample_ids vide."
        try:
            stats = summarize_samples(normalized)
        except Exception as exc:
            return f"Erreur lors du résumé EcoTaxa : {exc}"
        if not stats:
            return "Aucune statistique retournée par EcoTaxa pour ces samples."

        lines = [
            "| sample_id | projet | V | P | D | U | total | top taxa |",
            "|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for entry in stats:
            v = entry["nb_validated"]
            p = entry["nb_predicted"]
            d = entry["nb_dubious"]
            u = entry["nb_unclassified"]
            total = v + p + d + u
            names = [t["name"] for t in entry.get("per_taxon", [])[:5]]
            top = ", ".join(names) if names else "—"
            lines.append(
                f"| {entry['sample_id']} | {entry['projid']} | {v} | {p} | {d} | {u} | {total} | {top} |"
            )
        return "\n".join(lines)

    @tool
    def summarize_ecotaxa_sample(sample_id: int) -> str:
        """Résume UN sample EcoTaxa (V/P/D/U counts + taxa observés).

        Variante mono-sample de `summarize_ecotaxa_samples`. Renvoie le même
        tableau réduit à une ligne. Pas de download.
        """
        return summarize_ecotaxa_samples.invoke({"sample_ids": [sample_id]})

    @tool
    def summarize_ecotaxa_projects(project_ids: list[int]) -> str:
        """Résume un batch de projets EcoTaxa sans télécharger les objets.

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
            "| project_id | n_samples | date_min | date_max | bbox (S/W/N/E) | instruments | V | P | D | U | top taxa |",
            "|---:|---:|---|---|---|---|---:|---:|---:|---:|---|",
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
                f"{entry['nb_dubious']} | {entry['nb_unclassified']} | {top} |"
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

        Variante mono-projet de `summarize_ecotaxa_projects`. Renvoie le
        même tableau réduit à une ligne. Pas de download.
        """
        return summarize_ecotaxa_projects.invoke({"project_ids": [project_id]})

    @tool
    def export_ecotaxa_samples(
        sample_ids: list[int],
        confirmed: bool = False,
        status: str = "V",
        taxon: str | None = None,
    ) -> str:
        """Exporte une sélection de samples EcoTaxa, multi-projets en 1 appel.

        Groupe automatiquement les `sample_ids` par projet (via le cache
        local — pas d'appel API supplémentaire) et lance UN `query_ecotaxa`
        par projet avec le bon sous-ensemble de sample_ids. L'utilisateur
        n'a donc pas besoin de FOURNIR les project_id en entrée — mais ils
        sont systématiquement listés dans la réponse (plan dry-run et
        résumé d'exécution) pour traçabilité.

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
        normalized = _normalize_sample_ids(sample_ids)
        if not normalized:
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
                "",
                "| project_id | nb_samples | sample_ids |",
                "|---:|---:|---|",
            ]
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
                filters["taxo"] = taxon
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
        find_ecotaxa_projects_in_region,
        find_ecotaxa_observations,
        get_ecotaxa_sample,
        inspect_ecotaxa_project_schema,
        inspect_ecotaxa_column,
        count_ecotaxa_taxa,
        compare_ecotaxa_projects,
        list_ecotaxa_projects,
        preview_ecotaxa_project,
        query_ecotaxa,
        query_ecotaxa_sample,
        summarize_ecotaxa_sample,
        summarize_ecotaxa_samples,
        summarize_ecotaxa_project,
        summarize_ecotaxa_projects,
        export_ecotaxa_samples,
    ]
