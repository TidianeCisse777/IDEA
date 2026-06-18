"""EcoTaxa taxa counting service.

Returns V/P/D breakdowns per (project, taxon). Strings are resolved to
EcoTaxa taxon IDs via the autocomplete endpoint; ambiguous or missing
taxa raise a structured ``EcoTaxaBrowserError``.
"""

from __future__ import annotations

import unicodedata

import requests

from core.ecotaxa_browser.errors import EcoTaxaBrowserError
from tools.ecotaxa_client import EcotaxaClient

_TAXON_ALIASES = {
    "copepod": "Copepoda<Multicrustacea",
    "copepods": "Copepoda<Multicrustacea",
    "copepode": "Copepoda<Multicrustacea",
    "copepodes": "Copepoda<Multicrustacea",
    "copepoda": "Copepoda<Multicrustacea",
}


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

    taxa_resolved = _dedupe_resolved_taxa(
        [_resolve_taxon(client, item) for item in taxa]
    )

    rows = []
    inaccessible: list[int] = []
    taxa_ids_param = ",".join(str(item["taxon_id"]) for item in taxa_resolved)
    for project_id in project_ids:
        if project_id in inaccessible:
            continue
        try:
            stats = client.project_taxo_stats([project_id], taxa_ids=taxa_ids_param)
        except requests.HTTPError as exc:
            status_code = getattr(exc.response, "status_code", None)
            if status_code in {401, 403}:
                if project_id not in inaccessible:
                    inaccessible.append(project_id)
                continue
            raise

        stats_by_taxon: dict[int, dict] = {}
        for entry in stats:
            for taxon_id in entry.get("used_taxa") or []:
                if taxon_id is not None:
                    stats_by_taxon[int(taxon_id)] = entry
        for resolved in taxa_resolved:
            summary = stats_by_taxon.get(resolved["taxon_id"], {})
            count_v = int(summary.get("nb_validated") or 0)
            count_p = int(summary.get("nb_predicted") or 0)
            count_d = int(summary.get("nb_dubious") or 0)
            count_u = int(summary.get("nb_unclassified") or 0)
            rows.append(
                {
                    "project_id": project_id,
                    "taxon_id": resolved["taxon_id"],
                    "taxon_name": resolved["matched_name"],
                    "count_V": count_v,
                    "count_P": count_p,
                    "count_D": count_d,
                    "count_U": count_u,
                    "count_total": count_v + count_p + count_d + count_u,
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
            "matched_name": str(
                taxon.get("display_name") or taxon.get("text") or taxon.get("name") or ""
            ),
        }

    name = str(item).strip()
    lookup_name = _TAXON_ALIASES.get(_normalize_taxon_query(name), name)
    candidates = client.search_taxa(lookup_name) or []
    if not candidates:
        raise EcoTaxaBrowserError(
            "TAXON_NOT_FOUND",
            f"No EcoTaxa taxon matches '{name}'.",
        )

    lowered = lookup_name.lower()
    exact = [c for c in candidates if str(c.get("display_name") or c.get("text") or "").lower() == lowered]
    extending = [
        c for c in candidates
        if str(c.get("display_name") or c.get("text") or "").lower().startswith(lowered + " ")
    ]
    accepted_exact = [
        c for c in exact
        if str(c.get("status") or "").upper() == "A"
    ]
    if accepted_exact:
        # EcoTaxa autocomplete can return composite/stage variants before or
        # after an accepted exact taxon. For data queries, the accepted exact
        # taxon is the intended broad match.
        chosen = accepted_exact[0]
    elif exact and not extending:
        # Exact match is unambiguous: no other candidate refines it.
        chosen = exact[0]
    elif len(candidates) == 1:
        chosen = candidates[0]
    else:
        raise EcoTaxaBrowserError(
            "AMBIGUOUS_TAXON",
            f"Multiple EcoTaxa taxa match '{name}'; provide a more specific name or the integer ID.",
            candidates=[
                {
                    "taxon_id": int(c["id"]),
                    "display_name": str(c.get("display_name") or c.get("text") or ""),
                }
                for c in candidates
            ],
        )
    return {
        "input": name,
        "taxon_id": int(chosen["id"]),
        "matched_name": str(chosen.get("display_name") or chosen.get("text") or ""),
    }


def _dedupe_resolved_taxa(items: list[dict]) -> list[dict]:
    unique: dict[int, dict] = {}
    for item in items:
        taxon_id = int(item["taxon_id"])
        if taxon_id not in unique:
            unique[taxon_id] = item
            continue
        existing = unique[taxon_id]
        existing["input"] = f"{existing['input']}, {item['input']}"
    return list(unique.values())


def _normalize_taxon_query(value: str) -> str:
    without_accents = "".join(
        char for char in unicodedata.normalize("NFKD", value.lower())
        if not unicodedata.combining(char)
    )
    return " ".join(without_accents.replace("-", " ").split())
