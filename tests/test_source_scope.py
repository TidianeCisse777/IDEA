"""Source-scope gate: a loaded file is the default target; EcoTaxa needs a signal."""

from dataclasses import dataclass

import pytest

from tools.source_scope import (
    ecotaxa_signal,
    filter_tools_for_scope,
    is_ecotaxa_scoped_tool,
    is_ecotaxa_skill_load,
    is_file_scoped_turn,
    latest_user_text,
)


@dataclass
class _Tool:
    name: str


class _FakeStore:
    def __init__(self, has_df: bool):
        self._has_df = has_df

    def get(self, thread_id):
        return {"df": object() if self._has_df else None}


# --- ecotaxa_signal: generic sampling words are NOT signals -------------------

@pytest.mark.parametrize("text", [
    "Je veux une carte des positions des échantillons dans la mer du Labrador",
    "carte avec les positions de tous les samples de la Baie de Baffin",
    "ajoute la côte",
    "nombre de taxons par échantillon",
    "les stations situées dans Hudson Bay",
])
def test_generic_sampling_words_are_not_ecotaxa_signals(text):
    assert ecotaxa_signal(text) is False


@pytest.mark.parametrize("text", [
    "samples EcoTaxa en mer de Baffin",
    "enrichis avec EcoPart",
    "regarde dans le cache EcoTaxa",
    "https://ecotaxa.obs-vlfr.fr/prj/17498",
])
def test_explicit_ecotaxa_references_are_signals(text):
    assert ecotaxa_signal(text) is True


@pytest.mark.parametrize("text", [
    "résume le projet 17498 avant export",
    "show project 17498",
    "inspecte prj/17498",
])
def test_bare_project_ids_are_not_source_signals(text):
    assert ecotaxa_signal(text) is False


def test_bare_project_id_never_selects_ecotaxa():
    from tools.source_scope import decide_source

    decision = decide_source(
        "résume le projet 17498",
        affinity=None,
        file_loaded=False,
    )

    assert decision.authorized_sources == ()
    assert decision.needs_clarification is True


def test_explicit_ecotaxa_establishes_source():
    from tools.source_scope import decide_source

    decision = decide_source(
        "dans EcoTaxa, résume le projet 17498",
        affinity=None,
        file_loaded=False,
    )

    assert decision.primary_source == "ecotaxa"
    assert decision.explicit_sources == ("ecotaxa",)


def test_active_ecotaxa_is_inherited_without_repeating_source_name():
    from tools.source_scope import SourceAffinity, decide_source

    decision = decide_source(
        "montre les samples du projet 17498",
        affinity=SourceAffinity(
            active_sources=("ecotaxa",),
            evidence="explicit_name",
            origin_user_text="Explore EcoTaxa",
            updated_at="2026-07-15T12:00:00+00:00",
        ),
        file_loaded=False,
    )

    assert decision.authorized_sources == ("ecotaxa",)
    assert decision.evidence == "inherited_affinity"


def test_comparison_combines_active_and_new_source():
    from tools.source_scope import SourceAffinity, decide_source

    affinity = SourceAffinity(
        active_sources=("ecotaxa",),
        evidence="explicit_name",
        origin_user_text="Explore EcoTaxa",
        updated_at="2026-07-15T12:00:00+00:00",
    )
    decision = decide_source(
        "compare avec EcoPart",
        affinity=affinity,
        file_loaded=False,
    )

    assert decision.authorized_sources == ("ecotaxa", "ecopart")


def test_explicit_enrichment_replaces_stale_external_affinity_but_keeps_file():
    from tools.source_scope import SourceAffinity, decide_source

    affinity = SourceAffinity(
        active_sources=("file", "ecotaxa", "ecopart"),
        evidence="explicit_name",
        origin_user_text="Exporte le sample EcoTaxa avec EcoPart",
        updated_at="2026-07-15T12:00:00+00:00",
    )
    decision = decide_source(
        "Enrichis le sample avec Amundsen.",
        affinity=affinity,
        file_loaded=True,
    )

    assert decision.authorized_sources == ("file", "amundsen")
    assert decision.explicit_sources == ("amundsen",)


def test_loaded_file_takes_over_inherited_ecotaxa_for_implicit_followup():
    from tools.source_scope import SourceAffinity, decide_source

    decision = decide_source(
        "Liste les stations et les casts",
        affinity=SourceAffinity(
            active_sources=("ecotaxa",),
            evidence="explicit_name",
            origin_user_text="Explore EcoTaxa",
            updated_at="2026-07-17T12:00:00+00:00",
        ),
        file_loaded=True,
    )

    assert decision.authorized_sources == ("file",)
    assert decision.primary_source == "file"
    assert decision.evidence == "loaded_file_default"


def test_explicit_multi_source_enrichment_keeps_only_named_sources_and_file():
    from tools.source_scope import SourceAffinity, decide_source

    affinity = SourceAffinity(
        active_sources=("file", "ecotaxa", "ecopart"),
        evidence="explicit_name",
        origin_user_text="Exporte le sample EcoTaxa avec EcoPart",
        updated_at="2026-07-15T12:00:00+00:00",
    )
    decision = decide_source(
        "Enrichis le fichier avec Amundsen et Bio-ORACLE.",
        affinity=affinity,
        file_loaded=True,
    )

    assert decision.authorized_sources == ("file", "amundsen", "bio_oracle")


def test_explicit_switch_replaces_active_source():
    from tools.source_scope import SourceAffinity, decide_source

    affinity = SourceAffinity(
        active_sources=("ecotaxa",),
        evidence="explicit_name",
        origin_user_text="Explore EcoTaxa",
        updated_at="2026-07-15T12:00:00+00:00",
    )
    decision = decide_source(
        "passe à EcoPart",
        affinity=affinity,
        file_loaded=False,
    )

    assert decision.authorized_sources == ("ecopart",)


def test_exclusion_never_activates_named_source():
    from tools.source_scope import SourceAffinity, decide_source

    affinity = SourceAffinity(
        active_sources=("ecotaxa",),
        evidence="explicit_name",
        origin_user_text="Explore EcoTaxa",
        updated_at="2026-07-15T12:00:00+00:00",
    )
    decision = decide_source(
        "sans EcoTaxa, utilise mon fichier",
        affinity=affinity,
        file_loaded=True,
    )

    assert decision.primary_source == "file"
    assert "ecotaxa" not in decision.authorized_sources


# --- tool / skill classification ---------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("find_ecotaxa_samples_in_region", True),
    ("summarize_ecotaxa_samples", True),
    ("query_ecopart", True),
    ("enrich_ecotaxa_with_ecopart_remote", True),
    ("run_graph", False),
    ("filter_dataframe_by_zone", False),
    ("get_zone_info", False),
    ("enrich_with_amundsen_ctd", False),
    ("run_pandas", False),
])
def test_is_ecotaxa_scoped_tool(name, expected):
    assert is_ecotaxa_scoped_tool(name) is expected


def test_is_ecotaxa_skill_load():
    assert is_ecotaxa_skill_load("load_skill", {"skill_name": "ecotaxa_navigation"})
    assert is_ecotaxa_skill_load("load_skill", {"skill_name": "ecotaxa_query"})
    assert not is_ecotaxa_skill_load("load_skill", {"skill_name": "graph_writer"})
    assert not is_ecotaxa_skill_load("run_graph", {"code": "..."})


# --- turn-level scoping -------------------------------------------------------

def test_file_loaded_no_signal_is_file_scoped():
    msgs = [{"role": "user", "content": "carte des positions des échantillons en mer du Labrador"}]
    assert is_file_scoped_turn(_FakeStore(has_df=True), "t", msgs) is True


def test_file_loaded_with_ecotaxa_signal_is_not_scoped():
    msgs = [{"role": "user", "content": "compare avec les samples EcoTaxa du projet 17498"}]
    assert is_file_scoped_turn(_FakeStore(has_df=True), "t", msgs) is False


def test_file_loaded_with_inherited_ecotaxa_affinity_is_file_scoped(tmp_path):
    import pandas as pd

    from tools.session_store import SessionStore
    from tools.source_scope import SourceAffinity, write_source_affinity

    store = SessionStore(tmp_path)
    store.set("t", pd.DataFrame({"sample_id": [1]}), {"source": "file:data.tsv"})
    write_source_affinity(
        store,
        "t",
        SourceAffinity(
            active_sources=("ecotaxa",),
            evidence="explicit_name",
            origin_user_text="Explore EcoTaxa",
            updated_at="2026-07-15T12:00:00+00:00",
        ),
    )

    msgs = [{"role": "user", "content": "continue avec le projet 17498"}]

    assert is_file_scoped_turn(store, "t", msgs) is True


def test_active_ecotaxa_selection_is_not_a_loaded_file(tmp_path):
    import pandas as pd

    from tools.session_store import SessionStore
    from tools.source_scope import is_file_loaded

    store = SessionStore(tmp_path)
    store.set(
        "t",
        pd.DataFrame({"sample_id": [1]}),
        {"source": "ecotaxa_selection", "selection_name": "selection_baffin"},
    )

    assert is_file_loaded(store, "t") is False


def test_no_file_is_never_scoped():
    msgs = [{"role": "user", "content": "carte des positions des échantillons"}]
    assert is_file_scoped_turn(_FakeStore(has_df=False), "t", msgs) is False


def test_latest_user_text_picks_last_human():
    msgs = [
        {"role": "user", "content": "premier"},
        {"role": "assistant", "content": "réponse"},
        {"role": "user", "content": "dernier"},
    ]
    assert latest_user_text(msgs) == "dernier"


# --- tool filtering -----------------------------------------------------------

def test_filter_removes_ecotaxa_tools_when_file_scoped():
    tools = [_Tool("run_graph"), _Tool("find_ecotaxa_samples_in_region"),
             _Tool("filter_dataframe_by_zone"), _Tool("query_ecopart")]
    kept = {t.name for t in filter_tools_for_scope(tools, file_scoped=True)}
    assert kept == {"run_graph", "filter_dataframe_by_zone"}


def test_filter_keeps_all_when_not_file_scoped():
    tools = [_Tool("run_graph"), _Tool("find_ecotaxa_samples_in_region")]
    assert len(filter_tools_for_scope(tools, file_scoped=False)) == 2
