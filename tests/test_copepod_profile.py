import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.registry import get_profile, registered_types, _registry
from core.session_store import InMemorySessionStore


@pytest.fixture(autouse=True)
def fresh_registry():
    _registry.clear()
    yield
    _registry.clear()


@pytest.fixture(autouse=True)
def inmemory_session_store():
    """Use InMemorySessionStore in all profile tests — no Redis needed.

    Patch the source singleton so that importlib.reload() inside
    import_copepod_profile() re-binds the mocked object, not RedisSessionStore.
    """
    store = InMemorySessionStore()
    with patch("core.session_store.session_store", store):
        yield store


def import_copepod_profile():
    import agents.copepod_profile

    return importlib.reload(agents.copepod_profile)


def test_copepod_profile_registers_under_copepod_agent_type():
    import_copepod_profile()

    assert "copepod" in registered_types()
    assert get_profile("copepod").agent_type == "copepod"


def test_copepod_profile_uses_copepod_system_prompt_and_ignores_global_active_prompt():
    import_copepod_profile()
    from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT

    profile = get_profile("copepod")
    message = profile.get_system_message("\nUSER_ACTIVE_PROMPT")

    assert message.startswith(COPEPOD_SYSTEM_PROMPT)
    assert "USER_ACTIVE_PROMPT" not in message


def test_copepod_profile_uses_safe_runtime_and_copepod_instruction_blocks():
    import_copepod_profile()

    profile = get_profile("copepod")

    assert profile.tool_tags == {
        "core",
        "rag",
        "mcp",
        "copepod_data",
        "copepod_columns",
        "copepod_sources_meta",
        "copepod_rag",
        "copepod_artifacts",
        "copepod_taxonomy",
    }
    assert profile.instruction_blocks == [
        "output_format",
        "cli_reference",
        "copepod_tool_signatures",
        "copepod_mode_plan",
        "copepod_mode_analyse",
        "mcp_tools_block",
        "session_metadata",
    ]


def test_copepod_custom_instructions_use_copepod_blocks_without_sea_level_leakage():
    import_copepod_profile()

    profile = get_profile("copepod")
    instructions = profile.get_custom_instructions(
        host="http://localhost",
        user_id="user-1",
        session_id="session-1",
        static_dir="static",
        upload_dir="uploads",
    )

    assert "## Copepod Plan Mode" in instructions
    assert "## Copepod Analyse Mode" in instructions
    assert "## Copepod Runtime Tools" in instructions
    assert "get_station_info" not in instructions
    assert "get_climate_index" not in instructions
    assert "UHSLC" not in instructions
    assert "tide gauge" not in instructions


def test_copepod_custom_instructions_put_static_blocks_before_session_metadata():
    import_copepod_profile()

    profile = get_profile("copepod")
    instructions = profile.get_custom_instructions(
        host="http://localhost",
        user_id="user-1",
        session_id="session-1",
        static_dir="static",
        upload_dir="uploads",
    )

    assert instructions.index("## Copepod Runtime Tools") < instructions.index("The user_id is user-1")
    assert instructions.index("## Copepod Plan Mode") < instructions.index("The session_id is session-1")


def test_copepod_profile_uses_copepod_instruction_blocks():
    import_copepod_profile()

    profile = get_profile("copepod")

    assert "tool_signatures" not in profile.instruction_blocks
    assert "copepod_tool_signatures" in profile.instruction_blocks
    assert "copepod_mode_plan" in profile.instruction_blocks
    assert "copepod_mode_analyse" in profile.instruction_blocks


def test_copepod_plan_mode_establishes_context_from_loaded_data_before_analysis():
    import_copepod_profile()

    profile = get_profile("copepod")
    instructions = profile.get_custom_instructions(
        host="http://localhost",
        user_id="user-1",
        session_id="session-1",
        static_dir="static",
        upload_dir="uploads",
    )

    assert "establish and validate the scientific and technical context" in instructions
    assert "inspect_file" in instructions
    assert "infer_column_roles" in instructions
    assert "What the user wants to visualise" in instructions
    assert "what each column means" in instructions
    assert "metadata available in the files" in instructions
    assert "Before switching to Analyse Mode" in instructions
    assert "It must not generate the final graph" in instructions


def test_copepod_plan_mode_forces_two_phase_data_then_context_flow():
    import_copepod_profile()

    profile = get_profile("copepod")
    instructions = profile.get_custom_instructions(
        host="http://localhost",
        user_id="user-1",
        session_id="session-1",
        static_dir="static",
        upload_dir="uploads",
    )

    assert "Plan Mode is a two-phase workflow" in instructions
    assert "Phase 1 — Data Understanding" in instructions
    assert "Phase 2 — Context Framing" in instructions
    assert instructions.index("Phase 1 — Data Understanding") < instructions.index("Phase 2 — Context Framing")
    assert "Do not ask for graph context before summarizing the loaded data" in instructions
    assert "PLAN_READY" in instructions
    assert "### Data Understanding" in instructions
    assert "### Graph Context" in instructions


def test_copepod_instructions_require_artifact_tools_before_plan_ready():
    import_copepod_profile()
    profile = get_profile("copepod")

    instructions = profile.get_custom_instructions(
        host="http://localhost",
        user_id="user-1",
        session_id="session-1",
        static_dir="static",
        upload_dir="uploads",
    )

    assert "create_data_understanding_draft" in instructions
    assert "activate_data_understanding" in instructions
    assert "create_graph_context_draft" in instructions
    assert "activate_graph_context" in instructions
    assert "Do not emit `[PLAN_READY]` until `activate_graph_context` has succeeded" in instructions
    assert "Switch to Analyse Mode" in instructions


def test_copepod_plan_mode_uses_strict_numbered_protocol():
    import_copepod_profile()
    profile = get_profile("copepod")

    instructions = profile.get_custom_instructions(
        host="http://localhost",
        user_id="user-1",
        session_id="session-1",
        static_dir="static",
        upload_dir="uploads",
    )

    assert "### Phase 1 Protocol" in instructions
    assert "### Data Understanding Confirmation Protocol" in instructions
    assert "### Phase 2 Protocol" in instructions
    assert "### Graph Context Confirmation Protocol" in instructions
    assert "get_active_data_understanding" in instructions
    assert "get_active_graph_context" in instructions
    assert "Do not infer active artefacts from conversation memory" in instructions


def test_copepod_profile_renders_default_plan_instructions_with_memory_store():
    module = import_copepod_profile()
    profile = module.CopepodProfile(session_store=InMemorySessionStore())

    instructions = profile.get_custom_instructions(
        host="http://localhost",
        user_id="user-1",
        session_id="session-1",
        static_dir="static",
        upload_dir="uploads",
    )

    assert "## Copepod Plan Mode" in instructions
    assert "## Copepod Analyse Mode" in instructions
    assert "Phase 1 — Data Understanding" in instructions
    assert "PLAN_READY" in instructions


def test_copepod_profile_renders_only_analyse_mode_blocks_with_memory_store():
    module = import_copepod_profile()
    store = InMemorySessionStore()
    store.set_session_mode("user-1:session-1:copepod", "analyse")
    profile = module.CopepodProfile(session_store=store)

    instructions = profile.get_custom_instructions(
        host="http://localhost",
        user_id="user-1",
        session_id="session-1",
        static_dir="static",
        upload_dir="uploads",
    )

    assert "## Copepod Analyse Mode" in instructions
    assert "## Copepod Plan Mode" not in instructions
    assert "Phase 1 — Data Understanding" not in instructions
    assert "PLAN_READY" not in instructions


def test_copepod_profile_session_mode_isolated_by_three_segment_key():
    module = import_copepod_profile()
    store = InMemorySessionStore()
    store.set_session_mode("user-1:session-1:copepod", "analyse")
    profile = module.CopepodProfile(session_store=store)

    analyse_instructions = profile.get_custom_instructions(
        host="http://localhost",
        user_id="user-1",
        session_id="session-1",
        static_dir="static",
        upload_dir="uploads",
    )
    plan_instructions = profile.get_custom_instructions(
        host="http://localhost",
        user_id="user-1",
        session_id="session-2",
        static_dir="static",
        upload_dir="uploads",
    )

    assert "## Copepod Analyse Mode" in analyse_instructions
    assert "## Copepod Plan Mode" not in analyse_instructions
    assert "## Copepod Plan Mode" in plan_instructions
    assert "## Copepod Analyse Mode" in plan_instructions


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
