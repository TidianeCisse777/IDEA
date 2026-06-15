"""EcoTaxa taxonomy navigation services."""

from tools.ecotaxa_client import EcotaxaClient


def taxonomy_node(taxon_id: int | None = None) -> dict | list[dict]:
    """Return root taxa or one detailed taxonomy node."""
    client = EcotaxaClient()
    client.login()
    if taxon_id is None:
        return [_normalize_taxon(item) for item in client.list_root_taxa()]
    return _normalize_taxon(client.get_taxon(taxon_id))


def search_taxa(query: str) -> list[dict]:
    """Autocomplete taxonomy names."""
    query = query.strip()
    if not query:
        raise ValueError("query must not be blank")
    client = EcotaxaClient()
    client.login()
    return [
        {
            "taxon_id": int(item["id"]),
            "name": str(item["text"]),
            "status": item.get("status"),
            "in_project": bool(item.get("pr")),
            "aphia_id": item.get("aphia_id"),
            "replacement_id": item.get("renm_id"),
        }
        for item in client.search_taxa(query)
    ]


def _normalize_taxon(taxon: dict) -> dict:
    return {
        "taxon_id": int(taxon["id"]),
        "name": str(taxon.get("display_name") or taxon["name"]),
        "verbatim_name": str(taxon["name"]),
        "type": taxon.get("type"),
        "status": taxon.get("status"),
        "lineage": taxon.get("lineage", []),
        "lineage_ids": taxon.get("id_lineage", []),
        "object_count": taxon.get("nb_objects"),
        "children_object_count": taxon.get("nb_children_objects"),
        "aphia_id": taxon.get("aphia_id"),
        "rank": taxon.get("rank"),
        "children": taxon.get("children", []),
        "replacement_id": taxon.get("renm_id"),
    }
