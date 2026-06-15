"""EcoTaxa taxa counting service.

Returns V/P/D breakdowns per (project, taxon). Strings are resolved to
EcoTaxa taxon IDs via the autocomplete endpoint; ambiguous or missing
taxa raise a structured ``EcoTaxaBrowserError``.
"""

from __future__ import annotations

import requests

from core.ecotaxa_browser.errors import EcoTaxaBrowserError
from tools.ecotaxa_client import EcotaxaClient


def taxa_stats(
    project_ids: list[int],
    taxa: list[int | str],
) -> dict:
    """Return V/P/D counts per (project_id, taxon).

    Args:
        project_ids: EcoTaxa project IDs to query.
        taxa: List mixing integer taxon IDs and string scientific names.
            Strings are resolved via the taxonomy autocomplete; an exact
            display-name match wins over multiple candidates.
    """
    client = EcotaxaClient()
    client.login()

    taxa_resolved = [_resolve_taxon(client, item) for item in taxa]

    rows = []
    inaccessible: list[int] = []
    for project_id in project_ids:
        if project_id in inaccessible:
            continue
        for resolved in taxa_resolved:
            try:
                summary = client.taxon_summary(project_id, resolved["taxon_id"])
            except requests.HTTPError as exc:
                status_code = getattr(exc.response, "status_code", None)
                if status_code in {401, 403}:
                    if project_id not in inaccessible:
                        inaccessible.append(project_id)
                    break
                raise
            rows.append(
                {
                    "project_id": project_id,
                    "taxon_id": resolved["taxon_id"],
                    "taxon_name": resolved["matched_name"],
                    "count_V": int(summary.get("validated_objects") or 0),
                    "count_P": int(summary.get("predicted_objects") or 0),
                    "count_D": int(summary.get("dubious_objects") or 0),
                    "count_total": int(summary.get("total_objects") or 0),
                }
            )

    return {
        "project_ids_resolved": [p for p in project_ids if p not in inaccessible],
        "taxa_resolved": taxa_resolved,
        "rows": rows,
        "inaccessible_project_ids": inaccessible,
        "unresolved_taxa": [],
    }


def _resolve_taxon(client, item: int | str) -> dict:
    if isinstance(item, int):
        taxon = client.get_taxon(item)
        return {
            "input": item,
            "taxon_id": int(taxon["id"]),
            "matched_name": str(taxon.get("display_name") or taxon.get("name") or ""),
        }

    name = str(item).strip()
    candidates = client.search_taxa(name) or []
    if not candidates:
        raise EcoTaxaBrowserError(
            "TAXON_NOT_FOUND",
            f"No EcoTaxa taxon matches '{name}'.",
        )

    lowered = name.lower()
    exact = [c for c in candidates if str(c.get("display_name", "")).lower() == lowered]
    extending = [
        c for c in candidates
        if str(c.get("display_name", "")).lower().startswith(lowered + " ")
    ]
    if exact and not extending:
        # Exact match is unambiguous: no other candidate refines it.
        chosen = exact[0]
    elif len(candidates) == 1:
        chosen = candidates[0]
    else:
        raise EcoTaxaBrowserError(
            "AMBIGUOUS_TAXON",
            f"Multiple EcoTaxa taxa match '{name}'; provide a more specific name or the integer ID.",
            candidates=[
                {"taxon_id": int(c["id"]), "display_name": str(c.get("display_name") or "")}
                for c in candidates
            ],
        )
    return {
        "input": name,
        "taxon_id": int(chosen["id"]),
        "matched_name": str(chosen.get("display_name") or ""),
    }
