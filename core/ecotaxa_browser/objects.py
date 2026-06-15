"""EcoTaxa object navigation services."""

from core.ecotaxa_browser.acquisitions import _normalize_acquisition
from core.ecotaxa_browser.samples import _normalize_sample
from tools.ecotaxa_client import EcotaxaClient

_QUERY_FIELDS = ",".join([
    "obj.objid", "obj.orig_id", "obj.acquisid", "obj.classif_id",
    "obj.classif_qual", "obj.objdate", "obj.depth_min", "obj.depth_max",
    "txo.display_name",
])


def list_sample_objects(
    sample_id: int,
    taxon: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[dict]:
    """Return one page of objects from a sample."""
    _validate_pagination(page, page_size)
    client = EcotaxaClient()
    client.login()
    sample = client.get_sample(sample_id)
    project_id = int(sample["projid"])
    filters = {"samples": str(sample_id)}
    if taxon is not None:
        filters["taxo"] = str(taxon)
    if status:
        filters["statusfilter"] = status
    result = client.query_objects(
        project_id,
        filters,
        _QUERY_FIELDS,
        (page - 1) * page_size,
        page_size,
    )
    return [
        _normalize_query_row(result, index, row)
        for index, row in enumerate(result.get("details", []))
    ]


def get_object(object_id: int) -> dict:
    """Return an object with its acquisition, sample, and project context."""
    client = EcotaxaClient()
    client.login()
    raw_object = client.get_object(object_id)
    raw_sample = client.get_sample(int(raw_object["sample_id"]))
    raw_acquisition = client.get_acquisition(int(raw_object["acquisid"]))
    return {
        "object": _normalize_object(raw_object),
        "acquisition": _normalize_acquisition(raw_acquisition),
        "sample": _normalize_sample(raw_sample),
        "project": {"project_id": int(raw_object["project_id"])},
    }


def _normalize_query_row(result: dict, index: int, row: list) -> dict:
    return {
        "object_id": int(row[0]),
        "original_id": str(row[1]),
        "acquisition_id": int(row[2]),
        "sample_id": int(result["sample_ids"][index]),
        "project_id": int(result["project_ids"][index]),
        "taxon_id": row[3],
        "taxon": row[8],
        "classification_status": row[4],
        "date": row[5],
        "depth_min": row[6],
        "depth_max": row[7],
    }


def _normalize_object(obj: dict) -> dict:
    return {
        "object_id": int(obj["objid"]),
        "original_id": str(obj["orig_id"]),
        "acquisition_id": int(obj["acquisid"]),
        "sample_id": int(obj["sample_id"]),
        "project_id": int(obj["project_id"]),
        "taxon_id": obj.get("classif_id"),
        "classification_status": obj.get("classif_qual"),
        "date": obj.get("objdate"),
        "depth_min": obj.get("depth_min"),
        "depth_max": obj.get("depth_max"),
        "latitude": obj.get("latitude"),
        "longitude": obj.get("longitude"),
        "free_fields": obj.get("free_columns", {}),
    }


def _validate_pagination(page: int, page_size: int) -> None:
    if page < 1:
        raise ValueError("page must be at least 1")
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
