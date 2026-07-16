"""Budgets et parité documentaire attendus du control plane."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.mark.xfail(
    strict=True,
    reason="Étapes 6/10: filtrage dynamique puis réduction du prompt permanent",
)
def test_fixed_model_request_cost_stays_below_forty_percent(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from langchain_core.messages import SystemMessage

    from agent import _MAX_CONTEXT_TOKENS, _SYSTEM_PROMPT, _approx_tokens, _tool_schema_tokens
    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("redteam-fixed-budget")
    fixed = _approx_tokens([SystemMessage(content=_SYSTEM_PROMPT)]) + _tool_schema_tokens(
        catalog.tools
    )
    ceiling = int(_MAX_CONTEXT_TOKENS * 0.40)
    assert fixed <= ceiling, f"coût fixe {fixed} tokens > plafond {ceiling}"


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
