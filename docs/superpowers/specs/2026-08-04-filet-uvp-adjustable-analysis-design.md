# Analyse Filet–UVP à bins et profondeur ajustables

## Objectif

Refaire le scénario de démonstration Filet–UVP avec une comparaison
reproductible, lisible et modifiable par l’utilisateur. Les réglages d’analyse
doivent améliorer les graphiques sans jamais modifier la correspondance
scientifique entre un déploiement filet et un profil UVP.

## Invariants de correspondance

La table de correspondance conserve et expose :

- `station_id` normalisé comme clé d’identité obligatoire ;
- écart géographique et écart temporel ;
- statut de correspondance et preuve CTD ;
- profil UVP, projet EcoTaxa et projet EcoPart associés.

Ces critères ne sont pas des curseurs de la démo. Une ligne non certifiée ne
devient pas une comparaison d’abondance certifiée par un changement de bin ou
de profondeur.

## Réglages utilisateur

Les deux seuls réglages analytiques sont :

- largeur des strates verticales, en mètres (5 m par défaut) ;
- plage de profondeur incluse, bornée par `min_depth_m` et `max_depth_m`.

Ils s’appliquent après la jointure Filet–UVP canonique. La donnée source et le
bin de jointure EcoTaxa–EcoPart restent intacts. Chaque résultat dérivé porte
les paramètres appliqués et ses colonnes de profondeur/bin explicites.

## Flux

1. Charger les fichiers filet et obtenir les correspondances Filet–UVP
   certifiées.
2. Exporter les objets EcoTaxa correspondants, enrichir avec EcoPart, puis
   joindre localement au filet.
3. Construire une table analytique dérivée depuis la table canonique : filtre
   de profondeur, regroupement aux bins demandés et densités en `ind./m³`.
4. Calculer, au même grain station/profil/strate, abondance filet, abondance
   UVP, ratio, écart et log2-ratio.
5. Produire des graphiques à partir de cette seule table dérivée.

## Transparence attendue

Chaque réponse et chaque graphique indiquent :

- le nombre de paires certifiées et les exclusions ;
- les règles station/temps/CTD ayant autorisé la comparaison ;
- la largeur de bin et la plage de profondeur choisies ;
- les unités (`ind./m³`) et la formule du ratio ;
- les limites : différences instrumentales et aucune interprétation biologique
  automatique.

## Graphes de démonstration

- profil vertical comparé Filet–UVP par station/profil ;
- abondance normalisée par strate ;
- ratio UVP/Filet et écart absolu par strate ;
- synthèse par station/profil, avec les métriques de correspondance visibles.

## Tests d’acceptation

- une correspondance avec station ou temps non conforme est exclue ;
- le bin 5 m de la jointure EcoTaxa–EcoPart reste inchangé ;
- modifier le bin analytique regroupe uniquement la table dérivée ;
- le filtre de profondeur modifie uniquement la table dérivée ;
- les ratios utilisent des densités en `ind./m³` au même grain ;
- le scénario e2e produit les variables et graphes avec paramètres et
  provenance visibles.
