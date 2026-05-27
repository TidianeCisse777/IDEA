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

NEOLABS_DIR      = Path("/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/Donnée Neolabs Taxon")
NEOLABS_COMBINED = NEOLABS_DIR / "IDEA Taxonomy Samples and Analyses Data Metadata May 26 2026.csv"
NEOLABS_ABUND    = NEOLABS_DIR / "IDEA Taxonomy Zooplankton Abundances Data May 26 2026.csv"


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

    def test_tsv_delimiter_reported_as_tab(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        assert r["metadata"]["delimiter"] == "\t"

    def test_semicolon_csv_delimiter_detected(self, tools, tmp_path):
        f = tmp_path / "semicolon.csv"
        f.write_text("col_a;col_b;col_c\n1;2;3\n4;5;6\n", encoding="utf-8")
        r = tools["inspect_file"](str(f))
        assert r["metadata"]["delimiter"] == ";"
        assert r["n_columns"] == 3

    def test_ecotaxa_type_row_detected_and_skipped(self, tools, tmp_path):
        f = tmp_path / "ecotaxa_with_type_row.tsv"
        f.write_text(
            "object_id\tobject_lat\tobject_depth_min\tobject_annotation_status\n"
            "[t]\t[f]\t[f]\t[t]\n"
            "obj_001\t68.3\t10.5\tvalidated\n"
            "obj_002\t68.4\t12.0\tvalidated\n",
            encoding="utf-8",
        )
        r = tools["inspect_file"](str(f))
        assert r["metadata"].get("ecotaxa_type_row_skipped") is True
        assert any("type row" in w.lower() for w in r["warnings"])
        # First data row must be actual data, not [t]/[f] values.
        sample_vals = {v for col in r["columns"] for v in col["sample_values"]}
        assert "[t]" not in sample_vals
        assert "[f]" not in sample_vals
        # Row count must exclude the type row.
        assert r["n_rows"] == 2


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


# ── inspect_file — NeoLab Taxonomy ────────────────────────────────────────────

class TestInspectFileNeoLabs:
    def test_combined_never_modifies_file(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        assert r["raw_file_modified"] is False

    def test_combined_format_is_csv(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        assert r["format"] == "csv"

    def test_combined_has_93_columns(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        assert r["n_columns"] == 93

    def test_combined_source_not_ecotaxa(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        assert r["source_type_guess"]["value"] != "likely_ecotaxa"

    def test_combined_source_not_ecopart(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        assert r["source_type_guess"]["value"] != "likely_ecopart"

    def test_combined_volume_columns_present(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        col_names = [c["name"] for c in r["columns"]]
        assert "DEPTH_CALC_NET_FILTERED_VOL" in col_names
        assert "FLOWMETER_CALC_VOL" in col_names

    def test_combined_c1_abund_columns_present(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        col_names = [c["name"] for c in r["columns"]]
        assert "C1_ABUND (ind./m3 depth vol.)" in col_names
        assert "C1_ABUND (ind./m3 flowmeter vol.)" in col_names

    def test_combined_biomass_columns_present(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        col_names = [c["name"] for c in r["columns"]]
        assert "C1_BIOMASS (µg C m-3 depth vol.)" in col_names
        assert "COPEPODID_BIOMASS (µg C m-3 flowmeter vol.)" in col_names

    def test_combined_nauplius_columns_present(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        col_names = [c["name"] for c in r["columns"]]
        assert "NAUPLIUS_ABUND (ind./m3 depth vol.)" in col_names
        assert "ALL_STAGES_ABUND (ind./m3 depth vol.)" in col_names

    def test_combined_all_stages_no_biomass_column(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        col_names = [c["name"] for c in r["columns"]]
        # Nauplii and ALL_STAGES have no BIOMASS column in this file
        assert "ALL_STAGES_BIOMASS (µg C m-3 depth vol.)" not in col_names
        assert "NAUPLIUS_BIOMASS (µg C m-3 depth vol.)" not in col_names

    def test_abund_file_never_modifies_file(self, tools):
        r = tools["inspect_file"](str(NEOLABS_ABUND))
        assert r["raw_file_modified"] is False

    def test_abund_file_format_is_csv(self, tools):
        r = tools["inspect_file"](str(NEOLABS_ABUND))
        assert r["format"] == "csv"

    def test_abund_file_has_zooplankton_category(self, tools):
        r = tools["inspect_file"](str(NEOLABS_ABUND))
        col_names = [c["name"] for c in r["columns"]]
        assert "ZOOPLANKTON_CATEGORY" in col_names

    def test_abund_file_has_fraction_columns(self, tools):
        r = tools["inspect_file"](str(NEOLABS_ABUND))
        col_names = [c["name"] for c in r["columns"]]
        assert "Large Fract (ind./m3 depth vol)" in col_names
        assert "Small Fract (ind./m3 depth vol)" in col_names
        assert "Total abundance (ind./m3 depth vol)" in col_names


# ── infer_column_roles — NeoLab Taxonomy ──────────────────────────────────────

class TestInferColumnRolesNeoLabs:
    def test_volume_columns_get_sample_volume_role(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        roles = tools["infer_column_roles"](r["columns"])
        role_names = [x["role"] for x in roles["roles"]]
        assert "sample_volume" in role_names

    def test_depth_columns_get_depth_role(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        roles = tools["infer_column_roles"](r["columns"])
        role_names = [x["role"] for x in roles["roles"]]
        assert "depth" in role_names

    def test_taxon_column_gets_taxon_role(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        roles = tools["infer_column_roles"](r["columns"])
        role_names = [x["role"] for x in roles["roles"]]
        assert "taxon" in role_names

    def test_date_column_gets_time_role(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        roles = tools["infer_column_roles"](r["columns"])
        role_names = [x["role"] for x in roles["roles"]]
        assert "time" in role_names

    def test_biomass_columns_get_lab_measurement_role(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        roles = tools["infer_column_roles"](r["columns"])
        role_names = [x["role"] for x in roles["roles"]]
        assert "lab_measurement" in role_names

    def test_unmatched_columns_preserved(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        roles = tools["infer_column_roles"](r["columns"])
        all_col_names = {c["name"] for c in r["columns"]}
        matched = {x["column"] for x in roles["roles"]}
        unmatched = set(roles["unmatched_columns"])
        assert matched | unmatched == all_col_names
