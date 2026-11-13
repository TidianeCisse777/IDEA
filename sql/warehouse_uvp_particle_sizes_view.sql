-- Additive migration: expose UVP particle size spectra (warehouse.uvp_particle),
-- loaded by populate_ecopart.py but never read back by any explore view before
-- this file. sampled_volume_l is a per-bin attribute repeated on every size_class_key
-- row of that bin: aggregate volume per uvp_bin_id first (e.g. MIN(sampled_volume_l)
-- grouped by uvp_bin_id), then combine across bins.
--
-- Below the detection limit (13 novembre 2026): EcoPart exports every LPM class from 1 µm, and the classes
-- 1-32 µm are 0 in all 71 520 bins (32-64 µm in 33 676): the UVP does not see them, it did not count none.
-- Unknown is not zero: a class whose upper bound does not exceed the smallest class where the profile detected
-- anything (uvp_profile.particle_min_detected_um, set by warehouse_derived_refresh.sql) has its concentration NULL
-- and below_detection = true; the source value stays in supplied_concentration_source. The zeros of large classes
-- (rare particles, but detectable) stay zeros. Class bounds are rounded to 0.001 µm (8189.999999999999 → 8190).
ALTER TABLE warehouse.uvp_profile ADD COLUMN IF NOT EXISTS particle_min_detected_um double precision;
COMMENT ON COLUMN warehouse.uvp_profile.particle_min_detected_um IS
    'Borne basse de la plus petite classe LPM EcoPart non nulle dans au moins un bin du profil (seuil de détection observé); NULL tant qu''il n''est pas calculé (warehouse_derived_refresh.sql).';

CREATE OR REPLACE VIEW explore.uvp_particle_sizes AS
SELECT
    u.id AS uvp_profile_id, u.dataset_version_id, u.sample_name,
    u.marine_zone_key, u.marine_zone_assignment_status, u.sampled_at,
    b.id AS uvp_bin_id, b.depth_min_m, b.depth_max_m, b.sampled_volume_l,
    p.size_class_key,
    round(p.size_min_um::numeric, 3)::double precision AS size_min_um,
    round(p.size_max_um::numeric, 3)::double precision AS size_max_um,
    p.size_definition,
    p.particle_count, p.observed_volume_m3,
    CASE WHEN p.size_max_um <= u.particle_min_detected_um THEN NULL ELSE p.supplied_concentration END
        AS supplied_concentration,
    p.concentration_unit,
    coalesce(p.size_max_um <= u.particle_min_detected_um, false) AS below_detection,
    p.supplied_concentration AS supplied_concentration_source
FROM warehouse.uvp_particle p
JOIN warehouse.uvp_bin b ON b.id = p.bin_id
JOIN warehouse.uvp_profile u ON u.id = b.profile_id;

COMMENT ON VIEW explore.uvp_particle_sizes IS
    'Spectre de tailles UVP (produit EcoPart LPM), par profil et bin : une ligne par classe de taille. '
    'Grain non taxonomique, distinct de explore.uvp_taxon_abundance; aucune correspondance avec un taxon. '
    'supplied_concentration est la concentration EcoPart en particules/L (concentration_unit); NULL sous le seuil '
    'de détection du profil (below_detection), valeur source dans supplied_concentration_source. particle_count et '
    'observed_volume_m3 sont vides pour les données chargées. sampled_volume_l est répété sur chaque size_class_key '
    'd''un même bin : agréger le volume une fois par uvp_bin_id. Ne pas mélanger des bins de profondeur différente sans le dire.';
