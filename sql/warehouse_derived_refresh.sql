-- Tables dérivées des objets EcoTaxa recalculées quand leur source a changé (13 novembre 2026).
--
-- Constaté sur la base : objets des projets 17498 et 18084 (Amundsen 2024) rechargés avec de nouvelles annotations,
-- mais warehouse.uvp_taxon_abundance (9 659 et 5 863 objets validés de retard, taxons décalés) et
-- warehouse.ecotaxa_sample_taxon (1 669, 208 et 27 lignes fausses pour 17498, 18084, 14622) jamais recalculées.
-- À chaque déploiement : les comptes par sample et taxon sont recalculés (1 à 2 s), puis l'abondance si l'empreinte
-- de sa source (comptes par sample et taxon des samples liés à un profil UVP, rattachement objet → tranche, volumes)
-- a changé depuis le dernier calcul (~1 min 30 pour 12 M d'objets). populate_ecopart.py appelle les mêmes fonctions :
-- une seule définition du calcul. Additive et relançable.

CREATE TABLE IF NOT EXISTS warehouse.derived_refresh (
    name text PRIMARY KEY,
    signature text NOT NULL,
    row_count bigint,
    refreshed_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE warehouse.derived_refresh IS
    'Empreinte de la source au dernier calcul d''une table dérivée (uvp_taxon_abundance) : recalcul seulement si elle change.';

-- Positive counts per bin, taxon and annotation policy for one EcoPart version, or for all of them when p_version is
-- NULL (zeros are added at read time by explore.uvp_taxon_abundance). Two policies: every loaded object, and
-- validated objects only.
CREATE OR REPLACE FUNCTION warehouse.insert_uvp_taxon_abundance(p_version bigint)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE
    inserted bigint;
BEGIN
    INSERT INTO warehouse.uvp_taxon_abundance
        (dataset_version_id, profile_id, bin_id, taxon_key, annotation_policy,
         n_objects_taxon, sampled_volume_l, calculation_version, taxon_name)
    SELECT p.dataset_version_id, b.profile_id, b.id,
        CASE WHEN o.category_id IS NOT NULL THEN 'ecotaxa:id:' || o.category_id
             WHEN o.category_name IS NOT NULL THEN 'ecotaxa:name:' || o.category_name
             ELSE 'warehouse:unclassified' END,
        pol.policy || ':ecotaxa_project=' || s.project_id,
        count(*), b.sampled_volume_l, 'ecopart-warehouse-v1-sparse',
        min(o.category_name)
    FROM warehouse.uvp_bin b
    JOIN warehouse.uvp_profile p ON p.id = b.profile_id
    JOIN warehouse.uvp_object_bin m ON m.uvp_bin_id = b.id
    JOIN warehouse.ecotaxa_object o ON o.id = m.ecotaxa_object_id
    JOIN warehouse.ecotaxa_sample s ON s.id = o.sample_id
    CROSS JOIN LATERAL (VALUES ('all_loaded_objects', true),
                               ('validated_only', o.annotation_status = 'validated')) pol(policy, keep)
    WHERE (p_version IS NULL OR p.dataset_version_id = p_version) AND pol.keep
    GROUP BY 1, 2, 3, 4, 5;
    GET DIAGNOSTICS inserted = ROW_COUNT;
    RETURN inserted;
END
$$;

CREATE OR REPLACE FUNCTION warehouse.uvp_abundance_signature()
RETURNS text LANGUAGE sql STABLE AS $$
    SELECT md5(concat_ws('|',
        (SELECT string_agg(concat_ws(':', t.sample_id, t.taxon_id, t.n_objects, t.n_validated), ','
                           ORDER BY t.sample_id, t.taxon_id)
         FROM warehouse.ecotaxa_sample_taxon t
         WHERE t.sample_id IN (SELECT ecotaxa_sample_id FROM warehouse.uvp_ecotaxa)),
        (SELECT count(*) || ':' || coalesce(sum(uvp_bin_id), 0) FROM warehouse.uvp_object_bin),
        (SELECT string_agg(concat_ws(':', id, profile_id, sampled_volume_l), ',' ORDER BY id) FROM warehouse.uvp_bin)))
$$;

-- Rebuilds uvp_taxon_abundance for every EcoPart version when its source changed (or always with p_force).
-- Returns the number of rows written, or -1 when it was already up to date.
CREATE OR REPLACE FUNCTION warehouse.refresh_uvp_taxon_abundance(p_force boolean DEFAULT false)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE
    signature text := warehouse.uvp_abundance_signature();
    total bigint := 0;
BEGIN
    IF NOT p_force AND signature IS NOT DISTINCT FROM
            (SELECT d.signature FROM warehouse.derived_refresh d WHERE d.name = 'uvp_taxon_abundance') THEN
        RETURN -1;
    END IF;
    PERFORM pg_advisory_xact_lock(4172026);
    -- Every EcoPart version in one pass: one version at a time made each pass read the 12 M objects again
    -- (13 November 2026: still running after 2 h on the lab PC, ~1 min 20 for all at once).
    DELETE FROM warehouse.uvp_taxon_abundance a USING warehouse.dataset_version v
    WHERE v.id = a.dataset_version_id AND v.source_instance = 'ecopart';
    total := warehouse.insert_uvp_taxon_abundance(NULL);
    INSERT INTO warehouse.derived_refresh (name, signature, row_count, refreshed_at)
    VALUES ('uvp_taxon_abundance', signature, total, now())
    ON CONFLICT (name) DO UPDATE SET signature = EXCLUDED.signature, row_count = EXCLUDED.row_count,
                                     refreshed_at = EXCLUDED.refreshed_at;
    RETURN total;
END
$$;

-- Is the abundance up to date with its source (neolab-status)?
CREATE OR REPLACE FUNCTION warehouse.uvp_abundance_is_fresh()
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT warehouse.uvp_abundance_signature() IS NOT DISTINCT FROM
           (SELECT d.signature FROM warehouse.derived_refresh d WHERE d.name = 'uvp_taxon_abundance')
$$;

-- Particle detection limit observed per profile (explore.uvp_particle_sizes, below_detection): lower bound of the
-- smallest LPM class with a non-zero concentration in at least one bin of the profile (~1 s for 1 M rows).
UPDATE warehouse.uvp_profile u
SET particle_min_detected_um = d.min_detected_um
FROM (SELECT b.profile_id, min(p.size_min_um) FILTER (WHERE p.supplied_concentration > 0) AS min_detected_um
      FROM warehouse.uvp_particle p JOIN warehouse.uvp_bin b ON b.id = p.bin_id GROUP BY b.profile_id) d
WHERE u.id = d.profile_id AND u.particle_min_detected_um IS DISTINCT FROM d.min_detected_um;

SELECT warehouse.refresh_ecotaxa_sample_taxon(true);
SELECT warehouse.refresh_uvp_taxon_abundance();
