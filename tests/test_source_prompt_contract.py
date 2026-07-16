"""The source gateway prose is rendered from the executable policy."""

from __future__ import annotations


def test_system_prompt_embeds_generated_source_gateway_once():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    from tools.source_scope import SOURCE_SELECTION_GATEWAY

    assert COPEPOD_SYSTEM_PROMPT.count("## Source Selection Gateway") == 1
    assert SOURCE_SELECTION_GATEWAY in COPEPOD_SYSTEM_PROMPT


def test_generated_gateway_documents_persistent_affinity_and_bare_ids():
    from tools.source_scope import render_source_selection_gateway

    gateway = render_source_selection_gateway()

    assert "A project number alone is not an EcoTaxa signal" in gateway
    assert "remains active on following turns" in gateway
    assert "newly loaded file becomes the active source" in gateway
    assert "name another source" in gateway


def test_gateway_names_every_selectable_external_source():
    from tools.source_scope import render_source_selection_gateway

    gateway = render_source_selection_gateway()

    for label in ("EcoTaxa", "EcoPart", "Amundsen CTD", "Bio-ORACLE", "OGSL", "SQL"):
        assert label in gateway
