# Skill: amundsen_ctd_query

## Activation precondition

Apply this skill only when the current user request explicitly names Amundsen CTD
and the active session does not forbid Amundsen CTD. Do not load or apply this skill
for generic requests about samples, projects, stations, positions, zones,
temperature, salinity, environment, maps, or analyses. A loaded file remains
the default source unless the user explicitly requests Amundsen CTD.

You just called `query_amundsen_ctd`, `enrich_loaded_table_with_amundsen_ctd`,
or `enrich_with_amundsen_ctd`.
The Amundsen vertical CTD profile is now loaded, exported or joined to the
active table in the session.

---

## Routing rule

- To see available datasets (rare, only on explicit user request): `list_amundsen_datasets`.
- For a quick profile preview: `preview_amundsen_profile`.
- To load, export, download or analyse ONE specific vertical profile (single station/cast): `query_amundsen_ctd`.
- **To enrich a table already loaded in the session** with CTD context (the default expectation when the user says "enrichis avec le CTD", "joins avec Amundsen", "ajoute les variables CTD à mes samples"): `enrich_loaded_table_with_amundsen_ctd`. This is a one-shot tool — it handles catalogue lookup, per-profile fetch and join internally. **Do not** chain `list_amundsen_datasets` or `query_amundsen_ctd` before it.
- If the source table has latitude/longitude/time but no reliable station/cast
  keys, use `enrich_with_amundsen_ctd`. It deduplicates repeated
  coordinate/time/depth rows, batches ERDDAP requests by month with coarse
  spatial splitting for broad months, adds `PRES` constraints around source
  depths, caps source points and CTD rows per batch, then only splits rejected
  batches more finely. This is the safer path for large NeoLabs/EcoTaxa files.

---

## Enriching a loaded table — the short path

The expected flow when the user already has a table in session (EcoTaxa samples,
local file, SQL query result, …) and wants CTD context:

1. Identify the station and cast columns of the loaded table from what you
   already saw at load time (or one quick `run_pandas` on the columns list if
   unsure). Common pairs: `station_id` + `cast_id`, `station` + `cast_number`,
   `sample_station` + `sample_cast`.
2. Call `enrich_loaded_table_with_amundsen_ctd(station_column=..., cast_column=...)`
   in a SINGLE call. Add `depth_column=...` if the table has a real (non-null)
   depth column to pick the nearest CTD measurement.
3. The result is stored as `df_ctd_enriched` (latest alias) and a stable
   `df_amundsen_enriched_<fingerprint>` variable. Use it directly in the next
   `run_pandas` / `run_graph` — no extra join needed.

If the table lacks both station/cast AND latitude/longitude/time, the tool
returns `ctd_match_status=missing_sample_metadata` with a diagnostic preview.
Report that diagnostic to the user; do not try to invent a fallback join.

---

## What Amundsen CTD contains

- `amundsen12713` is the main vertical CTD dataset.
- Raw columns must remain unchanged.
- Join aliases added to the output are helpers for joining with zooplankton data — do not replace the original columns with them.

---

## After loading

1. Include the download link returned by the tool in your response.
2. Use depth, station, cast and time columns as join keys.
3. Do not interpret the profiles biologically — provide data and comparisons only.

---

## Limits

- The profile must stay raw and traceable.
- Aliases are helpers, not a substitute for the original columns.

## Runtime routing contract

- Dataset discovery for `amundsen12713` uses `list_amundsen_datasets`; one-profile inspection uses `preview_amundsen_profile`; a full explicit retrieval uses `query_amundsen_ctd`.
- For a loaded file request such as "récupère ça avec Amundsen Science", call `enrich_loaded_table_with_amundsen_ctd`/the standard enrichment path. Surface `missing_sample_metadata`; do not use `query_amundsen_ctd` for a whole loaded file.
