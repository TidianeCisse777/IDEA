# Evaluation agent : enrichissement Bio-ORACLE et OGSL

Ce harness exécute le vrai agent LangGraph avec le LLM configuré dans `.env`.
Il capture chaque appel de tool, ses arguments, un aperçu du résultat, les
tables persistées et l'intégrité du fichier source.

## Exécution

```bash
python scripts/evals/run_agent_source_enrichment_eval.py --scenario bio-oracle
python scripts/evals/run_agent_source_enrichment_eval.py --scenario ogsl
python scripts/evals/run_agent_source_enrichment_eval.py --scenario all
```

Le rapport JSON est écrit par défaut dans :

```text
output/evals/agent_source_enrichment.json
```

Le code de sortie est `0` si tous les critères passent, `1` sinon.

## Critères Bio-ORACLE

- l'agent charge le fichier ;
- il lit les lignes réelles avec `run_pandas` ;
- il appelle `couple_zooplankton_bio_oracle` ;
- il n'utilise pas `query_bio_oracle_zones` ;
- les stations et coordonnées transmises correspondent exactement au fichier ;
- une nouvelle table couplée est créée ;
- le nombre de lignes et toutes les colonnes source sont conservés ;
- le fichier brut reste inchangé.

## Critères OGSL

- l'agent charge le fichier ;
- il appelle un tool d'acquisition OGSL ;
- il charge le skill `environmental_join` ;
- il exécute une jointure explicite avec `run_pandas` ;
- une table OGSL est persistée ;
- le fichier brut reste inchangé.

## Baseline du 15 juin 2026

**Bio-ORACLE: passed after tool-contract fix.**

The coupling tool now reads the active DataFrame directly, uses the source
coordinates and station IDs, preserves all source columns, and creates a
same-cardinality derived table. The bounded live agent evaluation passed.

**OGSL: large-file tool validated locally and against the public endpoint.**

`query_ogsl` reads station IDs and sampling times from the active source table.
It issues one request per unique station with a station-specific padded time
window, persists raw `ismerSgdeCtd` profiles as `df_ogsl`, and creates the
derived enrichment table itself. The standard path no longer relies on an
LLM-generated pandas join.

## LangSmith OGSL trajectory evaluation

Dataset: `copepod-ogsl-enrichment-trajectory-v1`

Run one bounded example:

```bash
python scripts/evals/run_ogsl_langsmith_eval.py
```

The case uses the real OGSL station `02M`. The source timestamp drives a
24-hour padded acquisition window. Deterministic code evaluators are used, so
no additional LLM judge is called.

The initial small-file experiment `ogsl-enrichment-agent-260d508c` passed:

- `ogsl_trajectory`: 1.0
- `ogsl_query_integrity`: 1
- `ogsl_dataset_created`: 1
- `source_file_preserved`: 1

The dataset and code evaluators now target the large-file contract
`load_file -> query_ogsl`. The latest agent rerun was not evaluated because the
model provider returned HTTP 402 before generation. The script caps evaluation
output at 1000 tokens for the next run. Deterministic tests and a direct public
OGSL query validate the new raw and enriched table behavior.
