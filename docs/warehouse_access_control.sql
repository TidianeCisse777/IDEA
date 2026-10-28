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
-- A bounded grant hides rows whose zone or date is unknown, unless the admin
-- explicitly includes them for that grant.
ALTER TABLE warehouse.access_grant
    ADD COLUMN IF NOT EXISTS include_unknown_scope boolean NOT NULL DEFAULT false;
COMMENT ON TABLE warehouse.access_grant IS
    'Droits de lecture par rôle. NULL = sans restriction sur cette dimension. include_unknown_scope = inclure les lignes à zone non attribuée (ambiguous, unresolved, absente) ou sans date. Révoquer = renseigner revoked_at (historique conservé).';

CREATE INDEX IF NOT EXISTS access_grant_active_idx
    ON warehouse.access_grant (grantee) WHERE revoked_at IS NULL;

CREATE OR REPLACE FUNCTION warehouse.is_unrestricted()
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog
AS $$ SELECT pg_has_role(session_user, 'warehouse_all_access', 'member') $$;

-- p_scoped = false checks source and contract only (tables with no row-level
-- zone or year). A zone grant requires an 'assigned' zone; a year grant requires
-- a known year. Rows of unknown zone (ambiguous, unresolved, absent) or unknown
-- year are visible to such a grant only when it sets include_unknown_scope.
-- 'outside' is a known zone (outside the registry) and never matches a zone.
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
                   (g.zone_key IS NULL
                    OR (g.zone_key = p_zone AND p_zone_status = 'assigned')
                    OR (g.include_unknown_scope AND coalesce(p_zone_status, 'unresolved') IN ('ambiguous', 'unresolved')))
               AND ((g.year_min IS NULL AND g.year_max IS NULL)
                    OR (p_year IS NOT NULL AND (g.year_min IS NULL OR p_year >= g.year_min)
                                           AND (g.year_max IS NULL OR p_year <= g.year_max))
                    OR (g.include_unknown_scope AND p_year IS NULL))))
    )
$$;

-- Versions the caller may read, computed once per query and probed by hash.
-- Tables with no row-level zone or year use it instead of row_allowed(...,
-- false), which ran once per row (18 s on 600 000 abundance rows).
-- p_unknown_scope = true keeps only versions where a matching grant also covers
-- rows of unknown zone or year (unbounded, or include_unknown_scope).
CREATE OR REPLACE FUNCTION warehouse.readable_versions(p_unknown_scope boolean DEFAULT false)
RETURNS SETOF bigint LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, warehouse
AS $$
    SELECT DISTINCT v.id
    FROM warehouse.dataset_version v
    LEFT JOIN warehouse.dataset_metadata m ON m.dataset_version_id = v.id
    JOIN warehouse.access_grant g
      ON g.revoked_at IS NULL
     AND (g.source_instance IS NULL OR g.source_instance = v.source_instance)
     AND (g.contract IS NULL OR g.contract = m.access_contract)
    JOIN pg_roles r ON r.rolname = g.grantee
    WHERE pg_has_role(session_user, r.oid, 'member')
      AND (NOT p_unknown_scope OR g.include_unknown_scope
           OR (g.zone_key IS NULL AND g.year_min IS NULL AND g.year_max IS NULL))
$$;

REVOKE ALL ON FUNCTION warehouse.is_unrestricted(), warehouse.row_allowed(bigint, text, text, integer, boolean),
    warehouse.readable_versions(boolean) FROM PUBLIC;
-- Policy expressions run with the caller's privileges, so readers need EXECUTE.
-- These functions only evaluate the caller's own grants (session_user).
GRANT EXECUTE ON FUNCTION warehouse.is_unrestricted(), warehouse.row_allowed(bigint, text, text, integer, boolean),
    warehouse.readable_versions(boolean)
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
    -- Same planner setting as warehouse_reader (see warehouse_roles.sql).
    EXECUTE format('ALTER ROLE %I SET enable_mergejoin = off', p_role);
END
$$;
REVOKE ALL ON FUNCTION warehouse.enroll_access_role(name) FROM PUBLIC;

-- Accounts enrolled before a settings change get it on the next deploy too.
DO $$
DECLARE
    member record;
BEGIN
    FOR member IN
        SELECT r.rolname FROM pg_auth_members a
        JOIN pg_roles g ON g.oid = a.roleid AND g.rolname = 'warehouse_explore_reader'
        JOIN pg_roles r ON r.oid = a.member AND r.rolcanlogin
    LOOP
        BEGIN
            EXECUTE format('ALTER ROLE %I SET default_transaction_read_only = on', member.rolname);
            EXECUTE format('ALTER ROLE %I SET statement_timeout = ''30s''', member.rolname);
            EXECUTE format('ALTER ROLE %I SET enable_mergejoin = off', member.rolname);
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE WARNING 'settings not updated for role % (needs CREATEROLE with ADMIN on it)', member.rolname;
        END;
    END LOOP;
END
$$;

-- One policy per table. Parents filter on their own source, contract, zone and
-- year; children inherit what their parents allow, so a hidden sample hides its
-- objects, bins and links. Tables with an own dataset_version_id also need that
-- version's source and contract.
-- Children use an uncorrelated `fk IN (SELECT id FROM parent)`: PostgreSQL builds
-- the set of visible parents once and probes it by hash. A correlated EXISTS
-- re-evaluated the parent's policy for every child row (millions of objects)
-- and timed out at 30 s for scoped accounts. The one exception is a parent set
-- too large to hash (objects), probed by index.
DO $$
DECLARE
    spec record;
BEGIN
    FOR spec IN SELECT * FROM (VALUES
        ('ecotaxa_project',
         'dataset_version_id IN (SELECT warehouse.readable_versions())'),
        ('ecotaxa_sample',
         'warehouse.row_allowed(dataset_version_id, marine_zone_key, marine_zone_assignment_status, '
         'extract(year FROM datetime_min AT TIME ZONE ''UTC'')::integer)'),
        ('uvp_profile',
         'warehouse.row_allowed(dataset_version_id, marine_zone_key, marine_zone_assignment_status, '
         'extract(year FROM sampled_at AT TIME ZONE ''UTC'')::integer)'),
        ('ctd_profile',
         'warehouse.row_allowed(dataset_version_id, marine_zone_key, marine_zone_assignment_status, '
         'extract(year FROM sampled_at AT TIME ZONE ''UTC'')::integer)'),
        ('filet_sample',
         'warehouse.row_allowed(dataset_version_id, marine_zone_key, marine_zone_assignment_status, sampling_year)'),
        ('filet_analysis',
         'sample_ref IN (SELECT id FROM warehouse.filet_sample)'),
        ('filet_sample_net',
         'sample_ref IN (SELECT id FROM warehouse.filet_sample)'),
        ('filet_abundance',
         'dataset_version_id IN (SELECT warehouse.readable_versions()) AND ('
         '(metadata_dataset_version_id, sample_id, analysis_id) IN '
         '(SELECT dataset_version_id, sample_id, analysis_id FROM warehouse.filet_analysis) '
         'OR (metadata_dataset_version_id IS NULL AND dataset_version_id IN (SELECT warehouse.readable_versions(true))))'),
        ('ecotaxa_object',
         'sample_id IN (SELECT id FROM warehouse.ecotaxa_sample)'),
        ('uvp_bin',
         'profile_id IN (SELECT id FROM warehouse.uvp_profile)'),
        ('uvp_particle',
         'bin_id IN (SELECT id FROM warehouse.uvp_bin)'),
        -- Millions of objects do not fit in a hash: probe the object by index
        -- instead; its own policy is the hashed set of visible samples.
        ('uvp_object_bin',
         'uvp_bin_id IN (SELECT id FROM warehouse.uvp_bin) '
         'AND EXISTS (SELECT 1 FROM warehouse.ecotaxa_object o WHERE o.id = uvp_object_bin.ecotaxa_object_id)'),
        ('uvp_taxon_abundance',
         'dataset_version_id IN (SELECT warehouse.readable_versions()) '
         'AND profile_id IN (SELECT id FROM warehouse.uvp_profile)'),
        ('ecopart_bin_source',
         'bin_id IN (SELECT id FROM warehouse.uvp_bin)'),
        ('ecopart_project_import',
         'dataset_version_id IN (SELECT warehouse.readable_versions())'),
        ('ecopart_auxiliary_row',
         'dataset_version_id IN (SELECT warehouse.readable_versions(true))'),
        ('ctd_measurement',
         'profile_id IN (SELECT id FROM warehouse.ctd_profile)'),
        ('uvp_ecotaxa',
         'uvp_profile_id IN (SELECT id FROM warehouse.uvp_profile) '
         'AND ecotaxa_sample_id IN (SELECT id FROM warehouse.ecotaxa_sample)'),
        ('uvp_ctd',
         'uvp_profile_id IN (SELECT id FROM warehouse.uvp_profile) '
         'AND ctd_profile_id IN (SELECT id FROM warehouse.ctd_profile)'),
        ('ecotaxa_ctd',
         'ecotaxa_sample_id IN (SELECT id FROM warehouse.ecotaxa_sample) '
         'AND ctd_profile_id IN (SELECT id FROM warehouse.ctd_profile)'),
        ('filet_ecotaxa',
         'filet_analysis_id IN (SELECT id FROM warehouse.filet_analysis) '
         'AND ecotaxa_sample_id IN (SELECT id FROM warehouse.ecotaxa_sample)'),
        ('filet_ctd',
         'filet_sample_id IN (SELECT id FROM warehouse.filet_sample) '
         'AND ctd_profile_id IN (SELECT id FROM warehouse.ctd_profile)'),
        ('filet_uvp_match',
         'dataset_version_id IN (SELECT warehouse.readable_versions()) '
         'AND filet_sample_id IN (SELECT id FROM warehouse.filet_sample) '
         'AND uvp_profile_id IN (SELECT id FROM warehouse.uvp_profile)')
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
ALTER FUNCTION warehouse.readable_versions(boolean) OWNER TO warehouse_data_owner;

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

-- What each dataset version means for the calling role: full, partial or no
-- access, why, and whether a paired source is missing. It tells "hidden" from
-- "absent" at version level without exposing any row count.
CREATE OR REPLACE VIEW explore.my_datasets AS
WITH mine AS (
    SELECT g.*
    FROM warehouse.access_grant g
    JOIN pg_roles r ON r.rolname = g.grantee
    WHERE g.revoked_at IS NULL AND pg_has_role(session_user, r.oid, 'member')
), per_version AS (
    SELECT v.id, v.source_instance, v.dataset_key, v.version_key, m.title, m.access_contract,
           warehouse.is_unrestricted() AS unrestricted,
           bool_or(g.id IS NOT NULL) AS any_grant,
           bool_or(g.id IS NOT NULL AND g.zone_key IS NULL AND g.year_min IS NULL AND g.year_max IS NULL) AS unbounded,
           bool_or(coalesce(g.include_unknown_scope, false)) AS unknown_included,
           bool_or(g.zone_key IS NOT NULL) AS zone_bounded,
           bool_or(g.year_min IS NOT NULL OR g.year_max IS NOT NULL) AS year_bounded,
           string_agg(DISTINCT nullif(concat_ws(', ',
               'zone ' || g.zone_key,
               CASE WHEN g.year_min IS NOT NULL OR g.year_max IS NOT NULL
                    THEN 'années ' || coalesce(g.year_min::text, '…') || '–' || coalesce(g.year_max::text, '…') END), ''), '; ') AS bounds
    FROM warehouse.dataset_version v
    LEFT JOIN warehouse.dataset_metadata m ON m.dataset_version_id = v.id
    LEFT JOIN mine g ON (g.source_instance IS NULL OR g.source_instance = v.source_instance)
                    AND (g.contract IS NULL OR g.contract = m.access_contract)
    GROUP BY v.id, v.source_instance, v.dataset_key, v.version_key, m.title, m.access_contract
)
SELECT p.id AS dataset_version_id, p.source_instance, p.dataset_key, p.version_key, p.title, p.access_contract,
       CASE WHEN p.unrestricted OR p.unbounded THEN 'complet'
            WHEN p.any_grant THEN 'partiel'
            ELSE 'aucun' END AS my_scope,
       CASE WHEN p.unrestricted OR p.unbounded THEN 'toutes les lignes de cette version'
            WHEN p.any_grant THEN p.bounds || coalesce('; ' || nullif(concat_ws(' et ',
                CASE WHEN p.zone_bounded THEN 'lignes à zone non attribuée' END,
                CASE WHEN p.year_bounded THEN 'lignes sans date' END), '')
                || CASE WHEN p.unknown_included THEN ' incluses' ELSE ' exclues' END, '')
            ELSE 'aucun droit sur cette source et ce contrat: données masquées, pas absentes' END AS scope_detail,
       CASE WHEN p.source_instance IN ('ecotaxa', 'ecopart') AND (p.unrestricted OR p.any_grant)
             AND NOT EXISTS (SELECT 1 FROM per_version o
                             WHERE o.source_instance = CASE p.source_instance WHEN 'ecotaxa' THEN 'ecopart' ELSE 'ecotaxa' END
                               AND (o.unrestricted OR o.any_grant))
            THEN 'Les vues UVP joignent EcoTaxa et EcoPart: sans droit sur '
                 || CASE p.source_instance WHEN 'ecotaxa' THEN 'ecopart' ELSE 'ecotaxa' END
                 || ', elles restent vides pour ce compte.' END AS note
FROM per_version p;
ALTER VIEW explore.my_datasets OWNER TO warehouse_data_owner;
COMMENT ON VIEW explore.my_datasets IS
    'Pour chaque version de jeu de données: accès complet, partiel ou aucun pour le compte connecté, la raison, et une note si une source associée manque. Distingue « masqué » de « absent » sans compter les lignes.';

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
