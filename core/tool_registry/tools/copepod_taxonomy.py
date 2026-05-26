from core.tool_registry.registry import Tool, registry

_code = '''
def lookup_worms_taxonomy(query, include_children=False, marine_only=True, session_id=None):
    """Query the WoRMS API to get the full taxonomic classification of a marine organism.

    Use this when the user asks about:
    - The full taxonomic hierarchy of a species or group (genus, family, order)
    - Whether a name is accepted or a synonym in WoRMS
    - The AphiaID of a taxon
    - All species belonging to a genus or family (include_children=True)
    - Navigating the copepod classification tree

    The RAG knowledge base covers common copepod species. Use this tool when:
    - The species is not in the RAG (uncommon species)
    - The user wants a live, authoritative classification
    - The user asks about children taxa (all species of a genus, all genera of a family)

    Args:
        query (str | int): Scientific name (e.g. "Calanus hyperboreus") or AphiaID (e.g. 104464).
        include_children (bool): If True, also return direct child taxa (default False).
        marine_only (bool): Restrict search to marine taxa (default True). Set to False for
            brackish or freshwater copepods (e.g. Eurytemora, some Cyclopoida).
        session_id (str, optional): Session ID for Langfuse tracing.

    Returns:
        dict with keys:
            query           — original query
            aphia_id        — WoRMS AphiaID (int)
            scientific_name — accepted scientific name
            status          — "accepted" | "synonym" | "unaccepted" | "not_found"
            valid_aphia_id  — AphiaID of accepted name if synonym
            rank            — taxonomic rank (Species, Genus, Family, Order, Class, ...)
            classification  — list of dicts {rank, scientific_name, aphia_id} from kingdom to taxon
                              (always follows the accepted name's classification, even for synonyms)
            children        — list of dicts {aphia_id, scientific_name, rank, status} if include_children=True
            source          — "WoRMS REST API"
            error           — error message if the query failed, else None
    """
    import requests

    BASE = "https://www.marinespecies.org/rest"
    marine_param = "true" if marine_only else "false"
    result = {
        "query": str(query),
        "aphia_id": None,
        "scientific_name": None,
        "status": "not_found",
        "valid_aphia_id": None,
        "rank": None,
        "classification": [],
        "children": [],
        "source": "WoRMS REST API",
        "error": None,
    }

    try:
        # Pre-check: detect EcoTaxa annotation format (e.g. "Calanus_CV", "Calanus_glacialis_CV")
        import re as _re
        _STAGE_CODES = r"(?:N[IVX]+|C[IVX]+|CV|CIV|CIII|CII|CI|AF|AM)$"
        if isinstance(query, str) and _re.search(r"_" + _STAGE_CODES, query, _re.IGNORECASE):
            stripped = _re.sub(r"_" + _STAGE_CODES, "", query, flags=_re.IGNORECASE).replace("_", " ").strip()
            result["status"] = "ecotaxa_annotation"
            result["error"] = (
                f"'{query}' is an EcoTaxa annotation format (taxon + stage code) — not a valid WoRMS name. "
                f"Strip the stage code and search for the scientific name instead. "
                f"Suggested query: '{stripped}'"
            )
            return result

        # Step 1 — resolve AphiaID
        if isinstance(query, int) or (isinstance(query, str) and query.isdigit()):
            aphia_id = int(query)
            record_url = f"{BASE}/AphiaRecordByAphiaID/{aphia_id}"
            r = requests.get(record_url, timeout=10)
            r.raise_for_status()
            if not r.content:
                result["error"] = f"WoRMS returned empty response for AphiaID {aphia_id}"
                return result
            record = r.json()
        else:
            search_url = f"{BASE}/AphiaRecordsByName/{requests.utils.quote(str(query))}"
            r = requests.get(search_url, params={"like": "false", "marine_only": marine_param}, timeout=10)
            r.raise_for_status()
            records = r.json() if r.content else []
            if not records:
                # retry with fuzzy match
                r2 = requests.get(search_url, params={"like": "true", "marine_only": marine_param}, timeout=10)
                r2.raise_for_status()
                records = (r2.json() if r2.content else []) or []
            if not records:
                result["error"] = f"No WoRMS record found for '{query}'"
                return result
            # prefer accepted records
            accepted = [rec for rec in records if rec.get("status") == "accepted"]
            record = accepted[0] if accepted else records[0]
            aphia_id = record["AphiaID"]

        result["aphia_id"] = aphia_id
        result["scientific_name"] = record.get("scientificname") or record.get("valid_name")
        result["status"] = record.get("status", "unknown")
        result["valid_aphia_id"] = record.get("valid_AphiaID")
        result["rank"] = record.get("rank")

        # Step 2 — full classification hierarchy.
        # For synonyms, follow valid_AphiaID so the classification reflects the accepted name.
        cls_aphia_id = aphia_id
        if result["status"] != "accepted" and result["valid_aphia_id"]:
            cls_aphia_id = result["valid_aphia_id"]

        cls_url = f"{BASE}/AphiaClassificationByAphiaID/{cls_aphia_id}"
        rc = requests.get(cls_url, timeout=10)
        rc.raise_for_status()
        cls_data = rc.json() if rc.content else None

        def _flatten(node, out):
            if node is None:
                return
            out.append({
                "rank": node.get("rank"),
                "scientific_name": node.get("scientificname"),
                "aphia_id": node.get("AphiaID"),
            })
            _flatten(node.get("child"), out)

        flat = []
        _flatten(cls_data, flat)
        result["classification"] = flat

        # Step 3 — children (optional), paginated to retrieve all results.
        if include_children:
            ch_url = f"{BASE}/AphiaChildrenByAphiaID/{aphia_id}"
            all_children = []
            offset = 0
            page_size = 50
            while True:
                rch = requests.get(
                    ch_url,
                    params={"marine_only": marine_param, "offset": offset},
                    timeout=10,
                )
                rch.raise_for_status()
                page = (rch.json() if rch.content else None) or []
                all_children.extend(page)
                if len(page) < page_size:
                    break
                offset += page_size
            result["children"] = [
                {
                    "aphia_id": c.get("AphiaID"),
                    "scientific_name": c.get("scientificname") or c.get("valid_name"),
                    "rank": c.get("rank"),
                    "status": c.get("status"),
                }
                for c in all_children
            ]

    except requests.exceptions.Timeout:
        result["error"] = "WoRMS API timeout — try again or consult https://www.marinespecies.org"
    except requests.exceptions.HTTPError as e:
        result["error"] = f"WoRMS HTTP error: {e}"
    except Exception as e:
        result["error"] = f"Unexpected error: {e}"

    # Langfuse trace (optional)
    if session_id:
        try:
            from langfuse import Langfuse
            lf = Langfuse()
            span = lf.span(
                name="worms_taxonomy_lookup",
                session_id=session_id,
                input={"query": str(query), "include_children": include_children},
                output={
                    "aphia_id": result["aphia_id"],
                    "status": result["status"],
                    "rank": result["rank"],
                    "n_classification_levels": len(result["classification"]),
                    "n_children": len(result["children"]),
                },
            )
            span.end()
        except Exception:
            pass

    return result
'''

registry.register(Tool(
    name="copepod_taxonomy",
    tags=frozenset({"copepod_taxonomy"}),
    code=_code
))
