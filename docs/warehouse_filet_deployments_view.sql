-- explore.filet_deployments : une ligne par déploiement FILET (mise à l'eau d'un engin à une station), pour
-- voir d'un coup l'engin, le type de trait, les couches de profondeur et les mailles :
--   n_layers couches distinctes (min_sample_depth–max_sample_depth), n_meshes mailles distinctes, liste des
--   couches de haut en bas, échantillons analysés, et sampling_layout :
--   « couches superposées » (profil vertical, ex. Hydrobios, Bioness), « une couche, plusieurs mailles »
--   (ex. 2x1m2, 4x1m2), « une couche, une maille », « plusieurs couches et mailles ».
-- Lit explore.filet_samples (droits du compte). Additive et relançable.

CREATE OR REPLACE VIEW explore.filet_deployments AS
SELECT s.dataset_version_id, s.deployment_id, min(s.sampling_year) AS sampling_year,
       min(s.sampling_platform) AS sampling_platform, min(s.station_name) AS station_name,
       min(s.deployment_datetime_start) AS deployment_datetime_start,
       max(s.deployment_datetime_end) AS deployment_datetime_end,
       avg(s.latitude) AS latitude, avg(s.longitude) AS longitude, min(s.marine_zone_name) AS marine_zone_name,
       min(s.gear) AS gear, min(s.tow_type) AS tow_type, min(s.cast_number) AS cast_number,
       count(*) AS n_samples,
       count(DISTINCT (s.min_sample_depth, s.max_sample_depth)) AS n_layers,
       count(DISTINCT s.net_mesh_size) AS n_meshes,
       string_agg(DISTINCT s.net_mesh_size::text, ', ') AS meshes_um,
       min(s.min_sample_depth) AS depth_top_m, max(s.max_sample_depth) AS depth_bottom_m,
       (SELECT string_agg(l.min_d || '–' || l.max_d, '; ' ORDER BY l.min_d, l.max_d)
        FROM (SELECT DISTINCT x.min_sample_depth AS min_d, x.max_sample_depth AS max_d
              FROM explore.filet_samples x
              WHERE x.deployment_id = s.deployment_id AND x.dataset_version_id = s.dataset_version_id) l) AS layers,
       count(*) FILTER (WHERE s.n_analyses > 0) AS n_analysed_samples,
       CASE WHEN count(DISTINCT (s.min_sample_depth, s.max_sample_depth)) > 1 AND count(DISTINCT s.net_mesh_size) <= 1
                THEN 'couches superposées'
            WHEN count(DISTINCT (s.min_sample_depth, s.max_sample_depth)) <= 1 AND count(DISTINCT s.net_mesh_size) > 1
                THEN 'une couche, plusieurs mailles'
            WHEN count(DISTINCT (s.min_sample_depth, s.max_sample_depth)) <= 1 THEN 'une couche, une maille'
            ELSE 'plusieurs couches et mailles' END AS sampling_layout
FROM explore.filet_samples s
GROUP BY s.dataset_version_id, s.deployment_id;
COMMENT ON VIEW explore.filet_deployments IS
    'Un déploiement FILET par ligne : engin, trait, couches de profondeur (nombre et liste), mailles, échantillons analysés, disposition (profil vertical ou couche unique multi-mailles).';
