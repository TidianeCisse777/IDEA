"""Deterministic per-turn tool exposure policy (harness step 6)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tools.source_scope import SourceDecision
from tools.session_store import SessionStore
from tools.tool_result import error, success
from tools.turn_context import TurnContext


DEMO_REQUEST = (
    "Pour les déploiements NeoLabs de 2024 en baie de Baffin, compare le filet "
    "et l'UVP par tranche de profondeur en ind./m³."
)


def _source_decision(*sources: str) -> SourceDecision:
    return SourceDecision(
        primary_source=sources[0] if sources else None,
        authorized_sources=tuple(sources),
        explicit_sources=tuple(source for source in sources if source != "file"),
        evidence="explicit_name" if sources else "none",
        needs_clarification=False,
        reason="fixture",
    )


def _turn(*, file_loaded: bool, sources: tuple[str, ...] = (), output_intent: str = "ambiguous") -> TurnContext:
    return TurnContext(
        thread_id="tool-exposure",
        file_loaded=file_loaded,
        active_variable="df_file_demo" if file_loaded else None,
        active_source="file:demo.tsv" if file_loaded else None,
        derived_zone_subsets=(),
        authorized_sources=sources,
        primary_source=sources[0] if sources else None,
        explicit_sources=tuple(source for source in sources if source != "file"),
        capsule="",
        output_intent=output_intent,
    )


def _decision(text: str, *, file_loaded: bool = False, sources: tuple[str, ...] = (), messages=None, max_tools: int = 20, output_intent: str = "ambiguous", store=None):
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure

    history = messages or [HumanMessage(content=text)]
    return decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        _turn(file_loaded=file_loaded, sources=sources, output_intent=output_intent),
        _source_decision(*sources),
        history,
        max_tools=max_tools,
        store=store,
    )


def _successful_skill_messages(text: str, *skills: str):
    messages = [HumanMessage(content=text)]
    for index, skill in enumerate(skills):
        call_id = f"skill-{index}"
        call = {
            "name": "load_skill",
            "args": {"skill_name": skill},
            "id": call_id,
            "type": "tool_call",
        }
        content, artifact = success("loaded")
        messages.extend(
            [
                AIMessage(content="", tool_calls=[call]),
                ToolMessage(content=content, artifact=artifact, tool_call_id=call_id),
            ]
        )
    return messages


def _audited_demo_store(tmp_path) -> SessionStore:
    """Persist one certified audit so graph recovery cannot restart the audit."""
    store = SessionStore(tmp_path / "sessions")
    store.set(
        "tool-exposure:dataset:net-table",
        None,
        {"source": "file:neolabs_2024.tsv", "variable_name": "net-table"},
    )
    store.set(
        "tool-exposure:dataset:audit-table",
        None,
        {
            "source": "net_uvp_match",
            "variable_name": "audit-table",
            "net_variable_name": "net-table",
            "net_dataframe_fingerprint": "neolabs-2024",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    store.set(
        "tool-exposure:selection:certified-selection",
        None,
        {
            "source": "net_uvp_certified_selection",
            "selection_name": "certified-selection",
            "audit_variable": "audit-table",
            "net_variable_name": "net-table",
            "net_dataframe_fingerprint": "neolabs-2024",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    return store


def _audited_history_with_retryable_graph_error():
    """Model history for one failed render after the graph workflow succeeded."""
    messages = _successful_skill_messages(DEMO_REQUEST, "graph_planner", "graph_writer")
    call_id = "failed-graph"
    failed_call = {
        "name": "run_graph",
        "args": {"code": "raise ValueError('colonne de profondeur absente')"},
        "id": call_id,
        "type": "tool_call",
    }
    content, artifact = error(
        "Graphique non généré : colonne de profondeur absente.",
        retryable=True,
    )
    messages.extend(
        [
            AIMessage(content="", tool_calls=[failed_call]),
            ToolMessage(content=content, artifact=artifact, tool_call_id=call_id),
        ]
    )
    return messages


def test_no_state_exposes_permanent_core_and_geographic_capabilities():
    decision = _decision("Bonjour")

    assert decision.tool_names[:4] == (
        "load_file",
        "load_skill",
        "query_copepod_knowledge_base",
        "run_pandas",
    )
    assert set(decision.tool_names[4:]) == {
        "filter_dataframe_by_zone",
        "get_zone_info",
    }
    assert decision.active_groups == ("core", "geography")
    assert decision.policy_overflow is False


def test_neolabs_preparation_is_exposed_only_for_an_explicit_neolabs_request():
    ordinary = _decision("Bonjour")
    neolabs = _decision("Prépare les deux fichiers NeoLabs pour l'analyse")

    assert "prepare_neolabs_analysis" not in ordinary.tool_names
    assert "prepare_neolabs_analysis" in neolabs.tool_names


@pytest.mark.parametrize(
    "text",
    [
        "Prépare mon jeu de données Neo Lab",
        "Prepare my NeoLab dataset",
    ],
)
def test_neolabs_bilingual_variants_expose_preparation(text):
    """Common NeoLab spellings must keep the local preparation route visible."""
    decision = _decision(text)

    assert "prepare_neolabs_analysis" in decision.tool_names


@pytest.mark.parametrize(
    "text",
    [
        "Baie d’Hudson",
        "Fais la même chose pour le secteur scientifique alpha",
        "Bonjour",
    ],
)
def test_geographic_capabilities_do_not_depend_on_lexical_detection(text):
    decision = _decision(text)

    assert "get_zone_info" in decision.tool_names
    assert "filter_dataframe_by_zone" in decision.tool_names
    assert "geography" in decision.active_groups


def test_run_pandas_is_permanent_sandbox_without_loaded_file():
    decision = _decision("Bonjour")

    assert "run_pandas" in decision.tool_names
    assert "run_graph" not in decision.tool_names


def test_join_net_uvp_enriched_is_exposed_for_file_analysis():
    decision = _decision(
        "Prépare la table filet et UVP enrichie EcoPart déjà disponible.",
        file_loaded=True,
        sources=("file",),
    )

    assert "file_analysis" in decision.active_groups
    assert "join_net_uvp_enriched" in decision.tool_names


def test_ecopart_preflight_exposes_remote_enrichment_for_active_selection():
    """A remote EcoPart preflight must not be mistaken for local-only analysis."""
    decision = _decision(
        "Lance le préflight canonique EcoPart sur le projet 14844 pour "
        "vérifier l’accès distant, les volumes et les classes de profondeur.",
        file_loaded=True,
        sources=("file", "ecopart"),
    )

    assert "enrichment_ecopart" in decision.active_groups
    assert "enrich_ecotaxa_with_ecopart_remote" in decision.tool_names


def test_external_search_is_not_suppressed_by_environmental_enrichment_wording():
    """A new EcoTaxa query must precede enrichment of the export it creates."""
    decision = _decision(
        "Cherche dans EcoTaxa tous les casts disponibles en mer de Beaufort, "
        "exporte-les et enrichis-les avec les données environnementales.",
        file_loaded=True,
        sources=("ecotaxa", "amundsen", "file"),
    )

    assert "ecotaxa_discovery" in decision.active_groups
    assert "ecotaxa_export" in decision.active_groups
    assert "query_ecotaxa_cache" in decision.tool_names
    assert "query_ecotaxa" in decision.tool_names


def test_scoped_net_uvp_audit_is_exposed_in_strict_stages(tmp_path):
    """Le chargement, le sous-ensemble et l'audit ne doivent jamais coexister.

    Sinon le modèle les lance en parallèle et l'audit lit le fichier complet.
    """
    text = (
        "Charge NeoLabs, prends 2024 en Baie de Baffin puis audite avec les "
        "profils UVP et montre une carte des paires certifiées."
    )
    store = SessionStore(tmp_path / "sessions")
    first = _decision(text, file_loaded=False, sources=("file",), store=store)
    assert first.tool_names == ("load_file",)

    store.set(
        "tool-exposure:dataset:net-table",
        None,
        {"source": "file:net.tsv", "variable_name": "net-table"},
    )
    prepared = _decision(text, file_loaded=True, sources=("file",), store=store)
    assert set(prepared.tool_names) == {
        "prepare_net_uvp_audit_subsets",
        "run_pandas",
    }

    store.set(
        "tool-exposure:dataset:audit-input",
        None,
        {
            "source": "net_uvp_audit_subset",
            "variable_name": "audit-input",
            "net_uvp_audit_input": True,
            "parent_variable": "net-table",
        },
    )
    audited = _decision(text, file_loaded=True, sources=("file",), store=store)
    assert set(audited.tool_names) == {
        "find_uvp_matches_for_net_table",
        "run_pandas",
    }

    store.set(
        "tool-exposure:dataset:audit-table",
        None,
        {
            "source": "net_uvp_match",
            "variable_name": "audit-table",
            "net_variable_name": "audit-input",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    store.set(
        "tool-exposure:selection:certified-selection",
        None,
        {
            "source": "net_uvp_certified_selection",
            "selection_name": "certified-selection",
            "audit_variable": "audit-table",
            "net_variable_name": "audit-input",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    completed = _decision(
        text,
        file_loaded=True,
        sources=("file",),
        output_intent="visual",
        store=store,
    )
    assert "run_graph" in completed.tool_names
    assert "run_pandas" in completed.tool_names
    assert "prepare_net_uvp_audit_subsets" not in completed.tool_names
    assert "find_uvp_matches_for_net_table" not in completed.tool_names


def test_scoped_net_uvp_audit_uses_persisted_completion_for_visual_follow_up(tmp_path):
    """A later request must not repeat completed Net↔UVP protocol steps."""
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure

    store = SessionStore(tmp_path / "sessions")
    store.set(
        "tool-exposure:dataset:net-table",
        None,
        {"source": "file:net.tsv", "variable_name": "net-table"},
    )
    store.set(
        "tool-exposure:dataset:audit-table",
        None,
        {
            "source": "net_uvp_match",
            "variable_name": "audit-table",
            "net_variable_name": "net-table",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    store.set(
        "tool-exposure:selection:certified-selection",
        None,
        {
            "source": "net_uvp_certified_selection",
            "selection_name": "certified-selection",
            "audit_variable": "audit-table",
            "net_variable_name": "net-table",
            "ctd_verification": "verified",
            "exploratory": False,
        },
    )
    text = "Montre une carte des correspondances filet UVP de 2024 en Baie de Baffin."

    decision = decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        _turn(file_loaded=True, sources=("file",), output_intent="visual"),
        _source_decision("file"),
        [HumanMessage(content=text)],
        store=store,
    )

    assert "run_graph" in decision.tool_names
    assert "run_pandas" in decision.tool_names
    assert "prepare_net_uvp_audit_subsets" not in decision.tool_names
    assert "find_uvp_matches_for_net_table" not in decision.tool_names


def test_net_uvp_demo_recovers_from_a_failed_local_graph_call(tmp_path):
    """A retryable render error preserves both the graph and audited route."""
    history = _audited_history_with_retryable_graph_error()

    decision = _decision(
        DEMO_REQUEST,
        file_loaded=True,
        sources=("file", "ecotaxa"),
        messages=history,
        store=_audited_demo_store(tmp_path),
    )

    assert "run_graph" in decision.tool_names
    assert "find_uvp_matches_for_net_table" not in decision.tool_names


def test_amundsen_correspondence_request_does_not_trigger_net_uvp_audit():
    text = (
        "À partir des prélèvements NeoLabs calculables de 2016, cherche les "
        "correspondances CTD Amundsen par position et par date."
    )

    decision = _decision(
        text,
        file_loaded=True,
        sources=("amundsen", "file"),
    )

    assert "enrich_with_amundsen_ctd" not in decision.tool_names
    assert not {
        "prepare_net_uvp_audit_subsets",
        "find_uvp_matches_for_net_table",
        "join_net_uvp_enriched",
    }.intersection(decision.tool_names)


def test_explicit_visual_intent_exposes_graph_workflow_before_graph_skills():
    # The fixture carries the semantic decision that the runtime computes
    # before the first model call; no graph skill has been loaded yet.
    visual_context = _turn(
        file_loaded=True,
        sources=("file",),
        output_intent="visual",
    )
    indirect_request = (
        "Montre-moi où sont les stations et comment elles se répartissent au fil des années."
    )
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure

    decision = decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        visual_context,
        _source_decision("file"),
        [HumanMessage(content=indirect_request)],
    )

    assert "run_graph" in decision.tool_names
    assert "visualization" in decision.active_groups
    assert "semantic visual output requested" in decision.reasons


def test_already_enriched_table_keeps_local_analysis_and_graph_tools_available():
    """A provenance mention is not a request to enrich the table again."""
    visual_context = _turn(
        file_loaded=True,
        sources=("file", "bio_oracle"),
        output_intent="visual",
    )
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure

    decision = decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        visual_context,
        _source_decision("file", "bio_oracle"),
        [
            HumanMessage(
                content=(
                    "À partir de l’export 2024 enrichi avec Bio-ORACLE, "
                    "affiche un profil vertical pertinent."
                )
            )
        ],
    )

    assert "run_pandas" in decision.tool_names
    assert "run_graph" in decision.tool_names


def test_graph_and_deliverable_execution_unlock_from_successful_current_turn_skills():
    graph_messages = _successful_skill_messages(
        "Fais une carte", "graph_planner", "graph_writer"
    )
    graph = _decision(
        "Fais une carte",
        file_loaded=True,
        sources=("file",),
        messages=graph_messages,
    )
    report_messages = _successful_skill_messages(
        "Crée un rapport", "deliverable_writer"
    )
    report = _decision(
        "Crée un rapport",
        file_loaded=True,
        sources=("file",),
        messages=report_messages,
    )

    assert "run_graph" in graph.tool_names
    assert "export_deliverable" in report.tool_names


def test_graph_writer_is_not_reexposed_after_it_succeeds_in_the_same_turn():
    messages = _successful_skill_messages(
        "Affiche une carte", "graph_planner", "graph_writer"
    )

    decision = _decision(
        "Affiche une carte",
        file_loaded=True,
        sources=("file",),
        messages=messages,
        output_intent="visual",
    )

    assert "run_graph" in decision.tool_names
    assert "load_skill" not in decision.tool_names


@pytest.mark.parametrize(
    ("source", "text", "expected"),
    [
        ("ecopart", "Enrichis mon fichier avec EcoPart", "enrich_ecotaxa_with_ecopart_remote"),
        ("amundsen", "Enrichis mon fichier avec la température Amundsen CTD", "enrich_with_amundsen_ctd"),
        ("bio_oracle", "Enrichis mon fichier avec Bio-ORACLE", "enrich_with_bio_oracle"),
        ("ogsl", "Enrichis mon fichier avec OGSL", "enrich_with_ogsl"),
    ],
)
def test_explicit_enrichment_exposes_one_canonical_source_tool(source, text, expected):
    decision = _decision(text, file_loaded=True, sources=("file", source))

    source_tools = [
        name
        for name in decision.tool_names
        if name == expected or source in name or (source == "amundsen" and "amundsen" in name)
    ]
    assert expected in decision.tool_names
    assert source_tools == [expected]


@pytest.mark.parametrize(
    ("source", "text", "expected"),
    [
        ("ecotaxa", "Montre un aperçu du projet EcoTaxa 17498", "preview_ecotaxa_project"),
        ("ecotaxa", "Preview EcoTaxa project 17498", "preview_ecotaxa_project"),
        ("ecopart", "Prévisualise le sample EcoPart 14844", "preview_ecopart_sample"),
        ("ecopart", "Show me a preview of EcoPart sample 14844", "preview_ecopart_sample"),
    ],
)
def test_explicit_source_preview_exposes_only_the_lightweight_preview(source, text, expected):
    """French and English preview wording must expose the read-only preview."""
    decision = _decision(text, sources=(source,))

    assert expected in decision.tool_names


@pytest.mark.parametrize(
    "text",
    [
        "Récupère les annotations validées EcoTaxa dans un fichier",
        "Extrais les données EcoTaxa sélectionnées",
        "Fetch the selected EcoTaxa records",
        "Retrieve the validated EcoTaxa data as CSV",
        "Save selected EcoTaxa data as CSV",
    ],
)
def test_french_and_english_export_synonyms_expose_the_canonical_export(text):
    """Explicit retrieval wording must expose the confirmation-gated export."""
    decision = _decision(text, sources=("ecotaxa",))

    assert "query_ecotaxa" in decision.tool_names


def test_negated_retrieval_does_not_expose_ecotaxa_export():
    """A request to browse without retrieving data remains non-exporting."""
    decision = _decision(
        "Montre les objets EcoTaxa sans récupérer les données",
        sources=("ecotaxa",),
    )

    assert "query_ecotaxa" not in decision.tool_names


@pytest.mark.parametrize(
    ("source", "text", "expected"),
    [
        ("ecotaxa", "Show EcoTaxa project 17498 details", "preview_ecotaxa_project"),
        ("ecotaxa", "Inspecte le projet EcoTaxa 17498", "preview_ecotaxa_project"),
        ("ecopart", "Show EcoPart sample 14844 details", "preview_ecopart_sample"),
        ("ecopart", "Examine le sample EcoPart 14844", "preview_ecopart_sample"),
    ],
)
def test_bilingual_preview_synonyms_expose_only_lightweight_preview(source, text, expected):
    """Detail and inspection wording stays on the lightweight preview route."""
    decision = _decision(text, sources=(source,))

    assert expected in decision.tool_names


@pytest.mark.parametrize(
    ("text", "expected_group", "expected_tool"),
    [
        ("Check the EcoTaxa field structure", "ecotaxa_schema", "inspect_ecotaxa_project_schema"),
        ("Quels organismes sont présents dans EcoTaxa ?", "ecotaxa_taxonomy", "count_ecotaxa_taxa"),
        ("Validate EcoTaxa coverage", "ecotaxa_audit", "query_ecotaxa_cache"),
        ("Where are the EcoTaxa samples?", "ecotaxa_geo_time", "summarize_ecotaxa_profiles_for_map"),
    ],
)
def test_bilingual_ecotaxa_intent_synonyms_select_the_expected_group(text, expected_group, expected_tool):
    """The named source makes expanded intent wording safe and deterministic."""
    decision = _decision(text, sources=("ecotaxa",))

    assert expected_group in decision.active_groups
    assert expected_tool in decision.tool_names


@pytest.mark.parametrize("text", ["go", "vas-y", "proceed", "lance l'export"])
def test_bilingual_confirmation_synonyms_keep_pending_export_reachable(text):
    """Explicit confirmation variants must continue a pending, gated export."""
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure

    turn = replace(
        _turn(file_loaded=False, sources=("ecotaxa",)),
        pending_ecotaxa_export=True,
    )
    decision = decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        turn,
        _source_decision("ecotaxa"),
        [HumanMessage(content=text)],
    )

    assert "query_ecotaxa" in decision.tool_names


@pytest.mark.parametrize(
    ("source", "text", "expected"),
    [
        ("ecopart", "Add EcoPart sampled volumes to my loaded table", "enrich_ecotaxa_with_ecopart_remote"),
        ("bio_oracle", "Append Bio-ORACLE data to this dataset", "enrich_with_bio_oracle"),
        ("ogsl", "Merge OGSL measurements into the current file", "enrich_with_ogsl"),
    ],
)
def test_english_enrichment_synonyms_expose_the_canonical_tool(source, text, expected):
    """Common English verbs must activate the same source enrichment route."""
    decision = _decision(text, file_loaded=True, sources=("file", source))

    assert expected in decision.tool_names


@pytest.mark.parametrize(
    "text",
    [
        "Avec Amundsen CTD, ajoute la température et la salinité à mon fichier",
        "Complète ce fichier avec l'oxygène et les nitrates Amundsen",
        "Enrichis cette table avec toutes les variables CTD Amundsen",
    ],
)
def test_named_amundsen_environment_request_exposes_canonical_enrichment(text):
    """CTD variables with a named Amundsen source are an enrichment request."""
    decision = _decision(text, file_loaded=True, sources=("file", "amundsen"))

    assert "enrich_with_amundsen_ctd" in decision.tool_names
    assert "enrichment_amundsen" in decision.active_groups


@pytest.mark.parametrize(
    "text",
    [
        "Enrichis cette table avec les données CTD Amundsen",
        "Donne les données environnementales Amundsen CTD pour le tableau chargé",
        "Donne-moi les données Amundsen CTD associées à ce fichier",
        "CTD",
        "Amundsen",
        "Donne les données environnementales",
    ],
)
def test_broad_amundsen_request_exposes_direct_enrichment(text):
    decision = _decision(text, file_loaded=True, sources=("file", "amundsen"))

    assert "enrich_with_amundsen_ctd" in decision.tool_names
    assert "enrichment_amundsen" in decision.active_groups


def test_environmental_vertical_profile_followup_exposes_full_profile_retrieval():
    """An enriched Amundsen table must retain a route to full casts on a visual follow-up."""
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure

    source_decision = SourceDecision(
        primary_source="file",
        authorized_sources=("file", "amundsen"),
        explicit_sources=(),
        evidence="session_affinity",
        needs_clarification=False,
        reason="fixture",
    )
    turn = TurnContext(
        thread_id="tool-exposure",
        file_loaded=True,
        active_variable="df_derived_top3_station_ctd_profiles",
        active_source="analysis:explicit-derived",
        derived_zone_subsets=(),
        authorized_sources=("file", "amundsen"),
        primary_source="file",
        explicit_sources=(),
        capsule="",
        output_intent="visual",
    )
    decision = decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        turn,
        source_decision,
        [HumanMessage(content="Trace les profils verticaux complets de toutes les variables CTD Amundsen pour ces stations")],
    )

    assert "query_amundsen_profiles_for_table" in decision.tool_names
    assert "run_graph" in decision.tool_names
    assert "enrichment_amundsen" in decision.active_groups


def test_explicit_enrichment_source_wins_over_stale_authorized_sources():
    from tools.tool_catalog import TOOL_POLICIES
    from tools.tool_exposure import decide_tool_exposure

    source_decision = SourceDecision(
        primary_source="file",
        authorized_sources=("file", "ecotaxa", "ecopart", "amundsen"),
        explicit_sources=("amundsen",),
        evidence="explicit_name",
        needs_clarification=False,
        reason="stale affinity fixture",
    )
    decision = decide_tool_exposure(
        tuple(TOOL_POLICIES),
        TOOL_POLICIES,
        _turn(
            file_loaded=True,
            sources=source_decision.authorized_sources,
        ),
        source_decision,
        [HumanMessage(content="Enrichis le sample avec Amundsen.")],
    )

    assert decision.policy_overflow is False
    assert "enrich_with_amundsen_ctd" in decision.tool_names
    assert "enrich_ecotaxa_with_ecopart_remote" not in decision.tool_names
    assert not any(group.startswith("ecotaxa_") for group in decision.active_groups)
    # file_analysis actif (fichier chargé) → analyse locale et découpage
    # géographique. Les outils filet↔UVP restent cachés sans demande explicite.
    assert "split_dataframe_by_zone" in decision.tool_names
    assert not {
        "prepare_net_uvp_audit_subsets",
        "find_uvp_matches_for_net_table",
        "join_net_uvp_enriched",
    }.intersection(decision.tool_names)
    # The named enrichment routes directly to the canonical Amundsen tool;
    # stale external sources remain hidden.
    assert "enrichment_amundsen" in decision.active_groups


@pytest.mark.parametrize(
    ("source", "text", "canonical"),
    [
        ("ecopart", "Utilise EcoPart", "enrich_ecotaxa_with_ecopart_remote"),
        ("bio_oracle", "Utilise Bio-ORACLE", "enrich_with_bio_oracle"),
        ("ogsl", "Utilise OGSL", "enrich_with_ogsl"),
    ],
)
def test_source_name_without_enrichment_keeps_source_tools_hidden(source, text, canonical):
    decision = _decision(text, file_loaded=True, sources=("file", source))

    assert canonical not in decision.tool_names


def test_enrichment_without_loaded_file_keeps_canonical_tool_hidden():
    decision = _decision(
        "Enrichis avec Bio-ORACLE",
        file_loaded=False,
        sources=("bio_oracle",),
    )

    assert "enrich_with_bio_oracle" not in decision.tool_names


@pytest.mark.parametrize(
    ("text", "expected_group", "expected_tool"),
    [
        ("Explore EcoTaxa", "ecotaxa_discovery", "query_ecotaxa_cache"),
        ("Liste les samples EcoTaxa du projet", "ecotaxa_samples", "query_ecotaxa_cache"),
        ("Résous la station RA76 dans EcoTaxa", "ecotaxa_discovery", "query_ecotaxa_cache"),
        ("Trouve les samples EcoTaxa au Labrador en 2020", "ecotaxa_geo_time", "query_ecotaxa_cache"),
        ("Compte les taxons EcoTaxa", "ecotaxa_taxonomy", "count_ecotaxa_taxa"),
        ("Inspecte le schéma du projet EcoTaxa", "ecotaxa_schema", "inspect_ecotaxa_project_schema"),
        ("Audite la couverture EcoTaxa", "ecotaxa_audit", "query_ecotaxa_cache"),
        ("Résume maintenant le projet 17498", "ecotaxa_audit", "query_ecotaxa_cache"),
        ("Exporte les données EcoTaxa", "ecotaxa_export", "query_ecotaxa"),
    ],
)
def test_ecotaxa_selects_only_the_requested_subtoolset(text, expected_group, expected_tool):
    decision = _decision(text, sources=("ecotaxa",))

    assert expected_group in decision.active_groups
    assert expected_tool in decision.tool_names
    assert len(decision.tool_names) <= 20


def test_object_pagination_is_not_exposed_to_the_agent():
    decision = _decision(
        "Montre les objets du sample EcoTaxa 14853000001",
        sources=("ecotaxa",),
    )

    assert "ecotaxa_objects" not in decision.active_groups
    assert "list_ecotaxa_sample_objects" not in decision.tool_names


def test_cache_replaced_navigation_wrappers_are_not_exposed_to_the_agent():
    decision = _decision(
        "Explore les projets, campagnes, samples et taxons EcoTaxa",
        sources=("ecotaxa",),
    )

    hidden = {
        "list_ecotaxa_projects",
        "find_ecotaxa_projects",
        "list_ecotaxa_campaigns",
        "preview_ecotaxa_project",
        "resolve_ecotaxa_sample",
        "get_ecotaxa_sample",
        "summarize_ecotaxa_sample",
        "summarize_ecotaxa_samples",
        "list_ecotaxa_sample_objects",
        "get_ecotaxa_object",
        "describe_ecotaxa_project_coverage",
        "find_ecotaxa_observations",
    }

    assert hidden.isdisjoint(decision.tool_names)
    assert "query_ecotaxa_cache" in decision.tool_names


def test_ecotaxa_does_not_always_include_geo_time_for_a_project_audit():
    decision = _decision("Audite le projet EcoTaxa", sources=("ecotaxa",))

    assert "ecotaxa_geo_time" not in decision.active_groups
    assert "ecotaxa_audit" in decision.active_groups
    assert len(decision.tool_names) <= 20


def test_ecotaxa_exploration_keeps_discovery_and_multiple_intents():
    decision = _decision(
        "Montre le projet 1165 et ses samples de la campagne X",
        sources=("ecotaxa",),
    )

    assert "ecotaxa_discovery" in decision.active_groups
    assert "ecotaxa_samples" in decision.active_groups
    assert "ecotaxa_geo_time" not in decision.active_groups
    assert "query_ecotaxa_cache" in decision.tool_names
    assert "preview_ecotaxa_project" not in decision.tool_names
    assert "list_ecotaxa_campaigns" not in decision.tool_names
    assert "get_ecotaxa_sample" not in decision.tool_names


def test_ecotaxa_does_not_expose_geo_time_for_non_geographic_exploration():
    decision = _decision("Le cache EcoTaxa est-il à jour ?", sources=("ecotaxa",))

    assert "ecotaxa_discovery" in decision.active_groups
    assert "ecotaxa_geo_time" not in decision.active_groups
    assert "query_ecotaxa_cache" in decision.tool_names


def test_visual_overflow_keeps_graph_and_ecotaxa_discovery():
    decision = _decision(
        "Affiche les samples EcoTaxa de la Baie de Baffin sur une carte",
        sources=("ecotaxa",),
        output_intent="visual",
    )

    assert "run_graph" in decision.tool_names
    assert "query_ecotaxa_cache" in decision.tool_names
    assert "list_ecotaxa_campaigns" not in decision.tool_names


def test_compact_ecotaxa_exposure_keeps_central_cache_query_without_overflow():
    decision = _decision(
        "Explore les samples EcoTaxa par projet, station, date et instrument",
        sources=("ecotaxa",),
    )

    assert decision.policy_overflow is False
    assert "query_ecotaxa_cache" in decision.tool_names


def test_global_region_ranking_keeps_cache_sql_in_compact_exposure():
    decision = _decision(
        "Dans tout le cache EcoTaxa, classe les zones et écorégions par nombre de samples",
        sources=("ecotaxa",),
    )

    assert decision.policy_overflow is False
    assert "query_ecotaxa_cache" in decision.tool_names
    assert "rank_ecotaxa_samples_by_region" not in decision.tool_names


def test_negated_export_does_not_expose_ecotaxa_export_tools():
    decision = _decision(
        "Montre le projet 1165 et ses samples, ne fais aucun export",
        sources=("ecotaxa",),
    )

    assert "ecotaxa_export" not in decision.active_groups
    assert "query_ecotaxa" not in decision.tool_names


def test_export_planning_without_download_exposes_ecotaxa_dry_run():
    decision = _decision(
        "Prépare l'export EcoTaxa de tous les objets des samples 14859000001 "
        "et 17498000048, sans rien télécharger.",
        sources=("ecotaxa",),
    )

    assert "ecotaxa_export" in decision.active_groups
    assert "export_ecotaxa_samples" in decision.tool_names
    assert "list_ecotaxa_sample_objects" not in decision.tool_names


def test_ecotaxa_is_never_enabled_by_a_bare_identifier():
    decision = _decision("Résume le projet 17498")

    assert not any(name.startswith(("find_ecotaxa", "query_ecotaxa", "summarize_ecotaxa")) for name in decision.tool_names)


def test_hidden_legacy_tools_are_never_exposed():
    from tools.tool_catalog import TOOL_POLICIES

    decision = _decision(
        "Enrichis mon fichier avec Bio-ORACLE",
        file_loaded=True,
        sources=("file", "bio_oracle"),
    )
    hidden = {
        name
        for name, policy in TOOL_POLICIES.items()
        if policy.exposure_group == "hidden_legacy"
    }

    assert hidden.isdisjoint(decision.tool_names)


def test_overflow_falls_back_to_the_core_when_discovery_does_not_fit():
    decision = _decision("Explore EcoTaxa", sources=("ecotaxa",), max_tools=4)

    assert decision.policy_overflow is True
    assert decision.tool_names == (
        "load_file",
        "load_skill",
        "query_copepod_knowledge_base",
        "run_pandas",
    )
    assert len(decision.tool_names) <= 4
