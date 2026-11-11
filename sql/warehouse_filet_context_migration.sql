-- FILET : contexte de l'export du labo jusqu'ici non chargé, et engin visible sur chaque ligne d'abondance.
--
-- filet_sample : profondeur du fond (bottom_depth, m), ouverture du filet (net_mouth_aperture, m²) et
-- commentaires du labo (déploiement, filet, échantillon); filet_analysis : commentaire d'analyse. Les
-- commentaires signalent des échantillons non quantitatifs, des filets regroupés ou perdus, la méthode de trait.
-- explore.filet_data et filet_totals portent gear, tow_type et ces informations (colonnes ajoutées en fin).
-- Valeurs copiées telles quelles depuis l'export (scripts/populate_filet.py). Additive et relançable.

ALTER TABLE warehouse.filet_sample
    ADD COLUMN IF NOT EXISTS bottom_depth numeric,
    ADD COLUMN IF NOT EXISTS net_mouth_aperture numeric,
    ADD COLUMN IF NOT EXISTS deployment_comments text,
    ADD COLUMN IF NOT EXISTS net_comments text,
    ADD COLUMN IF NOT EXISTS sample_comments text;
ALTER TABLE warehouse.filet_analysis ADD COLUMN IF NOT EXISTS analysis_comments text;

-- filet_samples is rebuilt (its column order differs between a new database and one migrated over time, so
-- it cannot be replaced in place); filet_deployments, which reads it, is recreated by its own migration next.
DROP VIEW IF EXISTS explore.filet_deployments;
DROP VIEW IF EXISTS explore.filet_samples;
CREATE VIEW explore.filet_samples AS
SELECT s.id, s.dataset_version_id, s.sample_id, s.deployment_id,
       s.sampling_year, s.sampling_platform, s.station_name,
       s.deployment_datetime_start, s.deployment_datetime_end, s.cast_number,
       s.latitude, s.longitude, s.gear, s.tow_type, s.min_sample_depth,
       s.max_sample_depth, s.net_mesh_size, s.depth_calc_net_filtered_vol,
       s.flowmeter_calc_vol, s.number_of_nets, s.sample_nets,
       s.net_sampling_ids, s.subsampling_quantity, s.subsampling_unit,
       COUNT(DISTINCT a.id) AS n_analyses,
       s.marine_zone_key, s.marine_zone_name, s.marine_zone_source,
       s.marine_zone_version, s.marine_zone_assignment_status,
       s.bottom_depth, s.net_mouth_aperture, s.deployment_comments, s.net_comments, s.sample_comments
FROM warehouse.filet_sample s
LEFT JOIN warehouse.filet_analysis a ON a.sample_ref = s.id
GROUP BY s.id;

CREATE OR REPLACE VIEW explore.filet_data AS
SELECT f.*, s.deployment_id, s.sampling_year, s.sampling_platform,
       s.station_name, s.deployment_datetime_start,
       s.latitude, s.longitude, s.min_sample_depth, s.max_sample_depth,
       s.net_mesh_size, s.depth_calc_net_filtered_vol, s.flowmeter_calc_vol,
       s.net_sampling_ids, s.subsampling_quantity, s.subsampling_unit,
       a.analysis_contract, a.analysis_protocol_id,
       (a.id IS NOT NULL) AS metadata_matched,
       s.gear, s.tow_type, s.net_mouth_aperture, s.bottom_depth, s.sample_comments, a.analysis_comments
FROM warehouse.filet_abundance f
LEFT JOIN warehouse.filet_analysis a
    ON a.dataset_version_id = f.metadata_dataset_version_id
   AND a.sample_id = f.sample_id AND a.analysis_id = f.analysis_id
LEFT JOIN warehouse.filet_sample s ON s.id = a.sample_ref;

CREATE OR REPLACE VIEW explore.filet_totals AS
SELECT * FROM explore.filet_data WHERE stage = 'ALL_STAGES';
