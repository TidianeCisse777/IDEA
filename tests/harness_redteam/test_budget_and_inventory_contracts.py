"""Budgets et parité documentaire attendus du control plane."""

from __future__ import annotations

import re
from pathlib import Path

def test_fixed_model_request_cost_stays_below_forty_percent(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from langchain_core.messages import SystemMessage

    from agent import (
        _MAX_CONTEXT_TOKENS,
        _SYSTEM_PROMPT,
        _approx_tokens,
        _tool_schema_tokens,
    )
    from evals.replay_harness import build_offline_report
    from tools.tool_catalog import build_tool_catalog

    report = build_offline_report(runs=1)
    turns = [turn for run in report["scenarios"] for turn in run["turns"]]
    assert turns
    assert all(len(turn["tools_exposed"]) <= 15 for turn in turns)

    fixed = max(turn["context"]["fixed_tokens"] for turn in turns)
    ceiling = int(_MAX_CONTEXT_TOKENS * 0.40)
    assert fixed <= ceiling, f"coût fixe {fixed} tokens > plafond {ceiling}"

    # Preuve conservatrice : même les 15 schémas les plus lourds du catalogue
    # respectent le budget, quelle que soit la combinaison choisie par la policy.
    catalog = build_tool_catalog("redteam-dynamic-budget")
    largest = sorted(
        catalog.tools,
        key=lambda tool: _tool_schema_tokens([tool]),
        reverse=True,
    )[:15]
    worst_case = _approx_tokens(
        [SystemMessage(content=_SYSTEM_PROMPT)]
    ) + _tool_schema_tokens(largest)
    assert worst_case <= ceiling, (
        f"pire combinaison de 15 tools {worst_case} tokens > plafond {ceiling}"
    )


def test_tools_document_matches_runtime_catalog(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import OPTIONAL_SQL_TOOL_NAMES, build_tool_catalog

    catalog = build_tool_catalog("redteam-doc-parity")
    documented = set(re.findall(r"`([a-z][a-z0-9_]+)`", Path("TOOLS.md").read_text()))
    missing = sorted(catalog.names - documented)
    text = Path("TOOLS.md").read_text(encoding="utf-8")

    assert not missing, "tools runtime absents de TOOLS.md: " + ", ".join(missing)
    assert f"**{len(catalog.names)}**" in text
    assert f"**{len(catalog.names) + len(OPTIONAL_SQL_TOOL_NAMES)}**" in text
