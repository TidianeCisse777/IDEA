-- Additive migration: expose marine_zone_key/name/assignment_status and
-- ecotaxa_project_id/title on explore.uvp_taxon_abundance, sourced directly
-- from warehouse.uvp_profile (already joined as "u" in this view, just not
-- selected). Found live: a test agent computing abundance by zone found
-- explore.uvp_samples empty for its account's data and, lacking any other
-- path to the zone on this view, fell back to guessing a zone from the
-- dataset's own key text instead of reading the real one already available
-- one join away (see ROADMAP, 31 octobre 2026).
-- Taxon display name next to its key (ecotaxa:id:N says nothing to a reader); set by
-- populate_ecopart.insert_abundance from the objects' EcoTaxa display name.
ALTER TABLE warehouse.uvp_taxon_abundance ADD COLUMN IF NOT EXISTS taxon_name text;
-- Kept identical to its copy in warehouse_ecopart_migration.sql (tests/test_warehouse_schema.py checks it):
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
       t.taxon_name
FROM taxa t
JOIN warehouse.uvp_profile u ON u.id=t.profile_id
JOIN warehouse.uvp_bin b ON b.profile_id=t.profile_id
LEFT JOIN warehouse.uvp_taxon_abundance a
 ON a.dataset_version_id=t.dataset_version_id AND a.bin_id=b.id
 AND a.taxon_key=t.taxon_key AND a.annotation_policy=t.annotation_policy;

COMMENT ON VIEW explore.uvp_taxon_abundance IS
    'Abondances UVP dérivées des objets EcoTaxa et volumes EcoPart, zéros ajoutés à la lecture pour les bins sans objet d''un taxon observé dans le profil. marine_zone_key/name/assignment_status et ecotaxa_project_id viennent directement de uvp_profile : ne pas passer par explore.uvp_samples pour la zone (vide quand le profil n''a pas de sample EcoTaxa lié), la zone est déjà ici.';
