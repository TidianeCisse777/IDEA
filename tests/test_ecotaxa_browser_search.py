from unittest.mock import MagicMock, patch

import pytest
import vcr


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_raw_client_search_projects_uses_official_filters_and_pagination():
    from tools.ecotaxa_client import EcotaxaClient

    response = MagicMock()
    response.json.return_value = [
        {
            "projid": 123,
            "title": "Calanus project",
            "instrument": "UVP5",
        }
    ]
    client = EcotaxaClient()

    with patch.object(client._session, "get", return_value=response) as mock_get:
        projects = client.search_projects(
            title="Calanus",
            instrument="UVP5",
            window_start=50,
            window_size=25,
        )

    mock_get.assert_called_once_with(
        "https://ecotaxa.obs-vlfr.fr/api/projects/search",
        params={
            "title_filter": "Calanus",
            "instrument_filter": "UVP5",
            "window_start": 50,
            "window_size": 25,
            "order_field": "projid",
        },
        timeout=60,
    )
    response.raise_for_status.assert_called_once_with()
    assert projects == response.json.return_value


def test_core_search_projects_logs_in_paginates_and_normalizes():
    raw_projects = [
        {
            "projid": "123",
            "title": "Calanus project",
            "instrument": "UVP5",
            "status": "Annotate",
            "objcount": 1000,
            "pctvalidated": 42.5,
            "pctclassified": 90.0,
        }
    ]

    with patch("core.ecotaxa_browser.search.EcotaxaClient") as client_class:
        client = client_class.return_value
        client.search_projects.return_value = raw_projects

        from core.ecotaxa_browser.search import search_projects

        projects = search_projects(
            title="Calanus",
            instrument="UVP5",
            page=2,
            page_size=25,
        )

    client.login.assert_called_once_with()
    client.search_projects.assert_called_once_with(
        title="Calanus",
        instrument="UVP5",
        window_start=25,
        window_size=25,
    )
    assert projects == [
        {
            "project_id": 123,
            "name": "Calanus project",
            "instrument": "UVP5",
            "status": "Annotate",
            "object_count": 1000,
            "percent_validated": 42.5,
            "percent_classified": 90.0,
        }
    ]


@pytest.mark.parametrize(
    ("page", "page_size", "message"),
    [
        (0, 50, "page must be at least 1"),
        (1, 0, "page_size must be at least 1"),
    ],
)
def test_core_search_projects_rejects_invalid_pagination(page, page_size, message):
    from core.ecotaxa_browser.search import search_projects

    with pytest.raises(ValueError, match=message):
        search_projects(page=page, page_size=page_size)


@vcr.use_cassette(
    "tests/cassettes/projects_search_minimal.yaml",
    record_mode="none",
)
def test_core_search_projects_replays_official_api_without_credentials():
    from core.ecotaxa_browser.search import search_projects
    from tools.ecotaxa_client import EcotaxaClient

    with patch.object(EcotaxaClient, "login", return_value=None):
        projects = search_projects(page=1, page_size=2)

    assert len(projects) == 2
    assert {"project_id", "name", "instrument"} <= projects[0].keys()


def test_langchain_find_projects_renders_core_results_as_markdown(monkeypatch):
    monkeypatch.delenv("SESSION_STORE_DATABASE_URL", raising=False)
    projects = [
        {
            "project_id": 123,
            "name": "Calanus project",
            "instrument": "UVP5",
            "status": "Annotate",
            "object_count": 1000,
            "percent_validated": 42.5,
            "percent_classified": 90.0,
        }
    ]

    with patch(
        "tools.copepod_sources.search_projects",
        return_value=projects,
    ) as core_search:
        from tools.copepod_sources import make_source_tools

        find_projects = next(
            tool for tool in make_source_tools("thread-search")
            if tool.name == "find_ecotaxa_projects"
        )
        result = find_projects.invoke(
            {
                "title": "Calanus",
                "instrument": "UVP5",
                "page": 1,
                "page_size": 25,
            }
        )

    core_search.assert_called_once_with(
        title="Calanus",
        instrument="UVP5",
        page=1,
        page_size=25,
    )
    assert "| project_id | name | instrument | status | objects | validated |" in result
    assert "| 123 | Calanus project | UVP5 | Annotate | 1 000 | 42.5 % |" in result


@pytest.mark.anyio
async def test_fastmcp_search_projects_returns_structured_core_results():
    from fastmcp import Client

    from core.mcp.ecotaxa_server import create_mcp

    projects = [
        {
            "project_id": 123,
            "name": "Calanus project",
            "instrument": "UVP5",
            "status": "Annotate",
            "object_count": 1000,
            "percent_validated": 42.5,
            "percent_classified": 90.0,
        }
    ]

    with patch(
        "core.mcp.ecotaxa_server.search_projects",
        return_value=projects,
    ) as core_search:
        async with Client(create_mcp()) as client:
            result = await client.call_tool(
                "search_projects",
                {"title": "Calanus", "page": 1, "page_size": 50},
            )

    core_search.assert_called_once_with(
        title="Calanus",
        instrument=None,
        page=1,
        page_size=50,
    )
    assert result.data == projects
