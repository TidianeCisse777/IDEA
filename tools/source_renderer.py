"""Render source citations exclusively from structured provenance metadata."""
from __future__ import annotations

import re
from typing import Any

_PROJECT_URL = re.compile(
    r"^https?://(?P<service>ecotaxa|ecopart)\.obs-vlfr\.fr/prj/(?P<project>\d+)/?$",
    flags=re.IGNORECASE,
)
_BASE_URLS = {
    "ecotaxa": "https://ecotaxa.obs-vlfr.fr/prj/{project_id}",
    "ecopart": "https://ecopart.obs-vlfr.fr/prj/{project_id}",
}
_SOURCE_LABELS = {"ecotaxa": "EcoTaxa", "ecopart": "EcoPart"}


def _source_kind(meta: dict[str, Any]) -> str | None:
    source = str(meta.get("source") or "").strip().lower()
    for kind in _BASE_URLS:
        if source == kind or source.startswith(f"{kind}:"):
            return kind
    return None


def _canonical_project_url(meta: dict[str, Any]) -> str | None:
    kind = _source_kind(meta)
    project_id = meta.get("project_id")
    if kind is None or project_id is None:
        return None
    try:
        normalized = int(project_id)
    except (TypeError, ValueError):
        return None
    return _BASE_URLS[kind].format(project_id=normalized)


def source_urls(meta: dict[str, Any]) -> list[str]:
    """Return only URLs supported by the same metadata object."""
    canonical = _canonical_project_url(meta)
    candidates: list[str] = []
    for field in ("url", "dataset_url"):
        value = meta.get(field)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    candidates.extend(
        value.strip()
        for value in meta.get("urls", [])
        if isinstance(value, str) and value.strip()
    )

    accepted: list[str] = []
    if canonical:
        accepted.append(canonical)
    for candidate in candidates:
        project_match = _PROJECT_URL.match(candidate)
        if project_match:
            if canonical and candidate.rstrip("/") == canonical:
                accepted.append(canonical)
            continue
        if candidate.startswith(("http://", "https://")):
            accepted.append(candidate.rstrip("/"))
    return list(dict.fromkeys(accepted))


def _render_one(meta: dict[str, Any]) -> str:
    source = str(meta.get("source") or "").strip()
    if source.lower().startswith("file:"):
        path = source.split(":", 1)[1]
        encoding = str(meta.get("encoding") or "").strip()
        suffix = f" (encodage : {encoding})" if encoding else ""
        return f"Fichier local : `{path}`{suffix}"

    kind = _source_kind(meta)
    project_id = meta.get("project_id")
    proven_project_label = (
        f"{_SOURCE_LABELS[kind]} projet {int(project_id)}"
        if kind and project_id is not None and str(project_id).isdigit()
        else None
    )
    label = str(
        meta.get("citation")
        or meta.get("name")
        or proven_project_label
        or meta.get("dataset_id")
        or source
        or "Source structurée"
    ).strip()
    urls = source_urls(meta)
    return label + (" — " + " ".join(urls) if urls else "")


def render_sources(meta: dict[str, Any]) -> str:
    """Render one source or a structured ``sources`` collection deterministically."""
    nested = meta.get("sources")
    if isinstance(nested, list):
        entries = [_render_one(item) for item in nested if isinstance(item, dict)]
        return "\n".join(f"- {entry}" for entry in entries)
    return _render_one(meta)
