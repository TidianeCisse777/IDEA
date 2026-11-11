# Comparer FILET et UVP : paires et abondances

Méthode des fonctions `explore.filet_uvp_pairs` et `explore.filet_uvp_compare`
(`docs/warehouse_filet_uvp_compare.sql`), et tests du 11 novembre 2026 sur l'export FILET du 26 mai 2026.
Les valeurs sont posées côte à côte : aucune conversion entre filet et UVP, aucune interprétation.

## Paires FILET–UVP

`explore.filet_uvp_pairs(max_km, max_hours, require_same_station, station_if_no_position)`.

- Distance entre la position du trait de filet et celle du profil UVP (haversine, km); écart entre le début
  du déploiement FILET et l'heure du profil UVP (h, UTC).
- `max_km` NULL : pas de critère spatial. `require_same_station` : stations identiques après normalisation
  (lettres et chiffres, majuscules, « G » initial retiré : G107 = 107).
- Position UVP : celle d'EcoPart, sinon la moyenne des samples EcoTaxa du profil (`uvp_position_source`);
  les 182 profils GreenEdge 2016 sans position EcoPart l'ont ainsi.
- `station_if_no_position` : un profil UVP sans aucune position est accepté si la station est la même.
- Rang 1 = le plus proche (distance/max_km + écart/max_hours). `candidates_for_sample` dit s'il y en avait d'autres.

## Abondances sur la même couche

`explore.filet_uvp_compare(max_km, max_hours, require_same_station, station_if_no_position, uvp_taxon,
filet_taxon_pattern, filet_stages, min_size_um, max_size_um, size_measure, validated_only, best_only)`.

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

| Réglage | Paires | Couverture médiane | UVP/FILET médian |
|---|---|---|---|
| 5 km, 6 h | 33 | 0,99 | 0,197 |
| 30 km, 24 h | 33 | 0,99 | 0,197 |
| 50 km, 72 h | 34 | 0,99 | 0,191 |
| 100 km, 168 h | 34 | 0,99 | 0,191 |
| 50 km, 72 h, tous statuts UVP | 34 | 0,99 | 0,191 |
| 50 km, 72 h, stades C4, C5, M, F | 34 | 0,99 | 0,276 |

Limite : avec 50 km et 72 h, la variante *Calanus* / `Calanus%` dépasse les 30 s accordées à un compte de
lecture (11 novembre 2026); préférer 30 km et 24 h.

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
