-- Two reading schemas instead of one, so a person opening the database sees the
-- data first (3 novembre 2026: 37 views in one alphabetical list, rights and
-- FAIR views mixed with the scientific ones):
--   explore    the data: EcoTaxa, UVP/EcoPart, CTD, FILET, zones, reference tables
--   catalogue  about the data and the account: my_access, my_datasets,
--              dataset_catalog, dataset_versions, fair_readiness,
--              fair_column_coverage, warehouse_dictionary, warehouse_context,
--              warehouse_release, access_audit
-- Applied before the files that define those views, which now create them in
-- catalogue. On a database deployed earlier, the existing views are moved
-- (ALTER VIEW ... SET SCHEMA keeps their grants, comments and dependents).
CREATE SCHEMA IF NOT EXISTS catalogue;
COMMENT ON SCHEMA catalogue IS
    'À propos des données et du compte : droits (my_access, my_datasets), catalogue des jeux de données (dataset_catalog, dataset_versions), FAIR, dictionnaire des colonnes, fiches métier des agents (warehouse_context), version déployée. Les données elles-mêmes sont dans le schéma explore.';
COMMENT ON SCHEMA explore IS
    'Les données NeoLab en lecture : projets, samples et objets EcoTaxa, profils et abondances UVP/EcoPart, CTD, FILET, zones maritimes, référentiels. Droits, catalogue et dictionnaire : schéma catalogue.';

DO $$
DECLARE
    -- Dependency order: a view is moved after the views it reads.
    name text;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'warehouse_data_owner') THEN
        EXECUTE 'GRANT USAGE, CREATE ON SCHEMA catalogue TO warehouse_data_owner';
    END IF;
    FOREACH name IN ARRAY ARRAY['dataset_catalog', 'fair_readiness', 'fair_column_coverage', 'my_access',
                                'my_datasets', 'access_audit', 'warehouse_release', 'dataset_versions',
                                'warehouse_dictionary', 'warehouse_context'] LOOP
        IF to_regclass('explore.' || name) IS NOT NULL AND to_regclass('catalogue.' || name) IS NULL THEN
            EXECUTE format('ALTER VIEW explore.%I SET SCHEMA catalogue', name);
        END IF;
    END LOOP;
END
$$;
