# Copepod Assistant

Dockerized assistant for copepod file analysis, graph production, and technical
reporting. It runs a FastAPI/LangGraph agent behind Open WebUI.

Current status: loading and analysing local files works well. EcoTaxa
project/sample exploration is in development. Amundsen CTD, OGSL, and
Bio-ORACLE tools exist but are still being integrated more tightly into the
agent workflow.

User-facing docs:

- [`CAPABILITIES.md`](CAPABILITIES.md): what the assistant can do.
- [`MCP_CAPABILITIES.md`](MCP_CAPABILITIES.md): what the EcoTaxa MCP layer can do.
- [`MCP_ECOTAXA_SHARE_GUIDE.md`](MCP_ECOTAXA_SHARE_GUIDE.md): shareable EcoTaxa MCP setup and usage guide.

## Requirements

- Docker Desktop with Docker Compose
- `OPENAI_API_KEY`
- EcoTaxa credentials: `ECOTAXA_USERNAME`, `ECOTAXA_PASSWORD`
- Optional: `cloudflared` for temporary public URLs
- Optional: `DATABASE_URL` (SQLAlchemy) to enable the read-only SQL workspace

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

Optional — to enable the read-only SQL workspace, also set:

```dotenv
# SQLAlchemy URL with an absolute path. Inside the agent container the repo is mounted at /app.
# Examples:
#   sqlite:////app/data/sql_workspace_demo/ocean_observations.sqlite   (demo DB shipped with the repo)
#   postgresql+psycopg://user:password@host:5432/dbname
#   mysql+pymysql://user:password@host:3306/dbname
DATABASE_URL=sqlite:////app/data/sql_workspace_demo/ocean_observations.sqlite
```

`docker-compose.yml` forwards `DATABASE_URL` from `.env` into the agent
container as an explicit environment variable, so the value you set here is
picked up the next time you run `./start.sh` (no rebuild needed).

The repo ships a demo SQLite at `data/sql_workspace_demo/ocean_observations.sqlite`
(tables: `cruises`, `stations`, `casts`, `observations`, `profile_summary`) you
can use to validate the wiring without touching a real database.

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

To share only the EcoTaxa MCP server without the full IDEA stack, use:

```bash
cp .env.mcp.example .env.mcp
docker compose -f docker-compose.mcp.yml up -d
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
