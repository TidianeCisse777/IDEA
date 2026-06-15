import pytest
from httpx import ASGITransport, AsyncClient

from core.mcp.ecotaxa_server import create_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_health_is_public_and_reports_empty_cache(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "cache": None}


@pytest.mark.anyio
async def test_mcp_rejects_missing_bearer_token(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/mcp")

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


@pytest.mark.anyio
async def test_mcp_rejects_incorrect_bearer_token(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/mcp",
            headers={"Authorization": "Bearer wrong-token"},
        )

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


@pytest.mark.anyio
async def test_mcp_accepts_valid_bearer_token_for_initialize(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    app = create_app()
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    }

    async with app.app.lifespan(app.app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer test-token",
                    "Accept": "application/json, text/event-stream",
                },
                json=initialize,
            )

    assert response.status_code == 200


def test_app_requires_auth_token(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN"):
        create_app()
