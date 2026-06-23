"""EcoTaxa project schema inspection services.

Produces a typed view of the columns available on a project (sample,
acquisition, object levels), with free fields resolved to human labels
and a flat label index used by downstream tools (e.g. `get_column_distribution`
ambiguity resolution).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Literal

from tools.ecotaxa_client import EcotaxaClient

Level = Literal["sample", "acquisition", "object", "process"]
Kind = Literal["fixed", "free"]
FieldType = Literal["text", "number", "datetime", "unknown"]

_OBJECT_FIXED: list[tuple[str, FieldType]] = [
    ("orig_id", "text"),
    ("latitude", "number"),
    ("longitude", "number"),
    ("depth_min", "number"),
    ("depth_max", "number"),
    ("objdate", "datetime"),
    ("objtime", "text"),
    ("classif_id", "number"),
    ("classif_qual", "text"),
    ("classif_who", "number"),
    ("classif_when", "datetime"),
]

_SAMPLE_FIXED: list[tuple[str, FieldType]] = [
    ("orig_id", "text"),
]

_ACQUISITION_FIXED: list[tuple[str, FieldType]] = [
    ("orig_id", "text"),
    ("instrument", "text"),
]

_PROCESS_FIXED: list[tuple[str, FieldType]] = [
    ("orig_id", "text"),
]

_RAW_FREE_KEY: dict[Level, str] = {
    "sample": "sample_free_cols",
    "acquisition": "acquisition_free_cols",
    "object": "obj_free_cols",
    "process": "process_free_cols",
}

_NORMALIZE_PATTERN = re.compile(r"[\s_\-]+")


def get_project_schema(
    project_id: int,
    *,
    verbose: bool = False,
    include_process: bool = False,
    client: EcotaxaClient | None = None,
) -> dict:
    """Return the typed schema of a project (3 or 4 levels).

    Args:
        project_id: EcoTaxa project ID.
        verbose: When True, expose the internal free-field codes (``t01``,
            ``n02``…). Default hides them — labels stay the user-facing surface.
        include_process: When True, also expose the ``process`` level. Default
            keeps it hidden because it is rarely useful for scientific browsing.
    """
    if client is None:
        client = EcotaxaClient()
        client.login()
    raw = client.get_project(project_id)

    visible_levels: list[Level] = ["sample", "acquisition", "object"]
    if include_process:
        visible_levels.append("process")

    levels = {
        level: {
            "fixed": _fixed_fields(level),
            "free": _free_fields(raw, level, verbose=verbose),
        }
        for level in visible_levels
    }

    labels_index = _build_labels_index(levels)

    return {
        "project_id": int(raw["projid"]),
        "title": str(raw["title"]),
        "instrument": raw.get("instrument"),
        "levels": levels,
        "labels_index": labels_index,
    }


def _fixed_fields(level: Level) -> list[dict]:
    table = {
        "sample": _SAMPLE_FIXED,
        "acquisition": _ACQUISITION_FIXED,
        "object": _OBJECT_FIXED,
        "process": _PROCESS_FIXED,
    }[level]
    return [{"name": name, "type": typ} for name, typ in table]


def _free_fields(raw: dict, level: Level, *, verbose: bool) -> list[dict]:
    mapping: dict[str, str] = raw.get(_RAW_FREE_KEY[level]) or {}
    fields = []
    for label, code in sorted(mapping.items()):
        entry: dict = {"label": label, "type": _type_from_code(code)}
        if verbose:
            entry["code"] = code
        fields.append(entry)
    return fields


def _type_from_code(code: str) -> FieldType:
    if not code:
        return "unknown"
    head = code[0].lower()
    if head == "n":
        return "number"
    if head == "t":
        return "text"
    return "unknown"


def _build_labels_index(levels: dict) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = defaultdict(list)
    for level, content in levels.items():
        for field in content["fixed"]:
            index[_normalize_label(field["name"])].append(
                {"level": level, "kind": "fixed", "type": field["type"]}
            )
        for field in content["free"]:
            index[_normalize_label(field["label"])].append(
                {"level": level, "kind": "free", "type": field["type"]}
            )
    return dict(index)


def _normalize_label(label: str) -> str:
    return _NORMALIZE_PATTERN.sub("", label).lower()
