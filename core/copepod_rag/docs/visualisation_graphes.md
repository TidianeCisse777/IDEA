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
