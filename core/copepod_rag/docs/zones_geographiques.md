# Zones géographiques NeoLab — Amundsen et campagnes arctiques

Mots-clés : zones géographiques, baie de Baffin, mer de Beaufort, golfe du Saint-Laurent, baie d'Hudson, baie de James, baie d'Ungava, détroit d'Hudson, détroit de Davis, Hawke Channel, Nunavik, Arctique, stations, latitude, longitude, filtrage spatial

## Comment filtrer les données par zone

**Toujours appeler le tool `get_zone_info(zone_name=...)`** pour obtenir le polygone précis et la bbox d'une zone nommée. Le tool renvoie :

- `canonical` : nom canonique en français
- `source` : provenance du polygone (IHO Marine Regions v3, NeoLab cut, NeoLab composite)
- `bbox` : `{south, west, north, east}` — enveloppe rectangulaire, à utiliser pour les requêtes EcoTaxa `find_*_in_region` ou pour un pré-filtre pandas rapide
- `polygon_wkt` : polygone précis (WKT, WGS84) — à utiliser via `shapely.wkt.loads(...).contains(...)` quand la précision station-niveau compte (ex. distinguer Baie d'Ungava de Détroit d'Hudson, Baie de James de Baie d'Hudson)
- `pandas_filter` : expression `df[(df['latitude'] >= ...) & ...]` prête à coller dans `run_pandas` pour un filtre bbox

**Ne jamais coder en dur des bornes lat/lon dans une réponse ou un script** — les valeurs viennent toujours du tool.

## Zones couvertes (contexte scientifique)

### Nord du Québec / Arctique de l'Est

- **Baie d'Hudson** — eaux peu profondes (max ~250 m), saisonnières, couverture de glace importante en hiver. Polygone IHO + coupe pour séparer Baie de James au sud.
- **Baie de James** — extension méridionale de la Baie d'Hudson, eaux très peu profondes, fortement influencée par les apports d'eau douce (rivières La Grande, Eastmain, Rupert). Limite Cap Henrietta Maria / Pointe Louis-XIV.
- **Détroit d'Hudson** — passage entre la Baie d'Hudson et la Mer du Labrador. Forts courants, échanges d'eau atlantique. Polygone IHO + coupe pour séparer la Baie d'Ungava au sud-est.
- **Baie d'Ungava** — bras de mer entre Cap Hopes Advance et Cape Chidley, ouvert sur le Détroit d'Hudson. Eaux saisonnières, communautés zooplanctoniques distinctes. Stations typiques NeoLab/Amundsen.
- **Nunavik** — composite administratif des quatre zones ci-dessus (eaux bordant le territoire administratif du Nunavik).

### Arctique canadien

- **Baie de Baffin** — forte concentration de copépodes arctiques (*Calanus hyperboreus*, *C. glacialis*). Croisières Amundsen récurrentes. Stations typiques FoxSIPP, BB, Baffin.
- **Détroit de Davis** — passage entre Baie de Baffin et Atlantique Nord. Zone de mélange de masses d'eau arctiques et atlantiques.
- **Mer du Labrador** — convection profonde hivernale, masse d'eau distinctive (LSW). Bordée à l'est par Hawke Channel sur le plateau continental.
- **Hawke Channel** — canyon du plateau continental labradorien, échantillonnage NeoLab récurrent (stations HC-*). Le polygone est une approximation bbox carrée (TODO : remplacer par une enveloppe convexe + buffer de 25 km dérivée des stations HC-*).

### Saint-Laurent

- **Golfe du Saint-Laurent** — zone côtière et estuarienne, données NeoLab labo + OGSL. Stations IML, Rimouski, etc.

### Arctique élargi (circumpolaire)

- **Mer de Beaufort** — zone de glace saisonnière, données CTD et zooplancton Amundsen. Stations CB, Beaufort, ArcticNet.
- **Mer des Tchouktches**, **Mer du Groenland**, **Mer de Lincoln** — secteurs arctiques périphériques, polygones IHO standards.
- **Arctique** — composite circumpolaire incluant le bassin polaire IHO + Mers de Beaufort, Tchouktches, Lincoln, Groenland. À utiliser quand l'utilisateur dit « Arctique » de manière générique sans préciser le secteur.

## Aliases acceptés

Le tool `get_zone_info` accepte des aliases insensibles à la casse, en français comme en anglais — ex. `"Baie d'Ungava"`, `"ungava bay"`, `"Ungava"`, `"baie ungava"` résolvent tous vers `Baie d'Ungava`. Si l'utilisateur prononce un nom non reconnu, le tool retourne un dict `{"error": ..., "available_zones": [...]}`.

## Colonnes de coordonnées attendues

Quand un polygone ou un bbox est appliqué à un DataFrame :

- Tables labo NeoLab : colonnes `latitude`, `longitude` (décimales, longitude négative pour ouest)
- Tables EcoTaxa : colonnes `obj_latitude`, `obj_longitude` (objets) ou `lat`, `lon` (samples), selon le niveau d'export
- Tables Amundsen CTD : colonnes `latitude`, `longitude`
- Tables Bio-ORACLE : colonnes `latitude`, `longitude` (un point par requête)

Vérifier le nom exact via `load_file` avant de filtrer — ne pas supposer.
