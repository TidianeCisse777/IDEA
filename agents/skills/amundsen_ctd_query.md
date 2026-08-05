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

Use when the Source Selection Gateway authorizes Amundsen CTD. On a loaded
table, `CTD`, `Amundsen` (including common misspellings), `donne les données
environnementales`, `ajoute les variables environnementales`, or equivalent
authorize the canonical Amundsen enrichment. A bare local temperature or
salinity analysis without these source/enrichment signals remains local. The
loaded table stays primary and Amundsen is only its requested enrichment.

## Enrichment

When an Amundsen/CTD data or enrichment request names no measured variable,
call the canonical enrichment immediately with all eight supported variables:

- pressure/depth (`PRES`), temperature (`TE90`), salinity (`PSAL`),
  density (`SIGT`), oxygen (`OXYM`), pH (`pH`), nitrate (`NTRA`), and
  fluorescence (`FLOR`).

A request naming one or more variables proceeds directly with only those
variables. Never replace the remote call with placeholder columns or a local
`run_pandas` simulation.

`acq_*` fields already present in an export are acquisition metadata. They are
not an Amundsen enrichment and must not be used as evidence that a remote CTD
match has been executed. Only the canonical result columns
`amundsen_match_status` and `amundsen_dataset_id`, with their returned
provenance, establish an Amundsen match.

Call `enrich_with_amundsen_ctd` directly on the exact active variable for
“enrichis avec Amundsen”, “ajoute le CTD Amundsen”, or equivalent. The same
path applies when Amundsen CTD is named with a request for its data, measures,
parameters, or CTD/environmental variables: “donne les données Amundsen”,
“température et salinité Amundsen”, or “ajoute l'oxygène Amundsen”. The verb
*enrichir* is not required. This is the only canonical loaded-table enrichment
path.

Pass only variables requested by the user when they name a subset:
`temperature`/`température`,
`salinité`/`salinity`, `oxygène`/`oxygen`, `nitrate`, `chlorophylle`,
`fluorescence`, `densité`, or `pression`. For a broad request, omit `variables`
or pass all eight CTD codes; both mean all variables.

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
