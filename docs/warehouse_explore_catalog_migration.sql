-- Additive migration: views over every EcoTaxa project and every CTD profile,
-- not only those reached through a UVP profile or an EcoTaxa link.
--
-- Found live (3 novembre 2026): asked for annotation statistics on "EcoTaxa
-- objects", an agent could only reach the 13 projects linked to a UVP profile
-- (explore.uvp_samples/uvp_objects), because no explore view exposed the 10
-- others (Zooscan, LOKI, ...) — 4.4 M of the 15 M objects, including all the
-- never-classified ones. CTD profiles were likewise visible only through
-- explore.ecotaxa_ctd*, which drops any profile without an accepted EcoTaxa link.
--
-- Row security is unchanged: these views read the same warehouse tables as the
-- other explore views, whose forced policies keep each account to its contract,
-- zone and years. ctd_variable is a reference table (exempt, like marine_zone).

CREATE OR REPLACE VIEW explore.ecotaxa_projects AS
SELECT
    p.project_id AS ecotaxa_project_id,
    p.title AS ecotaxa_project_title,
    p.instrument,
    p.status AS ecotaxa_status,
    p.dataset_version_id,
    count(s.id) AS n_samples,
    sum(s.object_count) AS n_objects,
    sum(s.nb_validated) AS n_validated,
    sum(s.nb_predicted) AS n_predicted,
    sum(s.nb_dubious) AS n_dubious,
    sum(s.nb_unclassified) AS n_unclassified,
    min(s.datetime_min) AS start_at,
    max(s.datetime_max) AS end_at,
    array_agg(DISTINCT s.marine_zone_key ORDER BY s.marine_zone_key)
        FILTER (WHERE s.marine_zone_key IS NOT NULL) AS marine_zone_keys,
    EXISTS (SELECT 1 FROM warehouse.uvp_ecotaxa l JOIN warehouse.ecotaxa_sample s2 ON s2.id = l.ecotaxa_sample_id
            WHERE s2.project_id = p.project_id) AS has_uvp_profiles
FROM warehouse.ecotaxa_project p
LEFT JOIN warehouse.ecotaxa_sample s ON s.project_id = p.project_id
GROUP BY p.project_id, p.title, p.instrument, p.status, p.dataset_version_id;

COMMENT ON VIEW explore.ecotaxa_projects IS
    'Un projet EcoTaxa chargé par ligne, quel que soit l''instrument (UVP, Zooscan, LOKI...) : nombre de samples, d''objets et répartition par statut d''annotation (somme des compteurs des samples), période, zones. Point d''entrée pour toute question sur « les projets » ou « les objets EcoTaxa » en général; explore.uvp_projects ne couvre que les projets liés à un profil UVP. has_uvp_profiles dit si le projet a des profils UVP (sinon pas de volume échantillonné, donc pas d''abondance UVP).';

CREATE OR REPLACE VIEW explore.ecotaxa_samples AS
SELECT
    s.id AS ecotaxa_sample_id,
    s.project_id AS ecotaxa_project_id,
    p.title AS ecotaxa_project_title,
    COALESCE(s.instrument, p.instrument) AS instrument,
    s.dataset_version_id,
    s.sample_id AS ecotaxa_native_sample_id,
    s.sample_orig_id,
    s.station_id AS ecotaxa_station_id,
    s.cruise_id AS ecotaxa_cruise_id,
    s.profile_id AS ecotaxa_profile_id,
    s.datetime_min,
    s.datetime_max,
    s.lat_avg AS latitude,
    s.lon_avg AS longitude,
    s.depth_min,
    s.depth_max,
    s.marine_zone_key,
    s.marine_zone_name,
    s.marine_zone_assignment_status,
    s.object_count,
    s.nb_validated,
    s.nb_predicted,
    s.nb_dubious,
    s.nb_unclassified,
    EXISTS (SELECT 1 FROM warehouse.uvp_ecotaxa l WHERE l.ecotaxa_sample_id = s.id) AS has_uvp_profile
FROM warehouse.ecotaxa_sample s
LEFT JOIN warehouse.ecotaxa_project p ON p.project_id = s.project_id;

COMMENT ON VIEW explore.ecotaxa_samples IS
    'Un sample EcoTaxa par ligne, tous projets et instruments confondus, avec ses compteurs d''objets par statut d''annotation (recalculés depuis les objets chargés). Pour compter ou comparer des statuts d''annotation, partir d''ici (rapide) plutôt que de explore.ecotaxa_objects (15 M lignes). explore.uvp_samples ne montre que les samples liés à un profil UVP et peut répéter un sample lié à plusieurs profils; ici une ligne = un sample. Coordonnées et dates sont celles du sample EcoTaxa (NULL si la source ne les donne pas).';

CREATE OR REPLACE VIEW explore.ecotaxa_objects AS
SELECT
    o.id AS ecotaxa_object_id,
    o.object_id,
    o.sample_id AS ecotaxa_sample_id,
    s.project_id AS ecotaxa_project_id,
    COALESCE(s.instrument, p.instrument) AS instrument,
    o.category_id AS taxon_id,
    o.category_name AS taxon_name,
    o.annotation_status,
    o.object_datetime,
    o.depth_min_m AS object_depth_min_m,
    o.depth_max_m AS object_depth_max_m,
    o.object_lat,
    o.object_lon,
    s.marine_zone_key,
    o.acquisition_id,
    o.area_px, o.esd_px, o.major_px, o.minor_px,
    a.pixel_size_mm,
    (o.esd_px * a.pixel_size_mm * 1000) AS esd_um,
    (o.major_px * a.pixel_size_mm * 1000) AS major_um,
    (o.minor_px * a.pixel_size_mm * 1000) AS minor_um,
    (o.area_px * (a.pixel_size_mm * 1000) ^ 2) AS area_um2
FROM warehouse.ecotaxa_object o
JOIN warehouse.ecotaxa_sample s ON s.id = o.sample_id
LEFT JOIN warehouse.ecotaxa_project p ON p.project_id = s.project_id
LEFT JOIN warehouse.ecotaxa_acquisition a ON a.acquisition_id = o.acquisition_id;

COMMENT ON VIEW explore.ecotaxa_objects IS
    'Un objet EcoTaxa par ligne, tous projets et instruments confondus (15 M lignes) : taxon, statut d''annotation, profondeur, taille en pixels et en unités réelles quand l''acquisition porte sa calibration (NULL sinon, notamment LOKI). Filtrer d''abord par ecotaxa_project_id ou ecotaxa_sample_id, et agréger dans la requête : un balayage complet dépasse le délai de 30 s. Pour de simples comptes par statut, explore.ecotaxa_samples suffit. Aucun volume échantillonné ici : pas d''abondance (ind/m³) sans passer par les vues UVP.';

CREATE OR REPLACE VIEW explore.ctd_profiles AS
SELECT
    c.id AS ctd_profile_id,
    c.dataset_version_id,
    c.source_profile_key,
    c.cruise_key,
    c.station_key,
    c.sampled_at,
    c.latitude,
    c.longitude,
    c.marine_zone_key,
    c.marine_zone_name,
    c.marine_zone_assignment_status,
    (SELECT max(m.depth_m) FROM warehouse.ctd_measurement m WHERE m.profile_id = c.id) AS max_depth_m,
    EXISTS (SELECT 1 FROM warehouse.ecotaxa_ctd l WHERE l.ctd_profile_id = c.id AND l.match_status = 'accepted') AS has_ecotaxa_link
FROM warehouse.ctd_profile c;

COMMENT ON VIEW explore.ctd_profiles IS
    'Un profil CTD par ligne (Amundsen), lié ou non à un sample EcoTaxa : position, date, station, zone, profondeur maximale mesurée. explore.ecotaxa_ctd_profile ne montre que les profils liés à EcoTaxa (une ligne par liaison).';

CREATE OR REPLACE VIEW explore.ctd_measurements AS
SELECT
    m.profile_id AS ctd_profile_id,
    m.depth_m,
    m.pressure_dbar,
    m.variable_key,
    v.canonical_name AS variable_name,
    m.value,
    m.unit,
    m.qc,
    m.sensor_channel
FROM warehouse.ctd_measurement m
LEFT JOIN warehouse.ctd_variable v ON v.variable_key = m.variable_key;

COMMENT ON VIEW explore.ctd_measurements IS
    'Une mesure CTD par ligne (profil × scan × variable), format long : filtrer variable_key (TE90 température °C ITS-90, PSAL salinité pratique, SIGT sigma-t = densité moins 1000 kg/m³ (une valeur 27 signifie 1027 kg/m³), OXYM oxygène µM, NTRA nitrate, FLOR fluorescence, pH, PRES pression) et ctd_profile_id avant d''agréger. depth_m est la pression en dbar utilisée comme profondeur (1 dbar ≈ 0,99 m : écart d''environ 1 % à 2000 m), pas une profondeur recalculée. Unité dans unit, telle que fournie; qc toujours NULL dans les données chargées : aucun contrôle qualité n''est fourni, ce qui ne veut pas dire que les valeurs sont bonnes. Joindre explore.ctd_profiles sur ctd_profile_id pour la position, la date et la zone.';

-- Readable dataset titles. Catalog entries were seeded with placeholders such as
-- "ecotaxa dataset 42 (current)", which tell a reader nothing. This function
-- gives the source's own name; warehouse_fair_migration.sql uses it when it seeds
-- a new entry, and the UPDATE below fixes entries seeded before. Only a title
-- still equal to its placeholder changes: a title someone wrote stays as written.
CREATE OR REPLACE FUNCTION warehouse.dataset_native_title(version_id bigint)
RETURNS text LANGUAGE sql STABLE AS $$
    SELECT CASE v.source_instance
        WHEN 'ecotaxa' THEN (SELECT format('EcoTaxa %s — %s', p.project_id, p.title)
                             FROM warehouse.ecotaxa_project p WHERE p.dataset_version_id = v.id LIMIT 1)
        WHEN 'ecopart' THEN (SELECT format('EcoPart %s — profils UVP liés à EcoTaxa %s', v.dataset_key,
                                           string_agg(DISTINCT s.project_id::text, ', ' ORDER BY s.project_id::text))
                             FROM warehouse.uvp_profile u
                             JOIN warehouse.uvp_ecotaxa l ON l.uvp_profile_id = u.id
                             JOIN warehouse.ecotaxa_sample s ON s.id = l.ecotaxa_sample_id
                             WHERE u.dataset_version_id = v.id
                             HAVING count(*) > 0)
        WHEN 'amundsen_ctd' THEN format('CTD Amundsen (ERDDAP) %s', v.dataset_key)
    END
    FROM warehouse.dataset_version v WHERE v.id = version_id
$$;

UPDATE warehouse.dataset_metadata m
SET title = warehouse.dataset_native_title(v.id)
FROM warehouse.dataset_version v
WHERE m.dataset_version_id = v.id
  AND m.title = format('%s dataset %s (%s)', v.source_instance, v.dataset_key, v.version_key)
  AND warehouse.dataset_native_title(v.id) IS NOT NULL;

-- SIGT is sigma-t (density minus 1000 kg/m3, values 16-28 here), not density:
-- named "densité" until 4 novembre 2026, which let a reader take 27 kg/m3 for the
-- water's density. Same name as the CTD loader now writes; one-time, guarded.
UPDATE warehouse.ctd_variable SET canonical_name = 'sigma-t (densité moins 1000)', description = 'sigma-t (densité moins 1000)'
WHERE variable_key = 'SIGT' AND canonical_name = 'densité';
UPDATE warehouse.ctd_measurement SET variable_definition = 'sigma-t (densité moins 1000)'
WHERE variable_key = 'SIGT' AND variable_definition = 'densité';
