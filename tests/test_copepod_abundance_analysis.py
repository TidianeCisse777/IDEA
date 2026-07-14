import numpy as np
import pandas as pd
import pytest


def _canonical_bins() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sample_id": ["RA18", "RA18", "RA02"],
            "depth_bin": [212.5, 217.5, 512.5],
            "abundance_ind_L": [0.01, 0.0, 0.02],
            "abundance_ind_m3": [10.0, 0.0, 20.0],
            "amundsen_temperature": [-1.2, -1.1, -0.8],
            "canonical_method_version": ["copepod-sample-depth-v1"] * 3,
        }
    )


def test_default_correlation_frame_keeps_sampled_zero_bins():
    from core.copepod_abundance_analysis import prepare_environment_correlation

    result = prepare_environment_correlation(
        _canonical_bins(),
        ("amundsen_temperature",),
    )

    assert list(result.columns) == [
        "sample_id",
        "depth_bin",
        "abundance_ind_L",
        "amundsen_temperature",
    ]
    assert result["abundance_ind_L"].tolist() == [0.01, 0.0, 0.02]
    assert result.attrs == {
        "n_initial": 3,
        "n_retained": 3,
        "n_zero_abundance": 1,
        "n_missing_environment": 0,
        "presence_only": False,
        "abundance_column": "abundance_ind_L",
    }


def test_presence_only_explicitly_removes_zero_bins():
    from core.copepod_abundance_analysis import prepare_environment_correlation

    result = prepare_environment_correlation(
        _canonical_bins(),
        ("amundsen_temperature",),
        presence_only=True,
    )

    assert result["abundance_ind_L"].tolist() == [0.01, 0.02]
    assert result.attrs["n_initial"] == 3
    assert result.attrs["n_retained"] == 2
    assert result.attrs["n_zero_abundance"] == 0
    assert result.attrs["presence_only"] is True


def test_drops_only_missing_environment_and_reports_it():
    from core.copepod_abundance_analysis import prepare_environment_correlation

    canonical = _canonical_bins()
    canonical["amundsen_temperature"] = canonical["amundsen_temperature"].astype("object")
    canonical.loc[2, "amundsen_temperature"] = "not-numeric"
    result = prepare_environment_correlation(
        canonical,
        ("amundsen_temperature",),
    )

    assert result["abundance_ind_L"].tolist() == [0.01, 0.0]
    assert result.attrs["n_initial"] == 3
    assert result.attrs["n_retained"] == 2
    assert result.attrs["n_missing_environment"] == 1
    assert result.attrs["n_zero_abundance"] == 1


def test_refuses_non_canonical_table():
    from core.copepod_abundance_analysis import prepare_environment_correlation

    canonical = _canonical_bins().drop(columns="canonical_method_version")
    with pytest.raises(ValueError, match="canonical_method_version"):
        prepare_environment_correlation(canonical, ("amundsen_temperature",))


def test_refuses_wrong_canonical_version():
    from core.copepod_abundance_analysis import prepare_environment_correlation

    canonical = _canonical_bins()
    canonical["canonical_method_version"] = "other"
    with pytest.raises(ValueError, match="copepod-sample-depth-v1"):
        prepare_environment_correlation(canonical, ("amundsen_temperature",))


def test_refuses_unknown_abundance_unit():
    from core.copepod_abundance_analysis import prepare_environment_correlation

    with pytest.raises(ValueError, match="abundance"):
        prepare_environment_correlation(
            _canonical_bins(),
            ("amundsen_temperature",),
            abundance_column="abundance",
        )


@pytest.mark.parametrize("invalid", [-0.1, np.nan, np.inf, "not-numeric"])
def test_refuses_invalid_abundance(invalid):
    from core.copepod_abundance_analysis import prepare_environment_correlation

    canonical = _canonical_bins()
    canonical["abundance_ind_L"] = canonical["abundance_ind_L"].astype("object")
    canonical.loc[0, "abundance_ind_L"] = invalid

    with pytest.raises(ValueError, match="abundance_ind_L"):
        prepare_environment_correlation(canonical, ("amundsen_temperature",))


def test_refuses_empty_environment_column_list():
    from core.copepod_abundance_analysis import prepare_environment_correlation

    with pytest.raises(ValueError, match="environnement"):
        prepare_environment_correlation(_canonical_bins(), ())


@pytest.mark.parametrize("missing", ["sample_id", "depth_bin", "amundsen_temperature"])
def test_refuses_missing_required_column(missing: str):
    from core.copepod_abundance_analysis import prepare_environment_correlation

    canonical = _canonical_bins().drop(columns=missing)
    with pytest.raises(ValueError, match=missing):
        prepare_environment_correlation(canonical, ("amundsen_temperature",))


def test_compute_m5_uses_zero_inclusive_surface_and_bottom_bins():
    from core.copepod_abundance_analysis import compute_m5

    canonical = _canonical_bins()
    canonical.loc[len(canonical)] = {
        "sample_id": "RA18",
        "depth_bin": 12.5,
        "abundance_ind_L": 0.02,
        "abundance_ind_m3": 20.0,
        "amundsen_temperature": -1.3,
        "canonical_method_version": "copepod-sample-depth-v1",
    }

    result = compute_m5(canonical, sample_id="RA18")

    assert result == pytest.approx(
        {
            "m5_cop_dens_ind_per_L": 0.0125,
            "surface_mean_ind_L": 0.02,
            "bottom_mean_ind_L": 0.005,
            "n_surface_bins": 1,
            "n_bottom_bins": 2,
            "max_depth_bin": 217.5,
        }
    )


def test_compute_m5_refuses_missing_surface_coverage():
    from core.copepod_abundance_analysis import compute_m5

    with pytest.raises(ValueError, match=r"RA18.*0.?50"):
        compute_m5(_canonical_bins(), sample_id="RA18")
