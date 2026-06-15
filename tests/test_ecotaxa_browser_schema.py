"""TDD — core/ecotaxa_browser/schema.py."""

from unittest.mock import patch


_PROJECT_RAW = {
    "projid": 42,
    "title": "UVP5 GREEN EDGE Ice Camp 2015",
    "instrument": "UVP5SD",
    "objcount": 84668.0,
    "pctvalidated": 100.0,
    "pctclassified": 100.0,
    "sample_free_cols": {"profileid": "t01", "stationid": "t04"},
    "acquisition_free_cols": {"pixel": "n05", "exposure": "n17"},
    "obj_free_cols": {"area": "n01", "mean": "n02", "comment": "t03"},
    "process_free_cols": {"software": "t01"},
}


def _patched_get_project_schema():
    from core.ecotaxa_browser.schema import get_project_schema

    with patch("core.ecotaxa_browser.schema.EcotaxaClient") as client_class:
        client = client_class.return_value
        client.get_project.return_value = _PROJECT_RAW
        return get_project_schema(42)


def test_get_project_schema_returns_three_levels_by_default():
    schema = _patched_get_project_schema()

    assert set(schema["levels"]) == {"sample", "acquisition", "object"}
    assert "process" not in schema["levels"]


def test_get_project_schema_top_metadata():
    schema = _patched_get_project_schema()

    assert schema["project_id"] == 42
    assert schema["title"].startswith("UVP5 GREEN EDGE")
    assert schema["instrument"] == "UVP5SD"


def test_get_project_schema_includes_process_when_requested():
    from core.ecotaxa_browser.schema import get_project_schema

    with patch("core.ecotaxa_browser.schema.EcotaxaClient") as client_class:
        client_class.return_value.get_project.return_value = _PROJECT_RAW
        schema = get_project_schema(42, include_process=True)

    assert "process" in schema["levels"]
    assert schema["levels"]["process"]["free"][0]["label"] == "software"


def test_free_field_types_resolved_from_code_prefix():
    schema = _patched_get_project_schema()

    sample_free = {f["label"]: f["type"] for f in schema["levels"]["sample"]["free"]}
    assert sample_free == {"profileid": "text", "stationid": "text"}

    object_free = {f["label"]: f["type"] for f in schema["levels"]["object"]["free"]}
    assert object_free == {"area": "number", "mean": "number", "comment": "text"}


def test_free_fields_hide_codes_unless_verbose():
    schema = _patched_get_project_schema()
    sample_free = schema["levels"]["sample"]["free"]

    assert "code" not in sample_free[0]


def test_free_fields_expose_codes_when_verbose_true():
    from core.ecotaxa_browser.schema import get_project_schema

    with patch("core.ecotaxa_browser.schema.EcotaxaClient") as client_class:
        client_class.return_value.get_project.return_value = _PROJECT_RAW
        schema = get_project_schema(42, verbose=True)

    sample_free = {f["label"]: f["code"] for f in schema["levels"]["sample"]["free"]}
    assert sample_free == {"profileid": "t01", "stationid": "t04"}


def test_object_fixed_fields_include_geo_and_classification():
    schema = _patched_get_project_schema()
    object_fixed = {f["name"]: f["type"] for f in schema["levels"]["object"]["fixed"]}

    assert object_fixed["latitude"] == "number"
    assert object_fixed["longitude"] == "number"
    assert object_fixed["depth_min"] == "number"
    assert object_fixed["objdate"] == "datetime"
    assert object_fixed["classif_qual"] == "text"


def test_labels_index_resolves_unambiguous_label_to_single_match():
    schema = _patched_get_project_schema()

    matches = schema["labels_index"]["area"]
    assert matches == [
        {"level": "object", "kind": "free", "type": "number"}
    ]


def test_labels_index_normalises_case_and_separators():
    raw = dict(_PROJECT_RAW)
    raw["sample_free_cols"] = {"Station Name": "t04"}
    raw["acquisition_free_cols"] = {"station_name": "t12"}

    from core.ecotaxa_browser.schema import get_project_schema

    with patch("core.ecotaxa_browser.schema.EcotaxaClient") as client_class:
        client_class.return_value.get_project.return_value = raw
        schema = get_project_schema(42)

    matches = schema["labels_index"]["stationname"]
    levels = sorted(m["level"] for m in matches)
    assert levels == ["acquisition", "sample"]


def test_labels_index_lists_both_levels_for_ambiguous_free_field():
    raw = dict(_PROJECT_RAW)
    raw["sample_free_cols"] = {"depth": "n02"}
    raw["acquisition_free_cols"] = {"depth": "n08"}

    from core.ecotaxa_browser.schema import get_project_schema

    with patch("core.ecotaxa_browser.schema.EcotaxaClient") as client_class:
        client_class.return_value.get_project.return_value = raw
        schema = get_project_schema(42)

    matches = schema["labels_index"]["depth"]
    levels = sorted(m["level"] for m in matches)
    assert levels == ["acquisition", "sample"]
    kinds = {m["kind"] for m in matches}
    assert kinds == {"free"}
