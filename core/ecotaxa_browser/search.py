"""EcoTaxa project search services."""

from __future__ import annotations

from tools.ecotaxa_client import EcotaxaClient


def search_projects(
    title: str | None = None,
    instrument: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[dict]:
    """Search accessible EcoTaxa projects and return stable catalogue fields."""
    if page < 1:
        raise ValueError("page must be at least 1")
    if page_size < 1:
        raise ValueError("page_size must be at least 1")

    client = EcotaxaClient()
    client.login()
    raw_projects = client.search_projects(
        title=title,
        instrument=instrument,
        window_start=(page - 1) * page_size,
        window_size=page_size,
    )
    return [_normalize_project(project) for project in raw_projects]


def _normalize_project(project: dict) -> dict:
    return {
        "project_id": int(project["projid"]),
        "name": str(project["title"]),
        "instrument": project.get("instrument"),
        "status": project.get("status"),
        "object_count": project.get("objcount"),
        "percent_validated": project.get("pctvalidated"),
        "percent_classified": project.get("pctclassified"),
    }
