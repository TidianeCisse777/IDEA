import pytest


def test_catalog_contains_copod_recommendation_and_extended_environmental_variables():
    from core.bio_oracle_catalog import list_catalog_variables

    variables = {item["key"]: item for item in list_catalog_variables()}

    assert {
        "temperature",
        "salinity",
        "oxygen",
        "nitrate",
        "phosphate",
        "silicate",
        "chlorophyll",
        "primary_productivity",
        "mixed_layer_depth",
        "par",
        "diffuse_attenuation",
    } <= variables.keys()
    assert variables["temperature"]["recommended_for_copepods"] is True
    assert variables["sea_water_speed"]["recommended_for_copepods"] is False
    assert variables["primary_productivity"]["erddap_var"] == "phyc"
    assert variables["mixed_layer_depth"]["erddap_var"] == "mlotst"
    assert variables["cloud_cover"]["erddap_var"] == "clt"
    assert variables["sea_ice_cover"]["erddap_var"] == "siconc"
    assert variables["sea_ice_thickness"]["erddap_var"] == "sithick"
    assert variables["diffuse_attenuation"]["erddap_var"] == "kdpar_mean"
    assert "surface" in variables["temperature"]["layers"]
    assert "mean" in variables["temperature"]["statistics"]


def test_catalog_resolves_french_alias_and_layer_statistics():
    from core.bio_oracle_catalog import (
        resolve_catalog_statistic,
        resolve_catalog_variable,
    )

    variable = resolve_catalog_variable("température")

    assert variable.key == "temperature"
    assert variable.erddap_var == "thetao"
    assert resolve_catalog_statistic(variable, "moyenne") == "mean"
    assert resolve_catalog_statistic(variable, "maximum") == "max"


def test_validate_selection_returns_canonical_explicit_request():
    from core.bio_oracle_catalog import validate_enrichment_selection

    result = validate_enrichment_selection(
        variables=["température", "phosphate"],
        scenarios=["SSP2-4.5"],
        depth_layer="benthic_mean",
        statistic="max",
        target_year=2050,
    )

    assert result["ok"] is True
    assert result["variables"] == ["temperature", "phosphate"]
    assert result["scenarios"] == ["ssp245"]
    assert result["depth_layer"] == "depthmean"
    assert result["statistic"] == "max"
    assert result["target_year"] == 2050


@pytest.mark.parametrize(
    "kwargs, missing",
    [
        ({"variables": None, "scenarios": ["baseline"], "depth_layer": "surface", "statistic": "mean"}, "variables"),
        ({"variables": ["temperature"], "scenarios": None, "depth_layer": "surface", "statistic": "mean"}, "scenarios"),
        ({"variables": ["temperature"], "scenarios": ["baseline"], "depth_layer": None, "statistic": "mean"}, "depth_layer"),
        ({"variables": ["temperature"], "scenarios": ["baseline"], "depth_layer": "surface", "statistic": None}, "statistic"),
    ],
)
def test_validate_selection_blocks_missing_explicit_choices(kwargs, missing):
    from core.bio_oracle_catalog import validate_enrichment_selection

    result = validate_enrichment_selection(target_year=None, **kwargs)

    assert result["ok"] is False
    assert missing in result["missing"]
    assert result["remote_io"] is False


def test_validate_selection_requires_year_for_ssp():
    from core.bio_oracle_catalog import validate_enrichment_selection

    result = validate_enrichment_selection(
        variables=["temperature"],
        scenarios=["SSP5-8.5"],
        depth_layer="surface",
        statistic="mean",
        target_year=None,
    )

    assert result["ok"] is False
    assert result["code"] == "target_year_required"
    assert result["remote_io"] is False


def test_validate_selection_rejects_unknown_variable_and_invalid_statistic():
    from core.bio_oracle_catalog import validate_enrichment_selection

    unknown = validate_enrichment_selection(
        variables=["unknown_variable"],
        scenarios=["baseline"],
        depth_layer="surface",
        statistic="mean",
        target_year=None,
    )
    invalid_stat = validate_enrichment_selection(
        variables=["temperature"],
        scenarios=["baseline"],
        depth_layer="surface",
        statistic="bogus",
        target_year=None,
    )

    assert unknown["ok"] is False
    assert unknown["code"] == "unknown_variable"
    assert invalid_stat["ok"] is False
    assert invalid_stat["code"] == "statistic_not_available"
