import json
from unittest.mock import patch

import pytest
import requests
import vcr


@pytest.fixture
def anyio_backend():
    return "asyncio"


@vcr.use_cassette("tests/cassettes/project_detail.yaml", record_mode="none")
def test_get_project_returns_metadata_stats_and_schema_summary():
    from core.ecotaxa_browser.projects import get_project
    from tools.ecotaxa_client import EcotaxaClient

    with patch.object(EcotaxaClient, "login", return_value=None):
        project = get_project(42)

    assert project["project_id"] == 42
    assert project["name"] == "UVP5 GREEN EDGE Ice Camp 2015"
    assert project["stats"] == ["Total: 84668 objects"]
    assert project["schema"]["sample"] == ["profileid", "stationid"]
    assert project["schema"]["acquisition"] == ["exposure", "pixel"]
    assert "depth_min" in project["schema"]["object"]


def test_get_project_falls_back_to_metadata_when_stats_time_out():
    from core.ecotaxa_browser.projects import get_project

    raw = {
        "projid": 42,
        "title": "Project",
        "objcount": 100,
        "pctvalidated": 20.0,
        "pctclassified": 80.0,
    }
    with patch("core.ecotaxa_browser.projects.EcotaxaClient") as client_class:
        client = client_class.return_value
        client.get_project.return_value = raw
        client.get_project_stats.side_effect = requests.Timeout
        project = get_project(42)

    assert project["stats"] == [
        "Total: 100 objects",
        "Validated: 20.0%",
        "Classified: 80.0%",
    ]


@vcr.use_cassette("tests/cassettes/project_samples.yaml", record_mode="none")
def test_list_project_samples_returns_requested_page():
    from core.ecotaxa_browser.samples import list_project_samples
    from tools.ecotaxa_client import EcotaxaClient

    with patch.object(EcotaxaClient, "login", return_value=None):
        samples = list_project_samples(42, page=2, page_size=1)

    assert samples == [{
        "sample_id": 42000014,
        "project_id": 42,
        "original_id": "gn2015_l2_027",
        "latitude": 67.5873,
        "longitude": -62.9883,
        "free_fields": {},
    }]


@vcr.use_cassette("tests/cassettes/sample_detail.yaml", record_mode="none")
def test_get_sample_returns_stable_fields():
    from core.ecotaxa_browser.samples import get_sample
    from tools.ecotaxa_client import EcotaxaClient

    with patch.object(EcotaxaClient, "login", return_value=None):
        sample = get_sample(42000013)

    assert sample["sample_id"] == 42000013
    assert sample["project_id"] == 42
    assert sample["original_id"] == "gn2015_l2_019"
    assert sample["free_fields"] == {"profileid": "019"}


@vcr.use_cassette("tests/cassettes/project_acquisitions.yaml", record_mode="none")
def test_list_project_acquisitions_returns_stable_fields():
    from core.ecotaxa_browser.acquisitions import list_project_acquisitions
    from tools.ecotaxa_client import EcotaxaClient

    with patch.object(EcotaxaClient, "login", return_value=None):
        acquisitions = list_project_acquisitions(42)

    assert acquisitions[0]["acquisition_id"] == 420000014
    assert acquisitions[0]["sample_id"] == 42000013
    assert acquisitions[0]["instrument"] == "uvp5"


@vcr.use_cassette("tests/cassettes/acquisition_detail.yaml", record_mode="none")
def test_get_acquisition_returns_stable_fields():
    from core.ecotaxa_browser.acquisitions import get_acquisition
    from tools.ecotaxa_client import EcotaxaClient

    with patch.object(EcotaxaClient, "login", return_value=None):
        acquisition = get_acquisition(420000014)

    assert acquisition["acquisition_id"] == 420000014
    assert acquisition["sample_id"] == 42000013
    assert acquisition["free_fields"] == {"pixel": 0.147}


@vcr.use_cassette("tests/cassettes/sample_objects.yaml", record_mode="none")
def test_list_sample_objects_filters_and_paginates_in_two_requests():
    from core.ecotaxa_browser.objects import list_sample_objects
    from tools.ecotaxa_client import EcotaxaClient

    with patch.object(EcotaxaClient, "login", return_value=None):
        objects = list_sample_objects(
            42000013, taxon=85076, status="V", page=2, page_size=1
        )

    assert objects[0] == {
        "object_id": 4200030316,
        "original_id": "gn2015_l2_019_2",
        "acquisition_id": 420000014,
        "sample_id": 42000013,
        "project_id": 42,
        "taxon_id": 85076,
        "taxon": "fiber<detritus",
        "classification_status": "V",
        "date": "2015-05-22",
        "depth_min": 3.3,
        "depth_max": 3.3,
    }


@vcr.use_cassette("tests/cassettes/object_detail.yaml", record_mode="none")
def test_get_object_returns_vertical_context_in_three_requests():
    from core.ecotaxa_browser.objects import get_object
    from tools.ecotaxa_client import EcotaxaClient

    with patch.object(EcotaxaClient, "login", return_value=None):
        result = get_object(4200030315)

    assert result["object"]["object_id"] == 4200030315
    assert result["sample"]["sample_id"] == 42000013
    assert result["acquisition"]["acquisition_id"] == 420000014
    assert result["project"] == {"project_id": 42}


@vcr.use_cassette("tests/cassettes/taxonomy.yaml", record_mode="none")
def test_taxonomy_node_returns_roots_or_one_node():
    from core.ecotaxa_browser.taxonomy import taxonomy_node
    from tools.ecotaxa_client import EcotaxaClient

    with patch.object(EcotaxaClient, "login", return_value=None):
        roots = taxonomy_node()
        node = taxonomy_node(1)

    assert roots[0]["taxon_id"] == 1
    assert roots[0]["name"] == "Biota"
    assert node["taxon_id"] == 1
    assert node["children"] == [2, 3]


@vcr.use_cassette("tests/cassettes/taxonomy_search.yaml", record_mode="none")
def test_search_taxa_returns_autocomplete_results():
    from core.ecotaxa_browser.taxonomy import search_taxa
    from tools.ecotaxa_client import EcotaxaClient

    with patch.object(EcotaxaClient, "login", return_value=None):
        taxa = search_taxa("Calanus")

    assert taxa == [{
        "taxon_id": 25828,
        "name": "Calanus",
        "status": "A",
        "in_project": False,
        "aphia_id": 104152,
        "replacement_id": None,
    }]
    with pytest.raises(ValueError, match="query must not be blank"):
        search_taxa("  ")


@pytest.mark.anyio
async def test_fastmcp_v2_navigation_tools_gate():
    """Gate test V2 du MCP — vérifie d'un coup les changements apportés par
    les slices 1-4 du flow de navigation EcoTaxa :

    - 2 nouveaux outils exposés : ``summarize_samples`` (sample-level
      V/P/D/U + taxa) et ``summarize_projects`` (project-level overview
      via cache + /project_set/taxo_stats).
    - 3 outils existants acceptent désormais ``project_ids`` :
      ``samples_in_region``, ``projects_in_region``, ``find_observations``.
      Le paramètre est propagé tel quel à la couche core.

    Si ce test passe, l'API MCP V2 est complète pour le flow de navigation.
    """
    from fastmcp import Client

    from core.mcp.ecotaxa_server import create_mcp

    # ── Nouveaux outils ────────────────────────────────────────────────
    sample_summary_payload = [{
        "sample_id": 14853000001, "projid": 14853,
        "nb_validated": 50, "nb_predicted": 100,
        "nb_dubious": 2, "nb_unclassified": 0,
        "used_taxa": [80126], "per_taxon": [{"taxon_id": 80126, "name": "Calanus"}],
    }]
    project_summary_payload = [{
        "project_id": 14853, "n_samples": 20,
        "instruments": ["UVP6"],
        "date_min": "2024-10-01", "date_max": "2024-10-15",
        "bbox": {"south": 70.0, "west": -75.0, "north": 76.5, "east": -65.0},
        "nb_validated": 1500, "nb_predicted": 8000,
        "nb_dubious": 50, "nb_unclassified": 200,
        "used_taxa": [80126],
        "per_taxon": [{"taxon_id": 80126, "name": "Calanus"}],
    }]

    # ── Args reçus par les fonctions sous-jacentes (capture project_ids) ──
    captured: dict[str, dict] = {}

    def _make_capture(name: str, retval):
        def _inner(**kwargs):
            captured[name] = kwargs
            return retval
        return _inner

    samples_payload = {"samples": [], "total_matching": 0, "truncated": False, "summary": {}}
    projects_payload = {"projects": [], "total_projects": 0, "total_samples": 0, "summary": {}}
    observations_payload = {
        "taxon": {"taxon_id": 80126, "matched_name": "Calanus"},
        "granularity": "project_filtered", "status_filter": "V",
        "samples": [], "total_matching": 0, "truncated": False,
        "attested_projects": [], "project_counts": {},
    }

    patches = [
        # New tools
        patch("core.mcp.ecotaxa_server.summarize_samples",
              return_value=sample_summary_payload),
        patch("core.mcp.ecotaxa_server.summarize_projects",
              return_value=project_summary_payload),
        # Existing tools — capture kwargs to verify project_ids propagation
        patch("core.mcp.ecotaxa_server.samples_in_region",
              side_effect=_make_capture("samples_in_region", samples_payload)),
        patch("core.mcp.ecotaxa_server.projects_in_region",
              side_effect=_make_capture("projects_in_region", projects_payload)),
        patch("core.mcp.ecotaxa_server.find_observations",
              side_effect=_make_capture("find_observations", observations_payload)),
    ]
    for p in patches:
        p.start()

    try:
        async with Client(create_mcp()) as client:
            tools = {tool.name for tool in await client.list_tools()}

            # ── 1) Les 2 nouveaux outils sont publiés. ─────────────────
            assert "summarize_samples" in tools, "summarize_samples missing from MCP V2"
            assert "summarize_projects" in tools, "summarize_projects missing from MCP V2"

            # ── 2) summarize_samples retourne le payload sample-level. ─
            r1 = await client.call_tool("summarize_samples", {"sample_ids": [14853000001]})
            assert r1.data == sample_summary_payload

            # ── 3) summarize_projects retourne le payload project-level. ─
            r2 = await client.call_tool("summarize_projects", {"project_ids": [14853]})
            assert r2.data == project_summary_payload

            # ── 4) project_ids est accepté par les 3 outils existants
            #     ET propagé jusqu'à la couche core. ───────────────────
            await client.call_tool("samples_in_region", {
                "zone_name": "Baie de Baffin", "project_ids": [14853],
            })
            assert captured["samples_in_region"].get("project_ids") == [14853], \
                "samples_in_region did not propagate project_ids"

            await client.call_tool("projects_in_region", {
                "zone_name": "Baie de Baffin", "project_ids": [14853, 2331],
            })
            assert captured["projects_in_region"].get("project_ids") == [14853, 2331], \
                "projects_in_region did not propagate project_ids"

            await client.call_tool("find_observations", {
                "taxon": "Calanus", "zone_name": "Baie de Baffin",
                "project_ids": [2331],
            })
            assert captured["find_observations"].get("project_ids") == [2331], \
                "find_observations did not propagate project_ids"
    finally:
        for p in reversed(patches):
            p.stop()


@pytest.mark.anyio
async def test_fastmcp_exposes_all_m2_tools_with_json_results():
    from fastmcp import Client

    from core.mcp.ecotaxa_server import create_mcp

    cases = [
        ("get_project", {"project_id": 42}, {"project_id": 42}),
        ("list_project_samples", {"project_id": 42}, [{"sample_id": 1}]),
        ("get_sample", {"sample_id": 1}, {"sample_id": 1}),
        ("list_project_acquisitions", {"project_id": 42}, [{"acquisition_id": 2}]),
        ("get_acquisition", {"acquisition_id": 2}, {"acquisition_id": 2}),
        ("list_sample_objects", {"sample_id": 1}, [{"object_id": 3}]),
        ("get_object", {"object_id": 3}, {"object": {"object_id": 3}}),
        ("taxonomy_node", {}, [{"taxon_id": 1}]),
        ("search_taxa", {"query": "Calanus"}, [{"taxon_id": 25828}]),
    ]
    patches = [
        patch(f"core.mcp.ecotaxa_server.{name}", return_value=expected)
        for name, _, expected in cases
    ]
    for active_patch in patches:
        active_patch.start()
    try:
        async with Client(create_mcp()) as client:
            tools = {tool.name for tool in await client.list_tools()}
            for name, arguments, expected in cases:
                assert name in tools
                result = await client.call_tool(name, arguments)
                assert result.data == expected
                json.dumps(result.data)
    finally:
        for active_patch in reversed(patches):
            active_patch.stop()


@pytest.mark.anyio
async def test_fastmcp_returns_structured_business_errors():
    from fastmcp import Client

    from core.ecotaxa_browser.errors import EcoTaxaBrowserError
    from core.mcp.ecotaxa_server import create_mcp

    ambiguous_taxon = EcoTaxaBrowserError(
        "AMBIGUOUS_TAXON",
        "Multiple EcoTaxa taxa match 'Calanus'.",
        candidates=[{"taxon_id": 1, "display_name": "Calanus"}],
    )

    with patch("core.mcp.ecotaxa_server.taxa_stats", side_effect=ambiguous_taxon):
        async with Client(create_mcp()) as client:
            taxa_result = await client.call_tool(
                "taxa_stats",
                {"project_ids": [42], "taxa": ["Calanus"]},
            )

    assert taxa_result.data == {
        "ok": False,
        "error": {
            "code": "AMBIGUOUS_TAXON",
            "message": "Multiple EcoTaxa taxa match 'Calanus'.",
            "candidates": [{"taxon_id": 1, "display_name": "Calanus"}],
        },
    }

    async with Client(create_mcp()) as client:
        status_result = await client.call_tool(
            "find_observations",
            {"taxon": "Calanus", "status": "validated"},
        )

    assert status_result.data["ok"] is False
    assert status_result.data["error"]["code"] == "INVALID_STATUS"
    assert status_result.data["error"]["candidates"] == ["D", "P", "V", "all"]
