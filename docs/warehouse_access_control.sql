-- Row-level access control for the NeoLab warehouse. Idempotent; run as the
-- owner role after the DDL and FAIR files and BEFORE warehouse_roles.sql.
-- Design and operation: docs/WAREHOUSE_ACCESS_CONTROL.md.
--
-- A role sees a row only if an active access_grant matches the row's source,
-- contract (carried by the dataset version), zone and year. No grant means no
-- rows. Members of warehouse_all_access (loader, navigator, reader) see all.
--
-- PostgreSQL ignores row security for superusers and for table owners unless
-- forced, and a view runs with its owner's rights. Data therefore belongs to a
-- non-superuser role, row security is FORCED, and policies key on session_user
-- (the login role), never on current_user (which is the view owner).
-- This file contains no psql meta-commands so psycopg can run it as well.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'warehouse_data_owner') THEN
        CREATE ROLE warehouse_data_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'warehouse_all_access') THEN
        CREATE ROLE warehouse_all_access NOLOGIN NOSUPERUSER;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'warehouse_explore_reader') THEN
        CREATE ROLE warehouse_explore_reader NOLOGIN NOSUPERUSER;
    END IF;
END
$$;

-- The deploying role keeps full rights: it can maintain the data-owner objects
-- and is never filtered.
GRANT warehouse_data_owner TO CURRENT_USER;
GRANT warehouse_all_access TO CURRENT_USER;
-- CREATE is required to receive objects through ALTER ... OWNER TO.
GRANT USAGE, CREATE ON SCHEMA warehouse, explore TO warehouse_data_owner;

ALTER TABLE warehouse.dataset_metadata ADD COLUMN IF NOT EXISTS access_contract text;

CREATE TABLE IF NOT EXISTS warehouse.access_grant (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    grantee name NOT NULL,
    source_instance text,
    contract text,
    zone_key text,
    year_min integer,
    year_max integer,
    note text,
    granted_by name NOT NULL DEFAULT session_user,
    granted_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    CHECK (year_max IS NULL OR year_min IS NULL OR year_max >= year_min)
);
COMMENT ON TABLE warehouse.access_grant IS
    'Droits de lecture par rôle. NULL = sans restriction sur cette dimension. Révoquer = renseigner revoked_at (historique conservé).';

CREATE INDEX IF NOT EXISTS access_grant_active_idx
    ON warehouse.access_grant (grantee) WHERE revoked_at IS NULL;

CREATE OR REPLACE FUNCTION warehouse.is_unrestricted()
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog
AS $$ SELECT pg_has_role(session_user, 'warehouse_all_access', 'member') $$;

-- p_scoped = false checks source and contract only (tables with no row-level
-- zone or year). NULL zone or year match only grants that do not bound them, so
-- rows of unknown scope need an unscoped grant. A zone grant requires an
-- 'assigned' zone: ambiguous, outside and unresolved rows stay hidden.
CREATE OR REPLACE FUNCTION warehouse.row_allowed(
    p_version bigint, p_zone text, p_zone_status text, p_year integer,
    p_scoped boolean DEFAULT true)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, warehouse
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM warehouse.access_grant g
        JOIN pg_roles r ON r.rolname = g.grantee
        JOIN warehouse.dataset_version v ON v.id = p_version
        LEFT JOIN warehouse.dataset_metadata m ON m.dataset_version_id = v.id
        WHERE g.revoked_at IS NULL
          AND pg_has_role(session_user, r.oid, 'member')
          AND (g.source_instance IS NULL OR g.source_instance = v.source_instance)
          AND (g.contract IS NULL OR g.contract = m.access_contract)
          AND (NOT p_scoped OR (
                   (g.zone_key IS NULL OR (g.zone_key = p_zone AND p_zone_status = 'assigned'))
               AND (g.year_min IS NULL OR p_year >= g.year_min)
               AND (g.year_max IS NULL OR p_year <= g.year_max)))
    )
$$;

REVOKE ALL ON FUNCTION warehouse.is_unrestricted(), warehouse.row_allowed(bigint, text, text, integer, boolean) FROM PUBLIC;
-- Policy expressions run with the caller's privileges, so readers need EXECUTE.
-- Both functions only evaluate the caller's own grants (session_user).
GRANT EXECUTE ON FUNCTION warehouse.is_unrestricted(), warehouse.row_allowed(bigint, text, text, integer, boolean)
    TO warehouse_data_owner, warehouse_all_access, warehouse_explore_reader;

-- Enroll an existing login role as a scoped reader: it can query the explore
-- surface and sees only what access_grant gives it.
CREATE OR REPLACE FUNCTION warehouse.enroll_access_role(p_role name)
RETURNS void LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_role AND (rolsuper OR rolbypassrls)) THEN
        RAISE EXCEPTION 'role % bypasses row security and cannot be a scoped reader', p_role;
    END IF;
    IF pg_has_role(p_role, 'warehouse_all_access', 'member') THEN
        RAISE EXCEPTION 'role % is a member of warehouse_all_access and would see every row', p_role;
    END IF;
    EXECUTE format('GRANT warehouse_explore_reader TO %I', p_role);
    EXECUTE format('ALTER ROLE %I SET default_transaction_read_only = on', p_role);
    EXECUTE format('ALTER ROLE %I SET statement_timeout = ''30s''', p_role);
END
$$;
REVOKE ALL ON FUNCTION warehouse.enroll_access_role(name) FROM PUBLIC;

-- One policy per table. Parents filter on their own source, contract, zone and
-- year; children inherit what their parents allow, so a hidden sample hides its
-- objects, bins and links. Tables with an own dataset_version_id also need that
-- version's source and contract.
DO $$
DECLARE
    spec record;
    version_ok text;
BEGIN
    FOR spec IN SELECT * FROM (VALUES
        ('ecotaxa_project',
         'warehouse.row_allowed(dataset_version_id, NULL, NULL, NULL, false)'),
        ('ecotaxa_sample',
         'warehouse.row_allowed(dataset_version_id, marine_zone_key, marine_zone_assignment_status, '
         'extract(year FROM datetime_min AT TIME ZONE ''UTC'')::integer)'),
        ('uvp_profile',
         'warehouse.row_allowed(dataset_version_id, marine_zone_key, marine_zone_assignment_status, '
         'extract(year FROM sampled_at AT TIME ZONE ''UTC'')::integer)'),
        ('ctd_profile',
         'warehouse.row_allowed(dataset_version_id, NULL, NULL, '
         'extract(year FROM sampled_at AT TIME ZONE ''UTC'')::integer)'),
        ('filet_sample',
         'warehouse.row_allowed(dataset_version_id, marine_zone_key, marine_zone_assignment_status, sampling_year)'),
        ('filet_analysis',
         'EXISTS (SELECT 1 FROM warehouse.filet_sample p WHERE p.id = filet_analysis.sample_ref)'),
        ('filet_sample_net',
         'EXISTS (SELECT 1 FROM warehouse.filet_sample p WHERE p.id = filet_sample_net.sample_ref)'),
        ('filet_abundance',
         'warehouse.row_allowed(dataset_version_id, NULL, NULL, NULL, false) AND ('
         'EXISTS (SELECT 1 FROM warehouse.filet_analysis a '
         'WHERE a.dataset_version_id = filet_abundance.metadata_dataset_version_id '
         'AND a.sample_id = filet_abundance.sample_id AND a.analysis_id = filet_abundance.analysis_id) '
         'OR (metadata_dataset_version_id IS NULL AND warehouse.row_allowed(dataset_version_id, NULL, NULL, NULL)))'),
        ('ecotaxa_object',
         'EXISTS (SELECT 1 FROM warehouse.ecotaxa_sample p WHERE p.id = ecotaxa_object.sample_id)'),
        ('uvp_bin',
         'EXISTS (SELECT 1 FROM warehouse.uvp_profile p WHERE p.id = uvp_bin.profile_id)'),
        ('uvp_particle',
         'EXISTS (SELECT 1 FROM warehouse.uvp_bin p WHERE p.id = uvp_particle.bin_id)'),
        ('uvp_object_bin',
         'EXISTS (SELECT 1 FROM warehouse.uvp_bin p WHERE p.id = uvp_object_bin.uvp_bin_id) '
         'AND EXISTS (SELECT 1 FROM warehouse.ecotaxa_object o WHERE o.id = uvp_object_bin.ecotaxa_object_id)'),
        ('uvp_taxon_abundance',
         'warehouse.row_allowed(dataset_version_id, NULL, NULL, NULL, false) '
         'AND EXISTS (SELECT 1 FROM warehouse.uvp_profile p WHERE p.id = uvp_taxon_abundance.profile_id)'),
        ('ecopart_bin_source',
         'EXISTS (SELECT 1 FROM warehouse.uvp_bin p WHERE p.id = ecopart_bin_source.bin_id)'),
        ('ecopart_project_import',
         'warehouse.row_allowed(dataset_version_id, NULL, NULL, NULL, false)'),
        ('ecopart_auxiliary_row',
         'warehouse.row_allowed(dataset_version_id, NULL, NULL, NULL)'),
        ('ctd_measurement',
         'EXISTS (SELECT 1 FROM warehouse.ctd_profile p WHERE p.id = ctd_measurement.profile_id)'),
        ('uvp_ecotaxa',
         'EXISTS (SELECT 1 FROM warehouse.uvp_profile p WHERE p.id = uvp_ecotaxa.uvp_profile_id) '
         'AND EXISTS (SELECT 1 FROM warehouse.ecotaxa_sample s WHERE s.id = uvp_ecotaxa.ecotaxa_sample_id)'),
        ('uvp_ctd',
         'EXISTS (SELECT 1 FROM warehouse.uvp_profile p WHERE p.id = uvp_ctd.uvp_profile_id) '
         'AND EXISTS (SELECT 1 FROM warehouse.ctd_profile c WHERE c.id = uvp_ctd.ctd_profile_id)'),
        ('ecotaxa_ctd',
         'EXISTS (SELECT 1 FROM warehouse.ecotaxa_sample s WHERE s.id = ecotaxa_ctd.ecotaxa_sample_id) '
         'AND EXISTS (SELECT 1 FROM warehouse.ctd_profile c WHERE c.id = ecotaxa_ctd.ctd_profile_id)'),
        ('filet_ecotaxa',
         'EXISTS (SELECT 1 FROM warehouse.filet_analysis a WHERE a.id = filet_ecotaxa.filet_analysis_id) '
         'AND EXISTS (SELECT 1 FROM warehouse.ecotaxa_sample s WHERE s.id = filet_ecotaxa.ecotaxa_sample_id)'),
        ('filet_ctd',
         'EXISTS (SELECT 1 FROM warehouse.filet_sample f WHERE f.id = filet_ctd.filet_sample_id) '
         'AND EXISTS (SELECT 1 FROM warehouse.ctd_profile c WHERE c.id = filet_ctd.ctd_profile_id)'),
        ('filet_uvp_match',
         'warehouse.row_allowed(dataset_version_id, NULL, NULL, NULL, false) '
         'AND EXISTS (SELECT 1 FROM warehouse.filet_sample f WHERE f.id = filet_uvp_match.filet_sample_id) '
         'AND EXISTS (SELECT 1 FROM warehouse.uvp_profile u WHERE u.id = filet_uvp_match.uvp_profile_id)')
    ) AS t(table_name, expression)
    LOOP
        EXECUTE format('ALTER TABLE warehouse.%I OWNER TO warehouse_data_owner', spec.table_name);
        EXECUTE format('ALTER TABLE warehouse.%I ENABLE ROW LEVEL SECURITY', spec.table_name);
        EXECUTE format('ALTER TABLE warehouse.%I FORCE ROW LEVEL SECURITY', spec.table_name);
        EXECUTE format('DROP POLICY IF EXISTS access_scope ON warehouse.%I', spec.table_name);
        EXECUTE format(
            'CREATE POLICY access_scope ON warehouse.%I FOR ALL USING ((SELECT warehouse.is_unrestricted()) OR (%s))',
            spec.table_name, spec.expression);
    END LOOP;
END
$$;

-- Everything else in the schema belongs to the data owner too, so the views
-- (which run with their owner's rights) are filtered like the tables.
DO $$
DECLARE
    item record;
BEGIN
    FOR item IN
        SELECT n.nspname, c.relname, c.relkind
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('warehouse', 'explore') AND c.relkind IN ('r', 'v')
          AND pg_get_userbyid(c.relowner) <> 'warehouse_data_owner'
    LOOP
        EXECUTE format('ALTER %s %I.%I OWNER TO warehouse_data_owner',
                       CASE item.relkind WHEN 'v' THEN 'VIEW' ELSE 'TABLE' END, item.nspname, item.relname);
    END LOOP;
END
$$;
ALTER FUNCTION warehouse.is_unrestricted() OWNER TO warehouse_data_owner;
ALTER FUNCTION warehouse.row_allowed(bigint, text, text, integer, boolean) OWNER TO warehouse_data_owner;

-- What the calling role may read, so a user can see its own scope.
CREATE OR REPLACE VIEW explore.my_access AS
SELECT 'all data'::text AS grantee, NULL::text AS source_instance, NULL::text AS contract,
       NULL::text AS zone_key, NULL::integer AS year_min, NULL::integer AS year_max,
       'member of warehouse_all_access'::text AS note, NULL::timestamptz AS granted_at
WHERE warehouse.is_unrestricted()
UNION ALL
SELECT g.grantee::text, g.source_instance, g.contract, g.zone_key, g.year_min, g.year_max,
       g.note, g.granted_at
FROM warehouse.access_grant g
JOIN pg_roles r ON r.rolname = g.grantee
WHERE g.revoked_at IS NULL AND pg_has_role(session_user, r.oid, 'member');
ALTER VIEW explore.my_access OWNER TO warehouse_data_owner;
COMMENT ON VIEW explore.my_access IS
    'Périmètre de lecture du rôle connecté: source, contrat, zone et années autorisés. Aucune ligne = aucun accès.';

-- Gaps that would silently bypass the filter: a table with no row security that
-- is not a catalog, and a view over a protected table that does not run as the
-- data owner (typically one created later by the loader).
CREATE OR REPLACE VIEW explore.access_audit AS
SELECT 'table without row security'::text AS problem, c.relname::text AS object_name
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'warehouse' AND c.relkind = 'r' AND NOT c.relrowsecurity
  AND c.relname NOT IN ('dataset_version', 'dataset_metadata', 'dataset_file', 'column_metadata',
                        'validation_run', 'taxon_mapping', 'ctd_variable', 'access_grant')
UNION ALL
SELECT DISTINCT 'view bypasses row security', v.relname::text
FROM pg_class v
JOIN pg_namespace vn ON vn.oid = v.relnamespace AND vn.nspname = 'explore'
JOIN pg_rewrite rw ON rw.ev_class = v.oid
JOIN pg_depend d ON d.objid = rw.oid AND d.classid = 'pg_rewrite'::regclass
JOIN pg_class t ON t.oid = d.refobjid AND t.relrowsecurity
WHERE v.relkind = 'v' AND v.relname <> 'access_audit'
  AND pg_get_userbyid(v.relowner) <> 'warehouse_data_owner';
ALTER VIEW explore.access_audit OWNER TO warehouse_data_owner;
COMMENT ON VIEW explore.access_audit IS
    'Écarts du contrôle d''accès: table sans RLS ou vue qui la contourne. Doit être vide.';
