"""
Tests for copepod_data tools: inspect_file, infer_column_roles, summarize_understanding.

These tools are structured helpers — the LLM is free to explore data with raw pandas
before or after calling them. Tests verify correct structured output on real fixtures.
"""
import pytest
from pathlib import Path

FIXTURES = Path("/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv")
ECOTAXA  = FIXTURES / "ecotaxa_sample_50.tsv"
ECOPART  = FIXTURES / "uvp_amundsen_105_ecopart_particles_reduced.tsv"
CTD      = FIXTURES / "amundsen_12713_ctd_2018_sample.tsv"


@pytest.fixture(scope="module")
def tools():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_data  # noqa: F401 — triggers registration
    code = registry.render({"copepod_data"})
    ns = {}
    exec(code, ns)
    return ns


# ── inspect_file ──────────────────────────────────────────────────────────────

class TestInspectFile:
    def test_never_modifies_file(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        assert r["raw_file_modified"] is False

    def test_missing_file_returns_warning_not_exception(self, tools):
        r = tools["inspect_file"]("/nonexistent/file.tsv")
        assert r["raw_file_modified"] is False
        assert any("not found" in w.lower() for w in r["warnings"])

    def test_ecotaxa_format_detected(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        assert r["format"] == "tsv"
        assert isinstance(r["n_rows"], int)
        assert isinstance(r["n_columns"], int)
        assert r["n_columns"] > 0

    def test_ecotaxa_source_guess(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        guess = r["source_type_guess"]
        assert guess["value"] == "likely_ecotaxa"
        assert guess["confidence"] in ("medium", "high")
        assert len(guess["evidence"]) > 0

    def test_ecopart_source_guess(self, tools):
        r = tools["inspect_file"](str(ECOPART))
        guess = r["source_type_guess"]
        assert guess["value"] == "likely_ecopart"

    def test_ctd_source_guess(self, tools):
        r = tools["inspect_file"](str(CTD))
        guess = r["source_type_guess"]
        assert guess["value"] == "likely_amundsen_ctd"
        assert guess["confidence"] in ("medium", "high")

    def test_source_guess_never_certain(self, tools):
        for fixture in [ECOTAXA, ECOPART, CTD]:
            r = tools["inspect_file"](str(fixture))
            assert r["source_type_guess"]["value"].startswith("likely_") or \
                   r["source_type_guess"]["value"] == "unknown", \
                   "source_type_guess must never be declared as certain"

    def test_columns_have_required_fields(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        assert len(r["columns"]) > 0
        for col in r["columns"]:
            assert "name" in col
            assert "dtype" in col
            assert "missing_count" in col
            assert "missing_rate" in col
            assert "sample_values" in col
            assert "confidence" in col
            assert col["confidence"] in ("low", "medium", "high")

    def test_metadata_structure_present(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        meta = r["metadata"]
        assert "encoding" in meta
        assert "delimiter" in meta
        assert "sheet_names" in meta


# ── infer_column_roles ────────────────────────────────────────────────────────

class TestInferColumnRoles:
    def test_ecotaxa_validation_role_detected(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        roles = tools["infer_column_roles"](r["columns"])
        role_names = [x["role"] for x in roles["roles"]]
        assert "taxonomic_validation_status" in role_names

    def test_ecopart_profile_id_detected(self, tools):
        r = tools["inspect_file"](str(ECOPART))
        roles = tools["infer_column_roles"](r["columns"])
        role_names = [x["role"] for x in roles["roles"]]
        assert "profile_id" in role_names

    def test_ctd_lat_lon_detected(self, tools):
        r = tools["inspect_file"](str(CTD))
        roles = tools["infer_column_roles"](r["columns"])
        role_names = [x["role"] for x in roles["roles"]]
        assert "latitude" in role_names or "longitude" in role_names

    def test_unmatched_columns_preserved(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        roles = tools["infer_column_roles"](r["columns"])
        all_col_names = [c["name"] for c in r["columns"]]
        matched = [x["column"] for x in roles["roles"]]
        unmatched = roles["unmatched_columns"]
        assert set(matched) | set(unmatched) == set(all_col_names)

    def test_roles_have_confidence_and_evidence(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        roles = tools["infer_column_roles"](r["columns"])
        for role in roles["roles"]:
            assert role["confidence"] in ("low", "medium", "high")
            assert isinstance(role["evidence"], list)
            assert len(role["evidence"]) > 0

    def test_no_column_renamed(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        original_names = {c["name"] for c in r["columns"]}
        roles = tools["infer_column_roles"](r["columns"])
        for role in roles["roles"]:
            assert role["column"] in original_names


# ── summarize_understanding ───────────────────────────────────────────────────

class TestSummarizeUnderstanding:
    def test_ecotaxa_tax_validation_available(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        roles = tools["infer_column_roles"](r["columns"])
        summary = tools["summarize_understanding"](r, roles)
        assert summary["taxonomic_validation_status"] == "available"

    def test_ecopart_join_suggested(self, tools):
        r = tools["inspect_file"](str(ECOPART))
        roles = tools["infer_column_roles"](r["columns"])
        summary = tools["summarize_understanding"](r, roles)
        assert len(summary["possible_joins_or_couplings"]) > 0

    def test_useful_columns_subset_of_original(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        original_names = {c["name"] for c in r["columns"]}
        roles = tools["infer_column_roles"](r["columns"])
        summary = tools["summarize_understanding"](r, roles)
        for col in summary["useful_columns"]:
            assert col in original_names

    def test_no_biological_interpretation(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        roles = tools["infer_column_roles"](r["columns"])
        summary = tools["summarize_understanding"](r, roles)
        forbidden = ["species distribution", "population", "ecological", "biological conclusion"]
        text = str(summary).lower()
        for term in forbidden:
            assert term not in text

    def test_output_keys_complete(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        roles = tools["infer_column_roles"](r["columns"])
        summary = tools["summarize_understanding"](r, roles)
        required_keys = [
            "file_or_source", "probable_source_type", "useful_columns",
            "metadata_detected", "quality_limits", "taxonomic_validation_status",
            "possible_joins_or_couplings", "missing_or_ambiguous_data"
        ]
        for key in required_keys:
            assert key in summary, f"Missing key: {key}"

    def test_raw_file_never_modified(self, tools):
        import hashlib
        content_before = hashlib.md5(ECOTAXA.read_bytes()).hexdigest()
        r = tools["inspect_file"](str(ECOTAXA))
        tools["infer_column_roles"](r["columns"])
        content_after = hashlib.md5(ECOTAXA.read_bytes()).hexdigest()
        assert content_before == content_after
