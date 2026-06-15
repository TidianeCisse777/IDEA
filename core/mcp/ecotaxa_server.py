"""HTTP facade for the EcoTaxa browser MCP server."""

from __future__ import annotations

import os
import secrets
from functools import partial
from typing import Any

import anyio
from fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from core.ecotaxa_browser.acquisitions import (
    get_acquisition,
    list_project_acquisitions,
)
from core.ecotaxa_browser.objects import get_object, list_sample_objects
from core.ecotaxa_browser.projects import get_project
from core.ecotaxa_browser.samples import get_sample, list_project_samples
from core.ecotaxa_browser.search import search_projects
from core.ecotaxa_browser.taxonomy import search_taxa, taxonomy_node

_MCP_PATHS = {"/mcp", "/mcp/"}


class BearerAuthMiddleware:
    """Protect the MCP transport with a shared static Bearer token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") in _MCP_PATHS:
            authorization = _header_value(scope, b"authorization")
            expected = f"Bearer {self.token}"
            if authorization is None or not secrets.compare_digest(
                authorization,
                expected,
            ):
                response = JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def _header_value(scope: Scope, name: bytes) -> str | None:
    for header_name, value in scope.get("headers", []):
        if header_name.lower() == name:
            return value.decode("latin-1")
    return None


def create_app() -> ASGIApp:
    """Build the authenticated EcoTaxa MCP ASGI application."""
    token = os.getenv("MCP_AUTH_TOKEN")
    if not token:
        raise RuntimeError("MCP_AUTH_TOKEN must be configured")

    mcp = create_mcp()

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request: Any) -> JSONResponse:
        return JSONResponse({"status": "ok", "cache": None})

    return BearerAuthMiddleware(mcp.http_app(path="/mcp"), token)


def create_mcp() -> FastMCP:
    """Build the EcoTaxa MCP tool registry."""
    mcp = FastMCP("EcoTaxa Browser")

    @mcp.tool(name="search_projects")
    async def search_projects_tool(
        title: str | None = None,
        instrument: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        """Search accessible EcoTaxa projects before choosing data to export."""
        call = partial(
            search_projects,
            title=title,
            instrument=instrument,
            page=page,
            page_size=page_size,
        )
        return await anyio.to_thread.run_sync(call)

    @mcp.tool(name="get_project")
    async def get_project_tool(project_id: int) -> dict:
        """Return project metadata, stats, and a compact schema summary."""
        return await _run_sync(get_project, project_id=project_id)

    @mcp.tool(name="list_project_samples")
    async def list_project_samples_tool(
        project_id: int,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        """List one page of samples from a project."""
        return await _run_sync(
            list_project_samples,
            project_id=project_id,
            page=page,
            page_size=page_size,
        )

    @mcp.tool(name="get_sample")
    async def get_sample_tool(sample_id: int) -> dict:
        """Return one sample."""
        return await _run_sync(get_sample, sample_id=sample_id)

    @mcp.tool(name="list_project_acquisitions")
    async def list_project_acquisitions_tool(project_id: int) -> list[dict]:
        """List acquisitions from a project."""
        return await _run_sync(list_project_acquisitions, project_id=project_id)

    @mcp.tool(name="get_acquisition")
    async def get_acquisition_tool(acquisition_id: int) -> dict:
        """Return one acquisition."""
        return await _run_sync(get_acquisition, acquisition_id=acquisition_id)

    @mcp.tool(name="list_sample_objects")
    async def list_sample_objects_tool(
        sample_id: int,
        taxon: int | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        """List one page of objects from a sample."""
        return await _run_sync(
            list_sample_objects,
            sample_id=sample_id,
            taxon=taxon,
            status=status,
            page=page,
            page_size=page_size,
        )

    @mcp.tool(name="get_object")
    async def get_object_tool(object_id: int) -> dict:
        """Return an object with sample and acquisition context."""
        return await _run_sync(get_object, object_id=object_id)

    @mcp.tool(name="taxonomy_node")
    async def taxonomy_node_tool(taxon_id: int | None = None) -> dict | list[dict]:
        """Return taxonomy roots or one detailed node."""
        return await _run_sync(taxonomy_node, taxon_id=taxon_id)

    @mcp.tool(name="search_taxa")
    async def search_taxa_tool(query: str) -> list[dict]:
        """Autocomplete EcoTaxa taxonomy names."""
        return await _run_sync(search_taxa, query=query)

    return mcp


async def _run_sync(function, **kwargs):
    return await anyio.to_thread.run_sync(partial(function, **kwargs))
