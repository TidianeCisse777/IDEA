# Audit UX et plan d’amélioration du navigateur de couverture

**Date :** 5 octobre 2026  
**Surface auditée :** `warehouse_navigator/`, service local `http://localhost:8090`  
**Référence fonctionnelle :** [WAREHOUSE_NAVIGATOR_SPEC.md](WAREHOUSE_NAVIGATOR_SPEC.md)

## But du produit

Le navigateur doit répondre rapidement à une seule question :

> Quelles données sont réellement présentes dans le warehouse pour le
> périmètre que je consulte ?

L’utilisateur principal est un membre de NeoLab qui prépare une exploration ou
une requête scientifique. Il doit pouvoir confirmer l’espace, la période, les
projets et les méthodes disponibles avant d’interroger les données. La carte
n’est pas encore un environnement d’analyse biologique.

## Méthode de l’audit

L’audit combine :

- la recette réelle du navigateur et de ses filtres ;
- l’inspection de l’interface à une largeur de 884 px ;
- les contrats UI et les contrôles live SQL/API existants ;
- les principes de NASA Earthdata Search, NOAA Digital Coast et Copernicus
  Marine MyOcean Pro ;
- les contrôles d’accessibilité, d’interaction, de chargement et de mise en page
  du guide `ui-ux-pro-max`.

Les recommandations sont classées selon leur effet sur la compréhension de la
couverture, leur risque avant la démonstration et leur coût probable. Aucun
changement de données ou de sémantique scientifique n’est proposé ici.

## Références retenues

### NASA Earthdata Search

Earthdata Search associe filtres spatiaux et temporels, carte et résultats de
catalogue. Son intérêt pour NeoLab est le parcours de découverte : définir un
périmètre, voir immédiatement ce qui correspond, puis ouvrir les détails.

- Guide : <https://www.earthdata.nasa.gov/s3fs-public/2024-08/Getting_Started_with_Earthdata_Search.pdf>
- Webinaire : <https://www.earthdata.nasa.gov/fr/learn/webinars/learn-how-discover-access-customize-multiple-datasets-data-types-earthdata-search>
- Exemple d’architecture cartographique : <https://www.earthdata.nasa.gov/learn/webinars/modern-website-engineering-sta3cd-subsetting-tools-advanced-analysis-airborne>

### NOAA Digital Coast

NOAA recommande de définir précisément l’utilisateur, présenter d’abord le
résultat recherché, employer un langage simple, maintenir une conception
cohérente et vérifier les choix avec les utilisateurs. C’est la référence la
plus directement applicable au processus de conception NeoLab.

- Bonnes pratiques : <https://coast.noaa.gov/data/digitalcoast/pdf/best-practices.pdf>
- Formations GIS et cartographie : <https://www.coast.noaa.gov/digitalcoast/training/>
- Data Access Viewer : <https://www.coast.noaa.gov/digitalcoast/tools/dav.html>

### Copernicus Marine MyOcean Pro

MyOcean Pro fournit les modèles utiles pour les couches marines, les
observations in situ, les filtres espace-temps-profondeur, les légendes, les
fiches au clic, l’accessibilité des couleurs et les projections polaires. Il
sert de référence pour l’évolution scientifique du navigateur, sans importer
toute sa complexité dans la V1.

- Introduction : <https://help.marine.copernicus.eu/en/articles/6482737-introduction-to-myocean-pro-viewer>
- Inventaire des fonctionnalités : <https://help.marine.copernicus.eu/en/articles/4794675-overview-of-myocean-pro-features>

## État actuel

| Dimension | État | Preuve ou limite |
|---|---|---|
| Fiabilité des nombres | Solide | Les compteurs, périodes et points concordent entre SQL, API et interface. |
| Filtres spatiaux | Solide | Les 20 zones exposées passent un oracle spatial indépendant. |
| Retour de chargement | Solide | Un indicateur léger reste visible pendant les requêtes. |
| Cohérence couches–résumé | Solide | Le panneau droit suit les couches et filtres visibles. |
| Compréhension des filtres actifs | Partielle | Les sélections sont enfermées dans des listes repliées et peuvent être tronquées. |
| Légende | Partielle | Elle reste statique même lorsqu’une couche est masquée. |
| Résultats vides | Partielle | Le message existe, mais n’explique pas quelle couche ou quel filtre vide le résultat. |
| Lisibilité à largeur moyenne | Faible | Sous 1024 px, le résumé passe sous une carte d’au moins 550 px et disparaît de la vue initiale. |
| Densité cartographique | Faible | Les positions proches se superposent encore à faible zoom ; seule l’agrégation des coordonnées identiques est faite. |
| Inspection des résultats | Partielle | Le clic fournit de bonnes métadonnées, mais il n’existe aucune liste courte permettant de parcourir les positions trouvées. |
| Accessibilité | Partielle | Focus et mouvement réduit sont présents ; CTD repose encore principalement sur la couleur et la carte n’a pas de vue tabulaire équivalente. |
| Reproductibilité de la vue | Faible | Les filtres ne sont pas encodés dans une URL partageable. |
| Projection arctique | À étudier | La carte Leaflet utilise la projection Web Mercator par défaut, très déformée aux hautes latitudes. |

## Ce qui fonctionne déjà et doit être préservé

- [x] Les nombres proviennent du warehouse et restent synchronisés avec les
  filtres.
- [x] Les couches UVP et FILET commandent aussi les métriques et les dates.
- [x] Les correspondances FILET–UVP affichent seulement les paires acceptées.
- [x] Les contours sans point dans les couches visibles disparaissent.
- [x] Les points regroupent les profils ou échantillons partageant une position.
- [x] Un clic zoome et ouvre les métadonnées du point ou de la comparaison.
- [x] La carte distingue les UVP ayant un CTD lié.
- [x] Le chargement, les erreurs et les réponses tardives ont des contrats UI.
- [x] Les objets EcoTaxa individuels ne sont pas exposés.

## Direction visuelle

La palette sobre actuelle, la typographie système et la séparation nette entre
filtres, carte et couverture conviennent au caractère scientifique de l’outil.
Le plan ne prévoit ni rebranding, ni effets décoratifs, ni multiplication de
cartes de métriques. L’amélioration doit venir de la hiérarchie, de l’état des
filtres, de la densité cartographique et de la continuité entre carte, résumé et
détails.

## Priorités proposées

### Lot A — clarté pour la démonstration

Ces changements ont un effet immédiat et un risque technique limité.

| ID | Action | Pourquoi | Critère de réussite | État |
|---|---|---|---|---|
| UX-01 | Afficher les filtres actifs sous forme de pastilles supprimables et ajouter « Tout effacer » | L’utilisateur doit comprendre le périmètre sans rouvrir chaque liste. | Années, zones et projets actifs sont visibles sans troncature ; chaque valeur et l’ensemble peuvent être retirés. | Terminé — recette navigateur à 884 px |
| UX-02 | Rendre la légende dynamique | Une légende qui décrit une couche masquée donne une fausse lecture de la carte. | Chaque entrée correspond exactement à une couche ou relation visible ; FILET disparaît de la légende quand FILET est masqué. | Terminé — contrat UI et recette de masquage FILET |
| UX-03 | Garder le résumé accessible entre 768 et 1024 px | À 884 px, le panneau droit est placé sous la carte et n’est plus visible pendant l’exploration. | Les compteurs restent consultables sans devoir atteindre le bas d’une carte de 550 px, par rail compact ou tiroir accessible. | Terminé — résumé compact sur la carte à 884 px |
| UX-04 | Améliorer l’état vide | `0` ne dit pas si aucune donnée existe ou si une couche a été masquée. | Le message nomme les couches et le périmètre concernés, puis propose de retirer un filtre ou de réactiver une couche. | Terminé — recette UVP vide après masquage FILET |
| UX-05 | Clarifier l’action d’application | Les filtres se déclenchent automatiquement alors qu’un bouton « Mettre à jour » reste présent. | Un seul modèle est utilisé. Recommandation : préparer les changements de périmètre, puis les appliquer ensemble ; les couches restent instantanées. | Terminé — pastille « Filtres modifiés » puis bouton d’application |

**Critère de sortie du lot A :** une personne qui n’a jamais vu l’outil peut
dire en moins de 15 secondes quelles couches, zones, années et projets sont
actifs, combien de données sont disponibles, et pourquoi une carte est vide.

### Lot B — exploration efficace

| ID | Action | Pourquoi | Critère de réussite | État |
|---|---|---|---|---|
| UX-06 | Ajouter une liste courte synchronisée avec la carte | Une carte dense ne permet pas de parcourir méthodiquement les résultats. | Une liste de positions/profils visibles affiche type, station, date et projet ; sélectionner une ligne zoome et ouvre le même détail que le point. | À faire |
| UX-07 | Adapter les symboles au niveau de zoom | Les points superposés masquent la distribution à l’échelle arctique. | À faible zoom, des agrégats indiquent le nombre ; les points individuels apparaissent à un seuil documenté. Aucun total ne change. | À faire |
| UX-08 | Simplifier les fiches agrégées | Une longue liste d’identifiants ou de matériels masque l’information principale. | La fiche montre d’abord quantité, période, stations et disponibilité ; les identifiants complets sont révélés sur demande. | À faire |
| UX-09 | Synchroniser sélection, résumé et fiche | Il faut maintenir le contexte quand l’utilisateur passe de la carte aux détails. | Le point actif est visuellement distinct, son résumé est repris dans le panneau et la fermeture restaure l’état précédent. | À faire |
| UX-10 | Encoder l’état utile dans l’URL | Une vue de couverture doit être reproductible pour une discussion ou une démonstration. | Une URL recharge les années, zones, projets, couches et fenêtre FILET–UVP sans stocker de secret. | À faire |

**Critère de sortie du lot B :** l’utilisateur peut parcourir les résultats sans
chercher au hasard sur la carte et partager exactement le même périmètre avec
un collègue.

### Lot C — cartographie arctique et accessibilité approfondie

| ID | Action | Pourquoi | Critère de réussite | État |
|---|---|---|---|---|
| UX-11 | Prototyper une projection nord-polaire | Web Mercator déforme fortement les distances et surfaces de l’Arctique. | Comparaison documentée entre la carte actuelle et une projection polaire ; décision technique prise avant toute migration. | À faire |
| UX-12 | Ne plus coder CTD uniquement par la couleur | Le violet seul est insuffisant pour certains utilisateurs. | CTD possède un second signal, par exemple anneau ou symbole, lisible en niveaux de gris. | À faire |
| UX-13 | Fournir une vue tabulaire équivalente | La carte seule est difficile pour le clavier et les lecteurs d’écran. | Les positions visibles sont accessibles sous forme de liste structurée avec les mêmes informations essentielles. | À faire |
| UX-14 | Effectuer une recette responsive et clavier | La V1 doit rester utilisable sur les écrans de démonstration et portables. | Parcours complet au clavier et vérification à 375, 768, 1024 et 1440 px, sans contenu masqué ni défilement horizontal. | À faire |

**Critère de sortie du lot C :** la représentation arctique est défendable et
le parcours essentiel ne dépend ni d’une perception précise des couleurs ni de
la souris.

## Ordre d’exécution recommandé

1. UX-01, UX-02 et UX-04 : rendre l’état courant explicite.
2. UX-03 : conserver le résumé dans le champ visuel de la démonstration.
3. UX-05 : supprimer l’ambiguïté entre application automatique et bouton.
4. Rejouer les scénarios de référence Baie de Baffin 2024, Baie d’Hudson UVP
   seul et comparaison FILET–UVP à 10 h.
5. UX-06 et UX-07 : résoudre l’exploration à l’aveugle et la densité.
6. UX-08 à UX-10 : améliorer le détail et la reproductibilité.
7. UX-11 à UX-14 : décider la projection et terminer l’accessibilité.

## Scénarios de recette communs

Chaque lot doit préserver les scénarios suivants :

1. **Vue globale :** 585 UVP, 10 479 780 objets associés, 380 CTD et 6 102
   FILET ; 199 UVP sans coordonnées sont indiqués sans être cartographiés.
2. **Baie de Baffin, 2024 :** 123 UVP, 4 279 581 objets, 94 CTD et 272 FILET.
3. **Baie d’Hudson :** 235 FILET et 0 UVP ; le contour disparaît avec UVP seul.
4. **Comparaison 10 h :** 20 UVP, 130 FILET, 12 CTD et 554 752 objets pour les
   paires acceptées cartographiables.
5. **Sélection multiple :** les totaux représentent l’union géographique sans
   double compte et les contours vides ne sont pas affichés.
6. **Erreur et concurrence :** une erreur efface les nombres périmés et une
   ancienne réponse ne remplace jamais une sélection plus récente.

## Hors périmètre de cette amélioration

- ajouter des objets EcoTaxa individuels à la carte ;
- interpréter biologiquement les abondances ;
- transformer la V1 en outil complet de graphiques océanographiques ;
- ajouter une projection polaire sans prototype et validation ;
- changer les grains, liens ou règles scientifiques du warehouse ;
- reproduire toute la complexité de NASA Earthdata ou Copernicus MyOcean.

## Règle de suivi

Le tableau des lots constitue le suivi UX. Une ligne passe à `Terminé` seulement
si son critère de réussite est vérifié dans l’interface et si les scénarios de
recette affectés réussissent. Une modification CSS ou un test unitaire isolé ne
suffit pas. Le lot A est terminé pour les cinq lignes ci-dessus ; les lots B et
C restent ouverts.
