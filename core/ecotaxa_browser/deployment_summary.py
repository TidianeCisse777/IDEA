"""EcoTaxa sample deployment summary.

Light metadata-oriented view for one sample: sample fields, linked
acquisitions, object date/depth envelope, and UVP free fields when present.
This does not start an EcoTaxa export job and does not download images.
"""

from __future__ import annotations

from core.ecotaxa_browser.acquisitions import _normalize_acquisition
from core.ecotaxa_browser.samples import _normalize_sample
from tools.ecotaxa_client import EcotaxaClient

_DEPLOYMENT_FIELDS = ",".join([
    "obj.objdate",
    "obj.depth_min",
    "obj.depth_max",
    "obj.acquisid",
])


def summarize_sample_deployment(
    sample_id: int,
    *,
    page_size: int = 5000,
    max_objects: int = 50000,
) -> dict:
    """Return deployment metadata and object date/depth envelope for a sample."""
    client = EcotaxaClient()
    client.login()

    raw_sample = client.get_sample(sample_id)
    sample = _normalize_sample(raw_sample)
    project_id = int(sample["project_id"])

    acquisitions = [
        _normalize_acquisition(item)
        for item in client.list_acquisitions(project_id)
        if int(item.get("acq_sample_id")) == sample_id
    ]
    object_summary = _summarize_sample_objects(
        client,
        sample_id=sample_id,
        project_id=project_id,
        page_size=page_size,
        max_objects=max_objects,
    )

    return {
        "sample": sample,
        "acquisitions": acquisitions,
        "object_summary": object_summary,
    }


def _summarize_sample_objects(
    client: EcotaxaClient,
    *,
    sample_id: int,
    project_id: int,
    page_size: int,
    max_objects: int,
) -> dict:
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
    if max_objects < 1:
        raise ValueError("max_objects must be at least 1")

    total_objects: int | None = None
    objects_scanned = 0
    date_min: str | None = None
    date_max: str | None = None
    depth_min: float | None = None
    depth_max: float | None = None
    acquisition_ids: set[int] = set()

    window_start = 0
    while window_start < max_objects:
        window_size = min(page_size, max_objects - window_start)
        result = client.query_objects(
            project_id,
            {"samples": str(sample_id)},
            _DEPLOYMENT_FIELDS,
            window_start,
            window_size,
        )
        if total_objects is None:
            total_objects = int(result.get("total_ids") or 0)
        rows = result.get("details") or []
        if not rows:
            break

        for row in rows:
            objdate = row[0]
            dmin = _as_float(row[1])
            dmax = _as_float(row[2])
            acquisid = row[3]
            if objdate:
                text = str(objdate)
                date_min = text if date_min is None else min(date_min, text)
                date_max = text if date_max is None else max(date_max, text)
            if dmin is not None:
                depth_min = dmin if depth_min is None else min(depth_min, dmin)
            if dmax is not None:
                depth_max = dmax if depth_max is None else max(depth_max, dmax)
            if acquisid is not None:
                acquisition_ids.add(int(acquisid))

        objects_scanned += len(rows)
        window_start += len(rows)
        if total_objects is not None and window_start >= total_objects:
            break
        if len(rows) < window_size:
            break

    total = total_objects or 0
    return {
        "total_objects": total,
        "objects_scanned": objects_scanned,
        "truncated": objects_scanned < total,
        "date_min": date_min,
        "date_max": date_max,
        "depth_min": depth_min,
        "depth_max": depth_max,
        "acquisition_ids": sorted(acquisition_ids),
    }


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
