"""TDD — group EcoTaxa project samples by NeoLab/IHO region."""

import sqlite3
from unittest.mock import patch

import pytest

from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def cache_db(tmp_path):
    path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(str(path))
    init_schema(conn)
    conn.close()
    return str(path)


def _seed(cache_db, samples):
    conn = sqlite3.connect(cache_db)
    for sample in samples:
        upsert_sample(
            conn,
            sample_id=sample["sample_id"],
            project_id=sample["project_id"],
            lat_avg=sample.get("lat"),
            lon_avg=sample.get("lon"),
            date_min=sample.get("date_min", "2024-01-01"),
            date_max=sample.get("date_max", "2024-01-01"),
            object_count=sample.get("object_count", 10),
            instrument=sample.get("instrument", "UVP6"),
            last_synced="ts",
        )
    conn.close()


def _with_cache(cache_db):
    return patch(
        "core.ecotaxa_browser.region._cache_db_path",
        return_value=cache_db,
    )


def test_group_project_samples_by_region_assigns_project_samples_to_iho_zones(cache_db):
    from core.ecotaxa_browser.region import group_project_samples_by_region

    _seed(cache_db, [
        {"sample_id": 14853000001, "project_id": 14853, "lat": 73.5, "lon": -65.0},
        {"sample_id": 14853000002, "project_id": 14853, "lat": 60.0, "lon": -85.0},
        {"sample_id": 2331000001, "project_id": 2331, "lat": 73.5, "lon": -65.0},
    ])

    with _with_cache(cache_db):
        result = group_project_samples_by_region(14853)

    assert result["project_id"] == 14853
    assert result["total_samples"] == 2
    assert result["groups"]["Baie de Baffin"] == [14853000001]
    assert result["groups"]["Baie d'Hudson"] == [14853000002]
    assert "2331000001" not in result["markdown_summary"]


def test_group_project_samples_by_region_keeps_outside_and_missing_coordinate_buckets(cache_db):
    from core.ecotaxa_browser.region import group_project_samples_by_region

    _seed(cache_db, [
        {"sample_id": 10, "project_id": 42, "lat": 0.0, "lon": 0.0},
        {"sample_id": 11, "project_id": 42, "lat": None, "lon": None},
        {"sample_id": 12, "project_id": 99, "lat": 0.0, "lon": 0.0},
    ])

    with _with_cache(cache_db):
        result = group_project_samples_by_region(42)

    assert result["groups"]["Hors zone référencée"] == [10]
    assert result["groups"]["Sans coordonnées"] == [11]
    assert "| Hors zone référencée | 1 | 10 |" in result["markdown_summary"]
    assert "| Sans coordonnées | 1 | 11 |" in result["markdown_summary"]


def test_group_project_samples_by_region_uses_meow_for_points_outside_iho(cache_db):
    """Cascade partagée : un sample hors des polygones IHO mais dans une
    écorégion MEOW est rattaché à cette écorégion, pas au bucket hors zone."""
    from core.ecotaxa_browser.region import group_project_samples_by_region

    _seed(cache_db, [
        # (74.2N, -92.0W) : hors IHO, dans MEOW Lancaster Sound.
        {"sample_id": 14853000009, "project_id": 14853, "lat": 74.2, "lon": -92.0},
        # (73.5N, -65.0W) : Baie de Baffin (IHO) — priorité au nom physique.
        {"sample_id": 14853000010, "project_id": 14853, "lat": 73.5, "lon": -65.0},
    ])

    with _with_cache(cache_db):
        result = group_project_samples_by_region(14853)

    assert result["groups"]["MEOW: Lancaster Sound"] == [14853000009]
    assert result["groups"]["Baie de Baffin"] == [14853000010]
    assert result["groups"]["Hors zone référencée"] == []


def test_group_project_samples_by_region_returns_empty_groups_for_project_without_samples(cache_db):
    from core.ecotaxa_browser.region import group_project_samples_by_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 1, "lat": 73.5, "lon": -65.0},
    ])

    with _with_cache(cache_db):
        result = group_project_samples_by_region(999)

    assert result["project_id"] == 999
    assert result["total_samples"] == 0
    assert all(sample_ids == [] for sample_ids in result["groups"].values())
    assert "| Aucune région | 0 | — |" in result["markdown_summary"]


def test_rank_samples_by_region_counts_all_cached_samples(cache_db):
    from core.ecotaxa_browser.region import rank_samples_by_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 10, "lat": 73.5, "lon": -65.0},
        {"sample_id": 2, "project_id": 10, "lat": 73.6, "lon": -65.1},
        {"sample_id": 3, "project_id": 20, "lat": 60.0, "lon": -85.0},
        {"sample_id": 4, "project_id": 30, "lat": None, "lon": None},
        {"sample_id": 5, "project_id": 30, "lat": 0.0, "lon": 0.0},
    ])

    with _with_cache(cache_db):
        result = rank_samples_by_region(include_empty=False)

    rows = result["regions"]
    assert [row["region"] for row in rows] == [
        "Baie d'Hudson",
        "Hors zone référencée",
        "Sans coordonnées",
        "Baie de Baffin",
    ]
    assert [row["sample_count"] for row in rows] == [1, 1, 1, 2]
    assert rows[0]["project_count"] == 1
    assert rows[0]["sample_ids"] == [3]
    assert rows[0]["date_min"] == "2024-01-01"
    assert rows[0]["date_max"] == "2024-01-01"
    assert result["total_samples"] == 5
    assert result["regions_with_samples"] == 4


def test_rank_samples_by_region_can_include_empty_iho_zones(cache_db):
    from core.ecotaxa_browser.region import rank_samples_by_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 10, "lat": 73.5, "lon": -65.0},
    ])

    with _with_cache(cache_db):
        result = rank_samples_by_region(include_empty=True)

    by_region = {row["region"]: row for row in result["regions"]}
    assert by_region["Baie d'Ungava"]["sample_count"] == 0
    assert by_region["Baie de Baffin"]["sample_count"] == 1


def test_rank_samples_by_region_can_sort_descending(cache_db):
    from core.ecotaxa_browser.region import rank_samples_by_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 10, "lat": 73.5, "lon": -65.0},
        {"sample_id": 2, "project_id": 10, "lat": 73.6, "lon": -65.1},
        {"sample_id": 3, "project_id": 20, "lat": 60.0, "lon": -85.0},
    ])

    with _with_cache(cache_db):
        result = rank_samples_by_region(sort_order="desc")

    assert [row["region"] for row in result["regions"]] == [
        "Baie de Baffin",
        "Baie d'Hudson",
    ]
    assert [row["sample_count"] for row in result["regions"]] == [2, 1]
    assert result["sort_order"] == "desc"


def test_rank_samples_by_region_rejects_unknown_sort_order(cache_db):
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError
    from core.ecotaxa_browser.region import rank_samples_by_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 10, "lat": 73.5, "lon": -65.0},
    ])

    with _with_cache(cache_db), pytest.raises(EcoTaxaBrowserError, match="sort_order"):
        rank_samples_by_region(sort_order="sideways")


def test_rank_samples_by_region_can_sort_by_oldest_sampling_date(cache_db):
    from core.ecotaxa_browser.region import rank_samples_by_region

    _seed(cache_db, [
        {
            "sample_id": 1,
            "project_id": 10,
            "lat": 73.5,
            "lon": -65.0,
            "date_min": "2020-01-01",
            "date_max": "2020-01-02",
        },
        {
            "sample_id": 2,
            "project_id": 20,
            "lat": 60.0,
            "lon": -85.0,
            "date_min": "2015-06-01",
            "date_max": "2015-06-02",
        },
        {
            "sample_id": 3,
            "project_id": 20,
            "lat": 60.1,
            "lon": -85.1,
            "date_min": "2018-06-01",
            "date_max": "2018-06-02",
        },
    ])

    with _with_cache(cache_db):
        result = rank_samples_by_region(sort_by="date_min", sort_order="asc")

    assert [row["region"] for row in result["regions"]] == [
        "Baie d'Hudson",
        "Baie de Baffin",
    ]
    assert result["regions"][0]["date_min"] == "2015-06-01"
    assert result["regions"][0]["date_max"] == "2018-06-02"
    assert result["sort_by"] == "date_min"


def test_rank_samples_by_region_rejects_unknown_sort_by(cache_db):
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError
    from core.ecotaxa_browser.region import rank_samples_by_region

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 10, "lat": 73.5, "lon": -65.0},
    ])

    with _with_cache(cache_db), pytest.raises(EcoTaxaBrowserError, match="sort_by"):
        rank_samples_by_region(sort_by="depth")


@pytest.mark.anyio
async def test_mcp_exposes_group_project_samples_by_region_tool():
    from fastmcp import Client

    from core.mcp.ecotaxa_server import create_mcp

    payload = {
        "project_id": 42,
        "groups": {"Baie de Baffin": [42000001]},
        "total_samples": 1,
        "markdown_summary": "# Projet EcoTaxa 42",
    }
    with patch(
        "core.mcp.ecotaxa_server.group_project_samples_by_region",
        return_value=payload,
    ):
        async with Client(create_mcp()) as client:
            tools = {tool.name for tool in await client.list_tools()}
            assert "group_project_samples_by_region" in tools

            result = await client.call_tool(
                "group_project_samples_by_region",
                {"project_id": 42},
            )

    assert result.data == payload


@pytest.mark.anyio
async def test_mcp_exposes_rank_samples_by_region_tool():
    from fastmcp import Client

    from core.mcp.ecotaxa_server import create_mcp

    payload = {
        "regions": [{"region": "Baie de Baffin", "sample_count": 2}],
        "total_samples": 2,
        "markdown_summary": "# EcoTaxa — samples par région",
    }
    with patch(
        "core.mcp.ecotaxa_server.rank_samples_by_region",
        return_value=payload,
    ):
        async with Client(create_mcp()) as client:
            tools = {tool.name for tool in await client.list_tools()}
            assert "rank_samples_by_region" in tools

            result = await client.call_tool(
                "rank_samples_by_region",
                {
                    "include_empty": False,
                    "sort_by": "date_min",
                    "sort_order": "desc",
                },
            )

    assert result.data == payload


def test_langchain_tool_renders_project_samples_grouped_by_region():
    from tools.copepod_sources import make_source_tools

    payload = {
        "project_id": 42,
        "groups": {
            "Baie de Baffin": [42000001, 42000002],
            "Hors zone référencée": [],
            "Sans coordonnées": [42000003],
        },
        "total_samples": 3,
        "markdown_summary": (
            "# Projet EcoTaxa 42 — samples par région\n"
            "| Région | Samples | sample_ids |\n"
            "|---|---:|---|\n"
            "| Baie de Baffin | 2 | 42000001, 42000002 |\n"
            "| Sans coordonnées | 1 | 42000003 |"
        ),
    }
    with patch(
        "tools.copepod_sources.group_project_samples_by_region",
        return_value=payload,
    ):
        tools = make_source_tools("thread-regions")
        fn = next(
            tool for tool in tools
            if tool.name == "group_ecotaxa_project_samples_by_region"
        )
        result = fn.invoke({"project_id": 42})

    assert "Projet EcoTaxa 42" in result
    assert "Baie de Baffin | 2 | 42000001, 42000002" in result
    assert "Sans coordonnées | 1 | 42000003" in result


def test_langchain_tool_renders_ranked_samples_by_region():
    from tools.copepod_sources import make_source_tools

    payload = {
        "regions": [
            {
                "region": "Baie d'Hudson",
                "sample_count": 1,
                "project_count": 1,
                "sample_ids": [42000001],
            },
            {
                "region": "Baie de Baffin",
                "sample_count": 2,
                "project_count": 1,
                "sample_ids": [42000002, 42000003],
            },
        ],
        "total_samples": 3,
        "markdown_summary": (
            "# EcoTaxa — samples par région\n"
            "| Région | Samples | Projets | sample_ids |\n"
            "|---|---:|---:|---|\n"
            "| Baie d'Hudson | 1 | 1 | 42000001 |\n"
            "| Baie de Baffin | 2 | 1 | 42000002, 42000003 |"
        ),
    }
    with patch(
        "tools.copepod_sources.rank_samples_by_region",
        return_value=payload,
    ):
        tools = make_source_tools("thread-region-rank")
        fn = next(
            tool for tool in tools
            if tool.name == "rank_ecotaxa_samples_by_region"
        )
        result = fn.invoke({
            "include_empty": False,
            "sort_by": "date_min",
            "sort_order": "desc",
        })

    assert "EcoTaxa — samples par région" in result
    assert "Baie d'Hudson | 1 | 1 | 42000001" in result
    assert "Baie de Baffin | 2 | 1 | 42000002, 42000003" in result
