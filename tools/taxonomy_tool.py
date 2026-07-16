"""LangChain tool for marine taxonomy lookup."""

from collections.abc import Callable
from typing import Any

import requests
from langchain_core.tools import tool

from core.copepod_rag.query import query_copepod_rag
from core.taxonomy_lookup import lookup_marine_taxonomy_markdown
from tools.tool_result import error, success


def make_taxonomy_tool(
    *,
    rag_query: Callable[..., list[dict]] = query_copepod_rag,
    http_get: Callable[..., Any] = requests.get,
):
    """Create the active taxonomy lookup tool."""

    @tool(response_format="content_and_artifact")
    def lookup_marine_taxonomy(term: str, include_children: bool = False) -> str:
        """Resolve a taxon or organism term through local knowledge and WoRMS.

        Use for knowledge questions about any taxon mention, scientific name,
        common organism name, AphiaID, accepted WoRMS status, synonyms,
        classification, or plain-language definition. This is not limited to
        EcoTaxa. Do not use for data questions such as counts, locations,
        samples, projects, or observations; those must use source/data tools.
        """
        try:
            summary = lookup_marine_taxonomy_markdown(
                term,
                include_children=include_children,
                rag_query=rag_query,
                http_get=http_get,
            )
            return success(
                summary,
                provenance={"source": "WoRMS and local knowledge", "term": term},
                method="taxonomy lookup",
            )
        except Exception as exc:
            return error(
                f"Recherche taxonomique indisponible : {exc}",
                retryable=True,
                provenance={"source": "WoRMS and local knowledge", "term": term},
                method="taxonomy lookup",
            )

    return lookup_marine_taxonomy
