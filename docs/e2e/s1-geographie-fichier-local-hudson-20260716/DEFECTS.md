# Défauts — Rejeu S1 baie d’Hudson

## E2E-S1-HUDSON-001 — Le modèle tente `run_pandas` pour produire une figure

- Scénario / tour : rejeu S1 / tour 2
- Session (`CHAT_ID`, `THREAD_ID`) : `e2e-s1-hudson-20260716-144040`, `100126d06bee2851`
- Prompt exact : `Affiche toutes les stations présentes dans la baie d’Hudson sur une carte.`
- Attendu : appeler directement le tool de graphique pour produire la carte.
- Observé : `run_pandas` reçoit du code matplotlib/cartopy et est bloqué par le harness; le modèle appelle ensuite `run_graph`, qui réussit.
- Première décision incorrecte : choix de `run_pandas` pour un code qui produit une figure.
- Sévérité : mineur
- Artefact : `http://localhost:8000/graphs/d11e1105297f.png`

## E2E-S1-HUDSON-002 — La carte Baffin n’est pas produite après le filtrage

- Scénario / tour : rejeu S1 / tour 3
- Session (`CHAT_ID`, `THREAD_ID`) : `e2e-s1-hudson-20260716-144040`, `100126d06bee2851`
- Prompt exact : `Fais la même chose dans la baie de Baffin.`
- Attendu : réutiliser le dataset local filtré et produire une carte Baffin.
- Observé : `1570` lignes filtrées; `run_pandas` produit une table de `20 × 3`, puis `load_skill(graph_writer)` est bloqué par `output_intent_guard`. Réponse finale : la carte doit être relancée.
- Première décision incorrecte : le modèle n’enchaîne pas vers `run_graph` après la préparation des données et tente un chargement de skill bloqué.
- Sévérité : majeur

## E2E-S1-HUDSON-003 — La modification de carte reste textuelle

- Scénario / tour : rejeu S1 / tour 4
- Session (`CHAT_ID`, `THREAD_ID`) : `e2e-s1-fix-20260716-144820`, `f56f9aba815b124f`
- Prompt exact : `Modifie cette carte : affiche dans la légende le nombre de casts dans chaque station.`
- Attendu : recalculer `n_casts`, puis réémettre la carte avec la légende mise à jour.
- Observé : `run_pandas` calcule `20` stations, `1` cast chacune; aucun `run_graph` n’est appelé. Réponse textuelle seulement.
- Première décision incorrecte : le modèle traite « modifie cette carte » comme une analyse tabulaire et ne reprend pas le workflow graphique.
- Sévérité : majeur
