---
name: amundsen_ctd_query
version: 1.0.3
triggers:
  - Explicit Amundsen CTD query or loaded-table enrichment intent
forbidden_when:
  - Amundsen is not authorized by the source decision
requires:
  - "source:amundsen"
next_tool: enrich_with_amundsen_ctd
max_tokens: 700
---

# Skill: amundsen_ctd_query

## Activation

Use only when the Source Selection Gateway authorizes Amundsen CTD. A generic
temperature, salinity, or environment request without an explicit current
Amundsen CTD mention concerns the active table; it does not authorize Amundsen.
The loaded table stays primary and Amundsen is only its requested enrichment.

## Enrichment

Call `enrich_with_amundsen_ctd` directly on the exact active variable for
“enrichis avec Amundsen”, “ajoute le CTD Amundsen”, or equivalent. The same
path applies when Amundsen CTD is named with a request for its data, measures,
parameters, or CTD/environmental variables: “donne les données Amundsen”,
“température et salinité Amundsen”, or “ajoute l'oxygène Amundsen”. The verb
*enrichir* is not required. This is the only canonical loaded-table enrichment
path.

Pass only variables requested by the user: `temperature`/`température`,
`salinité`/`salinity`, `oxygène`/`oxygen`, `nitrate`, `chlorophylle`,
`fluorescence`, `densité`, or `pression`. For a broad environmental request,
keep the canonical default set.

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

## Constraints and result

Pass only explicit variables, `zone_name`, `date_range`, column overrides, or
tolerances. Treat only a successful tool result as success. Report rows,
matches, status/quality metrics, persisted variable, download, and provenance;
keep `no_match`, `matched_no_value`, and `outside_amundsen_ctd_range` visible.
Do not replace a failed result with another source or add scientific
interpretation.
