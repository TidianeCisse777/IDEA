# Rejeu E2E S1 — Géographie sur fichier local, baie d’Hudson

## Session

- Date : 2026-07-16
- `USER_ID` : `e2e-s1-hudson-20260716`
- `CHAT_ID` : `e2e-s1-hudson-20260716-144040`
- `THREAD_ID` : `100126d06bee2851`

## Déroulé

| Tour | Prompt | Résultat | Verdict |
|---|---|---|---|
| 1 | `Charge le fichier data/demo/neolabs_taxonomy_2014_2020.tsv.` | Fichier local chargé, 7093 × 82; variable persistante correcte. | PASS |
| 2 | `Affiche toutes les stations présentes dans la baie d’Hudson sur une carte.` | 1118 lignes filtrées; `run_pandas` bloqué car le code produisait une figure, puis `run_graph` réussit et produit la carte. | FAIL avec récupération |
| 3 | `Fais la même chose dans la baie de Baffin.` | 1570 lignes filtrées; préparation via `run_pandas`, puis `graph_writer` bloqué par le garde-fou d’intention; aucune carte. | FAIL |
| 4 | `Modifie cette carte : affiche dans la légende le nombre de casts dans chaque station.` | Calcul de `n_casts` réussi pour 20 stations, mais aucun `run_graph`; réponse textuelle seulement. | FAIL |

Le scénario est arrêté au premier tool incorrect, conformément au guide E2E.

Le rejeu a néanmoins été poursuivi à la demande de l’utilisateur après le tour
2. Il est arrêté au tour 3 dès que la carte Baffin n’est pas produite.

## Contrôles

- Source active : `file` durant les deux tours.
- Aucun tool EcoTaxa, EcoPart, Amundsen, Bio-ORACLE ou SQL appelé.
- Zone résolue par `get_zone_info`, provenance `IHO Marine Regions v3`.
- Filtre : `filter_dataframe_by_zone`, `1118` lignes conservées selon la
  métrique actuelle du tool.
- Dataset actif : `df_in_baie_d_hudson_data_demo_neolabs_taxonomy_2014_2020_tsv`.
- Skills chargés au tour 2 : `graph_planner` et `graph_writer`, fichiers locaux.
- Tool incorrect : `run_pandas`, bloqué avec `run_pandas produced a matplotlib
  figure. Use run_graph instead to execute visualization code.`
- Tool correct ensuite : `run_graph`, succès en `4.314 s`.
- Artefact image : `http://localhost:8000/graphs/d11e1105297f.png`.

## Tour 3 — Baffin

- Source active : `file`.
- Dataset actif : `df_in_baie_de_baffin_data_demo_neolabs_taxonomy_2014_2020_tsv`.
- Filtre : `filter_dataframe_by_zone`, `1570` lignes conservées.
- `run_pandas` : succès, préparation d’une table de `20` stations × `3` colonnes.
- `load_skill(graph_writer)` : bloqué par `output_intent_guard`.
- Carte produite : non.

## Tour 4 — Légende des casts

- Dataset actif : `df_in_baie_de_baffin_data_demo_neolabs_taxonomy_2014_2020_tsv`.
- `run_pandas` : calcul de `n_casts` réussi; `20` stations, `1` cast chacune.
- `run_graph` appelé : non.
- Résultat : aucune carte modifiée; réponse textuelle seulement.

## Artefacts

- [Tour 1 — SSE](../../../logs/e2e-e2e-s1-hudson-20260716-144040-t1.sse)
- [Tour 1 — trace](../../../logs/e2e-e2e-s1-hudson-20260716-144040-t1-trace.json)
- [Tour 2 — SSE](../../../logs/e2e-e2e-s1-hudson-20260716-144040-t2.sse)
- [Tour 2 — trace](../../../logs/e2e-e2e-s1-hudson-20260716-144040-t2-trace.json)
- [Tour 3 — SSE](../../../logs/e2e-e2e-s1-hudson-20260716-144040-t3.sse)
- [Tour 3 — trace](../../../logs/e2e-e2e-s1-hudson-20260716-144040-t3-trace.json)
- [Tour 4 — SSE](../../../logs/e2e-e2e-s1-fix-20260716-144820-t3.sse)
- [Tour 4 — trace](../../../logs/e2e-e2e-s1-fix-20260716-144820-t3-trace.json)

Voir le défaut détaillé dans [DEFECTS.md](DEFECTS.md).
