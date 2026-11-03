-- Additive migration: preserve original export rows and ingestion evidence.
CREATE TABLE IF NOT EXISTS warehouse.ecopart_project_import (
    dataset_version_id bigint PRIMARY KEY REFERENCES warehouse.dataset_version,
    ecopart_project_id bigint NOT NULL,
    ecotaxa_project_ids bigint[] NOT NULL,
    manifest_json jsonb NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS warehouse.ecopart_bin_source (
    bin_id bigint PRIMARY KEY REFERENCES warehouse.uvp_bin,
    source_depth_m double precision NOT NULL,
    source_row_json jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS uvp_bin_profile_depth_idx
    ON warehouse.uvp_bin(profile_id, depth_min_m);
CREATE INDEX IF NOT EXISTS uvp_ecotaxa_sample_idx
    ON warehouse.uvp_ecotaxa(ecotaxa_sample_id);
CREATE INDEX IF NOT EXISTS uvp_object_bin_bin_idx
    ON warehouse.uvp_object_bin(uvp_bin_id);

-- Scope mappings to the profile in this row, including multiple source versions.
CREATE OR REPLACE VIEW explore.uvp_objects AS
SELECT
    u.id AS uvp_profile_id, u.dataset_version_id, u.ecopart_project_id,
    u.sample_name, u.cruise_key, u.station_key, u.sampled_at,
    COALESCE(e.marine_zone_key,u.marine_zone_key) AS marine_zone_key,
    COALESCE(e.marine_zone_name,u.marine_zone_name) AS marine_zone_name,
    COALESCE(e.marine_zone_version,u.marine_zone_version) AS marine_zone_version,
    COALESCE(e.marine_zone_assignment_status,u.marine_zone_assignment_status) AS marine_zone_assignment_status,
    e.id AS ecotaxa_sample_id, e.project_id AS ecotaxa_project_id, e.sample_orig_id,
    o.id AS ecotaxa_object_id, o.object_id, o.acquisition_id, o.process_id,
    o.category_id AS taxon_id, o.category_name AS taxon_name, o.annotation_status,
    o.depth_min_m AS object_depth_min_m, o.depth_max_m AS object_depth_max_m,
    b.id AS uvp_bin_id, b.source_bin_key, b.depth_min_m, b.depth_max_m,
    b.sampled_volume_l, ob.depth_delta_m, ob.mapping_method, ob.mapping_status, o.image_uri
FROM warehouse.uvp_profile u
JOIN warehouse.uvp_ecotaxa ul ON ul.uvp_profile_id=u.id
JOIN warehouse.ecotaxa_sample e ON e.id=ul.ecotaxa_sample_id
JOIN warehouse.ecotaxa_object o ON o.sample_id=e.id
LEFT JOIN (warehouse.uvp_object_bin ob
    JOIN warehouse.uvp_bin b ON b.id=ob.uvp_bin_id)
    ON ob.ecotaxa_object_id=o.id AND b.profile_id=u.id;

-- Multiple EcoTaxa projects can refer to one EcoPart project.
-- Kept identical to its copy in warehouse_ecotaxa_project_title_migration.sql (tests/test_warehouse_schema.py checks it):
-- populate_ecopart.py replays the EcoPart migration at load time, after the always-applied migrations.
CREATE OR REPLACE VIEW explore.uvp_projects AS
SELECT e.project_id AS ecotaxa_project_id,u.ecopart_project_id,u.cruise_key,
    MIN(u.sampled_at) AS start_at,MAX(u.sampled_at) AS end_at,
    COUNT(DISTINCT u.id) AS n_profiles,COUNT(DISTINCT e.id) AS n_ecotaxa_samples,
    COUNT(DISTINCT u.cast_key) AS n_casts,
    COALESCE(MIN(e.marine_zone_key),MIN(u.marine_zone_key)) AS marine_zone_key,
    COALESCE(MIN(e.marine_zone_name),MIN(u.marine_zone_name)) AS marine_zone_name,
    MIN(u.latitude) AS latitude_min,MAX(u.latitude) AS latitude_max,
    MIN(u.longitude) AS longitude_min,MAX(u.longitude) AS longitude_max,
    MIN(ep.title) AS ecotaxa_project_title,
    ARRAY_AGG(DISTINCT COALESCE(e.marine_zone_key,u.marine_zone_key) ORDER BY COALESCE(e.marine_zone_key,u.marine_zone_key))
        FILTER (WHERE COALESCE(e.marine_zone_key,u.marine_zone_key) IS NOT NULL) AS marine_zone_keys
FROM warehouse.uvp_profile u
LEFT JOIN warehouse.uvp_ecotaxa l ON l.uvp_profile_id=u.id
LEFT JOIN warehouse.ecotaxa_sample e ON e.id=l.ecotaxa_sample_id
LEFT JOIN warehouse.ecotaxa_project ep ON ep.project_id=e.project_id
GROUP BY e.project_id,u.ecopart_project_id,u.cruise_key;

-- All sampled bins, including bins without objects; raw CTD and particle fields
-- retain their original column names and units in source_row_json.
CREATE OR REPLACE VIEW explore.ecopart_bins AS
SELECT u.dataset_version_id,u.ecopart_project_id,u.id AS profile_id,u.sample_name,
       b.id AS bin_id,b.depth_min_m,b.depth_max_m,b.sampled_volume_l,
       s.source_depth_m,s.source_row_json,
       -- Same keys under the names the other explore views use (uvp_profile_id, uvp_bin_id).
       u.id AS uvp_profile_id,b.id AS uvp_bin_id
FROM warehouse.uvp_profile u
JOIN warehouse.uvp_bin b ON b.profile_id=u.id
JOIN warehouse.ecopart_bin_source s ON s.bin_id=b.id;

-- Taxon display name next to its key (ecotaxa:id:N says nothing to a reader); set by
-- populate_ecopart.insert_abundance from the objects' EcoTaxa display name.
ALTER TABLE warehouse.uvp_taxon_abundance ADD COLUMN IF NOT EXISTS taxon_name text;
-- Densify on read, without millions of redundant stored zero values.
-- Taxon universe: taxa observed in this profile and this EcoTaxa project.
-- Kept identical to its copy in warehouse_uvp_abundance_zone_migration.sql (tests/test_warehouse_schema.py checks it):
-- populate_ecopart.py replays the EcoPart migration at load time, after the always-applied migrations.
CREATE OR REPLACE VIEW explore.uvp_taxon_abundance AS
WITH taxa AS (
    SELECT dataset_version_id,profile_id,taxon_key,annotation_policy,MIN(taxon_name) AS taxon_name
    FROM warehouse.uvp_taxon_abundance
    GROUP BY 1,2,3,4
)
SELECT t.dataset_version_id,t.profile_id,b.id AS bin_id,t.taxon_key,t.annotation_policy,
       COALESCE(a.n_objects_taxon,0::bigint) AS n_objects_taxon,b.sampled_volume_l,
       COALESCE(a.n_objects_taxon,0)::numeric / b.sampled_volume_l * 1000 AS abundance_uvp_ind_m3,
       b.depth_min_m,b.depth_max_m,u.sample_name,u.cruise_key,u.station_key,u.sampled_at,
       u.marine_zone_key,u.marine_zone_name,u.marine_zone_assignment_status,u.ecotaxa_project_id,
       t.taxon_name,t.profile_id AS uvp_profile_id,b.id AS uvp_bin_id
FROM taxa t
JOIN warehouse.uvp_profile u ON u.id=t.profile_id
JOIN warehouse.uvp_bin b ON b.profile_id=t.profile_id
LEFT JOIN warehouse.uvp_taxon_abundance a
 ON a.dataset_version_id=t.dataset_version_id AND a.bin_id=b.id
 AND a.taxon_key=t.taxon_key AND a.annotation_policy=t.annotation_policy;

CREATE TABLE IF NOT EXISTS warehouse.ecopart_auxiliary_row (
    dataset_version_id bigint NOT NULL REFERENCES warehouse.dataset_version,
    member_name text NOT NULL,
    row_number integer NOT NULL,
    content_kind text NOT NULL CHECK(content_kind IN ('metadata','zooplankton')),
    profile_name text,
    source_row_json jsonb NOT NULL,
    PRIMARY KEY(dataset_version_id,member_name,row_number)
);
CREATE OR REPLACE VIEW explore.ecopart_source_metadata AS
SELECT dataset_version_id,profile_name,source_row_json
FROM warehouse.ecopart_auxiliary_row WHERE content_kind='metadata';
CREATE OR REPLACE VIEW explore.ecopart_supplied_zooplankton AS
SELECT dataset_version_id,profile_name,source_row_json
FROM warehouse.ecopart_auxiliary_row WHERE content_kind='zooplankton';
