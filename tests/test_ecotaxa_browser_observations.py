"""TDD — core/ecotaxa_browser/observations.py."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from core.ecotaxa_browser.cache.repo import init_schema, upsert_sample


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
            lat_avg=sample["lat"],
            lon_avg=sample["lon"],
            date_min=sample.get("date_min", "2018-01-01"),
            date_max=sample.get("date_max", "2018-01-01"),
            object_count=sample.get("object_count", 10),
            instrument=sample.get("instrument", "UVP5"),
            last_synced="ts",
        )
    conn.close()


def _fake_client(taxon_counts: dict):
    client = MagicMock()
    client.login.return_value = None
    client.taxon_summary.side_effect = lambda project_id, taxon_id: taxon_counts.get(
        project_id, {"total_objects": 0, "validated_objects": 0,
                     "predicted_objects": 0, "dubious_objects": 0}
    )
    client.search_taxa.return_value = [{"id": 82431, "text": "Calanus finmarchicus"}]
    client.get_taxon.return_value = {"id": 82431, "text": "Calanus finmarchicus"}
    return client


def _with_setup(cache_db, client):
    return (
        patch("core.ecotaxa_browser.region._cache_db_path", return_value=cache_db),
        patch("core.ecotaxa_browser.observations._cache_db_path", return_value=cache_db),
        patch("core.ecotaxa_browser.observations.EcotaxaClient", return_value=client),
    )


def test_find_observations_filters_samples_to_projects_with_taxon(cache_db):
    from core.ecotaxa_browser.observations import find_observations

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0},
        {"sample_id": 2, "project_id": 99, "lat": 61.0, "lon": -81.0},
        {"sample_id": 3, "project_id": 99, "lat": 62.0, "lon": -82.0},
    ])
    client = _fake_client({
        42: {"total_objects": 100, "validated_objects": 80,
             "predicted_objects": 20, "dubious_objects": 0},
        99: {"total_objects": 0, "validated_objects": 0,
             "predicted_objects": 0, "dubious_objects": 0},
    })
    patches = _with_setup(cache_db, client)
    bbox = {"south": 55.0, "west": -95.0, "north": 70.0, "east": -75.0}
    with patches[0], patches[1], patches[2]:
        result = find_observations(taxon="Calanus finmarchicus", bbox=bbox)

    assert result["granularity"] == "project_filtered"
    assert result["taxon"]["taxon_id"] == 82431
    sample_ids = sorted(s["sample_id"] for s in result["samples"])
    assert sample_ids == [1]
    attested = result["attested_projects"]
    assert attested == [42]


def test_find_observations_status_V_requires_validated_count(cache_db):
    """Default status='V' filters to projects with > 0 validated objects."""
    from core.ecotaxa_browser.observations import find_observations

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0},
        {"sample_id": 2, "project_id": 99, "lat": 61.0, "lon": -81.0},
    ])
    client = _fake_client({
        42: {"total_objects": 100, "validated_objects": 0,
             "predicted_objects": 100, "dubious_objects": 0},
        99: {"total_objects": 50, "validated_objects": 40,
             "predicted_objects": 10, "dubious_objects": 0},
    })
    patches = _with_setup(cache_db, client)
    with patches[0], patches[1], patches[2]:
        result = find_observations(taxon="Calanus finmarchicus", status="V")

    assert result["attested_projects"] == [99]
    sample_ids = [s["sample_id"] for s in result["samples"]]
    assert sample_ids == [2]


def test_find_observations_status_all_accepts_predictions(cache_db):
    from core.ecotaxa_browser.observations import find_observations

    _seed(cache_db, [
        {"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0},
    ])
    client = _fake_client({
        42: {"total_objects": 100, "validated_objects": 0,
             "predicted_objects": 100, "dubious_objects": 0},
    })
    patches = _with_setup(cache_db, client)
    with patches[0], patches[1], patches[2]:
        result = find_observations(taxon="Calanus finmarchicus", status="all")

    assert 42 in result["attested_projects"]


def test_find_observations_raises_CACHE_EMPTY(cache_db):
    from core.ecotaxa_browser.observations import find_observations
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    client = _fake_client({})
    patches = _with_setup(cache_db, client)
    with patches[0], patches[1], patches[2]:
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            find_observations(taxon="Calanus finmarchicus")
    assert exc_info.value.code == "CACHE_EMPTY"


def test_find_observations_returns_empty_when_no_project_attested(cache_db):
    from core.ecotaxa_browser.observations import find_observations

    _seed(cache_db, [{"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0}])
    client = _fake_client({
        42: {"total_objects": 0, "validated_objects": 0,
             "predicted_objects": 0, "dubious_objects": 0},
    })
    patches = _with_setup(cache_db, client)
    with patches[0], patches[1], patches[2]:
        result = find_observations(taxon="Calanus finmarchicus")

    assert result["samples"] == []
    assert result["attested_projects"] == []


def test_find_observations_propagates_taxon_resolution_error(cache_db):
    from core.ecotaxa_browser.observations import find_observations
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    _seed(cache_db, [{"sample_id": 1, "project_id": 42, "lat": 60.0, "lon": -80.0}])

    client = _fake_client({})
    client.search_taxa.return_value = []  # taxon not found
    patches = _with_setup(cache_db, client)
    with patches[0], patches[1], patches[2]:
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            find_observations(taxon="Unknownus species")
    assert exc_info.value.code == "TAXON_NOT_FOUND"


def test_find_observations_caps_samples_at_500(cache_db):
    from core.ecotaxa_browser.observations import find_observations

    _seed(cache_db, [
        {"sample_id": idx, "project_id": 42, "lat": 60.0, "lon": -80.0}
        for idx in range(1, 600)
    ])
    client = _fake_client({
        42: {"total_objects": 100, "validated_objects": 80,
             "predicted_objects": 20, "dubious_objects": 0},
    })
    patches = _with_setup(cache_db, client)
    with patches[0], patches[1], patches[2]:
        result = find_observations(taxon="Calanus finmarchicus")

    assert len(result["samples"]) == 500
    assert result["truncated"] is True
    assert result["total_matching"] == 599
