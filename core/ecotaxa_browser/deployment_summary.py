"""EcoTaxa sample deployment summary.

Light metadata-oriented view for one sample: sample fields, linked
acquisitions, object date/depth envelope, and UVP free fields when present.
This does not start an EcoTaxa export job and does not download images.
"""

from __future__ import annotations

from core.ecotaxa_browser.acquisitions import _normalize_acquisition
from core.ecotaxa_browser.sample_metadata import (
    OBJECT_METADATA_FIELDS,
    accumulate_metadata_row,
    finalize_metadata,
    new_metadata_aggregate,
    normalize_sample_stats,
)
from core.ecotaxa_browser.samples import _normalize_sample
from tools.ecotaxa_client import EcotaxaClient

_DEPLOYMENT_FIELDS = f"{OBJECT_METADATA_FIELDS},obj.acquisid"


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
    stats_rows = client.sample_taxo_stats([sample_id])
    stats_row = next(
        (
            row for row in stats_rows
            if int(row.get("sample_id", -1)) == int(sample_id)
        ),
        None,
    )
    if stats_row is None:
        raise RuntimeError(
            f"EcoTaxa sample statistics returned no entry for sample {sample_id}"
        )
    stats = normalize_sample_stats(stats_row)

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
        authoritative_total=int(stats["object_count"]),
    )

    return {
        "sample": sample,
        "acquisitions": acquisitions,
        "object_summary": object_summary | {
            key: stats[key]
            for key in (
                "nb_validated",
                "nb_predicted",
                "nb_dubious",
                "nb_unclassified",
                "used_taxa",
            )
        },
    }


def _summarize_sample_objects(
    client: EcotaxaClient,
    *,
    sample_id: int,
    project_id: int,
    page_size: int,
    max_objects: int,
    authoritative_total: int,
) -> dict:
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
    if max_objects < 1:
        raise ValueError("max_objects must be at least 1")

    if authoritative_total == 0:
        metadata = finalize_metadata(
            new_metadata_aggregate(),
            authoritative_total=0,
            query_total=0,
        )
        return {
            **metadata,
            "total_objects": 0,
            "objects_scanned": metadata["metadata_objects_scanned"],
            "truncated": False,
            "acquisition_ids": [],
        }

    total_objects_from_query: int | None = None
    aggregate = new_metadata_aggregate()
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
        if total_objects_from_query is None:
            total_objects_from_query = int(result.get("total_ids") or 0)
        rows = result.get("details") or []
        if not rows:
            break

        for row in rows:
            accumulate_metadata_row(aggregate, row[:4])
            acquisid = row[4] if len(row) > 4 else None
            if acquisid is not None:
                acquisition_ids.add(int(acquisid))

        window_start += len(rows)
        if total_objects_from_query is not None and window_start >= total_objects_from_query:
            break
        if len(rows) < window_size:
            break

    metadata = finalize_metadata(
        aggregate,
        authoritative_total=authoritative_total,
        query_total=total_objects_from_query,
    )
    return {
        **metadata,
        "total_objects": authoritative_total,
        "objects_scanned": metadata["metadata_objects_scanned"],
        "truncated": metadata["metadata_complete"] is not True,
        "acquisition_ids": sorted(acquisition_ids),
    }
