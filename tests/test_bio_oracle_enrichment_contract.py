from pathlib import Path


def test_canonical_tool_description_requires_guided_explicit_selection():
    from tools.bio_oracle_sources import make_bio_oracle_tools

    enrich = next(
        tool for tool in make_bio_oracle_tools("thread-contract")
        if tool.name == "enrich_with_bio_oracle"
    )
    description = enrich.description.lower()

    assert "proposer" in description
    assert "choix" in description
    assert "statistique" in description
    assert "n'agrège jamais" in description
    assert "temperature" in description
    assert "primary_productivity" in description
    assert "ssp5-8.5" in description
    assert "benthic_mean" in description
    assert "lt_min" in description
    assert "description factuelle" in description


def test_prompt_and_skill_describe_the_same_guided_bio_oracle_contract():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    skill = Path("agents/skills/bio_oracle_query.md").read_text(encoding="utf-8")
    combined = f"{COPEPOD_SYSTEM_PROMPT}\n{skill}".lower()

    assert "propose" in combined
    assert "sélection" in combined or "selection" in combined
    assert "couche" in combined or "vertical layer" in combined
    assert "statistique" in combined or "statistic" in combined
    assert "ne l'applique jamais" in combined or "never apply a preset silently" in combined
    assert "otherwise use canonical" not in combined


def test_system_prompt_exposes_the_selection_sequence_and_option_groups():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()

    assert "propose" in prompt
    assert "wait for explicit" in prompt
    assert "variables" in prompt
    assert "scenarios" in prompt
    assert "vertical layer" in prompt
    assert "statistic" in prompt
    assert "factual descriptions" in prompt
    assert "from the catalog" in prompt
    assert "very low emissions" in prompt
    assert "missing/no_value" in prompt


def test_context_and_tools_document_row_preserving_canonical_enrichment():
    context = Path("CONTEXT.md").read_text(encoding="utf-8").lower()
    tools = Path("TOOLS.md").read_text(encoding="utf-8").lower()

    assert "dataframe" in context
    assert "une ligne" in context
    assert "statistique" in tools
    assert "présélection" in tools
