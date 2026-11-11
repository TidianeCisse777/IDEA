# Comparer FILET et UVP : paires et abondances

Méthode des fonctions `explore.filet_uvp_pairs` et `explore.filet_uvp_compare`
(`sql/warehouse_filet_uvp_compare.sql`), et tests du 11 novembre 2026 sur l'export FILET du 26 mai 2026.
Les valeurs sont posées côte à côte : aucune conversion entre filet et UVP, aucune interprétation.

## Paires FILET–UVP

`explore.filet_uvp_pairs(max_km, max_hours, require_same_station, station_if_no_position, filet_stations)`.

- Distance entre la position du trait de filet et celle du profil UVP (haversine, km); écart entre le début
  du déploiement FILET et l'heure du profil UVP (h, UTC).
- `max_km` NULL : pas de critère spatial. `require_same_station` : stations identiques après normalisation
  (lettres et chiffres, majuscules, « G » initial retiré : G107 = 107).
- Position UVP : celle d'EcoPart, sinon la moyenne des samples EcoTaxa du profil (`uvp_position_source`);
  les 182 profils GreenEdge 2016 sans position EcoPart l'ont ainsi.
- `station_if_no_position` : un profil UVP sans aucune position est accepté si la station est la même.
- `filet_stations` (tableau, ex. `ARRAY['133','134']`) : seulement ces stations filet. Pour une question sur
  quelques stations, toujours le donner : réponse en quelques secondes, quels que soient les autres réglages.
- Rang 1 = le plus proche (distance/max_km + écart/max_hours). `candidates_for_sample` dit s'il y en avait d'autres.

## Compter les couples : par déploiement, pas par ligne

Les deux fonctions renvoient une ligne par **échantillon** filet (un filet, une couche, une maille) :
un déploiement Hydrobios à 9 couches donne 9 lignes, un 4x1m2 à 3 mailles en donne 3. Un **couple
filet–UVP** se compte par déploiement : `count(DISTINCT filet_deployment_id)`. Même station et 5 h au plus
(`filet_uvp_pairs(NULL, 5, true, true)`, rang 1), le 11 novembre 2026 : 232 déploiements filet, 167 profils
UVP, 133 stations (955 échantillons). Chaque déploiement a un profil UVP; un profil peut servir à plusieurs
déploiements de la même station (ex. un 2x1m2 et un Hydrobios).

```sql
SELECT count(DISTINCT filet_deployment_id) AS couples, count(DISTINCT uvp_profile_id) AS profils_uvp
FROM explore.filet_uvp_pairs(NULL, 5, true, true) WHERE rank_for_sample = 1;
```

## Meilleurs couples pour comparer les copépodes (11 novembre 2026)

Même station, 5 h au plus, filet COPEPODID, UVP Copepoda validés : `filet_uvp_compare(NULL, 5, true, true)`.
Retenus : couche entièrement vue par l'UVP (couverture ≥ 0,95), au moins 50 objets UVP, annotation UVP
validée à 100 %, abondance filet renseignée. Abondances en ind./m3.

| Station (déploiement) | Date | Engin, couche | km / h | Filet (vol. profondeur / débitmètre) | UVP (objets) |
|---|---|---|---|---|---|
| G707 (1272) | 2016-07-08 | 4x1m2 - LOKI, 0–700 m | 0,1 / 1,1 | 126,8 / 250,3 | 18,5 (317) |
| G507 (1253) | 2016-06-30 | 4x1m2 - LOKI, 0–286 m | 0,1 / 0,8 | 347,5 / 555,0 | 65,5 (245) |
| G413 (1245) | 2016-06-27 | 4x1m2 - LOKI, 0–270 m | 0,7 / 0,7 | 531,0 / 503,5 | 45,8 (177) |
| 133 (2253) | 2023-09-18 | 2x1m2, 0–170 m | 1,4 / 1,8 | 420,9 / 502,2 | 63,2 (122) |
| 134 (2250) | 2023-09-17 | 2x1m2, 0–240 m | 0,2 / 1,7 | 149,3 / 177,2 | 34,0 (92) |

Aussi propres : G204, G201, G418, G512 (GreenEdge 2016). Profil vertical : RA62 (2488, Hydrobios,
2024-09-25), couches 40–60 et 60–100 m, filet 387,3 et 279,0, UVP 52,1 (14 objets) et 39,5 (21 objets),
0,1 km, 2,1 h; peu d'objets. À éviter : TCA-BB2 (21 % des copépodes UVP validés), stations 2024 au filet de
500 µm (aucun copépode UVP validé), traits 0–700 m où l'UVP ne voit que 37 à 72 % de la couche (G318, G324,
G312, G409…).

## Copies EcoTaxa : un seul projet par profil UVP

199 profils UVP GreenEdge 2016 sont liés à deux samples EcoTaxa qui sont des copies identiques des mêmes
images (projet 149 et projet 20880 ou 20890 : mêmes comptes par profil, taxon et statut, 1 500 880 objets
chacun). `filet_uvp_compare` ne compte que le plus petit `ecotaxa_project_id` du profil
(`uvp_ecotaxa_project_id`, 149 pour GreenEdge 2016). Avant cette correction (QA du 11 novembre 2026),
l'abondance UVP de GreenEdge était doublée. Dans les vues UVP, filtrer de même sur un seul projet.

## Abondances sur la même couche

`explore.filet_uvp_compare(max_km, max_hours, require_same_station, station_if_no_position, uvp_taxon,
filet_taxon_pattern, filet_stages, min_size_um, max_size_um, size_measure, validated_only, best_only,
min_filet_ug_c_per_ind, filet_stations)`.

- FILET : somme, par analyse, des lignes dont le taxon correspond à `filet_taxon_pattern` (ILIKE, ex.
  `Calanus%`) et le stade à `filet_stages`; abondances au volume profondeur et au volume débitmètre gardées
  séparées. Seules les lignes appariées aux métadonnées (metadata_matched) sont comptées.
- Stades : les agrégats sont la somme exacte de leurs parties (vérifié : COPEPODID = C1–C5 + M + F + COP_NS
  dans 4 607 cas sur 4 607; NAUPLIUS = N1–N6 + NAUP_NS; ALL_STAGES = COPEPODID + NAUPLIUS). Demander un agrégat
  et une de ses parties est refusé (double compte).
- UVP : tranches du profil entièrement comprises dans [min_sample_depth, max_sample_depth] du trait de filet.
  Abondance = objets retenus / volume de toutes ces tranches (tranches sans objet comprises), en ind./m3.
  Objets retenus : classe « organism », `uvp_taxon` dans la lignée EcoTaxa (ex. Copepoda, Calanus), statut
  validé si `validated_only`, taille ESD ou grand axe (`size_measure` esd ou major, µm) dans
  [min_size_um, max_size_um[.
- `min_filet_ug_c_per_ind` : ne garder côté filet que les lignes taxon × stade détaillé dont le carbone par
  individu (biomasse / abondance, valeurs du labo) atteint ce seuil, pour comparer les gros stades à ce que voit
  l'UVP (copépodes UVP validés : ESD ≥ ~1 mm, médiane 2,1 mm). Refusé avec un stade agrégé.
- Taille UVP : ESD source, ou 2·√(aire/π) quand le projet ne donne pas l'ESD (Amundsen 2023); identique à
  l'ESD source partout où les deux existent (rapport 1,0000 sur 200 000 objets). Un objet sans la mesure
  demandée n'est jamais compté « trop petit » : il est compté dans `uvp_n_objects_no_size`, et l'abondance UVP
  est alors NULL (inconnue), pas 0. Bug trouvé par un agent le 11 novembre 2026 (0 faux aux stations 133–134).
- `uvp_layer_coverage` = épaisseur des tranches retenues / épaisseur du trait (1 = couche entièrement vue par
  l'UVP). Une couverture faible signale un profil UVP moins profond que le filet.
- `ratio_uvp_filet_depth` = abondance UVP / abondance FILET au volume profondeur, simple quotient.

## Tests du 11 novembre 2026

Paires (rang 1), échantillons FILET appariés, distance et écart médians, part de même station :

| max_km, max_hours | Échantillons | km médian | h médian | Même station |
|---|---|---|---|---|
| 5, 6 | 1 046 | 0,6 | 1,9 | 94 % |
| 10, 12 | 1 126 | 0,6 | 1,9 | 95 % |
| 30, 24 | 1 160 | 0,6 | 2,0 | 93 % |
| 50, 48 | 1 179 | 0,6 | 2,0 | 92 % |
| station seule, 24 h | 1 114 | 0,7 | 2,0 | 100 % |
| station seule, 5 h | 955 (133 stations) | 0,6 | 1,8 | 100 % |

- Aucune paire de même station n'est à plus de 30 km; toutes ont une position UVP (EcoPart ou EcoTaxa).
- La proximité retrouve des paires que le nom de station manque (Keb-S8 / keb_S08, A7/196 / A7,
  Nares-East-23 / NaresE23, C4-23 / CA4-23).
- 30 km, 24 h : 310 échantillons n'ont qu'un candidat, les autres 2 à 10 (plusieurs profils UVP proches).

Comparaison des copépodes (UVP Copepoda validés, FILET COPEPODID, meilleure paire) : seules les analyses
FILET avec un profil UVP proche comptent, d'où peu de paires.

Les rapports UVP/FILET médians mesurés avant le 11 novembre au soir comptaient deux fois les objets UVP de
GreenEdge 2016 (voir « Copies EcoTaxa ») : ils ont été retirés et sont à remesurer.

Durée : le compte de lecture a 30 s par requête. Sur toutes les stations, les réglages larges (50 km et
72 h, tous les stades détaillés avec un seuil de carbone) dépassent cette limite (11 novembre 2026). Pour
quelques stations, passer `filet_stations` : 2 à 7 s mesurées. Si une requête dépasse 30 s, la refaire par
stations plutôt que de changer les critères demandés.

Ces rapports décrivent les données; leur explication (taille minimale vue par l'UVP, maille du filet,
annotation, écart de temps) relève du chercheur.

## Exemple : stades FILET précis contre une taille UVP

FILET *Calanus* C5 et femelles contre UVP *Calanus* validés de grand axe ≥ 2 mm (30 km, 24 h, station si
pas de position) :

```sql
SELECT * FROM explore.filet_uvp_compare(30, 24, false, true, 'Calanus', 'Calanus%', ARRAY['C5','F'],
                                        2000, NULL, 'major', true);
```

Le 11 novembre 2026 : 33 paires, dont 7 avec au moins un *Calanus* UVP validé ≥ 2 mm dans la couche
(Amundsen 2023 et 2024). Les profils GreenEdge 2016 appariés n'en ont aucun de validé dans la couche du filet,
alors que les *Calanus* UVP validés des profils appariés ont un grand axe médian de 3,9 mm. Une abondance FILET
vide (NULL) signifie que les valeurs source sont NA pour ces taxons et stades, pas zéro.
