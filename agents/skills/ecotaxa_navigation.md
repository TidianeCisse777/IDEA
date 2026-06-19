# Skill: ecotaxa_navigation

Loaded when the user asks to **explore** or **export** EcoTaxa samples by
zone, time, project, or any combination — typically the path
**zone+time → drill into samples → export a selection**.

This skill bundles the 3-slice navigation flow so the rules don't bloat
the always-on system prompt.

---

## Mental model

Four tools form the navigation pipeline. Use them in this order whenever
the user explores before exporting. Project-level scan (1b) is optional
and lives between « list » and « scan samples ».

General ambiguity rule:

- Prefer read-only navigation tools over exports when the wording is
  ambiguous. "stats", "tableau", "résumé", "scan", "liste", "combien",
  "où", "quels samples/projets", "lesquels", "le plus", "top", and "rank"
  are exploration intents, not downloads.
- Follow-up wording such as "ces samples", "ce tableau", "parmi ceux-là",
  "among these", or "which of these" means the user is referring to the
  `sample_id` / `project_id` values already shown in the previous result.
  Reuse those IDs; do not run a new broad `find_ecotaxa_samples_in_region`
  call unless the user explicitly asks for a new geographic/project search.
- Wording such as "samples présents" or "present samples" is ambiguous unless
  the previous turn clearly established a table or scope. It can mean samples
  present in the EcoTaxa cache, the current UI result, or a project/zone
  subset. If the scope is unclear, ask one short clarification question.
- Instrument names remain filters even if the user wording is sloppy. In
  samples-by-zone queries, `LOKI` / `Loki` means instrument Loki and must be
  passed as `instrument="Loki"`; do not drop it and do not reinterpret it as a
  project search.
- If the user gives numeric project IDs and asks for project stats/summaries,
  call `summarize_ecotaxa_projects`; do not switch to `run_pandas` or
  `query_ecotaxa`.
- "résume le projet", "summary", "stats avant export", "scan projet",
  "tableau de stats", "V/P/D/U", "top taxa", "bbox", "date_min/date_max",
  or "instruments" are summary intents. Use
  `summarize_ecotaxa_project(project_id=X)` or
  `summarize_ecotaxa_projects(project_ids=[...])`, not
  `preview_ecotaxa_project`.
- `preview_ecotaxa_project` is only for preview/object examples such as
  "aperçu", "preview", or "montre quelques objets". It is not the project
  summary tool.
- Schema and column inspection are navigation/read-only intents too. If the
  user asks for one named column, call
  `inspect_ecotaxa_column(project_id=..., column_name="exact_user_column")`
  directly. Do not inspect the whole schema first unless the column is absent
  or ambiguous, and do not rewrite a clear column name into a nearby one.
- If the only plausible routes are a read-only summary and a full export,
  choose the read-only summary unless the user explicitly says "exporte",
  "charge", "download", or "récupère les objets".

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
project_ids=[...], instrument="...")`.

- The EcoTaxa public API has **no bbox/datetime endpoint** — this tool
  reads the local cache (`samples_cache` SQLite). That's why the cache
  exists and why this is the only valid path for « zone+time » queries.
- `zone_name` is preferred over `polygon_wkt` (the polygon never traverses
  the LLM).
- `project_ids` is a SQL `IN` filter, NOT a post-process. Use it when the
  user gives numeric project IDs or when a previous tool result already
  identified project IDs. In samples-by-zone queries, if the user says
  "LOKI" / "Loki" (even with sloppy wording such as "projet loki"), treat it
  as the instrument and pass `instrument="Loki"` instead of resolving a
  project title. Only search project names when the user explicitly asks to
  "chercher/trouver le projet nommé ...".
- At least one filter is required — refusing without any filter is by
  design (avoid dumping 100k samples on the user).

Output : markdown table with `sample_id | projet | lat | lon | date_min |
date_max | instrument`. The result is already clickable (sample IDs
linkified to `/prj/{project_id}?samples={sample_id}` and project IDs to
`/prj/{project_id}`).

---

## Step 1b — scan projects (optional, before drilling samples)

When the user has a list of candidate projects (e.g. output of
`find_ecotaxa_projects_in_region` or `list_ecotaxa_projects`) and wants
to know which ones are worth exploring further, call
`summarize_ecotaxa_projects(project_ids=[...])`.

What it gives per project :

| Column | Source |
|---|---|
| `n_samples` | local cache |
| `date_min` / `date_max` | local cache (temporal envelope) |
| `bbox` (S/W/N/E) | local cache (geographic envelope of sample centroids) |
| `instruments` | local cache (distinct list) |
| `V` / `P` / `D` / `U` | project-level aggregate from `/project_set/taxo_stats` |
| `top taxa` | `/project_set/taxo_stats?taxa_ids=all`, sorted by taxon volume and resolved to names |

This is the project-level pendant of `summarize_ecotaxa_samples`. Use it
to decide WHICH project to dig into. Mono-project sugar :
`summarize_ecotaxa_project(project_id=X)`.

DO NOT use this instead of `preview_ecotaxa_project` when the user just
wants metadata + a few example objects — `preview_ecotaxa_project` is
lighter for that case (no samples enumeration).

---

## Taxon counts inside projects

When the user asks for a count of one taxon in one or more projects, route to
`count_ecotaxa_taxa(project_ids=[...], taxa=[...])`.

Examples :

- "combien de copépodes validés dans le projet 14853"
- "combien de Copepoda dans 14853"
- "comptes V/P/D pour Calanus finmarchicus dans les projets 1165 et 2331"

Do NOT use `query_ecotaxa` for these questions. Counts are server-side stats,
not an export/download.

What the tool does :

1. Resolve each taxon string to an EcoTaxa `taxon_id`.
2. Call `/project_set/taxo_stats` with `ids=<project_ids>` and
   `taxa_ids=<taxon_id[,taxon_id...]>`.
3. Return V/P/D/U + total per `(project_id, taxon_id)`.

Important alias :

| User wording | EcoTaxa accepted taxon | taxon_id |
|---|---|---:|
| `copepod`, `copepods`, `copepoda`, `copépode`, `copépodes` | `Copepoda<Multicrustacea` | `25828` |

Why this matters : `search_taxa("Copepoda")` can return composite categories
first (e.g. `copepoda + actinopterygii`). For broad copepod counts, the
accepted EcoTaxa taxon is `Copepoda<Multicrustacea` (`25828`), and the stats
call must use `taxa_ids=25828`.

If the tool returns `AMBIGUOUS_TAXON`, show the candidate `taxon_id` list and
ask the user to choose; do not guess. If the user already provides an integer
taxon ID, pass it directly.

---

## Step 2 — scan samples before exporting

When the user has a list of 5–50 candidate samples and asks « lequel
vaut l'export ? », « qu'y a-t-il dedans ? », or before any export of
several samples, call `summarize_ecotaxa_samples(sample_ids=[...])`.

What it gives :

| Column | Meaning |
|---|---|
| `V` | validated objects in the sample |
| `P` | predicted objects (model output, NOT human-validated) |
| `D` | dubious objects (flagged uncertain) |
| `U` | unclassified objects (no taxon assigned yet) |
| `total` | sum of V+P+D+U |
| `top taxa` | up to 5 taxon names observed in the sample |

Routing rules :

- DO use it instead of `query_ecotaxa_sample` when the user just wants to
  **know** what's in a sample. `query_ecotaxa_sample` downloads the whole
  thing.
- DO use it for current-result ranking questions such as "lesquels de ces
  samples contiennent le plus d'objets ?" or "parmi ceux-là, lesquels semblent
  les plus riches ?" Rank by `total` unless the user names a more precise
  V/P/D/U metric.
- DO use the batch form (`summarize_ecotaxa_samples`) over multiple
  single-sample calls — it issues one API call per batch.
- `summarize_ecotaxa_sample` (singular) is just sugar for one item; either
  form works.

Taxon-specific limitation:

- `summarize_ecotaxa_samples` exposes per-sample V/P/D/U totals and top taxa,
  but NOT exact per-sample counts for one named taxon.
- If the user asks "among these samples, which contain the most Copepoda /
  copepods / Calanus", first reuse the current visible sample IDs. Then:
  - if an approximate answer is acceptable from the summary, call
    `summarize_ecotaxa_samples(sample_ids=[...])`, rank only samples where the
    requested taxon appears in `top taxa`, and state that the ranking is based
    on sample totals/top-taxa presence, not exact per-taxon counts;
  - if exact taxon counts per sample are required, say the current read-only
    sample summary cannot provide them. Do NOT fall back to a fresh sample
    metadata listing. Exact object-level filtering requires an export/download
    path and therefore confirmation.

A sample with only `P` and no `V` means « model predictions, never
validated by a human » — flag this to the user before they treat the
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
sample_ids breakdown. ALWAYS show this plan to the user verbatim and ask
for explicit confirmation (« oui », « go », « lance », « confirme »)
before calling again with `confirmed=True`.

If the user says "prépare l'export", "ne lance rien", "avant que je confirme",
or asks for an export plan, still call
`export_ecotaxa_samples(sample_ids=[...], confirmed=False)`. That call is the
dry-run plan, not the confirmed export. Do not stop after `load_skill`.

The dry-run shape :

```
# Plan d'export — 12 samples sur 3 projets

| project_id | nb_samples | sample_ids |
|---:|---:|---|
| 14853 | 7 | 14853000003, 14853000002, … (+4) |
| 2331  | 3 | 2331000001, 2331000002, 2331000003 |
| 4042  | 2 | 4042000010, 4042000011 |
```

NEVER skip the dry-run by calling `confirmed=True` on the first turn,
even if the user wrote « exporte ces samples direct ». The plan is the
ack moment — it lets the user spot a wrong project before paying the
download.

### After a confirmed run

The response groups successes and failures. Partial failures are
expected (e.g. one project restricted, others open) — surface BOTH :

- ✅ Successful projects → mention `n_rows`, the download link, the
  session variable (`df_ecotaxa_*`).
- ❌ Failed projects → relay the `EXPORT_FAILED` marker with HTTP code
  and server message. See `Section: EXPORT_FAILED handling` below.

### Unresolved samples

If some `sample_ids` are not in the cache, they're listed as « ⚠️
Samples absents du cache ». Suggest a `/admin/resync` (the user, not the
agent, hits this endpoint) or verifying the IDs.

---

## EXPORT_FAILED handling (reminder)

A result starting with `EXPORT_FAILED` means EcoTaxa refused server-side
(usually missing `Export` right on a project, or project private).
Reaction :

1. Quote the server message verbatim to the user.
2. Suggest `preview_ecotaxa_project(<project_id>)` to confirm access.
3. Suggest an alternative project from the same zone via
   `find_ecotaxa_projects_in_region(zone_name=..., date_range=...)`.
4. NEVER fall back to `find_ecotaxa_samples_in_region` as if the export
   had succeeded — that produces metadata, not export data, and misleads
   the user.

---

## Worked example

User : « Sur tout ce qu'on a en Baie de Baffin en 2024, montre-moi ce
qu'il y a dans les samples LOKI, et exporte ceux qui ont du Calanus
validé. »

```
1. find_ecotaxa_samples_in_region(
      zone_name="Baie de Baffin",
      date_range={"from": "2024-01-01", "to": "2024-12-31"},
      instrument="Loki",
   )
   → 3 samples : [2331000007, 2331000008, 2331000009]

2. summarize_ecotaxa_samples(sample_ids=[2331000007, 2331000008, 2331000009])
   → row 1 : V=42, P=10, D=0, top: Calanus, Metridia
   → row 2 : V=0,  P=80, D=0, top: Calanus, Oithona
   → row 3 : V=15, P=5,  D=0, top: Pseudocalanus

3. The user reads the table, decides samples 1 and 3 have validated
   Calanus. Call :
   export_ecotaxa_samples(sample_ids=[2331000007, 2331000009])
   → dry-run : « projet 2331, 2 samples »

5. User confirms → export_ecotaxa_samples(
      sample_ids=[2331000007, 2331000009], confirmed=True,
      taxon="Calanus", status="V",
   )
   → ✅ Projet 2331 (2 samples) → 57 lignes, df_ecotaxa_2331_bulk_…
```

---

## What this skill explicitly does NOT cover

- Reading exported data (joins, computations) → that's `ecotaxa_query`
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

The 3-slice pipeline above is the **default path**, but the user may need
adjacent tools at any step. This section lists ALL EcoTaxa LC tools so
you can branch without thinking.

### Discover / locate a project

| Tool | When |
|---|---|
| `list_ecotaxa_projects()` | « quels projets j'ai accès » — full list of accessible projects. |
| `find_ecotaxa_projects(title=..., instrument=...)` | « cherche un projet UVP5 / Calanus / Amundsen » — keyword search. |
| `find_ecotaxa_projects_in_region(zone_name=..., date_range=...)` | « quels projets couvrent Baie de Baffin 2020-2022 » — aggregate per project. Accepts `project_ids=` to narrow. |

### Locate samples (zone / time / taxon / project)

| Tool | When |
|---|---|
| `find_ecotaxa_samples_in_region(zone_name=..., date_range=..., project_ids=...)` | **Step 1 of the pipeline.** Default for « samples en zone X entre A et B », possibly narrowed by project. |
| `find_ecotaxa_observations(taxon=..., zone_name=..., date_range=..., project_ids=...)` | « samples **avec Calanus** en Baie de Baffin » — taxon-centric. Returns samples whose project has the taxon attested. PREFER this over `find_ecotaxa_samples_in_region` whenever the user names a taxon — drop in for step 1. |

### Inspect a project before export

| Tool | When |
|---|---|
| `preview_ecotaxa_project(project_id=...)` | « aperçu du projet 1165 », « combien d'objets, qq exemples » — metadata + 10 sample objects. Light. |
| `inspect_ecotaxa_project_schema(project_id=..., verbose=...)` | « quelles colonnes / champs / free fields a ce projet » — sample/acquisition/object levels. Check before exporting. |
| `inspect_ecotaxa_column(project_id=..., column_name=..., level=...)` | « valeurs de la colonne X / distribution de profondeur / stations distinctes » — distribution stats on one column. |
| `compare_ecotaxa_projects(project_ids=[...])` | « ces 3 projets sont-ils compatibles » — schema diff, type/level conflicts. Call BEFORE a multi-project export to spot blockers. |

### Inspect a sample

| Tool | When |
|---|---|
| `get_ecotaxa_sample(sample_id=...)` | « métadonnées du sample / station / volume filtré » — identifiers, lat/lon, original_id, all free fields. No taxa info. |
| `summarize_ecotaxa_sample(sample_id=...)` / `summarize_ecotaxa_samples(sample_ids=[...])` | **Step 2 of the pipeline.** V/P/D/U counts + top taxa per sample. Use for scanning before export. |

### Count / aggregate taxa

| Tool | When |
|---|---|
| `count_ecotaxa_taxa(project_ids=[...], taxa=[...])` | « combien de Calanus validés dans le projet X / sur ces 3 projets » — V/P/D counts per (project × taxon). Project-level only, NOT per-sample. |

### Export (download into the session)

| Tool | When |
|---|---|
| `query_ecotaxa(project_id=..., sample_ids=..., taxon=..., status=...)` | « charge / exporte le projet X » — full single-project export, optionally narrowed by `sample_ids` and `taxon`. |
| `query_ecotaxa_sample(sample_id=..., taxon=..., status=...)` | « exporte ce sample » — single sample, project resolved automatically. |
| `export_ecotaxa_samples(sample_ids=[...], confirmed=...)` | **Step 3 of the pipeline.** Multi-project sample selection in one call, with dry-run + per-project success/failure. Use when the selection spans 2+ projects OR when the user gave a flat list of sample_ids from an earlier table. |

### Decision tree (which export tool ?)

```
User wants to export…
├─ a whole project        → query_ecotaxa(project_id=X)
├─ one sample              → query_ecotaxa_sample(sample_id=S)
├─ N samples from 1 project → query_ecotaxa(project_id=X, sample_ids=[...])
└─ N samples from M projects → export_ecotaxa_samples(sample_ids=[...])
                                   (groups by project automatically)
```

### Common chains

| User intent | Tool chain |
|---|---|
| « projets EcoTaxa actifs en Baie de Baffin 2024 » | `find_ecotaxa_projects_in_region(zone_name=..., date_range=...)` |
| « samples avec Calanus en mer du Labrador » | `find_ecotaxa_observations(taxon="Calanus", zone_name=...)` |
| « qu'y a-t-il dans le projet 1165 ? » | `preview_ecotaxa_project(1165)` (light) — full nav only if user asks « explore tous les samples » |
| « samples LOKI dans Baie de Baffin » | `find_ecotaxa_samples_in_region(zone_name=..., instrument="Loki")` |
| « samples du projet LOKI dans Baie de Baffin » | `find_ecotaxa_projects(title="LOKI")` → `find_ecotaxa_samples_in_region(zone_name=..., project_ids=[<id>])` |
| « scan ces 20 samples avant export » | `summarize_ecotaxa_samples(sample_ids=[...])` then user decides |
| « parmi ceux-là, lesquels contiennent le plus de copepods ? » | Reuse the visible `sample_id` values → `summarize_ecotaxa_samples(sample_ids=[...])`; if exact per-sample Copepoda counts are required, state the read-only limitation instead of listing metadata again. |
| « parmi les samples présents, lesquels contiennent le plus de copepods ? » | Ambiguous unless a scope was just established. Ask whether "présents" means current table, EcoTaxa cache, or a specific project/zone. |
| « combien de Calanus validés dans ces 3 projets » | `count_ecotaxa_taxa(project_ids=[...], taxa=["Calanus"])` (skip the pipeline — count, not export) |
| « les colonnes de ce projet contiennent-elles profondeur » | `inspect_ecotaxa_project_schema(project_id=...)` |
| « peut-on merger ces 3 projets » | `compare_ecotaxa_projects(project_ids=[...])` before any export |
