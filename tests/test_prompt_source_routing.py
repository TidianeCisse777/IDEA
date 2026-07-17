"""Static contracts for source routing and tool-result truth in the prompt."""

from pathlib import Path

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT


def test_source_gateway_precedes_source_specific_routing():
    gateway = COPEPOD_SYSTEM_PROMPT.index("## Source Selection Gateway")
    ecotaxa = COPEPOD_SYSTEM_PROMPT.index("EcoTaxa")
    assert gateway < ecotaxa


def test_generic_requests_default_to_loaded_file():
    assert "A loaded file is the default source" in COPEPOD_SYSTEM_PROMPT
    assert "Generic words are never external-source signals" in COPEPOD_SYSTEM_PROMPT


def test_external_sources_require_first_explicit_selection_then_persist():
    for source in (
        "EcoTaxa",
        "EcoPart",
        "Amundsen CTD",
        "Bio-ORACLE",
        "OGSL",
        "SQL",
    ):
        assert source in COPEPOD_SYSTEM_PROMPT
    assert "On first use, an external source must be named explicitly" in COPEPOD_SYSTEM_PROMPT
    assert "remains active on following turns" in COPEPOD_SYSTEM_PROMPT


def test_project_number_alone_is_not_ecotaxa():
    assert "A project number alone is not an EcoTaxa signal" in COPEPOD_SYSTEM_PROMPT


def test_explicit_lock_requires_explicit_release():
    assert (
        "persists across turns until the user explicitly releases it"
        in COPEPOD_SYSTEM_PROMPT
    )


def test_failed_tools_cannot_be_reported_as_success():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "## Tool Result Truth" in prompt
    assert "Error, blocked, exception, or an empty result is not success" in prompt
    assert "Never announce an image, file, or URL unless" in prompt


def test_empty_results_stop_before_graphing():
    assert (
        "When a filter returns zero rows, stop before graph planning"
        in COPEPOD_SYSTEM_PROMPT
    )


def test_graph_skills_forbid_invented_artifacts_and_empty_renders():
    for filename in ("graph_planner.md", "graph_writer.md"):
        text = (Path("agents/skills") / filename).read_text()
        assert "Never invent or reuse an artifact URL" in text
        assert "zero rows" in text


def test_graph_writer_has_exact_station_position_mapping():
    text = Path("agents/skills/graph_writer.md").read_text()
    assert '"position": {"variable": "longitude_latitude"' in text
    assert "A position mapping with `x` / `y` keys is invalid" in text


def test_source_procedures_are_not_duplicated_in_system_prompt():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "## EcoTaxa\n" not in prompt
    assert "find_ecotaxa_samples_in_region" not in prompt
    assert "summarize_ecotaxa_projects" not in prompt
    assert prompt.count('load_skill("ecotaxa_navigation")') <= 2


def test_system_prompt_is_small_enough_for_routing_rules_to_stay_salient():
    assert len(COPEPOD_SYSTEM_PROMPT) < 45_000
