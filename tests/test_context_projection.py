"""Post-implementation checks for the structured context projection module."""

from core.context_projection import ContextBlock, project_context_blocks


def _word_tokens(text: str) -> int:
    return len(text.split())


def test_projection_drops_low_priority_optional_blocks_before_required_facts():
    projection = project_context_blocks(
        [
            ContextBlock("task", "task facts stay", priority=100, required=True),
            ContextBlock("notes", "optional notes are removable", priority=10),
            ContextBlock("dataframes", "dataframe facts remain", priority=90),
        ],
        max_tokens=7,
        count_tokens=_word_tokens,
    )

    ledger = {item.name: item for item in projection.blocks}
    assert projection.projected_tokens <= 7
    assert ledger["task"].status == "kept"
    assert ledger["notes"].status == "dropped"
    assert ledger["dataframes"].status == "kept"


def test_projection_truncates_required_content_when_it_alone_exceeds_budget():
    projection = project_context_blocks(
        [ContextBlock(
            "recovery",
            "one two three four five six seven eight nine ten",
            priority=110,
            required=True,
        )],
        max_tokens=5,
        count_tokens=_word_tokens,
    )

    assert projection.projected_tokens <= 5
    assert projection.blocks[0].status == "truncated"
    assert projection.blocks[0].text.startswith("one")
