# Copepod Assistant

Shareable Docker setup for the Copepod Assistant.

## Setup

Requirements:

- Docker Desktop with Docker Compose
- The values provided by the project maintainers:
  `OPENAI_API_KEY`, `ECOTAXA_USERNAME`, `ECOTAXA_PASSWORD`

```bash
git clone <repo-url>
cd IDEA
cp .env.example .env
```

Open `.env` and edit only these three values:

```dotenv
OPENAI_API_KEY=REPLACE_WITH_THE_OPENAI_KEY
ECOTAXA_USERNAME=REPLACE_WITH_THE_ECOTAXA_USERNAME
ECOTAXA_PASSWORD=REPLACE_WITH_THE_ECOTAXA_PASSWORD
```

Everything else is managed by the project maintainers in Docker Compose and the
application defaults.

`MCP_AUTH_TOKEN` is not an EcoTaxa credential. It is an internal token used to
protect the local MCP service, and `./start.sh` generates it automatically in
`.env`.

EcoTaxa itself only needs `ECOTAXA_USERNAME` and `ECOTAXA_PASSWORD` here. The
code logs in with those credentials and receives the EcoTaxa bearer token
internally.

Start the app:

```bash
./start.sh
```

`./start.sh` starts the Docker containers for Postgres, MCP EcoTaxa, the agent
API, and Open WebUI. Open WebUI is available at:

```text
http://localhost:3000
```

If `cloudflared` is installed, the script also prints temporary public URLs.

By default, `./start.sh` does not rebuild Docker images. This avoids downloading
and reinstalling dependencies every time. Rebuild only when you explicitly need
to refresh the images:

```bash
./start.sh --build
```

## Local Agent Mode

If you do not want Docker to create or start the `copepod-agent` container, run:

```bash
./start.sh --local-agent
```

This starts only Postgres, MCP EcoTaxa, and Open WebUI in Docker. Open WebUI then
calls your local agent at `http://localhost:8000`, so start the agent locally in
another terminal:

```bash
python serve.py
```

You can combine both options if needed:

```bash
./start.sh --local-agent --build
```

## Stop

Press `Ctrl+C` in the `./start.sh` terminal. The script stops the containers it
started.

To stop manually:

```bash
docker compose stop open-webui copepod-agent mcp-ecotaxa postgres
```
