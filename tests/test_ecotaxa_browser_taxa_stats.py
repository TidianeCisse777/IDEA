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
    client.project_taxo_stats.side_effect = lambda project_ids, taxa_ids: {
        (1165, "84963,25828"): [
            {"projid": 1165, "used_taxa": [84963], "nb_validated": 12453, "nb_predicted": 8421, "nb_dubious": 56},
            {"projid": 1165, "used_taxa": [25828], "nb_validated": 84210, "nb_predicted": 102000, "nb_dubious": 320},
        ],
        (2331, "84963,25828"): [
            {"projid": 2331, "used_taxa": [84963], "nb_validated": 3000, "nb_predicted": 1490, "nb_dubious": 10},
            {"projid": 2331, "used_taxa": [25828], "nb_validated": 18000, "nb_predicted": 6900, "nb_dubious": 100},
        ],
    }[(project_ids[0], taxa_ids)]
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
    client.taxon_summary.assert_not_called()


def test_taxa_stats_resolves_string_taxa_via_search():
    from core.ecotaxa_browser.taxa_stats import taxa_stats

    client = _fake_client()
    client.search_taxa.side_effect = lambda query: {
        "Calanus finmarchicus": [{"id": 84963, "display_name": "Calanus finmarchicus"}],
    }[query]
    client.project_taxo_stats.return_value = [
        {"projid": 1165, "used_taxa": [84963], "nb_validated": 60, "nb_predicted": 40, "nb_dubious": 0},
    ]

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
    client.project_taxo_stats.return_value = [
        {"projid": 1165, "used_taxa": [84963], "nb_validated": 7, "nb_predicted": 3, "nb_dubious": 0},
    ]

    with _patched(client):
        result = taxa_stats(project_ids=[1165], taxa=["Calanus finmarchicus"])

    assert result["taxa_resolved"][0]["taxon_id"] == 84963


def test_taxa_stats_skips_inaccessible_projects_silently():
    from core.ecotaxa_browser.taxa_stats import taxa_stats

    def fake_project_taxo_stats(project_ids, taxa_ids):
        if project_ids == [9999]:
            response = requests.Response()
            response.status_code = 403
            raise requests.HTTPError(response=response)
        return [{"projid": 1165, "used_taxa": [84963], "nb_validated": 80, "nb_predicted": 20, "nb_dubious": 0}]

    client = _fake_client()
    client.project_taxo_stats.side_effect = fake_project_taxo_stats
    client.get_taxon.return_value = {"id": 84963, "display_name": "Calanus finmarchicus"}

    with _patched(client):
        result = taxa_stats(project_ids=[1165, 9999], taxa=[84963])

    assert result["inaccessible_project_ids"] == [9999]
    assert len(result["rows"]) == 1
    assert result["rows"][0]["project_id"] == 1165


@pytest.mark.parametrize("query", ["copepod", "copepods", "copepoda", "copépode", "copépodes"])
def test_taxa_stats_resolves_copepod_alias_to_ecotaxa_accepted_taxon(query):
    from core.ecotaxa_browser.taxa_stats import taxa_stats

    client = _fake_client()
    client.search_taxa.return_value = [{"id": 25828, "text": "Copepoda<Multicrustacea"}]
    client.project_taxo_stats.return_value = [
        {"projid": 14853, "used_taxa": [25828], "nb_validated": 2063, "nb_predicted": 15589, "nb_dubious": 0},
    ]

    with _patched(client):
        result = taxa_stats(project_ids=[14853], taxa=[query])

    assert result["taxa_resolved"][0]["taxon_id"] == 25828
    assert result["taxa_resolved"][0]["matched_name"] == "Copepoda<Multicrustacea"
    assert result["rows"][0]["count_V"] == 2063
    client.search_taxa.assert_called_once_with("Copepoda<Multicrustacea")


def test_taxa_stats_deduplicates_aliases_resolving_to_same_taxon_id():
    from core.ecotaxa_browser.taxa_stats import taxa_stats

    client = _fake_client()
    client.search_taxa.return_value = [{"id": 25828, "text": "Copepoda<Multicrustacea"}]
    client.project_taxo_stats.return_value = [
        {"projid": 14853, "used_taxa": [25828], "nb_validated": 2063, "nb_predicted": 15589, "nb_dubious": 0},
    ]

    with _patched(client):
        result = taxa_stats(project_ids=[14853], taxa=["copepod", "copépodes", "Copepoda<Multicrustacea"])

    assert len(result["taxa_resolved"]) == 1
    assert result["taxa_resolved"][0]["taxon_id"] == 25828
    assert len(result["rows"]) == 1
    client.project_taxo_stats.assert_called_once_with([14853], taxa_ids="25828")
