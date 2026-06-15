"""TDD — core/ecotaxa_browser/taxa_stats.py."""

from unittest.mock import patch

import pytest
import requests


def _fake_client():
    """Helper that builds a client mock with sensible defaults."""

    from unittest.mock import MagicMock

    client = MagicMock()
    client.login.return_value = None
    return client


def _patched(client):
    return patch("core.ecotaxa_browser.taxa_stats.EcotaxaClient", return_value=client)


def test_taxa_stats_returns_V_P_D_breakdown_per_project_per_taxon():
    from core.ecotaxa_browser.taxa_stats import taxa_stats

    client = _fake_client()
    client.taxon_summary.side_effect = lambda project_id, taxon_id: {
        (1165, 84963): {
            "total_objects": 20930,
            "validated_objects": 12453,
            "predicted_objects": 8421,
            "dubious_objects": 56,
        },
        (1165, 25828): {
            "total_objects": 186530,
            "validated_objects": 84210,
            "predicted_objects": 102000,
            "dubious_objects": 320,
        },
        (2331, 84963): {
            "total_objects": 4500,
            "validated_objects": 3000,
            "predicted_objects": 1490,
            "dubious_objects": 10,
        },
        (2331, 25828): {
            "total_objects": 25000,
            "validated_objects": 18000,
            "predicted_objects": 6900,
            "dubious_objects": 100,
        },
    }[(project_id, taxon_id)]
    client.get_taxon.side_effect = lambda taxon_id: {
        84963: {"id": 84963, "display_name": "Calanus finmarchicus"},
        25828: {"id": 25828, "display_name": "Copepoda"},
    }[taxon_id]

    with _patched(client):
        result = taxa_stats(project_ids=[1165, 2331], taxa=[84963, 25828])

    rows_by_key = {(r["project_id"], r["taxon_id"]): r for r in result["rows"]}
    assert rows_by_key[(1165, 84963)]["count_V"] == 12453
    assert rows_by_key[(1165, 84963)]["count_P"] == 8421
    assert rows_by_key[(1165, 84963)]["count_D"] == 56
    assert rows_by_key[(1165, 84963)]["count_total"] == 20930
    assert rows_by_key[(1165, 84963)]["taxon_name"] == "Calanus finmarchicus"
    assert len(result["rows"]) == 4
    assert result["inaccessible_project_ids"] == []
    assert result["unresolved_taxa"] == []


def test_taxa_stats_resolves_string_taxa_via_search():
    from core.ecotaxa_browser.taxa_stats import taxa_stats

    client = _fake_client()
    client.search_taxa.side_effect = lambda query: {
        "Calanus finmarchicus": [{"id": 84963, "display_name": "Calanus finmarchicus"}],
    }[query]
    client.taxon_summary.return_value = {
        "total_objects": 100,
        "validated_objects": 60,
        "predicted_objects": 40,
        "dubious_objects": 0,
    }

    with _patched(client):
        result = taxa_stats(project_ids=[1165], taxa=["Calanus finmarchicus"])

    assert result["taxa_resolved"][0]["input"] == "Calanus finmarchicus"
    assert result["taxa_resolved"][0]["taxon_id"] == 84963
    assert result["rows"][0]["count_V"] == 60


def test_taxa_stats_raises_TAXON_NOT_FOUND_with_candidates():
    from core.ecotaxa_browser.taxa_stats import taxa_stats
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    client = _fake_client()
    client.search_taxa.return_value = []  # no candidates

    with _patched(client):
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            taxa_stats(project_ids=[1165], taxa=["Nonexistus speciesus"])

    assert exc_info.value.code == "TAXON_NOT_FOUND"
    assert "Nonexistus speciesus" in str(exc_info.value)


def test_taxa_stats_raises_AMBIGUOUS_TAXON_when_multiple_matches():
    from core.ecotaxa_browser.taxa_stats import taxa_stats
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    client = _fake_client()
    client.search_taxa.return_value = [
        {"id": 1, "display_name": "Calanus"},
        {"id": 2, "display_name": "Calanus finmarchicus"},
        {"id": 3, "display_name": "Calanus hyperboreus"},
    ]

    with _patched(client):
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            taxa_stats(project_ids=[1165], taxa=["Calanus"])

    assert exc_info.value.code == "AMBIGUOUS_TAXON"
    assert exc_info.value.candidates == [
        {"taxon_id": 1, "display_name": "Calanus"},
        {"taxon_id": 2, "display_name": "Calanus finmarchicus"},
        {"taxon_id": 3, "display_name": "Calanus hyperboreus"},
    ]


def test_taxa_stats_resolves_string_taxa_via_exact_match_even_with_multiple_results():
    from core.ecotaxa_browser.taxa_stats import taxa_stats

    client = _fake_client()
    client.search_taxa.return_value = [
        {"id": 1, "display_name": "Calanus"},
        {"id": 84963, "display_name": "Calanus finmarchicus"},
    ]
    client.taxon_summary.return_value = {
        "total_objects": 10,
        "validated_objects": 7,
        "predicted_objects": 3,
        "dubious_objects": 0,
    }

    with _patched(client):
        result = taxa_stats(project_ids=[1165], taxa=["Calanus finmarchicus"])

    assert result["taxa_resolved"][0]["taxon_id"] == 84963


def test_taxa_stats_skips_inaccessible_projects_silently():
    from core.ecotaxa_browser.taxa_stats import taxa_stats

    def fake_summary(project_id, taxon_id):
        if project_id == 9999:
            response = requests.Response()
            response.status_code = 403
            raise requests.HTTPError(response=response)
        return {
            "total_objects": 100,
            "validated_objects": 80,
            "predicted_objects": 20,
            "dubious_objects": 0,
        }

    client = _fake_client()
    client.taxon_summary.side_effect = fake_summary
    client.get_taxon.return_value = {"id": 84963, "display_name": "Calanus finmarchicus"}

    with _patched(client):
        result = taxa_stats(project_ids=[1165, 9999], taxa=[84963])

    assert result["inaccessible_project_ids"] == [9999]
    assert len(result["rows"]) == 1
    assert result["rows"][0]["project_id"] == 1165
