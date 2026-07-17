# Scénario E2E S0 — Smoke du harness

## Objectif

Valider que le harness relie correctement une session E2E à sa trace et expose
les informations nécessaires avant les scénarios comportementaux.

## Session

- Date : 2026-07-16
- `USER_ID` : `e2e-s0-20260716`
- `CHAT_ID` : `e2e-s0-20260716-143417`
- `THREAD_ID` : `4e3b5814c34ba548`
- Prompt exact : `Charge le fichier tests/fixtures/source_enrichment_stations.csv.`

## Résultat

**PASS**

- Réponse : fichier chargé, `3` lignes × `5` colonnes.
- Variable persistante : `df_file_source_enrichment_stations`.
- Colonnes : `station`, `latitude`, `longitude`, `sample_date`, `abundance`.
- Source active : `file`.
- Dataset actif : `df_file_source_enrichment_stations`.
- Appel tool : `load_file(path="tests/fixtures/source_enrichment_stations.csv")`, succès,
  durée `0.036 s`, `3` lignes × `5` colonnes.
- Appels modèle : `2`, dans l’ordre attendu.
- Tools exposés : appel 1 — `5`; appel 2 — `6`; exposition limitée aux familles
  `core`, `geography` et `file_analysis`.
- Tools externes appelés : aucun.
- Skills chargés : aucun.
- Contexte : aucune troncature, aucun message supprimé, aucun dépassement de budget.
- Usage SSE final : `4 360` tokens prompt, `66` completion, `4 426` total,
  dont `4 096` cached. Usage cumulatif provider absent (`provider_cumulative_missing`).

## Artefacts

- Flux SSE brut : [`logs/e2e-e2e-s0-20260716-143417.sse`](../../../logs/e2e-e2e-s0-20260716-143417.sse)
- Trace harness : [`logs/e2e-e2e-s0-20260716-143417-trace.json`](../../../logs/e2e-e2e-s0-20260716-143417-trace.json)

## Critère de sortie

Le harness est suffisamment relié pour poursuivre avec S1. La session ne doit
pas être réutilisée pour un autre scénario.
