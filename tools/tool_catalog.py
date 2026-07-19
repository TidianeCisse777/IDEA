"""Validated construction and user-facing metadata for LangChain tools.

This module is the composition seam shared by the agent runtime and the SSE
presentation layer. Routing is shared by executable source/exposure policies,
tool metadata, and the compact model-facing prompt kernel.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, TypeAlias, get_args

from langchain_core.tools import BaseTool

from tools.amundsen_sources import make_amundsen_tools
from tools.bio_oracle_sources import make_bio_oracle_tools
from tools.copepod_sources import make_source_tools
from tools.data_tools import make_tools
from tools.deliverable_tool import export_deliverable
from tools.ecopart_sources import make_ecopart_tools
from tools.geo_tools import get_zone_info, make_geo_tools
from tools.ogsl_sources import make_ogsl_tools
from tools.rag_tool import make_rag_tool
from tools.skill_tool import SKILLS_DIR, make_skill_tool
from tools.sql_workspace import SQLWorkspaceNotConfiguredError, make_sql_tools
from tools.taxonomy_tool import make_taxonomy_tool
from tools.tool_input import apply_strict_tool_schema
from tools.tool_result import ToolResultSchema

Language = Literal["fr", "en"]
ToolRisk = Literal["low", "medium", "high"]
ToolSource = Literal[
    "file",
    "ecotaxa",
    "ecopart",
    "amundsen",
    "bio_oracle",
    "ogsl",
    "sql",
    "geography",
    "knowledge",
    "taxonomy",
    "skill",
    "deliverable",
]
ToolExposureGroup: TypeAlias = Literal[
    "core",
    "file_analysis",
    "visualization",
    "geography",
    "taxonomy",
    "deliverable",
    "enrichment_ecopart",
    "enrichment_amundsen",
    "enrichment_bio_oracle",
    "enrichment_ogsl",
    "sql_workspace",
    "ecotaxa_discovery",
    "ecotaxa_samples",
    "ecotaxa_objects",
    "ecotaxa_geo_time",
    "ecotaxa_taxonomy",
    "ecotaxa_schema",
    "ecotaxa_audit",
    "ecotaxa_export",
    "hidden_legacy",
]
TOOL_EXPOSURE_GROUPS = frozenset(get_args(ToolExposureGroup))


@dataclass(frozen=True)
class LocalizedText:
    """French and English text with a safe French fallback."""

    fr: str
    en: str

    def for_language(self, language: str) -> str:
        return self.en if language == "en" else self.fr


@dataclass(frozen=True)
class ToolPresentation:
    """Presentation-only facts for one stable LangChain tool name."""

    label: LocalizedText
    family: str
    source_result: bool = False
    slow: bool = False
    progress: LocalizedText | None = None
    progress_detail: LocalizedText | None = None
    source_label: LocalizedText | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class ToolPolicy:
    """Executable control-plane facts for one stable tool name."""

    family: str
    source: ToolSource
    risk: ToolRisk
    read_only: bool
    mutates_session: bool
    remote_io: bool
    expensive: bool
    reversible: bool
    requires_confirmation: bool
    required_skill: str | None
    allowed_workflows: tuple[str, ...]
    max_calls_per_turn: int
    exposure_group: ToolExposureGroup
    result_schema: ToolResultSchema = "tool_result_v1"


@dataclass(frozen=True)
class ToolCatalog:
    """Immutable runtime tools with validated presentation lookup."""

    tools: tuple[BaseTool, ...]
    names: frozenset[str]
    presentations: Mapping[str, ToolPresentation]
    policies: Mapping[str, ToolPolicy]

    def presentation(self, name: str) -> ToolPresentation | None:
        return self.presentations.get(name)

    def policy(self, name: str) -> ToolPolicy | None:
        return self.policies.get(name)


def _text(fr: str, en: str) -> LocalizedText:
    return LocalizedText(fr=fr, en=en)


def _presentation(
    fr: str,
    en: str,
    family: str,
    *,
    source_result: bool = False,
    slow: bool = False,
    progress_fr: str | None = None,
    progress_en: str | None = None,
    progress_detail_fr: str | None = None,
    progress_detail_en: str | None = None,
    source_label: LocalizedText | None = None,
    source_url: str | None = None,
) -> ToolPresentation:
    if not fr.strip() or not en.strip() or not family.strip():
        raise ValueError("Tool presentation requires French, English, and family")
    if bool(progress_fr and progress_fr.strip()) != bool(
        progress_en and progress_en.strip()
    ):
        raise ValueError("progress requires both French and English")
    if bool(progress_detail_fr and progress_detail_fr.strip()) != bool(
        progress_detail_en and progress_detail_en.strip()
    ):
        raise ValueError("progress_detail requires both French and English")
    if progress_detail_fr and not progress_fr:
        raise ValueError("progress_detail requires progress")
    progress = None
    if progress_fr and progress_en:
        progress = _text(progress_fr, progress_en)
    progress_detail = None
    if progress_detail_fr and progress_detail_en:
        progress_detail = _text(progress_detail_fr, progress_detail_en)
    return ToolPresentation(
        label=_text(fr, en),
        family=family,
        source_result=source_result,
        slow=slow,
        progress=progress,
        progress_detail=progress_detail,
        source_label=source_label,
        source_url=source_url,
    )


ECOTAXA_SOURCE = _text("EcoTaxa", "EcoTaxa")
ECOPART_SOURCE = _text("EcoPart", "EcoPart")
BIO_ORACLE_SOURCE = _text("Bio-ORACLE", "Bio-ORACLE")
AMUNDSEN_SOURCE = _text("Amundsen Science", "Amundsen Science")
OGSL_SOURCE = _text("OGSL", "OGSL")
SQL_SOURCE = _text("Espace SQL", "SQL workspace")


def _source(
    fr: str,
    en: str,
    family: str,
    source_label: LocalizedText,
    source_url: str | None,
    *,
    slow: bool = False,
    progress_fr: str | None = None,
    progress_en: str | None = None,
    progress_detail_fr: str | None = None,
    progress_detail_en: str | None = None,
) -> ToolPresentation:
    return _presentation(
        fr,
        en,
        family,
        source_result=True,
        slow=slow,
        progress_fr=progress_fr,
        progress_en=progress_en,
        progress_detail_fr=progress_detail_fr,
        progress_detail_en=progress_detail_en,
        source_label=source_label,
        source_url=source_url,
    )


TOOL_PRESENTATION: Mapping[str, ToolPresentation] = MappingProxyType({
    # Local workspace and analysis.
    "load_file": _presentation("Chargement de fichier", "File loading", "data", slow=True),
    "run_pandas": _presentation("Analyse du tableau", "Table analysis", "data"),
    "run_graph": _presentation("Génération du graphique", "Chart generation", "data"),
    # EcoTaxa.
    "find_ecotaxa_projects": _source("EcoTaxa · recherche de projets", "EcoTaxa · project search", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "find_ecotaxa_samples_in_region": _source("EcoTaxa · samples par zone / période", "EcoTaxa · samples by region / period", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "combine_ecotaxa_selections": _source("EcoTaxa · combiner les sélections zonées", "EcoTaxa · combine zoned selections", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "group_ecotaxa_samples_by_year": _source("EcoTaxa · samples par année", "EcoTaxa · samples by year", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "find_ecotaxa_projects_in_region": _source("EcoTaxa · projets par zone", "EcoTaxa · projects by region", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "group_ecotaxa_project_samples_by_region": _source("EcoTaxa · répartition régionale", "EcoTaxa · regional distribution", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "rank_ecotaxa_samples_by_region": _source("EcoTaxa · classement par zone", "EcoTaxa · regional ranking", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "find_ecotaxa_observations": _source("EcoTaxa · recherche d’observations", "EcoTaxa · observation search", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "get_ecotaxa_sample": _source("EcoTaxa · métadonnées du sample", "EcoTaxa · sample metadata", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "list_ecotaxa_sample_objects": _source("EcoTaxa · objets du sample", "EcoTaxa · sample objects", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "get_ecotaxa_object": _source("EcoTaxa · détail d'un objet", "EcoTaxa · object detail", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "summarize_ecotaxa_sample_deployment": _source("EcoTaxa · déploiement du sample", "EcoTaxa · sample deployment", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "inspect_ecotaxa_project_schema": _source("EcoTaxa · schéma du projet", "EcoTaxa · project schema", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "inspect_ecotaxa_column": _source("EcoTaxa · inspection de colonne", "EcoTaxa · column inspection", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "count_ecotaxa_taxa": _source("EcoTaxa · comptage des taxons", "EcoTaxa · taxon counts", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "search_ecotaxa_taxa": _source("EcoTaxa · recherche de taxons", "EcoTaxa · taxon search", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "describe_ecotaxa_project_coverage": _source("EcoTaxa · couverture du projet (réseau vs cache)", "EcoTaxa · project coverage (network vs cache)", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "compare_ecotaxa_projects": _source("EcoTaxa · comparaison de projets", "EcoTaxa · project comparison", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "list_ecotaxa_projects": _source("EcoTaxa · projets accessibles", "EcoTaxa · accessible projects", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "list_ecotaxa_campaigns": _source("EcoTaxa · campagnes", "EcoTaxa · campaigns", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "preview_ecotaxa_project": _source("EcoTaxa · aperçu du projet", "EcoTaxa · project preview", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "query_ecotaxa": _source("EcoTaxa · export du projet", "EcoTaxa · project export", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr", slow=True, progress_fr="Export EcoTaxa en cours — cela peut prendre 1–2 minutes", progress_en="EcoTaxa export in progress — this may take 1–2 minutes"),
    "query_ecotaxa_sample": _source("EcoTaxa · export du sample", "EcoTaxa · sample export", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr", slow=True, progress_fr="Export du sample EcoTaxa en cours — cela peut prendre 1–2 minutes", progress_en="EcoTaxa sample export in progress — this may take 1–2 minutes"),
    "summarize_ecotaxa_sample": _source("EcoTaxa · résumé du sample", "EcoTaxa · sample summary", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "summarize_ecotaxa_samples": _source("EcoTaxa · résumé de samples", "EcoTaxa · samples summary", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "summarize_ecotaxa_project": _source("EcoTaxa · résumé du projet", "EcoTaxa · project summary", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "summarize_ecotaxa_projects": _source("EcoTaxa · résumé des projets", "EcoTaxa · projects summary", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "export_ecotaxa_samples": _source("EcoTaxa · export des samples", "EcoTaxa · samples export", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr", slow=True),
    "resolve_ecotaxa_sample": _source("EcoTaxa · résolution de sample", "EcoTaxa · sample resolver", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "audit_ecotaxa_spatial_coverage": _source("EcoTaxa · audit de couverture spatiale", "EcoTaxa · spatial coverage audit", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "list_ecotaxa_cache_tables": _source("EcoTaxa · tables du cache", "EcoTaxa · cache tables", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "describe_ecotaxa_cache_table": _source("EcoTaxa · schéma d'une table cache", "EcoTaxa · cache table schema", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    "query_ecotaxa_cache": _source("EcoTaxa · SQL cache", "EcoTaxa · SQL cache", "ecotaxa", ECOTAXA_SOURCE, "https://ecotaxa.obs-vlfr.fr"),
    # Bio-ORACLE.
    "list_bio_oracle_datasets": _source("Bio-ORACLE · jeux de données", "Bio-ORACLE · datasets", "bio_oracle", BIO_ORACLE_SOURCE, "https://erddap.bio-oracle.org/erddap"),
    "preview_bio_oracle_point": _source("Bio-ORACLE · aperçu ponctuel", "Bio-ORACLE · point preview", "bio_oracle", BIO_ORACLE_SOURCE, "https://erddap.bio-oracle.org/erddap"),
    "query_bio_oracle": _source("Bio-ORACLE · extraction", "Bio-ORACLE · extraction", "bio_oracle", BIO_ORACLE_SOURCE, "https://erddap.bio-oracle.org/erddap", slow=True, progress_fr="Extraction Bio-ORACLE en cours — cela peut prendre 1–2 minutes", progress_en="Bio-ORACLE extraction in progress — this may take 1–2 minutes"),
    "couple_zooplankton_bio_oracle": _source("Bio-ORACLE · couplage environnemental", "Bio-ORACLE · environmental coupling", "bio_oracle", BIO_ORACLE_SOURCE, "https://erddap.bio-oracle.org/erddap", slow=True),
    "query_bio_oracle_zones": _source("Bio-ORACLE · extraction par zones", "Bio-ORACLE · zone extraction", "bio_oracle", BIO_ORACLE_SOURCE, "https://erddap.bio-oracle.org/erddap"),
    "find_bio_oracle_data_for_table": _source("Bio-ORACLE · disponibilité pour le tableau", "Bio-ORACLE · availability for table", "bio_oracle", BIO_ORACLE_SOURCE, "https://erddap.bio-oracle.org/erddap"),
    "enrich_with_bio_oracle": _source("Bio-ORACLE · enrichissement du tableau", "Bio-ORACLE · table enrichment", "bio_oracle", BIO_ORACLE_SOURCE, "https://erddap.bio-oracle.org/erddap", slow=True, progress_fr="Préparation de l’enrichissement Bio-ORACLE", progress_en="Preparing Bio-ORACLE enrichment", progress_detail_fr="Le cache de données sera vérifié automatiquement avant le calcul.", progress_detail_en="The data cache will be checked automatically before computation."),
    # Amundsen CTD.
    "list_amundsen_datasets": _source("Amundsen · jeux de données CTD", "Amundsen · CTD datasets", "amundsen", AMUNDSEN_SOURCE, "https://erddap.amundsenscience.com/erddap"),
    "preview_amundsen_profile": _source("Amundsen · aperçu du profil CTD", "Amundsen · CTD profile preview", "amundsen", AMUNDSEN_SOURCE, "https://erddap.amundsenscience.com/erddap"),
    "query_amundsen_ctd": _source("Amundsen · extraction CTD", "Amundsen · CTD extraction", "amundsen", AMUNDSEN_SOURCE, "https://erddap.amundsenscience.com/erddap", slow=True, progress_fr="Extraction Amundsen CTD en cours — cela peut prendre 1–2 minutes", progress_en="Amundsen CTD extraction in progress — this may take 1–2 minutes"),
    "find_amundsen_data_for_table": _source("Amundsen · disponibilité pour le tableau", "Amundsen · availability for table", "amundsen", AMUNDSEN_SOURCE, "https://erddap.amundsenscience.com/erddap"),
    "enrich_loaded_table_with_amundsen_ctd": _source("Amundsen · enrichissement du tableau chargé", "Amundsen · loaded table enrichment", "amundsen", AMUNDSEN_SOURCE, "https://erddap.amundsenscience.com/erddap", slow=True, progress_fr="Préparation de l’enrichissement CTD", progress_en="Preparing CTD enrichment", progress_detail_fr="Le cache de données sera vérifié automatiquement avant le calcul.", progress_detail_en="The data cache will be checked automatically before computation."),
    "enrich_with_amundsen_ctd": _source("Amundsen · enrichissement CTD", "Amundsen · CTD enrichment", "amundsen", AMUNDSEN_SOURCE, "https://erddap.amundsenscience.com/erddap", slow=True, progress_fr="Préparation de l’enrichissement CTD", progress_en="Preparing CTD enrichment", progress_detail_fr="Le cache de données sera vérifié automatiquement avant le calcul.", progress_detail_en="The data cache will be checked automatically before computation."),
    # OGSL.
    "query_ogsl": _source("OGSL · extraction CTD", "OGSL · CTD extraction", "ogsl", OGSL_SOURCE, "https://erddap.ogsl.ca/erddap", slow=True),
    "enrich_with_ogsl": _source("OGSL · enrichissement CTD", "OGSL · CTD enrichment", "ogsl", OGSL_SOURCE, "https://erddap.ogsl.ca/erddap", slow=True, progress_fr="Préparation de l’enrichissement OGSL", progress_en="Preparing OGSL enrichment", progress_detail_fr="Le cache de données sera vérifié automatiquement avant le calcul.", progress_detail_en="The data cache will be checked automatically before computation."),
    # EcoPart.
    "list_ecopart_samples": _source("EcoPart · samples accessibles", "EcoPart · accessible samples", "ecopart", ECOPART_SOURCE, "https://ecopart.obs-vlfr.fr"),
    "preview_ecopart_sample": _source("EcoPart · aperçu du sample", "EcoPart · sample preview", "ecopart", ECOPART_SOURCE, "https://ecopart.obs-vlfr.fr"),
    "query_ecopart": _source("EcoPart · extraction", "EcoPart · extraction", "ecopart", ECOPART_SOURCE, "https://ecopart.obs-vlfr.fr", slow=True, progress_fr="Téléchargement EcoPart en cours — cela peut prendre 1–2 minutes", progress_en="EcoPart download in progress — this may take 1–2 minutes"),
    "join_ecotaxa_ecopart": _source("EcoTaxa/EcoPart · jumelage", "EcoTaxa/EcoPart · join", "ecopart", ECOPART_SOURCE, "https://ecopart.obs-vlfr.fr"),
    "enrich_ecotaxa_with_ecopart_remote": _source("EcoTaxa/EcoPart · enrichissement distant", "EcoTaxa/EcoPart · remote enrichment", "ecopart", ECOPART_SOURCE, "https://ecopart.obs-vlfr.fr", slow=True, progress_fr="Préparation du jumelage EcoTaxa/EcoPart", progress_en="Preparing EcoTaxa/EcoPart join", progress_detail_fr="Le cache de données sera vérifié automatiquement avant le calcul.", progress_detail_en="The data cache will be checked automatically before computation."),
    "find_ecopart_project_for_ecotaxa": _source("EcoPart · projet correspondant", "EcoPart · matching project", "ecopart", ECOPART_SOURCE, "https://ecopart.obs-vlfr.fr"),
    "audit_ecotaxa_ecopart_join": _source("EcoTaxa/EcoPart · audit de jumelage", "EcoTaxa/EcoPart · join audit", "ecopart", ECOPART_SOURCE, "https://ecopart.obs-vlfr.fr"),
    # Geography and core services.
    "filter_dataframe_by_zone": _presentation("Filtrage géographique", "Geographic filtering", "geography"),
    "split_dataframe_by_zone": _presentation("Découpage géographique", "Geographic split", "geography"),
    "get_zone_info": _presentation("Information géographique", "Geographic information", "geography"),
    "query_copepod_knowledge_base": _presentation("Recherche documentaire", "Knowledge-base search", "core"),
    "lookup_marine_taxonomy": _presentation("Recherche taxonomique", "Taxonomy lookup", "core"),
    "load_skill": _presentation("Chargement des instructions spécialisées", "Specialized instructions loading", "core"),
    "export_deliverable": _presentation("Export du livrable", "Deliverable export", "core", slow=True),
    # Optional read-only SQL workspace.
    "list_sql_tables": _source("SQL · tables accessibles", "SQL · accessible tables", "sql", SQL_SOURCE, None),
    "preview_sql_table": _source("SQL · aperçu de table", "SQL · table preview", "sql", SQL_SOURCE, None),
    "copy_sql_query_to_workspace": _source("SQL · copie vers l’espace de travail", "SQL · copy to workspace", "sql", SQL_SOURCE, None),
})

OPTIONAL_SQL_TOOL_NAMES = frozenset(
    {"list_sql_tables", "preview_sql_table", "copy_sql_query_to_workspace"}
)


@dataclass(frozen=True)
class _PolicyProfile:
    risk: ToolRisk
    read_only: bool
    mutates_session: bool
    remote_io: bool
    expensive: bool
    reversible: bool
    requires_confirmation: bool
    max_calls_per_turn: int


_POLICY_PROFILES: Mapping[str, _PolicyProfile] = MappingProxyType({
    "local_read": _PolicyProfile("low", True, False, False, False, True, False, 3),
    "local_session": _PolicyProfile("medium", False, True, False, False, True, False, 3),
    "local_artifact": _PolicyProfile("medium", False, True, False, True, True, False, 2),
    "local_heavy": _PolicyProfile("high", False, True, False, True, True, True, 1),
    "skill_session": _PolicyProfile("medium", False, True, True, False, True, False, 3),
    "remote_read": _PolicyProfile("low", True, False, True, False, True, False, 3),
    "remote_session": _PolicyProfile("medium", False, True, True, False, True, False, 2),
    "remote_heavy": _PolicyProfile("high", False, True, True, True, True, True, 1),
    "local_source_read": _PolicyProfile("low", True, False, False, False, True, False, 3),
    "local_source_session": _PolicyProfile("medium", False, True, False, False, True, False, 2),
})


# Every stable name is deliberately classified. There is no default profile:
# adding a presentation/runtime tool without adding it here fails validation.
_TOOL_PROFILE_BY_NAME: Mapping[str, str] = MappingProxyType({
    # Local data/code execution.
    "load_file": "local_session",
    "run_pandas": "local_session",
    "run_graph": "local_artifact",
    # EcoTaxa read-only/cache navigation.
    "audit_ecotaxa_spatial_coverage": "remote_read",
    "list_ecotaxa_cache_tables": "local_source_read",
    "describe_ecotaxa_cache_table": "local_source_read",
    "query_ecotaxa_cache": "local_source_read",
    "compare_ecotaxa_projects": "remote_read",
    "count_ecotaxa_taxa": "remote_read",
    "describe_ecotaxa_project_coverage": "remote_read",
    "find_ecotaxa_projects": "remote_read",
    "find_ecotaxa_projects_in_region": "remote_read",
    "get_ecotaxa_sample": "remote_read",
    "list_ecotaxa_sample_objects": "remote_read",
    "get_ecotaxa_object": "remote_read",
    "group_ecotaxa_project_samples_by_region": "remote_read",
    "inspect_ecotaxa_column": "remote_read",
    "inspect_ecotaxa_project_schema": "remote_read",
    "list_ecotaxa_campaigns": "remote_read",
    "resolve_ecotaxa_sample": "remote_read",
    "list_ecotaxa_projects": "remote_read",
    "preview_ecotaxa_project": "remote_read",
    "rank_ecotaxa_samples_by_region": "remote_read",
    "search_ecotaxa_taxa": "remote_read",
    "summarize_ecotaxa_project": "remote_read",
    "summarize_ecotaxa_projects": "remote_read",
    "summarize_ecotaxa_sample": "remote_read",
    "summarize_ecotaxa_sample_deployment": "remote_read",
    "summarize_ecotaxa_samples": "remote_read",
    # EcoTaxa selection/session and heavy extraction.
    "find_ecotaxa_observations": "remote_session",
    "find_ecotaxa_samples_in_region": "remote_session",
    "combine_ecotaxa_selections": "remote_session",
    "group_ecotaxa_samples_by_year": "remote_session",
    "export_ecotaxa_samples": "remote_heavy",
    "query_ecotaxa": "remote_heavy",
    "query_ecotaxa_sample": "remote_heavy",
    # Bio-ORACLE.
    "find_bio_oracle_data_for_table": "remote_read",
    "list_bio_oracle_datasets": "remote_read",
    "preview_bio_oracle_point": "remote_read",
    "query_bio_oracle_zones": "remote_session",
    "couple_zooplankton_bio_oracle": "remote_heavy",
    "enrich_with_bio_oracle": "remote_heavy",
    "query_bio_oracle": "remote_heavy",
    # Amundsen CTD.
    "find_amundsen_data_for_table": "remote_read",
    "list_amundsen_datasets": "remote_read",
    "preview_amundsen_profile": "remote_read",
    "enrich_loaded_table_with_amundsen_ctd": "remote_heavy",
    "enrich_with_amundsen_ctd": "remote_heavy",
    "query_amundsen_ctd": "remote_heavy",
    # OGSL.
    "enrich_with_ogsl": "remote_heavy",
    "query_ogsl": "remote_heavy",
    # EcoPart. Local join/audit are explicitly distinguished from remote I/O.
    "find_ecopart_project_for_ecotaxa": "remote_read",
    "list_ecopart_samples": "remote_read",
    "preview_ecopart_sample": "remote_read",
    "audit_ecotaxa_ecopart_join": "local_source_read",
    "join_ecotaxa_ecopart": "local_source_session",
    "enrich_ecotaxa_with_ecopart_remote": "remote_heavy",
    "query_ecopart": "remote_heavy",
    # Geography and core services.
    "get_zone_info": "local_read",
    "filter_dataframe_by_zone": "local_session",
    "split_dataframe_by_zone": "local_session",
    "query_copepod_knowledge_base": "local_read",
    "lookup_marine_taxonomy": "remote_read",
    "load_skill": "skill_session",
    "export_deliverable": "local_heavy",
    # Optional SQL workspace.
    "list_sql_tables": "remote_read",
    "preview_sql_table": "remote_read",
    "copy_sql_query_to_workspace": "remote_heavy",
})


_SOURCE_BY_FAMILY: Mapping[str, ToolSource] = MappingProxyType({
    "data": "file",
    "ecotaxa": "ecotaxa",
    "ecopart": "ecopart",
    "amundsen": "amundsen",
    "bio_oracle": "bio_oracle",
    "ogsl": "ogsl",
    "sql": "sql",
    "geography": "geography",
})

_CORE_SOURCE_BY_NAME: Mapping[str, ToolSource] = MappingProxyType({
    "query_copepod_knowledge_base": "knowledge",
    "lookup_marine_taxonomy": "taxonomy",
    "load_skill": "skill",
    "export_deliverable": "deliverable",
})

_EXPOSURE_GROUP_BY_NAME: Mapping[str, ToolExposureGroup] = MappingProxyType({
    # Permanent core and state-gated local tools.
    "load_file": "core",
    "load_skill": "core",
    "query_copepod_knowledge_base": "core",
    "run_pandas": "file_analysis",
    "run_graph": "visualization",
    "get_zone_info": "geography",
    "filter_dataframe_by_zone": "geography",
    # Le découpage annote le DataFrame chargé : c'est une capacité d'analyse de
    # fichier, exposée seulement quand un fichier est chargé. La garder hors du
    # groupe permanent "geography" préserve le budget d'outils EcoTaxa.
    "split_dataframe_by_zone": "file_analysis",
    "lookup_marine_taxonomy": "taxonomy",
    "export_deliverable": "deliverable",
    # Canonical enrichment-only external paths.
    "enrich_ecotaxa_with_ecopart_remote": "enrichment_ecopart",
    "enrich_with_amundsen_ctd": "enrichment_amundsen",
    "enrich_with_bio_oracle": "enrichment_bio_oracle",
    "enrich_with_ogsl": "enrichment_ogsl",
    # EcoTaxa discovery.
    "list_ecotaxa_projects": "ecotaxa_discovery",
    "find_ecotaxa_projects": "ecotaxa_discovery",
    "list_ecotaxa_campaigns": "ecotaxa_discovery",
    "preview_ecotaxa_project": "ecotaxa_discovery",
    "list_ecotaxa_cache_tables": "ecotaxa_discovery",
    "describe_ecotaxa_cache_table": "ecotaxa_discovery",
    "describe_ecotaxa_project_coverage": "ecotaxa_audit",
    # Cross-project reference resolution is part of EcoTaxa discovery and stays
    # visible in the deterministic overflow fallback used by the agent.
    "resolve_ecotaxa_sample": "ecotaxa_discovery",
    "get_ecotaxa_sample": "ecotaxa_samples",
    # A paginated API page is neither persistent nor suitable for an object-level
    # analysis. Keep these compatibility tools out of the LLM's normal routing.
    "list_ecotaxa_sample_objects": "hidden_legacy",
    "get_ecotaxa_object": "hidden_legacy",
    "summarize_ecotaxa_sample": "ecotaxa_samples",
    "summarize_ecotaxa_samples": "ecotaxa_samples",
    "summarize_ecotaxa_sample_deployment": "ecotaxa_samples",
    # EcoTaxa geography and time — replaced by query_ecotaxa_cache SQL.
    "find_ecotaxa_samples_in_region": "hidden_legacy",
    "combine_ecotaxa_selections": "hidden_legacy",
    "group_ecotaxa_samples_by_year": "hidden_legacy",
    "find_ecotaxa_projects_in_region": "hidden_legacy",
    "group_ecotaxa_project_samples_by_region": "hidden_legacy",
    "rank_ecotaxa_samples_by_region": "hidden_legacy",
    # EcoTaxa taxonomy.
    "search_ecotaxa_taxa": "ecotaxa_taxonomy",
    "count_ecotaxa_taxa": "ecotaxa_taxonomy",
    "find_ecotaxa_observations": "ecotaxa_taxonomy",
    # EcoTaxa schema.
    "inspect_ecotaxa_project_schema": "ecotaxa_schema",
    "inspect_ecotaxa_column": "ecotaxa_schema",
    "compare_ecotaxa_projects": "ecotaxa_schema",
    # EcoTaxa audit — cache-only tools replaced by query_ecotaxa_cache SQL.
    "audit_ecotaxa_spatial_coverage": "hidden_legacy",
    "query_ecotaxa_cache": "ecotaxa_discovery",
    "summarize_ecotaxa_project": "hidden_legacy",
    "summarize_ecotaxa_projects": "hidden_legacy",
    # EcoTaxa exports.
    "query_ecotaxa": "ecotaxa_export",
    "query_ecotaxa_sample": "ecotaxa_export",
    "export_ecotaxa_samples": "ecotaxa_export",
    # Optional SQL workspace.
    "list_sql_tables": "sql_workspace",
    "preview_sql_table": "sql_workspace",
    "copy_sql_query_to_workspace": "sql_workspace",
    # Registered for compatibility, never advertised by step 6.
    "list_ecopart_samples": "hidden_legacy",
    "preview_ecopart_sample": "hidden_legacy",
    "find_ecopart_project_for_ecotaxa": "hidden_legacy",
    "query_ecopart": "hidden_legacy",
    "join_ecotaxa_ecopart": "hidden_legacy",
    "audit_ecotaxa_ecopart_join": "hidden_legacy",
    "list_amundsen_datasets": "hidden_legacy",
    "preview_amundsen_profile": "hidden_legacy",
    "find_amundsen_data_for_table": "hidden_legacy",
    "enrich_loaded_table_with_amundsen_ctd": "hidden_legacy",
    "query_amundsen_ctd": "hidden_legacy",
    "list_bio_oracle_datasets": "hidden_legacy",
    "preview_bio_oracle_point": "hidden_legacy",
    "query_bio_oracle_zones": "hidden_legacy",
    "find_bio_oracle_data_for_table": "hidden_legacy",
    "couple_zooplankton_bio_oracle": "hidden_legacy",
    "query_bio_oracle": "hidden_legacy",
    "query_ogsl": "hidden_legacy",
})

_REQUIRED_SKILL_BY_FAMILY: Mapping[str, str] = MappingProxyType({
    "ecotaxa": "ecotaxa_navigation",
    "ecopart": "ecopart_query",
    "amundsen": "amundsen_ctd_query",
    "bio_oracle": "bio_oracle_query",
    "ogsl": "ogsl_query",
})

def _build_policy(name: str, profile_name: str) -> ToolPolicy:
    presentation = TOOL_PRESENTATION[name]
    profile = _POLICY_PROFILES[profile_name]
    source = _CORE_SOURCE_BY_NAME.get(name) or _SOURCE_BY_FAMILY[presentation.family]
    required_skill = _REQUIRED_SKILL_BY_FAMILY.get(presentation.family)
    if name == "run_graph":
        required_skill = "graph_writer"
    elif name == "export_deliverable":
        required_skill = "deliverable_writer"
    workflows = (
        ("visualization",)
        if name == "run_graph"
        else ("deliverable",)
        if name == "export_deliverable"
        else (presentation.family,)
    )
    return ToolPolicy(
        family=presentation.family,
        source=source,
        risk=profile.risk,
        read_only=profile.read_only,
        mutates_session=profile.mutates_session,
        remote_io=profile.remote_io,
        expensive=profile.expensive,
        reversible=profile.reversible,
        requires_confirmation=profile.requires_confirmation,
        required_skill=required_skill,
        allowed_workflows=workflows,
        max_calls_per_turn=profile.max_calls_per_turn,
        exposure_group=_EXPOSURE_GROUP_BY_NAME[name],
        result_schema="tool_result_v1",
    )


TOOL_POLICIES: Mapping[str, ToolPolicy] = MappingProxyType({
    name: _build_policy(name, profile_name)
    for name, profile_name in _TOOL_PROFILE_BY_NAME.items()
})


def _normalize_supported_language(value: object) -> Language | None:
    if not isinstance(value, str):
        return None
    selected: Language | None = None
    selected_quality = -1.0
    for preference in value.split(","):
        parts = [part.strip() for part in preference.split(";")]
        token = parts[0].lower().replace("_", "-")
        base = token.split("-", 1)[0]
        if base not in {"fr", "en"}:
            continue
        quality = 1.0
        for parameter in parts[1:]:
            if parameter.lower().startswith("q="):
                try:
                    quality = float(parameter.split("=", 1)[1])
                except ValueError:
                    quality = 0.0
                if not 0.0 <= quality <= 1.0:
                    quality = 0.0
        if quality > 0 and quality > selected_quality:
            selected = base  # type: ignore[assignment]
            selected_quality = quality
    return selected


def resolve_user_language(
    metadata: dict | None = None,
    accept_language: str | None = None,
) -> Language:
    """Resolve an explicit user locale, with French as the safe default."""

    if isinstance(metadata, dict):
        for key in ("language", "locale"):
            if language := _normalize_supported_language(metadata.get(key)):
                return language
    if language := _normalize_supported_language(accept_language):
        return language
    return "fr"


def get_tool_presentation(name: str) -> ToolPresentation | None:
    """Return presentation metadata without ever deriving UI text from a name."""

    return TOOL_PRESENTATION.get(name)


def validate_catalog(
    tool_names: Collection[str],
    *,
    optional_names: Collection[str] = (),
    runtime_tools: Collection[BaseTool] = (),
) -> None:
    """Fail fast when runtime tools and declared presentation facts drift."""

    names = set(tool_names)
    optional = set(optional_names)
    metadata_names = set(TOOL_PRESENTATION)
    missing = sorted(names - metadata_names)
    if missing:
        raise ValueError(f"Tool catalog missing metadata: {', '.join(missing)}")
    orphaned = sorted(metadata_names - names - optional)
    if orphaned:
        raise ValueError(f"Tool catalog orphan metadata: {', '.join(orphaned)}")
    missing_source_identity = sorted(
        name
        for name in names
        if TOOL_PRESENTATION[name].source_result
        and TOOL_PRESENTATION[name].source_label is None
    )
    if missing_source_identity:
        raise ValueError(
            "Tool catalog source identity missing: "
            + ", ".join(missing_source_identity)
        )
    incomplete = []
    for name in sorted(names | optional):
        presentation = TOOL_PRESENTATION[name]
        localized_values = [presentation.label]
        if presentation.progress is not None:
            localized_values.append(presentation.progress)
        if presentation.progress_detail is not None:
            localized_values.append(presentation.progress_detail)
        if presentation.source_label is not None:
            localized_values.append(presentation.source_label)
        localized_complete = all(
            value.fr.strip() and value.en.strip() for value in localized_values
        )
        progress_complete = not (
            presentation.progress_detail is not None
            and presentation.progress is None
        )
        if (
            not presentation.family.strip()
            or not localized_complete
            or not progress_complete
        ):
            incomplete.append(name)
    if incomplete:
        raise ValueError(
            "Tool catalog incomplete presentation: " + ", ".join(incomplete)
        )

    policy_names = set(TOOL_POLICIES)
    missing_policies = sorted(names - policy_names)
    if missing_policies:
        raise ValueError(f"Tool catalog missing policy: {', '.join(missing_policies)}")
    orphaned_policies = sorted(policy_names - names - optional)
    if orphaned_policies:
        raise ValueError(
            f"Tool catalog orphan policy: {', '.join(orphaned_policies)}"
        )
    exposure_names = set(_EXPOSURE_GROUP_BY_NAME)
    missing_exposure = sorted((names | optional) - exposure_names)
    orphaned_exposure = sorted(exposure_names - names - optional)
    if missing_exposure:
        raise ValueError(
            f"Tool catalog missing exposure group: {', '.join(missing_exposure)}"
        )
    if orphaned_exposure:
        raise ValueError(
            f"Tool catalog orphan exposure group: {', '.join(orphaned_exposure)}"
        )

    policy_issues = []
    local_skills = {path.stem for path in SKILLS_DIR.glob("*.md")}
    for name in sorted(names | optional):
        presentation = TOOL_PRESENTATION[name]
        policy = TOOL_POLICIES[name]
        issues = []
        if policy.family != presentation.family:
            issues.append("family")
        if policy.read_only and policy.mutates_session:
            issues.append("read_only+mutates_session")
        if policy.requires_confirmation and policy.risk != "high":
            issues.append("confirmation_without_high_risk")
        if policy.max_calls_per_turn < 1:
            issues.append("max_calls_per_turn")
        if policy.exposure_group not in TOOL_EXPOSURE_GROUPS:
            issues.append("exposure_group")
        if policy.result_schema != "tool_result_v1":
            issues.append("legacy result schema")
        if not policy.allowed_workflows:
            issues.append("allowed_workflows")
        if policy.required_skill and policy.required_skill not in local_skills:
            issues.append(f"unknown_skill={policy.required_skill}")
        if issues:
            policy_issues.append(f"{name} ({', '.join(issues)})")
    if policy_issues:
        raise ValueError(
            "Tool catalog invalid policy: " + "; ".join(policy_issues)
        )

    schema_issues = []
    for item in runtime_tools:
        schema = getattr(item, "args_schema", None)
        config = getattr(schema, "model_config", {})
        if config.get("strict") is not True or config.get("extra") != "forbid":
            schema_issues.append(item.name)
    if schema_issues:
        raise ValueError(
            "Tool catalog non-strict args schema: " + ", ".join(sorted(schema_issues))
        )

    result_format_issues = sorted(
        item.name
        for item in runtime_tools
        if getattr(item, "response_format", None) != "content_and_artifact"
    )
    if result_format_issues:
        raise ValueError(
            "Tool catalog non-structured result format: "
            + ", ".join(result_format_issues)
        )


def build_tool_catalog(thread_id: str) -> ToolCatalog:
    """Build the exact thread-scoped runtime tools and validate presentation."""

    tools: list[BaseTool] = [
        *make_tools(thread_id),
        *make_source_tools(thread_id),
        *make_bio_oracle_tools(thread_id),
        *make_amundsen_tools(thread_id),
        *make_ogsl_tools(thread_id),
        *make_ecopart_tools(thread_id),
        *make_geo_tools(thread_id),
        make_rag_tool(),
        make_taxonomy_tool(),
        make_skill_tool(thread_id=thread_id),
        export_deliverable,
        get_zone_info,
    ]
    sql_available = True
    try:
        tools.extend(make_sql_tools(thread_id))
    except SQLWorkspaceNotConfiguredError:
        sql_available = False

    tools = [apply_strict_tool_schema(item) for item in tools]

    name_counts = Counter(tool.name for tool in tools)
    duplicates = sorted(name for name, count in name_counts.items() if count > 1)
    if duplicates:
        raise ValueError(
            f"Tool catalog duplicate runtime names: {', '.join(duplicates)}"
        )
    names = frozenset(name_counts)
    validate_catalog(
        names,
        optional_names=() if sql_available else OPTIONAL_SQL_TOOL_NAMES,
        runtime_tools=tools,
    )
    return ToolCatalog(
        tools=tuple(tools),
        names=names,
        presentations=MappingProxyType(
            {name: TOOL_PRESENTATION[name] for name in names}
        ),
        policies=MappingProxyType(
            {name: TOOL_POLICIES[name] for name in names}
        ),
    )
