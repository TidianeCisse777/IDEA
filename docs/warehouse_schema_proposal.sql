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
    sample_id bigint NOT NULL,       -- ID interne EcoTaxa
    sample_orig_id text NOT NULL,    -- identifiant original importe
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
    image_uri text,
    UNIQUE (sample_id, object_id)
);

CREATE TABLE warehouse.uvp_profile (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_version_id bigint NOT NULL REFERENCES warehouse.dataset_version,
    ecopart_project_id bigint NOT NULL,
    ecopart_sample_id bigint NOT NULL,
    sample_name text NOT NULL,
    cruise_key text,
    station_key text,
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

-- Grain : un lien UVP/EcoTaxa x un objet.
CREATE VIEW explore.uvp_objects AS
SELECT u.id AS uvp_profile_id, u.dataset_version_id AS uvp_dataset_version_id,
       u.sample_name, u.cruise_key, u.station_key,
       s.dataset_version_id AS ecotaxa_dataset_version_id,
       s.project_id AS ecotaxa_project_id, s.sample_orig_id,
       o.*
FROM warehouse.uvp_profile u
JOIN warehouse.uvp_ecotaxa l ON l.uvp_profile_id = u.id
JOIN warehouse.ecotaxa_sample s ON s.id = l.ecotaxa_sample_id
JOIN warehouse.ecotaxa_object o ON o.sample_id = s.id;

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
