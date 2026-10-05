"""Read-only warehouse/API acceptance checks. Run with NAVIGATOR_LIVE=1.

These are live audits, not fixture unit tests. No scientific rows are modified.
The spatial oracle uses Shapely independently of the navigator's ray casting.
"""
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.skipif(os.getenv("NAVIGATOR_LIVE") != "1", reason="Opt-in live warehouse audit")
ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("NAVIGATOR_URL", "http://localhost:8090")


def sql(query):
    result = subprocess.run(
        ["docker", "exec", "neolab-warehouse-db", "psql", "-X", "-v", "ON_ERROR_STOP=1",
         "-U", "neolab", "-d", "neolab_warehouse", "-qAtc",
         "BEGIN READ ONLY; SELECT coalesce(json_agg(t),'[]') FROM (" + query + ") t; COMMIT;"],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def api(route, params=()):
    with urlopen(BASE + route + "?" + urlencode(params), timeout=60) as response:
        return json.load(response)


@pytest.fixture(scope="module")
def source():
    return {
        "uvp": sql("SELECT id,sample_name,latitude,longitude,sampled_at,marine_zone_name,ecotaxa_project_id FROM warehouse.uvp_profile"),
        "filet": sql("SELECT id,sample_id,latitude,longitude,sampling_year,deployment_datetime_start FROM warehouse.filet_sample"),
    }


def test_baseline_metrics_match_sql(source):
    result = api("/api/coverage")
    assert result["uvp"]["profiles"] == len(source["uvp"])
    assert result["filet"]["samples"] == len(source["filet"])
    assert result["ctd"]["profiles"] == sql("SELECT count(DISTINCT ctd_profile_id) AS n FROM warehouse.uvp_ctd")[0]["n"]
    assert result["uvp"]["objects_mapped"] == sql("SELECT count(*) AS n FROM warehouse.uvp_object_bin WHERE mapping_status='accepted'")[0]["n"]
    dates = sorted(row["sampled_at"][:10] for row in source["uvp"] if row["sampled_at"])
    assert (result["uvp"]["first_date"], result["uvp"]["last_date"]) == (dates[0], dates[-1])


def test_map_baseline_preserves_geolocated_samples(source):
    result = api("/api/map")
    for kind in ("uvp", "filet"):
        expected = [r for r in source[kind] if r["latitude"] is not None and r["longitude"] is not None]
        assert sum(r["count"] for r in result[kind]) == len(expected)
        assert len({(r["latitude"], r["longitude"]) for r in result[kind]}) == len(result[kind])


ZONES = sorted({f["properties"]["canonical"] for f in json.loads((ROOT / "shared_data/geo/zones_registry.geojson").read_text())["features"]})


@pytest.mark.parametrize("zone", ZONES)
def test_zone_filet_is_geographic_membership(zone, source):
    from shapely.geometry import Point, shape
    if zone not in api("/api/options")["zones"]:
        pytest.skip("Outside navigator scope")
    polygons = [shape(f["geometry"]) for f in json.loads((ROOT / "shared_data/geo/zones_registry.geojson").read_text())["features"] if f["properties"]["canonical"] == zone]
    expected = {r["sample_id"] for r in source["filet"] if r["longitude"] is not None and r["latitude"] is not None and any(p.covers(Point(r["longitude"], r["latitude"])) for p in polygons)}
    params = [("zone", zone)]
    actual = api("/api/map", params)["filet"]
    actual_ids = {sample for point in actual for sample in point["samples"].split(", ")}
    assert actual_ids == expected, {"zone": zone, "missing": len(expected - actual_ids), "extra": len(actual_ids - expected)}
    assert api("/api/coverage", params)["filet"]["samples"] == len(expected)
    expected_uvp_rows = [r for r in source["uvp"] if r["longitude"] is not None and r["latitude"] is not None and any(p.covers(Point(r["longitude"], r["latitude"])) for p in polygons)]
    expected_uvp = {r["sample_name"] for r in expected_uvp_rows}
    points = api("/api/map", params)["uvp"]
    assert {s for p in points for s in p["samples"].split(", ")} == expected_uvp
    assert sum(p["count"] for p in points) == len(expected_uvp_rows)
    assert api("/api/coverage", params)["uvp"]["profiles"] == len(expected_uvp_rows)


@pytest.mark.parametrize("start,end", [(2024, 2024), (2020, 2024), (2025, 2025), (1900, 1901), (2024, 2020)])
def test_year_ranges_match_source(start, end, source):
    result = api("/api/coverage", [("year_from", start), ("year_to", end)])
    low, high = sorted((start, end))
    assert result["uvp"]["profiles"] == sum(bool(r["sampled_at"]) and low <= int(r["sampled_at"][:4]) <= high for r in source["uvp"])
    assert result["filet"]["samples"] == sum(r["sampling_year"] is not None and low <= r["sampling_year"] <= high for r in source["filet"])


@pytest.mark.parametrize("hours", [1, 4, 6, 10])
def test_comparison_time_and_metadata(hours):
    from datetime import datetime, timezone
    result = api("/api/filet-uvp", [("max_gap_hours", hours)])
    expected = sql(f"SELECT count(*) AS n FROM warehouse.filet_uvp_match m JOIN warehouse.filet_sample s ON s.id=m.filet_sample_id JOIN warehouse.uvp_profile p ON p.id=m.uvp_profile_id WHERE m.time_gap_hours <= {hours} AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL")[0]["n"]
    assert len(result["matches"]) == expected
    for row in result["matches"]:
        def utc(value):
            parsed = datetime.fromisoformat(value)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        gap = abs((utc(row["filet_time"]) - utc(row["uvp_time"])).total_seconds()) / 3600
        assert abs(gap - row["time_gap_hours"]) < 0.001
        assert gap <= hours
        assert row["uvp_project"]
        assert "gear" in row and "min_sample_depth" in row


@pytest.mark.parametrize("params", [[("year_from", 1800)], [("max_gap_hours", 0)], [("max_gap_hours", 73)], [("ecotaxa_project", "invalid")]])
def test_invalid_filters_are_rejected(params):
    from urllib.error import HTTPError
    with pytest.raises(HTTPError) as error:
        api("/api/coverage", params)
    assert error.value.code == 422


@pytest.mark.parametrize("params", [[], [("zone", "Baie de Baffin")], [("year_from", 2024), ("year_to", 2024)], [("ecotaxa_project", 14844), ("ecotaxa_project", 14859)], [("zone", "Baie d'Hudson"), ("zone", "Nunavik")]])
@pytest.mark.parametrize("hours", [4, 10])
def test_matched_map_and_totals_use_exact_same_pairs(params, hours):
    pairs = api("/api/filet-uvp", params + [("max_gap_hours", hours)])["matches"]
    accepted = [r for r in pairs if r["match_status"] == "accepted"]
    selected = params + [("max_gap_hours", hours), ("matched_only", "true")]
    points = api("/api/map", selected)
    coverage = api("/api/coverage", selected)
    expected_filet = {r["sample_id"] for r in accepted}
    expected_uvp = {r["sample_name"] for r in accepted}
    assert {s for p in points["filet"] for s in p["samples"].split(", ")} == expected_filet
    assert {s for p in points["uvp"] for s in p["samples"].split(", ")} == expected_uvp
    assert coverage["filet"]["samples"] == len(expected_filet)
    assert coverage["uvp"]["profiles"] == len(expected_uvp)


def test_filet_period_and_multizone_union(source):
    params = [("zone", "Baie d'Hudson"), ("zone", "Nunavik")]
    samples = {s for p in api("/api/map", params)["filet"] for s in p["samples"].split(", ")}
    separate = set()
    for param in params:
        separate.update(s for p in api("/api/map", [param])["filet"] for s in p["samples"].split(", "))
    assert samples == separate
    coverage = api("/api/coverage", params)["filet"]
    assert coverage["samples"] == len(samples)
    dates = sorted(r["deployment_datetime_start"][:10] for r in source["filet"] if r["sample_id"] in samples and r["deployment_datetime_start"])
    assert (coverage["first_date"], coverage["last_date"]) == (dates[0], dates[-1])
