import importlib
from pathlib import Path

import pytest

from agents.registry import get_profile, registered_types, _registry


@pytest.fixture(autouse=True)
def fresh_registry():
    _registry.clear()
    yield
    _registry.clear()


def import_copepod_profile():
    import agents.copepod_profile

    return importlib.reload(agents.copepod_profile)


def test_copepod_profile_registers_under_copepod_agent_type():
    import_copepod_profile()

    assert "copepod" in registered_types()
    assert get_profile("copepod").agent_type == "copepod"


def test_copepod_profile_uses_copepod_system_prompt_and_appends_active_prompt():
    import_copepod_profile()
    from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT

    profile = get_profile("copepod")
    message = profile.get_system_message("\nUSER_ACTIVE_PROMPT")

    assert message.startswith(COPEPOD_SYSTEM_PROMPT)
    assert message.endswith("USER_ACTIVE_PROMPT")


def test_copepod_profile_keeps_generic_instruction_blocks_for_first_increment():
    import_copepod_profile()

    profile = get_profile("copepod")

    assert profile.tool_tags == {"core", "rag", "mcp"}
    assert profile.instruction_blocks == [
        "session_metadata",
        "output_format",
        "cli_reference",
        "tool_signatures",
        "mcp_tools_block",
    ]


def test_copepod_system_prompt_contains_domain_invariants():
    from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT

    assert "Copepod Graphing Assistant" in prompt
    assert "EcoTaxa" in prompt
    assert "EcoPart" in prompt
    assert "Amundsen CTD" in prompt
    assert "lab data" in prompt
    assert "OGSL" in prompt
    assert "Bio-ORACLE" in prompt
    assert "OBIS is not an authorized source" in prompt
    assert "Do not provide scientific or biological interpretation" in prompt
    assert "Never modify raw input files" in prompt
    assert "Never expose credentials" in prompt
    assert "execute" in prompt
    assert "Python or R" in prompt


def test_copepod_system_prompt_uses_sea_like_structure():
    from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT

    headings = [
        "## Copepod Role & Scope",
        "## Copepod Execution Conventions",
        "## Copepod Data Rules & Defaults",
        "## Copepod Source Rules",
        "## Copepod RAG Rules",
        "## Copepod Graphing Rules",
        "## Copepod Taxonomy Validation",
        "## Copepod Error Handling & Validation",
    ]

    for heading in headings:
        assert heading in COPEPOD_SYSTEM_PROMPT


def test_copepod_system_prompt_covers_traceability_gap_invariants():
    from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT

    assert "reliable, exploratory, or impossible" in prompt
    assert "present the graph plan or method before execution" in prompt
    assert "Do not run massive downloads" in prompt
    assert "Use a sober, clinical, non-anthropomorphic style" in prompt
    assert "Provenance must be attached" in prompt
    assert "verify that key statements match the source data" in prompt
    assert "A local absence is not evidence of biological absence" in prompt


def test_copepod_system_prompt_removes_sea_level_domain_identity():
    from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT

    forbidden = [
        "tide gauge",
        "UHSLC",
        "Station Explorer Assistant",
        "Station Zero",
        "datum conversion",
        "get_station_info",
        "get_climate_index",
    ]

    for term in forbidden:
        assert term not in COPEPOD_SYSTEM_PROMPT


def test_app_bootstrap_imports_copepod_profile():
    app_source = Path("app.py").read_text(encoding="utf-8")

    assert "import agents.copepod_profile" in app_source
