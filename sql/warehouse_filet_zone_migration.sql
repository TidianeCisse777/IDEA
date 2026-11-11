-- FILET spatial enrichment: same versioned zone contract as EcoTaxa/EcoPart.
ALTER TABLE warehouse.filet_sample
    ADD COLUMN IF NOT EXISTS marine_zone_key text,
    ADD COLUMN IF NOT EXISTS marine_zone_name text,
    ADD COLUMN IF NOT EXISTS marine_zone_source text,
    ADD COLUMN IF NOT EXISTS marine_zone_version text,
    ADD COLUMN IF NOT EXISTS marine_zone_assignment_status text
        CHECK (marine_zone_assignment_status IN ('assigned', 'ambiguous', 'outside', 'unresolved'));

CREATE INDEX IF NOT EXISTS filet_sample_marine_zone_name_idx
    ON warehouse.filet_sample (marine_zone_name);

CREATE OR REPLACE VIEW explore.filet_samples AS
SELECT s.id, s.dataset_version_id, s.sample_id, s.deployment_id,
       s.sampling_year, s.sampling_platform, s.station_name,
       s.deployment_datetime_start, s.deployment_datetime_end, s.cast_number,
       s.latitude, s.longitude, s.gear, s.tow_type, s.min_sample_depth,
       s.max_sample_depth, s.net_mesh_size, s.depth_calc_net_filtered_vol,
       s.flowmeter_calc_vol, s.number_of_nets, s.sample_nets,
       s.net_sampling_ids, s.subsampling_quantity, s.subsampling_unit,
       COUNT(DISTINCT a.id) AS n_analyses,
       s.marine_zone_key, s.marine_zone_name, s.marine_zone_source,
       s.marine_zone_version, s.marine_zone_assignment_status
FROM warehouse.filet_sample s
LEFT JOIN warehouse.filet_analysis a ON a.sample_ref = s.id
GROUP BY s.id, s.dataset_version_id, s.sample_id, s.deployment_id,
         s.sampling_year, s.sampling_platform, s.station_name,
         s.deployment_datetime_start, s.deployment_datetime_end, s.cast_number,
         s.latitude, s.longitude, s.gear, s.tow_type, s.min_sample_depth,
         s.max_sample_depth, s.net_mesh_size, s.depth_calc_net_filtered_vol,
         s.flowmeter_calc_vol, s.number_of_nets, s.sample_nets,
         s.net_sampling_ids, s.subsampling_quantity, s.subsampling_unit,
         s.marine_zone_key, s.marine_zone_name, s.marine_zone_source,
         s.marine_zone_version, s.marine_zone_assignment_status;
