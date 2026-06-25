import ast
from pathlib import Path

import yaml


def test_compose_defines_mcp_ecotaxa_service():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["mcp-ecotaxa"]

    assert service["ports"] == ["8001:8001"]
    assert service["env_file"] == [".env"]
    assert service["build"]["dockerfile"] == "Dockerfile.mcp"
    assert service["image"] == "ghcr.io/tidianecisse777/mcp-ecotaxa:latest"
    assert service["pull_policy"] == "missing"
    assert service["command"] == (
        "uvicorn core.mcp.ecotaxa_server:create_app "
        "--factory --host 0.0.0.0 --port 8001 --reload"
    )

    environment = service["environment"]
    assert "MCP_AUTH_TOKEN=${MCP_AUTH_TOKEN}" in environment
    assert "ECOTAXA_TOKEN=${ECOTAXA_TOKEN:-}" in environment
    assert "ECOTAXA_USERNAME=${ECOTAXA_USERNAME:-}" in environment
    assert "ECOTAXA_PASSWORD=${ECOTAXA_PASSWORD:-}" in environment

    assert ".:/app" in service["volumes"]
    assert "./data:/app/data" in service["volumes"]
    assert service["healthcheck"]["test"] == [
        "CMD",
        "curl",
        "-sf",
        "http://localhost:8001/health",
    ]


def test_standalone_mcp_compose_is_shareable_without_repo_mount():
    compose = yaml.safe_load(
        Path("docker-compose.mcp.yml").read_text(encoding="utf-8")
    )
    service = compose["services"]["mcp-ecotaxa"]

    assert service["image"] == "ghcr.io/tidianecisse777/mcp-ecotaxa:latest"
    assert service["pull_policy"] == "missing"
    assert "build" not in service
    assert service["ports"] == ["8001:8001"]
    assert service["env_file"] == [".env.mcp"]
    assert ".:/app" not in service.get("volumes", [])
    assert "mcp_ecotaxa_cache:/app/cache" in service["volumes"]

    environment = service["environment"]
    assert all("MCP_AUTH_TOKEN" not in item for item in environment)
    assert all("ECOTAXA_USERNAME" not in item for item in environment)
    assert all("ECOTAXA_PASSWORD" not in item for item in environment)
    assert "ECOTAXA_CACHE_DB=/app/cache/ecotaxa_cache.sqlite" in environment
    assert "ZONES_REGISTRY=/app/data/geo/zones_registry.geojson" in environment

    assert "mcp_ecotaxa_cache" in compose["volumes"]


def test_mcp_image_has_a_minimal_dependency_set():
    dockerfile = Path("Dockerfile.mcp").read_text(encoding="utf-8")
    requirements = Path("requirements-mcp.txt").read_text(encoding="utf-8")

    assert "COPY requirements-mcp.txt ." in dockerfile
    assert "COPY requirements.txt ." not in dockerfile
    assert "fastmcp>=3.0.0,<4.0.0" in requirements
    assert "apscheduler>=3.11.0,<4.0.0" in requirements
    assert "requests>=2.30.0,<3.0.0" in requirements
    assert "python-dotenv>=1.0.0,<2.0.0" in requirements
    assert "pandas>=2.0.0" in requirements
    assert "torch" not in requirements.lower()
    assert "COPY tools/__init__.py tools/ecotaxa_client.py ./tools/" in dockerfile
    assert (
        "COPY data/geo/zones_registry.geojson ./data/geo/zones_registry.geojson"
        in dockerfile
    )


def test_mcp_share_env_template_is_tracked():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8")
    env_example = Path(".env.mcp.example").read_text(encoding="utf-8")

    assert "!.env.mcp.example" in gitignore
    assert "!data/geo/zones_registry.geojson" in dockerignore
    assert "MCP_AUTH_TOKEN=" in env_example
    assert "ECOTAXA_USERNAME=" in env_example
    assert "ECOTAXA_PASSWORD=" in env_example


def test_ecotaxa_client_does_not_import_pandas_at_module_load():
    source = Path("tools/ecotaxa_client.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level_imports = [
        node for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]

    assert all(
        not (
            isinstance(node, ast.Import)
            and any(alias.name == "pandas" for alias in node.names)
        )
        for node in top_level_imports
    )
