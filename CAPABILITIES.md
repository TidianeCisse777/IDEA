# Copepod Assistant Capabilities

This document explains what the assistant can do today, what is partial, and
what is not supported yet.

## Primary Use Cases

- Load and inspect copepod-related tabular files.
- Produce static scientific graphs from loaded or downloaded data.
- Query EcoTaxa, EcoPart, Amundsen CTD, OGSL, Bio-ORACLE, and read-only SQL
  sources.
- Join biological observations with environmental data.
- Generate PDF deliverables from the current session.
- Answer technical questions using the NeoLab knowledge base.

## Local Files

The assistant can load:

- CSV
- TSV
- Excel
- JSON
- Parquet
- UVP-style EcoTaxa and EcoPart exports

After loading a file, it can inspect columns, types, missing values, value
ranges, distributions, and likely semantic roles such as station, depth,
latitude, longitude, taxon, image ID, and morphometry fields.

## Data Analysis

The assistant can run controlled pandas analysis on active session data:

- filtering
- grouping
- aggregation
- derived variables
- table previews
- data quality checks
- missing-value checks
- duplicate checks
- simple joins
- abundance and biomass calculations when the required fields exist

Numeric claims should come from tool execution, not from free-form guessing.

## Graphs

The assistant can generate static PNG graphs with matplotlib. Generated images
are hosted by the agent API and displayed in Open WebUI.

Supported graph families include:

- vertical profiles
- station maps
- spatial gap maps
- taxonomic distributions
- time series
- depth-stratified summaries
- CTD profiles
- environmental overlays

Graph workflow:

1. `graph_planner`
2. `graph_writer`
3. `run_graph`

Current limitation: graph output is PNG only. Interactive Plotly/HTML graphs are
not implemented yet.

## EcoTaxa

The assistant can:

- list accessible projects
- preview a project
- inspect project schema and column distributions
- compare project schemas
- count taxa by project
- export project data by project ID, taxon, and status
- search projects, samples, and observations through the local MCP EcoTaxa cache
- filter by geographic bounding box, date range, and instrument when supported

The MCP EcoTaxa service keeps a local read-only cache for fast geographic and
temporal discovery.

## EcoPart

The assistant can:

- list EcoPart samples
- preview a sample
- export sample data
- join EcoPart profiles with EcoTaxa object data when matching IDs are available

## Amundsen CTD

The assistant can access Amundsen CTD data through ERDDAP:

- list known datasets
- preview station/cast profiles
- extract temperature, salinity, oxygen, fluorescence, depth/pressure, and time
  fields when available

## OGSL

The assistant can enrich a loaded station/time table with OGSL CTD profiles from
the Gulf of St. Lawrence. It reports match quality using time and depth deltas.

## Bio-ORACLE

The assistant can:

- list available variables and scenarios
- preview a variable at a point
- query current and future marine variables
- couple zooplankton rows with environmental variables using latitude and
  longitude columns

This area is functional but still considered partial because scenario coverage
and end-to-end user workflows need more testing.

## SQL Workspace

The assistant can connect to read-only SQL databases:

- SQLite
- PostgreSQL
- MySQL
- MariaDB through the MySQL protocol

Supported operations:

- list tables and views
- inspect primary keys and foreign keys
- preview tables with filters
- copy limited query results into the session workspace as TSV

Write queries are not allowed.

## Knowledge Base

The assistant has a NeoLab-specific RAG knowledge base built from Markdown docs
under `core/copepod_rag/docs/`.

It covers:

- copepod domain concepts
- source-specific columns
- lab column conventions
- instrument columns
- taxonomy notes
- environmental joins
- calculation methods
- Arctic and northern Quebec geography
- online source guidance

Fresh environments must build the ChromaDB index once:

```bash
python core/copepod_rag/build_index.py
```

## Geographic Knowledge

The assistant recognizes common named regions such as:

- Baffin Bay
- Beaufort Sea
- Hudson Strait
- Ungava Bay
- James Bay
- Hudson Bay
- Labrador Sea
- Gulf of St. Lawrence
- Nunavik
- Arctic regions used in the project context

Named zones are resolved through the local geographic registry and MCP/cache
tools where applicable.

## Deliverables

The assistant can compile session material into a PDF deliverable:

- markdown sections
- figures
- sources
- method notes
- limitations

Output is generated with WeasyPrint. If PDF generation fails because native
libraries are missing, the tool can fall back to HTML.

## Persistence

Current persistence:

- Open WebUI conversation history
- LangGraph checkpoints per conversation
- PostgreSQL-backed runtime/session metadata
- local generated graph and download URLs

Session dataframes may need to be reloaded after some restarts, depending on the
runtime path and storage mode.

## Current Limitations

- No interactive Plotly/HTML graph workflow yet.
- No R code generation workflow.
- No production-grade multi-user quotas.
- No ULaval server deployment included in this local setup.
- No local LLM hosting; the agent currently depends on the OpenAI API.
- Bio-ORACLE and some long end-to-end workflows still need more UI testing.
- The ChromaDB RAG index is generated locally and is not committed.

## Good Example Requests

- "Load this TSV and list the columns."
- "Show the stations from this file on a map."
- "Filter the loaded stations to Baffin Bay and make a map."
- "List EcoTaxa samples in Baffin Bay for 2024."
- "Find EcoTaxa projects with UVP6 data."
- "Preview this EcoTaxa project schema."
- "Join the EcoTaxa export with EcoPart profile data."
- "Enrich this station table with OGSL CTD data."
- "Create a PDF report from the graph and methods used in this session."
