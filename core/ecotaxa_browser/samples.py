"""EcoTaxa sample navigation services."""

from tools.ecotaxa_client import EcotaxaClient


def list_project_samples(
    project_id: int,
    page: int = 1,
    page_size: int = 50,
) -> list[dict]:
    """Return one page of samples belonging to a project."""
    _validate_pagination(page, page_size)
    client = EcotaxaClient()
    client.login()
    start = (page - 1) * page_size
    return [
        _normalize_sample(sample)
        for sample in client.list_samples(project_id)[start:start + page_size]
    ]


def get_sample(sample_id: int) -> dict:
    """Return one normalized sample."""
    client = EcotaxaClient()
    client.login()
    return _normalize_sample(client.get_sample(sample_id))


def _normalize_sample(sample: dict) -> dict:
    return {
        "sample_id": int(sample["sampleid"]),
        "project_id": int(sample["projid"]),
        "original_id": str(sample["orig_id"]),
        "latitude": sample.get("latitude"),
        "longitude": sample.get("longitude"),
        "free_fields": sample.get("free_columns", {}),
    }


def _validate_pagination(page: int, page_size: int) -> None:
    if page < 1:
        raise ValueError("page must be at least 1")
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
