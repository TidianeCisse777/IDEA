-- Position retenue des profils UVP et copie EcoTaxa de référence (13 novembre 2026).
--
-- Position : l'UVP est monté sur la rosette, et le fichier CTD cité dans EcoTaxa fait foi (décision du 13 novembre
-- 2026). Constaté sur la base : positions fausses dans EcoPart et EcoTaxa pour des profils 2021 (`de…`, 20 aux
-- coordonnées entières, ~1,5° de longitude ailleurs) et dans la copie EcoTaxa 149 de GreenEdge 2016 (signe de
-- longitude, latitude 59 au lieu de 69), alors que la CTD citée est à la bonne heure. Un profil dont un lien CTD
-- vient du fichier cité (uvp_ctd, link_method filename_transitive) prend la position et la zone de ce profil CTD
-- (position_source = 'ctd_cite'); sinon il garde la position de la source (position_source = 'source'). La
-- position et la zone d'origine restent dans source_latitude, source_longitude, source_marine_zone_*.
-- warehouse.apply_uvp_cited_ctd_positions() le recalcule; warehouse_uvp_ctd_links.sql l'appelle après les liens.
--
-- Copie de référence : 199 profils GreenEdge 2016 sont liés à deux samples EcoTaxa, copies des mêmes images
-- (projet 149 et 20880 ou 20890). On en garde un par profil, celui dont la position concorde avec celle du
-- profil (donc avec la CTD citée), le plus petit projet à égalité. Avant : toujours le plus petit projet (149),
-- dont la position est fausse pour 19 de ces profils.
--
-- Additive et relançable. Avant les vues explore qui lisent warehouse.uvp_canonical_sample.

-- Kept identical to its copy in warehouse_ecopart_migration.sql (tests/test_uvp_reference.py checks it).
ALTER TABLE warehouse.uvp_profile ADD COLUMN IF NOT EXISTS source_latitude double precision;
ALTER TABLE warehouse.uvp_profile ADD COLUMN IF NOT EXISTS source_longitude double precision;
ALTER TABLE warehouse.uvp_profile ADD COLUMN IF NOT EXISTS source_marine_zone_key text;
ALTER TABLE warehouse.uvp_profile ADD COLUMN IF NOT EXISTS source_marine_zone_name text;
ALTER TABLE warehouse.uvp_profile ADD COLUMN IF NOT EXISTS source_marine_zone_source text;
ALTER TABLE warehouse.uvp_profile ADD COLUMN IF NOT EXISTS source_marine_zone_version text;
ALTER TABLE warehouse.uvp_profile ADD COLUMN IF NOT EXISTS source_marine_zone_assignment_status text;
ALTER TABLE warehouse.uvp_profile ADD COLUMN IF NOT EXISTS position_source text;
ALTER TABLE warehouse.uvp_profile ADD COLUMN IF NOT EXISTS position_ctd_profile_id bigint;
CREATE OR REPLACE VIEW warehouse.uvp_canonical_sample AS
SELECT DISTINCT ON (l.uvp_profile_id) l.uvp_profile_id, e.id AS ecotaxa_sample_id, e.project_id
FROM warehouse.uvp_ecotaxa l
JOIN warehouse.ecotaxa_sample e ON e.id = l.ecotaxa_sample_id
JOIN warehouse.uvp_profile u ON u.id = l.uvp_profile_id
ORDER BY l.uvp_profile_id,
    round((2 * 6371.0088 * asin(least(1, sqrt(power(sin(radians(e.lat_avg - u.latitude) / 2), 2)
        + cos(radians(u.latitude)) * cos(radians(e.lat_avg)) * power(sin(radians(e.lon_avg - u.longitude) / 2), 2)))))::numeric, 1)
        NULLS LAST,
    e.project_id;

COMMENT ON COLUMN warehouse.uvp_profile.position_source IS
    'ctd_cite : latitude, longitude et zone du profil CTD cité dans EcoTaxa (position_ctd_profile_id); source : celles de la source (EcoPart). Les valeurs de la source restent dans source_latitude, source_longitude, source_marine_zone_*.';
COMMENT ON VIEW warehouse.uvp_canonical_sample IS
    'Sample EcoTaxa de référence de chaque profil UVP (un seul) : la copie la plus proche de la position du profil, le plus petit projet à égalité.';

CREATE OR REPLACE FUNCTION warehouse.apply_uvp_cited_ctd_positions()
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
    changed integer;
    reverted integer;
BEGIN
    -- Source values kept once per profile (new profiles of a reload included), before any change.
    UPDATE warehouse.uvp_profile
    SET source_latitude = latitude, source_longitude = longitude,
        source_marine_zone_key = marine_zone_key, source_marine_zone_name = marine_zone_name,
        source_marine_zone_source = marine_zone_source, source_marine_zone_version = marine_zone_version,
        source_marine_zone_assignment_status = marine_zone_assignment_status, position_source = 'source'
    WHERE position_source IS NULL;
    -- Back to the source where the cited CTD link is gone.
    UPDATE warehouse.uvp_profile p
    SET latitude = p.source_latitude, longitude = p.source_longitude,
        marine_zone_key = p.source_marine_zone_key, marine_zone_name = p.source_marine_zone_name,
        marine_zone_source = p.source_marine_zone_source, marine_zone_version = p.source_marine_zone_version,
        marine_zone_assignment_status = p.source_marine_zone_assignment_status,
        position_source = 'source', position_ctd_profile_id = NULL
    WHERE p.position_source = 'ctd_cite' AND NOT EXISTS (
        SELECT 1 FROM warehouse.uvp_ctd u JOIN warehouse.ctd_profile c ON c.id = u.ctd_profile_id
        WHERE u.uvp_profile_id = p.id AND u.link_method = 'filename_transitive'
          AND c.latitude IS NOT NULL AND c.longitude IS NOT NULL);
    GET DIAGNOSTICS reverted = ROW_COUNT;
    WITH cited AS (
        SELECT DISTINCT ON (u.uvp_profile_id) u.uvp_profile_id, c.id, c.latitude, c.longitude, c.marine_zone_key,
               c.marine_zone_name, c.marine_zone_source, c.marine_zone_version, c.marine_zone_assignment_status
        FROM warehouse.uvp_ctd u JOIN warehouse.ctd_profile c ON c.id = u.ctd_profile_id
        WHERE u.link_method = 'filename_transitive' AND c.latitude IS NOT NULL AND c.longitude IS NOT NULL
        ORDER BY u.uvp_profile_id, c.id)
    UPDATE warehouse.uvp_profile p
    SET latitude = c.latitude, longitude = c.longitude,
        marine_zone_key = c.marine_zone_key, marine_zone_name = c.marine_zone_name,
        marine_zone_source = c.marine_zone_source, marine_zone_version = c.marine_zone_version,
        marine_zone_assignment_status = c.marine_zone_assignment_status,
        position_source = 'ctd_cite', position_ctd_profile_id = c.id
    FROM cited c
    WHERE p.id = c.uvp_profile_id
      AND (p.position_source IS DISTINCT FROM 'ctd_cite' OR p.position_ctd_profile_id IS DISTINCT FROM c.id
           OR p.latitude IS DISTINCT FROM c.latitude OR p.longitude IS DISTINCT FROM c.longitude
           OR p.marine_zone_key IS DISTINCT FROM c.marine_zone_key
           OR p.marine_zone_assignment_status IS DISTINCT FROM c.marine_zone_assignment_status);
    GET DIAGNOSTICS changed = ROW_COUNT;
    RETURN changed + reverted;    -- profiles whose position changed, either way
END
$$;
