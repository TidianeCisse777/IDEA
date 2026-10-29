-- Release record of the NeoLab warehouse. Run last, as the owner, by
-- scripts/deploy_warehouse_postgres.py or the Docker init hook. Each run appends
-- one row: which release was applied, how, by whom, and the SHA-256 of every
-- migration file. Readable by all accounts through explore.warehouse_release.
--
--   psql -v release=1.0.0 -v method=manual -v migrations='[]' -f docs/warehouse_release.sql
\set ON_ERROR_STOP on
\if :{?release}
\else
  \set release '1.0.0'
\endif
\if :{?method}
\else
  \set method 'manual'
\endif
\if :{?migrations}
\else
  \set migrations '[]'
\endif

CREATE TABLE IF NOT EXISTS warehouse.release_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release text NOT NULL,
    method text NOT NULL,
    applied_by name NOT NULL DEFAULT session_user,
    applied_at timestamptz NOT NULL DEFAULT now(),
    migrations jsonb NOT NULL DEFAULT '[]'::jsonb
);
-- Same owner as every other warehouse table, so the explore view (adopted by
-- the data owner at creation) can read it on the very first deploy.
ALTER TABLE warehouse.release_history OWNER TO warehouse_data_owner;
COMMENT ON TABLE warehouse.release_history IS
    'Historique des déploiements: version, méthode, auteur, date et empreinte SHA-256 de chaque migration appliquée.';

INSERT INTO warehouse.release_history (release, method, migrations)
VALUES (:'release', :'method', CAST(:'migrations' AS jsonb));

CREATE OR REPLACE VIEW explore.warehouse_release AS
SELECT release, method, applied_at, jsonb_array_length(migrations) AS migration_count, migrations
FROM warehouse.release_history
ORDER BY applied_at DESC, id DESC
LIMIT 1;
COMMENT ON VIEW explore.warehouse_release IS
    'Version du warehouse actuellement déployée, méthode et empreintes des migrations.';
DO $$
DECLARE
    reader name;
BEGIN
    FOREACH reader IN ARRAY ARRAY['warehouse_reader', 'warehouse_navigator', 'warehouse_explore_reader']::name[] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = reader) THEN
            EXECUTE format('GRANT SELECT ON explore.warehouse_release TO %I', reader);
        END IF;
    END LOOP;
END
$$;
