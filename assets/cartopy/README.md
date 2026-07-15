# Fonds cartographiques embarqués

IDEA embarque quatre couches Natural Earth à **deux échelles** (`110m` bassin
entier et `50m` régional), utilisées par ses cartes Cartopy :

- `ne_{110m,50m}_land` ;
- `ne_{110m,50m}_ocean` ;
- `ne_{110m,50m}_coastline` ;
- `ne_{110m,50m}_admin_0_boundary_lines_land`.

Le `50m` est nécessaire parce que les singletons `cfeature.LAND/OCEAN/COASTLINE`
portent un `AdaptiveScaler` qui, au rendu d'une carte régionale zoomée (baie de
Baffin, baie d'Hudson, mer du Labrador), choisit une échelle plus fine que le
`110m` par défaut. `core.cartography._install_scale_guard` borne toute échelle
demandée (y compris `10m` ou `auto`) à la plus fine échelle vendorée (`50m`),
de sorte que Cartopy ne lit **que** ces fichiers et ne déclenche jamais de
téléchargement réseau.

Source : [Natural Earth](https://www.naturalearthdata.com/downloads/) — vecteurs
physiques et culturels `110m` et `50m`, distribués par le téléchargeur Natural
Earth de Cartopy 0.25.0. Acquisition : 15 juillet 2026. Natural Earth dédie ces
données au domaine public.

Ces fichiers totalisent environ 5 Mo et permettent de rendre les cartes sans
accès réseau après un clone, une archive du projet ou le téléchargement de
l'image Docker. Ils sont distincts du shapefile IHO lourd placé sous
`data/geo/sources/`, qui sert uniquement à reconstruire le registre des zones.
