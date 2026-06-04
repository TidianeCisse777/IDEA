# Copepod Graph Happy Path Matrix

Reference matrix for the next lean eval batch focused on graph generation after
the document-comprehension stage. The goal is to verify that the system prompt
fix pushes the model through:

- reasoning visible in the reply
- Python plotting code in a fenced block
- production-oriented graph flow on enriched fixtures

## Scope

We separate two behaviours:

- `raisonnement + code`
- `production flow`

We prioritize fixtures that are already enriched or easy to use for meaningful
analysis, so the first batch maximizes the happy path instead of testing noisy
raw-table failures.

## Matrix

| Scenario slug | Type | Fixture(s) | Why this fixture | Candidate prompt |
|---|---|---|---|---|
| `ecotaxa_simple_reasoning_code` | `raisonnement + code` | `/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/uvp_amundsen_1165_ecotaxa_object_sample.tsv` | Simple EcoTaxa UVP5 baseline. Clean depth columns. Useful control scenario before enriched tables. | `Voici un export EcoTaxa UVP5.\nFichier : {paths}\nFais un graphique de obj_depth_max en fonction de obj_depth_min — les colonnes sont confirmées.\nDonne un plan puis le code Python.` |
| `uvp_enriched_reasoning_code` | `raisonnement + code` | `/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/uvp_amundsen_1165_105_enriched_nearest_depth.tsv` | Best UVP happy path. Already enriched EcoTaxa UVP5 ↔ EcoPart with depth and environmental context. | `Voici un fichier UVP enrichi.\nFichier : {paths}\nFais un graphique de ecopart_temperature_degC en fonction de object_depth — les colonnes sont confirmées.\nDonne un plan puis le code Python.` |
| `neolabs_raw_pair_reasoning_code` | `raisonnement + code` | `/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/Donnée Neolabs Taxon/IDEA Taxonomy Zooplankton Abundances Data May 26 2026.csv` + `/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/Donnée Neolabs Taxon/IDEA Taxonomy Samples and Analyses Data Metadata May 26 2026.csv` | Realistic NeoLabs two-file case. Forces the model to reason over the business join `SAMPLE_ID + ANALYSIS_ID` before graphing. | `Voici deux fichiers NeoLabs : un fichier d'abondances taxonomiques et un fichier de métadonnées d'échantillons/analyses.\nFichiers : {paths}\nRelie-les correctement puis fais un graphique de Total abundance (ind./m3 depth vol) en fonction de MIN_SAMPLE_DEPTH — les colonnes sont confirmées.\nDonne un plan puis le code Python.` |
| `neolabs_ctd_production_flow` | `production flow` | `/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv/neolabs_taxonomy_abundance_amundsen_ctd.tsv` | Rich NeoLabs enriched table with CTD context and match-quality columns. Good candidate to test that the model is pushed through production-oriented graph flow. | `Voici une table NeoLabs enrichie avec la CTD Amundsen.\nFichier : {paths}\nFais un graphique de Total abundance (ind./m3 depth vol) en fonction de amundsen_temperature_degC_nearest — les colonnes sont confirmées.\nDonne un plan puis le code Python.` |

## Fixture notes

### `uvp_amundsen_1165_ecotaxa_object_sample.tsv`

Useful columns observed:

- `obj_depth_min`
- `obj_depth_max`
- `fre_area`
- `fre_major`
- `fre_minor`
- `fre_feret`
- `fre_esd`

### `uvp_amundsen_1165_105_enriched_nearest_depth.tsv`

Useful columns observed:

- `object_depth`
- `fre_area`
- `fre_esd`
- `fre_major`
- `depth_delta_m`
- `ecopart_temperature_degC`
- `ecopart_salinity_psu`

### `IDEA Taxonomy Zooplankton Abundances Data May 26 2026.csv`

Used jointly with sample/analysis metadata to recover sampling context before
graphing abundance patterns.

### `IDEA Taxonomy Samples and Analyses Data Metadata May 26 2026.csv`

Used jointly with abundance rows through:

- `SAMPLE_ID + ANALYSIS_ID`

### `neolabs_taxonomy_abundance_amundsen_ctd.tsv`

Useful columns observed:

- `MIN_SAMPLE_DEPTH`
- `MAX_SAMPLE_DEPTH`
- `sample_mid_depth_m`
- `Total abundance (ind./m3 depth vol)`
- `ctd_match_status`
- `amundsen_temperature_degC_mean_sample_interval`
- `amundsen_salinity_psu_mean_sample_interval`
- `amundsen_fluorescence_ug_l_mean_sample_interval`

## Recommended implementation order

1. `uvp_enriched_reasoning_code`
2. `neolabs_ctd_production_flow`
3. `ecotaxa_simple_reasoning_code`
4. `neolabs_raw_pair_reasoning_code`

## Validation status

| Scenario slug | Status | Notes |
|---|---|---|
| `ecotaxa_simple_reasoning_code` | Validated | Happy path reached. `graph_readiness = ready`; assistant reply contains `**Plan**` + fenced `python` block; no clarification required. Prompt actually validated: `obj_depth_max` vs `obj_depth_min` on `uvp_amundsen_1165_ecotaxa_object_sample.tsv`. |
| `uvp_enriched_reasoning_code` | Reclassified: expected clarification | Current behaviour is a user-facing clarification on taxonomic validation status (`inclure` vs `exclure` les annotations non confirmées) before graph generation. This is treated as a legitimate business clarification, not a graph-readiness failure. Next step: test the follow-up turn after the user answers this clarification. |
| `uvp_enriched_after_validation_clarification` | Validated | Multi-turn path validated on `uvp_amundsen_1165_105_enriched_nearest_depth.tsv`. Turn 1 asks the expected validation-status clarification. After the user reply `Exclure les annotations non confirmées.`, turn 2 generates `**Plan**` + fenced `python` block and does not repeat the same clarification. |
| `neolabs_ctd_production_flow` | Reclassified: expected clarification | One-shot run still stops on taxonomic validation policy before code generation. The clarification wording is now more actionable: `faut-il conserver uniquement les annotations au statut confirmed, ou inclure aussi les annotations non confirmées ?`. Multi-turn follow-up is not yet validated. |

## Intended assertions

### For `raisonnement + code`

- `inspect_and_report` is called on each uploaded fixture
- the graph path is triggered
- the reply contains `**Plan**`
- the reply contains a fenced `python` code block
- the reply mentions the requested columns or close aliases
- the reply does not block on missing/unknown columns when the prompt says the columns are confirmed

### For `production flow`

- the graph path is triggered
- the reply does not fall back to a refusal or vague explanation
- the reply contains language indicating that a graph output is being produced, prepared, or ready for display
- no explicit frontend JSON contract is required yet at this stage

## Out of scope for this batch

- formal artifact capture in the eval harness
- frontend JSON schema validation
- retry-loop validation on plotting failure

Those should come after the happy path is stable on these fixtures.
