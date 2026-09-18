# Cas d’usage UVP — SQL lisible pour IDEA

Ce document sert de contrat de lecture avant l’intégration dans l’agent. Chaque
cas doit produire un DataFrame directement exploitable. Les valeurs entre `:`
sont des paramètres fournis par l’agent ; les jointures structurelles sont déjà
encapsulées dans les vues `explore`.

## 1. Lister les projets UVP

Question : « Quels projets existent, combien de profils, de samples et de
casts contiennent-ils, et dans quelles zones maritimes ? »

```sql
SELECT ecotaxa_project_id, ecopart_project_id, cruise_key,
       marine_zone_key, marine_zone_name,
       n_profiles, n_ecotaxa_samples, n_casts,
       start_at, end_at
FROM explore.uvp_projects
ORDER BY start_at;
```

Friction à vérifier : un projet peut traverser plusieurs zones. La V1 expose
une zone principale ; il faudra une vue projet × zone si l’on veut conserver
toutes les zones sans agrégation.

## 2. Trouver les samples d’une zone maritime

Question : « Donne-moi les samples du projet `:project_id` dans la zone
`:zone_key`, avec station, cast, date et profondeur. »

```sql
SELECT uvp_profile_id, sample_name, station_key, cast_key,
       sampled_at, latitude, longitude,
       marine_zone_key, marine_zone_name,
       depth_min, depth_max, object_count
FROM explore.uvp_samples
WHERE ecopart_project_id = :project_id
  AND marine_zone_key = :zone_key
ORDER BY sampled_at, sample_name;
```

Friction à vérifier : le calcul de zone doit être fait à l’ingestion par une
jointure point-dans-polygone, avec `marine_zone_source`, `marine_zone_version`
et un statut `assigned/ambiguous/outside/unresolved`. L’agent ne doit jamais
recalculer cette zone.

## 3. Voir les métadonnées d’un sample

Question : « Donne toutes les informations disponibles sur le sample
`:sample_name`. »

```sql
SELECT *
FROM explore.uvp_samples
WHERE sample_name = :sample_name;
```

Le résultat doit contenir les identifiants EcoTaxa et EcoPart, campagne,
station, cast, date, position, instrument, profondeurs, volume/objet si
disponibles, zone maritime et nom de fichier CTD.

## 4. Explorer les objets EcoTaxa d’un sample

Question : « Quels objets ont été détectés dans ce sample, avec leur taxon,
profondeur et bin EcoPart ? »

```sql
SELECT ecotaxa_object_id, object_id, taxon_id, taxon_name,
       annotation_status, object_depth_min_m, object_depth_max_m,
       uvp_bin_id, source_bin_key, depth_min_m, depth_max_m,
       sampled_volume_l, mapping_status
FROM explore.uvp_objects
WHERE sample_name = :sample_name
  AND (:taxon IS NULL OR taxon_id = :taxon)
ORDER BY object_depth_min_m, ecotaxa_object_id;
```

La règle de rattachement est déterministe dans la V1 : le bin est calculé à
partir de `object_depth_min` avec `floor(object_depth_min / 5) * 5 + 2.5`.
`mapping_status` reste exposé pour auditer les lignes sans objet ou sans volume.

## 5. Obtenir les objets d’une tranche de profondeur

Question : « Dans les bins 0–5 m et 5–10 m, quels objets appartiennent au
taxon sélectionné ? »

```sql
SELECT *
FROM explore.uvp_objects
WHERE sample_name = :sample_name
  AND mapping_status = 'accepted'
  AND depth_min_m >= :depth_min_m
  AND depth_max_m <= :depth_max_m
  AND (:taxon IS NULL OR taxon_id = :taxon);
```

La règle d’inclusion suit le centre du bin calculé depuis `object_depth_min`.
La V1 conserve `depth_delta_m` pour contrôler la distance entre l’objet et ce
centre.

## 6. Comparer l’abondance taxonomique entre bins

Question : « Donne l’abondance UVP du taxon `:taxon` dans ce profil, par bin. »

```sql
SELECT sample_name, profile_id, bin_id, depth_min_m, depth_max_m,
       n_objects_taxon, sampled_volume_l, abundance_uvp_ind_m3
FROM explore.uvp_taxon_abundance
WHERE profile_id = :profile_id
  AND taxon_key = :taxon
ORDER BY depth_min_m;
```

Le calcul est centralisé : `n_objects_taxon / sampled_volume_l * 1000`. Le
notebook ne recalcule pas la concentration.

## 7. Récupérer directement le CTD du sample

Question : « Pour ce profil EcoTaxa, donne les mesures CTD disponibles. »

```sql
SELECT variable_key, depth_m, pressure_dbar, value, unit, qc,
       ctd_sampled_at, ctd_station_id, relation_type, match_status
FROM explore.ecotaxa_ctd
WHERE ecotaxa_native_sample_id = :sample_id
  AND variable_key IN ('temperature', 'salinity', 'oxygen');
```

Les noms demandés sont traduits par le dictionnaire `ctd_variable` vers les
codes Amundsen `PRES`, `TE90`, `PSAL`, `SIGT`, `OXYM`, `pH`, `NTRA` ou `FLOR`.
La vue ne joint pas les objets EcoTaxa aux scans CTD, sinon le nombre de lignes
explose.

## 8. Comparer UVP et FILET après sélection taxonomique

Question : « Compare l’abondance du taxon/stade FILET avec l’abondance UVP,
pour les correspondances acceptées. »

```sql
SELECT station_id, filet_sample_id, filet_stage,
       depth_min_m, depth_max_m,
       abundance_filet_depth_ind_m3,
       abundance_filet_flowmeter_ind_m3,
       abundance_uvp_ind_m3,
       time_gap_hours
FROM explore.filet_uvp_abundance
WHERE match_status = 'accepted'
  AND filet_stage = :stage;
```

Friction à vérifier : le mapping taxonomique accepté est obligatoire ; le
simple rapprochement de deux chaînes de caractères serait scientifiquement
incorrect. Le choix de la fenêtre temporelle est porté par les lignes de
`filet_uvp_match` (`time_gap_hours`) et peut être filtré sans refaire la
jointure.

## Frictions à traiter après ces scénarios

1. ingestion des polygones marins et versionnement de l’affectation des zones ;
2. définition de `cast_key` et cardinalité projet × zone ;
3. dictionnaire des variables CTD et contrôle des unités ;
4. sélection d’un agrégat UVP lorsqu’un taxon couvre plusieurs bins ;
5. mapping taxonomique FILET/UVP et gestion des correspondances ambiguës.
