"""
Tests for copepod remote source fetch helpers.
"""

import pytest

pytestmark = pytest.mark.tool_contract


@pytest.fixture(scope="module")
def tools():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_sources_meta  # noqa: F401
    from core.tool_registry.tools import copepod_remote_sources  # noqa: F401

    code = registry.render({"copepod_sources_meta", "copepod_remote_sources"})
    ns = {}
    exec(code, ns)
    return ns


class TestFetchRemoteSourcePreview:
    def test_bio_oracle_request_returns_preview_rows(self, tools, monkeypatch):
        class FakeResponse:
            status_code = 200
            text = (
                "time,latitude,longitude,si_mean\n"
                "UTC,degrees_north,degrees_east,MMol' 'M-3\n"
                "2020-01-01T00:00:00Z,0.025,0.025,58.710329566654956\n"
                "2030-01-01T00:00:00Z,0.025,0.025,58.64176214680066\n"
            )

            def raise_for_status(self):
                return None

        requested_urls = []

        def fake_get(url, timeout=30):
            requested_urls.append(url)
            return FakeResponse()

        monkeypatch.setattr("requests.get", fake_get)

        r = tools["fetch_remote_source_preview"](
            "Va me chercher Bio-ORACLE pour le scénario SSP126 de 2020 à 2050 sur la variable si_mean.",
            source_hint="bio_oracle",
            latitude=0.0,
            longitude=0.0,
        )

        assert r["status"] == "ok"
        assert r["source_id"] == "bio_oracle"
        assert r["dataset_id"] == "si_ssp126_2020_2100_depthmean"
        assert r["row_count"] == 2
        assert r["rows"][0]["time"] == "2020-01-01T00:00:00Z"
        assert r["rows"][0]["si_mean"] == "58.710329566654956"
        assert requested_urls
        assert "erddap.bio-oracle.org" in requested_urls[0]

    def test_bio_oracle_request_without_coordinates_asks_for_clarification(self, tools):
        r = tools["fetch_remote_source_preview"](
            "Va me chercher Bio-ORACLE pour le scénario SSP126 de 2020 à 2050 sur la variable si_mean.",
            source_hint="bio_oracle",
        )

        assert r["status"] == "needs_clarification"
        assert r["source_id"] == "bio_oracle"
        assert "coordonnées" in r["clarification_question"].lower()

    def test_ogsl_request_returns_preview_rows(self, tools, monkeypatch):
        class FakeResponse:
            status_code = 200
            text = (
                "cruiseID,cruise_start_date,cruise_end_date,cruise_chief_scientist,platform_name,instrument,stationID,cast_number,time,latitude,longitude,PRES,TE90,PSAL,ASAL,FLOR,OXYM,PSAR,SIGT,TRAN\n"
                "unitless,unitless,unitless,unitless,unitless,unitless,unitless,unitless,UTC,degrees_north,degrees_east,decibars,degree_C,PSU,g/kg,mg m-3,µM,µeinsteins s-1 m-2,kg m-3,percent\n"
                "2024_06 BioDiv,2024-05-02T08:00:00Z,2024-05-05T23:59:00Z,\"Mélanie Santo\",Macoma,Sea-Bird SBE 19plus,ST122,1,2024-05-02T14:10:49Z,50.168783,-66.501883,1.0,4.3228,27.0538,27.184,2.3325,353.248,506.49,21.444,NaN\n"
                "2024_06 BioDiv,2024-05-02T08:00:00Z,2024-05-05T23:59:00Z,\"Mélanie Santo\",Macoma,Sea-Bird SBE 19plus,ST122,1,2024-05-02T14:10:49Z,50.168783,-66.501883,2.0,3.0723,28.3458,28.482,2.3964,NaN,223.335,22.5715,NaN\n"
            )

            def raise_for_status(self):
                return None

        requested_urls = []

        def fake_get(url, timeout=30):
            requested_urls.append(url)
            return FakeResponse()

        monkeypatch.setattr("requests.get", fake_get)

        r = tools["fetch_remote_source_preview"](
            "Va me chercher OGSL pour la mission 2024_06 BioDiv de 2024-05-02 à 2024-05-05 avec TE90 et PSAL.",
            source_hint="ogsl",
        )

        assert r["status"] == "ok"
        assert r["source_id"] == "ogsl"
        assert r["dataset_id"] == "ismerSgdeCtd"
        assert r["row_count"] == 2
        assert r["rows"][0]["cruiseID"] == "2024_06 BioDiv"
        assert r["rows"][0]["stationID"] == "ST122"
        assert requested_urls
        assert "erddap.ogsl.ca" in requested_urls[0]


class TestToolRegistration:
    def test_copepod_remote_sources_tag_registered(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_remote_sources  # noqa: F401

        code = registry.render({"copepod_remote_sources"})
        assert "fetch_remote_source_preview" in code
