"""Deterministic marine taxonomy lookup.

Source order:
1. Local copepod RAG for definitions.
2. WoRMS REST for authoritative taxonomy.
3. French Wikipedia fallback for plain-language definitions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import requests

from core.copepod_rag.query import query_copepod_rag

HttpGet = Callable[..., Any]
RagQuery = Callable[..., list[dict]]

WORMS_BASE = "https://www.marinespecies.org/rest"
WIKIPEDIA_API = "https://fr.wikipedia.org/w/api.php"


def lookup_marine_taxonomy_markdown(
    term: str,
    include_children: bool = False,
    *,
    rag_query: RagQuery = query_copepod_rag,
    http_get: HttpGet = requests.get,
) -> str:
    """Return a concise markdown taxonomy lookup for a user taxon term."""
    normalized = " ".join((term or "").strip().split())
    if not normalized:
        return "Erreur : le terme taxonomique ne peut pas etre vide."

    definition, definition_source = _definition_from_rag(normalized, rag_query)
    if not definition:
        definition, definition_source = _definition_from_wikipedia(normalized, http_get)
    worms = _lookup_worms(normalized, include_children, http_get)

    lines = [f"# {normalized}", ""]
    if definition:
        lines.extend(["## Definition", f"{definition}", "", f"Source definition : {definition_source}", ""])
    else:
        lines.extend(["## Definition", "Aucune definition trouvee dans le RAG local ni Wikipedia.", ""])

    if worms.get("record"):
        record = worms["record"]
        lines.extend(
            [
                "## Validation WoRMS",
                f"- Nom scientifique : {record.get('scientificname') or record.get('valid_name') or normalized}",
                f"- AphiaID : {record.get('AphiaID')}",
                f"- Statut : {record.get('status') or 'inconnu'}",
                f"- Rang : {record.get('rank') or 'inconnu'}",
                "",
            ]
        )
        classification = worms.get("classification") or []
        if classification:
            lines.append("## Classification")
            for item in classification:
                rank = item.get("rank") or "rang inconnu"
                name = item.get("scientific_name") or "nom inconnu"
                aphia = item.get("aphia_id")
                suffix = f" (AphiaID {aphia})" if aphia else ""
                lines.append(f"- {rank} : {name}{suffix}")
            lines.append("")
    else:
        lines.extend(
            [
                "## Validation WoRMS",
                f"WoRMS n'a pas resolu `{normalized}`.",
                "",
            ]
        )

    if worms.get("error"):
        lines.extend(["## Limites", str(worms["error"]), ""])

    return "\n".join(lines).strip()


def _definition_from_rag(term: str, rag_query: RagQuery) -> tuple[str | None, str | None]:
    try:
        chunks = rag_query(term, top_k=1)
    except Exception as exc:
        return None, f"RAG local indisponible: {exc}"
    if not chunks:
        return None, None
    content = str(chunks[0].get("content") or "").strip()
    if not content:
        return None, None
    return content, "RAG local"


def _definition_from_wikipedia(term: str, http_get: HttpGet) -> tuple[str | None, str | None]:
    extract = _wikipedia_extract_for_title(term, http_get)
    if extract:
        return extract, "Wikipedia fallback"

    title = _wikipedia_search_title(term, http_get)
    if not title:
        return None, None
    extract = _wikipedia_extract_for_title(title, http_get)
    if extract:
        return extract, "Wikipedia fallback"
    return None, None


def _wikipedia_extract_for_title(title: str, http_get: HttpGet) -> str | None:
    try:
        response = http_get(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "format": "json",
                "prop": "extracts",
                "exintro": 1,
                "explaintext": 1,
                "redirects": 1,
                "titles": title,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json() if getattr(response, "content", b"") else {}
    except Exception:
        return None

    pages = payload.get("query", {}).get("pages", {})
    for page_id, page in pages.items():
        if str(page_id) == "-1":
            continue
        extract = str(page.get("extract") or "").strip()
        if extract:
            return extract
    return None


def _wikipedia_search_title(term: str, http_get: HttpGet) -> str | None:
    try:
        response = http_get(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "format": "json",
                "list": "search",
                "srlimit": 1,
                "srsearch": term,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json() if getattr(response, "content", b"") else {}
    except Exception:
        return None

    matches = payload.get("query", {}).get("search", [])
    if not matches:
        return None
    title = str(matches[0].get("title") or "").strip()
    return title or None


def _lookup_worms(term: str, include_children: bool, http_get: HttpGet) -> dict:
    try:
        record = _worms_record_by_name(term, http_get)
        if not record:
            return {"record": None, "classification": [], "children": []}
        aphia_id = record.get("valid_AphiaID") or record.get("AphiaID")
        classification = _worms_classification(int(aphia_id), http_get) if aphia_id else []
        children = _worms_children(int(aphia_id), http_get) if include_children and aphia_id else []
        return {"record": record, "classification": classification, "children": children}
    except Exception as exc:
        return {"record": None, "classification": [], "children": [], "error": f"Erreur WoRMS : {exc}"}


def _worms_record_by_name(term: str, http_get: HttpGet) -> dict | None:
    url = f"{WORMS_BASE}/AphiaRecordsByName/{quote(term)}"
    response = http_get(url, params={"like": "false", "marine_only": "true"}, timeout=10)
    response.raise_for_status()
    records = response.json() if getattr(response, "content", b"") else []
    if not records:
        return None
    accepted = [record for record in records if record.get("status") == "accepted"]
    return accepted[0] if accepted else records[0]


def _worms_classification(aphia_id: int, http_get: HttpGet) -> list[dict]:
    url = f"{WORMS_BASE}/AphiaClassificationByAphiaID/{aphia_id}"
    response = http_get(url, timeout=10)
    response.raise_for_status()
    root = response.json() if getattr(response, "content", b"") else None
    out: list[dict] = []
    node = root
    while node:
        out.append(
            {
                "rank": node.get("rank"),
                "scientific_name": node.get("scientificname"),
                "aphia_id": node.get("AphiaID"),
            }
        )
        node = node.get("child")
    return out


def _worms_children(aphia_id: int, http_get: HttpGet) -> list[dict]:
    url = f"{WORMS_BASE}/AphiaChildrenByAphiaID/{aphia_id}"
    response = http_get(url, params={"marine_only": "true", "offset": 0}, timeout=10)
    response.raise_for_status()
    children = response.json() if getattr(response, "content", b"") else []
    return [
        {
            "aphia_id": child.get("AphiaID"),
            "scientific_name": child.get("scientificname") or child.get("valid_name"),
            "rank": child.get("rank"),
            "status": child.get("status"),
        }
        for child in (children or [])
    ]
