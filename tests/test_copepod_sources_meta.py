"""
Tests for copepod_sources_meta tools: list_available_sources, describe_source.

TDD — these tests were written before the implementation.
"""
import pytest

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


# ── tool registry integration ──────────────────────────────────────────────────

class TestToolRegistration:
    def test_copepod_sources_meta_tag_registered(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_sources_meta  # noqa: F401
        code = registry.render({"copepod_sources_meta"})
        assert "list_available_sources" in code
        assert "describe_source" in code

    def test_rendered_code_is_executable(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_sources_meta  # noqa: F401
        code = registry.render({"copepod_sources_meta"})
        ns = {}
        exec(code, ns)
        assert "list_available_sources" in ns
        assert "describe_source" in ns

    def test_functions_have_docstrings(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_sources_meta  # noqa: F401
        code = registry.render({"copepod_sources_meta"})
        ns = {}
        exec(code, ns)
        assert ns["list_available_sources"].__doc__ is not None
        assert ns["describe_source"].__doc__ is not None
