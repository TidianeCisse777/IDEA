# Copepod Assistant

Dockerized assistant for copepod file analysis, graph production, and technical
reporting. It runs a FastAPI/LangGraph agent behind Open WebUI.

Current status: loading and analysing local files works well. EcoTaxa
project/sample exploration is in development. Amundsen CTD, OGSL, and
Bio-ORACLE tools exist but are still being integrated more tightly into the
agent workflow.

## Documentation

La doc suit une règle simple : **la référence figée est à la racine, les guides
et notes détaillées sont sous [`docs/`](docs/README.md)**. Les notes internes
(test maps, brouillons) restent locales et ne sont pas versionnées — voir
[`docs/README.md`](docs/README.md) pour la carte complète.

**Référence figée (racine) — à lire en premier :**

| Doc | Contenu |
|---|---|
| [`CONTEXT.md`](CONTEXT.md) | Identité métier de l'agent : périmètre, ce qu'il fait / ne fait pas, sources. |
| [`SPEC.md`](SPEC.md) | Spécification figée : use cases (UC-A…UC-J), inventaire des 59 tools (62 avec SQL), skills, RAG, contraintes dures. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Câblage logiciel : serve.py / agent.py / tools / RAG / MCP / Open WebUI, config, ADR. |
| [`TOOLS.md`](TOOLS.md) | Référence tool par tool, par catégorie. |
| [`SEQUENCES.md`](SEQUENCES.md) | Diagrammes de séquence par use case (S0…S9). |
| [`PARTAGE.md`](PARTAGE.md) | Partage & déploiement : état actuel (Cloudflare Tunnel) et cible (VM prod / sous-domaine ULaval). |
| [`CHANGELOG.md`](CHANGELOG.md) | Historique des releases. |
| [`CLAUDE.md`](CLAUDE.md) · [`AGENTS.md`](AGENTS.md) | Consignes pour les assistants de code (Claude Code, Codex…). |

**Guides détaillés ([`docs/`](docs/README.md), versionnés) :**

| Doc | Contenu |
|---|---|
| [`docs/deploy/DEPLOY.md`](docs/deploy/DEPLOY.md) | Runbook prod détaillé : hardening, TLS, backups, migration. |
| [`docs/features/ENRICHMENT_ECOTAXA_ECOPART.md`](docs/features/ENRICHMENT_ECOTAXA_ECOPART.md) | Enrichissement EcoTaxa ↔ EcoPart et métriques d'abondance. |
| [`docs/mcp/MCP_CAPABILITIES.md`](docs/mcp/MCP_CAPABILITIES.md) | Ce que couvre la couche MCP EcoTaxa. |
| [`docs/mcp/MCP_ECOTAXA_ORCHESTRATION.md`](docs/mcp/MCP_ECOTAXA_ORCHESTRATION.md) | Orchestration des 4 couches (prompt → skill → tool → MCP). |
| [`docs/mcp/MCP_ECOTAXA_SHARE_GUIDE.md`](docs/mcp/MCP_ECOTAXA_SHARE_GUIDE.md) | Partage, lancement et test du serveur MCP EcoTaxa. |

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

### First run: wait for the EcoTaxa cache

On the first start the EcoTaxa cache fills in the background (~1–2 min, longer
for large accounts). Until it is populated, EcoTaxa questions return an empty
result even though the agent is up.

**Watch the progress live** — `last_sync_status` is `running` while the sync
is in progress, and `samples_indexed` / `projects_indexed` climb as it goes:

```bash
# refresh every 3s; stop when last_sync_status flips to "ok"
while true; do
  curl -s http://localhost:8001/health | jq -c .cache
  sleep 3
done
```

You will see the counts rise, for example:

```jsonc
{"samples_indexed":0,  "projects_indexed":0, "last_sync_status":"running"}  // just started
{"samples_indexed":28, "projects_indexed":2, "last_sync_status":"running"}  // in progress
{"samples_indexed":97, "projects_indexed":6, "last_sync_status":"ok"}       // done — safe to query
```

The cache is ready when `last_sync_status` is `ok` and `samples_indexed > 0`.
If it stays at `0` with no `running` status, force a sync:

```bash
source .env
curl -X POST http://localhost:8001/admin/resync -H "Authorization: Bearer $MCP_AUTH_TOKEN"
```

You can also ask the agent directly — *"le cache EcoTaxa est-il à jour ?"* — it
reports the indexed counts, the last sync time, and whether a sync is running.

### Confirm the agent actually sees the cache

`http://localhost:8001/health` is the **MCP server's** view — it does **not**
prove the agent reads the same data. The agent and the MCP server must read
the same `data/ecotaxa_cache.sqlite` file. Compare the two views:

```bash
# MCP-side view (the server that fills the cache)
curl -s http://localhost:8001/health | jq .cache

# Agent-side view (what the LLM actually reads)
docker compose exec -T copepod-agent python -c "
import sqlite3, os
p = os.getenv('ECOTAXA_CACHE_DB', 'data/ecotaxa_cache.sqlite')
c = sqlite3.connect(p)
print('agent samples =', c.execute('SELECT COUNT(*) FROM samples_cache').fetchone()[0])
print('agent projects=', c.execute('SELECT COUNT(DISTINCT project_id) FROM samples_cache').fetchone()[0])
"
```

Read the result like this:

- **Agent counts == MCP counts, and > 0** → the cache is shared and complete.
  If the agent still answers EcoTaxa questions poorly, it is **not** a cache
  problem (look at the LLM/tool routing, not the cache).
- **Agent counts = 0 while MCP shows data** → the agent is reading a
  *different* file than the MCP server. Do not run the standalone
  `docker-compose.mcp.yml` alongside `./start.sh`: it stores the cache in an
  isolated Docker volume that the agent never mounts. Use `./start.sh` only.

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

## Agent capabilities

The agent exposes ~54 tools to the LLM, grouped by category:

- **Files & analysis** — load CSV/TSV/Excel, controlled pandas, graph production
- **EcoTaxa** (read-only via MCP cache + confirmed exports) — catalogue, schema, taxa, zone/period search, summaries, export
- **EcoPart** — samples, join, remote enrichment
- **Amundsen CTD / OGSL** — profile preview, per-row CTD enrichment
- **Bio-ORACLE** — env variables & climate scenarios by point/zone/row
- **SQL workspace** (read-only, optional), **named geography**, **taxonomy (WoRMS)**, **knowledge base (RAG)**, **deliverables (PDF)**

Full, up-to-date inventory and use cases → **[`SPEC.md`](SPEC.md)** (capabilities + UC-A…UC-J).
Tool-by-tool reference → **[`TOOLS.md`](TOOLS.md)**.
