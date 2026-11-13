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
