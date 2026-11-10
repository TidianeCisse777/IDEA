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
    EXISTS (SELECT 1 FROM warehouse.uvp_ecotaxa l WHERE l.ecotaxa_sample_id = s.id) AS has_uvp_profile,
    -- Same name as uvp_samples and ctd_profiles (agents asked for it 2 times in 103 cases).
    s.datetime_min AS sampled_at
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
    (o.area_px * (a.pixel_size_mm * 1000) ^ 2) AS area_um2,
    t.lineage AS taxon_lineage,
    t.taxon_type,
    t.object_class,
    NULLIF(trim(o.sun_position), '') AS sun_position,
    o.classif_who AS annotator_id,
    o.classif_when AS annotated_at,
    o.classif_auto_score AS prediction_score,
    COALESCE(o.image_uri, 'https://ecotaxa.obs-vlfr.fr/vault/' || o.image_file) AS image_uri,
    o.perim_px,
    o.feret_px,
    o.circularity,
    o.elongation,
    o.mean_grey,
    o.convex_area_px,
    (o.perim_px * a.pixel_size_mm * 1000) AS perim_um,
    (o.feret_px * a.pixel_size_mm * 1000) AS feret_um
FROM warehouse.ecotaxa_object o
JOIN warehouse.ecotaxa_sample s ON s.id = o.sample_id
LEFT JOIN warehouse.ecotaxa_project p ON p.project_id = s.project_id
LEFT JOIN warehouse.ecotaxa_acquisition a ON a.acquisition_id = o.acquisition_id
LEFT JOIN warehouse.ecotaxa_taxon t ON t.taxon_id::text = o.category_id;

COMMENT ON VIEW explore.ecotaxa_objects IS
    'Un objet EcoTaxa par ligne, tous projets et instruments confondus (15 M lignes) : taxon, statut d''annotation, profondeur, taille en pixels et en unités réelles quand l''acquisition porte sa calibration (NULL sinon, notamment LOKI). Filtrer d''abord par ecotaxa_project_id ou ecotaxa_sample_id, et agréger dans la requête : un balayage complet dépasse le délai de 30 s. Pour de simples comptes par statut, explore.ecotaxa_samples suffit; pour chercher un taxon ou compter par taxon, explore.ecotaxa_sample_taxa (un filtre sur taxon_name ici peut dépasser 30 s). taxon_lineage : lignée EcoTaxa du taxon (lui-même en premier). Aucun volume échantillonné ici : pas d''abondance (ind/m³) sans passer par les vues UVP.';

-- Taxa: found live, an agent could not find a taxon by name within 30 s (scan of
-- the 15 M objects under row security) nor tell which categories are copepods.
-- Both views read small tables (docs/warehouse_ecotaxa_taxa_migration.sql).
CREATE OR REPLACE VIEW explore.ecotaxa_sample_taxa AS
SELECT
    st.sample_id AS ecotaxa_sample_id,
    s.project_id AS ecotaxa_project_id,
    p.title AS ecotaxa_project_title,
    COALESCE(s.instrument, p.instrument) AS instrument,
    s.sample_id AS ecotaxa_native_sample_id,
    s.datetime_min AS sampled_at,
    s.lat_avg AS latitude,
    s.lon_avg AS longitude,
    s.marine_zone_key,
    st.taxon_id,
    st.taxon_name,
    t.taxon_type,
    t.lineage AS taxon_lineage,
    st.n_objects,
    st.n_validated,
    st.n_predicted,
    st.n_dubious,
    st.n_unclassified,
    t.object_class
FROM warehouse.ecotaxa_sample_taxon st
JOIN warehouse.ecotaxa_sample s ON s.id = st.sample_id
LEFT JOIN warehouse.ecotaxa_project p ON p.project_id = s.project_id
LEFT JOIN warehouse.ecotaxa_taxon t ON t.taxon_id = st.taxon_id;

COMMENT ON VIEW explore.ecotaxa_sample_taxa IS
    'Un sample EcoTaxa × une catégorie par ligne (environ 40 000 lignes) : nombre d''objets par statut d''annotation, avec la lignée du taxon. Point de départ pour chercher un taxon (taxon_name ILIKE ''%oithon%''), savoir où il est, ou compter des objets par taxon, projet, sample, zone ou date : réponse en moins d''une seconde, là où explore.ecotaxa_objects balaie 15 M lignes. Tous les copépodes : ''Copepoda'' = ANY(taxon_lineage), qui inclut les organismes entiers (taxons, stades et vues : female+lateral<Metridia longa, cvstage..., small<, ovigerous) mais aussi des catégories qui ne sont pas un copépode entier vivant (part<, cut<, antenna<, copepoda eggs, dead<) ou incertaines (like<, badfocus<, multiple<) : lister les catégories et dire lesquelles sont gardées. taxon_type M ne veut pas dire fragment (les stades sont M). object_class sépare organismes, non vivants (détritus...), catégories techniques et provisoires. taxon_id NULL = objets jamais classés. Pas de profondeur ni de taille : pour cela, explore.ecotaxa_objects filtré par projet ou sample.';

CREATE OR REPLACE VIEW explore.ecotaxa_taxa AS
SELECT
    t.taxon_id,
    t.display_name AS taxon_name,
    t.taxon_name AS taxon_short_name,
    t.taxon_type,
    t.taxon_rank,
    t.lineage AS taxon_lineage,
    t.id_lineage AS taxon_id_lineage,
    t.aphia_id,
    c.n_projects,
    c.n_samples,
    c.n_objects,
    c.n_validated,
    c.n_predicted,
    c.n_dubious,
    'ecotaxa:id:' || t.taxon_id AS taxon_key,
    t.object_class
FROM warehouse.ecotaxa_taxon t
LEFT JOIN (
    SELECT st.taxon_id, count(DISTINCT s.project_id) AS n_projects, count(*) AS n_samples,
           sum(st.n_objects) AS n_objects, sum(st.n_validated) AS n_validated,
           sum(st.n_predicted) AS n_predicted, sum(st.n_dubious) AS n_dubious
    FROM warehouse.ecotaxa_sample_taxon st
    JOIN warehouse.ecotaxa_sample s ON s.id = st.sample_id
    GROUP BY st.taxon_id
) c ON c.taxon_id = t.taxon_id;

COMMENT ON VIEW explore.ecotaxa_taxa IS
    'Une catégorie EcoTaxa présente dans le warehouse par ligne : nom tel qu''il apparaît dans les objets (taxon_name), lignée jusqu''à la racine (taxon_lineage, le taxon en premier), type P (phylogénétique) ou M (morphologique : stade, vue, taille, mais aussi part, cut, dead, eggs, like...), rang, AphiaID WoRMS, et nombre de projets, samples et objets lisibles par le compte. object_class dit ce qu''est un objet de la catégorie : organism (sous Biota), not_living (détritus, artefacts, fèces), technical (badsegmentation, oversegmented, duplicate), temporary (catégories provisoires t0xx). taxon_key = explore.uvp_taxon_abundance.taxon_key, pour classer les abondances UVP. Pour savoir quelles catégories sont des copépodes : WHERE ''Copepoda'' = ANY(taxon_lineage), puis décider (et dire) si part<, cut<, antenna<, eggs, dead<, like<, badfocus<, multiple< sont gardés; taxon_short_name donne le qualificatif (part, cut, like...). Taxonomie EcoTaxa, chargée par scripts/populate_ecotaxa_taxonomy.py.';

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
    'Une mesure CTD par ligne (profil × scan × variable), format long : filtrer variable_key (TE90 température °C ITS-90, PSAL salinité pratique, SIGT sigma-t = densité moins 1000 kg/m³ (une valeur 27 signifie 1027 kg/m³), OXYM oxygène µM, NTRA nitrate, FLOR fluorescence, PRES pression; aucune mesure pH dans les données chargées, bien que demandée à la source) et ctd_profile_id avant d''agréger. depth_m est la pression en dbar utilisée comme profondeur (1 dbar ≈ 0,99 m : écart d''environ 1 % à 2000 m), pas une profondeur recalculée. Unité dans unit, telle que fournie; qc toujours NULL dans les données chargées : aucun contrôle qualité n''est fourni, ce qui ne veut pas dire que les valeurs sont bonnes. Joindre explore.ctd_profiles sur ctd_profile_id pour la position, la date et la zone.';

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

-- UVP profiles whose linked EcoTaxa samples disagree on the zone were loaded with
-- an empty zone marked 'assigned' (3 GreenEdge 2016 profiles at 70 N: Baie de
-- Baffin in project 149, Detroit de Davis in 20890), so zone_membership dropped
-- them silently. They are AMBIGUOUS, as populate_ecopart.py now writes; one-time, guarded.
UPDATE warehouse.uvp_profile u
SET marine_zone_key = 'AMBIGUOUS', marine_zone_name = 'AMBIGUOUS', marine_zone_assignment_status = 'ambiguous'
WHERE u.marine_zone_key IS NULL AND u.marine_zone_assignment_status = 'assigned'
  AND (SELECT count(DISTINCT s.marine_zone_key) FROM warehouse.uvp_ecotaxa l
       JOIN warehouse.ecotaxa_sample s ON s.id = l.ecotaxa_sample_id WHERE l.uvp_profile_id = u.id) > 1;

-- UVP profile times: the loader took the date of the linked EcoTaxa samples, which
-- carry no hour (the objects loader never asked EcoTaxa for obj.objtime), so all 686
-- profiles were at midnight. EcoPart's own metadata gives the capture time
-- ("yyyy-mm-dd hh:mm", kept in ecopart_auxiliary_row): 686 profiles, no conflicting
-- time, same date as before for all. Read as UTC, the warehouse convention for
-- source times without a zone. One-time, guarded: only a midnight or missing time
-- whose date agrees with EcoPart's.
UPDATE warehouse.uvp_profile u
SET sampled_at = m.t
FROM (SELECT dataset_version_id, profile_name,
             (min(source_row_json ->> 'yyyy-mm-dd hh:mm'))::timestamp AT TIME ZONE 'UTC' AS t
      FROM warehouse.ecopart_auxiliary_row
      WHERE content_kind = 'metadata' AND source_row_json ->> 'yyyy-mm-dd hh:mm' ~ '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}'
      GROUP BY 1, 2
      HAVING count(DISTINCT source_row_json ->> 'yyyy-mm-dd hh:mm') = 1) m
WHERE m.dataset_version_id = u.dataset_version_id AND m.profile_name = u.ecopart_sample_id
  AND (u.sampled_at IS NULL
       OR ((u.sampled_at AT TIME ZONE 'UTC')::time = '00:00' AND (u.sampled_at AT TIME ZONE 'UTC')::date = (m.t AT TIME ZONE 'UTC')::date));
