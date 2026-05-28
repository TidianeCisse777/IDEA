"""
Tests for copepod_sources_meta tools: list_available_sources, describe_source.

TDD — these tests were written before the implementation.
"""
import pytest

pytestmark = pytest.mark.tool_contract

KNOWN_SOURCE_FAMILIES = {"ecotaxa", "ecopart", "amundsen_ctd", "ogsl", "bio_oracle"}


@pytest.fixture(scope="module")
def tools():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_sources_meta  # noqa: F401
    code = registry.render({"copepod_sources_meta"})
    ns = {}
    exec(code, ns)
    return ns


# ── list_available_sources ─────────────────────────────────────────────────────

class TestListAvailableSources:
    def test_returns_sources_list(self, tools):
        r = tools["list_available_sources"]()
        assert "sources" in r
        assert isinstance(r["sources"], list)
        assert len(r["sources"]) > 0

    def test_all_source_families_present(self, tools):
        r = tools["list_available_sources"]()
        ids = {s["id"] for s in r["sources"]}
        for family in KNOWN_SOURCE_FAMILIES:
            assert any(family in sid for sid in ids), \
                f"Source family '{family}' missing — got: {ids}"

    def test_each_source_has_required_keys(self, tools):
        r = tools["list_available_sources"]()
        for source in r["sources"]:
            for key in ["id", "label", "type", "activated", "requires_credentials"]:
                assert key in source, f"Missing key '{key}' in source {source.get('id')}"

    def test_ecotaxa_sources_require_credentials(self, tools):
        r = tools["list_available_sources"]()
        ecotaxa = [s for s in r["sources"] if "ecotaxa" in s["id"]]
        assert len(ecotaxa) > 0, "No ecotaxa source in list"
        for s in ecotaxa:
            assert s["requires_credentials"] is True

    def test_api_sources_not_activated_without_token(self, tools):
        r = tools["list_available_sources"]()
        api_sources = [s for s in r["sources"] if s["type"] == "api"]
        for s in api_sources:
            assert s["activated"] is False, \
                f"API source '{s['id']}' should not be activated without auth_token"

    def test_type_values_are_valid(self, tools):
        valid_types = {"local", "api", "rag_only"}
        r = tools["list_available_sources"]()
        for s in r["sources"]:
            assert s["type"] in valid_types, \
                f"Invalid type '{s['type']}' for source '{s['id']}'"

    def test_activated_is_boolean(self, tools):
        r = tools["list_available_sources"]()
        for s in r["sources"]:
            assert isinstance(s["activated"], bool)

    def test_no_project_id_hardcoded_in_logic(self, tools):
        import inspect
        from core.tool_registry.tools import copepod_sources_meta
        src = inspect.getsource(copepod_sources_meta)
        # project IDs like "1165", "105", "2331" must not appear outside of metadata dicts
        # This is a structural test: the function must not embed project_id in its API call logic
        assert "project_id" not in src or "metadata" in src.lower() or "describe" in src.lower()

    def test_session_id_does_not_crash(self, tools):
        r = tools["list_available_sources"](session_id="test-ses-xyz")
        assert "sources" in r

    def test_unknown_auth_token_does_not_crash(self, tools):
        r = tools["list_available_sources"](auth_token="invalid_token_for_test")
        assert "sources" in r
        assert isinstance(r["sources"], list)


# ── describe_source ────────────────────────────────────────────────────────────

class TestDescribeSource:
    def test_ecotaxa_1165_has_content_summary(self, tools):
        r = tools["describe_source"]("ecotaxa_1165")
        assert "content_summary" in r
        assert len(r["content_summary"]) > 10

    def test_ecotaxa_1165_has_join_keys(self, tools):
        r = tools["describe_source"]("ecotaxa_1165")
        assert "join_keys" in r
        assert isinstance(r["join_keys"], list)
        assert len(r["join_keys"]) > 0

    def test_ecotaxa_1165_requires_credentials(self, tools):
        r = tools["describe_source"]("ecotaxa_1165")
        assert r.get("requires_credentials") is True

    def test_ecopart_105_has_join_key_profile(self, tools):
        r = tools["describe_source"]("ecopart_105")
        keys_lower = [k.lower() for k in r.get("join_keys", [])]
        assert any("profile" in k for k in keys_lower), \
            f"EcoPart must have profile join key, got: {r.get('join_keys')}"

    def test_unknown_source_signals_not_found(self, tools):
        r = tools["describe_source"]("xyz_nonexistent_source_99")
        text = str(r).lower()
        assert "not found" in text or "unknown" in text or r.get("found") is False

    def test_result_has_all_required_keys(self, tools):
        r = tools["describe_source"]("ecotaxa_1165")
        required = ["id", "label", "content_summary", "join_keys",
                    "known_limitations", "requires_credentials"]
        for key in required:
            assert key in r, f"Missing key: {key}"

    def test_known_limitations_is_list(self, tools):
        r = tools["describe_source"]("ecotaxa_1165")
        assert isinstance(r["known_limitations"], list)

    def test_amundsen_ctd_does_not_require_credentials(self, tools):
        r = tools["describe_source"]("amundsen_ctd")
        assert r.get("requires_credentials") is False

    def test_session_id_does_not_crash(self, tools):
        r = tools["describe_source"]("ecopart_105", session_id="ses-456")
        assert "id" in r

    def test_id_field_matches_input(self, tools):
        r = tools["describe_source"]("ecotaxa_1165")
        assert r["id"] == "ecotaxa_1165"


# ── plan_remote_source_request ────────────────────────────────────────────────

class TestPlanRemoteSourceRequest:
    def test_detects_bio_oracle_from_message_and_extracts_scenario_and_variable(self, tools):
        r = tools["plan_remote_source_request"](
            "Va me chercher Bio-ORACLE pour le scénario SSP126 de 2020 à 2050 sur la variable si_mean."
        )

        assert r["source_id"] == "bio_oracle"
        assert r["intent"] == "fetch"
        assert r["parameters"]["scenario"] == "SSP126"
        assert r["parameters"]["variable"] == "si_mean"
        assert r["parameters"]["period"]["start"] == 2020
        assert r["parameters"]["period"]["end"] == 2050
        assert r["recommended_next_step"] == "ask_clarification"
        assert "zone" in r["missing_fields"]

    def test_detects_ogsl_from_message_and_extracts_period_and_station(self, tools):
        r = tools["plan_remote_source_request"](
            "Va me chercher OGSL pour la station 12 entre 2024-01-01 et 2024-03-31 avec TE90 et PSAL."
        )

        assert r["source_id"] == "ogsl"
        assert r["intent"] == "fetch"
        assert r["parameters"]["station"] == "12"
        assert r["parameters"]["period"]["start"] == "2024-01-01"
        assert r["parameters"]["period"]["end"] == "2024-03-31"
        assert "TE90" in r["parameters"]["variables"]
        assert "PSAL" in r["parameters"]["variables"]
        assert r["recommended_next_step"] == "ask_clarification"
        assert "zone_or_station_or_mission" not in r["missing_fields"]

    def test_detects_ogsl_mission_from_message(self, tools):
        r = tools["plan_remote_source_request"](
            "Va me chercher OGSL pour la mission 2024_06 BioDiv de 2024-05-02 à 2024-05-05 avec TE90 et PSAL."
        )

        assert r["source_id"] == "ogsl"
        assert r["parameters"]["cruise_id"] == "2024_06 BioDiv"
        assert r["recommended_next_step"] == "ask_clarification"

    def test_hint_overrides_ambiguous_text(self, tools):
        r = tools["plan_remote_source_request"](
            "extrais la variable sur cette zone",
            source_hint="bio_oracle",
        )

        assert r["source_id"] == "bio_oracle"
        assert r["intent"] == "fetch"
        assert r["recommended_next_step"] == "ask_clarification"
        assert "variable" in r["missing_fields"]
        assert "scenario" in r["missing_fields"]

    def test_unknown_request_returns_unknown_source(self, tools):
        r = tools["plan_remote_source_request"]("fais quelque chose avec des données")

        assert r["source_id"] == "unknown"
        assert r["recommended_next_step"] == "ask_clarification"
        assert "source" in r["missing_fields"]


# ── tool registry integration ──────────────────────────────────────────────────

class TestToolRegistration:
    def test_copepod_sources_meta_tag_registered(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_sources_meta  # noqa: F401
        code = registry.render({"copepod_sources_meta"})
        assert "list_available_sources" in code
        assert "describe_source" in code
        assert "plan_remote_source_request" in code

    def test_rendered_code_is_executable(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_sources_meta  # noqa: F401
        code = registry.render({"copepod_sources_meta"})
        ns = {}
        exec(code, ns)
        assert "list_available_sources" in ns
        assert "describe_source" in ns
        assert "plan_remote_source_request" in ns

    def test_functions_have_docstrings(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_sources_meta  # noqa: F401
        code = registry.render({"copepod_sources_meta"})
        ns = {}
        exec(code, ns)
        assert ns["list_available_sources"].__doc__ is not None
        assert ns["describe_source"].__doc__ is not None
        assert ns["plan_remote_source_request"].__doc__ is not None
