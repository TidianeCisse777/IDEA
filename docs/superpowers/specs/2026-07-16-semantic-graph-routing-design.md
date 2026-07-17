# Semantic Graph Routing Design — étape 4B

**Date :** 16 juillet 2026
**Statut :** approuvé et implémenté le 16 juillet 2026
**Portée :** corriger la contradiction qui charge les skills graphiques pour toute analyse. Les procédures OGSL et autres sources restent dans la tranche 4C.

## Objectif

L'agent doit choisir le workflow graphique à partir de l'intention de sortie de l'utilisateur, sans routeur lexical fermé. Une demande de représentation visuelle charge `graph_planner`, puis `graph_writer`, puis exécute le graphique. Une demande de nombre, tableau, classement, résumé ou coordonnées reste sur la route non visuelle, même si elle emploie un verbe général comme « montrer » ou « afficher ».

## Décision sémantique

Le contrat distingue deux intentions :

1. **Sortie visuelle** — l'utilisateur demande ou implique une représentation graphique des données. Une carte de positions, une évolution représentée spatialement ou temporellement, ou un profil vertical à tracer sont des sorties visuelles même si le mot « graphique » n'est pas présent.
2. **Sortie non visuelle** — l'utilisateur demande une valeur, un calcul, un classement, un résumé, des coordonnées ou un tableau. La présentation peut être textuelle ou tabulaire sans charger les skills graphiques.

Les verbes généraux de présentation ne déterminent jamais seuls la route. « Montre les cinq stations avec le plus d'objets » reste non visuel; « montre ces stations sur une carte » est visuel. Ces exemples illustrent le raisonnement et ne constituent pas une liste de déclencheurs.

En cas d'ambiguïté réelle sur le format, l'agent privilégie la sortie non visuelle minimale. Il demande une précision seulement si le choix du format modifie matériellement le résultat demandé.

## Architecture

La correction reste dans le contrat modèle et les skills :

- une constante `GRAPH_OUTPUT_ROUTING_RULES` porte le bloc canonique;
- `COPEPOD_SYSTEM_PROMPT` injecte ce bloc une seule fois;
- la règle absolue « For ANY data analysis or visualization request » est retirée;
- `graph_planner.md` décide `visual` selon l'intention de représentation, sans liste fermée de mots;
- `graph_writer.md` devient explicitement un writer de sorties visuelles; sa branche table n'est plus une raison de le charger;
- les tables et calculs utilisent directement le tool tabulaire approprié quand une exécution est nécessaire;
- aucun classifieur Python, regex de mots-clés ou nouveau middleware n'est ajouté.

Le garde-fou exécutable existant de `run_graph` et son exigence `graph_writer` restent inchangés. Cette tranche corrige la décision du modèle; les futurs filtrages dynamiques et automates restent dans les étapes 6 et 8.

## Alignement des instructions

Le system prompt et les deux skills doivent exprimer la même séquence :

```text
intention visuelle
  → graph_planner
  → graph_writer
  → run_graph immédiatement après graph_writer

intention non visuelle
  → aucun skill graphique
  → tool spécialisé ou exécution tabulaire si nécessaire
```

Les règles de sécurité existantes restent valides : résultat vide, colonnes absentes, contrat graphique bloqué ou exécution échouée doivent rester visibles et ne produisent aucun artefact fictif.

## Stratégie TDD

Les tests déterministes sont écrits avant la correction et doivent prouver :

- disparition de la règle « ANY data analysis »;
- injection unique du contrat canonique;
- neutralité des verbes généraux de présentation;
- caractère visuel inféré d'un format ou d'une structure visuelle demandée;
- route non visuelle pour valeurs, tableaux, classements, résumés et coordonnées;
- absence de liste fermée dans `graph_planner.md`;
- `graph_writer.md` réservé aux figures;
- conservation de la séquence stricte `graph_planner → graph_writer → run_graph` pour une sortie visuelle.

## Test réel obligatoire de l'agent

Après les gates déterministes, un test agent réel contrôlé vérifie les deux frontières comportementales avec le modèle configuré, tracing désactivé et store isolé :

1. une demande non visuelle formulée naturellement avec « montre » produit le tableau ou le classement sans charger `graph_planner` ni `graph_writer`;
2. une demande visuelle sémantiquement équivalente mais demandée sur une carte, ou sous forme de profil vertical, charge les deux skills et appelle `run_graph`.

Le rapport du smoke capture les tools visibles, les appels, leurs arguments, les résultats structurés et la réponse finale. Un échec est diagnostiqué avant toute relance; aucun replay en boucle n'est autorisé.

## Critères d'acceptation

1. Les tests rouges du contrat graphique deviennent verts.
2. Une demande non visuelle ne charge aucun skill graphique.
3. Une demande visuelle exécute effectivement le graphique dans le même tour.
4. Le smoke agent réel valide les deux frontières.
5. La suite ciblée et la suite complète ne régressent pas.
6. La baseline offline conserve 100 % aux niveaux 1 et 2 et mesure le nouveau coût fixe.

## Preuves de clôture

- Cycle rouge : 8 échecs sur les contradictions visées, 16 contrats graphiques voisins déjà verts.
- Contrat canonique : `6 passed`.
- Régressions graphiques : `124 passed`.
- Suite complète : `1129 passed, 20 skipped, 4 xfailed`.
- Baseline offline : niveaux 1 et 2 à 100 %, `24 699` tokens fixes (`6 695` prompt + `18 004` schémas).
- Smoke agent réel, `openai/gpt-5.4-mini`, tracing désactivé et store isolé : la demande tabulaire avec « Montre » a appelé uniquement pandas; la demande de carte a chargé `graph_planner`, puis `graph_writer`, puis exécuté `run_graph` avec statut `success`.

La première fixture envisagée (`ecotaxa_sample_50.tsv`) avait zéro coordonnée spatiale non nulle. Le premier rendu a donc échoué correctement sans fabriquer de carte. Après diagnostic local, le smoke de validation a utilisé `zooplankton_demo_stations.tsv`, dont les 15 lignes portent des coordonnées valides.

## Hors portée

- Classification déterministe de l'intention dans le runtime Python.
- Filtrage dynamique des tools par tour.
- Refonte des contrats de rendu ou des validateurs `run_graph`.
- Modification des procédures OGSL ou des autres sources.
- Nouveau type de graphique ou changement de style visuel.
