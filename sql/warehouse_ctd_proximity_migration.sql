-- Liens CTD par proximité (espace, temps) pour les profils UVP et les déploiements FILET sans CTD.
--
-- warehouse.uvp_ctd et warehouse.filet_ctd gardent leur clé; colonnes ajoutées pour dire comment le lien a été
-- fait : link_method (filename_transitive : fichier CTD cité par EcoTaxa; proximity : CTD Amundsen la plus proche),
-- ctd_source (rosette, hydrobios = CTD montée sur le filet Hydrobios, bioness), distance_km, time_gap_hours,
-- match_status (accepted : ≤ 5 km et ≤ 6 h; candidate : ≤ 10 km et ≤ 12 h). Remplies par
-- scripts/populate_ctd_proximity.py. explore.uvp_ctd et explore.filet_ctd les exposent (colonnes en fin).
-- Additive et relançable.

ALTER TABLE warehouse.uvp_ctd
    ADD COLUMN IF NOT EXISTS link_method text NOT NULL DEFAULT 'filename_transitive',
    ADD COLUMN IF NOT EXISTS ctd_source text,
    ADD COLUMN IF NOT EXISTS distance_km numeric,
    ADD COLUMN IF NOT EXISTS time_gap_hours numeric,
    ADD COLUMN IF NOT EXISTS match_status text NOT NULL DEFAULT 'accepted';
ALTER TABLE warehouse.filet_ctd
    ADD COLUMN IF NOT EXISTS link_method text NOT NULL DEFAULT 'proximity',
    ADD COLUMN IF NOT EXISTS ctd_source text,
    ADD COLUMN IF NOT EXISTS distance_km numeric,
    ADD COLUMN IF NOT EXISTS time_gap_hours numeric,
    ADD COLUMN IF NOT EXISTS match_status text NOT NULL DEFAULT 'accepted';

INSERT INTO warehouse.ctd_variable (variable_key, canonical_name, canonical_unit, description, source_code, source_instance)
VALUES ('NET', 'numéro du filet ouvert', '1',
        'Numéro du filet ouvert à cet instant (CTD montée sur le filet Hydrobios ou Bioness, variable Net)', 'Net', 'amundsen')
ON CONFLICT (variable_key) DO NOTHING;

CREATE OR REPLACE VIEW explore.filet_ctd AS
SELECT s.sample_id AS filet_sample_id,
    s.station_name,
    l.ctd_profile_id,
    c.source_profile_key,
    m.depth_m,
    m.pressure_dbar,
    m.variable_key,
    m.value,
    m.unit,
    m.qc,
    s.deployment_id AS filet_deployment_id,
    l.link_method, l.ctd_source, l.distance_km, l.time_gap_hours, l.match_status
FROM warehouse.filet_sample s
JOIN warehouse.filet_ctd l ON l.filet_sample_id = s.id
JOIN warehouse.ctd_profile c ON c.id = l.ctd_profile_id
JOIN warehouse.ctd_measurement m ON m.profile_id = c.id;

CREATE OR REPLACE VIEW explore.uvp_ctd AS
SELECT u.id AS uvp_profile_id, u.dataset_version_id AS uvp_dataset_version_id,
       u.ecopart_project_id, u.ecopart_sample_id, u.sample_name,
       u.cruise_key, u.station_key,
       c.id AS ctd_profile_id, c.dataset_version_id AS ctd_dataset_version_id,
       c.source_profile_key AS ctd_source_profile_key,
       m.source_row_key, m.scan_key, m.depth_m, m.pressure_dbar,
       m.variable_key, m.variable_definition, m.sensor_channel,
       m.value, m.unit, m.qc,
       l.link_method, l.ctd_source, l.distance_km, l.time_gap_hours, l.match_status
FROM warehouse.uvp_profile u
JOIN warehouse.uvp_ctd l ON l.uvp_profile_id = u.id
JOIN warehouse.ctd_profile c ON c.id = l.ctd_profile_id
JOIN warehouse.ctd_measurement m ON m.profile_id = c.id;
