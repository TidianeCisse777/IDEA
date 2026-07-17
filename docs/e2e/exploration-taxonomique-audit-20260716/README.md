# E2E — Exploration taxonomique, audit et lacunes

## Session

- `USER_ID` : `e2e-taxonomy-audit-20260716`
- `CHAT_ID` : `e2e-taxonomy-audit-20260716-1`
- `THREAD_ID` : `48c2249c88662b28`
- Date : 2026-07-16
- Intention : explorer le contenu taxonomique, auditer la qualité des données et repérer les lacunes avec tableaux, graphiques et cartes.

## Fichiers inspectés avant le scénario

- `data/neolabs/neolabs_abundance.csv` : 5 047 lignes × 93 colonnes.
- `data/neolabs/neolabs_sample.csv` : 6 105 lignes × 33 colonnes.
- `TAXON_ID` : 101 valeurs distinctes.
- Taxonomie présente : `KINGDOM`, `PHYLUM`, `CLASS`, `ORDER`, `FAMILY`.
- Tous les enregistrements d’abondance sont `Copepoda`.
- Années d’abondance : 2010–2018, 2023–2025.
- Échantillons d’abondance : 393 ; stations : 223.
- Clé de jointure attendue : `SAMPLE_ID` ↔ `sample_id`.

## Parcours prévu

1. Charger les deux CSV.
2. Auditer chaque fichier séparément.
3. Réaliser et persister la jointure.
4. Auditer les correspondances, doublons et valeurs manquantes.
5. Inventorier les taxons réellement présents.
6. Explorer un taxon précis dans le temps et l’espace.
7. Comparer deux taxons présents.
8. Produire les tableaux, graphiques et cartes demandés.
9. Terminer par les lacunes temporelles, spatiales, taxonomiques et quantitatives.

## Tour 1 — Audit initial

### Prompt utilisateur

> Charge les deux fichiers NeoLabs disponibles dans data/neolabs, puis décris brièvement ce qu’ils contiennent : dimensions, colonnes importantes, période couverte, stations, échantillons, taxonomie et variables d’abondance. Ne fais pas encore de graphique ni de jointure : je veux d’abord un audit initial des fichiers.

### Verdict

`FAIL` — l’agent a tenté deux appels `load_file` avec `path=neolabs`, puis a signalé que le dossier n’était pas chargeable. Il n’a pas chargé les deux CSV et n’a pas réalisé l’audit.

### Artefact

- [Flux SSE du tour 1](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t1.sse)

## Règle de poursuite

Le tour suivant peut réaliser la jointure, car les deux fichiers sont maintenant chargés séparément.

## Tour 2 — Audit initial réussi

### Prompt utilisateur

> Charge séparément ces deux fichiers : `data/neolabs/neolabs_abundance.csv` et `data/neolabs/neolabs_sample.csv`. Fais ensuite un audit initial séparé de chacun : dimensions, colonnes taxonomiques, périodes, stations, échantillons, variables d’abondance et valeurs manquantes principales. Ne fais pas encore la jointure ni de graphique.

### Verdict

`PASS` — les deux fichiers ont été chargés sous deux variables distinctes et audités sans jointure ni graphique.

### Résultats clés

- abundance : 5 047 × 93, 223 stations, 393 échantillons, 2010–2025 ;
- sample : 6 105 × 33, 581 stations, 6 102 échantillons, 2010–2025 ;
- abundance : taxonomie et variables d’abondance présentes ;
- sample : métadonnées spatiales, temporelles et de cast, sans variable d’abondance explicite ;
- valeurs manquantes importantes détectées dans les biomasses et les commentaires/métadonnées.

### Artefact

- [Flux SSE du tour 2](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t2.sse)

## Tour 3 — Jointure et audit des correspondances

### Prompt utilisateur

> Joins maintenant les deux fichiers déjà chargés avec la clé correspondant à `SAMPLE_ID` et `sample_id`. Fais une jointure détaillée et persiste la table jointe comme nouvelle table active. Vérifie avant de conclure : dimensions avant/après, nombre de clés communes, lignes appariées et non appariées, doublons côté métadonnées, stations et coordonnées récupérées. Donne un tableau d’audit clair. Ne produis pas encore de graphique.

### Verdict

`PASS` — la jointure a été exécutée et persistée comme table active `df_join_2c062b7a0352`.

### Résultats clés

- clé : `SAMPLE_ID` ↔ `sample_id` ;
- dimensions : 5 047 × 93 et 6 105 × 33 avant jointure ;
- dimensions après jointure : 5 140 × 127 ;
- 393 clés communes distinctes ;
- 5 140 lignes appariées et 0 ligne abondance non appariée ;
- 965 lignes métadonnées sans abondance correspondante ;
- doublons de clé côté abondance : 4 654 ;
- clé unique côté métadonnées ;
- stations, latitudes et longitudes non nulles dans la table jointe.

### Artefact

- [Flux SSE du tour 3](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t3.sse)

## Tour 4 — Jointure contrôlée corrigée

### Prompt utilisateur

> La jointure précédente a augmenté le nombre de lignes d’abondance. Reprends-la proprement à partir des deux fichiers déjà chargés, sans les recharger. L’objectif est de conserver exactement une ligne de sortie par ligne du fichier abondance et d’ajouter au plus une ligne de métadonnées par `SAMPLE_ID`. Audite les doublons et les conflits, persiste la nouvelle table active et ne produis pas de graphique.

### Verdict

`PASS` — la jointure corrigée est persistée sous `df_join_f35f9afc4c48`.

### Résultats clés

- sortie : 5 047 × 127 ;
- invariant respecté : une ligne de sortie par ligne abondance ;
- 5 047 lignes appariées ;
- 0 ligne non appariée ;
- 0 conflit de métadonnées détecté ;
- latitude et longitude présentes sur les 5 047 lignes ;
- colonne `match_status` ajoutée.

### Artefact

- [Flux SSE du tour 4](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t4-controlled-join.sse)

## Tour 5 — Inventaire taxonomique

### Prompt utilisateur

> À partir de la table jointe active corrigée, fais l’inventaire taxonomique réel des données. Donne le nombre de taxons distincts, les niveaux taxonomiques disponibles, les taxons les plus représentés, la répartition par ordre et famille, ainsi que les valeurs manquantes par niveau. Ne choisis pas encore de taxon pour une carte ou un graphique et ne recharge aucun fichier.

### Verdict

`PASS` — l’agent a utilisé `df_join_f35f9afc4c48` et a produit l’inventaire sans graphique ni rechargement.

### Résultats clés

- 101 taxons distincts sur 5 047 lignes ;
- niveaux présents : `KINGDOM`, `PHYLUM`, `CLASS`, `ORDER`, `FAMILY`, `TAXON_ID` ;
- `TAXON_ID` sans valeur manquante ;
- 129 valeurs manquantes dans `ORDER` ;
- 320 valeurs manquantes dans `FAMILY` ;
- taxons fréquents : `Calanus glacialis`, `Calanus hyperboreus`, `Metridia longa`, `Oithona similis`, `Pseudocalanus spp.` ;
- ordre dominant : `Calanoida`.

### Artefact

- [Flux SSE du tour 5](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t5-taxonomy-inventory.sse)

## Tour 6 — Premier taxon et visualisations

### Prompt utilisateur

> Explore maintenant le taxon `Calanus glacialis` dans la table jointe active. Commence par un tableau d’audit : lignes, échantillons, stations, années, zones, profondeurs, variables d’abondance disponibles et valeurs manquantes. Ensuite produis deux sorties visuelles descriptives : un graphique du nombre de lignes par année et une carte des stations où ce taxon est observé. Utilise uniquement les lignes réellement attribuées à `Calanus glacialis`, ne recharge aucun fichier et n’ajoute aucune interprétation biologique.

### Verdict

`FAIL` — l’audit tabulaire a été produit, mais aucun des deux graphiques demandés n’a été exécuté. L’agent a chargé `graph_planner`, puis a répondu que le workflow graphique n’avait pas été lancé ; aucun appel `run_graph` n’apparaît.

### Résultats tabulaires obtenus

- 387 lignes ;
- 384 échantillons distincts ;
- 220 stations distinctes ;
- 12 années ;
- profondeur observée : 0 à 1 972 ;
- zones non disponibles dans la table jointe active ;
- années : 2010–2018, 2023–2025.

### Défaut bloquant

La demande contenait explicitement deux visualisations, mais le modèle s’est arrêté après `graph_planner` sans charger `graph_writer` ni appeler `run_graph`.

### Artefact

- [Flux SSE du tour 6](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t6-calanus-glacialis.sse)

## Tour 7 — Comparaison temporelle de deux taxons

### Prompt utilisateur

> À partir de la table jointe active, compare Calanus glacialis et Calanus hyperboreus. Donne d’abord un tableau de couverture par taxon : lignes, échantillons, stations et années observées. Ensuite montre leur évolution annuelle dans un même graphique, avec un symbole distinct pour chaque taxon. N’utilise aucun autre fichier et n’ajoute pas d’interprétation biologique.

### Verdict

`PASS` — l’agent a conservé `df_join_f35f9afc4c48`, produit le tableau de couverture et généré un graphique annuel comparatif avec un symbole distinct par taxon. Un premier rendu bloqué par l’absence de `graph_contract` a été corrigé par le retry prévu, puis `run_graph` a réussi.

### Résultats

- `Calanus glacialis` : 387 lignes, 384 échantillons, 220 stations, 12 années ;
- `Calanus hyperboreus` : 352 lignes, 348 échantillons, 209 stations, 11 années ;
- graphique : [b680645a1aad.png](../../../graphs/b680645a1aad.png).

### Artefacts

- [Flux SSE du tour 7](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t7-taxonomy-compare.sse)
- [Trace harness du tour 7](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t7-taxonomy-compare-trace.json)

## Tour 8 — Comparaison normalisée par effort d’échantillonnage

### Prompt utilisateur

> Le graphique précédent compte les lignes et favorise les années avec plus d’échantillons. Reprends la comparaison sur la table jointe active uniquement. Pour Calanus glacialis et Calanus hyperboreus, calcule par année : échantillons distincts du taxon, stations distinctes du taxon, nombre total d’échantillons et de stations échantillonnés, puis les proportions taxon/total pour les échantillons et les stations. Affiche le tableau de contrôle et produis un graphique des proportions annuelles, avec un symbole différent par taxon. N’interprète pas biologiquement et ne recharge aucun fichier.

### Verdict

`FAIL` — les proportions ont été calculées avec les bons dénominateurs, mais le résultat de `run_pandas` a été persisté sous `df_join_0cb47a6f2413`, remplaçant la table jointe active. L’agent a ensuite tenté `run_graph` sans charger `graph_writer` et a répondu que le graphique était bloqué.

### Défauts observés

- la table de contrôle devait rester éphémère ou être persistée comme résultat dérivé explicitement nommé ;
- la table active attendue `df_join_f35f9afc4c48` n’a pas été conservée ;
- l’échec de routage `graph_writer` persiste dans ce chemin malgré l’intention visuelle exposée.

### Artefacts

- [Flux SSE du tour 8](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t8-taxonomy-normalized.sse)
- [Trace harness du tour 8](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t8-taxonomy-normalized-trace.json)

### Correction après le tour 8

- Les merges analytiques intermédiaires ne sont plus persistés comme `df_join_*` : seuls un `result = ...merge(...)` direct ou un DataFrame nommé `joined`/`merged`/`result_df` sont considérés comme une nouvelle jointure active.
- Si `run_graph` est appelé sans `graph_writer`, le tool active automatiquement le skill validé et poursuit l’exécution récupérable au lieu d’abandonner le tour.
- Régressions couvertes par `test_analytical_merge_does_not_replace_active_join_with_control_table` et `test_run_graph_requires_graph_writer_after_loaded_analysis_skill`.

## Tour 9 — Rejeu après correction

### Verdict

`PASS PARTIEL` — le calcul de contrôle est resté éphémère (`persisted=false`), la source utilisée par le graphique est explicitement `df_join_f35f9afc4c48`, et `run_graph` a réussi après chargement de `graph_writer`.

Le pointeur de table active du thread historique reste toutefois `df_join_0cb47a6f2413`, héritage de la corruption du tour 8. Le correctif empêche toute nouvelle corruption, mais ce thread doit être réinitialisé avant de poursuivre un scénario strict sur l’état actif.

### Artefacts

- [Flux SSE du tour 9](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t9-taxonomy-normalized-fixed.sse)
- [Trace harness du tour 9](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t9-taxonomy-normalized-fixed-trace.json)
- [Graphique](http://localhost:8000/graphs/a32c0ced63e7.png)

## Tour 10 — Retry final du rendu normalisé

`PASS` — le calcul a utilisé explicitement `df_join_f35f9afc4c48`, le tableau est resté éphémère, `graph_writer` a été chargé et le rendu a réussi : [fa47cbf1c4f4.png](http://localhost:8000/graphs/fa47cbf1c4f4.png).

- [Flux SSE du tour 10](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t10-taxonomy-normalized-retry.sse)
- [Trace harness du tour 10](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t10-taxonomy-normalized-retry-trace.json)

## Tour 11 — Dénominateur annuel sur toute la table

`PASS` — les totaux annuels ont été calculés sur `df_join_f35f9afc4c48` avant le filtre taxonomique. Le tableau est resté éphémère et le graphique a été produit : [3d26b469b566.png](http://localhost:8000/graphs/3d26b469b566.png).

Les proportions restent souvent proches de 1 dans les années disponibles : c’est un résultat observé de la couverture NeoLabs, pas un effet du dénominateur restreint aux deux taxons.

- [Flux SSE du tour 11](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t11-taxonomy-coverage-all-samples.sse)
- [Trace harness du tour 11](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t11-taxonomy-coverage-all-samples-trace.json)

## Tour 12 — Abondance par échantillon

`BLOCKED` — la requête `curl` a reçu une réponse HTTP 500 avant le premier appel outil. Aucun dataset ni résultat ne peut être validé pour ce tour ; le scénario s’arrête ici.

- [Flux SSE du tour 12](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t12-taxonomy-abundance.sse)
- [Trace harness du tour 12](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t12-taxonomy-abundance-trace.json)

## Tour 13 — Retry abondance

`FAIL` — la requête a atteint l’agent, mais la variable demandée `df_join_f35f9afc4c48` ne contient plus la colonne d’abondance ; elle expose le résumé de couverture (`year`, `prop_samples`, `prop_stations`). La session historique est donc toujours contaminée et le scénario doit repartir dans une session propre.

- [Flux SSE du tour 13](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t13-taxonomy-abundance-retry.sse)
- [Trace harness du tour 13](../../../logs/e2e-e2e-taxonomy-audit-20260716-1-t13-taxonomy-abundance-retry-trace.json)

## Nouvelle session propre — Tour 1

Session : `e2e-taxonomy-clean-20260716-1` · thread `e2e-taxonomy-clean-20260716`.

`PASS` — les fichiers restent séparés (`df_file_neolabs_abundance`, 5 047 × 93 ; `df_file_neolabs_sample`, 6 105 × 33). Une première jointure invalide `m:1` a été rejetée sur les doublons `sample_id`, puis l’agent a dédupliqué la table sample et persisté la jointure contrôlée `df_join_5537fd443276` (5 047 × 126), en conservant exactement une ligne par ligne abundance.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-clean-20260716-1-t1-clean-load-join.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-clean-20260716-1-t1-clean-load-join-trace.json)

## Nouvelle session propre — Tour 2

`FAIL` — l’input demandait le taxon `Calanus glacialis`, mais le code a recherché cette chaîne dans plusieurs niveaux (`TAXON_ID`, `FAMILY`, `ORDER`, `CLASS`, `PHYLUM`, `KINGDOM`). Le sous-ensemble obtenu (533 lignes) n’est donc pas un filtre strict sur le taxon demandé. Le scénario est arrêté avant l’exploration spatiale.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-clean-20260716-1-t2-taxonomy-time-depth.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-clean-20260716-1-t2-taxonomy-time-depth-trace.json)

## Nouvelle session propre — Tour 3

`PASS` — le filtre est maintenant strictement `TAXON_ID == "Calanus glacialis"`. Résultat : 387 lignes, 375 échantillons distincts, 212 stations, profondeur 10–1972 m, médiane 103,5 m, et tableau temporel produit sans modifier la jointure active.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-clean-20260716-1-t3-taxonomy-time-depth-fixed.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-clean-20260716-1-t3-taxonomy-time-depth-fixed-trace.json)

## Nouvelle session propre — Tour 4

`PASS` — l’agent a conservé `df_join_5537fd443276`, appliqué le filtre strict `TAXON_ID == "Calanus glacialis"`, puis produit un tableau de 213 stations avec coordonnées, nombre d’échantillons distincts et première/dernière date observée. La carte utilise une projection Lambert, les côtes, les stations et une taille de symbole proportionnelle au nombre d’échantillons. Aucun fichier n’a été rechargé et la jointure active est restée inchangée.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-clean-20260716-1-t4-taxonomy-spatial-map.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-clean-20260716-1-t4-taxonomy-spatial-map-trace.json)
- [Carte](http://localhost:8000/graphs/ba5017666e2f.png)

## Nouvelle session propre — Tour 5

`FAIL` — l’input demandait un focus géographique sur la baie d’Hudson. Le tool de filtrage a retourné un résultat incohérent (`n_in=654`, `n_out=4393`), puis l’analyse a affiché des bornes latitude 57,0286–63,7325 alors que son tableau contient encore des stations à latitude 76° (stations 101, 105 et 108). La carte a donc été générée sur une zone mal contrôlée. Le scénario est arrêté avant tout nouvel input.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-clean-20260716-1-t5-zone-hudson.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-clean-20260716-1-t5-zone-hudson-trace.json)
- [Carte invalide](http://localhost:8000/graphs/d3e835defed2.png)

### Diagnostic et correction après le tour 5

- Le polygone IHO n’était pas en cause : la reproduction directe sur les CSV conserve bien 654 lignes, et le taxon filtré reste dans 55,3851–63,7325°N.
- Le tableau affiché par l’agent complétait au-delà de l’aperçu `run_pandas` et introduisait des stations absentes du résultat vérifié.
- Le filtre persistait aussi son sous-ensemble dans le slot actif, ce qui pouvait masquer la jointure source.
- Correction : les sous-ensembles de zone restent nommés mais ne remplacent plus la table active ; les aperçus pandas tronqués portent une consigne explicite de ne pas compléter les lignes invisibles ; le prompt impose la restitution exacte des seules lignes vérifiées.

## Session de retest — Zone après correction

### Tour 2 — Retry avec routage implicite

`FAIL` — le filtre géographique était exposé mais n’a pas été appelé. L’agent a utilisé directement `df_join_af8ea36ab490`, produit 384 lignes et des bornes globales jusqu’à 81,3679°N. La capture des sorties `print` n’était donc pas suffisante sans garantir l’appel du tool géographique.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t3-zone-hudson-retry.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t3-zone-hudson-retry-trace.json)
- [Carte invalide — source complète au lieu de la zone](http://localhost:8000/graphs/3840aa0bcc71.png)

### Tour 3 — Retry avec appel géographique obligatoire

`PASS` pour le filtrage et le tableau : `filter_dataframe_by_zone` a été appelé en premier, puis `run_pandas` a retourné 68 lignes strictes `TAXON_ID == "Calanus glacialis"`. Les bornes observées sont cohérentes (55,3851–63,7325°N ; -94,0111–-77,9125°W), et la jointure active `df_join_af8ea36ab490` est restée inchangée. La sortie contrôlée complète désormais le tableau sans invention de lignes.

La carte n’a pas été relancée dans ce dernier retry ; elle reste à valider après ce routage corrigé.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t4-zone-hudson-final.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t4-zone-hudson-final-trace.json)
- [Carte intermédiaire invalide — générée avant le retry final](http://localhost:8000/graphs/2959f3a3bc7d.png)

### Tour 4 — Carte après validation du sous-ensemble

`PASS` — la carte utilise exclusivement `df_in_baie_d_hudson_join`, applique le filtre strict du taxon, agrège 35 stations et encode `n_samples` dans la taille des symboles. Le rendu est une vraie carte Lambert avec côtes ; `run_graph` a réussi et la jointure active `df_join_af8ea36ab490` est restée inchangée.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t5-zone-hudson-map.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t5-zone-hudson-map-trace.json)
- [Carte](http://localhost:8000/graphs/fd3d79f84432.png)

### Tour 5 — Changement complet d’exploration : Calanus hyperboreus

`PASS` — l’agent a utilisé explicitement `df_join_af8ea36ab490`, et non le sous-ensemble baie d’Hudson. Il a produit un contrôle annuel profondeur × échantillons/stations sur 11 années (2010–2025 selon disponibilité), puis un graphique temporel. La jointure active est restée inchangée.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t6-hyperboreus-time-depth.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t6-hyperboreus-time-depth-trace.json)
- [Graphique](http://localhost:8000/graphs/74f006acc78e.png)

### Tour 6 — Normalisation par échantillon

`PASS AVEC RÉCUPÉRATION` — l’input précise qu’une année riche en lignes ne doit pas dominer. L’agent a utilisé une contribution par `SAMPLE_ID`, résumé la profondeur intra-échantillon par médiane, puis calculé les statistiques annuelles avec effectifs et IQR. Source confirmée : `df_join_af8ea36ab490`; le sous-ensemble de baie n’a pas été utilisé. Le premier rendu a échoué sur une barre d’erreur négative, puis le retry automatique a produit le graphique avec bande IQR. La jointure active est restée inchangée.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t7-hyperboreus-sample-normalized.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t7-hyperboreus-sample-normalized-trace.json)
- [Graphique](http://localhost:8000/graphs/77de3939d0d1.png)

### Tour 7 — Bio-ORACLE 9.5 : pré-vérification initiale

`FAIL RÉCUPÉRABLE` — le code de pré-vérification imprimait les couvertures mais n’assignait pas `result`; avant correction, `run_pandas` perdait donc ces sorties et l’agent ne pouvait pas confirmer le nombre de lignes utilisables. Aucune requête Bio-ORACLE n’a été lancée.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t8-bio-oracle-95-preflight.sse)

### Tour 8 — Bio-ORACLE 9.5 : pré-vérification corrigée

`PASS` — source confirmée `df_join_af8ea36ab490`, 5 140 lignes, 5 034 lignes complètes utilisables, 106 lignes incomplètes pour latitude/longitude/date, profondeur complète. Variables baseline proposées : température, salinité, oxygène, phosphate, nitrate et silicate. Aucune opération distante lourde n’a été lancée ; confirmation utilisateur requise avant l’enrichissement.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t9-bio-oracle-95-preflight-retry.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t9-bio-oracle-95-preflight-retry-trace.json)

### Tour 9 — Pré-vérification Amundsen CTD

`PASS` — source confirmée `df_join_af8ea36ab490`, 5 034 lignes complètes sur 5 140, emprise 54,7195–81,3679°N et -167,1443–-57,7632°W, période 2010–2025 et profondeur 10–1972 m. La méthode proposée est un appariement au plus proche avec tolérances 25 km, 24 h et 25 dbar. Aucune requête distante lourde n’a été lancée ; confirmation nécessaire avant enrichissement.

- [Flux SSE](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t10-amundsen-preflight.sse)
- [Trace harness](../../../logs/e2e-e2e-taxonomy-retest-20260716-1-t10-amundsen-preflight-trace.json)
