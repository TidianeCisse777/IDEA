"""Cross-project schema comparison service.

Resolves which columns are shared across N projects, which conflict on
type or level, and which are unique to each project. Used as the
pre-flight check before exporting multiple projects together.
"""

from __future__ import annotations

import re
from collections import defaultdict

from core.ecotaxa_browser.schema import get_project_schema

_NORMALIZE_PATTERN = re.compile(r"[\s_\-]+")
_WARNING_PAIRS = frozenset({frozenset({"text", "datetime"})})


def compare_project_schemas(project_ids: list[int]) -> dict:
    """Compare typed schemas across projects and surface compatibility risks."""
    if len(project_ids) < 2:
        raise ValueError("compare_project_schemas requires at least 2 project_ids")

    schemas = {pid: get_project_schema(pid) for pid in project_ids}

    # Index every column by normalized label.
    # value: { (project_id, level, kind): {"raw": str, "type": str} }
    by_label: dict[str, dict[tuple[int, str, str], dict]] = defaultdict(dict)
    raw_by_project: dict[int, set[str]] = {pid: set() for pid in project_ids}

    for pid, schema in schemas.items():
        for level, content in schema["levels"].items():
            for entry in content["fixed"]:
                norm = _normalize(entry["name"])
                by_label[norm][(pid, level, "fixed")] = {
                    "raw": entry["name"],
                    "type": entry["type"],
                }
                raw_by_project[pid].add(entry["name"])
            for entry in content["free"]:
                norm = _normalize(entry["label"])
                by_label[norm][(pid, level, "free")] = {
                    "raw": entry["label"],
                    "type": entry["type"],
                }
                raw_by_project[pid].add(entry["label"])

    common_columns: list[dict] = []
    type_conflicts: list[dict] = []
    level_conflicts: list[dict] = []

    for label, entries in sorted(by_label.items()):
        projects_seen = {pid for pid, _, _ in entries.keys()}
        if len(projects_seen) < 2:
            continue

        common_columns.append(
            {
                "label_normalized": label,
                "matched_in": [
                    {
                        "project_id": pid,
                        "level": level,
                        "kind": kind,
                        "raw_label": value["raw"],
                        "type": value["type"],
                    }
                    for (pid, level, kind), value in sorted(entries.items())
                ],
            }
        )

        types_by_project = defaultdict(list)
        for (pid, _, _), value in entries.items():
            types_by_project[value["type"]].append(pid)
        if len(types_by_project) > 1:
            severity = (
                "warning"
                if frozenset(types_by_project) in _WARNING_PAIRS
                else "blocker"
            )
            type_conflicts.append(
                {
                    "label_normalized": label,
                    "severity": severity,
                    "types_seen": {
                        typ: sorted(pids) for typ, pids in types_by_project.items()
                    },
                }
            )

        # A level conflict only exists when different projects place this
        # column at different sets of levels. Same-name fixed fields that
        # appear at every level in every project (e.g. orig_id) are not a
        # conflict — they're the EcoTaxa structural fields.
        levels_per_project: dict[int, set[str]] = defaultdict(set)
        for (pid, level, _), _ in entries.items():
            levels_per_project[pid].add(level)
        level_sets = {frozenset(v) for v in levels_per_project.values()}
        if len(level_sets) > 1:
            levels_by_project = defaultdict(list)
            for (pid, level, _), _ in entries.items():
                levels_by_project[level].append(pid)
            level_conflicts.append(
                {
                    "label_normalized": label,
                    "levels_seen": {
                        level: sorted(pids) for level, pids in levels_by_project.items()
                    },
                }
            )

    common_normalized = {c["label_normalized"] for c in common_columns}
    unique_to_project = {
        str(pid): sorted(
            raw
            for raw in raw_by_project[pid]
            if _normalize(raw) not in common_normalized
        )
        for pid in project_ids
    }

    return {
        "project_ids": list(project_ids),
        "common_columns": common_columns,
        "type_conflicts": type_conflicts,
        "level_conflicts": level_conflicts,
        "unique_to_project": unique_to_project,
    }


def _normalize(label: str) -> str:
    return _NORMALIZE_PATTERN.sub("", label).lower()
