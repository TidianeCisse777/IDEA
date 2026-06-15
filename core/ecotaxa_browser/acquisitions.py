"""EcoTaxa acquisition navigation services."""

from tools.ecotaxa_client import EcotaxaClient


def list_project_acquisitions(project_id: int) -> list[dict]:
    """Return acquisitions belonging to one project."""
    client = EcotaxaClient()
    client.login()
    return [
        _normalize_acquisition(item)
        for item in client.list_acquisitions(project_id)
    ]


def get_acquisition(acquisition_id: int) -> dict:
    """Return one normalized acquisition."""
    client = EcotaxaClient()
    client.login()
    return _normalize_acquisition(client.get_acquisition(acquisition_id))


def _normalize_acquisition(acquisition: dict) -> dict:
    return {
        "acquisition_id": int(acquisition["acquisid"]),
        "sample_id": int(acquisition["acq_sample_id"]),
        "original_id": str(acquisition["orig_id"]),
        "instrument": acquisition.get("instrument"),
        "free_fields": acquisition.get("free_columns", {}),
    }
