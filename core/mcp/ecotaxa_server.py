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

from core.ecotaxa_browser.search import search_projects

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

    return mcp
