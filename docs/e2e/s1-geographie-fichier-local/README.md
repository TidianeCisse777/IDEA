# Scénario E2E S1 — Géographie sur fichier local

## Objectif

Vérifier qu’une demande de carte géographique reste limitée au fichier local
chargé, filtre le dataset actif sur la zone demandée et produit une carte à
partir du sous-ensemble exact.

## Session

- Date : 2026-07-16
- `USER_ID` : `e2e-s1-20260716`
- `CHAT_ID` : `e2e-s1-20260716-143529`
- `THREAD_ID` : `c864fb7e77342838`

## Déroulé exécuté

| Tour | Prompt | Résultat | Verdict |
|---|---|---|---|
| 1 | `Charge le fichier data/demo/neolabs_taxonomy_2014_2020.tsv.` | Fichier chargé, 7093 lignes × 82 colonnes, variable persistante correcte. | PASS |
| 2 | `Affiche toutes les stations présentes dans la mer du Labrador sur une carte.` | Le filtre exact IHO conserve réellement 0 ligne; aucune carte n’est produite. Les noms `rows_in`/`rows_out` sont inversés sémantiquement dans le contrat du tool. | FAIL |

Le scénario est arrêté au premier défaut, conformément au guide E2E. Les tours
3 à 5 ne sont pas exécutés.

## Tour 1 — Contrôle

- Source active : `file`.
- Dataset actif : `df_file_neolabs_taxonomy_2014_2020`.
- Tool appelé : `load_file` — succès.
- Skill chargé : `neolabs_abundance_analysis`, source locale, version `1.0.0`.
- Appels modèle : `3`.

## Tour 2 — Contrôle

- Source active : `file`.
- Dataset source : `df_file_neolabs_taxonomy_2014_2020`.
- Tool appelé : `filter_dataframe_by_zone` avec `zone_name="Mer du Labrador"`,
  `lat_col="latitude"`, `lon_col="longitude"`.
- Le filtre conserve réellement `0` ligne sur `7093` : le polygone IHO
  enregistré pour la Mer du Labrador a pour bbox `[-64.306, -43.6749] ×
  [47.386, 60.3971]`, et le TSV ne contient aucun point dans cette bbox.
- Contrat de métriques trompeur : `rows_in=0` désigne les lignes conservées et
  `rows_out=7093` les lignes rejetées; les libellés sont inversés par rapport à
  leur sens habituel.
- `run_graph` appelé : non.
- Source externe appelée : non.
- Tools exposés : `load_file`, `load_skill`, `query_copepod_knowledge_base`,
  `run_pandas`, `filter_dataframe_by_zone`, `get_zone_info`.

## Artefacts

- [Tour 1 — SSE](../../../logs/e2e-e2e-s1-20260716-143529-t1.sse)
- [Tour 1 — trace](../../../logs/e2e-e2e-s1-20260716-143529-t1-trace.json)
- [Tour 2 — SSE](../../../logs/e2e-e2e-s1-20260716-143529-t2.sse)
- [Tour 2 — trace](../../../logs/e2e-e2e-s1-20260716-143529-t2-trace.json)

Voir le défaut détaillé dans [DEFECTS.md](DEFECTS.md).
