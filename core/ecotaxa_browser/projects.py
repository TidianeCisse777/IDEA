"""EcoTaxa project navigation services."""

import requests

from tools.ecotaxa_client import EcotaxaClient

_OBJECT_FIELDS = {
    "object_id", "original_id", "date", "time", "latitude", "longitude",
    "depth_min", "depth_max", "classification_id", "classification_status",
}


def get_project(project_id: int) -> dict:
    """Return project metadata, raw stats, and a compact schema summary."""
    client = EcotaxaClient()
    client.login()
    raw = client.get_project(project_id)
    try:
        stats = client.get_project_stats(project_id)
    except requests.RequestException:
        stats = [
            f"Total: {raw.get('objcount')} objects",
            f"Validated: {raw.get('pctvalidated')}%",
            f"Classified: {raw.get('pctclassified')}%",
        ]
    return {
        "project_id": int(raw["projid"]),
        "name": str(raw["title"]),
        "instrument": raw.get("instrument"),
        "status": raw.get("status"),
        "access": raw.get("highest_right") or raw.get("access"),
        "object_count": raw.get("objcount"),
        "percent_validated": raw.get("pctvalidated"),
        "percent_classified": raw.get("pctclassified"),
        "comments": raw.get("comments"),
        "stats": stats,
        "schema": {
            "sample": sorted(raw.get("sample_free_cols", {})),
            "acquisition": sorted(raw.get("acquisition_free_cols", {})),
            "object": sorted(_OBJECT_FIELDS | set(raw.get("obj_free_cols", {}))),
        },
    }
