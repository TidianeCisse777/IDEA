# Enrichissement Bio-ORACLE d'un DataFrame

## Objectif

Rendre la voie canonique `enrich_with_bio_oracle` fiable, cohérente et flexible
pour enrichir une table chargée. Elle conserve strictement le grain de la table :
une ligne d'entrée reste une ligne de sortie, avec des colonnes Bio-ORACLE
ajoutées selon les coordonnées de cette ligne.

Cette spécification ne concerne ni les requêtes ponctuelles, ni les requêtes par
zone, ni le couplage historique. Ces routes restent hors du parcours proposé au
modèle.

## Contrat utilisateur

L'utilisateur fournit ou choisit :

- une ou plusieurs variables environnementales ;
- un ou plusieurs scénarios ;
- une année cible pour tout scénario SSP ;
- une couche verticale ;
- une statistique Bio-ORACLE.

Les cinq choix sont explicites. L'agent ne lance pas d'enrichissement lorsque
l'un manque : il propose les valeurs disponibles, explique les contraintes
applicables, puis attend la sélection de l'utilisateur. Une confirmation
supplémentaire reste requise avant une opération dont le coût calculé dépasse le
seuil configuré.

Par défaut, l'agent propose une présélection « copépodes » mais ne l'applique
jamais de lui-même. Elle contient : température, salinité, oxygène, nitrate,
phosphate, silicate, chlorophylle, phytoplancton, profondeur de couche
mélangée, rayonnement photosynthétiquement disponible et atténuation lumineuse.
Les variables de courant, glace, air, nébulosité et topographie restent
sélectionnables dans le catalogue complet.

## Catalogue et validation

Un catalogue déclaratif Bio-ORACLE devient l'unique source interne des noms
conviviaux, identifiants ERDDAP, unités, groupes, compatibilités de couche,
scénarios et statistiques. Il remplace la résolution permissive actuelle des
variables inconnues.

Le catalogue est validé à partir de l'index ERDDAP avant une requête ; il échoue
clairement si un choix n'est pas disponible plutôt que de deviner un identifiant
de dataset. Les libellés utilisateur restent en français ; les identifiants
ERDDAP restent de la provenance interne.

Les couches possibles sont `surface`, `benthic_min`, `benthic_mean` et
`benthic_max`. Aucune valeur de profondeur n'est implicite. Les statistiques
possibles dépendent du dataset : `mean`, `min`, `max`, `lt_min`, `lt_max` et
`range` lorsque présentes. Elles sont choisies explicitement et la colonne
sortie inclut le choix effectué.

## Exécution

1. Résoudre la table active ou `source_variable`, puis les colonnes latitude et
   longitude, sans changer le DataFrame source.
2. Valider les cinq sélections et leur compatibilité par le catalogue ; pour un
   SSP, valider aussi l'année cible parmi les tranches offertes par le dataset.
3. Dédupliquer les coordonnées sur la grille configurée, regrouper les appels
   par variable × scénario × couche × statistique × année, puis utiliser le
   cache de tuiles ERDDAP existant.
4. Ajouter une colonne de valeur et, par sélection, les colonnes de provenance
   (dataset, tranche temporelle, coordonnées de grille réellement associées).
   Ajouter un statut de correspondance par ligne sans supprimer ni agréger les
   lignes d'origine.
5. Stocker le résultat comme nouveau DataFrame de session et retourner un bloc
   Méthode décrivant les sélections, la déduplication, la couverture et les
   limites de la grille.

Les coordonnées invalides, les cellules terrestres et les échecs partiels
produisent un statut explicite par ligne. Un échec de toutes les tuiles ne crée
aucun résultat persistant.

## Description du tool et comportement de l'agent

La docstring de `enrich_with_bio_oracle` décrit le parcours comme une action
guidée : l'agent doit d'abord proposer les catégories et valeurs du catalogue,
puis appeler le tool uniquement après une sélection explicite. Elle indique
aussi que le tool enrichit chaque ligne du DataFrame et ne doit jamais être
utilisé pour produire une agrégation par zone.

Le skill Bio-ORACLE et le prompt reprennent la même règle. La règle exécutable
reste l'autorité : une omission retourne un résultat bloqué, sans I/O distant.

## Tests d'acceptation

- Un appel sans variables, scénario, couche ou statistique ne fait aucun appel
  ERDDAP et retourne les choix à fournir.
- Un SSP sans année, ou une année non disponible, est bloqué sans I/O distant.
- Une sélection valide enrichit chaque ligne et conserve l'ordre, les colonnes
  et le nombre de lignes du DataFrame source.
- Chaque choix produit une colonne de valeur et une provenance distincte,
  incluant statistique, dataset, temps et coordonnées de grille associées.
- Les alias français et les identifiants catalogués sont normalisés vers le même
  dataset ; une variable inconnue est refusée.
- Les valeurs de surface et benthiques incompatibles sont refusées avant l'appel.
- Le catalogue complet et la présélection copépodes sont proposés au modèle,
  mais aucune présélection n'est appliquée sans choix utilisateur.
- Les coordonnées manquantes, invalides, terrestres et les échecs de tuiles
  partiels restent visibles dans le statut de chaque ligne.

## Hors périmètre

- Interprétation biologique ou écologique des valeurs enrichies.
- Agrégation spatiale, comparaison de zones ou changement de grain du DataFrame.
- Modification des outils historiques point, zone ou couplage, sauf pour les
  empêcher d'être confondus avec la voie canonique.
