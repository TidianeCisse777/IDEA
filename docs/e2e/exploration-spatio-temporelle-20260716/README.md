# E2E — Exploration spatiale et temporelle du fichier NeoLabs

## Session

- Date : 2026-07-16
- `USER_ID` : `e2e-green-spatial-20260716`
- `CHAT_ID` : `e2e-green-spatial-20260716-151137`
- `THREAD_ID` : `c9a01e6975eecc6d`
- Source : fichier local
- Dataset actif : fichier NeoLabs taxonomie-abondance chargé dans la session

Objectif : explorer progressivement les dimensions spatiale et temporelle du
fichier, en conservant une trajectoire simple et descriptive malgré un volume
de données limité.

## Phase A — Cartes et corrections visuelles

| Tour | Demande | Résultat | Verdict |
|---|---|---|---|
| A1 | Charger le fichier NeoLabs | Fichier chargé, dataset actif disponible | PASS |
| A2 | Carte de toutes les stations | Carte produite | PASS |
| A3 | Carte de la baie de Baffin | Carte produite après assouplissement du suivi planner/writer | PASS |
| A4 | Carte de la baie d’Hudson | Carte produite | PASS |
| A5 | Couleur par année et taille par abondance | Carte produite après correction de l’abondance | PASS |
| A6 | Carte simplifiée | Carte produite | PASS |
| A7 | Carte par année, taille par abondance | Première tentative incorrecte : mauvaise variable de taille | FAIL puis corrigé |
| A8 | Correction avec `Total abundance (ind./m3 depth vol)` | Carte produite | PASS |
| A9 | Âge des casts par rapport à 2020 | Carte produite | PASS |
| A10 | Hudson 2014–2020, couleur + taille | Échec initial sur contexte long, puis succès après hausse de capacité | PASS après retry |
| A11 | Symboles différents par année | Carte produite avec légende explicite | PASS |

Artefacts principaux :

- [Carte abundance corrigée](http://localhost:8000/graphs/5585065cbb6a.png)
- [Carte Hudson couleur + symboles](http://localhost:8000/graphs/2a4d0d59511e.png)
- [Carte spatio-temporelle finale](http://localhost:8000/graphs/ca61b97876df.png)

## Les 12 graphes produits

1. [Carte de toutes les stations](http://localhost:8000/graphs/d9d0e52aa433.png)
2. [Carte de la baie de Baffin](http://localhost:8000/graphs/351825b78772.png)
3. [Carte de la baie d’Hudson](http://localhost:8000/graphs/88e68d1250c8.png)
4. [Hudson avec légende des casts](http://localhost:8000/graphs/7ebdf52f806d.png)
5. [Baffin, taille par nombre de casts](http://localhost:8000/graphs/fd32c0a65d2c.png)
6. [Carte Baffin simplifiée](http://localhost:8000/graphs/a451757de4f0.png)
7. [Baffin, couleur par année](http://localhost:8000/graphs/66f36beae1ba.png)
8. [Baffin, taille par abondance corrigée](http://localhost:8000/graphs/5585065cbb6a.png)
9. [Âge des casts par rapport à 2020](http://localhost:8000/graphs/b3d0ed8dbdf8.png)
10. [Hudson 2014–2020, couleur par année](http://localhost:8000/graphs/d0f7d52dfaa4.png)
11. [Hudson, symboles distincts par année](http://localhost:8000/graphs/2a4d0d59511e.png)
12. [Hudson, exploration spatio-temporelle](http://localhost:8000/graphs/ca61b97876df.png)

## Phase B — Exploration spatio-temporelle

| Tour | Demande | Résultat | Verdict |
|---|---|---|---|
| B1 | Petits multiples par année | Refus correct : `station_map` ne supporte qu’un axe | BLOCKED — limite de contrat |
| B2 | Carte unique avec ligne des moyennes annuelles | Contrat rejeté car la légende n’était pas attachée | FAIL |
| B3 | Même demande après correction du contrat | Carte produite | PASS |
| B4 | Nombre de stations distinctes par année | Tableau renvoyé malgré la demande graphique | FAIL — format incorrect |
| B5 | Classement année + zones + samples | Utilisation de stations comme pseudo-zones et années hors filtre dans la réponse | FAIL |
| B6 | Reprise du fichier complet | Erreur provider `Prompt tokens limit exceeded` à 103601 tokens | BLOCKED |
| B7 | Reprise après plafond applicatif à 100k | Analyse du fichier actif, 172 lignes année/station/samples, années présentes 2014–2020 | PASS partiel |
| B8 | Découpage par mers, baies, détroits | Erreur provider `Insufficient credits` | BLOCKED |

Le fichier ne contient pas de colonne explicite `zone` ou `region`. Le fallback
correct actuel est donc `STATION_NAME`, qui doit être présenté comme station et
non comme zone géographique.

## Gestion du contexte

La session a été configurée avec :

- `MAX_CONTEXT_TOKENS=100000` après constat de la limite provider à 103601 ;
- `KEEP_FULL_TOOL_TURNS=3` ;
- compaction des anciens résultats de tools volumineux ;
- conservation des trois derniers tours, du dataset actif, des artefacts et des
  skills chargés.

Sur le tour B7 :

- 146756 tokens estimés avant trimming ;
- 45 messages supprimés par trimming ;
- 5 anciens résultats compactés ;
- 26319 caractères économisés par compaction ;
- requête modèle estimée à 86495 tokens ;
- aucun dépassement de la limite applicative.

## Artefacts SSE

- [B1](../../../logs/e2e-e2e-green-spatial-20260716-exploration-01.sse)
- [B2](../../../logs/e2e-e2e-green-spatial-20260716-exploration-02-zones.sse)
- [B3](../../../logs/e2e-e2e-green-spatial-20260716-exploration-03-full-file-retry.sse)
- [B4](../../../logs/e2e-e2e-green-spatial-20260716-exploration-04-aquatic-zones.sse)

Voir [DEFECTS.md](DEFECTS.md) pour les défauts à reprendre.
