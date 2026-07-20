"""Pure sample-level aggregation of EcoTaxa object metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
import math


OBJECT_METADATA_FIELDS = ",".join((
    "obj.objdate",
    "obj.objtime",
    "obj.depth_min",
    "obj.depth_max",
))


def new_metadata_aggregate() -> dict[str, object]:
    """Create an empty aggregate for one EcoTaxa sample metadata scan."""
    return {
        "date_min": None,
        "date_max": None,
        "time_min": None,
        "time_max": None,
        "datetime_min": None,
        "datetime_max": None,
        "depth_min": None,
        "depth_max": None,
        "missing_date_count": 0,
        "missing_time_count": 0,
        "missing_depth_min_count": 0,
        "missing_depth_max_count": 0,
        "metadata_objects_scanned": 0,
        "valid_date_count": 0,
    }


def _normalized_date(value: object) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        return None


def _normalized_time(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = time.fromisoformat(text).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None
    return parsed.isoformat(timespec="seconds")


def _finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _extend(aggregate: dict[str, object], prefix: str, value: object) -> None:
    if value is None:
        return
    minimum = f"{prefix}_min"
    maximum = f"{prefix}_max"
    if aggregate[minimum] is None or value < aggregate[minimum]:
        aggregate[minimum] = value
    if aggregate[maximum] is None or value > aggregate[maximum]:
        aggregate[maximum] = value


def accumulate_metadata_row(
    aggregate: dict[str, object], row: Sequence[object]
) -> None:
    """Accumulate date, time, and depth envelopes from one metadata row."""
    if len(row) < 4:
        raise ValueError("EcoTaxa metadata row must contain date, time and two depths")
    raw_date, raw_time, raw_depth_min, raw_depth_max = row[:4]
    normalized_date = _normalized_date(raw_date)
    normalized_time = _normalized_time(raw_time)
    depth_min = _finite_float(raw_depth_min)
    depth_max = _finite_float(raw_depth_max)

    aggregate["metadata_objects_scanned"] += 1
    if normalized_date is None:
        aggregate["missing_date_count"] += 1
    else:
        aggregate["valid_date_count"] += 1
        _extend(aggregate, "date", normalized_date)
    if normalized_time is None:
        aggregate["missing_time_count"] += 1
    else:
        _extend(aggregate, "time", normalized_time)
    if normalized_date is not None and normalized_time is not None:
        combined = datetime.fromisoformat(
            f"{normalized_date}T{normalized_time}"
        ).isoformat(timespec="seconds")
        _extend(aggregate, "datetime", combined)
    if depth_min is None:
        aggregate["missing_depth_min_count"] += 1
    else:
        current = aggregate["depth_min"]
        if current is None or depth_min < current:
            aggregate["depth_min"] = depth_min
    if depth_max is None:
        aggregate["missing_depth_max_count"] += 1
    else:
        current = aggregate["depth_max"]
        if current is None or depth_max > current:
            aggregate["depth_max"] = depth_max


def finalize_metadata(
    aggregate: Mapping[str, object],
    *,
    authoritative_total: int | None,
    query_total: int | None = None,
) -> dict[str, object]:
    """Return metadata envelopes and completeness against the authoritative count."""
    scanned = int(aggregate["metadata_objects_scanned"])
    missing_dates = int(aggregate["missing_date_count"])
    missing_times = int(aggregate["missing_time_count"])
    valid_dates = int(aggregate["valid_date_count"])
    if valid_dates == 0:
        precision = "none"
    elif missing_dates:
        precision = "partial"
    elif missing_times:
        precision = "date"
    else:
        precision = "datetime"

    discrepancy = (
        query_total is not None
        and authoritative_total is not None
        and int(query_total) != int(authoritative_total)
    )
    if authoritative_total is None:
        complete = None
        coverage = None
        depth_complete = None
    else:
        total = int(authoritative_total)
        complete = scanned == total and not discrepancy
        coverage = 100.0 if total == 0 else min(100.0, scanned * 100.0 / total)
        depth_complete = (
            complete
            and int(aggregate["missing_depth_min_count"]) == 0
            and int(aggregate["missing_depth_max_count"]) == 0
        )

    return {
        key: aggregate[key]
        for key in (
            "date_min", "date_max", "time_min", "time_max",
            "datetime_min", "datetime_max", "depth_min", "depth_max",
            "missing_date_count", "missing_time_count",
            "missing_depth_min_count", "missing_depth_max_count",
            "metadata_objects_scanned",
        )
    } | {
        "temporal_precision": precision,
        "metadata_complete": complete,
        "metadata_coverage_pct": coverage,
        "depth_complete": depth_complete,
        "query_total_objects": query_total,
        "count_discrepancy": discrepancy,
    }


def normalize_sample_stats(row: Mapping[str, object]) -> dict[str, object]:
    """Normalize sample_taxo_stats values, the sole authoritative count source."""
    sample_id = int(row["sample_id"])
    validated = int(row.get("nb_validated") or 0)
    predicted = int(row.get("nb_predicted") or 0)
    dubious = int(row.get("nb_dubious") or 0)
    unclassified = int(row.get("nb_unclassified") or 0)
    return {
        "sample_id": sample_id,
        "nb_validated": validated,
        "nb_predicted": predicted,
        "nb_dubious": dubious,
        "nb_unclassified": unclassified,
        "object_count": validated + predicted + dubious + unclassified,
        "used_taxa": row.get("used_taxa") or [],
    }
