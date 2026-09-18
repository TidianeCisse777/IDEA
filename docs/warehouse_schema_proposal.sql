-- PROPOSITION REVISEE, NON EXECUTEE. PostgreSQL.
-- But : SQL genere par IDEA -> DataFrame dans son notebook.
-- Aucun schema work ; cles natives conservees, JOIN explicites autorises.
-- Noms de colonnes canoniques proposes, pas un contrat d'export NeoLab verifie.
-- Version coherente des sources a selectionner ; droits a definir au deploiement.
CREATE SCHEMA warehouse;
CREATE SCHEMA explore;

CREATE TABLE warehouse.dataset_version (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_instance text NOT NULL,
    dataset_key text NOT NULL,
    version_key text NOT NULL,
    file_manifest_uri text NOT NULL,
    sha256 text NOT NULL,
    UNIQUE (source_instance, dataset_key, version_key)
);

CREATE TABLE warehouse.ecotaxa_sample (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_version_id bigint NOT NULL REFERENCES warehouse.dataset_version,
    project_id bigint NOT NULL,
    -- EcoTaxa exports use textual sample identifiers (for example
    -- ``hc_02_030924``); keep them losslessly even when a source uses digits.
    sample_id text NOT NULL,
    sample_orig_id text NOT NULL,    -- identifiant original importe
    station_id text,
    cruise_id text,
    profile_id text,
    ctd_rosette_filename text,
    lat_avg double precision,
    lon_avg double precision,
    datetime_min timestamptz,
    datetime_max timestamptz,
    depth_min double precision,
    depth_max double precision,
    instrument text,
    marine_zone_key text,
    marine_zone_name text,
    marine_zone_source text,
    marine_zone_version text,
    marine_zone_assignment_status text CHECK (marine_zone_assignment_status IN ('assigned', 'ambiguous', 'outside', 'unresolved')),
    object_count bigint,
    nb_validated bigint,
    nb_predicted bigint,
    nb_dubious bigint,
    nb_unclassified bigint,
    free_fields_json jsonb,
    UNIQUE (dataset_version_id, project_id, sample_id)
);
CREATE TABLE warehouse.ecotaxa_object (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sample_id bigint NOT NULL REFERENCES warehouse.ecotaxa_sample,
    object_id text NOT NULL,         -- identifiant natif dans cet export
    acquisition_id text,
    process_id text,
    category_id text,
    category_name text,
    annotation_status text,
    depth_min_m double precision,
    depth_max_m double precision,
    object_lat double precision,
    object_lon double precision,
    image_uri text,
    UNIQUE (sample_id, object_id)
);

CREATE TABLE warehouse.uvp_profile (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_version_id bigint NOT NULL REFERENCES warehouse.dataset_version,
    ecotaxa_project_id bigint,
    ecopart_project_id bigint NOT NULL,
    -- EcoPart ``Profile`` is a textual source identifier.
    ecopart_sample_id text NOT NULL,
    sample_name text NOT NULL,
    cruise_key text,
    station_key text,
    cast_key text,
    marine_zone_key text,
    marine_zone_name text,
    marine_zone_source text,
    marine_zone_version text,
    marine_zone_assignment_status text CHECK (marine_zone_assignment_status IN ('assigned', 'ambiguous', 'outside', 'unresolved')),
    sampled_at timestamptz,
    latitude double precision,
    longitude double precision,
    UNIQUE (dataset_version_id, ecopart_project_id, ecopart_sample_id)
);
CREATE TABLE warehouse.uvp_bin (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    profile_id bigint NOT NULL REFERENCES warehouse.uvp_profile,
    source_bin_key text NOT NULL,
    depth_min_m double precision,
    depth_max_m double precision,
    pressure_dbar double precision,
    sampled_volume_l numeric CHECK (sampled_volume_l > 0),
    UNIQUE (profile_id, source_bin_key)
);
CREATE TABLE warehouse.uvp_particle (
    bin_id bigint NOT NULL REFERENCES warehouse.uvp_bin,
    size_class_key text NOT NULL,
    size_min_um double precision NOT NULL,
    size_max_um double precision NOT NULL,
    size_definition text NOT NULL,
    particle_count bigint,
    observed_volume_m3 double precision,
    supplied_concentration double precision,
    concentration_unit text,
    PRIMARY KEY (bin_id, size_class_key),
    CHECK (size_max_um > size_min_um)
);

CREATE TABLE warehouse.uvp_object_bin (
    ecotaxa_object_id bigint NOT NULL REFERENCES warehouse.ecotaxa_object,
    uvp_bin_id bigint NOT NULL REFERENCES warehouse.uvp_bin,
    depth_delta_m numeric,
    mapping_method text NOT NULL,
    mapping_status text NOT NULL CHECK (mapping_status IN ('accepted', 'ambiguous', 'unmatched')),
    PRIMARY KEY (ecotaxa_object_id, uvp_bin_id)
);

-- Abondance taxonomique UVP : variable DERIVEE, absente des exports sources.
-- EcoTaxa fournit les objets/annotations ; EcoPart fournit le volume du bin.
CREATE TABLE warehouse.uvp_taxon_abundance (
    dataset_version_id bigint NOT NULL REFERENCES warehouse.dataset_version,
    profile_id bigint NOT NULL REFERENCES warehouse.uvp_profile,
    bin_id bigint NOT NULL REFERENCES warehouse.uvp_bin,
    taxon_key text NOT NULL,
    annotation_policy text NOT NULL,
    n_objects_taxon bigint NOT NULL CHECK (n_objects_taxon >= 0),
    sampled_volume_l numeric NOT NULL CHECK (sampled_volume_l > 0),
    abundance_uvp_ind_m3 numeric GENERATED ALWAYS AS
        (n_objects_taxon::numeric / sampled_volume_l * 1000) STORED,
    calculation_version text NOT NULL,
    PRIMARY KEY (dataset_version_id, bin_id, taxon_key, annotation_policy)
);

-- Les abondances FILET sont des valeurs source déjà normalisées dans l'export.
-- Le warehouse conserve depth-vol et flowmeter-vol séparément : aucun choix
-- implicite de dénominateur et aucune seconde normalisation.

-- CTD deja associee dans EcoPart OU profil source Amundsen : provenance
-- conservee ; ne pas supposer que leurs identifiants internes sont identiques.
CREATE TABLE warehouse.ctd_profile (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_version_id bigint NOT NULL REFERENCES warehouse.dataset_version,
    source_profile_key text NOT NULL,
    cruise_key text,
    station_key text,
    sampled_at timestamptz,
    latitude double precision,
    longitude double precision,
    UNIQUE (dataset_version_id, source_profile_key)
);
CREATE TABLE warehouse.ctd_measurement (
    profile_id bigint NOT NULL REFERENCES warehouse.ctd_profile,
    source_row_key text NOT NULL,
    scan_key text NOT NULL,
    depth_m double precision,
    pressure_dbar double precision,
    variable_key text NOT NULL,
    variable_definition text NOT NULL,
    sensor_channel text NOT NULL,
    value double precision,
    unit text NOT NULL,
    qc text,
    PRIMARY KEY (profile_id, source_row_key)
);

-- FILET : structure revue sur les exports Desktop du 26 mai 2026.
-- Les metadonnees ont 6102 echantillons, certains sans analyse.
CREATE TABLE warehouse.filet_sample (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_version_id bigint NOT NULL REFERENCES warehouse.dataset_version,
    sample_id text NOT NULL,
    deployment_id text NOT NULL,
    sampling_year integer,
    sampling_platform text,
    station_name text,
    deployment_datetime_start timestamp, -- fuseau absent de l'export : a confirmer
    deployment_datetime_end timestamp,
    cast_number text,                   -- numero du trait ; PAS un ID CTD prouve
    latitude double precision,
    longitude double precision,
    gear text,
    tow_type text,
    min_sample_depth numeric,
    max_sample_depth numeric,
    net_mesh_size numeric,              -- micrometres
    depth_calc_net_filtered_vol numeric, -- m3, conserver les deux estimations
    flowmeter_calc_vol numeric,          -- m3
    number_of_nets integer,
    sample_nets text,                   -- libelle source : peut valoir 8+9
    net_sampling_ids text,              -- liste source preservee
    subsampling_quantity numeric,
    subsampling_unit text,              -- ne pas assimiler a fraction analysee
    UNIQUE (dataset_version_id, sample_id),
    UNIQUE (id, dataset_version_id, sample_id)
);
-- Membership extrait de net_sampling_ids. Pas d'invention de profondeur ou
-- volume propre a chaque filet lorsque seul le groupe est decrit.
CREATE TABLE warehouse.filet_sample_net (
    sample_ref bigint REFERENCES warehouse.filet_sample,
    net_sampling_id text,
    PRIMARY KEY (sample_ref, net_sampling_id)
);
CREATE TABLE warehouse.filet_analysis (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_version_id bigint NOT NULL,
    sample_ref bigint NOT NULL,
    sample_id text NOT NULL,
    analysis_id text NOT NULL,
    analysis_type text,
    analysis_contract text,
    analysis_datetime timestamp,
    analysis_protocol_id text,
    FOREIGN KEY (sample_ref, dataset_version_id, sample_id)
        REFERENCES warehouse.filet_sample(id, dataset_version_id, sample_id),
    UNIQUE (dataset_version_id, sample_id, analysis_id)
);
-- Grain cible : ligne source (sample, analyse, taxon) x stade.
-- Colonnes depliees sans recalcul des valeurs scientifiques.
CREATE TABLE warehouse.filet_abundance (
    dataset_version_id bigint NOT NULL REFERENCES warehouse.dataset_version,
    source_row_number integer NOT NULL,
    sample_id text NOT NULL,
    analysis_id text NOT NULL,
    taxon_id text NOT NULL,             -- texte source, pas un AphiaID suppose
    stage text NOT NULL CHECK (stage IN (
        'C1','C2','C3','C4','C5','M','F','COP_NS','COPEPODID',
        'N1','N2','N3','N4','N5','N6','NAUP_NS','NAUPLIUS','ALL_STAGES')),
    is_aggregate boolean GENERATED ALWAYS AS
        (stage IN ('COPEPODID','NAUPLIUS','ALL_STAGES')) STORED,
    sample_abundance numeric,          -- individus attribues, deja calcules
    abundance_depth_ind_m3 numeric,
    abundance_flowmeter_ind_m3 numeric,
    biomass_depth_ug_c_m3 numeric,
    biomass_flowmeter_ug_c_m3 numeric,
    -- Nullable : 106 lignes source n'ont pas de metadonnees dans ces exports.
    metadata_dataset_version_id bigint,
    FOREIGN KEY (metadata_dataset_version_id, sample_id, analysis_id)
        REFERENCES warehouse.filet_analysis(dataset_version_id, sample_id, analysis_id),
    PRIMARY KEY (dataset_version_id, sample_id, analysis_id, taxon_id, stage),
    UNIQUE (dataset_version_id, source_row_number, stage)
);
-- Colonnes de contexte deja presentes dans l'export abondance a conserver
-- aussi dans la couche source : ne pas perdre leur station/date/volumes lorsque
-- le lien aux metadonnees est absent. Une vue enrichie de fallback est a definir
-- explicitement si souhaitee, sans attribuer de latitude ou deployment_id absent.

-- Liens connus charges a l'ingestion ; preuve inclut source/version/cle.
-- Ils exposent des relations existantes, pas un moteur de candidats.
CREATE TABLE warehouse.uvp_ecotaxa (
    uvp_profile_id bigint REFERENCES warehouse.uvp_profile,
    ecotaxa_sample_id bigint REFERENCES warehouse.ecotaxa_sample,
    source_evidence text NOT NULL,
    PRIMARY KEY (uvp_profile_id, ecotaxa_sample_id)
);
CREATE TABLE warehouse.uvp_ctd (
    uvp_profile_id bigint REFERENCES warehouse.uvp_profile,
    ctd_profile_id bigint REFERENCES warehouse.ctd_profile,
    source_evidence text NOT NULL,
    PRIMARY KEY (uvp_profile_id, ctd_profile_id)
);
CREATE TABLE warehouse.ecotaxa_ctd (
    ecotaxa_sample_id bigint NOT NULL REFERENCES warehouse.ecotaxa_sample,
    ctd_profile_id bigint NOT NULL REFERENCES warehouse.ctd_profile,
    relation_type text NOT NULL CHECK (relation_type IN (
        'filename_exact', 'filename_station_time_position', 'station_time_position'
    )),
    filename_match boolean NOT NULL,
    station_match boolean,
    distance_km numeric,
    time_gap_minutes numeric,
    match_status text NOT NULL CHECK (match_status IN ('accepted', 'ambiguous', 'rejected')),
    evidence text NOT NULL,
    PRIMARY KEY (ecotaxa_sample_id, ctd_profile_id)
);
CREATE TABLE warehouse.filet_ecotaxa (
    filet_analysis_id bigint REFERENCES warehouse.filet_analysis,
    ecotaxa_sample_id bigint REFERENCES warehouse.ecotaxa_sample,
    source_evidence text NOT NULL,
    PRIMARY KEY (filet_analysis_id, ecotaxa_sample_id)
);
CREATE TABLE warehouse.filet_ctd (
    filet_sample_id bigint REFERENCES warehouse.filet_sample,
    ctd_profile_id bigint REFERENCES warehouse.ctd_profile,
    source_evidence text NOT NULL,
    PRIMARY KEY (filet_sample_id, ctd_profile_id)
);

CREATE TABLE warehouse.filet_uvp_match (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_version_id bigint NOT NULL REFERENCES warehouse.dataset_version,
    station_id text NOT NULL,
    filet_sample_id bigint NOT NULL REFERENCES warehouse.filet_sample,
    filet_analysis_id bigint REFERENCES warehouse.filet_analysis,
    uvp_profile_id bigint NOT NULL REFERENCES warehouse.uvp_profile,
    filet_sampled_at timestamp,
    uvp_sampled_at timestamptz,
    time_gap_hours numeric NOT NULL CHECK (time_gap_hours >= 0),
    match_status text NOT NULL CHECK (match_status IN ('accepted', 'ambiguous', 'rejected')),
    match_method text NOT NULL,
    evidence text NOT NULL,
    UNIQUE (dataset_version_id, filet_sample_id, filet_analysis_id, uvp_profile_id)
);

CREATE TABLE warehouse.taxon_mapping (
    filet_taxon_id text NOT NULL,
    uvp_taxon_id text NOT NULL,
    mapping_relation text NOT NULL,
    mapping_version text NOT NULL,
    mapping_status text NOT NULL CHECK (mapping_status IN ('accepted', 'ambiguous', 'rejected')),
    evidence text NOT NULL,
    PRIMARY KEY (filet_taxon_id, uvp_taxon_id, mapping_version)
);

-- Vue directement convertible en DataFrame.
-- Grain : un lien UVP/CTD x une mesure CTD native.
CREATE VIEW explore.uvp_ctd AS
SELECT u.id AS uvp_profile_id, u.dataset_version_id AS uvp_dataset_version_id,
       u.ecopart_project_id, u.ecopart_sample_id, u.sample_name,
       u.cruise_key, u.station_key,
       c.id AS ctd_profile_id, c.dataset_version_id AS ctd_dataset_version_id,
       c.source_profile_key AS ctd_source_profile_key,
       m.source_row_key, m.scan_key, m.depth_m, m.pressure_dbar,
       m.variable_key, m.variable_definition, m.sensor_channel,
       m.value, m.unit, m.qc
FROM warehouse.uvp_profile u
JOIN warehouse.uvp_ctd l ON l.uvp_profile_id = u.id
JOIN warehouse.ctd_profile c ON c.id = l.ctd_profile_id
JOIN warehouse.ctd_measurement m ON m.profile_id = c.id;

-- Navigation EcoTaxa/EcoPart : une ligne par projet.
CREATE VIEW explore.uvp_projects AS
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
    MAX(u.longitude) AS longitude_max
FROM warehouse.uvp_profile u
LEFT JOIN warehouse.uvp_ecotaxa l ON l.uvp_profile_id = u.id
LEFT JOIN warehouse.ecotaxa_sample e ON e.id = l.ecotaxa_sample_id
GROUP BY u.ecotaxa_project_id, u.ecopart_project_id, u.cruise_key;

-- Une ligne par sample/profil avec les metadonnees EcoTaxa et EcoPart.
CREATE VIEW explore.uvp_samples AS
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
    e.nb_unclassified
FROM warehouse.uvp_profile u
JOIN warehouse.uvp_ecotaxa l ON l.uvp_profile_id = u.id
JOIN warehouse.ecotaxa_sample e ON e.id = l.ecotaxa_sample_id;

-- Une ligne par objet EcoTaxa et bin EcoPart associe.
CREATE VIEW explore.uvp_objects AS
SELECT
    u.id AS uvp_profile_id,
    u.sample_name,
    u.cruise_key,
    u.station_key,
    u.sampled_at,
    COALESCE(e.marine_zone_key, u.marine_zone_key) AS marine_zone_key,
    COALESCE(e.marine_zone_name, u.marine_zone_name) AS marine_zone_name,
    COALESCE(e.marine_zone_version, u.marine_zone_version) AS marine_zone_version,
    COALESCE(e.marine_zone_assignment_status, u.marine_zone_assignment_status) AS marine_zone_assignment_status,
    e.id AS ecotaxa_sample_id,
    e.project_id AS ecotaxa_project_id,
    e.sample_orig_id,
    o.id AS ecotaxa_object_id,
    o.object_id,
    o.acquisition_id,
    o.process_id,
    o.category_id AS taxon_id,
    o.category_name AS taxon_name,
    o.annotation_status,
    o.depth_min_m AS object_depth_min_m,
    o.depth_max_m AS object_depth_max_m,
    b.id AS uvp_bin_id,
    b.source_bin_key,
    b.depth_min_m,
    b.depth_max_m,
    b.sampled_volume_l,
    ob.depth_delta_m,
    ob.mapping_method,
    ob.mapping_status,
    o.image_uri
FROM warehouse.uvp_profile u
JOIN warehouse.uvp_ecotaxa ul ON ul.uvp_profile_id = u.id
JOIN warehouse.ecotaxa_sample e ON e.id = ul.ecotaxa_sample_id
JOIN warehouse.ecotaxa_object o ON o.sample_id = e.id
LEFT JOIN warehouse.uvp_object_bin ob ON ob.ecotaxa_object_id = o.id
LEFT JOIN warehouse.uvp_bin b ON b.id = ob.uvp_bin_id
;

CREATE VIEW explore.uvp_taxon_abundance AS
SELECT
    a.dataset_version_id,
    a.profile_id,
    a.bin_id,
    a.taxon_key,
    a.annotation_policy,
    a.n_objects_taxon,
    a.sampled_volume_l,
    a.abundance_uvp_ind_m3,
    b.depth_min_m,
    b.depth_max_m,
    u.sample_name,
    u.cruise_key,
    u.station_key,
    u.sampled_at
FROM warehouse.uvp_taxon_abundance a
JOIN warehouse.uvp_bin b ON b.id = a.bin_id
JOIN warehouse.uvp_profile u ON u.id = a.profile_id;

-- Grain : sample x analyse x taxon x stade. LEFT JOIN conserve les non-apparies.
CREATE VIEW explore.filet_data AS
SELECT f.*, s.deployment_id, s.sampling_year, s.sampling_platform,
       s.station_name, s.deployment_datetime_start,
       s.latitude, s.longitude, s.min_sample_depth, s.max_sample_depth,
       s.net_mesh_size, s.depth_calc_net_filtered_vol, s.flowmeter_calc_vol,
       s.net_sampling_ids, s.subsampling_quantity, s.subsampling_unit,
       a.analysis_contract, a.analysis_protocol_id,
       (a.id IS NOT NULL) AS metadata_matched
FROM warehouse.filet_abundance f
LEFT JOIN warehouse.filet_analysis a
    ON a.dataset_version_id = f.metadata_dataset_version_id
   AND a.sample_id = f.sample_id AND a.analysis_id = f.analysis_id
LEFT JOIN warehouse.filet_sample s ON s.id = a.sample_ref;

-- Vue pratique sans additionner les sous-stades et leurs totaux.
CREATE VIEW explore.filet_totals AS
SELECT * FROM explore.filet_data WHERE stage = 'ALL_STAGES';

CREATE VIEW explore.filet_samples AS
SELECT s.*,
       COUNT(DISTINCT a.id) AS n_analyses
FROM warehouse.filet_sample s
LEFT JOIN warehouse.filet_analysis a ON a.sample_ref = s.id
GROUP BY s.id, s.dataset_version_id, s.sample_id, s.deployment_id,
         s.sampling_year, s.sampling_platform, s.station_name,
         s.deployment_datetime_start, s.deployment_datetime_end, s.cast_number,
         s.latitude, s.longitude, s.gear, s.tow_type, s.min_sample_depth,
         s.max_sample_depth, s.net_mesh_size, s.depth_calc_net_filtered_vol,
         s.flowmeter_calc_vol, s.number_of_nets, s.sample_nets,
         s.net_sampling_ids, s.subsampling_quantity, s.subsampling_unit;

CREATE VIEW explore.filet_ctd AS
SELECT
    s.sample_id AS filet_sample_id,
    s.station_name,
    l.ctd_profile_id,
    c.source_profile_key,
    m.depth_m,
    m.pressure_dbar,
    m.variable_key,
    m.value,
    m.unit,
    m.qc
FROM warehouse.filet_sample s
JOIN warehouse.filet_ctd l ON l.filet_sample_id = s.id
JOIN warehouse.ctd_profile c ON c.id = l.ctd_profile_id
JOIN warehouse.ctd_measurement m ON m.profile_id = c.id;

CREATE VIEW explore.ecotaxa_ctd_profile AS
SELECT
    e.id AS ecotaxa_sample_id,
    e.sample_id AS ecotaxa_native_sample_id,
    e.sample_orig_id,
    e.profile_id AS ecotaxa_profile_id,
    e.station_id AS ecotaxa_station_id,
    e.cruise_id AS ecotaxa_cruise_id,
    e.ctd_rosette_filename,
    e.marine_zone_key,
    e.marine_zone_name,
    l.ctd_profile_id,
    c.source_profile_key,
    c.station_key AS ctd_station_id,
    c.sampled_at AS ctd_sampled_at,
    l.relation_type,
    l.match_status,
    l.distance_km,
    l.time_gap_minutes,
    l.evidence
FROM warehouse.ecotaxa_sample e
JOIN warehouse.ecotaxa_ctd l ON l.ecotaxa_sample_id = e.id
JOIN warehouse.ctd_profile c ON c.id = l.ctd_profile_id;

CREATE VIEW explore.ecotaxa_ctd AS
SELECT p.*, m.depth_m, m.pressure_dbar, m.variable_key,
       m.variable_definition, m.sensor_channel, m.value, m.unit, m.qc
FROM explore.ecotaxa_ctd_profile p
JOIN warehouse.ctd_measurement m ON m.profile_id = p.ctd_profile_id
WHERE p.match_status = 'accepted';

CREATE VIEW explore.filet_uvp_matches AS
SELECT * FROM warehouse.filet_uvp_match;

CREATE VIEW explore.filet_uvp_abundance AS
SELECT
    m.id AS match_id,
    m.dataset_version_id,
    m.station_id,
    m.filet_sample_id,
    m.filet_analysis_id,
    m.uvp_profile_id,
    m.time_gap_hours,
    m.match_status,
    f.taxon_id AS taxon_filet,
    f.stage AS filet_stage,
    f.abundance_depth_ind_m3 AS abundance_filet_depth_ind_m3,
    f.abundance_flowmeter_ind_m3 AS abundance_filet_flowmeter_ind_m3,
    u.taxon_key AS uvp_taxon,
    ub.depth_min_m,
    ub.depth_max_m,
    u.abundance_uvp_ind_m3,
    u.n_objects_taxon,
    u.sampled_volume_l
FROM warehouse.filet_uvp_match m
JOIN warehouse.filet_analysis fa ON fa.id = m.filet_analysis_id
JOIN warehouse.filet_abundance f
  ON f.sample_id = fa.sample_id
 AND f.analysis_id = fa.analysis_id
JOIN warehouse.taxon_mapping tm
  ON tm.filet_taxon_id = f.taxon_id
 AND tm.mapping_status = 'accepted'
JOIN warehouse.uvp_taxon_abundance u
  ON u.profile_id = m.uvp_profile_id
 AND u.taxon_key = tm.uvp_taxon_id
JOIN warehouse.uvp_bin ub ON ub.id = u.bin_id;

-- Exemples (parametres fournis par le client SQL) :
-- SELECT * FROM explore.uvp_ctd
-- WHERE uvp_dataset_version_id = :version AND sample_name = :sample;
-- SELECT * FROM explore.filet_data
-- WHERE dataset_version_id = :version AND sample_id = :sample;
--
-- Ne pas joindre tous les objets a tous les scans par le seul profil.
-- Un enrichissement au grain objet/tranche exige une regle verticale validee.
-- Les ID rattachement profil ne sont pas une cle d'alignement de chaque mesure.
-- A ajouter apres inspection des exports : dictionnaire taxonomique, produits
-- EcoPart zooplancton, index selon requetes, droits et versions coherentes.
