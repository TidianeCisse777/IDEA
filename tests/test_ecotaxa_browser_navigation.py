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
