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

**Bio-ORACLE : échec comportemental.**

L'agent choisit correctement `couple_zooplankton_bio_oracle`, mais ne lit pas
les lignes du fichier. Il invente des identifiants de stations et des
coordonnées, puis produit une table qui perd `sample_date` et `abundance`.

**OGSL : capacité absente.**

L'agent actuel ne possède aucun tool LangChain pour acquérir OGSL. Il tente une
jointure sur `df_ogsl`, puis échoue parce que cette table n'a jamais été chargée.
Le registre `core/tool_registry/tools/copepod_remote_sources.py` contient une
implémentation OGSL, mais elle n'est pas exposée par `agent.make_agent()`.
