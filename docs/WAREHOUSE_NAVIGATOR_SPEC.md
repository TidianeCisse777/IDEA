# Navigateur de couverture du warehouse NeoLab — V1

## Question à laquelle répondre

> Quelles données sont réellement disponibles dans le warehouse pour le
> périmètre que je consulte ?

Le navigateur est une surface de découverte avant analyse. Il ne remplace ni
les requêtes scientifiques, ni les graphiques, ni la consultation détaillée
des objets.

## Périmètre utilisateur

L'utilisateur peut restreindre l'inventaire par espace, temps, projet et
sample. L'interface résume ensuite les sources disponibles : EcoTaxa, EcoPart,
CTD Amundsen et FILET.

Pour le périmètre choisi, elle affiche seulement :

- zones, positions, périodes, campagnes et projets couverts ;
- nombre de samples, profils et bins ;
- nombre d'objets EcoTaxa associés à EcoPart, sans liste d'objets ;
- disponibilité d'une série d'abondance taxonomique ;
- disponibilité CTD et FILET ;
- liens disponibles entre EcoTaxa, EcoPart, CTD et FILET ;
- manques, non-appariés et ambiguïtés, avec leur statut.

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

La première page comporte une matrice de disponibilité par source, des cartes
de métriques, des filtres espace/temps/projet/sample et des tableaux de
couverture. Elle doit rendre immédiatement lisible un état tel que :

> Baie de Baffin · 2024 : 123 profils EcoPart, 13 800 bins, 3 projets
> EcoTaxa liés, 121 358 objets `Copepoda<Multicrustacea`, CTD partiellement
> disponible, FILET absent du filtre.
