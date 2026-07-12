import re
from pathlib import Path

import yaml


def _env_assignment_keys(text: str) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(r"(?m)^([A-Z][A-Z0-9_]*)=", text)
    }


def test_env_example_exposes_required_user_secrets_with_placeholders():
    env_example = Path(".env.example").read_text(encoding="utf-8")

    # Les 3 secrets que l'utilisateur doit fournir, avec des placeholders explicites.
    assert "OPENAI_API_KEY=REPLACE_WITH_THE_OPENAI_KEY" in env_example
    assert "ECOTAXA_USERNAME=REPLACE_WITH_THE_ECOTAXA_USERNAME" in env_example
    assert "ECOTAXA_PASSWORD=REPLACE_WITH_THE_ECOTAXA_PASSWORD" in env_example

    # MCP_AUTH_TOKEN est généré par ./start.sh, jamais saisi par l'utilisateur :
    # présent mais vide dans le fichier partagé.
    assert "MCP_AUTH_TOKEN=\n" in env_example

    # Aucun secret d'observabilité/tracing ne fuit dans le fichier partagé.
    assert "LANGCHAIN" not in env_example
    assert "LANGSMITH" not in env_example
    assert "LANGFUSE" not in env_example


def test_start_script_generates_internal_mcp_token():
    script = Path("start.sh").read_text(encoding="utf-8")

    required_block = script.split("REQUIRED_ENV_VARS=(", 1)[1].split(")", 1)[0]
    assert "OPENAI_API_KEY" in required_block
    assert "ECOTAXA_USERNAME" in required_block
    assert "ECOTAXA_PASSWORD" in required_block
    assert "MCP_AUTH_TOKEN" not in required_block

    assert "generate_mcp_token()" in script
    assert "openssl rand -hex 32" in script
    assert "MCP_AUTH_TOKEN=\"$(generate_mcp_token)\"" in script
    assert "MCP_AUTH_TOKEN=$MCP_AUTH_TOKEN" in script


def test_start_script_does_not_build_by_default():
    script = Path("start.sh").read_text(encoding="utf-8")

    assert 'BUILD_MODE="no-build"' in script
    assert "--no-build" in script
    assert "--build: allow Docker Compose to build images if needed." in script


def test_openwebui_supports_container_and_local_agent_modes():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    webui = compose["services"]["open-webui"]
    environment = webui["environment"]

    assert (
        "OPENAI_API_BASE_URL="
        "${OPENWEBUI_AGENT_BASE_URL:-http://copepod-agent:8000/v1}"
    ) in environment
    assert (
        "RAG_OPENAI_API_BASE_URL="
        "${OPENWEBUI_AGENT_BASE_URL:-http://copepod-agent:8000/v1}"
    ) in environment
    assert "host.docker.internal:host-gateway" in webui["extra_hosts"]
    assert "copepod-agent" not in webui.get("depends_on", {})


def test_readme_documents_minimal_user_setup_and_local_agent_mode():
    readme = Path("README.md").read_text(encoding="utf-8")

    # Setup minimal : l'utilisateur ne remplit que les 3 valeurs requises.
    assert "fill only" in readme
    assert "OPENAI_API_KEY" in readme
    assert "ECOTAXA_USERNAME" in readme
    assert "ECOTAXA_PASSWORD" in readme

    # MCP_AUTH_TOKEN est généré automatiquement par ./start.sh.
    assert "generates `MCP_AUTH_TOKEN`" in readme

    # Modes de lancement documentés.
    assert "./start.sh --local-agent" in readme
    assert "./start.sh --build" in readme
