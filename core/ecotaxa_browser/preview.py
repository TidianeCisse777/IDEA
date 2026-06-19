"""EcoTaxa project preview service.

Thin kernel wrapper around `EcotaxaClient.preview_project` so both the
LangChain `@tool` layer (tools/copepod_sources.py) and the MCP server
can share the same entry point. Mirrors the layout of `projects.py`,
`samples.py`, `schema.py`, etc.
"""
from __future__ import annotations

from tools.ecotaxa_client import EcotaxaClient


def preview_project(project_id: int, limit: int = 10) -> dict:
    """Return project metadata + a small sample of objects.

    Same payload as `EcotaxaClient.preview_project`: keys ``metadata``,
    ``summary``, ``objects``. Light, read-only — does not trigger an
    export. The MCP wrapper returns this dict as-is; the @tool layer
    formats it as a markdown table for the LLM.
    """
    client = EcotaxaClient()
    client.login()
    return client.preview_project(project_id, limit=limit)
