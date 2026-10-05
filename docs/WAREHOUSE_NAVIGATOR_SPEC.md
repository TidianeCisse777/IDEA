# Navigateur de couverture du warehouse NeoLab — V1

## Question à laquelle répondre

> Quelles données sont réellement disponibles dans le warehouse pour le
> périmètre que je consulte ?

Le navigateur est une surface de découverte avant analyse. Il ne remplace ni
les requêtes scientifiques, ni les graphiques, ni la consultation détaillée
des objets.

## Périmètre utilisateur

L'utilisateur peut restreindre l'inventaire par espace, temps et projet.
L'interface résume ensuite les sources disponibles : EcoTaxa, EcoPart, CTD
Amundsen et FILET. Le détail d'un sample est consultable depuis son point sur
la carte.

Pour le périmètre choisi, elle affiche seulement :

- zones, positions, périodes, campagnes et projets couverts ;
- nombre de samples FILET et de profils UVP et CTD ;
- nombre d'objets EcoTaxa associés à EcoPart, sans liste d'objets ;
- disponibilité CTD et FILET ;
- correspondances FILET–UVP acceptées selon une fenêtre temporelle choisie ;
- profils sans coordonnées, absences et données associées disponibles.

Une vue détaillée n'est ouverte qu'après une demande explicite de l'utilisateur.

## Contrat scientifique et technique

- Les chiffres viennent des tables et vues PostgreSQL du warehouse ; aucune
  valeur, relation ou couverture n'est inférée par le navigateur.
- Chaque métrique affiche son grain et sa provenance. Une abondance UVP est
  explicitement calculée au grain bin ou profil à partir des objets EcoTaxa et
  du volume EcoPart.
- Les absences sont distinctes des données non encore importées, ambiguës ou
  non appariées.
- Les objets individuels ne figurent pas dans l'interface V1 ; seuls leurs
  comptes agrégés sont exposés.
- La V1 est un navigateur de couverture, indépendant de l'agent
  conversationnel. L'exposition d'un outil à LangGraph sera une étape
  ultérieure.

## Première interface

La première page comporte une carte, des couches UVP et FILET, des filtres
espace/temps/projet et un résumé de couverture. Elle doit rendre immédiatement
lisible un état tel que :

> Baie de Baffin · 2024 : 123 profils UVP, 4 279 581 objets EcoTaxa associés,
> 94 profils CTD et 272 échantillons FILET, du 12 août au 13 octobre 2024.

## Suivi UX

L’état de l’interface, les références de conception, les priorités et leurs
critères de réussite sont suivis dans
[WAREHOUSE_NAVIGATOR_UX_AUDIT.md](WAREHOUSE_NAVIGATOR_UX_AUDIT.md).
