"""TDD — core/ecotaxa_browser/compare_schemas.py."""

from unittest.mock import patch


def _schema(project_id, *, sample_free=None, object_free=None, object_fixed_extra=None):
    sample_free = sample_free or {}
    object_free = object_free or {}
    object_fixed_extra = object_fixed_extra or []

    return {
        "project_id": project_id,
        "title": f"Project {project_id}",
        "instrument": "UVP5",
        "levels": {
            "sample": {
                "fixed": [{"name": "orig_id", "type": "text"}],
                "free": [
                    {"label": label, "type": typ}
                    for label, typ in sample_free.items()
                ],
            },
            "acquisition": {
                "fixed": [
                    {"name": "orig_id", "type": "text"},
                    {"name": "instrument", "type": "text"},
                ],
                "free": [],
            },
            "object": {
                "fixed": (
                    [
                        {"name": "depth_min", "type": "number"},
                        {"name": "classif_qual", "type": "text"},
                    ]
                    + object_fixed_extra
                ),
                "free": [
                    {"label": label, "type": typ}
                    for label, typ in object_free.items()
                ],
            },
        },
        "labels_index": {},  # not consulted by compare logic
    }


def _patched(*schemas):
    schema_by_id = {s["project_id"]: s for s in schemas}
    return patch(
        "core.ecotaxa_browser.compare_schemas.get_project_schema",
        side_effect=lambda project_id, **_: schema_by_id[project_id],
    )


def test_compare_detects_common_columns_via_normalized_label():
    from core.ecotaxa_browser.compare_schemas import compare_project_schemas

    a = _schema(1, sample_free={"Station Name": "text"})
    b = _schema(2, sample_free={"station_name": "text"})

    with _patched(a, b):
        result = compare_project_schemas([1, 2])

    common = {c["label_normalized"]: c for c in result["common_columns"]}
    assert "stationname" in common
    matched_projects = sorted(m["project_id"] for m in common["stationname"]["matched_in"])
    assert matched_projects == [1, 2]


def test_compare_detects_type_conflict_with_blocker_severity():
    from core.ecotaxa_browser.compare_schemas import compare_project_schemas

    a = _schema(1, sample_free={"depth": "number"})
    b = _schema(2, sample_free={"depth": "text"})

    with _patched(a, b):
        result = compare_project_schemas([1, 2])

    conflicts = {c["label_normalized"]: c for c in result["type_conflicts"]}
    assert "depth" in conflicts
    assert conflicts["depth"]["severity"] == "blocker"
    assert set(conflicts["depth"]["types_seen"].keys()) == {"number", "text"}


def test_compare_marks_text_vs_datetime_as_warning():
    from core.ecotaxa_browser.compare_schemas import compare_project_schemas

    a = _schema(1, sample_free={"cruise_date": "text"})
    b = _schema(2, sample_free={"cruise_date": "datetime"})

    with _patched(a, b):
        result = compare_project_schemas([1, 2])

    conflicts = {c["label_normalized"]: c for c in result["type_conflicts"]}
    assert conflicts["cruisedate"]["severity"] == "warning"


def test_compare_detects_level_conflict():
    from core.ecotaxa_browser.compare_schemas import compare_project_schemas

    a = _schema(1, sample_free={"depth": "number"})
    b = _schema(2, object_free={"depth": "number"})

    with _patched(a, b):
        result = compare_project_schemas([1, 2])

    conflicts = {c["label_normalized"]: c for c in result["level_conflicts"]}
    assert "depth" in conflicts
    levels = set(conflicts["depth"]["levels_seen"].keys())
    assert levels == {"sample", "object"}


def test_compare_lists_unique_columns_per_project():
    from core.ecotaxa_browser.compare_schemas import compare_project_schemas

    a = _schema(1, sample_free={"transect": "text"})
    b = _schema(2, sample_free={"cruise_leg": "text", "weather": "text"})

    with _patched(a, b):
        result = compare_project_schemas([1, 2])

    assert sorted(result["unique_to_project"]["1"]) == ["transect"]
    assert sorted(result["unique_to_project"]["2"]) == ["cruise_leg", "weather"]


def test_compare_handles_shared_fixed_fields_without_conflict():
    """orig_id is fixed in all projects — it should be common, not conflicting."""
    from core.ecotaxa_browser.compare_schemas import compare_project_schemas

    a = _schema(1)
    b = _schema(2)

    with _patched(a, b):
        result = compare_project_schemas([1, 2])

    common_labels = {c["label_normalized"] for c in result["common_columns"]}
    assert "origid" in common_labels
    assert "depthmin" in common_labels
    assert "classifqual" in common_labels
    assert result["type_conflicts"] == []
    assert result["level_conflicts"] == []
