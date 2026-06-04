"""
Tests for UVP MCA metric input resolution.

The resolver is intentionally separate from metric calculation: it only binds
semantic roles to concrete columns and reports whether m5/m6 can be computed.
"""
import os
from pathlib import Path

import pandas as pd
import pytest

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

ENRICHED_UVP_OBJECTS = (
    _SPECS_ROOT
    / "data_exploration/examples_tsv/uvp_amundsen_1165_105_enriched_nearest_depth.tsv"
)


@pytest.fixture(scope="module")
def tools():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_data  # noqa: F401 - triggers registration
    from core.tool_registry.tools import copepod_uvp_metrics  # noqa: F401 - triggers registration

    code = registry.render({"copepod_data", "copepod_uvp_metrics"})
    ns = {}
    exec(code, ns)
    return ns


class TestResolveUvpM5M6Inputs:
    def test_resolves_joined_ecotaxa_columns_for_m5_but_blocks_m6_without_acq_pixel(self, tools):
        inspected = tools["inspect_file"](str(ENRICHED_UVP_OBJECTS))

        resolved = tools["resolve_uvp_m5_m6_inputs"](inspected["columns"], inspected["metadata"])

        assert resolved["method"] == "uvp_mca_m5_m6"
        assert resolved["roles"]["profile_id"]["column"] == "sample_id"
        assert resolved["roles"]["taxon"]["column"] == "taxon"
        assert resolved["roles"]["depth_bin"]["column"] == "ecopart_depth"
        assert resolved["roles"]["sample_volume_l"]["column"] == "ecopart_sampled_volume_l"
        assert resolved["roles"]["large_copepod_length_pixels"]["column"] == "fre_major"

        assert resolved["metrics"]["m5"]["feasible"] is True
        assert resolved["metrics"]["m5"]["missing_roles"] == []
        assert resolved["metrics"]["m6"]["feasible"] is False
        assert resolved["metrics"]["m6"]["missing_roles"] == ["pixel_size_um"]

    def test_resolves_m6_when_major_and_acq_pixel_are_present(self, tools):
        columns = [
            {"name": "sample_id"},
            {"name": "depth_bin"},
            {"name": "sampled_volume"},
            {"name": "object_annotation_category"},
            {"name": "object_major"},
            {"name": "acq_pixel"},
        ]

        resolved = tools["resolve_uvp_m5_m6_inputs"](columns)

        assert resolved["metrics"]["m5"]["feasible"] is True
        assert resolved["metrics"]["m6"]["feasible"] is True
        assert resolved["roles"]["large_copepod_length_pixels"]["column"] == "object_major"
        assert resolved["roles"]["pixel_size_um"]["column"] == "acq_pixel"
        assert resolved["calculation_contract"]["m6_size_formula"] == (
            "copepod_size_um = object_major_or_fre_major * acq_pixel"
        )

    def test_derives_depth_bin_from_object_depth_only_when_no_depth_bin_exists(self, tools):
        columns = [
            {"name": "sample_id"},
            {"name": "object_depth"},
            {"name": "sampled_volume"},
            {"name": "taxon"},
        ]

        resolved = tools["resolve_uvp_m5_m6_inputs"](columns)

        assert resolved["metrics"]["m5"]["feasible"] is True
        assert resolved["roles"]["depth_bin"]["column"] == "object_depth"
        assert resolved["roles"]["depth_bin"]["derivation"] == "floor(depth / 5) * 5 + 2.5"

    def test_does_not_accept_size_category_label_as_m6_size_source(self, tools):
        columns = [
            {"name": "sample_id"},
            {"name": "depth_bin"},
            {"name": "sampled_volume"},
            {"name": "taxon"},
            {"name": "taxon_size_category"},
            {"name": "acq_pixel"},
        ]

        resolved = tools["resolve_uvp_m5_m6_inputs"](columns)

        assert resolved["metrics"]["m5"]["feasible"] is True
        assert resolved["metrics"]["m6"]["feasible"] is False
        assert "large_copepod_length_pixels" in resolved["metrics"]["m6"]["missing_roles"]
        assert "taxon_size_category" in resolved["ignored_for_m6_size"]


class TestCalculateUvpM5M6:
    def test_calculates_m5_and_m6_from_resolved_semantic_roles(self, tools):
        rows = [
            {
                "sample_id": "cast-a",
                "station": "S1",
                "lat": 50.0,
                "lon": -60.0,
                "depth_bin": 2.5,
                "sampled_volume": 10.0,
                "category": "Copepoda<Multicrustacea",
                "object_major": 25.0,
                "acq_pixel": 100.0,
            },
            {
                "sample_id": "cast-a",
                "station": "S1",
                "lat": 50.0,
                "lon": -60.0,
                "depth_bin": 2.5,
                "sampled_volume": 10.0,
                "category": "Calanus",
                "object_major": 10.0,
                "acq_pixel": 100.0,
            },
            {
                "sample_id": "cast-a",
                "station": "S1",
                "lat": 50.0,
                "lon": -60.0,
                "depth_bin": 2.5,
                "sampled_volume": 10.0,
                "category": "detritus",
                "object_major": 40.0,
                "acq_pixel": 100.0,
            },
            {
                "sample_id": "cast-a",
                "station": "S1",
                "lat": 50.0,
                "lon": -60.0,
                "depth_bin": 47.5,
                "sampled_volume": 20.0,
                "category": "Metridia",
                "object_major": 20.0,
                "acq_pixel": 100.0,
            },
            {
                "sample_id": "cast-a",
                "station": "S1",
                "lat": 50.0,
                "lon": -60.0,
                "depth_bin": 102.5,
                "sampled_volume": 10.0,
                "category": "Paraeuchaeta",
                "object_major": 21.0,
                "acq_pixel": 100.0,
            },
        ]

        result = tools["calculate_uvp_m5_m6"](rows)

        assert result["status"] == "ok"
        assert result["resolved"]["metrics"]["m5"]["feasible"] is True
        assert result["resolved"]["metrics"]["m6"]["feasible"] is True
        assert len(result["records"]) == 1
        record = result["records"][0]
        assert record["sample_id"] == "cast-a"
        assert record["max_depth"] == 102.5
        assert record["m5_surface_mean_cop_dens"] == pytest.approx(0.125)
        assert record["m5_bottom_mean_cop_dens"] == pytest.approx(0.1)
        assert record["m5_cop_dens"] == pytest.approx(0.1125)
        assert record["m6_surface_mean_largecop_dens"] == pytest.approx(0.1)
        assert record["m6_bottom_mean_largecop_dens"] == pytest.approx(0.1)
        assert record["m6_largecop_dens"] == pytest.approx(0.1)

    def test_blocks_m6_but_still_calculates_m5_when_acq_pixel_is_missing(self, tools):
        rows = [
            {
                "sample_id": "cast-a",
                "depth_bin": 2.5,
                "sampled_volume": 10.0,
                "category": "Calanus",
                "object_major": 25.0,
            }
        ]

        result = tools["calculate_uvp_m5_m6"](rows)

        assert result["status"] == "partial"
        assert result["resolved"]["metrics"]["m5"]["feasible"] is True
        assert result["resolved"]["metrics"]["m6"]["feasible"] is False
        assert result["records"][0]["m5_cop_dens"] == pytest.approx(0.1)
        assert result["records"][0]["m6_largecop_dens"] is None
        assert "pixel_size_um" in result["resolved"]["metrics"]["m6"]["missing_roles"]

    def test_blocks_all_metrics_when_volume_is_missing(self, tools):
        rows = [
            {
                "sample_id": "cast-a",
                "depth_bin": 2.5,
                "category": "Calanus",
                "object_major": 25.0,
                "acq_pixel": 100.0,
            }
        ]

        result = tools["calculate_uvp_m5_m6"](rows)

        assert result["status"] == "blocked"
        assert result["records"] == []
        assert result["resolved"]["metrics"]["m5"]["feasible"] is False
        assert result["resolved"]["metrics"]["m6"]["feasible"] is False


class TestUvpM5M6Integration:
    def test_inspect_resolve_then_calculate_on_real_joined_ecotaxa_file(self, tools):
        inspected = tools["inspect_file"](str(ENRICHED_UVP_OBJECTS))
        resolved = tools["resolve_uvp_m5_m6_inputs"](inspected["columns"], inspected["metadata"])
        df = pd.read_csv(ENRICHED_UVP_OBJECTS, sep="\t")

        result = tools["calculate_uvp_m5_m6"](df, resolved_inputs=resolved)

        assert result["status"] == "partial"
        assert result["resolved"] == resolved
        assert result["resolved"]["metrics"]["m5"]["feasible"] is True
        assert result["resolved"]["metrics"]["m6"]["feasible"] is False
        assert result["resolved"]["metrics"]["m6"]["missing_roles"] == ["pixel_size_um"]
        assert len(result["records"]) == 1
        record = result["records"][0]
        assert record["sample_id"] == 77324
        assert record["m5_cop_dens"] == pytest.approx(0.03995822623273603)
        assert record["m6_largecop_dens"] is None
