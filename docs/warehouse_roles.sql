-- Access roles for the NeoLab warehouse. Idempotent; run as the owner role
-- (POSTGRES_USER, "neolab") on the target database, after every other DDL file:
--
--   WAREHOUSE_READER_PASSWORD=... WAREHOUSE_NAVIGATOR_PASSWORD=... \
--   psql -v ON_ERROR_STOP=1 -d neolab_warehouse -f docs/warehouse_roles.sql
--
-- Passwords are read from the environment so they never appear in a process
-- list; -v reader_password=... / -v navigator_password=... also works (tests).
-- Roles (see docs/WAREHOUSE_ROLES.md):
--   neolab               owner and loader. The only role that writes.
--   warehouse_navigator  navigator API. SELECT on warehouse and explore.
--   warehouse_reader     DbHub / agents. SELECT on explore only.
-- Both are members of warehouse_all_access (see every row). Scoped readers are
-- created separately and enrolled with warehouse.enroll_access_role().
-- Both read roles are read-only, time-bounded and cannot create objects.
\set ON_ERROR_STOP on
\if :{?reader_password}
\else
  \getenv reader_password WAREHOUSE_READER_PASSWORD
\endif
\if :{?navigator_password}
\else
  \getenv navigator_password WAREHOUSE_NAVIGATOR_PASSWORD
\endif
\if :{?reader_password}
\else
  DO $$ BEGIN RAISE EXCEPTION 'WAREHOUSE_READER_PASSWORD is required'; END $$;
\endif
\if :{?navigator_password}
\else
  DO $$ BEGIN RAISE EXCEPTION 'WAREHOUSE_NAVIGATOR_PASSWORD is required'; END $$;
\endif

-- The access-control file creates the groups used below and must run first.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'warehouse_all_access') THEN
        RAISE EXCEPTION 'apply docs/warehouse_access_control.sql before warehouse_roles.sql';
    END IF;
END
$$;

-- Create the read roles when absent; rotate their password on every run.
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
              r.rolname, CASE r.rolname WHEN 'warehouse_reader' THEN :'reader_password'
                                        ELSE :'navigator_password' END)
FROM (VALUES ('warehouse_reader'), ('warehouse_navigator')) AS r(rolname)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE pg_roles.rolname = r.rolname)
\gexec

SELECT format('ALTER ROLE %I PASSWORD %L', 'warehouse_reader', :'reader_password') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', 'warehouse_navigator', :'navigator_password') \gexec

-- Nothing is public: connection and schema creation are granted by name.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

SELECT format('GRANT CONNECT ON DATABASE %I TO warehouse_reader, warehouse_navigator, warehouse_explore_reader',
              current_database()) \gexec

GRANT warehouse_all_access TO warehouse_reader, warehouse_navigator;

ALTER ROLE warehouse_reader SET default_transaction_read_only = on;
ALTER ROLE warehouse_reader SET statement_timeout = '30s';
ALTER ROLE warehouse_navigator SET default_transaction_read_only = on;
ALTER ROLE warehouse_navigator SET statement_timeout = '30s';
-- Agent-facing reads: the planner misestimates explore.uvp_objects and picks a
-- merge join that discards hundreds of millions of rows (> 90 s on 4.8 M
-- objects); hash joins finish in 7-9 s. Measured in docs/WAREHOUSE_ACCESS_CONTROL.md.
ALTER ROLE warehouse_reader SET enable_mergejoin = off;

-- The reader sees the curated surface only; raw tables stay out of reach.
REVOKE ALL ON SCHEMA warehouse FROM warehouse_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA warehouse FROM warehouse_reader;
GRANT USAGE ON SCHEMA explore TO warehouse_reader, warehouse_navigator, warehouse_explore_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA explore TO warehouse_reader, warehouse_navigator, warehouse_explore_reader;

GRANT USAGE ON SCHEMA warehouse TO warehouse_navigator;
GRANT SELECT ON ALL TABLES IN SCHEMA warehouse TO warehouse_navigator;

-- Objects created later by the owner (new views, reloads) stay reachable
-- without a re-grant; the reader still never gets the warehouse schema.
-- Views are created by the loader or, once ownership is transferred, by the
-- data owner: cover both.
ALTER DEFAULT PRIVILEGES IN SCHEMA explore
    GRANT SELECT ON TABLES TO warehouse_reader, warehouse_navigator, warehouse_explore_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA warehouse
    GRANT SELECT ON TABLES TO warehouse_navigator;
ALTER DEFAULT PRIVILEGES FOR ROLE warehouse_data_owner IN SCHEMA explore
    GRANT SELECT ON TABLES TO warehouse_reader, warehouse_navigator, warehouse_explore_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE warehouse_data_owner IN SCHEMA warehouse
    GRANT SELECT ON TABLES TO warehouse_navigator;

-- Scoped readers never reach raw tables or the grant list.
REVOKE ALL ON SCHEMA warehouse FROM warehouse_explore_reader;
