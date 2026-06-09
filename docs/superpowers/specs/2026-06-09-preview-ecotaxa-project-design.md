# Aperçu léger d'un projet EcoTaxa

## Objectif

Permettre à l'agent de présenter rapidement un projet EcoTaxa sans lancer
d'export complet, télécharger de fichier ou modifier la session d'analyse.

## Architecture

`EcotaxaClient.preview_project(project_id, limit=10)` orchestre trois endpoints
EcoTaxa authentifiés :

1. `GET /projects/{project_id}` pour les métadonnées;
2. `POST /object_set/{project_id}/summary?only_total=false` pour les comptages;
3. `POST /object_set/{project_id}/query` avec `window_size=limit` pour un
   échantillon d'objets.

La requête d'objets demande uniquement des champs standards disponibles sur
les projets EcoTaxa :

- `obj.orig_id`;
- `obj.objdate`;
- `obj.depth_min`;
- `txo.display_name`.

Le client retourne une structure Python normalisée contenant `metadata`,
`summary` et `objects`.

## Tool LangChain

`make_source_tools(thread_id)` expose `preview_ecotaxa_project(project_id)`.
Le tool rend un Markdown compact avec :

- identifiant et titre;
- instrument, statut et droit du compte;
- nombre total d'objets;
- pourcentages classifiés et validés;
- comptages validés, douteux et prédits;
- tableau des 10 premiers objets.

Une liste vide d'objets reste un résultat valide. Les erreurs utilisent le même
préfixe contrôlé que les autres tools EcoTaxa. Le tool ne touche pas au
`session_store`.

## Routage de l'agent

Les trois tools EcoTaxa ont des responsabilités exclusives :

- `list_ecotaxa_projects` pour « quels projets sont disponibles ? »;
- `preview_ecotaxa_project` pour « présente-moi », « aperçu », « détails »,
  « combien d'objets » ou « montre quelques objets »;
- `query_ecotaxa` pour « charge », « exporte », « télécharge » ou lorsqu'une
  analyse complète exige le DataFrame.

L'agent ne doit pas lancer un export complet pour une simple demande
d'information sur un projet. Le skill `ecotaxa_query` rappelle cette séparation.

## Tests TDD

Les tests couvrent :

- les trois appels HTTP et leurs paramètres;
- la normalisation des métadonnées, comptages et objets;
- le rendu Markdown du tool;
- le cas sans objets;
- le retour contrôlé d'une erreur;
- l'absence de mutation de session;
- l'enregistrement du tool;
- les règles de routage du prompt et du skill;
- une vérification réelle sur un projet accessible.

## Hors portée

- images et miniatures;
- pagination interactive;
- filtre taxonomique de preview;
- téléchargement ou export;
- pourcentage de progression d'un export;
- modification du frontend Open WebUI.
