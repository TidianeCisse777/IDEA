# Fonds cartographiques embarqués

IDEA embarque uniquement les quatre couches Natural Earth à l'échelle `110m`
utilisées par ses cartes Cartopy :

- `ne_110m_land` ;
- `ne_110m_ocean` ;
- `ne_110m_coastline` ;
- `ne_110m_admin_0_boundary_lines_land`.

Source : [Natural Earth](https://www.naturalearthdata.com/downloads/110m-cultural-vectors/)
et [vecteurs physiques 110m](https://www.naturalearthdata.com/downloads/110m-physical-vectors/),
distribués par le téléchargeur Natural Earth de Cartopy 0.25.0. Acquisition :
15 juillet 2026. Natural Earth dédie ces données au domaine public.

Ces fichiers totalisent moins de 1 Mo et permettent de rendre les cartes sans
accès réseau après un clone, une archive du projet ou le téléchargement de
l'image Docker. Ils sont distincts du shapefile IHO lourd placé sous
`data/geo/sources/`, qui sert uniquement à reconstruire le registre des zones.
