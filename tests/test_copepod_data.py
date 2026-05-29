"""
Tests for copepod_data tools: inspect_file, infer_column_roles, summarize_understanding.

These tools are structured helpers — the LLM is free to explore data with raw pandas
before or after calling them. Tests verify correct structured output on real fixtures.
"""
import pytest
from pathlib import Path

pytestmark = pytest.mark.tool_contract

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

    def test_ecotaxa_unmatched_columns_are_minimal(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        roles = tools["infer_column_roles"](r["columns"])
        assert len(roles["unmatched_columns"]) == 0

    def test_ecopart_unmatched_columns_are_minimal(self, tools):
        r = tools["inspect_file"](str(ECOPART))
        roles = tools["infer_column_roles"](r["columns"], r["metadata"])
        assert len(roles["unmatched_columns"]) == 0

    def test_ctd_unmatched_columns_are_minimal(self, tools):
        r = tools["inspect_file"](str(CTD))
        roles = tools["infer_column_roles"](r["columns"], r["metadata"])
        assert len(roles["unmatched_columns"]) == 0

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
            "possible_joins_or_couplings", "missing_or_ambiguous_data",
            "coverage_assessment",
        ]
        for key in required_keys:
            assert key in summary, f"Missing key: {key}"
        assert summary["coverage_assessment"]["status"] in {"sufficient", "partial", "insufficient"}

    def test_unsupported_format_reports_insufficient_coverage(self, tools, tmp_path):
        f = tmp_path / "unsupported.bin"
        f.write_bytes(b"\x00\x01\x02")

        inspected = tools["inspect_file"](str(f))
        roles = tools["infer_column_roles"](inspected["columns"], inspected["metadata"])
        summary = tools["summarize_understanding"](inspected, roles)

        assert inspected["format"] == "unknown"
        assert summary["coverage_assessment"]["status"] == "insufficient"
        assert "unsupported_or_unparsed_format" in summary["coverage_assessment"]["gaps"]

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

    def test_combined_source_is_neolabs_taxon(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        assert r["source_type_guess"]["value"] == "likely_neolabs_taxon"

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
        assert "depth" in role_names or "sample_depth" in role_names

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
        assert "lab_measurement" in role_names or "biomass_measurement" in role_names

    def test_unmatched_columns_preserved(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        roles = tools["infer_column_roles"](r["columns"])
        all_col_names = {c["name"] for c in r["columns"]}
        matched = {x["column"] for x in roles["roles"]}
        unmatched = set(roles["unmatched_columns"])
        assert matched | unmatched == all_col_names

    def test_combined_unmatched_columns_are_minimal(self, tools):
        r = tools["inspect_file"](str(NEOLABS_COMBINED))
        roles = tools["infer_column_roles"](r["columns"], r["metadata"])
        assert len(roles["unmatched_columns"]) == 0

    def test_abund_file_source_is_neolabs_taxon(self, tools):
        r = tools["inspect_file"](str(NEOLABS_ABUND))
        assert r["source_type_guess"]["value"] == "likely_neolabs_taxon"

    def test_abund_file_unmatched_columns_are_minimal(self, tools):
        r = tools["inspect_file"](str(NEOLABS_ABUND))
        roles = tools["infer_column_roles"](r["columns"], r["metadata"])
        assert len(roles["unmatched_columns"]) == 0


# ── format_inspect_report ─────────────────────────────────────────────────────

class TestFormatInspectReport:
    """Deterministic text rendering of an inspect_file report.

    Replaces the LLM's fragile `print(file_report)` / hand-crafted loop with a
    single helper that always prints the full report — no truncation, no
    skipped columns, no hallucinated "console limit" excuses.
    """

    def test_returns_string(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        out = tools["format_inspect_report"](r)
        assert isinstance(out, str)

    def test_contains_header_fields(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        out = tools["format_inspect_report"](r)
        assert "RAPPORT D'INSPECTION" in out
        assert "file_path" in out
        assert "format" in out
        assert "n_rows" in out
        assert "n_columns" in out
        assert "source_type_guess" in out

    def test_contains_every_column_no_truncation(self, tools):
        r = tools["inspect_file"](str(NEOLABS_ABUND))
        out = tools["format_inspect_report"](r)
        for col in r["columns"]:
            assert col["name"] in out, f"Column {col['name']!r} missing from rendered report"
        # No ellipsis-style truncation markers
        assert "[truncated]" not in out
        assert "…" not in out
        assert "..." not in out

    def test_per_column_shows_dtype_missing_and_sample(self, tools):
        r = tools["inspect_file"](str(ECOTAXA))
        out = tools["format_inspect_report"](r)
        first = r["columns"][0]
        assert first["name"] in out
        assert str(first["dtype"]) in out
        assert f"missing={first['missing_count']}" in out or str(first["missing_count"]) in out

    def test_source_type_evidence_listed(self, tools):
        r = tools["inspect_file"](str(NEOLABS_ABUND))
        out = tools["format_inspect_report"](r)
        for ev in r["source_type_guess"]["evidence"][:3]:
            assert ev in out

    def test_handles_unknown_format_gracefully(self, tools):
        r = tools["inspect_file"]("/nonexistent/path.csv")
        out = tools["format_inspect_report"](r)
        # Doesn't raise, still emits the header
        assert "RAPPORT D'INSPECTION" in out
        assert "format" in out

    def test_handles_empty_columns_list(self, tools):
        empty = {
            "file_path": "/tmp/x.csv",
            "format": "csv",
            "n_rows": 0,
            "n_columns": 0,
            "columns": [],
            "metadata": {"encoding": "utf-8", "delimiter": ",", "sheet_names": [],
                         "netcdf_dimensions": {}, "netcdf_variables": [], "source_metadata": {}},
            "source_type_guess": {"value": "unknown", "confidence": "low", "evidence": []},
            "warnings": [],
            "raw_file_modified": False,
        }
        out = tools["format_inspect_report"](empty)
        assert "RAPPORT D'INSPECTION" in out
        # Should not blow up on empty columns
        assert isinstance(out, str)

    def test_warnings_section_present_when_warnings_exist(self, tools):
        report = {
            "file_path": "/tmp/x.csv", "format": "csv",
            "n_rows": 10, "n_columns": 1,
            "columns": [{"name": "a", "dtype": "int64", "missing_count": 0,
                         "missing_rate": 0.0, "sample_values": [1, 2],
                         "semantic_guess": None, "unit_guess": None, "confidence": "low"}],
            "metadata": {"encoding": "utf-8", "delimiter": ",", "sheet_names": [],
                         "netcdf_dimensions": {}, "netcdf_variables": [], "source_metadata": {}},
            "source_type_guess": {"value": "unknown", "confidence": "low", "evidence": []},
            "warnings": ["File detected as ambiguous", "Encoding inferred"],
            "raw_file_modified": False,
        }
        out = tools["format_inspect_report"](report)
        assert "File detected as ambiguous" in out
        assert "Encoding inferred" in out


# ── collect_column_definitions + format_inspect_report with RAG ───────────────

@pytest.fixture
def tools_with_mock_describe(tools):
    """Inject a mock describe_column into the sandbox so we can test
    collect_column_definitions without hitting the real ChromaDB."""
    def _mock_describe(name, source_hint=None, session_id=None):
        known = {
            "STATION_NAME": {
                "column": "STATION_NAME",
                "definition": "Nom de la station d'échantillonnage.",
                "unit": None,
                "confidence": "reliable",
                "critical_notes": [],
                "rag_doc_ref": "colonnes_sources.md",
                "source_file": "colonnes_sources.md",
            },
            "MIN_SAMPLE_DEPTH": {
                "column": "MIN_SAMPLE_DEPTH",
                "definition": "Profondeur minimale de l'échantillon en mètres.",
                "unit": "m",
                "confidence": "reliable",
                "critical_notes": ["Toujours positif."],
                "rag_doc_ref": "colonnes_instruments.md",
                "source_file": "colonnes_instruments.md",
            },
        }
        if name in known:
            return known[name]
        return {
            "column": name,
            "definition": f"Column '{name}' not found in knowledge base.",
            "unit": None,
            "confidence": "unknown",
            "critical_notes": [],
            "rag_doc_ref": None,
            "source_file": None,
        }
    tools["describe_column"] = _mock_describe
    return tools


class TestCollectColumnDefinitions:
    """Batch-fetch RAG definitions for every column in a file_report.
    Filters out columns the RAG doesn't know."""

    def _make_report(self, column_names, source="likely_neolabs_taxon"):
        return {
            "file_path": "/tmp/x.csv",
            "format": "csv",
            "n_rows": 10,
            "n_columns": len(column_names),
            "columns": [
                {"name": n, "dtype": "object", "missing_count": 0, "missing_rate": 0.0,
                 "sample_values": [], "semantic_guess": None, "unit_guess": None,
                 "confidence": "low"}
                for n in column_names
            ],
            "metadata": {"encoding": "utf-8", "delimiter": ",", "sheet_names": [],
                         "netcdf_dimensions": {}, "netcdf_variables": [], "source_metadata": {}},
            "source_type_guess": {"value": source, "confidence": "high", "evidence": []},
            "warnings": [],
            "raw_file_modified": False,
        }

    def test_returns_list(self, tools_with_mock_describe):
        report = self._make_report(["STATION_NAME", "UNKNOWN_COL"])
        defs = tools_with_mock_describe["collect_column_definitions"](report)
        assert isinstance(defs, list)

    def test_only_known_columns_returned(self, tools_with_mock_describe):
        report = self._make_report(["STATION_NAME", "MIN_SAMPLE_DEPTH", "UNKNOWN_COL", "RANDOM"])
        defs = tools_with_mock_describe["collect_column_definitions"](report)
        names = [d["column"] for d in defs]
        assert "STATION_NAME" in names
        assert "MIN_SAMPLE_DEPTH" in names
        assert "UNKNOWN_COL" not in names
        assert "RANDOM" not in names

    def test_empty_report_returns_empty_list(self, tools_with_mock_describe):
        report = self._make_report([])
        defs = tools_with_mock_describe["collect_column_definitions"](report)
        assert defs == []

    def test_passes_source_hint_from_report(self, tools_with_mock_describe):
        captured = {}
        def spy(name, source_hint=None, session_id=None):
            captured["source_hint"] = source_hint
            captured["session_id"] = session_id
            return {"column": name, "definition": "x", "unit": None,
                    "confidence": "reliable", "critical_notes": [],
                    "rag_doc_ref": "x.md", "source_file": "x.md"}
        tools_with_mock_describe["describe_column"] = spy
        report = self._make_report(["X"], source="likely_ecotaxa")
        tools_with_mock_describe["collect_column_definitions"](report, session_id="s1")
        # Strip 'likely_' prefix before passing as source_hint
        assert captured["source_hint"] == "ecotaxa"
        assert captured["session_id"] == "s1"

    def test_resilient_to_describe_column_errors(self, tools_with_mock_describe):
        def boom(name, source_hint=None, session_id=None):
            raise RuntimeError("RAG down")
        tools_with_mock_describe["describe_column"] = boom
        report = self._make_report(["STATION_NAME"])
        # Should not raise; just returns empty
        defs = tools_with_mock_describe["collect_column_definitions"](report)
        assert defs == []


class TestFormatInspectReportWithDefinitions:
    """format_inspect_report accepts an optional column_definitions list and
    integrates them per-column in the rendered report."""

    def test_definitions_rendered_under_their_column(self, tools_with_mock_describe):
        r = tools_with_mock_describe["inspect_file"](str(NEOLABS_ABUND))
        defs = tools_with_mock_describe["collect_column_definitions"](r)
        out = tools_with_mock_describe["format_inspect_report"](r, column_definitions=defs)
        assert "Nom de la station" in out
        assert "Profondeur minimale" in out
        assert "colonnes_sources.md" in out or "colonnes_instruments.md" in out

    def test_no_definitions_means_no_rag_section(self, tools_with_mock_describe):
        r = tools_with_mock_describe["inspect_file"](str(NEOLABS_ABUND))
        out = tools_with_mock_describe["format_inspect_report"](r)  # no definitions
        # The bare column lines are still there, but no definition lines
        assert "Nom de la station" not in out

    def test_critical_notes_rendered_when_present(self, tools_with_mock_describe):
        r = tools_with_mock_describe["inspect_file"](str(NEOLABS_ABUND))
        defs = tools_with_mock_describe["collect_column_definitions"](r)
        out = tools_with_mock_describe["format_inspect_report"](r, column_definitions=defs)
        assert "Toujours positif" in out
