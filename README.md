# Copepod Assistant

Dockerized assistant for copepod data exploration, graph production, and
technical reporting. It runs a FastAPI/LangGraph agent behind Open WebUI.

User-facing docs:

- [`CAPABILITIES.md`](CAPABILITIES.md): what the assistant can do.
- [`MCP_CAPABILITIES.md`](MCP_CAPABILITIES.md): what the EcoTaxa MCP layer can do.

## Requirements

- Docker Desktop with Docker Compose
- `OPENAI_API_KEY`
- EcoTaxa credentials: `ECOTAXA_USERNAME`, `ECOTAXA_PASSWORD`
- Optional: `cloudflared` for temporary public URLs

## Quick Start

```bash
git clone https://github.com/TidianeCisse777/IDEA.git
cd IDEA
cp .env.example .env
```

Edit `.env` and fill only:

```dotenv
OPENAI_API_KEY=...
ECOTAXA_USERNAME=...
ECOTAXA_PASSWORD=...
```

Start the stack:

```bash
./start.sh
```

Open WebUI:

```text
http://localhost:3000
```

`./start.sh` starts Postgres, MCP EcoTaxa, the agent API, and Open WebUI. It
also generates `MCP_AUTH_TOKEN` in `.env` if missing.

If Docker images are missing or need rebuilding:

```bash
./start.sh --build
```

## Local Agent Mode

Run Open WebUI, Postgres, and MCP EcoTaxa in Docker, but keep the FastAPI agent
local:

```bash
./start.sh --local-agent
```

With rebuild:

```bash
./start.sh --local-agent --build
```

## Health Checks

```bash
docker compose ps
docker compose exec -T copepod-agent curl -sf http://localhost:8000/
docker compose exec -T mcp-ecotaxa curl -sf http://localhost:8001/health
docker compose exec -T open-webui python3 -c "import urllib.request; print(urllib.request.urlopen('http://copepod-agent:8000/v1/models').status)"
```

Expected services:

- `open_webui`: `http://localhost:3000`
- `copepod_agent`: `http://localhost:8000`
- `mcp_ecotaxa`: `http://localhost:8001`
- `copepod_postgres`

## Tests

Useful smoke/unit tests inside the agent image:

```bash
docker compose exec -T copepod-agent python -m pip install pytest pytest-asyncio
docker compose exec -T copepod-agent python -m pytest -q tests/test_public_url.py tests/test_serve_streaming.py tests/test_openwebui_uploads.py
docker compose exec -T copepod-agent python -m pytest -q tests/test_mcp_compose.py tests/test_mcp_health.py tests/test_shareable_setup.py tests/test_requirements.py
```

For a broader suite in a fresh environment, build the RAG index first:

```bash
docker compose exec -T copepod-agent python core/copepod_rag/build_index.py
docker compose exec -T copepod-agent env -u SESSION_STORE_DATABASE_URL python -m pytest -q -k 'not test_export_deliverable_configures_homebrew_library_path'
```

The excluded test is macOS/Homebrew-specific and is not required for Docker
portability.

## Stop

If `./start.sh` is running in the foreground, press `Ctrl+C`.

Or stop services manually:

```bash
docker compose stop open-webui copepod-agent mcp-ecotaxa postgres
```
