"""Parity test: each MCP_CAPABILITIES.md section must map to at least one @tool.

This test pins the contract documented in MCP_CAPABILITIES.md against the
actual `@tool` surface exposed to the LLM via tools.copepod_sources.

When a new capability is added to the doc, add it here with the expected
covering tools. When a tool is renamed, update the mapping in one place.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ---- ground truth: capability section -> covering @tool names ----------
#
# Keys are the section headers from MCP_CAPABILITIES.md (without the
# leading "## N. " numbering). Values are the @tool names that satisfy
# at least one phrasing from the section.
CAPABILITY_TO_TOOLS: dict[str, list[str]] = {
    "Trouver Des Projets EcoTaxa": [
        "list_ecotaxa_projects",
        "find_ecotaxa_projects",
        "preview_ecotaxa_project",
    ],
    "Explorer Les Projets Par Zone": [
        "find_ecotaxa_projects_in_region",
    ],
    "Explorer Les Samples Par Zone, Date Ou Instrument": [
        "find_ecotaxa_samples_in_region",
        "group_ecotaxa_project_samples_by_region",
    ],
    "Explorer Un Taxon": [
        "count_ecotaxa_taxa",
        "find_ecotaxa_observations",
        "search_ecotaxa_taxa",
    ],
    "Résumer Des Projets Avant De Choisir": [
        "summarize_ecotaxa_project",
        "summarize_ecotaxa_projects",
    ],
    "Résumer Des Samples Avant Export": [
        "summarize_ecotaxa_sample",
        "summarize_ecotaxa_samples",
    ],
    "Comprendre Un Sample Ou Un Déploiement": [
        "get_ecotaxa_sample",
        "summarize_ecotaxa_sample_deployment",
    ],
    "Explorer Les Métadonnées UVP": [
        "inspect_ecotaxa_project_schema",
    ],
    "Inspecter Une Colonne": [
        "inspect_ecotaxa_column",
    ],
    "Comparer Des Projets Avant Export": [
        "compare_ecotaxa_projects",
    ],
    # Section 11 (Vérifier Les Droits Et L'accessibilité) is satisfied by the
    # error-handling surface of multiple tools rather than a dedicated tool.
    # Section 12 (Préparer Un Export Sans Le Lancer) is satisfied by
    # export_ecotaxa_samples in dry-run mode (`confirmed=False`).
    "Préparer Un Export Sans Le Lancer": [
        "export_ecotaxa_samples",
    ],
    "Exporter Les Données Complètes": [
        "query_ecotaxa",
        "query_ecotaxa_sample",
        "export_ecotaxa_samples",
    ],
}


@pytest.fixture(scope="module")
def tool_names() -> set[str]:
    from tools.copepod_sources import make_source_tools

    tools = make_source_tools("thread-parity")
    return {tool.name for tool in tools}


@pytest.fixture(scope="module")
def capabilities_doc_text() -> str:
    return Path("MCP_CAPABILITIES.md").read_text(encoding="utf-8")


def test_every_capability_maps_to_at_least_one_existing_tool(tool_names):
    """For each capability listed, at least one @tool name actually exists."""
    missing: list[tuple[str, list[str]]] = []
    for capability, expected_tools in CAPABILITY_TO_TOOLS.items():
        if not any(tool in tool_names for tool in expected_tools):
            missing.append((capability, expected_tools))
    assert not missing, (
        "These MCP_CAPABILITIES.md sections have no covering @tool exposed "
        "to the LLM:\n"
        + "\n".join(f"  - {cap}: expected one of {tools}" for cap, tools in missing)
    )


def test_every_capability_header_in_doc_is_mapped(capabilities_doc_text):
    """No capability section is silently dropped from the parity matrix."""
    headers_in_doc: list[str] = []
    for raw_line in capabilities_doc_text.splitlines():
        if not raw_line.startswith("## "):
            continue
        # Skip the "Ce Que L'utilisateur Ne Peut Pas Demander" wrap-up section,
        # and the "Vérifier Les Droits" / "Comprendre Un Sample" intentionally
        # tracked elsewhere.
        text = raw_line[3:].strip()
        if "Ne Peut Pas" in text or "Vérifier Les Droits" in text:
            continue
        # Strip leading "N. " numbering.
        if "." in text:
            _, _, title = text.partition(". ")
            text = title.strip() or text
        headers_in_doc.append(text)

    unmapped = [
        title for title in headers_in_doc if title not in CAPABILITY_TO_TOOLS
    ]
    assert not unmapped, (
        "These MCP_CAPABILITIES.md sections are not represented in the "
        "parity mapping (CAPABILITY_TO_TOOLS in this test file):\n"
        + "\n".join(f"  - {title}" for title in unmapped)
    )


def test_new_quickwin_tools_are_exposed(tool_names):
    """Pin the QW1 + QW2 additions."""
    assert "search_ecotaxa_taxa" in tool_names
    assert "get_ecotaxa_cache_status" in tool_names


# ---- MCP parity: same capabilities exposed via the FastMCP façade ----
#
# @tool name (C3) → MCP tool name (C4). Naming is intentionally different
# (C3 has the `_ecotaxa_` infix for LLM readability; C4 is compact). This
# table is the source of truth for the planned convergence — when a tool
# is added on one side it must appear on the other (or be exempted with a
# comment).
TOOL_TO_MCP_TOOL: dict[str, str] = {
    "find_ecotaxa_projects": "search_projects",
    "list_ecotaxa_projects": "search_projects",  # MCP merges full list + filtered
    "preview_ecotaxa_project": "preview_project",
    "inspect_ecotaxa_project_schema": "get_project_schema",
    "inspect_ecotaxa_column": "get_column_distribution",
    "compare_ecotaxa_projects": "compare_project_schemas",
    "find_ecotaxa_samples_in_region": "samples_in_region",
    "find_ecotaxa_projects_in_region": "projects_in_region",
    "group_ecotaxa_project_samples_by_region": "group_project_samples_by_region",
    "find_ecotaxa_observations": "find_observations",
    "get_ecotaxa_sample": "get_sample",
    "summarize_ecotaxa_sample_deployment": "summarize_sample_deployment",
    "summarize_ecotaxa_samples": "summarize_samples",
    "summarize_ecotaxa_sample": "summarize_sample",
    "summarize_ecotaxa_projects": "summarize_projects",
    "summarize_ecotaxa_project": "summarize_project",
    "count_ecotaxa_taxa": "taxa_stats",
    "search_ecotaxa_taxa": "search_taxa",
    "get_ecotaxa_cache_status": "cache_status",
    # Exempted (export tools stay agent-only by design):
    # "query_ecotaxa", "query_ecotaxa_sample", "export_ecotaxa_samples"
}


@pytest.fixture(scope="module")
def mcp_tool_names() -> set[str]:
    from core.mcp.ecotaxa_server import create_mcp

    mcp = create_mcp()
    # FastMCP stores registered tools in mcp._tool_manager._tools (private
    # API). The public way to enumerate is async; we rely on the private
    # registry — if it ever moves, this test will surface the change.
    registry = getattr(mcp, "_tool_manager", None)
    if registry is not None and hasattr(registry, "_tools"):
        return set(registry._tools.keys())
    # Fallback: use the public async list_tools via anyio.
    import anyio

    tools = anyio.run(mcp.list_tools)
    return {tool.name for tool in tools}


def test_every_readonly_tool_has_a_mcp_counterpart(tool_names, mcp_tool_names):
    """Every read-only @tool must have a matching MCP tool."""
    gaps: list[tuple[str, str]] = []
    for tool_name, expected_mcp_name in TOOL_TO_MCP_TOOL.items():
        if tool_name not in tool_names:
            continue  # the @tool itself was removed; tracked elsewhere
        if expected_mcp_name not in mcp_tool_names:
            gaps.append((tool_name, expected_mcp_name))
    assert not gaps, (
        "These @tool entries have no matching MCP tool:\n"
        + "\n".join(f"  - {tool} → expected `{mcp}`" for tool, mcp in gaps)
    )
