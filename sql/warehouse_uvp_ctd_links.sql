-- Liens profil UVP → profil CTD, recalculés à chaque déploiement.
--
-- Même règle que populate_ecopart.py : lien transitif profil UVP → sample EcoTaxa (warehouse.uvp_ecotaxa,
-- profil EcoPart exact) → profil CTD (warehouse.ecotaxa_ctd, match_status accepted). Le chargeur EcoPart ne
-- les crée qu'au moment où il tourne : les CTD Amundsen chargées après lui laissaient warehouse.uvp_ctd vide
-- (explore.uvp_ctd à 0 ligne, constaté le 11 novembre 2026). Un lien dont la source n'est plus acceptée est
-- retiré. Ce fichier ne fait aucun lien par proximité (scripts/populate_ctd_proximity.py s'en charge, avec
-- link_method = 'proximity'). Additive et relançable. Après warehouse_ctd_proximity_migration.sql (link_method).

INSERT INTO warehouse.uvp_ctd (uvp_profile_id, ctd_profile_id, source_evidence)
SELECT DISTINCT l.uvp_profile_id, c.ctd_profile_id,
       'Transitive accepted EcoTaxa–CTD link; exact EcoPart profile; see uvp_ecotaxa and ecotaxa_ctd'
FROM warehouse.uvp_ecotaxa l
JOIN warehouse.ecotaxa_ctd c ON c.ecotaxa_sample_id = l.ecotaxa_sample_id
WHERE c.match_status = 'accepted'
ON CONFLICT DO NOTHING;

DELETE FROM warehouse.uvp_ctd u
WHERE u.link_method = 'filename_transitive'  -- proximity links belong to populate_ctd_proximity.py
  AND NOT EXISTS (
    SELECT 1 FROM warehouse.uvp_ecotaxa l
    JOIN warehouse.ecotaxa_ctd c ON c.ecotaxa_sample_id = l.ecotaxa_sample_id AND c.match_status = 'accepted'
    WHERE l.uvp_profile_id = u.uvp_profile_id AND c.ctd_profile_id = u.ctd_profile_id);

-- Position of each UVP profile from the CTD cited in EcoTaxa, once the links are known
-- (warehouse_uvp_reference_migration.sql; run again by populate_ctd_proximity.py after new CTD zones).
SELECT warehouse.apply_uvp_cited_ctd_positions();

-- Distance and time gap of the filename links, for transparency: between the UVP's declared position (EcoPart when it
-- gives both coordinates, else its reference EcoTaxa copy; 30 GreenEdge profiles have an EcoPart latitude without
-- longitude) and time, and the cited CTD. They do not change the link (the cited file is the source of truth): they
-- show the cases to read with care (e.g. ge_2016_149-151: same place, ~151 h apart; de… 2021: declared positions
-- 40-110 km off). NULL when the UVP declares no complete position (warehouse.haversine_km is STRICT).
UPDATE warehouse.uvp_ctd t
SET distance_km = x.distance_km, time_gap_hours = x.time_gap_hours
FROM (
    SELECT u.uvp_profile_id, u.ctd_profile_id,
           round(warehouse.haversine_km(d.lat, d.lon, c.latitude, c.longitude)::numeric, 2) AS distance_km,
           round((abs(extract(epoch FROM c.sampled_at - p.sampled_at)) / 3600)::numeric, 2) AS time_gap_hours
    FROM warehouse.uvp_ctd u
    JOIN warehouse.uvp_profile p ON p.id = u.uvp_profile_id
    JOIN warehouse.ctd_profile c ON c.id = u.ctd_profile_id
    LEFT JOIN warehouse.uvp_canonical_sample k ON k.uvp_profile_id = p.id
    LEFT JOIN warehouse.ecotaxa_sample e ON e.id = k.ecotaxa_sample_id
    CROSS JOIN LATERAL (SELECT CASE WHEN p.source_latitude IS NOT NULL AND p.source_longitude IS NOT NULL
                                    THEN p.source_latitude ELSE e.lat_avg END AS lat,
                               CASE WHEN p.source_latitude IS NOT NULL AND p.source_longitude IS NOT NULL
                                    THEN p.source_longitude ELSE e.lon_avg END AS lon) d
    WHERE u.link_method = 'filename_transitive'
) x
WHERE t.uvp_profile_id = x.uvp_profile_id AND t.ctd_profile_id = x.ctd_profile_id
  AND (t.distance_km IS DISTINCT FROM x.distance_km OR t.time_gap_hours IS DISTINCT FROM x.time_gap_hours);
