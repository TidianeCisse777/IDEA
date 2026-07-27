import re
from pathlib import Path

import yaml


def _env_assignment_keys(text: str) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(r"(?m)^([A-Z][A-Z0-9_]*)=", text)
    }


def test_env_example_configures_consumers_without_ecotaxa_credentials():
    env_example = Path(".env.example").read_text(encoding="utf-8")

    # Un collaborateur utilise une release validée, jamais le mot de passe EcoTaxa.
    assert "OPENAI_API_KEY=REPLACE_WITH_THE_OPENAI_KEY" in env_example
    assert "ECOTAXA_CACHE_MODE=consumer" in env_example
    assert "ECOTAXA_CACHE_RELEASE_REPOSITORY=TidianeCisse777/IDEA" in env_example
    assert "ECOTAXA_CACHE_RELEASE_TAG=ecotaxa-cache-current" in env_example
    assert "ECOTAXA_USERNAME=" not in env_example
    assert "ECOTAXA_PASSWORD=" not in env_example
    assert "ECOTAXA_CACHE_AUTO_PUBLISH=" not in env_example
    assert "GITHUB_TOKEN=" not in env_example

    # MCP_AUTH_TOKEN est généré par ./start.sh, jamais saisi par l'utilisateur :
    # présent mais vide dans le fichier partagé.
    assert "MCP_AUTH_TOKEN=\n" in env_example

    # Le tracing LangSmith est requis sur chaque déploiement : les variables
    # sont exposées, mais la clé reste un placeholder — la vraie clé est
    # distribuée hors repo, jamais commitée.
    assert "LANGCHAIN_TRACING_V2=true" in env_example
    assert "LANGCHAIN_API_KEY=REPLACE_WITH_THE_LANGSMITH_KEY" in env_example
    assert "LANGCHAIN_PROJECT=copepod-agent" in env_example

    # Aucun autre secret d'observabilité ne fuit dans le fichier partagé.
    assert "lsv2_" not in env_example  # format des vraies clés LangSmith
    assert "LANGFUSE" not in env_example


def test_start_script_generates_internal_mcp_token():
    script = Path("start.sh").read_text(encoding="utf-8")

    required_block = script.split("REQUIRED_ENV_VARS=(", 1)[1].split(")", 1)[0]
    assert "OPENAI_API_KEY" in required_block
    assert "LANGCHAIN_API_KEY" in required_block
    assert "MCP_AUTH_TOKEN" not in required_block
    assert "REQUIRED_ENV_VARS+=(ECOTAXA_USERNAME ECOTAXA_PASSWORD)" in script
    assert (
        "REQUIRED_ENV_VARS+=(ECOTAXA_CACHE_RELEASE_REPOSITORY "
        "ECOTAXA_CACHE_RELEASE_TAG)" in script
    )

    assert "generate_mcp_token()" in script
    assert "openssl rand -hex 32" in script
    assert "MCP_AUTH_TOKEN=\"$(generate_mcp_token)\"" in script
    assert "MCP_AUTH_TOKEN=$MCP_AUTH_TOKEN" in script
    assert 'CACHE_MODE="${ECOTAXA_CACHE_MODE:-consumer}"' in script


def test_publisher_startup_can_supply_a_github_token_without_storing_it():
    script = Path("start.sh").read_text(encoding="utf-8")
    publisher_env_example = Path(".env.mcp.example").read_text(encoding="utf-8")

    assert "ECOTAXA_CACHE_AUTO_PUBLISH=true" in publisher_env_example
    assert "GITHUB_TOKEN=" in publisher_env_example
    assert 'gh auth token' in script
    assert "ECOTAXA_CACHE_AUTO_PUBLISH" in script


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

    # Setup minimal : aucun credential EcoTaxa ne circule chez les consommateurs.
    assert "fill only" in readme
    assert "OPENAI_API_KEY" in readme
    assert "does not use EcoTaxa credentials" in readme
    assert "ECOTAXA_CACHE_MODE=publisher" in readme

    # MCP_AUTH_TOKEN est généré automatiquement par ./start.sh.
    assert "generates `MCP_AUTH_TOKEN`" in readme

    # Modes de lancement documentés.
    assert "./start.sh --local-agent" in readme
    assert "./start.sh --build" in readme
