# Sources géographiques externes (non commitées)

Ce dossier contient les données sources utilisées par `core/geo/build_registry.py`
pour produire `data/geo/zones_registry.geojson`.

Tout le contenu de ce dossier est gitignoré (cf `.gitignore` `data/geo/sources/**`).
La sortie compilée (`data/geo/zones_registry.geojson`) est commitée, donc
**il n'est pas nécessaire d'avoir ces sources pour utiliser `core.geo`** — elles
ne servent qu'à rebâtir le registry.

## World_Seas_IHO_v3/

Marine Regions / VLIZ — World Seas, IHO Sea Areas v3, baseline S-23.

- Téléchargement : https://www.marineregions.org/downloads.php
  (chercher "IHO Sea Areas, version 3" → shapefile zip ~50 MB)
- Licence : voir `LICENSE_IHO_v3.txt` du zip (CC-BY 4.0, attribution VLIZ)
- Citation : Flanders Marine Institute (2018). IHO Sea Areas, version 3.
  Available online at https://www.marineregions.org/. https://doi.org/10.14284/323

Fichiers attendus dans `World_Seas_IHO_v3/` :
- `World_Seas_IHO_v3.shp` (~142 MB, gitignoré)
- `World_Seas_IHO_v3.shx`
- `World_Seas_IHO_v3.dbf`
- `World_Seas_IHO_v3.prj`
- `World_Seas_IHO_v3.cpg`
- `World_Seas_IHO_v3.qpj`
- `LICENSE_IHO_v3.txt`

## Rebâtir le registry

```bash
python -m core.geo.build_registry
# Lit data/geo/sources/World_Seas_IHO_v3/ → écrit data/geo/zones_registry.geojson
```
