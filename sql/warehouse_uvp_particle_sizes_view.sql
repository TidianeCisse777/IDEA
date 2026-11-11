-- Additive migration: expose UVP particle size spectra (warehouse.uvp_particle),
-- loaded by populate_ecopart.py but never read back by any explore view before
-- this file. Raw counts and volume only; no density/concentration invented —
-- the caller picks the size range and computes the density itself. sampled_volume_l
-- is a per-bin attribute repeated on every size_class_key row of that bin, so a
-- naive SUM(particle_count)/SUM(sampled_volume_l) over several size classes divides
-- by the volume counted once per class instead of once per bin: aggregate volume
-- per uvp_bin_id first (e.g. MIN(sampled_volume_l) grouped by uvp_bin_id), then sum
-- particles and volume across bins before dividing.
CREATE OR REPLACE VIEW explore.uvp_particle_sizes AS
SELECT
    u.id AS uvp_profile_id, u.dataset_version_id, u.sample_name,
    u.marine_zone_key, u.marine_zone_assignment_status, u.sampled_at,
    b.id AS uvp_bin_id, b.depth_min_m, b.depth_max_m, b.sampled_volume_l,
    p.size_class_key, p.size_min_um, p.size_max_um, p.size_definition,
    p.particle_count, p.observed_volume_m3, p.supplied_concentration, p.concentration_unit
FROM warehouse.uvp_particle p
JOIN warehouse.uvp_bin b ON b.id = p.bin_id
JOIN warehouse.uvp_profile u ON u.id = b.profile_id;

COMMENT ON VIEW explore.uvp_particle_sizes IS
    'Spectre de tailles UVP (produit EcoPart LPM), par profil et bin : une ligne par classe de taille. '
    'Grain non taxonomique, distinct de explore.uvp_taxon_abundance; aucune correspondance avec un taxon. '
    'sampled_volume_l est répété sur chaque size_class_key d''un même bin : pour une densité sur une gamme de '
    'tailles, agréger le volume une fois par uvp_bin_id (ex. MIN(sampled_volume_l) GROUP BY uvp_bin_id), sommer '
    'particle_count et ce volume par bin sur les classes choisies, puis diviser; sinon le volume est compté '
    'une fois par classe au lieu d''une fois par bin. Ne pas mélanger des bins de profondeur différente sans le dire.';
