import pandas as pd
import pytest


def _table(**extra) -> pd.DataFrame:
    data = {"object_lat": [74.0], "object_lon": [-80.0], **extra}
    return pd.DataFrame(data)


def test_resolves_object_date_before_sampledatetime():
    from core.environment_resolver import resolve_environment_schema

    schema = resolve_environment_schema(
        _table(object_date=["2018-08-01"], sampledatetime=["2018-08-02"])
    )

    assert schema.time_column == "object_date"
    assert schema.resolution["time"] == "detected"


def test_falls_back_to_sampledatetime():
    from core.environment_resolver import resolve_environment_schema

    schema = resolve_environment_schema(_table(sampledatetime=["2018-08-02"]))

    assert schema.time_column == "sampledatetime"


def test_explicit_overrides_resolve_case_insensitively():
    from core.environment_resolver import resolve_environment_schema

    dataframe = pd.DataFrame(
        {"Latitude": [74.0], "Longitude": [-80.0], "Object_Date": ["2018-08-01"]}
    )
    schema = resolve_environment_schema(
        dataframe,
        latitude_column="LATITUDE",
        longitude_column="longitude",
        time_column="OBJECT_DATE",
    )

    assert schema.latitude_column == "Latitude"
    assert schema.longitude_column == "Longitude"
    assert schema.time_column == "Object_Date"
    assert schema.resolution == {
        "latitude": "explicit",
        "longitude": "explicit",
        "time": "explicit",
        "depth": "detected",
    }


def test_refuses_missing_explicit_override():
    from core.environment_resolver import resolve_environment_schema

    with pytest.raises(ValueError, match=r"time.*sampledatetime.*object_date"):
        resolve_environment_schema(
            _table(object_date=["2018-08-01"]),
            time_column="sampledatetime",
        )


def test_refuses_missing_required_time():
    from core.environment_resolver import resolve_environment_schema

    with pytest.raises(ValueError, match="time"):
        resolve_environment_schema(_table())


def test_optional_depth_can_be_unresolved_and_serialized():
    from core.environment_resolver import resolve_environment_schema

    schema = resolve_environment_schema(_table(object_date=["2018-08-01"]))

    assert schema.depth_column is None
    assert schema.to_dict()["columns"] == {
        "latitude": "object_lat",
        "longitude": "object_lon",
        "time": "object_date",
        "depth": None,
    }
