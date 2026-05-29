"""
Tests for copepod_remote_sources and plan_remote_source_request.

Unit tests (plan_*): no network.
E2E tests (fetch_*): hit real ERDDAP APIs — require internet access.
Run only E2E:  pytest -m e2e tests/test_copepod_remote_sources.py -v
Skip E2E:      pytest -m "not e2e" tests/test_copepod_remote_sources.py -v
"""
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Load tool code into a shared namespace ───────────────────────────────────

def _load_tools():
    from core.tool_registry import registry
    ns = {}
    exec(registry.render(tags={"copepod_sources_meta", "copepod_remote_sources"}), ns)
    return ns

_tools = _load_tools()
plan_remote_source_request  = _tools["plan_remote_source_request"]
fetch_remote_source_dataset = _tools["fetch_remote_source_dataset"]
_write_derived_csv          = _tools["_write_derived_csv"]


# ── plan_remote_source_request — no network ──────────────────────────────────

class TestPlanBioOracle:
    def test_detects_ssp_scenario(self):
        plan = plan_remote_source_request("thetao Bio-ORACLE SSP245 2041-2060 lat 50 lon -66")
        assert plan["parameters"].get("scenario") == "SSP245"

    def test_detects_period_years(self):
        plan = plan_remote_source_request("thetao SSP245 2041 2060 lat 50 lon -66", source_hint="bio_oracle")
        assert plan["parameters"].get("period") == {"start": 2041, "end": 2060}

    def test_detects_coordinates(self):
        plan = plan_remote_source_request("thetao SSP245 latitude 50 longitude -66", source_hint="bio_oracle")
        assert "zone" not in plan["missing_fields"]

    def test_missing_variable_flagged(self):
        plan = plan_remote_source_request("Bio-ORACLE SSP245 2041-2060 lat 50 lon -66")
        assert "variable" in plan["missing_fields"]

    def test_missing_scenario_flagged(self):
        plan = plan_remote_source_request("thetao Bio-ORACLE 2041-2060 lat 50 lon -66")
        assert "scenario" in plan["missing_fields"]

    def test_missing_zone_flagged(self):
        plan = plan_remote_source_request("thetao Bio-ORACLE SSP245 2041-2060")
        assert "zone" in plan["missing_fields"]

    def test_all_fields_present_recommends_proceed(self):
        plan = plan_remote_source_request(
            "variable thetao SSP245 2041-2060 latitude 50 longitude -66",
            source_hint="bio_oracle"
        )
        assert plan["missing_fields"] == []
        assert plan["recommended_next_step"] == "proceed"


class TestPlanOGSL:
    def test_detects_ogsl_from_text(self):
        plan = plan_remote_source_request("données CTD golfe du Saint-Laurent 2013")
        assert plan["source_id"] == "ogsl"

    def test_extracts_iso_period(self):
        plan = plan_remote_source_request("OGSL CTD 2013-06-01 2013-07-15", source_hint="ogsl")
        assert plan["parameters"].get("period") == {"start": "2013-06-01", "end": "2013-07-15"}

    def test_extracts_station(self):
        plan = plan_remote_source_request("OGSL station IML4 2013", source_hint="ogsl")
        assert plan["parameters"].get("station") == "IML4"

    def test_missing_zone_flagged(self):
        plan = plan_remote_source_request("OGSL CTD données", source_hint="ogsl")
        assert "zone_or_station_or_mission" in plan["missing_fields"]


class TestPlanUnknownSource:
    def test_unknown_source_returns_clarification(self):
        plan = plan_remote_source_request("données météo")
        assert plan["source_id"] == "unknown"
        assert "source" in plan["missing_fields"]


# ── fetch_remote_source_dataset — gating (no network) ────────────────────────

class TestFetchGating:
    def test_unknown_source_needs_clarification(self):
        r = fetch_remote_source_dataset("u:s:c", "unknown_xyz", {})
        assert r["status"] == "needs_clarification"

    def test_bio_oracle_missing_scenario(self):
        r = fetch_remote_source_dataset("u:s:c", "bio_oracle", {"variable": "thetao"})
        assert r["status"] == "needs_clarification"
        assert "scenario" in r["missing_fields"]

    def test_bio_oracle_missing_zone(self):
        r = fetch_remote_source_dataset("u:s:c", "bio_oracle", {
            "variable": "thetao", "scenario": "SSP245",
            "period": {"start": 2041, "end": 2060},
        })
        assert r["status"] == "needs_clarification"
        assert "zone" in r["missing_fields"]


# ── download_url format ───────────────────────────────────────────────────────

class TestDownloadUrl:
    def test_download_url_starts_with_slash_static(self, tmp_path):
        import pandas as pd

        df = pd.DataFrame({"time": ["2041-01-01"], "thetao_max": [5.2]})
        orig = _tools["_remote_source_upload_root"]
        _tools["_remote_source_upload_root"] = lambda sk: tmp_path
        try:
            r = _write_derived_csv(
                "user:session:copepod", df, "test.csv",
                {"source_id": "bio_oracle", "source_dataset_id": "ds1",
                 "source_dataset_title": "T", "source_query": "q"}
            )
        finally:
            _tools["_remote_source_upload_root"] = orig

        assert r["status"] == "persisted"
        assert r["download_url"].startswith("/")
        assert r["download_url"].endswith(".csv")
        assert r["row_count"] == 1


# ── E2E — Bio-ORACLE (real ERDDAP) ───────────────────────────────────────────

@pytest.mark.e2e
class TestFetchBioOracleE2E:
    """Hits erddap.bio-oracle.org — requires internet."""

    SESSION_KEY = "testuser:test-e2e-session:copepod"

    def test_fetch_thetao_ssp245_single_point(self, tmp_path):
        orig = _tools["_remote_source_upload_root"]
        _tools["_remote_source_upload_root"] = lambda sk: tmp_path
        try:
            r = fetch_remote_source_dataset(
                session_key=self.SESSION_KEY,
                source_id="bio_oracle",
                parameters={
                    "variable": "thetao",
                    "variables": ["thetao"],
                    "scenario": "SSP245",
                    "period": {"start": 2041, "end": 2060},
                    "latitude": 50.0,
                    "longitude": -66.0,
                }
            )
        finally:
            _tools["_remote_source_upload_root"] = orig

        assert r["status"] == "persisted", f"unexpected: {r}"
        assert r["source_id"] == "bio_oracle"
        assert "ssp245" in r["source_dataset_id"].lower()
        assert r["row_count"] >= 1
        assert r["download_url"].startswith("/")
        assert Path(r["file_path"]).exists()

    def test_fetch_so_ssp126(self, tmp_path):
        orig = _tools["_remote_source_upload_root"]
        _tools["_remote_source_upload_root"] = lambda sk: tmp_path
        try:
            r = fetch_remote_source_dataset(
                session_key=self.SESSION_KEY,
                source_id="bio_oracle",
                parameters={
                    "variable": "so",
                    "variables": ["so"],
                    "scenario": "SSP126",
                    "period": {"start": 2041, "end": 2060},
                    "latitude": 48.0,
                    "longitude": -68.0,
                }
            )
        finally:
            _tools["_remote_source_upload_root"] = orig

        assert r["status"] == "persisted", f"unexpected: {r}"
        assert r["row_count"] >= 1

    def test_csv_file_has_expected_columns(self, tmp_path):
        import pandas as pd

        orig = _tools["_remote_source_upload_root"]
        _tools["_remote_source_upload_root"] = lambda sk: tmp_path
        try:
            r = fetch_remote_source_dataset(
                session_key=self.SESSION_KEY,
                source_id="bio_oracle",
                parameters={
                    "variable": "thetao",
                    "variables": ["thetao"],
                    "scenario": "SSP245",
                    "period": {"start": 2041, "end": 2060},
                    "latitude": 50.0,
                    "longitude": -66.0,
                }
            )
        finally:
            _tools["_remote_source_upload_root"] = orig

        df = pd.read_csv(r["file_path"])
        assert "time" in df.columns
        assert "latitude" in df.columns
        assert "longitude" in df.columns
        # At least one variable column beyond coordinates
        data_cols = [c for c in df.columns if c not in ("time", "latitude", "longitude")]
        assert len(data_cols) >= 1


# ── E2E — OGSL (real ERDDAP) ─────────────────────────────────────────────────

@pytest.mark.e2e
class TestFetchOGSLE2E:
    """Hits erddap.ogsl.ca — requires internet."""

    SESSION_KEY = "testuser:test-e2e-session:copepod"

    def test_fetch_ctd_2013(self, tmp_path):
        orig = _tools["_remote_source_upload_root"]
        _tools["_remote_source_upload_root"] = lambda sk: tmp_path
        try:
            r = fetch_remote_source_dataset(
                session_key=self.SESSION_KEY,
                source_id="ogsl",
                parameters={
                    "period": {"start": "2013-06-01", "end": "2013-07-15"},
                    "variables": ["TE90", "PSAL"],
                }
            )
        finally:
            _tools["_remote_source_upload_root"] = orig

        assert r["status"] == "persisted", f"unexpected: {r}"
        assert r["source_id"] == "ogsl"
        assert r["row_count"] >= 1
        assert r["download_url"].startswith("/")

    def test_csv_has_erddap_column_names(self, tmp_path):
        import pandas as pd

        orig = _tools["_remote_source_upload_root"]
        _tools["_remote_source_upload_root"] = lambda sk: tmp_path
        try:
            r = fetch_remote_source_dataset(
                session_key=self.SESSION_KEY,
                source_id="ogsl",
                parameters={
                    "period": {"start": "2013-06-01", "end": "2013-07-15"},
                    "variables": ["TE90", "PSAL"],
                }
            )
        finally:
            _tools["_remote_source_upload_root"] = orig

        df = pd.read_csv(r["file_path"])
        # OGSL uses ERDDAP names — must NOT contain plain English names
        assert "temperature" not in df.columns
        assert "salinity" not in df.columns
        # Core coordinate columns always present
        assert "time" in df.columns
        assert "latitude" in df.columns
        assert "longitude" in df.columns
