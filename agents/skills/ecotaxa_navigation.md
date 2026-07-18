---
name: ecotaxa_navigation
version: 2.0.0
triggers:
  - Explicit EcoTaxa discovery, navigation, read-only inspection, or export planning intent
forbidden_when:
  - EcoTaxa is not authorized by the source decision
requires:
  - "source:ecotaxa"
next_tool: null
max_tokens: 9500
size_exemption: The read-only EcoTaxa decision tree is kept atomic so the model can choose one route without loading a second navigation fragment; runtime delivery is budget-aware and tested end to end.
---

# Skill: ecotaxa_navigation

## Activation precondition

Apply this skill only when the Source Selection Gateway authorizes EcoTaxa,
either by an explicit current request or an inherited active-source follow-up.
Do not load or apply this skill for generic requests about samples, projects,
stations, positions, zones, maps, counts, or analyses. A loaded file remains
the default source unless the gateway authorizes EcoTaxa.

---

## Central exploration path — `query_ecotaxa_cache`

**All zone / time / region / grouping / ranking queries go through
`query_ecotaxa_cache(sql=...)`.**

The cache is a local SQLite database (`data/ecotaxa_cache.sqlite`).
Write read-only `SELECT` statements — no `INSERT`, `UPDATE`, `DELETE`.

### `samples_cache` schema

| Column | Type | Notes |
|---|---|---|
| `sample_id` | INTEGER PK | EcoTaxa sample ID |
| `project_id` | INTEGER | Parent project |
| `lat_avg` | REAL | Sample centroid latitude (WGS84) |
| `lon_avg` | REAL | Sample centroid longitude (WGS84) |
| `date_min` | TEXT | ISO date, earliest object |
| `date_max` | TEXT | ISO date, latest object |
| `depth_min` | REAL | Shallowest object depth (m) |
| `depth_max` | REAL | Deepest object depth (m) |
| `object_count` | INTEGER | Total objects in the sample |
| `instrument` | TEXT | e.g. "UVP6", "UVP5SD", "Loki" |
| `profile_id` | TEXT | Cast identifier (use for distinct casts) |
| `station_id` | TEXT | Station label |
| `original_id` | TEXT | Free-field original identifier |
| `free_fields_json` | TEXT | Raw JSON free fields |
| `iho_zone` | TEXT | Zone IHO/MEOW assignée par point-in-polygon au sync (ex. `"Baie de Baffin"`, `"MEOW: Northern Labrador"`, `"Hors zone référencée"`) |

`objects_cache` also exists; join on `sample_id`. Validated objects =
`classification_status = 'V'`.

### Zone queries — utiliser `iho_zone` directement

Le cache a une colonne `iho_zone` pré-calculée par point-in-polygon (IHO puis MEOW).
Toujours utiliser `LIKE` pour filtrer les zones — jamais `=` (les apostrophes et accents cassent silencieusement `=`).

```sql
WHERE iho_zone LIKE '%Baffin%'
WHERE iho_zone LIKE '%Hudson%'
WHERE iho_zone LIKE 'MEOW: %'
GROUP BY iho_zone
```

**Règle apostrophe/accent** : ne jamais écrire `WHERE iho_zone = 'Détroit d''Hudson'`. Toujours `LIKE '%Détroit%Hudson%'` ou `LIKE '%Hudson%'`.

**Invariance linguistique** : l'utilisateur peut nommer les zones en français ou en anglais. Convertir avant la requête :

| Ce que dit l'utilisateur | `LIKE` à utiliser |
|---|---|
| Hudson Strait / Détroit d'Hudson | `LIKE '%Hudson%'` + exclure `'%Baie%'` si besoin |
| Hudson Bay / Baie d'Hudson | `LIKE '%Hudson%'` + `NOT LIKE '%Détroit%'` |
| Baffin Bay / Baie de Baffin | `LIKE '%Baffin%'` |
| Davis Strait / Détroit de Davis | `LIKE '%Davis%'` |
| Labrador Sea / Mer du Labrador | `LIKE '%Labrador%'` |
| Beaufort Sea / Mer de Beaufort | `LIKE '%Beaufort%'` |
| Gulf of St. Lawrence / Golfe du Saint-Laurent | `LIKE '%Laurent%'` ou `LIKE '%Saint%Laurent%'` |
| Lincoln Sea / Mer de Lincoln | `LIKE '%Lincoln%'` |
| Arctic / Arctique | `LIKE '%Arctique%'` ou `LIKE '%Arctic%'` |

**Règle d'ambiguïté obligatoire** : quand le LIKE ramène plusieurs zones distinctes (ex. `Baie d'Hudson` + `Détroit d'Hudson`), NE PAS choisir silencieusement. Afficher la liste des zones trouvées avec leur nombre de samples, puis s'arrêter et demander : "Ces deux zones correspondent — laquelle vous intéresse, ou les deux ?" Ne passer à l'analyse qu'après confirmation explicite.

Ne plus utiliser `get_zone_info` + bbox pour les requêtes de zone — `iho_zone` est plus précis.
`get_zone_info` reste utile pour afficher la description d'une zone à l'utilisateur.

### Common SQL patterns

**Samples in a zone + time window:**
```sql
SELECT sample_id, project_id, lat_avg, lon_avg, date_min, date_max,
       depth_min, depth_max, instrument
FROM samples_cache
WHERE iho_zone = 'Baie de Baffin'
  AND date_min >= '2024-01-01'
  AND date_max <= '2024-12-31'
ORDER BY date_min
```

**Projects in a zone (aggregate):**
```sql
SELECT project_id,
       COUNT(*) AS n_samples,
       MIN(date_min) AS date_min, MAX(date_max) AS date_max,
       GROUP_CONCAT(DISTINCT instrument) AS instruments
FROM samples_cache
WHERE iho_zone = 'Baie de Baffin'
GROUP BY project_id
ORDER BY n_samples DESC
```

**Samples per year in a zone:**
```sql
SELECT strftime('%Y', date_min) AS year,
       COUNT(*) AS n_samples,
       COUNT(DISTINCT profile_id) AS n_casts
FROM samples_cache
WHERE iho_zone = 'Baie de Baffin'
GROUP BY year ORDER BY year
```

**Rank all zones by cast count:**
```sql
SELECT iho_zone,
       COUNT(DISTINCT profile_id) AS n_casts,
       COUNT(*) AS n_samples,
       MIN(date_min) AS date_min, MAX(date_max) AS date_max
FROM samples_cache
WHERE iho_zone != 'Hors zone référencée'
GROUP BY iho_zone
ORDER BY n_casts ASC
```

**Samples of one project by zone:**
```sql
SELECT iho_zone,
       COUNT(*) AS n_samples,
       GROUP_CONCAT(sample_id) AS sample_ids
FROM samples_cache
WHERE project_id = 17498
GROUP BY iho_zone
ORDER BY n_samples DESC
```

**Casts avec position (pour carte) — toujours inclure lat/lon :**
```sql
SELECT profile_id AS cast_id,
       AVG(lat_avg) AS lat,
       AVG(lon_avg) AS lon,
       COUNT(DISTINCT sample_id) AS n_samples,
       MIN(date_min) AS date_min,
       MAX(date_max) AS date_max,
       GROUP_CONCAT(DISTINCT instrument) AS instruments
FROM samples_cache
WHERE iho_zone LIKE '%Détroit%Hudson%'
GROUP BY profile_id
ORDER BY date_min
```

Règle : dès que l'utilisateur demande d'afficher des casts sur une carte, toujours inclure `AVG(lat_avg) AS lat` et `AVG(lon_avg) AS lon` dans le SELECT groupé par `profile_id`.

**Depth filter — `depth_max`:**
- `depth_max_gte=200` → `depth_max >= 200` ("descend en-dessous de 200 m")
- `depth_max_lt=100` → `depth_max < 100` ("n'a pas atteint 100 m")
- `depth_min_gte=50` → `depth_min >= 50` ("ne touche pas la surface")

**Instrument filter:**
```sql
WHERE instrument = 'Loki'   -- exact match, case-sensitive
```
"LOKI" / "loki" / "projet LOKI" = instrument `'Loki'` unless the user explicitly says "projet nommé LOKI".

**Cache status:**
```sql
SELECT COUNT(*) AS n_samples, COUNT(DISTINCT project_id) AS n_projects FROM samples_cache;
SELECT status, ended_at FROM sync_runs ORDER BY run_id DESC LIMIT 1;
```

After `query_ecotaxa_cache`, use `run_pandas` for derived tables, joins,
rankings, or cross-source comparisons. The result is available as
`df_ecotaxa_cache_query`.

---

## Navigation pipeline

```
1. FIND (query_ecotaxa_cache SQL)
   WHERE iho_zone = '...' → SELECT from samples_cache
   Result: table of sample_id, project_id, lat, lon, dates, depth, instrument

1b. PROJECT SCAN (optional, before drilling)
    query_ecotaxa_cache GROUP BY project_id → n_samples, envelope, instruments
    + count_ecotaxa_taxa(project_ids=[...], taxa=[...]) for V/P/D/U stats

2. SAMPLE SCAN (optional, before export)
   summarize_ecotaxa_samples(sample_ids=[...])
   → V/P/D/U + top taxa per sample — one API call, no download

3. EXPORT (confirmed)
   export_ecotaxa_samples(sample_ids=[...], confirmed=False)  ← dry-run first
   export_ecotaxa_samples(sample_ids=[...], confirmed=True)   ← after user ack
```

---

## Ambiguity rules

- **STOP rule — ambiguous "samples présents" / "qu'est-ce qu'on a"**: when
  no scope was established in the previous turn, ask ONE clarifying question
  with 2–3 concrete options. Call ZERO tools this turn.
- Follow-up wording ("ces samples", "ce tableau", "parmi ceux-là") means
  reuse the `sample_id` values already shown. Do not launch a new search.
- "stats", "tableau", "résumé", "scan", "liste", "combien", "où", "top",
  "rank" → read-only SQL path, not export.
- When the user gives numeric `project_ids` and wants project stats →
  `query_ecotaxa_cache` GROUP BY project_id, optionally `count_ecotaxa_taxa`
  for V/P/D/U. Do not route to `run_pandas` or `query_ecotaxa`.
- Cache is not the source: a sample absent from the cache may still exist
  in EcoTaxa. Use `describe_ecotaxa_project_coverage(project_id=...)` to
  distinguish a real absence (`vide_source`) from `non_indexe` / `partiel`.
- When the only plausible routes are a read-only summary and a full export,
  choose the read-only SQL path unless the user says "exporte", "charge",
  or "download".

---

## Step 2 — scan samples before exporting

`summarize_ecotaxa_samples(sample_ids=[...])` — one API call per batch.

| Column | Meaning |
|---|---|
| `V` | validated objects |
| `P` | predicted (model output, NOT human-validated) |
| `D` | dubious |
| `U` | unclassified |
| `top taxa` | up to 5 taxon names per sample |

Use for "lequel vaut l'export ?", "qu'y a-t-il dedans ?", current-result
ranking by `total`. Exact per-taxon counts per sample require an export.

A sample with only `P` and no `V` = model predictions never validated —
flag to the user before they treat numbers as ground truth.

---

## Step 3 — export (multi-project safe)

`export_ecotaxa_samples(sample_ids=[...], confirmed=False)` — always
dry-run first. Shows the project → sample_ids breakdown. Only call with
`confirmed=True` after explicit user confirmation ("oui", "go", "lance").

Never skip the dry-run even if the user says "exporte direct".

After a confirmed run, surface both ✅ successes (n_rows, download link,
`df_ecotaxa_*` variable) and ❌ failures (EXPORT_FAILED + HTTP code).

**Export tool selection:**
```
├─ whole project          → query_ecotaxa(project_id=X)
├─ one sample             → query_ecotaxa_sample(sample_id=S)
├─ N samples, 1 project   → query_ecotaxa(project_id=X, sample_ids=[...])
└─ N samples, M projects  → export_ecotaxa_samples(sample_ids=[...])
```

After `EXPORT_FAILED`: quote the server message, suggest
`preview_ecotaxa_project(project_id=...)` to verify access. Do not fall
back to a cache query as if the export had succeeded.

---

## Taxon counts — `count_ecotaxa_taxa`

For "combien de Calanus validés dans le projet 17498":
`count_ecotaxa_taxa(project_ids=[17498], taxa=["Calanus"])` →
V/P/D/U per (project × taxon). Project-level only, NOT per-sample.

Broad copepod alias: `Copepoda<Multicrustacea` (taxon_id 25828). When
`count_ecotaxa_taxa` returns `AMBIGUOUS_TAXON`, call
`search_ecotaxa_taxa(query=...)` first to resolve the ID, then retry.
Never invent a `taxon_id`.

---

## Taxon observations — `find_ecotaxa_observations`

Use when the user names a taxon AND a zone/date: "samples avec Calanus en
Baie de Baffin". Prefer over a cache SQL when taxon presence is the
primary filter — it searches directly via EcoTaxa project stats.

---

## Project and sample inspection tools

| Tool | When |
|---|---|
| `list_ecotaxa_projects()` | "quels projets j'ai accès" |
| `find_ecotaxa_projects(title=..., instrument=...)` | keyword search on project names |
| `preview_ecotaxa_project(project_id=...)` | metadata + 10 example objects — light first look |
| `inspect_ecotaxa_project_schema(project_id=...)` | column/field list before export |
| `inspect_ecotaxa_column(project_id=..., column_name=...)` | distribution of one column |
| `compare_ecotaxa_projects(project_ids=[...])` | schema diff before multi-project export |
| `get_ecotaxa_sample(sample_id=...)` | full metadata of one sample (no taxa) |
| `resolve_ecotaxa_sample(reference=..., project_id=...)` | resolve a label/station/profile to sample_id |
| `list_ecotaxa_sample_objects(sample_id=...)` | paginated object list, read-only (no export) |
| `get_ecotaxa_object(object_id=...)` | detail of one object from `list_ecotaxa_sample_objects` |
| `describe_ecotaxa_project_coverage(project_id=...)` | cache vs network reconciliation |

**resolve_ecotaxa_sample priority rule:** when the user gives a label,
station, profile, deployment, or numeric ID without a grounded project,
call `resolve_ecotaxa_sample` immediately — do not call the RAG, do not
guess a project, do not explain a procedure instead of executing.

---

## Common chains

| User intent | Tool chain |
|---|---|
| "samples en Baie de Baffin 2024" | `query_ecotaxa_cache` WHERE iho_zone = 'Baie de Baffin' AND date_min >= '2024-01-01' |
| "projets en Baie de Baffin 2024" | `query_ecotaxa_cache` WHERE iho_zone = 'Baie de Baffin' GROUP BY project_id |
| "samples par année en Baie de Baffin" | `query_ecotaxa_cache` WHERE iho_zone = 'Baie de Baffin' GROUP BY strftime('%Y', date_min) |
| "zones les moins échantillonnées" | `query_ecotaxa_cache` GROUP BY iho_zone ORDER BY COUNT(DISTINCT profile_id) ASC |
| "groupe les samples du projet 17498 par zone" | `query_ecotaxa_cache` WHERE project_id = 17498 GROUP BY iho_zone |
| "samples LOKI dans Baie de Baffin" | `query_ecotaxa_cache` WHERE iho_zone = 'Baie de Baffin' AND instrument = 'Loki' |
| "samples avec Calanus en mer du Labrador" | `find_ecotaxa_observations(taxon="Calanus", zone_name=...)` |
| "combien de Calanus validés dans ces 3 projets" | `count_ecotaxa_taxa(project_ids=[...], taxa=["Calanus"])` |
| "scan ces 20 samples avant export" | `summarize_ecotaxa_samples(sample_ids=[...])` |
| "exporte cette sélection" | `export_ecotaxa_samples(sample_ids=[...], confirmed=False)` then user confirms |
| "les colonnes de ce projet" | `inspect_ecotaxa_project_schema(project_id=...)` |
| "ces 3 projets sont-ils compatibles" | `compare_ecotaxa_projects(project_ids=[...])` |
| "qu'y a-t-il dans le projet 1165 ?" | `preview_ecotaxa_project(1165)` |

---

## Runtime routing contract

- For any EcoTaxa navigation request with a named zone: (1) `load_skill("ecotaxa_navigation")`, (2) `query_ecotaxa_cache` with `WHERE iho_zone = '...'` — do NOT call `get_zone_info` for zone filtering.
- With multiple named zones, use `WHERE iho_zone IN ('Zone A', 'Zone B')` or a `CASE iho_zone` label before graphing — never plot only the last selection.
- For object-level browsing (read-only): `list_ecotaxa_sample_objects`, NOT `query_ecotaxa_sample`.
- EcoTaxa dry-run export ("prépare l'export", "mais ne lance rien"): call `export_ecotaxa_samples(..., confirmed=False)` — do not stop after loading the skill.
- After a previous `EXPORT_FAILED` / rights failure: use `preview_ecotaxa_project(project_id=...)` to verify access; do not call `query_ecotaxa` or `export_ecotaxa_samples`.
- For distribution/stats on one column: `inspect_ecotaxa_column(project_id=..., column_name=...)`.
- Preserve EcoTaxa source links: `https://ecotaxa.obs-vlfr.fr/prj/{project_id}` and `?samples={sample_id}`.
- A no-export approximation uses `summarize_ecotaxa_samples(sample_ids=[...])`. Exact per-sample counts for one taxon require an export/download path with confirmation.
