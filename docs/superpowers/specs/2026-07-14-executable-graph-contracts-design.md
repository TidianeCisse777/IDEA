# Contrats graphiques exécutables

## Objectif

Empêcher l’affichage d’un graphique scientifiquement ou visuellement non
conforme à la demande. Les règles ne reposent plus uniquement sur le prompt :
chaque figure déclare un contrat structuré et `run_graph` vérifie la figure
matplotlib réellement produite avant de l’héberger.

## Périmètre

Quatre familles sont couvertes dans ce lot :

1. profil vertical d’abondance ;
2. relation abondance–variable environnementale ;
3. diagramme température–salinité sample–profondeur ;
4. carte d’abondance avec encodage environnemental.

Les règles de lisibilité existantes, le thème sombre et les niveaux de
confiance `confirmed` / `exploratory` / `uncertain identification` restent en
vigueur.

## Architecture

### Déclaration du contrat

Le code transmis à `run_graph` définit un dictionnaire `graph_contract`. Il
contient au minimum :

- `kind` : famille de graphique autorisée ;
- `axes` : rôle scientifique des axes x et y ;
- `inverted_axes` : liste explicite des axes inversés ;
- `mappings` : rôle des encodages taille, couleur, forme et facette ;
- `zero_policy` : représentation demandée des abondances nulles ;
- `source_variables` : colonnes effectivement utilisées.

Le contrat est une donnée d’audit, pas une instruction libre. Les clés et
valeurs admises sont validées par une fonction pure avant l’inspection de la
figure.

### Validation de la figure

Après exécution du code et avant sauvegarde :

1. vérifier la présence et la validité du contrat ;
2. identifier les axes de données déclarés ;
3. comparer l’état réel `xaxis_inverted()` / `yaxis_inverted()` au contrat ;
4. vérifier les artistes matplotlib requis par les mappings ;
5. vérifier la représentation des zéros lorsque celle-ci est obligatoire ;
6. refuser le graphique avec un message correctif machine-actionnable si un
   invariant échoue.

Une validation échouée utilise le mécanisme de blocage graphique existant : le
modèle doit corriger puis rappeler `run_graph`, sans remplacer la figure par un
tableau.

## Invariants par famille

### Profil vertical

- axe x : `abundance_ind_L` ou `abundance_ind_m3`, échelle normale ;
- axe y : profondeur en mètres, seul axe inversé ;
- aucune inversion propagée aux autres sous-graphiques ;
- les bins échantillonnés à abondance nulle restent présents.

### Relation environnementale

- une figure ou un axe indépendant par relation demandée ;
- axe d’abondance toujours normal ;
- aucune inversion héritée du profil vertical ;
- données issues de la table canonique et zéros conservés par défaut ;
- exclusion des zéros permise uniquement pour une demande explicite
  « présence seulement ».

### Diagramme température–salinité

- x = salinité ; y = température ;
- taille = abondance en `ind./L` ;
- couleur = profondeur ;
- station distinguée par forme ou facette ;
- abondances nulles affichées par cercles vides ;
- aucun axe inversé.

### Carte abondance–environnement

- axe Cartopy obligatoire ;
- position = longitude/latitude avec transformation géographique explicite ;
- taille des points = abondance en `ind./L` ;
- variable environnementale encodée par couleur ou panneau ;
- légendes distinctes pour taille et variable environnementale ;
- chaque mapping demandé doit être déclaré et présent dans la figure ;
- aucun axe géographique inversé.

## Erreurs

Les refus nomment l’invariant précis et l’état observé, par exemple :

- `graph contract blocked: abundance x-axis must remain normal` ;
- `graph contract blocked: only the depth y-axis may be inverted` ;
- `graph contract blocked: zero abundance must use hollow markers` ;
- `graph contract blocked: environmental colour mapping is missing`.

Les erreurs ne contiennent aucun nom de donnée sensible et ne sont pas
présentées comme un résultat scientifique.

## Modifications prévues

- nouveau module pur `core/graph_contracts.py` ;
- intégration dans `tools/data_tools.py` avant capture du PNG ;
- règles de production dans `agents/skills/graph_writer.md` ;
- règles de routage et obligation du contrat dans
  `agents/copepod_system_prompt.py` ;
- tests unitaires des contrats et tests d’intégration de `run_graph` ;
- scénarios curl réels pour chaque famille prioritaire.

## Stratégie TDD

Ordre rouge–vert :

1. validation de schéma et absence de contrat ;
2. profil vertical conforme et inversions invalides ;
3. relations environnementales avec axes indépendants ;
4. diagramme température–salinité et zéros creux ;
5. carte Cartopy et mappings complets ;
6. intégration `run_graph`, suite complète, puis curl agent.

## Critères d’acceptation

- une figure conforme est rendue sans changement d’API utilisateur ;
- chacune des erreurs observées dans le scénario Baffin est bloquée par un test
  automatisé ;
- un échec explique la correction attendue et interdit le repli en tableau ;
- les anciens graphiques couverts par les tests restent fonctionnels ;
- la suite complète et les scénarios curl passent.
