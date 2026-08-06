# Décisions de visualisation scientifique — NeoLab
# Format RAG — chaque section délimitée par `---` est un chunk autonome

---

# Quand consulter cette référence pour un graphique

Mots-clés : graphique, tracé, carte, profil, comparaison station, choix de figure, plot_df, unité, données manquantes

Cette référence aide à choisir et préparer une visualisation lorsque la règle
métier ou graphique n'est pas déjà certaine. Elle ne remplace jamais les
données réellement chargées : les colonnes, types, valeurs manquantes et unités
doivent venir de la table active. Elle ne remplace pas non plus les outils de
source, de jointure certifiée ou d'enrichissement.

Question RAG utile : « avec une table d'abondance par taxon, comment préparer
une comparaison entre stations ? ». Question RAG inutile : « quelles sont les
valeurs de température de mes stations ? » — cela demande les données et un
outil d'analyse, pas une réponse documentaire.

---

# Préparer `plot_df` avant tout tracé

Mots-clés : plot_df, filtrer, valeurs manquantes, NaN, conversion numérique, identifiant, unité, grain, agrégation

`plot_df` est la table explicite effectivement dessinée. Elle doit contenir le
périmètre demandé, les colonnes vraiment représentées et au moins une ligne
complète après filtrage. Convertir seulement les mesures et coordonnées utilisées
en numérique, puis exclure ou signaler les valeurs manquantes ; une absence de
mesure ne devient jamais zéro.

Les identifiants (`sample_id`, station, cast, profil, analyse, projet, taxon)
sont des libellés catégoriels. Ne pas les transformer artificiellement en axes
numériques ou en valeurs de mesure. Chaque axe ou échelle de couleur doit donner
le nom de la mesure et son unité réelle.

Avant de tracer, placer les données au bon grain : une ligne par échantillon ou
station pour les comparaisons spatiales/temporelles ; une ligne par taxon ou
catégorie pour une composition ; une ligne par strate de profondeur pour un
profil. Des lignes taxonomiques brutes ne sont pas automatiquement des
échantillons indépendants.

---

# Choisir le type de figure à partir de la question

Mots-clés : carte, station, profil vertical, composition taxonomique, série temporelle, comparaison, graphique approprié

| Question | Grain de `plot_df` | Figure adaptée |
|---|---|---|
| Où sont les observations ? Quelle est leur distribution géographique ? | position de sample, profil ou station | carte Cartopy |
| Les stations diffèrent-elles pour une mesure ? | une ligne par station ou station × période | comparaison par station (barres, points ou boîte selon la distribution) |
| Comment une mesure change-t-elle avec la profondeur ? | une ligne par profondeur/strate et profil | profil vertical |
| Quels taxons composent les échantillons ? | taxon × échantillon/station | barres empilées ou heatmap après agrégation |
| Comment une mesure évolue-t-elle dans le temps ? | date/période × groupe | série temporelle |

Le format suit la question et les données, non un template imposé. Si le choix
change le sens scientifique — par exemple somme versus moyenne, ou station
versus échantillon — expliciter l'hypothèse ou poser une seule question courte.

---

# Carte géographique : coordonnées réelles et Cartopy

Mots-clés : carte, Cartopy, latitude, longitude, station_map, projection, polygone, zone marine, distribution spatiale

Une demande de carte géographique utilise Cartopy avec latitude/longitude
réelles, projection, côtes et géométrie de zone autorisée quand une zone est
requise. Un simple nuage longitude–latitude ne remplace pas une carte. Les
marques représentent le grain choisi : position de station/sample/profil ou
agrégat spatial clairement défini ; ne pas montrer chaque objet taxonomique
brut comme s'il était une station indépendante.

L'étendue doit couvrir les données et la zone demandée, sans géométrie inventée.
Les couleurs, tailles ou formes encodent seulement une variable réellement
présente et expliquée. Pour des points très denses, préférer transparence,
marqueurs petits ou agrégation plutôt qu'un amas opaque.

---

# Comparer correctement les stations

Mots-clés : station, comparaison, barplot, boîte, moyenne, médiane, réplication, catégories, abondance

Une comparaison par station commence par une table au grain station ou
station × période/réplicat, selon la question. Agréger les lignes d'objets ou
de taxons avant le graphique lorsque l'objectif est une mesure d'échantillon
ou de station. Conserver les réplications si elles sont nécessaires pour montrer
la variabilité ; ne pas masquer plusieurs stations ou dates sous une moyenne non
annoncée.

Traiter le nom ou l'ID de station comme une catégorie ordonnée, avec des labels
lisibles. Choisir barres/points/boîtes selon ce qui est disponible : une seule
valeur agrégée par station peut être montrée par barres ou points ; plusieurs
réplicats appellent plutôt des points ou une boîte. L'axe de mesure conserve son
unité et la politique des zéros est annoncée si elle influe sur la comparaison.

---

# Profil vertical : profondeur orientée correctement

Mots-clés : profil vertical, profondeur, CTD, strate, depth, vertical_profile, inversion axe, filet UVP

Un profil vertical relie une mesure à la profondeur, avec profondeur sur l'axe
vertical inversé : les faibles profondeurs en haut, les grandes en bas. Utiliser
des observations ou agrégats appartenant aux mêmes strates de profondeur et
indiquer les unités des deux axes.

Pour une comparaison filet ↔ UVP, ne comparer que des concentrations et volumes
validés dans le même intervalle de profondeur, le même périmètre taxonomique et
la même unité normalisée. Un profil UVP complet ne peut pas être opposé à une
seule strate de filet. Les statuts de validation ou d'incertitude doivent rester
visibles lorsqu'ils déterminent quels points sont comparables.

---

# Lisibilité minimale d'une figure scientifique

Mots-clés : titre, axes, unités, légende, couleur, lisibilité, labels, ticks, valeurs manquantes, incertitude

Une figure répond à une question identifiable : titre concis, axes nommés avec
unités, légende ou barre de couleur seulement si elle explique un encodage réel.
Réduire, agréger ou espacer les catégories avant que les labels ne se
chevauchent. Les taxons à nom long peuvent être raccourcis au nom terminal ;
les catégories nombreuses peuvent être limitées aux principales avec « Autres »
si cette réduction est annoncée.

La couleur ne doit pas être l'unique moyen de distinguer un statut important :
associer libellé, forme, style ou hachure lorsque nécessaire. Ne pas tirer de
conclusion biologique depuis l'apparence de la figure ; la figure décrit les
données et toute limite de couverture, de valeur manquante ou de validation.

---

# Charte NeoLab Ocean — rendu de rapport scientifique

Mots-clés : style, rapport, publication, lisibilité, cartographie, CTD, profils, palettes

Le moteur de rendu applique une charte NeoLab Ocean à toute figure : fond blanc,
typographie homogène, titres et axes hiérarchisés, grille légère, résolution
élevée et légende encadrée lorsqu'elle est pertinente. Ce style est imposé par
l'exécuteur ; le code ne doit pas réinitialiser le style global.

La figure conserve une hiérarchie scientifique : données et incertitudes au
premier plan, repères géographiques ou grille au second plan, sans effets
décoratifs. Les catégories utilisent une palette contrastée et accessible ; une
variable physique continue conserve une palette océanographique appropriée.
Une anomalie ou un écart par rapport à une référence exige une palette
divergente centrée sur cette référence, généralement zéro.

Pour une carte, employer une projection adaptée, un fond marin discret, des
traits de côte fins et des contours de zone seulement lorsqu'ils apportent une
information. Pour un profil CTD, inverser l'axe profondeur/pression, aligner les
panneaux et conserver la même convention entre variables. Pour une section,
marquer les stations et rendre visibles les unités, la direction du transect et
les isolignes réellement pertinentes. Pour un diagramme T-S, les isopycnes
restent fines et neutres afin que les observations et groupes documentés restent
lisibles.

---

# Bibliothèques océanographiques pour une figure

Mots-clés : cmocean, gsw, xarray, TEOS-10, densité, palette thermique, salinité, oxygène, NetCDF

`cmocean` sert aux échelles continues de variables physiques : `thermal` pour
la température, `haline` pour la salinité, `oxy` pour l'oxygène et `speed` pour
la vitesse. Toujours conserver une barre de couleur libellée avec l'unité de
la mesure source.

`gsw` permet un calcul TEOS-10, par exemple une variable physique dérivée de
mesures CTD. Ne l'utiliser que lorsque toutes les entrées requises et leurs
unités sont réellement disponibles ; aucune entrée manquante n'est devinée et
le calcul ne constitue pas une interprétation biologique.

`xarray` sert aux jeux de données déjà disponibles sous forme de grille ou de
dimensions multiples, notamment NetCDF : sélectionner d'abord le temps, la
profondeur et la zone nécessaires, puis transmettre la coupe ou grille à
Matplotlib/Cartopy. Les tableaux ordinaires EcoTaxa, EcoPart et NeoLab restent
traités avec pandas. L'autorisation d'importer xarray ne crée pas, à elle seule,
un chargeur NetCDF.

---

# Règle de départ pour toute figure océanographique

Mots-clés : océanographie, CTD, figure, graphique, RAG obligatoire, plan, unités, contrôle qualité

Consulter cette référence une seule fois lorsqu'une recette océanographique ou
une convention peut changer le résultat : T-S/densité, section, anomalie,
courant, Hovmöller ou variable inconnue. La consultation contient les variables,
le type de figure visé et les unités connues. Un profil, une comparaison ou une
carte directe déjà maîtrisés passent directement à l'inspection puis au tracé.
Le RAG détermine la recette et les prérequis ; la table active détermine les
valeurs, le périmètre et les unités effectivement affichées.

Ne pas faire plusieurs consultations documentaires ni attendre une confirmation
après le RAG : poursuivre directement avec le graphe si les colonnes requises
sont présentes. Si elles ne le sont pas, annoncer précisément ce qui manque et
ne pas substituer une autre variable.

---

# Catalogue de figures océanographiques

Mots-clés : catalogue, profil, T-S, section, carte, série temporelle, Hovmöller, courant, CTD, biogéochimie

| Dimensions et question | Figure adaptée | Prérequis |
|---|---|---|
| variable + profondeur, un profil/cast | profil vertical | pression ou profondeur avec unité |
| température + salinité | diagramme T-S / SA-CT | nature et unité exactes des variables |
| variable + distance/latitude + profondeur | section verticale | ordre réel du transect et couverture suffisante |
| variable + latitude/longitude à un niveau/date | carte ou carte d'anomalie | mêmes niveau et période comparés |
| variable + date | série temporelle | dates valides et grain annoncé |
| variable + temps + profondeur | Hovmöller | couverture régulière ou binning annoncé |
| deux propriétés au même sample/cast | nuage propriété-propriété | co-localisation des mesures |
| plusieurs casts | profils superposés ou facettes | légende lisible et même convention verticale |
| composantes u + v | vecteurs de courant, couleur vitesse | même repère, unité, temps et profondeur |
| abondance + contexte physique | relation exploratoire | grain biologique correct et co-localisation |

Une grille incomplète ne justifie pas une interpolation silencieuse : préférer
points, profils ou facettes et signaler la couverture.

---

# Profils CTD et contrôle qualité visuel

Mots-clés : CTD, profil vertical, température, salinité, oxygène, nitrate, fluorescence, pression, profondeur, qualité

Les profils de température, salinité, oxygène, nitrate ou fluorescence contre
pression/profondeur sont la première figure à produire pour vérifier une
campagne. Un seul cast peut être une ligne ou des points ; plusieurs casts
demandent des facettes ou une couleur/une légende par station, jamais une ligne
reliant des stations différentes.

La variable verticale doit être nommée exactement : `Pression (dbar)` si la
colonne est une pression, `Profondeur (m)` si elle est une profondeur. Inverser
l'axe vertical pour une profondeur ou une pression croissante vers le bas. Les
profils servent à repérer des valeurs aberrantes ; un point isolé n'est pas
automatiquement supprimé ou corrigé.

---

# Diagramme T-S et isopycnes TEOS-10

Mots-clés : T-S, diagramme température salinité, SA CT, isopycnes, sigma0, densité, TEOS-10, masse d'eau

Pour un diagramme densité rigoureux, exiger salinité pratique SP (PSS-78),
température in situ ITS-90, pression (dbar), longitude et latitude. Calculer
SA à partir de SP, pression et position, puis CT à partir de SA, température et
pression. Tracer **SA (g/kg)** en abscisse et **CT (°C)** en ordonnée ; calculer
les isopycnes sigma0 directement sur une grille SA × CT.

Ne pas appeler « exactes » des isopycnes calculées sur des axes SP × température
in situ avec une pression/position moyenne : elles sont une approximation et
doivent être libellées ainsi. La couleur peut représenter `Pression (dbar)`,
jamais « profondeur / pression » si seule la pression a été fournie. Un T-S
décrit des regroupements et mélanges possibles ; il ne prouve pas seul une masse
d'eau ou un mécanisme.

Référence : TEOS-10, norme distinguant SA de SP et CT de la température in situ :
https://www.teos-10.org/index.htm

---

# Sections verticales et transects

Mots-clés : section verticale, transect, coupe, distance, latitude, longitude, profondeur, contourf, CTD

Une section représente une variable continue le long d'un transect : abscisse =
distance cumulée, latitude ou longitude ; verticale = profondeur ; couleur =
variable avec unité. Trier les stations dans l'ordre réel du transect avant toute
coupe et marquer leurs positions. Ne pas trier uniquement par numéro de station
sans vérifier qu'il représente bien l'ordre spatial.

Utiliser une section colorée/contourée seulement si les stations et niveaux
couvrent suffisamment le plan distance-profondeur. Sinon tracer les points ou
les profils en facettes. Toute interpolation, grille ou lissage doit être nommé,
limité à l'enveloppe échantillonnée, et ne doit pas créer d'information derrière
la côte ou sous le fond. Les sections sont adaptées à température, salinité,
densité, oxygène, nutriments et fluorescence.

Les atlas WOCE utilisent des sections verticales et des graphiques
propriété-propriété pour les propriétés hydrographiques :
https://woceatlas.ucsd.edu/

---

# Cartes, anomalies et vecteurs de courant

Mots-clés : carte océanographique, surface, profondeur standard, anomalie, courant, u v, vitesse, direction, bathymétrie

Une carte compare des observations au même horizon : même date/période et même
profondeur, ou couche explicitement agrégée. Pour une variable mesurée à de
nombreuses profondeurs, sélectionner une profondeur/couche avant de cartographier
plutôt que mélanger toute la colonne d'eau. Une anomalie exige une référence
calculée et affichée (moyenne de campagne, climatologie ou baseline documentée) ;
sans référence, produire une carte de valeurs observées.

Pour les courants, utiliser u et v seulement lorsqu'ils ont le même repère, la
même unité et le même temps/profondeur. Les flèches donnent la direction ; la
couleur ou la longueur peut donner la vitesse. Sous-échantillonner des flèches
trop nombreuses de façon annoncée. La bathymétrie ou la côte est un contexte ;
ne pas interpréter une frontière de zone comme une frontière physique dynamique.

---

# Séries temporelles et diagrammes Hovmöller

Mots-clés : série temporelle, Hovmöller, temps profondeur, saisonnalité, anomalie, moyenne mobile, incertitude

Une série temporelle montre une mesure à grain constant : observation, moyenne
journalière, mensuelle ou campagne. Le grain choisi, les agrégations et le
nombre d'observations par période doivent être visibles ou rapportés. Ne pas
relier par une ligne de longues lacunes temporelles ; utiliser points ou segments
séparés. Une moyenne mobile ne remplace jamais les observations et doit être
étiquetée avec sa fenêtre.

Un Hovmöller temps-profondeur exige un échantillonnage assez régulier pour une
grille. Sinon utiliser un nuage temps-profondeur ou des profils répétés. Les
anomalies temporelles doivent nommer leur baseline et leur période de référence ;
elles ne sont pas calculables si la référence manque.

---

# Relations biogéochimiques et distributions

Mots-clés : oxygène, nitrate, fluorescence, chlorophylle, relation, distribution, histogramme, boîte, corrélation, copépodes

Les profils et sections d'oxygène, nitrate, fluorescence ou chlorophylle sont
les figures de base. Les nuages nitrate-oxygène, fluorescence-nitrate,
température-oxygène ou abondance-variable environnementale sont exploratoires :
les deux variables doivent être co-localisées au même sample/profil et à une
profondeur/période compatible. Afficher les points et, si utile, une tendance
descriptive ; ne pas conclure à une causalité.

Histogrammes, densités, boîtes/violons et ECDF décrivent la distribution d'une
variable par station, campagne, strate ou taxon une fois le grain fixé. Ne pas
appliquer une échelle logarithmique à des zéros ou valeurs négatives sans une
politique explicite. Les concentrations et abondances biologiques doivent être
normalisées et comparables avant toute comparaison avec l'environnement.

Les manuels GO-SHIP recommandent notamment de comparer les profils de nutriments
aux profils de salinité, température et oxygène lors du contrôle qualité :
https://www.ioccp.org/images/06Nutrients/GO-SHIPRepeatHydrographyNutrientManual_August2019_Finalv2.pdf
