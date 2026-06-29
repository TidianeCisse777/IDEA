# Skill: ecotaxa_navigation

Loaded when the user asks to **explore** or **export** EcoTaxa samples by
zone, time, project, or any combination — typically the path
**zone+time → drill into samples → export a selection**.

This skill bundles the 3-slice navigation flow so the rules don't bloat
the always-on system prompt.

User-facing wording is in French by default; trigger phrases below are
kept verbatim in French so they match the actual prompts.

---

## Mental model

Four tools form the navigation pipeline. Use them in this order whenever
the user explores before exporting. Project-level scan (1b) is optional
and lives between "list" and "scan samples".

General ambiguity rules:

- Prefer read-only navigation tools over exports when the wording is
  ambiguous. The following are exploration intents, not downloads:
  "stats", "tableau", "résumé", "scan", "liste", "combien", "où",
  "quels samples/projets", "lesquels", "le plus", "top", "rank".
- Follow-up wording such as "ces samples", "ce tableau", "parmi ceux-là",
  "among these", or "which of these" means the user is referring to the
  `sample_id` / `project_id` values already shown in the previous result.
  Reuse those IDs; do not run a new broad `find_ecotaxa_samples_in_region`
  call unless the user explicitly asks for a new geographic/project search.
- **STOP rule — ambiguous "samples présents" / "qu'est-ce qu'on a"**:
  when the user says "samples présents" / "present samples" / "samples
  disponibles" / "qu'est-ce qu'on a" / "what's available" AND no scope
  (project_ids, zone, table) was established in the previous turn, you
  **MUST ask one short clarification question and call ZERO tools in this turn**.
  This is a hard zero-tool-call rule, not a preference. Concretely:
  - DO NOT call `find_ecotaxa_samples_in_region` at all — not with an
    invented zone (`"Arctique"`, `"Atlantique Nord"`, `"global"`), not
    with a broad bbox, not as a no-args probe (all parameters `None`),
    not as a way to read the error message. The probe-then-ask pattern
    is forbidden.
  - DO NOT call `find_ecotaxa_observations`,
    `find_ecotaxa_projects_in_region`, `summarize_ecotaxa_samples`,
    `count_ecotaxa_taxa`, `query_ecotaxa`, or any other navigation tool
    either — you have no scope to give them.
  - DO NOT load additional skills (`graph_planner`, `graph_writer`,
    `ecotaxa_query`) as a stalling tactic. The answer is a question,
    not a tool.
  - The clarifying question must propose 2–3 concrete options, e.g.:
    "Tu veux dire les samples de la table que je viens de t'envoyer,
    ceux d'un projet précis, ou ceux d'une zone donnée ?" Then end the
    turn and wait for the user.
- Instrument names remain filters even when the user wording is sloppy.
  In samples-by-zone queries, `LOKI` / `Loki` means instrument Loki and
  must be passed as `instrument="Loki"`; it is the instrument, not the project. Do not drop it and do not
  reinterpret it as a project search.
- When the user gives numeric project IDs and asks for project
  stats/summaries, call `summarize_ecotaxa_projects`; do not switch to `run_pandas` or `query_ecotaxa`.
- When `summarize_ecotaxa_project(s)` reports the project is absent from the local cache, surface that cache-missing result and suggest a
  resync. Do not compensate by exporting/downloading the project unless
  the user explicitly confirms a full export.
- Project-level intents split into two symmetric routes — pick by the
  *shape* the user wants back, not by overall verbosity. Both routes are
  read-only and cheap; neither downloads objects.
  - **Summary intent** → `summarize_ecotaxa_project(project_id=X)` or
    `summarize_ecotaxa_projects(project_ids=[...])`. Returns aggregated
    stats: n_samples, temporal envelope, bbox, instruments, V/P/D/U, top
    taxa. Triggers: "résume le projet", "summary", "stats avant export",
    "scan projet", "tableau de stats", "V/P/D/U", "top taxa", "bbox",
    "date_min/date_max", "instruments".
  - **Preview intent** → `preview_ecotaxa_project(project_id=X)`.
    Returns a metadata card + 10 example objects. Triggers:
    "présente-moi le projet", "présente rapidement le projet",
    "montre-moi le projet", "à quoi ressemble le projet", "qu'y a-t-il
    dans le projet", "aperçu du projet", "preview", "combien d'objets +
    quelques exemples".
  - If both intents seem plausible, prefer `preview_ecotaxa_project`
    when the user only wants a light first look, and `summarize_ecotaxa_*`
    when V/P/D/U or top taxa are explicitly named.
- Schema and column inspection are navigation/read-only intents too.
  When the user asks for one named column, call
  `inspect_ecotaxa_column(project_id=..., column_name="exact_user_column")`
  directly. Do not inspect the whole schema first unless the column is
  absent or ambiguous, and do not rewrite a clear column name into a
  nearby one.
- When the only plausible routes are a read-only summary and a full
  export, choose the read-only summary unless the user explicitly says
  "exporte", "charge", "download", or "récupère les objets".
- When a question names multiple zones, repeat the zone flow for each
  zone: `get_zone_info(zone_name=...)` then the matching EcoTaxa browser
  tool with the same date/instrument filters. Do not concatenate zones
  into a single `zone_name`.
- When the user asks to group one project's samples "par mer", "par
  secteur", "par zone", or "par région", call
  `group_ecotaxa_project_samples_by_region(project_id=...)`. This is a
  project-level grouping tool, not an export.
- Preserve EcoTaxa project/sample source links when the UI/tool output
  has them or when the user explicitly asks for links.

```
┌──────────────────────────────────────┐
│ 1. LIST                              │
│ find_ecotaxa_samples_in_region(...)  │
│  or find_ecotaxa_projects_in_region  │
│ → table of candidate samples/projets │
└──────────┬───────────────────────────┘
           │
           ▼ (optional)
┌──────────────────────────────────────┐
│ 1b. SCAN PROJECTS (light)            │
│ summarize_ecotaxa_projects([p1, ...])│
│ → n_samples + envelope + V/P/D/U     │
│   + top taxa per project             │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│ 2. SCAN SAMPLES (optional, light)    │
│ summarize_ecotaxa_samples([s1, ...]) │
│ → V/P/D counts + top taxa per sample │
│ → no download, ~500 ms               │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│ 3. EXPORT                            │
│ export_ecotaxa_samples([s1, ...],    │
│                       confirmed=...) │
│ → dry-run by default (CT-AG-06)      │
│ → groups by project automatically    │
└──────────────────────────────────────┘
```

---

## Step 1 — list samples by zone + time + (optional) project

`find_ecotaxa_samples_in_region(zone_name="...", date_range={...},
project_ids=[...], instrument="...", depth_max_lt=..., depth_max_gte=...,
month=...)`.

- The EcoTaxa public API has **no bbox/datetime endpoint** — this tool
  reads the local cache (`samples_cache` SQLite). That's why the cache
  exists and why this is the only valid path for zone+time queries.
- `zone_name` is preferred over `polygon_wkt` (the polygon never
  traverses the LLM).
- `project_ids` is a SQL `IN` filter, NOT a post-process. Use it when
  the user gives numeric project IDs or when a previous tool result
  already identified project IDs. In samples-by-zone queries, when the
  user says "LOKI" / "Loki" (even with sloppy wording such as
  "projet loki"), treat it as the instrument and pass `instrument="Loki"`
  instead of resolving a project title. Only search project names when
  the user explicitly asks to "chercher/trouver le projet nommé ...".
- `depth_max_lt` / `depth_max_gte` filter the cached sample-level
  **maximum** object depth in metres (the deepest object the sample
  reached). FR wording maps as follows:
  - `depth_max_lt=X` (sample.depth_max < X) — "moins de X m de
    profondeur max", "n'ont pas atteint X m", "pas eu X m", "sans
    données à X m", "ne dépasse pas X m", "shallow / superficiel".
  - `depth_max_gte=X` (sample.depth_max ≥ X) — "descend à plus de X m",
    "descend en-dessous de X m", "atteint X m", "atteignent X m",
    "samples profonds (≥ X m)", "samples qui plongent à X m". **The
    French idiom "descend en-dessous de X" means "reaches deeper than
    X" — map to `depth_max_gte`, NOT `depth_max_lt`.**
  - A band: combine both — `depth_max_gte=50, depth_max_lt=200` for
    "depth_max entre 50 et 200 m".
  - **Never set both args to the same value** (`depth_max_lt=100 AND
    depth_max_gte=100` is an empty band). If the user wants "exactly X
    metres" or "objets entre A et B m", that's an **object-level**
    request — route to `query_ecotaxa(project_id=..., taxon=...,
    obj_depth_gte=A, obj_depth_lte=B)` which filters server-side via
    EcoTaxa's `depthmin`/`depthmax`. For « exactement 100 m » use a
    small symmetric band (e.g. `obj_depth_gte=95, obj_depth_lte=105`)
    rather than a degenerate single value. `query_ecotaxa` is a
    confirmed export — ask the user before launching (CT-AG-06).
  - Samples whose `depth_max` is unknown do not match these filters.
- `depth_min_lt` / `depth_min_gte` filter the cached sample-level
  **minimum** object depth in metres (the shallowest object the sample
  reached, i.e. where the cast started). FR wording:
  - `depth_min_gte=X` — "ne touche pas la surface (depth_min ≥ X)",
    "samples qui démarrent profond", "profondeur minimale ≥ X m".
  - `depth_min_lt=X` — "samples qui passent dans les X premiers mètres",
    "remontent jusqu'à X m", "qui touchent la surface".
  - Combine `depth_min_gte=A, depth_max_lt=B` to get "samples
    entièrement contenus dans la tranche A–B m" (cast démarre à ≥A,
    descend < B).
- `month` filters calendar month 1-12 across years. Use `month=7` for
  "mois de juillet" when no specific year is given. If the user gives a
  precise year or date interval, use `date_range` instead or combine it
  with `month` only when both constraints are explicit.
- At least one filter is required — refusing without any filter is by
  design (avoid dumping 100k samples on the user).

Output: a markdown table with `sample_id | projet | lat | lon |
date_min | date_max | depth_min | depth_max | instrument`. The result
is already clickable (sample IDs linkified to
`/prj/{project_id}?samples={sample_id}` and project IDs to
`/prj/{project_id}`).

---

## Step 1b — scan projects (optional, before drilling samples)

When the user has a list of candidate projects (e.g. output of
`find_ecotaxa_projects_in_region` or `list_ecotaxa_projects`) and wants
to know which ones are worth exploring further, call
`summarize_ecotaxa_projects(project_ids=[...])`.

What it returns per project:

| Column | Source |
|---|---|
| `n_samples` | local cache |
| `date_min` / `date_max` | local cache (temporal envelope) |
| `bbox` (S/W/N/E) | local cache (geographic envelope of sample centroids) |
| `instruments` | local cache (distinct list) |
| `V` / `P` / `D` / `U` | project-level aggregate from `/project_set/taxo_stats` |
| `top taxa` | `/project_set/taxo_stats?taxa_ids=all`, sorted by taxon volume and resolved to names |

This is the project-level counterpart of `summarize_ecotaxa_samples`.
Use it to decide WHICH project to dig into. Mono-project sugar:
`summarize_ecotaxa_project(project_id=X)`.

Do NOT use this instead of `preview_ecotaxa_project` when the user just
wants metadata + a few example objects — `preview_ecotaxa_project` is
lighter for that case (no sample enumeration).

---

## Taxon counts inside projects

When the user asks for a count of one taxon in one or more projects,
route to `count_ecotaxa_taxa(project_ids=[...], taxa=[...])`.

Example triggers:

- "combien de copépodes validés dans le projet 14853"
- "combien de Copepoda dans 14853"
- "comptes V/P/D pour Calanus finmarchicus dans les projets 1165 et 2331"

Do NOT use `query_ecotaxa` for these questions. Counts are server-side
stats, not an export/download.

What the tool does:

1. Resolve each taxon string to an EcoTaxa `taxon_id`.
2. Call `/project_set/taxo_stats` with `ids=<project_ids>` and
   `taxa_ids=<taxon_id[,taxon_id...]>`.
3. Return V/P/D/U + total per `(project_id, taxon_id)`.

Important alias:

| User wording | EcoTaxa accepted taxon | taxon_id |
|---|---|---:|
| `copepod`, `copepods`, `copepoda`, `copépode`, `copépodes` | `Copepoda<Multicrustacea` | `25828` |

Why this matters: `search_taxa("Copepoda")` can return composite
categories first (e.g. `copepoda + actinopterygii`). For broad copepod
counts, the accepted EcoTaxa taxon is `Copepoda<Multicrustacea`
(`25828`), and the stats call must use `taxa_ids=25828`.

If the tool returns `AMBIGUOUS_TAXON`, show the candidate `taxon_id`
list and ask the user to choose; do not guess. When the user already
provides an integer taxon ID, pass it directly.

### Taxon disambiguation — `search_ecotaxa_taxa`

When the user types a short, vernacular, or potentially misspelled
taxon name, call `search_ecotaxa_taxa(query="...")` FIRST to retrieve
candidate `taxon_id`s, then call `count_ecotaxa_taxa` /
`find_ecotaxa_observations` with the resolved IDs.

Triggers:

- `count_ecotaxa_taxa` or `find_ecotaxa_observations` returned `AMBIGUOUS_TAXON`.
- The user wording is short or unsure: "calanus glaci", "copepode",
  "Oithonna".
- The user mixed Latin and vernacular and the right ID is non-obvious.

What `search_ecotaxa_taxa` returns:

- `taxon_id`, `nom`, EcoTaxa `statut` (`1` = validated, `0` = pending),
  `in_project` flag (whether at least one project uses it), `aphia_id`
  (WoRMS).

Never invent a `taxon_id`. If the autocomplete returns several
plausible matches and the user has not chosen, surface the markdown
table and ask which one to count. The Copepoda alias above still
applies for the broad "copépodes" wording — use it directly instead of
`search_ecotaxa_taxa` when the user clearly means the order-level count.

---

## Cache diagnostics — `get_ecotaxa_cache_status`

The `find_ecotaxa_samples_in_region`, `find_ecotaxa_projects_in_region`
and `find_ecotaxa_observations` tools all read the local SQLite cache
(`data/ecotaxa_cache.sqlite`), refreshed by the nightly MCP sync at 3
AM UTC. Call `get_ecotaxa_cache_status` whenever:

- a region/observation tool returned `CACHE_EMPTY`;
- the user asks "est-ce que le cache est à jour", "quand est-ce que ça
  a été synchronisé", "combien de samples sont indexés", "is the cache
  fresh";
- you are about to chain several zone+time queries and want to verify
  the cache is populated before committing to a long exploration.

Output covers: samples indexed, projects indexed, schemas indexed, last
sync timestamp, sync status (`success`, `running`, `failed`), error
message when present. The tool is read-only — it cannot trigger a
sync. When the cache is empty or stale, tell the user the operator
must call `POST /admin/resync` on the MCP server
(`http://mcp-ecotaxa:8001`) to populate or refresh the cache.

---

## Step 2 — scan samples before exporting

When the user has a list of 5–50 candidate samples and asks "lequel
vaut l'export ?", "qu'y a-t-il dedans ?", or before any export of
several samples, call `summarize_ecotaxa_samples(sample_ids=[...])`.

What it returns:

| Column | Meaning |
|---|---|
| `V` | validated objects in the sample |
| `P` | predicted objects (model output, NOT human-validated) |
| `D` | dubious objects (flagged uncertain) |
| `U` | unclassified objects (no taxon assigned yet) |
| `total` | sum of V+P+D+U |
| `top taxa` | up to 5 taxon names observed in the sample |

Routing rules:

- Use it instead of `query_ecotaxa_sample` when the user just wants to
  **know** what's in a sample. `query_ecotaxa_sample` downloads the
  whole thing.
- Use it for current-result ranking questions such as "lesquels de ces
  samples contiennent le plus d'objets ?" or "parmi ceux-là, lesquels
  semblent les plus riches ?" Rank by `total` unless the user names a
  more precise V/P/D/U metric.
- Use the batch form (`summarize_ecotaxa_samples`) over multiple
  single-sample calls — it issues one API call per batch.
- `summarize_ecotaxa_sample` (singular) is just sugar for one item;
  either form works.

Taxon-specific limitation:

- `summarize_ecotaxa_samples` exposes per-sample V/P/D/U totals and top
  taxa, but NOT exact per-sample counts for one named taxon.
- When the user asks "among these samples, which contain the most
  Copepoda / copepods / Calanus", first reuse the current visible
  sample IDs. Then:
  - if an approximate answer is acceptable from the summary, call
    `summarize_ecotaxa_samples(sample_ids=[...])`, rank only samples
    where the requested taxon appears in `top taxa`, and state that the
    ranking is based on sample totals/top-taxa presence, not exact
    per-taxon counts;
  - if exact taxon counts per sample are required, say the current
    read-only sample summary cannot provide them. Do NOT fall back to a fresh sample metadata listing. Exact object-level filtering requires an export/download path and therefore confirmation.

A sample with only `P` and no `V` means "model predictions, never
validated by a human" — flag this to the user before they treat the
numbers as ground truth. CT-AG-26 still applies (no interpretation
beyond surfacing the fact).

---

## Step 3 — export a selection (multi-project safe)

`export_ecotaxa_samples(sample_ids=[...], confirmed=False)`.

The tool resolves each `sample_id` to its `project_id` via the local
cache, groups them, and launches one `query_ecotaxa(project_id,
sample_ids=[...])` per project.

### Confirmation (mandatory, CT-AG-06)

Default `confirmed=False` → **dry-run only**. Returns the project →
sample_ids breakdown. ALWAYS show this plan to the user verbatim and
ask for explicit confirmation ("oui", "go", "lance", "confirme")
before calling again with `confirmed=True`.

If the user says "prépare l'export", "ne lance rien", "avant que je
confirme", or asks for an export plan, still call
`export_ecotaxa_samples(sample_ids=[...], confirmed=False)`. That call
is the dry-run plan, not the confirmed export. Do not stop after
`load_skill`.

If the user reports a previous `EXPORT_FAILED` / missing export rights
and asks to verify access without relaunching export, use
`preview_ecotaxa_project` or `list_ecotaxa_projects` only. Do not call
`query_ecotaxa`, `query_ecotaxa_sample`, or `export_ecotaxa_samples`.

The dry-run shape:

```
# Plan d'export — 12 samples sur 3 projets

| project_id | nb_samples | sample_ids |
|---:|---:|---|
| 14853 | 7 | 14853000003, 14853000002, … (+4) |
| 2331  | 3 | 2331000001, 2331000002, 2331000003 |
| 4042  | 2 | 4042000010, 4042000011 |
```

NEVER skip the dry-run by calling `confirmed=True` on the first turn,
even if the user wrote "exporte ces samples direct". The plan is the
ack moment — it lets the user spot a wrong project before paying the
download.

### After a confirmed run

The response groups successes and failures. Partial failures are
expected (e.g. one project restricted, others open) — surface BOTH:

- ✅ Successful projects → mention `n_rows`, the download link, the
  session variable (`df_ecotaxa_*`).
- ❌ Failed projects → relay the `EXPORT_FAILED` marker with HTTP code
  and server message. See section "EXPORT_FAILED handling" below.

### Unresolved samples

When some `sample_ids` are not in the cache, they are listed as
"⚠️ Samples absents du cache". Suggest a `/admin/resync` (the user, not
the agent, hits this endpoint) or verifying the IDs.

---

## EXPORT_FAILED handling (reminder)

A result starting with `EXPORT_FAILED` means EcoTaxa refused
server-side (usually missing `Export` right on a project, or the
project is private). Reaction:

1. Quote the server message verbatim to the user.
2. Suggest `preview_ecotaxa_project(<project_id>)` to confirm access.
3. Suggest an alternative project from the same zone via
   `find_ecotaxa_projects_in_region(zone_name=..., date_range=...)`.
4. NEVER fall back to `find_ecotaxa_samples_in_region` as if the export
   had succeeded — that produces metadata, not export data, and
   misleads the user.

---

## Worked example

User: "Sur tout ce qu'on a en Baie de Baffin en 2024, montre-moi ce
qu'il y a dans les samples LOKI, et exporte ceux qui ont du Calanus
validé."

```
1. find_ecotaxa_samples_in_region(
      zone_name="Baie de Baffin",
      date_range={"from": "2024-01-01", "to": "2024-12-31"},
      instrument="Loki",
   )
   → 3 samples: [2331000007, 2331000008, 2331000009]

2. summarize_ecotaxa_samples(sample_ids=[2331000007, 2331000008, 2331000009])
   → row 1: V=42, P=10, D=0, top: Calanus, Metridia
   → row 2: V=0,  P=80, D=0, top: Calanus, Oithona
   → row 3: V=15, P=5,  D=0, top: Pseudocalanus

3. The user reads the table, decides samples 1 and 3 have validated
   Calanus. Call:
   export_ecotaxa_samples(sample_ids=[2331000007, 2331000009])
   → dry-run: "projet 2331, 2 samples"

5. User confirms → export_ecotaxa_samples(
      sample_ids=[2331000007, 2331000009], confirmed=True,
      taxon="Calanus", status="V",
   )
   → ✅ Projet 2331 (2 samples) → 57 lignes, df_ecotaxa_2331_bulk_…
```

---

## What this skill explicitly does NOT cover

- Reading exported data (joins, computations) → that is `ecotaxa_query`
  (loaded after a successful export).
- Single-project download without a selection → use `query_ecotaxa`
  directly with a `project_id`.
- Single-sample download when the parent project is unknown → use
  `query_ecotaxa_sample`.
- Project schema, columns, or distribution checks →
  `inspect_ecotaxa_project_schema` / `inspect_ecotaxa_column`.
- Bio-ORACLE / EcoPart / Amundsen coupling → their respective skills.

---

## EcoTaxa tool reference — complete map

The 3-slice pipeline above is the **default path**, but the user may
need adjacent tools at any step. This section lists ALL EcoTaxa LC
tools so you can branch without thinking.

### Discover / locate a project

| Tool | When |
|---|---|
| `list_ecotaxa_projects()` | "quels projets j'ai accès" — full list of accessible projects. |
| `find_ecotaxa_projects(title=..., instrument=...)` | "cherche un projet UVP5 / Calanus / Amundsen" — keyword search. |
| `find_ecotaxa_projects_in_region(zone_name=..., date_range=..., depth_max_lt=..., depth_max_gte=..., depth_min_lt=..., depth_min_gte=...)` | "quels projets couvrent Baie de Baffin 2020-2022" — aggregate per project. Accepts `project_ids=` to narrow and depth filters at the sample level (a project is excluded when none of its samples match). |

### Locate samples (zone / time / taxon / project)

| Tool | When |
|---|---|
| `find_ecotaxa_samples_in_region(zone_name=..., date_range=..., project_ids=...)` | **Step 1 of the pipeline.** Default for "samples en zone X entre A et B", possibly narrowed by project. |
| `group_ecotaxa_project_samples_by_region(project_id=...)` | "groupe les samples du projet X par mer / secteur / zone / région" — returns `region -> sample_ids` plus `Hors zones IHO` and `Sans coordonnées`. |
| `find_ecotaxa_observations(taxon=..., zone_name=..., date_range=..., month=..., depth_max_lt=..., depth_max_gte=..., depth_min_lt=..., depth_min_gte=..., project_ids=...)` | "samples **avec Calanus** en Baie de Baffin", including month/depth filters — taxon-centric. Returns samples whose project has the taxon attested. PREFER this over `find_ecotaxa_samples_in_region` whenever the user names a taxon — drop in for step 1. |

### Inspect a project before export

| Tool | When |
|---|---|
| `preview_ecotaxa_project(project_id=...)` | "présente-moi le projet 1165", "à quoi ressemble le projet", "aperçu du projet", "combien d'objets, qq exemples" — metadata + 10 sample objects. Light. |
| `inspect_ecotaxa_project_schema(project_id=..., verbose=...)` | "quelles colonnes / champs / free fields a ce projet" — sample/acquisition/object levels. Check before exporting. |
| `inspect_ecotaxa_column(project_id=..., column_name=..., level=...)` | "valeurs de la colonne X / distribution de profondeur / stations distinctes" — distribution stats on one column. |
| `compare_ecotaxa_projects(project_ids=[...])` | "ces 3 projets sont-ils compatibles" — schema diff, type/level conflicts. Call BEFORE a multi-project export to spot blockers. |

### Inspect a sample

| Tool | When |
|---|---|
| `get_ecotaxa_sample(sample_id=...)` | "métadonnées du sample / station / volume filtré" — identifiers, lat/lon, original_id, all free fields. No taxa info. |
| `summarize_ecotaxa_sample(sample_id=...)` / `summarize_ecotaxa_samples(sample_ids=[...])` | **Step 2 of the pipeline.** V/P/D/U counts + top taxa per sample. Use for scanning before export. |

### Count / aggregate taxa

| Tool | When |
|---|---|
| `count_ecotaxa_taxa(project_ids=[...], taxa=[...])` | "combien de Calanus validés dans le projet X / sur ces 3 projets" — V/P/D counts per (project × taxon). Project-level only, NOT per-sample. |
| `search_ecotaxa_taxa(query=...)` | "comment EcoTaxa appelle ce taxon" — autocomplete to resolve `taxon_id` before counting / locating observations. Call FIRST whenever `count_ecotaxa_taxa` or `find_ecotaxa_observations` returns `AMBIGUOUS_TAXON`. |

### Cache diagnostics

| Tool | When |
|---|---|
| `get_ecotaxa_cache_status()` | "cache à jour", "combien de samples indexés", debug after a `CACHE_EMPTY` error. Reports counts + last sync status. Read-only — operator must call `POST /admin/resync` on the MCP server to refresh. |

### Export (download into the session)

| Tool | When |
|---|---|
| `query_ecotaxa(project_id=..., sample_ids=..., taxon=..., status=...)` | "charge / exporte le projet X" — full single-project export, optionally narrowed by `sample_ids` and `taxon`. |
| `query_ecotaxa_sample(sample_id=..., taxon=..., status=...)` | "exporte ce sample" — single sample, project resolved automatically. |
| `export_ecotaxa_samples(sample_ids=[...], confirmed=...)` | **Step 3 of the pipeline.** Multi-project sample selection in one call, with dry-run + per-project success/failure. Use when the selection spans 2+ projects OR when the user gave a flat list of sample_ids from an earlier table. |
| `summarize_ecotaxa_samples(selection_name="latest")` / `export_ecotaxa_samples(selection_name="latest", confirmed=...)` | Reuse the current named selection created by `find_ecotaxa_samples_in_region`. Use this when the user says "cette sélection", "ces samples", "le tableau précédent", or names the selection shown in the previous tool output. |

### Decision tree (which export tool?)

```
User wants to export…
├─ a whole project          → query_ecotaxa(project_id=X)
├─ one sample               → query_ecotaxa_sample(sample_id=S)
├─ N samples from 1 project → query_ecotaxa(project_id=X, sample_ids=[...])
└─ N samples from M projects → export_ecotaxa_samples(sample_ids=[...])
                                   (groups by project automatically)
```

### Common chains

| User intent | Tool chain |
|---|---|
| "projets EcoTaxa actifs en Baie de Baffin 2024" | `find_ecotaxa_projects_in_region(zone_name=..., date_range=...)` |
| "samples avec Calanus en mer du Labrador" | `find_ecotaxa_observations(taxon="Calanus", zone_name=...)` |
| "samples avec Calanus en juillet en Baie de Baffin qui n'ont pas atteint 100 m" | `find_ecotaxa_observations(taxon="Calanus", zone_name="Baie de Baffin", month=7, depth_max_lt=100)` |
| "samples en Baie de Baffin 2024 qui descendent en-dessous de 200 m" | `find_ecotaxa_samples_in_region(zone_name=..., date_range=..., depth_max_gte=200)` |
| "samples en Baie de Baffin 2024 qui ne touchent pas la surface (depth_min ≥ 50 m)" | `find_ecotaxa_samples_in_region(zone_name=..., date_range=..., depth_min_gte=50)` |
| "samples avec Copepoda en oct. 2024 dans la tranche 50-200 m max" | `find_ecotaxa_observations(taxon="Copepoda", zone_name=..., date_range=..., depth_max_gte=50, depth_max_lt=200)` |
| "samples avec Calanus dont le cast est contenu dans 50-200 m" | `find_ecotaxa_observations(taxon="Calanus", depth_min_gte=50, depth_max_lt=200)` |
| "objets de Copepoda à ~100 m dans le projet 14853 (export)" | `query_ecotaxa(project_id=14853, taxon="Copepoda", obj_depth_gte=95, obj_depth_lte=105)` (confirmer avant) |
| "projets EcoTaxa avec samples descendant à plus de 1000 m en Baie de Baffin 2024" | `find_ecotaxa_projects_in_region(zone_name="Baie de Baffin", date_range=..., depth_max_gte=1000)` |
| "qu'y a-t-il dans le projet 1165 ?" | `preview_ecotaxa_project(1165)` (light) — full nav only if user asks "explore tous les samples" |
| "samples LOKI dans Baie de Baffin" | `find_ecotaxa_samples_in_region(zone_name=..., instrument="Loki")` |
| "samples du projet LOKI dans Baie de Baffin" | `find_ecotaxa_projects(title="LOKI")` → `find_ecotaxa_samples_in_region(zone_name=..., project_ids=[<id>])` |
| "groupe les samples du projet 14853 par mer" | `group_ecotaxa_project_samples_by_region(project_id=14853)` |
| "scan ces 20 samples avant export" | `summarize_ecotaxa_samples(sample_ids=[...])` then user decides |
| "résume cette sélection" | `summarize_ecotaxa_samples(selection_name="latest")` |
| "exporte cette sélection" | `export_ecotaxa_samples(selection_name="latest", confirmed=False)` unless the user explicitly confirms the export |
| "parmi ceux-là, lesquels contiennent le plus de copepods ?" | Reuse the visible `sample_id` values → `summarize_ecotaxa_samples(sample_ids=[...])`; if exact per-sample Copepoda counts are required, state the read-only limitation instead of listing metadata again. |
| "parmi les samples présents, lesquels contiennent le plus de copepods ?" | Ambiguous unless a scope was just established. Ask whether "présents" means current table, EcoTaxa cache, or a specific project/zone. |
| "combien de Calanus validés dans ces 3 projets" | `count_ecotaxa_taxa(project_ids=[...], taxa=["Calanus"])` (skip the pipeline — count, not export) |
| "les colonnes de ce projet contiennent-elles profondeur" | `inspect_ecotaxa_project_schema(project_id=...)` |
| "peut-on merger ces 3 projets" | `compare_ecotaxa_projects(project_ids=[...])` before any export |
