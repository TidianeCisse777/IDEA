"""Contrats 2A.1 du registre déclaratif de politiques de tools."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest


def test_policy_registry_has_exact_presentation_parity():
    from tools.tool_catalog import (
        TOOL_EXPOSURE_GROUPS,
        TOOL_POLICIES,
        TOOL_PRESENTATION,
    )

    assert set(TOOL_POLICIES) == set(TOOL_PRESENTATION)
    assert len(TOOL_POLICIES) == 25
    for name, policy in TOOL_POLICIES.items():
        assert policy.family == TOOL_PRESENTATION[name].family
        assert policy.exposure_group in TOOL_EXPOSURE_GROUPS
        assert policy.max_calls_per_turn >= 1
        assert policy.result_schema == "tool_result_v1"


def test_canonical_enrichment_exposure_groups_are_explicit():
    from tools.tool_catalog import TOOL_POLICIES

    canonical = {
        "enrich_ecotaxa_with_ecopart_remote": "enrichment_ecopart",
        "enrich_with_amundsen_ctd": "enrichment_amundsen",
        "enrich_with_bio_oracle": "enrichment_bio_oracle",
        "enrich_with_ogsl": "enrichment_ogsl",
    }
    for name, group in canonical.items():
        assert TOOL_POLICIES[name].exposure_group == group

    assert "hidden_legacy" not in {
        policy.exposure_group for policy in TOOL_POLICIES.values()
    }


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
        "enrich_ecotaxa_with_ecopart_remote",
        "enrich_with_amundsen_ctd",
        "enrich_with_bio_oracle",
        "export_deliverable",
    ):
        policy = TOOL_POLICIES[name]
        assert policy.risk == "high", name
        assert policy.expensive is True, name
        assert policy.requires_confirmation is True, name
        assert policy.max_calls_per_turn == 1, name

    assert TOOL_POLICIES["run_graph"].mutates_session is True
    assert TOOL_POLICIES["run_pandas"].mutates_session is True
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
    assert "22 tools obligatoires" in first
    assert "25 avec SQL" in first
    assert "| `lookup_marine_taxonomy` |" in first
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
