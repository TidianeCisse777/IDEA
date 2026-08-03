---
name: amundsen_ctd_query
version: 1.0.4
triggers:
  - Explicit Amundsen CTD query or loaded-table enrichment intent
forbidden_when:
  - Amundsen is not authorized by the source decision
requires:
  - "source:amundsen"
next_tool: enrich_with_amundsen_ctd
max_tokens: 1050
---

# Skill: amundsen_ctd_query

## Activation

Use only when the Source Selection Gateway authorizes Amundsen CTD. A generic
temperature, salinity, or environment request without an explicit current
Amundsen CTD mention concerns the active table; it does not authorize Amundsen.
The loaded table stays primary and Amundsen is only its requested enrichment.

## Enrichment

When an Amundsen/CTD data or enrichment request names no measured variable,
present all eight supported CTD variables and wait for the user's selection;
do not call the remote enrichment yet:

- pressure/depth (`PRES`), temperature (`TE90`), salinity (`PSAL`),
  density (`SIGT`), oxygen (`OXYM`), pH (`pH`), nitrate (`NTRA`), and
  fluorescence (`FLOR`).

Show the readable name, CTD code, canonical output column, and short factual
description. A request for **all variables** is an explicit selection: call
the enrichment with all eight codes. A request naming one or more variables
proceeds directly with only those variables. Never choose a default subset for
the user. State the catalog exactly once, then stop and wait for the answer.

Call `enrich_with_amundsen_ctd` directly on the exact active variable for
“enrichis avec Amundsen”, “ajoute le CTD Amundsen”, or equivalent. The same
path applies when Amundsen CTD is named with a request for its data, measures,
parameters, or CTD/environmental variables: “donne les données Amundsen”,
“température et salinité Amundsen”, or “ajoute l'oxygène Amundsen”. The verb
*enrichir* is not required. This is the only canonical loaded-table enrichment
path.

Pass only variables requested by the user: `temperature`/`température`,
`salinité`/`salinity`, `oxygène`/`oxygen`, `nitrate`, `chlorophylle`,
`fluorescence`, `densité`, or `pression`. Do not infer a default set from a
broad environmental request; apply the selection rule above.

For an EcoTaxa export with `sample_ctdrosettefilename` (or an equivalent CTD
filename column), the tool automatically fetches the matching CTD profile by
filename and selects the closest `PRES` locally. It does not issue one query
per object depth. Without that filename, it falls back to the usual
latitude/longitude/time nearest-profile enrichment.

For a requested subset, first persist it with `run_pandas`, then pass its exact
`source_variable`; never enrich the original full table. Do not run discovery,
preview, or raw CTD retrieval first. Do not require station/cast identifiers or
reuse an earlier refusal. The canonical tool detects compatible position/time/depth
columns, batches ERDDAP, and preserves source rows; retain its blocked
diagnostic when metadata is insufficient.

For a complete vertical-profile graph after enrichment, call
`query_amundsen_profiles_for_table` on the exact selected table. It retrieves
every unique resolved `amundsen_station` + `amundsen_cast_number` pair and keeps
missing-cast statuses. Plot its full `PRES`-derived depth, not NeoLabs
`max_sample_depth`; `amundsen_pres_dbar` is only the matched CTD point. Never
present nearest enriched points as complete profiles.

The returned profile table already contains canonical plotting columns:
`depth_m`, `temperature_degC`, `salinity_psu`, `density_sigt`, `oxygen_oxym`,
`ph`, `nitrate_ntra`, and `fluorescence_flor` when requested. Do not rename raw `PRES`, `TE90`, or `PSAL` onto those canonical columns: both raw and canonical
columns are deliberately retained, and renaming would create duplicate column
labels. Select and convert the canonical columns directly.

## Constraints and result

Pass only explicit variables, `zone_name`, `date_range`, column overrides, or
tolerances. Treat only a successful tool result as success. Report rows,
matches, status/quality metrics, persisted variable, download, and provenance;
keep `no_match`, `matched_no_value`, and `outside_amundsen_ctd_range` visible.
Do not replace a failed result with another source or add scientific
interpretation.
