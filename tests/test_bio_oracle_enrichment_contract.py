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


def test_context_and_tools_document_row_preserving_canonical_enrichment():
    context = Path("CONTEXT.md").read_text(encoding="utf-8").lower()
    tools = Path("TOOLS.md").read_text(encoding="utf-8").lower()

    assert "dataframe" in context
    assert "une ligne" in context
    assert "statistique" in tools
    assert "présélection" in tools
