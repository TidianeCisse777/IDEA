# MCP EcoTaxa Server

Read-only MCP server exposing EcoTaxa catalogue navigation, schema
inspection, taxon counts, and cross-project geo+temporal browse to any
MCP-capable agent (Claude Desktop, Claude Code CLI, custom agents,
IDEA itself).

The server is **curated**: 15 tools mapped to 7 use cases, no write
endpoints, no exports (exports stay with the IDEA-native `query_ecotaxa`
tool).

---

## Quick start

```bash
# In the repo root
docker compose up -d mcp-ecotaxa

# Sanity check
curl http://localhost:8001/health

# First-time cache warmup (otherwise samples_in_region returns CACHE_EMPTY)
curl -X POST http://localhost:8001/admin/resync \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN"

# Wait ~2 min, then verify
curl http://localhost:8001/health | jq '.cache'
```

After that, the nightly scheduler refreshes the cache automatically at
3 AM (configurable via `ECOTAXA_SYNC_HOUR`).

---

## Configuration

| Env var | Required | Default | Role |
|---|---|---|---|
| `MCP_AUTH_TOKEN` | yes | — | Shared Bearer protecting `/mcp` and `/admin/*` |
| `ECOTAXA_TOKEN` or (`ECOTAXA_USERNAME` + `ECOTAXA_PASSWORD`) | yes | — | Service account credentials |
| `ECOTAXA_CACHE_DB` | no | `data/ecotaxa_cache.sqlite` | Path to the local SQLite cache |
| `ECOTAXA_NIGHTLY_SYNC` | no | `true` | Set to `false` to disable the nightly cron |
| `ECOTAXA_SYNC_HOUR` | no | `3` | UTC hour for the nightly sync (0–23) |

---

## Endpoints

### Public

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Returns `{status, cache: {samples_indexed, projects_indexed, schemas_indexed, last_sync_status, cache_age_hours}}` |

### Bearer-protected

| Method | Path | Description |
|---|---|---|
| `POST` | `/mcp` | MCP JSON-RPC transport (Streamable HTTP) |
| `POST` | `/admin/resync` | Fire-and-forget full sync. Returns `202 {run_id: "pending", status: "started"}` |
| `GET` | `/admin/sync_runs/{run_id}` | Returns the row for a given sync run (`status`, `samples_synced`, …) |

All Bearer-protected requests must carry `Authorization: Bearer $MCP_AUTH_TOKEN`. Any other Authorization value returns 401.

---

## Tools

Surface is read-only, organised by use case. Every tool returns a JSON
object. Business errors are returned structured (`{ok: false, error: {code, message, candidates}}`); infrastructure errors propagate as MCP `isError: true`.

### UC1 — Geographic / temporal availability (cache-only)

| Tool | Inputs | Returns |
|---|---|---|
| `samples_in_region` | `bbox?` (`{south, west, north, east}`), `date_range?` (`{from, to}`), `instrument?` | `{samples[], total_matching, truncated, summary}` — cap 500 |
| `projects_in_region` | `bbox?`, `date_range?` | `{projects[], total_projects, total_samples}` — one row per project with `sample_count`, `object_count`, `instruments`, date range |

### UC2 — Taxon mapping (cache + live taxon counts)

| Tool | Inputs | Returns |
|---|---|---|
| `find_observations` | `taxon` (str/int), `bbox?`, `date_range?`, `instrument?`, `status?` (`V`/`P`/`D`/`all`) | `{samples[], attested_projects, project_counts, granularity: "project_filtered"}` |

### UC3 — Counts

| Tool | Inputs | Returns |
|---|---|---|
| `taxa_stats` | `project_ids`, `taxa` (mix of int IDs and strings) | `{rows[], inaccessible_project_ids, taxa_resolved}` with V/P/D/total per (project, taxon) |

### UC4 — Schema inspection

| Tool | Inputs | Returns |
|---|---|---|
| `get_project_schema` | `project_id`, `verbose?`, `include_process?` | `{levels: {sample, acquisition, object}, labels_index}` |
| `get_column_distribution` | `project_id`, `column_name`, `level?` | numeric: `{min, max, mean, median, p25, p75, n}`. text: `{top_values[], total_distinct, sample_size}`. `source` exposes `ecotaxa_column_stats` vs `first_window_sample` |

### UC5 — Multi-project compatibility

| Tool | Inputs | Returns |
|---|---|---|
| `compare_project_schemas` | `project_ids` | `{common_columns, type_conflicts (severity), level_conflicts, unique_to_project}` |

### UC6 — Catalogue navigation

| Tool | Inputs | Returns |
|---|---|---|
| `search_projects` | `title?`, `instrument?`, `page?`, `page_size?` | Project list |
| `get_project` | `project_id` | Project metadata + stats + schema summary |
| `list_project_samples` | `project_id`, `page?`, `page_size?` | Sample list |
| `get_sample` | `sample_id` | Sample metadata |
| `list_project_acquisitions` | `project_id` | Acquisition list |
| `get_acquisition` | `acquisition_id` | Acquisition metadata |
| `list_sample_objects` | `sample_id`, `taxon?`, `status?`, `page?`, `page_size?` | Object list |
| `get_object` | `object_id` | Object **with sample + acquisition + project inlined** (vertical context) |

### UC7 — Taxonomy

| Tool | Inputs | Returns |
|---|---|---|
| `taxonomy_node` | `taxon_id?` (None = roots) | Node + children |
| `search_taxa` | `query` | Autocomplete results |

---

## Error codes

| Code | Cause | Recovery |
|---|---|---|
| `AMBIGUOUS_COLUMN` | `get_column_distribution` column name exists at >1 level | Re-call with `level=` from the `candidates` array |
| `COLUMN_NOT_FOUND` | Column does not exist on the project | Call `get_project_schema` first |
| `AMBIGUOUS_TAXON` | Scientific name matches multiple taxa | Re-call with integer ID from the `candidates` |
| `TAXON_NOT_FOUND` | No taxon matches the name | Refine spelling |
| `INVALID_BBOX` | bbox dict missing keys or south > north | Fix the bbox |
| `INVALID_DATE_RANGE` | date_range dict missing keys | Fix the date_range |
| `CACHE_EMPTY` | Local cache has no samples (first boot, no sync yet) | `POST /admin/resync` and wait |

---

## Example: end-to-end "where is Calanus in Hudson Bay 2018-2022?"

```bash
TOKEN="$MCP_AUTH_TOKEN"
URL="http://localhost:8001/mcp"

# Initialize MCP session
curl -s -X POST "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"initialize",
    "params":{"protocolVersion":"2025-11-25","capabilities":{},
              "clientInfo":{"name":"curl","version":"0"}}
  }'

# Call the tool
curl -s -X POST "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":2,"method":"tools/call",
    "params":{
      "name":"find_observations",
      "arguments":{
        "taxon":"Calanus finmarchicus",
        "bbox":{"south":51.0,"west":-95.0,"north":66.0,"east":-75.0},
        "date_range":{"from":"2018-01-01","to":"2022-12-31"},
        "status":"V"
      }
    }
  }'
```

---

## Architecture (D3)

```
core/ecotaxa_browser/      Python pure (no LangChain, no FastMCP)
  ├── search.py            search_projects
  ├── projects.py          get_project
  ├── samples.py           list_project_samples, get_sample
  ├── acquisitions.py      list_project_acquisitions, get_acquisition
  ├── objects.py           list_sample_objects, get_object
  ├── taxonomy.py          taxonomy_node, search_taxa
  ├── schema.py            get_project_schema + labels_index
  ├── taxa_stats.py        taxa_stats (str→int resolution)
  ├── column_distribution.py  D4 hybrid (column_stats + fallback)
  ├── compare_schemas.py   C3 normalised match
  ├── region.py            samples_in_region, projects_in_region (cache)
  ├── observations.py      find_observations (G1 project-filtered)
  ├── errors.py            EcoTaxaBrowserError (code + candidates)
  └── cache/
      ├── repo.py          SQLite repository
      └── sync.py          F1/P2/E3 full sync engine

core/mcp/ecotaxa_server.py FastMCP server + BearerAuthMiddleware +
                           /health + /admin/* + nightly scheduler
```

The same `core/ecotaxa_browser/` package is consumed by the IDEA agent
through `@tool` LangChain wrappers in `tools/copepod_sources.py` —
direct import, no HTTP round-trip.

---

## Validation

- 343 pytest tests green (no live network).
- Smoke-tested end-to-end against EcoTaxa with the IDEA service account:
  7 projects, 77 samples cached in ~100 s, all UC1–UC7 paths confirmed.
