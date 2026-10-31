-- Additive migration: expose marine_zone_key/name/assignment_status and
-- ecotaxa_project_id/title on explore.uvp_taxon_abundance, sourced directly
-- from warehouse.uvp_profile (already joined as "u" in this view, just not
-- selected). Found live: a test agent computing abundance by zone found
-- explore.uvp_samples empty for its account's data and, lacking any other
-- path to the zone on this view, fell back to guessing a zone from the
-- dataset's own key text instead of reading the real one already available
-- one join away (see ROADMAP, 31 octobre 2026).
CREATE OR REPLACE VIEW explore.uvp_taxon_abundance AS
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
    u.sampled_at,
    u.marine_zone_key,
    u.marine_zone_name,
    u.marine_zone_assignment_status,
    u.ecotaxa_project_id
FROM warehouse.uvp_taxon_abundance a
JOIN warehouse.uvp_bin b ON b.id = a.bin_id
JOIN warehouse.uvp_profile u ON u.id = a.profile_id;

COMMENT ON VIEW explore.uvp_taxon_abundance IS
    'Abondances UVP dérivées des objets EcoTaxa et volumes EcoPart. marine_zone_key/name/assignment_status et ecotaxa_project_id viennent directement de uvp_profile : ne pas passer par explore.uvp_samples pour la zone (vide quand le profil n''a pas de sample EcoTaxa lié), la zone est déjà ici.';
