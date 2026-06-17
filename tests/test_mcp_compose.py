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
    assert "copepod_data:/app/data" in service["volumes"]
    assert service["healthcheck"]["test"] == [
        "CMD",
        "curl",
        "-sf",
        "http://localhost:8001/health",
    ]


def test_mcp_image_has_a_minimal_dependency_set():
    dockerfile = Path("Dockerfile.mcp").read_text(encoding="utf-8")
    requirements = Path("requirements-mcp.txt").read_text(encoding="utf-8")

    assert "COPY requirements-mcp.txt ." in dockerfile
    assert "COPY requirements.txt ." not in dockerfile
    assert "fastmcp>=3.0.0,<4.0.0" in requirements
    assert "apscheduler>=3.11.0,<4.0.0" in requirements
    assert "requests>=2.30.0,<3.0.0" in requirements
    assert "python-dotenv>=1.0.0,<2.0.0" in requirements
    assert "torch" not in requirements.lower()
    assert "COPY tools/__init__.py tools/ecotaxa_client.py ./tools/" in dockerfile


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
