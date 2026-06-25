---
name: copepod_hydrodynamic_micro_zoom
description: Copepod-centric reasoning guide for micro-hydrodynamic mechanisms: thermal/salinity fronts, river plumes, estuarine stratification, upwellings, eddies, local currents, breakup, blooms, vertical migration, reproduction, diapause, larvae, feeding, and predation. Use when the user asks how fine-scale physical structures affect copepods.
---

# Skill: copepod_hydrodynamic_micro_zoom

Use this skill to answer questions about fine-scale hydrodynamic structures only through their effects on copepods.

## Core rule

This is copepod-centric. Fronts, plumes, upwellings, eddies, and currents are explanatory mechanisms, not the final topic.

Always bring the answer back to one or more copepod outcomes:

- spatial segregation or aggregation
- diel migration verticale
- feeding and phytoplankton access
- reproduction, egg production, larval survival
- diapause exit or spring awakening
- growth and development rate
- predation exposure
- species or stage differences

Do not present fronts, plumes, upwellings, or currents as fixed zones. They are dynamic contexts that require evidence from date, depth, hydrography, and sampling geometry.

## Response shape

For conceptual questions:

1. Physical mechanism
2. Expected copepod response
3. Testable predictions
4. Data needed
5. Limits and uncertainty

For data-backed questions:

1. State the hypothesis in copepod terms.
2. Identify available evidence: date, latitude/longitude, depth, taxon/stage, abundance, temperature, salinity, density, fluorescence/chlorophyll, oxygen, turbidity, nutrients.
3. Use source tools when needed; do not invent missing fields.
4. Conclude as compatible, not compatible, or indeterminate.

## Mechanisms

### Fronts

A front is a narrow transition where water masses differ in temperature, salinity, density, or flow. Treat fronts as possible barriers and concentration zones.

Copepod hypotheses:

- Aggregation near the front because phytoplankton and particles accumulate.
- Segregation by species, stage, or depth if one side is colder, saltier, or denser.
- Higher feeding opportunity, but possibly higher predation if predators also aggregate.
- Reproduction can increase if food is concentrated and temperatures remain within the species' tolerance.

Evidence to seek:

- strong horizontal or vertical gradients in temperature, salinity, density, fluorescence, chlorophyll, or turbidity
- samples close in space/time but with abrupt environmental differences
- abundance or stage composition differing across the gradient

Do not claim copepods crossed or were trapped by a front unless the sampling design compares both sides or repeated transects support it.

### River plumes / panaches de rivière

A river plume / panache de rivière is fresh, often warmer and more turbid surface water spreading over saltier marine water, especially during breakup and snowmelt.

Copepod hypotheses:

- Surface freshening can create stratification and change diel migration verticale.
- Turbidity can alter light exposure, predator visibility, and feeding conditions.
- A plume may be a refuge, a stressor, or a food-rich layer depending on salinity tolerance and phytoplankton response.
- Eggs, nauplii, copepodites, and adults can respond differently.

Evidence to seek:

- month/season: especially May, June, July in northern estuaries
- low surface salinity relative to deeper water
- temperature/salinity stratification
- turbidity, fluorescence, chlorophyll, or CDOM when available
- distance to river mouth if known

Do not infer plume influence from a river name alone; state what evidence is missing.

### Upwellings and eddies

Upwelling brings deeper, colder, nutrient-rich water toward the surface. Eddies can retain, concentrate, or disperse plankton and nutrients.

Copepod hypotheses:

- Nutrient injection can trigger phytoplankton blooms and improve food supply after a lag.
- Cold water can slow development even when food increases.
- Upwelling can alter vertical position of eggs, nauplii, and copepodites, but do not claim bottom eggs are lifted without evidence.
- Retention in eddies can increase local abundance; dispersive eddies can separate life stages.

Evidence to seek:

- cold anomaly near surface or shoaling of cold/salty/dense water
- nitrate, chlorophyll, or fluorescence increase
- bathymetric/topographic context if available
- repeated observations showing retention, displacement, or bloom timing

Without velocity fields, wind, or repeated transects, call this a possible signal, not a detected upwelling or eddy.

## Tool routing

- Conceptual question without data: call `query_copepod_knowledge_base` after this skill if local domain facts are needed.
- User asks for EcoTaxa samples/projects/observations: also load `ecotaxa_navigation` and use the read-only EcoTaxa tools.
- Loaded table with coordinates/time/depth: use `run_pandas` to inspect available columns and compute evidence.
- Need CTD context: use `enrich_with_amundsen_ctd` or `enrich_with_ogsl` when the table has lat/lon/time.
- Broad environmental context: use `enrich_with_bio_oracle`, but say it is too coarse to locate a fine front.
- Visual request: load `graph_planner` and `graph_writer`, then use `run_graph`.

## Forbidden

- Do not answer as general oceanography without linking back to copepods.
- Do not fabricate `uo` / `vo`, current speed, river discharge, or front location.
- Do not treat "Labrador Current", "front", "plume", "eddy", or "upwelling" as a stable `zone_name`.
- Do not claim causality from a single sample. Use "compatible with", "suggests", or "indeterminate".
