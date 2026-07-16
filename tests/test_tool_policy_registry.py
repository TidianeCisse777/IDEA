"""Contrats 2A.1 du registre déclaratif de politiques de tools."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest


def test_policy_registry_has_exact_presentation_parity():
    from tools.tool_catalog import TOOL_POLICIES, TOOL_PRESENTATION

    assert set(TOOL_POLICIES) == set(TOOL_PRESENTATION)
    assert len(TOOL_POLICIES) == 62
    for name, policy in TOOL_POLICIES.items():
        assert policy.family == TOOL_PRESENTATION[name].family
        assert policy.max_calls_per_turn >= 1
        assert policy.result_schema in ("legacy_text", "tool_result_v1")


def test_catalog_exposes_immutable_policy_lookup(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    from tools.tool_catalog import build_tool_catalog

    catalog = build_tool_catalog("policy-lookup")
    policy = catalog.policy("query_ecotaxa")

    assert policy is not None
    assert policy.requires_confirmation is True
    assert catalog.policy("does_not_exist") is None
    with pytest.raises(TypeError):
        catalog.policies["query_ecotaxa"] = policy
    with pytest.raises(FrozenInstanceError):
        policy.risk = "low"


def test_sensitive_tool_policies_are_explicit():
    from tools.tool_catalog import TOOL_POLICIES

    for name in (
        "query_ecotaxa",
        "query_ecopart",
        "query_amundsen_ctd",
        "query_bio_oracle",
        "export_deliverable",
    ):
        policy = TOOL_POLICIES[name]
        assert policy.risk == "high", name
        assert policy.expensive is True, name
        assert policy.requires_confirmation is True, name
        assert policy.max_calls_per_turn == 1, name

    assert TOOL_POLICIES["run_graph"].required_skill == "graph_writer"
    assert TOOL_POLICIES["run_graph"].mutates_session is True
    assert TOOL_POLICIES["run_pandas"].mutates_session is True
    assert TOOL_POLICIES["load_skill"].mutates_session is True
    assert TOOL_POLICIES["copy_sql_query_to_workspace"].requires_confirmation is True


def test_policy_validation_is_fail_closed(monkeypatch):
    import tools.tool_catalog as catalog_module

    missing = dict(catalog_module.TOOL_POLICIES)
    missing.pop("run_graph")
    monkeypatch.setattr(catalog_module, "TOOL_POLICIES", missing)
    with pytest.raises(ValueError, match="missing policy: run_graph"):
        catalog_module.validate_catalog(set(catalog_module.TOOL_PRESENTATION))


def test_policy_validation_rejects_inconsistent_invariants(monkeypatch):
    import tools.tool_catalog as catalog_module

    invalid = dict(catalog_module.TOOL_POLICIES)
    invalid["query_ecotaxa"] = replace(
        invalid["query_ecotaxa"],
        risk="low",
        read_only=True,
        mutates_session=True,
    )
    monkeypatch.setattr(catalog_module, "TOOL_POLICIES", invalid)

    with pytest.raises(ValueError, match="query_ecotaxa"):
        catalog_module.validate_catalog(set(catalog_module.TOOL_PRESENTATION))


def test_generated_inventory_is_deterministic_and_complete():
    from tools.tool_catalog import OPTIONAL_SQL_TOOL_NAMES, TOOL_POLICIES
    from tools.tool_docs import render_tool_inventory

    first = render_tool_inventory(TOOL_POLICIES, OPTIONAL_SQL_TOOL_NAMES)
    second = render_tool_inventory(TOOL_POLICIES, OPTIONAL_SQL_TOOL_NAMES)

    assert first == second
    assert "59 tools obligatoires" in first
    assert "62 avec SQL" in first
    assert "| `audit_ecotaxa_availability` |" in first
    assert "| `list_ecotaxa_project_samples` |" in first
    assert "| `query_ecotaxa` | ecotaxa | ecotaxa | high | oui |" in first
    assert "| `copy_sql_query_to_workspace` | sql | sql | high | oui |" in first


def test_generated_inventory_replacement_is_idempotent():
    from tools.tool_docs import replace_generated_inventory

    original = (
        "# Tools\n\n"
        "<!-- TOOL-INVENTORY:START -->\nold\n<!-- TOOL-INVENTORY:END -->\n\n"
        "## Narrative\nKeep me.\n"
    )
    once = replace_generated_inventory(original, "new block")
    twice = replace_generated_inventory(once, "new block")

    assert once == twice
    assert "old" not in once
    assert "new block" in once
    assert "## Narrative\nKeep me." in once
