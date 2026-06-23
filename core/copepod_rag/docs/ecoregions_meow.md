# Écorégions marines (MEOW) intégrées au registry NeoLab

Mots-clés : écorégions marines, MEOW, Spalding 2007, Hudson Complex, Northern Labrador, Lancaster Sound, West Greenland Shelf, Gulf of St. Lawrence, Scotian Shelf, Beaufort Sea, Arctique, bioregionalisation, écozone

## Source

Les polygones d'écorégions sont issus de :

- **Spalding M.D., Fox H.E., Allen G.R., Davidson N., Ferdaña Z.A., Finlayson M., Halpern B.S., Jorge M.A., Lombana A., Lourie S.A., Martin K.D., McManus E., Molnar J., Recchia C.A., Robertson J. (2007).** *Marine Ecoregions of the World: A Bioregionalization of Coastal and Shelf Areas.* BioScience 57(7):573-583. https://doi.org/10.1641/B570707

Téléchargement opérationnel des polygones : ArcGIS Online MEOW FeatureServer (item id `74b6ac5c8fc24dcb8abaad6428a5dfa4`, owner `kvangraafeiland_oceans`), filtré bbox >40°N pour rester dans le périmètre NeoLab.

Champs Spalding conservés dans les properties du registry : `ECOREGION`, `PROVINCE`, `REALM`, `Lat_Zone`.

## Comment filtrer par écorégion

Le tool `get_zone_info(zone_name=...)` accepte :
- le nom court ECOREGION exact (ex. `"Hudson Complex"`, `"Northern Labrador"`)
- le préfixe explicite `"MEOW: <ECOREGION>"` (ex. `"MEOW: Hudson Complex"`)

Les chaînes downstream sont identiques aux zones IHO :
- `filter_dataframe_by_zone(zone_name="MEOW: Hudson Complex")` sur un fichier chargé
- `find_ecotaxa_samples_in_region(zone_name="Hudson Complex")` sur le cache EcoTaxa
- `query_bio_oracle_zones(zone_names=["Hudson Complex"])` pour récupérer un proxy environnemental moyen par écorégion

## Coexistence avec les zones IHO

MEOW et IHO sont **deux couches parallèles**, pas un remplacement :
- IHO décrit des entités physiques (mers, baies, détroits) avec les bordures hydrographiques officielles
- MEOW décrit des régions écologiques (faune/flore associée) avec des bordures dérivées de la biogéographie

Exemple : `"Baie d'Hudson"` (IHO) et `"MEOW: Hudson Complex"` (qui englobe Hudson + James + Strait + Ungava) ne sont pas équivalents — la première est plus restrictive, la seconde reflète l'unité écologique régionale.

## Écorégions intégrées au registry NeoLab (50, >40°N)

### Realm — Arctic
Province : Arctic
- Baffin Bay - Davis Strait
- Beaufort Sea - continental coast and shelf
- Beaufort-Amundsen-Viscount Melville-Queen Maud
- Chukchi Sea
- East Greenland Shelf
- East Siberian Sea
- Eastern Bering Sea
- High Arctic Archipelago
- Hudson Complex
- Kara Sea
- Lancaster Sound
- Laptev Sea
- North Greenland
- North and East Barents Sea
- North and East Iceland
- Northern Grand Banks - Southern Labrador
- Northern Labrador
- West Greenland Shelf
- White Sea

### Realm — Temperate Northern Atlantic
Province : Cold Temperate Northwest Atlantic
- Gulf of Maine/Bay of Fundy
- Gulf of St. Lawrence - Eastern Scotian Shelf
- Scotian Shelf
- Southern Grand Banks - South Newfoundland
- Virginian

Province : Northern European Seas
- Baltic Sea
- Celtic Seas
- Faroe Plateau
- North Sea
- Northern Norway and Finnmark
- South and West Iceland
- Southern Norway

Province : Lusitanian
- Azores Canaries Madeira
- South European Atlantic Shelf

Province : Mediterranean Sea
- Adriatic Sea
- Aegean Sea
- Ionian Sea
- Western Mediterranean

Province : Black Sea
- Black Sea

### Realm — Temperate Northern Pacific
Province : Cold Temperate Northeast Pacific
- Aleutian Islands
- Gulf of Alaska
- North American Pacific Fijordland
- Northern California
- Oregon, Washington, Vancouver Coast and Shelf
- Puget Trough/Georgia Basin

Province : Cold Temperate Northwest Pacific
- Kamchatka Shelf and Coast
- Northeastern Honshu
- Oyashio Current
- Sea of Japan/East Sea
- Sea of Okhotsk
- Yellow Sea

## Limites du modèle MEOW

- **Côtier / plateau seulement** : MEOW couvre les eaux côtières et de plate-forme (jusqu'à ~200 m typiquement). Pour les bassins océaniques pélagiques (par ex. coeur de la Mer du Labrador, Bassin de Baffin profond), le complément est **PPOW** (Pelagic Provinces of the World, Spalding et al. 2012) — non intégré ici.
- **Bordures statiques** : MEOW est un découpage **fixe** issu de l'expertise de 50+ auteurs. Il ne reflète pas la variabilité saisonnière des fronts ou des masses d'eau.
- **Échelle régionale** : conçu pour la planification et la classification large échelle. Pour des questions station-niveau (intra-écorégion), croiser avec un CTD (`enrich_with_amundsen_ctd`, `enrich_with_ogsl`) ou un proxy environnemental (`query_bio_oracle_zones`).

## Simplification appliquée

Les polygones bruts du FeatureServer ont été simplifiés à **tolérance 0.05°** (~5 km à 60°N) avant intégration au registry, pour rester sous le poids GeoJSON cible. Précision largement suffisante pour la classification de stations en mer (échelle des points >> 5 km).
