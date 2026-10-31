-- Additive migration: expose warehouse.ecotaxa_project.title (the project's
-- human name, e.g. "Campagne Amundsen 2023") through explore.uvp_samples and
-- explore.uvp_projects. Found missing live: an agent asked to color a map by
-- EcoTaxa project name could only reach the numeric ecotaxa_project_id,
-- because no explore view ever joined warehouse.ecotaxa_project (see ROADMAP,
-- 31 octobre 2026). warehouse.ecotaxa_project is a reference/catalog table
-- like dataset_version (one row per project, not occurrence data), so the
-- join adds no new row-security surface: ecotaxa_project_id already decides
-- visibility through warehouse.ecotaxa_sample/uvp_profile.
CREATE OR REPLACE VIEW explore.uvp_samples AS
SELECT
    u.id AS uvp_profile_id,
    u.dataset_version_id,
    u.ecopart_project_id,
    u.ecopart_sample_id,
    u.sample_name,
    u.cruise_key,
    u.station_key,
    u.cast_key,
    u.sampled_at,
    u.latitude,
    u.longitude,
    e.id AS ecotaxa_sample_id,
    e.project_id AS ecotaxa_project_id,
    e.sample_id AS ecotaxa_native_sample_id,
    e.sample_orig_id,
    e.profile_id AS ecotaxa_profile_id,
    e.ctd_rosette_filename,
    e.datetime_min,
    e.datetime_max,
    e.depth_min,
    e.depth_max,
    e.instrument,
    COALESCE(e.marine_zone_key, u.marine_zone_key) AS marine_zone_key,
    COALESCE(e.marine_zone_name, u.marine_zone_name) AS marine_zone_name,
    COALESCE(e.marine_zone_source, u.marine_zone_source) AS marine_zone_source,
    COALESCE(e.marine_zone_version, u.marine_zone_version) AS marine_zone_version,
    COALESCE(e.marine_zone_assignment_status, u.marine_zone_assignment_status) AS marine_zone_assignment_status,
    e.object_count,
    e.nb_validated,
    e.nb_predicted,
    e.nb_dubious,
    e.nb_unclassified,
    ep.title AS ecotaxa_project_title
FROM warehouse.uvp_profile u
JOIN warehouse.uvp_ecotaxa l ON l.uvp_profile_id = u.id
JOIN warehouse.ecotaxa_sample e ON e.id = l.ecotaxa_sample_id
LEFT JOIN warehouse.ecotaxa_project ep ON ep.project_id = e.project_id;

CREATE OR REPLACE VIEW explore.uvp_projects AS
SELECT
    u.ecotaxa_project_id,
    u.ecopart_project_id,
    u.cruise_key,
    MIN(u.sampled_at) AS start_at,
    MAX(u.sampled_at) AS end_at,
    COUNT(DISTINCT u.id) AS n_profiles,
    COUNT(DISTINCT e.id) AS n_ecotaxa_samples,
    COUNT(DISTINCT u.cast_key) AS n_casts,
    COALESCE(MIN(e.marine_zone_key), MIN(u.marine_zone_key)) AS marine_zone_key,
    COALESCE(MIN(e.marine_zone_name), MIN(u.marine_zone_name)) AS marine_zone_name,
    MIN(u.latitude) AS latitude_min,
    MAX(u.latitude) AS latitude_max,
    MIN(u.longitude) AS longitude_min,
    MAX(u.longitude) AS longitude_max,
    MIN(ep.title) AS ecotaxa_project_title
FROM warehouse.uvp_profile u
LEFT JOIN warehouse.uvp_ecotaxa l ON l.uvp_profile_id = u.id
LEFT JOIN warehouse.ecotaxa_sample e ON e.id = l.ecotaxa_sample_id
LEFT JOIN warehouse.ecotaxa_project ep ON ep.project_id = u.ecotaxa_project_id
GROUP BY u.ecotaxa_project_id, u.ecopart_project_id, u.cruise_key;

COMMENT ON VIEW explore.uvp_samples IS
    'Un sample/profil UVP par ligne, metadonnees EcoTaxa et EcoPart. ecotaxa_project_title est le nom natif du projet EcoTaxa (NULL si le projet n''a pas ete charge dans warehouse.ecotaxa_project); ecotaxa_project_id reste l''identifiant stable a utiliser pour grouper ou joindre, le titre peut changer ou manquer.';
COMMENT ON VIEW explore.uvp_projects IS
    'Navigation EcoTaxa/EcoPart : une ligne par projet (ecotaxa_project_id, ecopart_project_id, campagne). ecotaxa_project_title est le nom natif du projet EcoTaxa, pour l''affichage; ne pas l''utiliser comme cle, deux projets pourraient en theorie partager un titre.';
