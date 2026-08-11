"""Contracts for the non-Tool-Search provider fallback."""

from tools.source_scope import SourceDecision
from tools.tool_catalog import TOOL_POLICIES
from tools.tool_exposure import decide_tool_exposure


def test_fallback_exposes_every_canonical_tool_without_keyword_filtering():
    decision = decide_tool_exposure(
        TOOL_POLICIES,
        TOOL_POLICIES,
        turn_context=None,
        source_decision=SourceDecision(
            primary_source=None,
            authorized_sources=(),
            explicit_sources=(),
            evidence="none",
            needs_clarification=False,
            reason="test",
        ),
        messages=[],
        max_tools=1,
    )

    assert set(decision.tool_names) == set(TOOL_POLICIES)
    assert decision.dropped_tool_names == ()
    assert decision.policy_overflow is False
    assert "lookup_marine_taxonomy" in decision.tool_names
    assert "load_skill" not in decision.tool_names
