"""
Functional workflow tests for Mode Plan data understanding.

These tests exercise the intended tool chain on real fixtures:
inspect_file -> infer_column_roles -> optional describe_column/check_column_for_calc
-> summarize_understanding. The tools must document the data state without
modifying raw files.
"""
from pathlib import Path
import hashlib

import pytest


FIXTURES = Path("/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv")
ECOTAXA = FIXTURES / "ecotaxa_sample_50.tsv"
ECOPART = FIXTURES / "uvp_amundsen_105_ecopart_particles_reduced.tsv"
CTD = FIXTURES / "amundsen_12713_ctd_2018_sample.tsv"
LOKI_COLUMNS_METADATA = Path(
    "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/"
    "data_exploration/ecotaxa_14622_probe/outputs/sample/columns_metadata.tsv"
)


@pytest.fixture(scope="module")
def tools():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_columns  # noqa: F401 - triggers registration
    from core.tool_registry.tools import copepod_data  # noqa: F401 - triggers registration

    code = registry.render({"copepod_data", "copepod_columns"})
    ns = {}
    exec(code, ns)
    return ns


def _md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def _understand_file(tools, path, calculation=None):
    before = _md5(path)
    inspected = tools["inspect_file"](str(path))
    roles = tools["infer_column_roles"](inspected["columns"], inspected["metadata"])
    calc = tools["check_column_for_calc"](roles, calculation) if calculation else None
    summary = tools["summarize_understanding"](inspected, roles)
    after = _md5(path)
    assert before == after
    assert inspected["raw_file_modified"] is False
    return inspected, roles, calc, summary


def _role_names(role_report):
    return {r["role"] for r in role_report["roles"]}


class TestModePlanDataUnderstandingWorkflow:
    def test_ecotaxa_workflow_blocks_concentration_without_volume(self, tools):
        inspected, roles, calc, summary = _understand_file(tools, ECOTAXA, "concentration")

        assert inspected["source_type_guess"]["value"] == "likely_ecotaxa"
        assert "depth" in _role_names(roles)
        assert "profile_id" in _role_names(roles)
        assert "sample_volume" not in _role_names(roles)
        assert calc["feasible"] is False
        assert calc["missing_roles"] == ["sample_volume"]
        assert "sample_volume" in calc["blocking_reason"]
        assert summary["probable_source_type"] == "likely_ecotaxa"
        assert summary["taxonomic_validation_status"] == "available"
        assert "object_depth_min" in summary["useful_columns"]

    def test_ecopart_workflow_allows_concentration_with_required_roles(self, tools):
        inspected, roles, calc, summary = _understand_file(tools, ECOPART, "concentration")

        role_names = _role_names(roles)
        assert inspected["source_type_guess"]["value"] == "likely_ecopart"
        assert {"profile_id", "depth", "sample_volume"}.issubset(role_names)
        assert calc["feasible"] is True
        assert calc["missing_roles"] == []
        assert calc["blocking_reason"] is None
        assert "Profile" in summary["useful_columns"]
        assert "Sampled volume [L]" in summary["useful_columns"]
        assert len(summary["possible_joins_or_couplings"]) > 0

    def test_ctd_workflow_documents_environmental_context_not_concentration_inputs(self, tools):
        inspected, roles, calc, summary = _understand_file(tools, CTD, "concentration")

        role_names = _role_names(roles)
        assert inspected["source_type_guess"]["value"] == "likely_amundsen_ctd"
        assert "depth" in role_names
        assert "environmental_variable" in role_names
        assert calc["feasible"] is False
        assert {"sample_volume", "profile_id"}.issubset(set(calc["missing_roles"]))
        assert summary["probable_source_type"] == "likely_amundsen_ctd"
        assert summary["taxonomic_validation_status"] == "not_applicable"
        assert "TE90 (degC)" in summary["useful_columns"]

    def test_acq_pixel_um_size_is_pixel_calibration_or_documented_by_rag(self, tools):
        column_descriptor = {
            "name": "acq_pixel_um_size",
            "dtype": "float64",
            "missing_count": 0,
            "missing_rate": 0.0,
            "sample_values": [11.8],
            "semantic_guess": None,
            "unit_guess": None,
            "confidence": "low",
        }

        roles = tools["infer_column_roles"]([column_descriptor])
        role_names = _role_names(roles)
        description = tools["describe_column"]("acq_pixel_um_size", source_hint="ecotaxa")
        described_text = " ".join(
            str(description.get(k, "")) for k in ("definition", "unit", "critical_notes")
        ).lower()

        assert (
            "pixel_calibration" in role_names
            or ("pixel" in described_text and ("mm" in described_text or "um" in described_text))
        )
        assert description["confidence"] in {"reliable", "exploratory"}

    def test_loki_columns_metadata_workflow_is_covered_when_fixture_exists(self, tools):
        if not LOKI_COLUMNS_METADATA.exists():
            pytest.skip("LOKI columns metadata fixture is not available")

        inspected, roles, calc, summary = _understand_file(
            tools, LOKI_COLUMNS_METADATA, "concentration"
        )

        assert inspected["format"] == "tsv"
        assert inspected["n_rows"] != "unknown"
        assert {"category", "field", "source_name", "definition"}.issubset(
            {c["name"] for c in inspected["columns"]}
        )
        assert calc["feasible"] is False
        assert set(calc["missing_roles"]) == {"sample_volume", "depth", "profile_id"}
        assert summary["file_or_source"] == str(LOKI_COLUMNS_METADATA)
        assert len(summary["missing_or_ambiguous_data"]) > 0

