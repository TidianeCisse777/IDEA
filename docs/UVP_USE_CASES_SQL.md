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

## Cas de découverte et de contrôle des lacunes

Ces requêtes servent à comprendre ce qui est disponible avant de formuler une
analyse scientifique. Elles produisent des tableaux de contrôle directement
chargeables dans le notebook.

## 9. Inventorier les données disponibles

Question : « Quelles campagnes, projets, profils, samples et objets sont
présents dans le warehouse ? »

```sql
SELECT dataset_version_id,
       COUNT(DISTINCT uvp_profile_id) AS n_profiles,
       COUNT(DISTINCT ecotaxa_sample_id) AS n_samples,
       COUNT(DISTINCT ecotaxa_object_id) AS n_objects,
       MIN(sampled_at) AS first_sample,
       MAX(sampled_at) AS last_sample
FROM explore.uvp_objects
GROUP BY dataset_version_id
ORDER BY first_sample;
```

Friction détectée : version d’export présente mais vide, profil sans sample
EcoTaxa, ou sample sans objet exporté.

## 10. Vérifier la complétude des métadonnées des samples

Question : « Quels samples sont incomplets et quelles métadonnées manquent ? »

```sql
SELECT sample_name, station_key, sampled_at,
       (sample_name IS NULL) AS missing_sample_name,
       (station_key IS NULL) AS missing_station,
       (sampled_at IS NULL) AS missing_time,
       (latitude IS NULL OR longitude IS NULL) AS missing_position,
       (marine_zone_key IS NULL) AS missing_zone,
       (ctd_rosette_filename IS NULL) AS missing_ctd_filename,
       (object_count IS NULL) AS missing_object_count
FROM explore.uvp_samples
WHERE sample_name IS NULL
   OR station_key IS NULL
   OR sampled_at IS NULL
   OR latitude IS NULL OR longitude IS NULL
   OR marine_zone_key IS NULL
   OR ctd_rosette_filename IS NULL
   OR object_count IS NULL;
```

Friction détectée : les colonnes manquantes doivent rester distinguées d’une
valeur zéro ou d’un sample réellement sans objet.

## 11. Mesurer la couverture CTD

Question : « Quelle proportion des samples possède un profil CTD accepté ? »

```sql
SELECT
    COUNT(*) AS n_samples,
    COUNT(*) FILTER (WHERE ctd_profile_id IS NOT NULL) AS n_with_ctd_candidate,
    COUNT(*) FILTER (WHERE match_status = 'accepted') AS n_with_ctd_accepted,
    COUNT(*) FILTER (WHERE match_status = 'ambiguous') AS n_ctd_ambiguous,
    COUNT(*) FILTER (WHERE match_status = 'rejected') AS n_ctd_rejected,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE match_status = 'accepted')
        / NULLIF(COUNT(*), 0), 2
    ) AS pct_ctd_accepted
FROM explore.ecotaxa_ctd_profile;
```

Friction détectée : un nom de fichier CTD présent ne signifie pas que la
correspondance Amundsen a été confirmée.

## 12. Auditer la jointure EcoTaxa/EcoPart

Question : « Combien d’objets sont correctement rattachés à un bin avec un
volume valide ? »

```sql
SELECT mapping_status,
       COUNT(*) AS n_objects,
       COUNT(*) FILTER (WHERE sampled_volume_l > 0) AS n_with_volume,
       MAX(ABS(depth_delta_m)) AS max_depth_delta_m
FROM explore.uvp_objects
GROUP BY mapping_status
ORDER BY mapping_status;
```

Friction détectée : objets non rattachés, volumes absents ou écarts de
profondeur anormaux. La règle de bin reste celle de `object_depth_min`.

## 13. Décrire les taxons réellement observés

Question : « Quels taxons sont présents, dans quels projets et à quelle
profondeur ? »

```sql
SELECT ecopart_project_id, marine_zone_key, taxon_id, taxon_name,
       COUNT(*) AS n_objects,
       MIN(object_depth_min_m) AS min_depth_m,
       MAX(object_depth_max_m) AS max_depth_m
FROM explore.uvp_objects
WHERE mapping_status = 'accepted'
GROUP BY ecopart_project_id, marine_zone_key, taxon_id, taxon_name
ORDER BY ecopart_project_id, n_objects DESC;
```

Friction détectée : plusieurs libellés pour un même taxon, catégories
non-validées ou taxonomie trop agrégée pour une comparaison FILET.

## 14. Voir la couverture spatiale et verticale

Question : « Où et à quelles profondeurs les samples sont-ils disponibles ? »

```sql
SELECT marine_zone_key, station_key,
       COUNT(DISTINCT sample_name) AS n_samples,
       MIN(latitude) AS latitude_min, MAX(latitude) AS latitude_max,
       MIN(longitude) AS longitude_min, MAX(longitude) AS longitude_max,
       MIN(depth_min) AS depth_min_m, MAX(depth_max) AS depth_max_m
FROM explore.uvp_samples
GROUP BY marine_zone_key, station_key
ORDER BY marine_zone_key, station_key;
```

Friction détectée : stations sans zone, coordonnées incohérentes ou
profondeurs manquantes. Cette vue alimente une carte ou un profil global sans
reconstruire les jointures dans le notebook.

## 15. Construire une table globale pour un graphique exploratoire

Question : « Donne-moi une ligne par sample, bin et taxon avec les variables
de contexte nécessaires à un graphique. »

```sql
SELECT a.sample_name, a.cruise_key, a.station_key,
       s.marine_zone_key, s.sampled_at,
       a.taxon_key, a.depth_min_m, a.depth_max_m,
       a.n_objects_taxon, a.sampled_volume_l,
       a.abundance_uvp_ind_m3
FROM explore.uvp_taxon_abundance a
JOIN explore.uvp_samples s ON s.uvp_profile_id = a.profile_id
WHERE (:project_id IS NULL OR s.ecopart_project_id = :project_id)
  AND (:zone_key IS NULL OR s.marine_zone_key = :zone_key)
  AND (:taxon IS NULL OR a.taxon_key = :taxon)
ORDER BY a.sampled_at, a.station_key, a.depth_min_m;
```

Cette sortie est le format cible pour un DataFrame et des graphiques de
distribution verticale, de comparaison entre stations ou de suivi temporel.

## Analyses concrètes par zone

## 16. Résumer une zone maritime

Question : « Dans la zone `:zone_key`, combien avons-nous de projets, profils,
samples et objets ? »

```sql
SELECT marine_zone_key,
       COUNT(DISTINCT ecotaxa_project_id) AS n_projects,
       COUNT(DISTINCT uvp_profile_id) AS n_profiles,
       COUNT(DISTINCT ecotaxa_sample_id) AS n_samples,
       SUM(COALESCE(object_count, 0)) AS n_objects
FROM explore.uvp_samples
WHERE marine_zone_key = :zone_key
GROUP BY marine_zone_key;
```

Grain : une ligne par zone. Cette sortie donne immédiatement la taille réelle
du jeu disponible avant une analyse.

## 17. Résumer les profils par zone et par station

Question : « Comment les profils sont-ils répartis dans la zone ? »

```sql
SELECT marine_zone_key, station_key,
       COUNT(DISTINCT uvp_profile_id) AS n_profiles,
       COUNT(DISTINCT ecotaxa_sample_id) AS n_samples,
       COUNT(DISTINCT cast_key) AS n_casts,
       MIN(sampled_at) AS first_profile,
       MAX(sampled_at) AS last_profile,
       MIN(depth_min) AS shallowest_m,
       MAX(depth_max) AS deepest_m
FROM explore.uvp_samples
WHERE marine_zone_key = :zone_key
GROUP BY marine_zone_key, station_key
ORDER BY station_key;
```

Grain : zone × station. Les doublons de profil sont évités par les comptes
`DISTINCT`.

## 18. Abondance moyenne par zone et profondeur

Question : « Quelle est l’abondance moyenne du taxon `:taxon` dans la zone,
par profondeur ? »

```sql
WITH profile_bin AS (
    SELECT s.marine_zone_key,
           a.profile_id,
           a.depth_min_m,
           a.depth_max_m,
           SUM(a.n_objects_taxon) AS n_objects,
           SUM(a.sampled_volume_l) AS volume_l
    FROM explore.uvp_taxon_abundance a
    JOIN explore.uvp_samples s ON s.uvp_profile_id = a.profile_id
    WHERE s.marine_zone_key = :zone_key
      AND a.taxon_key = :taxon
    GROUP BY s.marine_zone_key, a.profile_id,
             a.depth_min_m, a.depth_max_m
), profile_concentration AS (
    SELECT *, n_objects / NULLIF(volume_l, 0) * 1000 AS abundance_ind_m3
    FROM profile_bin
)
SELECT marine_zone_key, depth_min_m, depth_max_m,
       COUNT(*) AS n_profiles,
       AVG(abundance_ind_m3) AS mean_abundance_ind_m3,
       STDDEV_SAMP(abundance_ind_m3) AS sd_abundance_ind_m3
FROM profile_concentration
GROUP BY marine_zone_key, depth_min_m, depth_max_m
ORDER BY depth_min_m;
```

L’agrégation est faite en deux étapes : volume et objets sont d’abord regroupés
par profil, puis la moyenne est calculée entre profils. On évite ainsi de
surpondérer les profils qui possèdent davantage de bins.

## 19. Relier abondance et contexte CTD par sample

Question : « Pour chaque sample de la zone, quelle est l’abondance et la
température/salinité CTD associée ? »

```sql
WITH ctd_context AS (
    SELECT ecotaxa_sample_id,
           AVG(value) FILTER (WHERE variable_key = 'temperature') AS temperature_mean,
           AVG(value) FILTER (WHERE variable_key = 'salinity') AS salinity_mean
    FROM explore.ecotaxa_ctd
    WHERE match_status = 'accepted'
    GROUP BY ecotaxa_sample_id
), abundance AS (
    SELECT s.ecotaxa_sample_id, s.sample_name, s.marine_zone_key,
           a.taxon_key,
           SUM(a.n_objects_taxon) AS n_objects,
           SUM(a.sampled_volume_l) AS volume_l
    FROM explore.uvp_taxon_abundance a
    JOIN explore.uvp_samples s ON s.uvp_profile_id = a.profile_id
    WHERE s.marine_zone_key = :zone_key
      AND (:taxon IS NULL OR a.taxon_key = :taxon)
    GROUP BY s.ecotaxa_sample_id, s.sample_name, s.marine_zone_key, a.taxon_key
)
SELECT a.*, a.n_objects / NULLIF(a.volume_l, 0) * 1000 AS abundance_ind_m3,
       c.temperature_mean, c.salinity_mean
FROM abundance a
LEFT JOIN ctd_context c ON c.ecotaxa_sample_id = a.ecotaxa_sample_id;
```

Grain : sample × taxon. Le CTD est résumé au niveau du sample ; les mesures
verticales détaillées restent accessibles dans `explore.ecotaxa_ctd`.

## 20. Explorer les objets d’une zone avec leur contexte EcoPart

Question : « Quels objets EcoTaxa sont observés dans cette zone, avec leur bin,
volume, taxon et statut de rattachement ? »

```sql
SELECT marine_zone_key, sample_name, station_key, sampled_at,
       ecotaxa_object_id, object_id, taxon_id, taxon_name,
       object_depth_min_m, object_depth_max_m,
       source_bin_key, depth_min_m, depth_max_m,
       sampled_volume_l, mapping_status
FROM explore.uvp_objects
WHERE marine_zone_key = :zone_key
  AND (:taxon IS NULL OR taxon_id = :taxon)
ORDER BY sampled_at, station_key, object_depth_min_m;
```

Grain : objet EcoTaxa. Cette sortie est adaptée à l’exploration d’images,
à la vérification des annotations et au contrôle de la jointure EcoPart.

## 21. Couverture CTD par zone et par station

Question : « Dans quelles stations de la zone avons-nous réellement un CTD
complet ? »

```sql
SELECT s.marine_zone_key, s.station_key,
       COUNT(DISTINCT s.uvp_profile_id) AS n_profiles,
       COUNT(DISTINCT p.ecotaxa_sample_id) AS n_samples_with_ctd,
       COUNT(DISTINCT p.ctd_profile_id) AS n_ctd_profiles,
       COUNT(DISTINCT m.variable_key) AS n_ctd_variables
FROM explore.uvp_samples s
LEFT JOIN explore.ecotaxa_ctd_profile p
       ON p.ecotaxa_sample_id = s.ecotaxa_sample_id
      AND p.match_status = 'accepted'
LEFT JOIN explore.ecotaxa_ctd m
       ON m.ecotaxa_sample_id = p.ecotaxa_sample_id
WHERE s.marine_zone_key = :zone_key
GROUP BY s.marine_zone_key, s.station_key
ORDER BY s.station_key;
```

Cette requête distingue présence d’un lien CTD et richesse réelle des mesures
CTD disponibles.
