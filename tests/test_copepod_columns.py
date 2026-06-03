"""
Tests for copepod_columns tools: describe_column, check_column_for_calc.

TDD — these tests were written before the implementation.
"""
import os
import pytest
from pathlib import Path

pytestmark = pytest.mark.tool_contract

def _resolve_copepod_specs_root() -> Path | None:
    candidates = []
    env_root = os.getenv("COPEPOD_SPECS_DIR")
    if env_root:
        candidates.append(Path(env_root))
    repo_root = Path(__file__).resolve().parents[1]
    candidates.append(repo_root.parent / "assistant-copepodes-specs")
    for root in candidates:
        if root.exists():
            return root
    return None


_SPECS_ROOT = _resolve_copepod_specs_root()
if _SPECS_ROOT is None:
    pytest.skip(
        "Copepod fixture repo not found. Clone assistant-copepodes-specs beside IDEA or set COPEPOD_SPECS_DIR.",
        allow_module_level=True,
    )

FIXTURES = _SPECS_ROOT / "data_exploration/examples_tsv"
ECOTAXA_FILE = FIXTURES / "ecotaxa_sample_50.tsv"
ECOPART_FILE = FIXTURES / "uvp_amundsen_105_ecopart_particles_reduced.tsv"


@pytest.fixture(scope="module")
def tools():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_columns  # noqa: F401 — triggers registration
    code = registry.render({"copepod_columns"})
    ns = {}
    exec(code, ns)
    return ns


def _roles(*role_names):
    """Build a minimal infer_column_roles() output dict for a given set of role names."""
    return {
        "roles": [
            {"role": r, "column": f"col_{r}", "confidence": "medium", "evidence": [f"test fixture for {r}"]}
            for r in role_names
        ],
        "unmatched_columns": [],
        "warnings": [],
    }


@pytest.fixture(scope="module")
def ecotaxa_roles(tools):
    """Roles inferred from the EcoTaxa fixture — no sample_volume, no profile_id."""
    import pandas as pd
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_data  # noqa: F401
    data_code = registry.render({"copepod_data"})
    ns = {}
    exec(data_code, ns)
    df = pd.read_csv(ECOTAXA_FILE, sep="\t", nrows=5, on_bad_lines="skip")
    col_dicts = [{"name": c, "dtype": "object", "missing_count": 0,
                  "missing_rate": 0.0, "sample_values": [], "semantic_guess": None,
                  "unit_guess": None, "confidence": "low"} for c in df.columns]
    return ns["infer_column_roles"](col_dicts)


# ── describe_column ────────────────────────────────────────────────────────────

class TestDescribeColumn:
    def test_acq_pixel_unit_contains_mm(self, tools):
        r = tools["describe_column"]("acq_pixel")
        assert r["unit"] is not None
        assert "mm" in r["unit"].lower()

    def test_acq_pixel_has_critical_note(self, tools):
        r = tools["describe_column"]("acq_pixel")
        assert len(r["critical_notes"]) > 0
        combined = " ".join(r["critical_notes"]).lower()
        assert "convers" in combined or "pixel" in combined or "mm" in combined

    def test_acq_pixel_cites_instruments_doc(self, tools):
        r = tools["describe_column"]("acq_pixel")
        assert r["rag_doc_ref"] is not None
        assert "colonnes_instruments" in r["rag_doc_ref"]

    def test_known_column_has_non_empty_definition(self, tools):
        r = tools["describe_column"]("object_feret")
        assert r["definition"] is not None
        assert len(r["definition"].strip()) > 5

    def test_unknown_column_confidence_is_unknown(self, tools):
        r = tools["describe_column"]("xyz_nonexistent_column_9999")
        assert r["confidence"] == "unknown"

    def test_result_has_all_required_keys(self, tools):
        r = tools["describe_column"]("acq_pixel")
        required = ["column", "definition", "unit", "confidence", "critical_notes",
                    "rag_doc_ref", "source_file"]
        for key in required:
            assert key in r, f"Missing key: {key}"

    def test_column_field_echoes_input(self, tools):
        r = tools["describe_column"]("object_depth_min")
        assert r["column"] == "object_depth_min"

    def test_critical_notes_is_list(self, tools):
        r = tools["describe_column"]("acq_pixel")
        assert isinstance(r["critical_notes"], list)

    def test_source_hint_does_not_crash(self, tools):
        r = tools["describe_column"]("depth", source_hint="ecotaxa")
        assert "column" in r

    def test_session_id_does_not_crash(self, tools):
        r = tools["describe_column"]("acq_pixel", session_id="test-ses-123")
        assert "column" in r

    def test_object_depth_min_unit_is_m(self, tools):
        r = tools["describe_column"]("object_depth_min")
        if r["unit"] is not None:
            assert "m" in r["unit"].lower()

    def test_no_crash_on_empty_string(self, tools):
        r = tools["describe_column"]("")
        assert "column" in r
        assert r["confidence"] == "unknown"


# ── check_column_for_calc ──────────────────────────────────────────────────────

class TestCheckColumnForCalc:
    def test_concentration_ecotaxa_only_is_infeasible(self, tools, ecotaxa_roles):
        # EcoTaxa alone has no sample_volume role → infeasible
        r = tools["check_column_for_calc"](ecotaxa_roles, "concentration")
        assert r["feasible"] is False

    def test_concentration_missing_sample_volume_role(self, tools, ecotaxa_roles):
        r = tools["check_column_for_calc"](ecotaxa_roles, "concentration")
        assert "sample_volume" in r["missing_roles"]

    def test_blocking_reason_set_when_infeasible(self, tools, ecotaxa_roles):
        r = tools["check_column_for_calc"](ecotaxa_roles, "concentration")
        assert r["blocking_reason"] is not None and len(r["blocking_reason"]) > 0

    def test_role_hints_provided_for_missing_roles(self, tools, ecotaxa_roles):
        r = tools["check_column_for_calc"](ecotaxa_roles, "concentration")
        for missing_role in r["missing_roles"]:
            assert missing_role in r["role_hints"], f"No hint for missing role: {missing_role}"

    def test_empty_roles_dict_is_infeasible(self, tools):
        r = tools["check_column_for_calc"]({"roles": [], "unmatched_columns": []}, "concentration")
        assert r["feasible"] is False
        assert len(r["missing_roles"]) > 0

    def test_result_has_all_required_keys(self, tools, ecotaxa_roles):
        r = tools["check_column_for_calc"](ecotaxa_roles, "concentration")
        required = ["feasible", "required_roles", "present_roles", "missing_roles",
                    "role_hints", "blocking_reason"]
        for key in required:
            assert key in r, f"Missing key: {key}"

    def test_present_roles_subset_of_required(self, tools, ecotaxa_roles):
        r = tools["check_column_for_calc"](ecotaxa_roles, "concentration")
        for role in r["present_roles"]:
            assert role in r["required_roles"]

    def test_missing_roles_subset_of_required(self, tools, ecotaxa_roles):
        r = tools["check_column_for_calc"](ecotaxa_roles, "concentration")
        for role in r["missing_roles"]:
            assert role in r["required_roles"]

    def test_present_plus_missing_covers_required(self, tools, ecotaxa_roles):
        r = tools["check_column_for_calc"](ecotaxa_roles, "concentration")
        covered = set(r["present_roles"]) | set(r["missing_roles"])
        for role in r["required_roles"]:
            assert role in covered

    def test_unknown_calculation_is_infeasible(self, tools):
        r = tools["check_column_for_calc"](_roles("depth"), "calcul_xyz_inconnu_9999")
        assert r["feasible"] is False
        assert r["blocking_reason"] is not None

    def test_feasible_when_all_roles_present(self, tools):
        roles = _roles("sample_volume", "depth", "profile_id")
        r = tools["check_column_for_calc"](roles, "concentration")
        assert r["feasible"] is True
        assert r["blocking_reason"] is None
        assert r["missing_roles"] == []

    def test_any_column_name_works_if_role_is_right(self, tools):
        # Column named "Vol_L" with role sample_volume should make it feasible
        roles = {
            "roles": [
                {"role": "sample_volume", "column": "Vol_L", "confidence": "medium", "evidence": []},
                {"role": "depth",         "column": "Depth_m", "confidence": "medium", "evidence": []},
                {"role": "profile_id",    "column": "Station_ID", "confidence": "medium", "evidence": []},
            ],
            "unmatched_columns": [],
        }
        r = tools["check_column_for_calc"](roles, "concentration")
        assert r["feasible"] is True, "Role-based check should not care about column names"

    def test_feasible_false_means_blocking_reason_set(self, tools):
        r = tools["check_column_for_calc"]({"roles": []}, "concentration")
        if r["feasible"] is False:
            assert r["blocking_reason"] is not None

    def test_session_id_does_not_crash(self, tools):
        r = tools["check_column_for_calc"]({"roles": []}, "concentration", session_id="ses-abc")
        assert "feasible" in r

    def test_concentration_feasible_with_neolabs_volume_roles(self, tools):
        # DEPTH_CALC_NET_FILTERED_VOL and FLOWMETER_CALC_VOL both match "vol" → sample_volume role
        roles = _roles("sample_volume", "depth", "profile_id")
        r = tools["check_column_for_calc"](roles, "concentration")
        assert r["feasible"] is True
        assert r["missing_roles"] == []

    def test_concentration_infeasible_without_neolabs_volume(self, tools):
        # Only taxonomy and date — no volume role
        roles = _roles("taxon", "time", "station")
        r = tools["check_column_for_calc"](roles, "concentration")
        assert r["feasible"] is False
        assert "sample_volume" in r["missing_roles"]


# ── describe_column — NeoLab Taxonomy ─────────────────────────────────────────

class TestDescribeColumnNeoLabs:
    def test_depth_calc_vol_unit_is_m3(self, tools):
        r = tools["describe_column"]("DEPTH_CALC_NET_FILTERED_VOL")
        assert r["unit"] is not None
        assert "m" in r["unit"].lower()

    def test_depth_calc_vol_confidence_not_unknown(self, tools):
        r = tools["describe_column"]("DEPTH_CALC_NET_FILTERED_VOL")
        assert r["confidence"] != "unknown"

    def test_depth_calc_vol_cites_colonnes_labo(self, tools):
        r = tools["describe_column"]("DEPTH_CALC_NET_FILTERED_VOL")
        assert r["rag_doc_ref"] is not None
        assert "colonnes_labo" in r["rag_doc_ref"]

    def test_flowmeter_calc_vol_unit_is_m3(self, tools):
        r = tools["describe_column"]("FLOWMETER_CALC_VOL")
        assert r["unit"] is not None
        assert "m" in r["unit"].lower()

    def test_flowmeter_calc_vol_confidence_not_unknown(self, tools):
        r = tools["describe_column"]("FLOWMETER_CALC_VOL")
        assert r["confidence"] != "unknown"

    def test_c1_abund_depth_vol_confidence_not_unknown(self, tools):
        r = tools["describe_column"]("C1_ABUND (ind./m3 depth vol.)")
        assert r["confidence"] != "unknown"

    def test_c1_abund_depth_vol_unit_is_ind_m3(self, tools):
        r = tools["describe_column"]("C1_ABUND (ind./m3 depth vol.)")
        assert r["unit"] is not None
        unit = r["unit"].lower()
        assert "ind" in unit or "m" in unit

    def test_c1_biomass_depth_vol_confidence_not_unknown(self, tools):
        r = tools["describe_column"]("C1_BIOMASS (µg C m-3 depth vol.)")
        assert r["confidence"] != "unknown"

    def test_c1_biomass_depth_vol_unit_contains_ug_or_c(self, tools):
        r = tools["describe_column"]("C1_BIOMASS (µg C m-3 depth vol.)")
        assert r["unit"] is not None
        unit = r["unit"].lower()
        assert "µg" in unit or "ug" in unit or "c" in unit or "m" in unit

    def test_zooplankton_category_confidence_not_unknown(self, tools):
        r = tools["describe_column"]("ZOOPLANKTON_CATEGORY")
        assert r["confidence"] != "unknown"

    def test_all_stages_abund_depth_vol_confidence_not_unknown(self, tools):
        r = tools["describe_column"]("ALL_STAGES_ABUND (ind./m3 depth vol.)")
        assert r["confidence"] != "unknown"

    def test_nauplius_abund_depth_vol_confidence_not_unknown(self, tools):
        r = tools["describe_column"]("NAUPLIUS_ABUND (ind./m3 depth vol.)")
        assert r["confidence"] != "unknown"

    def test_c1_sample_abund_unit_is_ind(self, tools):
        r = tools["describe_column"]("C1_SAMPLE_ABUND (nbr of ind.)")
        assert r["confidence"] != "unknown"
        if r["unit"] is not None:
            assert "ind" in r["unit"].lower()

    def test_result_has_all_required_keys(self, tools):
        r = tools["describe_column"]("FLOWMETER_CALC_VOL")
        required = ["column", "definition", "unit", "confidence", "critical_notes",
                    "rag_doc_ref", "source_file"]
        for key in required:
            assert key in r, f"Missing key: {key}"

    def test_column_field_echoes_input(self, tools):
        r = tools["describe_column"]("DEPTH_CALC_NET_FILTERED_VOL")
        assert r["column"] == "DEPTH_CALC_NET_FILTERED_VOL"


# ── tool registry integration ──────────────────────────────────────────────────

class TestToolRegistration:
    def test_copepod_columns_tag_registered(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_columns  # noqa: F401
        code = registry.render({"copepod_columns"})
        assert "describe_column" in code
        assert "check_column_for_calc" in code
        assert "required_roles" in code  # role-based, not column-based

    def test_rendered_code_is_executable(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_columns  # noqa: F401
        code = registry.render({"copepod_columns"})
        ns = {}
        exec(code, ns)
        assert "describe_column" in ns
        assert "check_column_for_calc" in ns

    def test_functions_have_docstrings(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_columns  # noqa: F401
        code = registry.render({"copepod_columns"})
        ns = {}
        exec(code, ns)
        assert ns["describe_column"].__doc__ is not None
        assert ns["check_column_for_calc"].__doc__ is not None
