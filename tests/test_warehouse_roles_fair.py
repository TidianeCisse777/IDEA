"""Contrats des rôles PostgreSQL et des exigences FAIR du warehouse.

Les tests statiques lisent le SQL. Les tests live créent une base temporaire,
y déploient le warehouse avec scripts/deploy_warehouse_postgres.py puis la
suppriment. Ils s'activent avec WAREHOUSE_TEST_LIVE=1 et les variables PG*
(PGHOST, PGPORT, PGUSER, PGPASSWORD) d'un rôle pouvant créer une base.
"""

import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ROLES = (DOCS / "warehouse_roles.sql").read_text(encoding="utf-8")
FAIR = (DOCS / "warehouse_fair_migration.sql").read_text(encoding="utf-8")
ACCESS = (DOCS / "warehouse_access_control.sql").read_text(encoding="utf-8")
DEPLOY = ROOT / "scripts" / "deploy_warehouse_postgres.py"
COMPOSE = (ROOT / "docker-compose.warehouse.yml").read_text(encoding="utf-8")


class RolesContractTests(unittest.TestCase):
    def test_read_roles_cannot_write_or_escalate(self):
        for attribute in ("NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOREPLICATION", "NOBYPASSRLS"):
            self.assertIn(attribute, ROLES)
        for role in ("warehouse_reader", "warehouse_navigator"):
            self.assertIn(f"ALTER ROLE {role} SET default_transaction_read_only = on", ROLES)
            self.assertIn(f"ALTER ROLE {role} SET statement_timeout = '30s'", ROLES)
        self.assertNotRegex(ROLES, r"GRANT\s+(INSERT|UPDATE|DELETE|ALL)[^;]*TO[^;]*warehouse_(reader|navigator)")

    def test_reader_is_limited_to_the_explore_schema(self):
        self.assertIn("REVOKE ALL ON SCHEMA warehouse FROM warehouse_reader", ROLES)
        self.assertNotRegex(ROLES, r"GRANT USAGE ON SCHEMA warehouse TO[^;]*warehouse_reader")

    def test_passwords_come_from_the_environment_not_the_file(self):
        self.assertIn("\\getenv reader_password WAREHOUSE_READER_PASSWORD", ROLES)
        self.assertNotRegex(ROLES, r"PASSWORD\s+'[^']+'")

    def test_compose_does_not_hand_the_owner_role_to_the_navigator(self):
        navigator = COMPOSE.split("warehouse-navigator:")[1].split("volumes:")[0]
        self.assertIn("warehouse_navigator", navigator)
        self.assertNotIn("WAREHOUSE_POSTGRES_USER:-neolab", navigator)

    def test_compose_publishes_ports_on_the_local_machine_only_by_default(self):
        import yaml
        services = yaml.safe_load(COMPOSE)["services"]
        for name in ("neolab-warehouse-db", "warehouse-navigator"):
            for port in services[name]["ports"]:
                self.assertTrue(port.startswith("${WAREHOUSE_BIND_ADDRESS:-127.0.0.1}:"), (name, port))

    def test_compose_initializes_every_ddl_then_roles_in_order(self):
        order = [m for m in re.findall(r"/docker-entrypoint-initdb\.d/(\d+_[\w.]+)", COMPOSE)]
        self.assertEqual(order, sorted(order))
        self.assertTrue(order[-1].endswith("roles.sh"))
        for fragment in ("warehouse_ecopart_migration", "warehouse_fair_migration"):
            self.assertIn(fragment, COMPOSE)


class FairContractTests(unittest.TestCase):
    def test_migration_is_additive_and_replayable(self):
        self.assertNotRegex(FAIR, r"(?i)\b(DROP\s+(TABLE|COLUMN)|DELETE\s+FROM|TRUNCATE|UPDATE\s+warehouse)\b")
        self.assertNotRegex(FAIR, r"(?m)^CREATE (TABLE|VIEW|INDEX|UNIQUE INDEX)\s+(?!IF NOT EXISTS|OR REPLACE)")
        self.assertNotRegex(FAIR, r"ADD COLUMN\s+(?!IF NOT EXISTS)")

    def test_each_fair_letter_has_a_measured_criterion(self):
        for criterion in ("f1_persistent_identifier", "f2_rich_metadata", "f4_searchable",
                          "a1_access_declared", "i1_standard_declared", "i3_related_references",
                          "r1_license", "r2_provenance", "r3_validated"):
            self.assertIn(criterion, FAIR)

    def test_catalog_hides_file_locations(self):
        catalog = FAIR.split("explore.dataset_catalog AS")[1].split(";")[0]
        self.assertNotIn("source_uri", catalog)
        self.assertNotIn("file_manifest_uri", catalog)


class AccessControlContractTests(unittest.TestCase):
    def test_every_protected_table_forces_row_security(self):
        policies = ACCESS.split("FOR spec IN SELECT * FROM (VALUES")[1].split(") AS t(table_name")[0]
        tables = re.findall(r"\('(\w+)',\n", policies)
        self.assertGreaterEqual(len(tables), 23)
        self.assertIn("FORCE ROW LEVEL SECURITY", ACCESS)
        self.assertIn("OWNER TO warehouse_data_owner", ACCESS)

    def test_identity_is_the_login_role_never_the_view_owner(self):
        self.assertIn("session_user", ACCESS)
        functions = ACCESS.split("CREATE OR REPLACE FUNCTION warehouse.is_unrestricted")[1].split("REVOKE ALL ON FUNCTION")[0]
        self.assertTrue("current_user" not in functions.lower(), "policy functions must key on session_user")
        self.assertIn("p_zone_status = 'assigned'", ACCESS)

    def test_scoped_readers_cannot_be_superusers_or_all_access_members(self):
        self.assertIn("rolsuper OR rolbypassrls", ACCESS)
        self.assertIn("warehouse_all_access", ACCESS)

    def test_child_policies_are_set_based_except_for_objects(self):
        self.assertGreaterEqual(ACCESS.count("IN (SELECT id FROM warehouse."), 20)
        policies = ACCESS.split("FOR spec IN SELECT * FROM (VALUES")[1].split(") AS t(table_name")[0]
        correlated = re.findall(r"EXISTS \(SELECT 1 FROM warehouse\.(\w+)", policies)
        self.assertEqual(correlated, ["ecotaxa_object"], "only the unhashable object set is probed by index")
        self.assertIn("warehouse.readable_versions()", ACCESS)
        self.assertNotIn("row_allowed(dataset_version_id, NULL, NULL, NULL, false)", ACCESS)

    def test_ctd_profiles_are_filtered_on_their_own_zone(self):
        policy = ACCESS.split("('ctd_profile',")[1].split("),")[0]
        self.assertIn("marine_zone_key, marine_zone_assignment_status", policy)
        self.assertIn("warehouse_ctd_zone_migration", COMPOSE)
        self.assertIn("warehouse_ctd_zone_migration.sql", DEPLOY.read_text(encoding="utf-8"))

    def test_unknown_scope_is_opt_in_and_my_datasets_has_no_counts(self):
        self.assertIn("include_unknown_scope boolean NOT NULL DEFAULT false", ACCESS)
        view = ACCESS.split("CREATE OR REPLACE VIEW explore.my_datasets AS")[1].split("ALTER VIEW")[0]
        self.assertNotRegex(view, r"(?i)count\(")

    def test_compose_publishes_the_mcp_context_once_the_database_is_ready(self):
        service = COMPOSE.split("warehouse-context:")[1].split("warehouse-navigator:")[0]
        self.assertIn("publish_warehouse_context.py", service)
        self.assertIn("condition: service_healthy", service)
        self.assertIn("pg_isready -h 127.0.0.1", COMPOSE)

    def test_new_explore_views_are_adopted_at_creation_when_possible(self):
        self.assertIn("CREATE EVENT TRIGGER warehouse_adopt_explore_views ON ddl_command_end", ACCESS)
        self.assertIn("WHEN TAG IN ('CREATE VIEW')", ACCESS)
        self.assertIn("EXCEPTION WHEN insufficient_privilege", ACCESS.split("adopt_new_explore_views()")[1])

    def test_agent_read_roles_disable_merge_joins(self):
        self.assertIn("ALTER ROLE warehouse_reader SET enable_mergejoin = off", ROLES)
        self.assertIn("SET enable_mergejoin = off", ACCESS)
        self.assertIn("Accounts enrolled before a settings change get it on the next deploy", ACCESS)

    def test_no_psql_meta_commands_so_psycopg_can_apply_it(self):
        self.assertNotRegex(ACCESS, r"(?m)^\\")

    def test_grants_are_revoked_not_deleted(self):
        self.assertIn("revoked_at timestamptz", ACCESS)
        self.assertNotRegex(ACCESS, r"(?i)DELETE\s+FROM\s+warehouse\.access_grant")

    def test_roles_file_requires_the_access_file_first(self):
        self.assertIn("apply docs/warehouse_access_control.sql before", ROLES)
        names = re.findall(r"/docker-entrypoint-initdb\.d/(\d+_\w+)", COMPOSE)
        self.assertLess(names.index("009_warehouse_access"), names.index("010_warehouse_roles"))


class ReleaseContractTests(unittest.TestCase):
    def deploy_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("deploy_warehouse_postgres", DEPLOY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_release_number_has_a_single_source(self):
        module = self.deploy_module()
        self.assertRegex(module.release_version(), r"^\d+\.\d+\.\d+$")
        self.assertNotIn(module.release_version(), DEPLOY.read_text(encoding="utf-8"))
        self.assertIn(module.release_version(), (DOCS / "WAREHOUSE_RELEASE_V1.md").read_text(encoding="utf-8"))

    def test_manifest_hashes_every_release_file(self):
        import hashlib
        manifest = self.deploy_module().release_manifest()
        names = [entry["file"] for entry in manifest]
        self.assertEqual(names[-2:], ["warehouse_roles.sql", "warehouse_release.sql"])
        for entry in manifest:
            self.assertEqual(entry["sha256"], hashlib.sha256((DOCS / entry["file"]).read_bytes()).hexdigest())

    def test_docker_init_records_the_release_after_roles(self):
        self.assertIn("warehouse_release.sql:/opt/warehouse/warehouse_release.sql", COMPOSE)
        hook = (ROOT / "docker" / "warehouse_init_roles.sh").read_text(encoding="utf-8")
        self.assertLess(hook.index("warehouse_roles.sql"), hook.index("-f /opt/warehouse/warehouse_release.sql"))
        self.assertIn("method=docker-init", hook)

    def test_verify_mode_changes_nothing(self):
        source = DEPLOY.read_text(encoding="utf-8")
        verify = source.split("if args.verify:")[1].split("deploy(env")[0]
        self.assertIn("return check(env)", verify)


class DeployScriptTests(unittest.TestCase):
    def test_owner_password_is_required_and_never_on_argv(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("WAREHOUSE_", "PG"))}
        result = subprocess.run([sys.executable, str(DEPLOY), "--dry-run"], env=env,
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WAREHOUSE_POSTGRES_PASSWORD", result.stderr)
        source = DEPLOY.read_text(encoding="utf-8")
        self.assertNotIn("'-v', f", source)
        self.assertNotRegex(source, r"password\s*=\s*['\"][^'\"]+['\"]")


@unittest.skipUnless(os.environ.get("WAREHOUSE_TEST_LIVE") == "1", "WAREHOUSE_TEST_LIVE=1 requis")
class LivePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = "fair_test_" + uuid.uuid4().hex[:8]
        cls.owner_env = dict(os.environ)
        cls.admin("postgres", f"CREATE DATABASE {cls.db}")
        env = dict(os.environ, WAREHOUSE_POSTGRES_HOST=os.environ.get("PGHOST", "127.0.0.1"),
                   WAREHOUSE_POSTGRES_PORT=os.environ.get("PGPORT", "5432"),
                   WAREHOUSE_POSTGRES_DB=cls.db,
                   WAREHOUSE_POSTGRES_USER=os.environ.get("PGUSER", "neolab"),
                   WAREHOUSE_POSTGRES_PASSWORD=os.environ.get("PGPASSWORD", "unused"),
                   WAREHOUSE_READER_PASSWORD="reader-pw", WAREHOUSE_NAVIGATOR_PASSWORD="navigator-pw")
        cls.deploy_env = env
        cls.deploy_result = subprocess.run([sys.executable, str(DEPLOY)], env=env,
                                           capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        # Roles are cluster-wide: release what they own here, then drop them.
        tag = getattr(cls, "tag", None)
        if tag:
            for name in ("scoped", "empty"):
                cls.admin(cls.db, f"DROP OWNED BY acl_{name}_{tag}")
        cls.admin("postgres", f"DROP DATABASE IF EXISTS {cls.db} WITH (FORCE)")
        if tag:
            for name in ("scoped", "empty"):
                cls.admin("postgres", f"DROP ROLE IF EXISTS acl_{name}_{tag}")

    @classmethod
    def admin(cls, db, sql):
        subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", db, "-c", sql],
                       env=cls.owner_env, check=True, capture_output=True, text=True)

    def run_as(self, user, sql, password=None):
        env = dict(self.owner_env)
        if password:
            env["PGPASSWORD"] = password
        result = subprocess.run(["psql", "-X", "-At", "-d", self.db, "-U", user, "-c", sql],
                                env=env, capture_output=True, text=True)
        return result.returncode, (result.stdout + result.stderr).strip()

    def owner(self, sql):
        code, output = self.run_as(os.environ.get("PGUSER", "neolab"), sql)
        return code, output

    def test_00_deploy_succeeds_and_replays(self):
        self.assertEqual(self.deploy_result.returncode, 0, self.deploy_result.stderr)
        replay = subprocess.run([sys.executable, str(DEPLOY)], env=self.deploy_env,
                                capture_output=True, text=True)
        self.assertEqual(replay.returncode, 0, replay.stderr)

    def test_reader_reads_explore_only(self):
        code, out = self.run_as("warehouse_reader", "SELECT count(*) FROM explore.dataset_catalog", "reader-pw")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.isdigit(), out)
        code, out = self.run_as("warehouse_reader", "SELECT count(*) FROM warehouse.dataset_version", "reader-pw")
        self.assertNotEqual(code, 0)
        self.assertIn("permission denied", out)

    def test_read_roles_cannot_write_or_create(self):
        insert = ("INSERT INTO warehouse.dataset_version (source_instance, dataset_key, version_key, "
                  "file_manifest_uri, sha256) VALUES ('a','b','c','d','e')")
        for user, password in (("warehouse_reader", "reader-pw"), ("warehouse_navigator", "navigator-pw")):
            code, out = self.run_as(user, insert, password)
            self.assertNotEqual(code, 0, user)
            code, out = self.run_as(user, "CREATE TABLE explore.leak (a int)", password)
            self.assertNotEqual(code, 0, user)
            self.assertEqual(self.run_as(user, "SHOW default_transaction_read_only", password), (0, "on"))

    def test_navigator_reads_raw_tables(self):
        code, out = self.run_as("warehouse_navigator", "SELECT count(*) FROM warehouse.dataset_version", "navigator-pw")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.isdigit(), out)

    def test_new_owner_views_are_readable_without_regrant(self):
        self.assertEqual(self.owner("CREATE VIEW explore.later_view AS SELECT 1 AS one")[0], 0)
        self.assertEqual(self.run_as("warehouse_reader", "SELECT one FROM explore.later_view", "reader-pw"),
                         (0, "1"))

    def test_fair_readiness_reports_what_is_missing_then_passes(self):
        owner = self.owner
        owner("INSERT INTO warehouse.dataset_version (source_instance, dataset_key, version_key, "
              "file_manifest_uri, sha256) VALUES ('ecotaxa','p1','v1','uri','abc')")
        owner("INSERT INTO warehouse.dataset_metadata (dataset_version_id, title, description) "
              "SELECT id, 'T', 'D' FROM warehouse.dataset_version WHERE dataset_key='p1'")
        code, out = self.run_as("warehouse_reader",
                                "SELECT fair_ready, array_to_string(missing_criteria, ',') "
                                "FROM explore.fair_readiness WHERE dataset_key='p1'", "reader-pw")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("f|F1,F2,F4,A1,I1,I3,R1,R2,R3"), out)
        done = ("UPDATE warehouse.dataset_metadata SET persistent_identifier='doi:10.0000/x', "
                "creators_json='[{\"name\":\"A\"}]', keywords_json='[\"zooplankton\"]', access_level='open', "
                "metadata_standard='DataCite 4.5', related_identifiers_json='[{\"id\":\"x\"}]', "
                "license='CC-BY-4.0', methodology='m', software_version='1.0' WHERE title='T'")
        self.assertEqual(owner(done)[0], 0)
        owner("INSERT INTO warehouse.dataset_file (dataset_version_id, logical_name, source_uri, sha256) "
              "SELECT id, 'f', 'u', 'abc' FROM warehouse.dataset_version WHERE dataset_key='p1'")
        owner("INSERT INTO warehouse.validation_run (dataset_version_id, validator_name, started_at, status) "
              "SELECT id, 'v', now(), 'passed' FROM warehouse.dataset_version WHERE dataset_key='p1'")
        code, out = self.run_as("warehouse_reader",
                                "SELECT fair_ready FROM explore.fair_readiness WHERE dataset_key='p1'", "reader-pw")
        self.assertEqual((code, out), (0, "t"))

    def test_published_version_requires_license_and_identifier(self):
        owner = self.owner
        owner("INSERT INTO warehouse.dataset_version (source_instance, dataset_key, version_key, "
              "file_manifest_uri, sha256) VALUES ('filet','gate','v1','uri','g')")
        owner("INSERT INTO warehouse.dataset_metadata (dataset_version_id, title, description) "
              "SELECT id, 'G', 'G' FROM warehouse.dataset_version WHERE dataset_key='gate'")
        code, out = owner("UPDATE warehouse.dataset_metadata SET publication_status='published' WHERE title='G'")
        self.assertNotEqual(code, 0)
        self.assertIn("dataset_metadata_publish_gate", out)

    def test_persistent_identifier_is_unique(self):
        owner = self.owner
        for key in ("u1", "u2"):
            owner("INSERT INTO warehouse.dataset_version (source_instance, dataset_key, version_key, "
                  f"file_manifest_uri, sha256) VALUES ('ecopart','{key}','v1','uri','{key}')")
            owner("INSERT INTO warehouse.dataset_metadata (dataset_version_id, title, description) "
                  f"SELECT id, '{key}', 'D' FROM warehouse.dataset_version WHERE dataset_key='{key}'")
        self.assertEqual(owner("UPDATE warehouse.dataset_metadata SET persistent_identifier='doi:dup' WHERE title='u1'")[0], 0)
        code, out = owner("UPDATE warehouse.dataset_metadata SET persistent_identifier='doi:dup' WHERE title='u2'")
        self.assertNotEqual(code, 0)
        self.assertIn("persistent_identifier_uidx", out)

    # ---- access control -------------------------------------------------
    def seed_access_data(self):
        owner = self.owner
        tag = uuid.uuid4().hex[:6]
        type(self).tag = tag
        owner(
            "INSERT INTO warehouse.dataset_version (source_instance, dataset_key, version_key, file_manifest_uri, sha256) VALUES "
            f"('ecotaxa','acl_c1_{tag}','v1','u','1{tag}'),('ecotaxa','acl_c2_{tag}','v1','u','2{tag}'),"
            f"('filet','acl_f_{tag}','v1','u','3{tag}')")
        owner("INSERT INTO warehouse.dataset_metadata (dataset_version_id, title, description, access_contract) "
              f"SELECT id, 't', 'd', CASE WHEN dataset_key = 'acl_c2_{tag}' THEN 'C2' ELSE 'C1' END "
              f"FROM warehouse.dataset_version WHERE dataset_key LIKE 'acl\\_%{tag}'")
        owner("INSERT INTO warehouse.ecotaxa_sample (dataset_version_id, project_id, sample_id, sample_orig_id, "
              "marine_zone_key, marine_zone_assignment_status, datetime_min) "
              "SELECT v.id, 1, s.n, s.n, s.z, s.st, s.d::timestamptz FROM warehouse.dataset_version v, (VALUES "
              "('ok','lab','assigned','2019-06-01'),('year','lab','assigned','2023-06-01'),"
              "('zone','bay','assigned','2019-06-01'),('amb','lab','ambiguous','2019-06-01'),"
              "('nodate','lab','assigned',NULL)) AS s(n,z,st,d) "
              f"WHERE v.dataset_key IN ('acl_c1_{tag}','acl_c2_{tag}')")
        owner("INSERT INTO warehouse.ecotaxa_object (sample_id, object_id) "
              "SELECT s.id, 'o' || s.id FROM warehouse.ecotaxa_sample s JOIN warehouse.dataset_version v "
              f"ON v.id = s.dataset_version_id WHERE v.dataset_key LIKE 'acl\\_%{tag}'")
        owner("CREATE VIEW explore.acl_samples AS SELECT s.sample_id, v.dataset_key "
              "FROM warehouse.ecotaxa_sample s JOIN warehouse.dataset_version v ON v.id = s.dataset_version_id")
        owner("CREATE VIEW explore.acl_objects AS SELECT o.object_id FROM warehouse.ecotaxa_object o")
        owner("INSERT INTO warehouse.dataset_version (source_instance, dataset_key, version_key, file_manifest_uri, sha256) "
              f"VALUES ('ctd','acl_ctd_{tag}','v1','u','4{tag}')")
        owner("INSERT INTO warehouse.dataset_metadata (dataset_version_id, title, description, access_contract) "
              f"SELECT id, 't', 'd', 'C1' FROM warehouse.dataset_version WHERE dataset_key = 'acl_ctd_{tag}'")
        owner("INSERT INTO warehouse.ctd_profile (dataset_version_id, source_profile_key, sampled_at, "
              "marine_zone_key, marine_zone_assignment_status) "
              "SELECT v.id, c.k, c.d::timestamptz, c.z, c.st FROM warehouse.dataset_version v, (VALUES "
              "('ctd_lab','2019-06-01','lab','assigned'),('ctd_bay','2019-06-01','bay','assigned'),"
              "('ctd_unassigned','2019-06-01',NULL,NULL)) AS c(k,d,z,st) "
              f"WHERE v.dataset_key = 'acl_ctd_{tag}'")
        owner("CREATE VIEW explore.acl_ctd AS SELECT c.source_profile_key, v.dataset_key "
              "FROM warehouse.ctd_profile c JOIN warehouse.dataset_version v ON v.id = c.dataset_version_id")
        # Views created by the loader are handed to the data owner by a replay.
        subprocess.run([sys.executable, str(DEPLOY)], env=self.deploy_env, check=True, capture_output=True)
        for name in ("scoped", "empty"):
            role = f"acl_{name}_{tag}"
            owner(f"CREATE ROLE {role} LOGIN PASSWORD 'pw'")
            owner(f"SELECT warehouse.enroll_access_role('{role}')")

    def scoped_samples(self, role):
        code, out = self.run_as(role, f"SELECT string_agg(sample_id || '@' || dataset_key, ',' ORDER BY sample_id, dataset_key) "
                                      f"FROM explore.acl_samples WHERE dataset_key LIKE 'acl\\_%{self.tag}'", "pw")
        self.assertEqual(code, 0, out)
        return out

    def grant(self, role, **dims):
        columns = ["grantee"] + list(dims)
        values = [f"'{role}'"] + ["NULL" if v is None else (f"'{v}'" if isinstance(v, str) else str(v)) for v in dims.values()]
        code, out = self.owner(f"INSERT INTO warehouse.access_grant ({','.join(columns)}) VALUES ({','.join(values)}) RETURNING id")
        self.assertEqual(code, 0, out)
        return int(out.splitlines()[0])

    def test_zz_scoped_role_sees_only_its_source_contract_zone_and_year(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        scoped, empty = f"acl_scoped_{self.tag}", f"acl_empty_{self.tag}"
        self.assertEqual(self.scoped_samples(scoped), "", "no grant means no rows")
        grant_id = self.grant(scoped, source_instance="ecotaxa", contract="C1", zone_key="lab", year_min=2018, year_max=2022)
        # Only the C1 version, assigned zone 'lab', year 2019: not C2, not 2023,
        # not zone 'bay', not 'ambiguous', not an unknown date.
        self.assertEqual(self.scoped_samples(scoped), f"ok@acl_c1_{self.tag}")
        self.assertEqual(self.scoped_samples(empty), "")
        code, out = self.run_as(scoped, "SELECT count(*) FROM explore.acl_objects", "pw")
        self.assertEqual((code, out), (0, "1"), "objects follow their visible sample")
        code, out = self.run_as(scoped, "SELECT contract, zone_key, year_min, year_max FROM explore.my_access", "pw")
        self.assertEqual((code, out), (0, "C1|lab|2018|2022"))
        # Revoking keeps the history and closes the access.
        self.owner(f"UPDATE warehouse.access_grant SET revoked_at = now() WHERE id = {grant_id}")
        self.assertEqual(self.scoped_samples(scoped), "")
        code, out = self.owner(f"SELECT count(*) FROM warehouse.access_grant WHERE id = {grant_id}")
        self.assertEqual(out, "1")

    def test_zz_unscoped_grant_reaches_ambiguous_and_undated_rows(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        role = f"acl_scoped_{self.tag}"
        self.owner(f"UPDATE warehouse.access_grant SET revoked_at = now() WHERE grantee = '{role}' AND revoked_at IS NULL")
        self.grant(role, source_instance="ecotaxa", contract="C2")
        self.assertEqual(self.scoped_samples(role),
                         ",".join(f"{n}@acl_c2_{self.tag}" for n in ("amb", "nodate", "ok", "year", "zone")))
        self.owner(f"UPDATE warehouse.access_grant SET revoked_at = now() WHERE grantee = '{role}' AND revoked_at IS NULL")

    def test_zz_scoped_role_cannot_reach_raw_tables_or_the_grant_list(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        role = f"acl_scoped_{self.tag}"
        for sql in ("SELECT 1 FROM warehouse.ecotaxa_sample", "SELECT 1 FROM warehouse.access_grant",
                    "SELECT warehouse.row_allowed(1, NULL, NULL, NULL)"):
            code, out = self.run_as(role, sql, "pw")
            self.assertNotEqual(code, 0, sql)
            self.assertIn("permission denied", out)

    def test_zz_all_access_roles_see_everything(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        code, out = self.run_as("warehouse_reader", f"SELECT count(*) FROM explore.acl_samples WHERE dataset_key LIKE 'acl\\_%{self.tag}'", "reader-pw")
        self.assertEqual((code, out), (0, "10"))
        code, out = self.run_as("warehouse_reader", "SELECT grantee FROM explore.my_access", "reader-pw")
        self.assertEqual(out, "all data")

    def test_zz_enrollment_refuses_roles_that_would_see_everything(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        code, out = self.owner("SELECT warehouse.enroll_access_role('warehouse_reader')")
        self.assertNotEqual(code, 0)
        self.assertIn("warehouse_all_access", out)

    def test_zz_a_view_created_later_never_bypasses_row_security(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        superuser = self.owner("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")[1] == "t"
        self.owner("CREATE VIEW explore.acl_later AS SELECT sample_id, dataset_version_id FROM warehouse.ecotaxa_sample")
        owner_now = self.owner("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'explore.acl_later'::regclass")[1]
        if superuser:
            # The event trigger hands the view over at creation: filtered immediately, nothing to audit.
            self.assertEqual(owner_now, "warehouse_data_owner")
            self.assertEqual(self.owner("SELECT count(*) FROM explore.access_audit"), (0, "0"))
            self.assertEqual(self.run_as(f"acl_empty_{self.tag}", "SELECT count(*) FROM explore.acl_later", "pw"), (0, "0"))
        else:
            # Without an event trigger the audit flags it until a deploy replay adopts it.
            self.assertIn("acl_later", self.owner("SELECT object_name FROM explore.access_audit")[1])
            subprocess.run([sys.executable, str(DEPLOY)], env=self.deploy_env, check=True, capture_output=True)
            self.assertEqual(self.owner("SELECT count(*) FROM explore.access_audit"), (0, "0"))
        self.owner("DROP VIEW explore.acl_later")

    def revoke_all(self, role):
        self.owner(f"UPDATE warehouse.access_grant SET revoked_at = now() WHERE grantee = '{role}' AND revoked_at IS NULL")

    def test_zz_include_unknown_scope_is_an_explicit_choice(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        role = f"acl_scoped_{self.tag}"
        self.revoke_all(role)
        self.grant(role, source_instance="ecotaxa", contract="C1", zone_key="lab", year_min=2018, year_max=2022)
        self.assertEqual(self.scoped_samples(role), f"ok@acl_c1_{self.tag}", "bounded grant hides unknown scope")
        self.revoke_all(role)
        code, out = self.owner(
            "INSERT INTO warehouse.access_grant (grantee, source_instance, contract, zone_key, year_min, year_max, "
            f"include_unknown_scope) VALUES ('{role}', 'ecotaxa', 'C1', 'lab', 2018, 2022, true)")
        self.assertEqual(code, 0, out)
        # Ambiguous zone and missing date join; another zone and another year never do.
        self.assertEqual(self.scoped_samples(role),
                         ",".join(f"{n}@acl_c1_{self.tag}" for n in ("amb", "nodate", "ok")))
        self.revoke_all(role)

    def test_zz_ctd_profiles_follow_their_own_zone(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        role = f"acl_scoped_{self.tag}"
        self.revoke_all(role)
        self.grant(role, source_instance="ctd", contract="C1", zone_key="lab")
        code, out = self.run_as(role, "SELECT string_agg(source_profile_key, ',' ORDER BY 1) FROM explore.acl_ctd "
                                      f"WHERE dataset_key = 'acl_ctd_{self.tag}'", "pw")
        self.assertEqual((code, out), (0, "ctd_lab"))
        self.revoke_all(role)

    def test_zz_my_datasets_tells_hidden_from_absent_without_counts(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        role = f"acl_scoped_{self.tag}"
        self.revoke_all(role)
        self.grant(role, source_instance="ecotaxa", contract="C1", zone_key="lab")
        code, out = self.run_as(role, "SELECT dataset_key || ':' || my_scope || ':' || (note IS NOT NULL) "
                                      f"FROM explore.my_datasets WHERE dataset_key LIKE 'acl\\_%{self.tag}' ORDER BY 1", "pw")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines(), [f"acl_c1_{self.tag}:partiel:true", f"acl_c2_{self.tag}:aucun:false",
                                            f"acl_ctd_{self.tag}:aucun:false", f"acl_f_{self.tag}:aucun:false"])
        code, out = self.run_as(role, f"SELECT scope_detail FROM explore.my_datasets WHERE dataset_key = 'acl_c2_{self.tag}'", "pw")
        self.assertIn("masquées, pas absentes", out)
        code, out = self.run_as(role, f"SELECT note FROM explore.my_datasets WHERE dataset_key = 'acl_c1_{self.tag}'", "pw")
        self.assertIn("ecopart", out)
        code, out = self.run_as("warehouse_reader", "SELECT DISTINCT my_scope FROM explore.my_datasets "
                                f"WHERE dataset_key LIKE 'acl\\_%{self.tag}'", "reader-pw")
        self.assertEqual((code, out), (0, "complet"))
        self.revoke_all(role)

    def test_zz_read_roles_avoid_the_merge_join_plan(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        # An account enrolled before the setting existed is updated by a replay.
        self.owner(f"ALTER ROLE acl_empty_{self.tag} RESET enable_mergejoin")
        self.assertEqual(self.run_as(f"acl_empty_{self.tag}", "SHOW enable_mergejoin", "pw"), (0, "on"))
        subprocess.run([sys.executable, str(DEPLOY)], env=self.deploy_env, check=True, capture_output=True)
        self.assertEqual(self.run_as(f"acl_empty_{self.tag}", "SHOW enable_mergejoin", "pw"), (0, "off"))
        for role, password in ((f"acl_scoped_{self.tag}", "pw"), ("warehouse_reader", "reader-pw")):
            self.assertEqual(self.run_as(role, "SHOW enable_mergejoin", password), (0, "off"))

    def test_zz_privilege_escalation_and_bypass_attempts_are_refused(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        role = f"acl_scoped_{self.tag}"
        attempts = (
            "SET ROLE warehouse_data_owner",
            "SET ROLE warehouse_all_access",
            "SET SESSION AUTHORIZATION " + os.environ.get("PGUSER", "neolab"),
            "SET row_security = off; SELECT count(*) FROM explore.acl_samples",
            "INSERT INTO warehouse.access_grant (grantee, contract) VALUES ('%s', 'C2')" % role,
            "CREATE TEMP TABLE leak AS SELECT * FROM warehouse.ecotaxa_sample",
            "SELECT pg_read_file('/etc/passwd')",
            "COPY (SELECT 1) TO PROGRAM 'id'",
            "SELECT count(*) FROM warehouse.ecotaxa_object",
        )
        for sql in attempts:
            code, out = self.run_as(role, sql, "pw")
            self.assertNotEqual(code, 0, sql)

    def test_zz_no_protected_table_is_left_without_row_security(self):
        code, out = self.owner("SELECT count(*) FROM explore.access_audit WHERE problem = 'table without row security'")
        self.assertEqual((code, out), (0, "0"))


@unittest.skipUnless(os.environ.get("WAREHOUSE_TEST_LIVE") == "1", "WAREHOUSE_TEST_LIVE=1 requis")
class LiveNonSuperuserOwnerTests(unittest.TestCase):
    """Managed-hosting case: the owner has CREATEROLE but is not a superuser."""

    @classmethod
    def setUpClass(cls):
        tag = uuid.uuid4().hex[:6]
        cls.owner_role, cls.db, cls.reader = f"nsowner_{tag}", f"ns_test_{tag}", f"nsread_{tag}"
        cls.admin_env = dict(os.environ)
        cls.admin("postgres", f"CREATE ROLE {cls.owner_role} LOGIN PASSWORD 'o' CREATEDB CREATEROLE NOSUPERUSER")
        # Group and service roles are cluster-wide and may already exist: an administrator delegates them.
        for group in ("warehouse_data_owner", "warehouse_all_access", "warehouse_explore_reader",
                      "warehouse_reader", "warehouse_navigator"):
            cls.admin("postgres", f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{group}') THEN "
                                  f"GRANT {group} TO {cls.owner_role} WITH ADMIN OPTION; END IF; END $$")
        cls.admin("postgres", f"CREATE DATABASE {cls.db} OWNER {cls.owner_role}")
        cls.env = dict(os.environ, WAREHOUSE_POSTGRES_HOST=os.environ.get("PGHOST", "127.0.0.1"),
                       WAREHOUSE_POSTGRES_PORT=os.environ.get("PGPORT", "5432"), WAREHOUSE_POSTGRES_DB=cls.db,
                       WAREHOUSE_POSTGRES_USER=cls.owner_role, WAREHOUSE_POSTGRES_PASSWORD="o",
                       WAREHOUSE_READER_PASSWORD="reader-pw", WAREHOUSE_NAVIGATOR_PASSWORD="navigator-pw")

    @classmethod
    def tearDownClass(cls):
        cls.admin(cls.db, f"DROP OWNED BY {cls.reader}", check=False)
        cls.admin("postgres", f"DROP DATABASE IF EXISTS {cls.db} WITH (FORCE)")
        cls.admin("postgres", f"DROP ROLE IF EXISTS {cls.reader}", check=False)
        cls.admin("postgres", f"DROP OWNED BY {cls.owner_role}", check=False)
        cls.admin("postgres", f"DROP ROLE IF EXISTS {cls.owner_role}", check=False)

    @classmethod
    def admin(cls, db, sql, check=True):
        return subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", db, "-c", sql],
                              env=cls.admin_env, check=check, capture_output=True, text=True)

    def deploy(self):
        return subprocess.run([sys.executable, str(DEPLOY)], env=self.env, capture_output=True, text=True)

    def owner_settings(self):
        return self.admin("postgres", f"SELECT coalesce(array_to_string(s.setconfig, ' '), '') FROM pg_roles r "
                                      f"LEFT JOIN pg_db_role_setting s ON s.setrole = r.oid WHERE r.rolname = '{self.owner_role}'")

    def test_replays_never_make_the_owner_read_only(self):
        first = self.deploy()
        self.assertEqual(first.returncode, 0, first.stderr[-400:])
        env = dict(self.admin_env, PGUSER=self.owner_role, PGPASSWORD="o")
        subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", self.db, "-c",
                        f"CREATE ROLE {self.reader} LOGIN PASSWORD 'pw'", "-c",
                        f"SELECT warehouse.enroll_access_role('{self.reader}')"], env=env, check=True, capture_output=True)
        # Simulate the faulty earlier version, then check that a replay repairs it.
        self.admin("postgres", f"ALTER ROLE {self.owner_role} SET default_transaction_read_only = on")
        second = self.deploy()
        self.assertEqual(second.returncode, 0, second.stderr[-400:])
        self.assertIn("event trigger not installed", second.stderr)
        settings = subprocess.run(["psql", "-X", "-At", "-d", "postgres", "-c",
                                   f"SELECT coalesce(array_to_string(s.setconfig, ' '), '') FROM pg_roles r "
                                   f"LEFT JOIN pg_db_role_setting s ON s.setrole = r.oid AND s.setdatabase = 0 "
                                   f"WHERE r.rolname = '{self.owner_role}'"], env=self.admin_env,
                                  capture_output=True, text=True).stdout
        self.assertNotIn("default_transaction_read_only", settings)
        write = subprocess.run(["psql", "-X", "-At", "-d", self.db, "-c",
                                "INSERT INTO warehouse.dataset_version (source_instance, dataset_key, version_key, "
                                "file_manifest_uri, sha256) VALUES ('ecotaxa','w','v1','u','w') RETURNING 1"],
                               env=env, capture_output=True, text=True)
        self.assertEqual((write.returncode, write.stdout.splitlines()[:1]), (0, ["1"]), write.stderr)
        reader = subprocess.run(["psql", "-X", "-At", "-d", self.db, "-U", self.reader, "-c", "SHOW enable_mergejoin"],
                                env=dict(env, PGPASSWORD="pw"), capture_output=True, text=True)
        self.assertEqual(reader.stdout.strip(), "off", reader.stderr)


@unittest.skipUnless(os.environ.get("WAREHOUSE_TEST_LIVE") == "1", "WAREHOUSE_TEST_LIVE=1 requis")
class LiveDockerInitSimulationTests(unittest.TestCase):
    """Replays docker-compose.warehouse.yml's first init without Docker: same files,
    same container names and order, same hook, then the warehouse-context service."""

    def test_compose_first_init_ends_ready(self):
        import shutil
        import tempfile
        import yaml
        compose = yaml.safe_load((ROOT / "docker-compose.warehouse.yml").read_text(encoding="utf-8"))
        db_service = compose["services"]["neolab-warehouse-db"]
        mounts = {}
        for volume in db_service["volumes"]:
            source, target = volume.split(":")[:2]
            if source.startswith("./"):
                mounts[target] = ROOT / source[2:]
        initdb = sorted(t for t in mounts if t.startswith("/docker-entrypoint-initdb.d/"))
        self.assertTrue(initdb[-1].endswith(".sh"), "the roles and release hook runs last")
        db = "docker_sim_" + uuid.uuid4().hex[:8]
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        container = {"/docker-entrypoint-initdb.d": tmp / "initdb", "/opt/warehouse": tmp / "opt"}
        for directory in container.values():
            directory.mkdir()
        for target, source in mounts.items():
            for prefix, local in container.items():
                if target.startswith(prefix + "/"):
                    (local / target[len(prefix) + 1:]).symlink_to(source)
        env = dict(os.environ, POSTGRES_USER=os.environ.get("PGUSER", "neolab"), POSTGRES_DB=db,
                   WAREHOUSE_READER_PASSWORD="reader-pw", WAREHOUSE_NAVIGATOR_PASSWORD="navigator-pw")
        subprocess.run(["psql", "-X", "-q", "-d", "postgres", "-c", f"CREATE DATABASE {db}"], env=env, check=True)
        self.addCleanup(subprocess.run, ["psql", "-X", "-q", "-d", "postgres", "-c",
                                         f"DROP DATABASE IF EXISTS {db} WITH (FORCE)"], env=env, capture_output=True)
        for target in initdb:
            name = target.rsplit("/", 1)[1]
            if name.endswith(".sql"):
                # As the image entrypoint does: one psql per file, stop on error.
                run = subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", env["POSTGRES_USER"],
                                      "-d", db, "-f", str(container["/docker-entrypoint-initdb.d"] / name)],
                                     env=env, capture_output=True, text=True)
            else:
                script = mounts[target].read_text(encoding="utf-8")
                for prefix, local in container.items():
                    script = script.replace(prefix, str(local))
                run = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, f"{name}: {run.stderr[-500:]}")
        service = compose["services"]["warehouse-context"]
        self.assertIn("publish_warehouse_context.py", " ".join(service["command"]))
        publish_env = dict(env, WAREHOUSE_POSTGRES_HOST=os.environ.get("PGHOST", "127.0.0.1"),
                           WAREHOUSE_POSTGRES_PORT=os.environ.get("PGPORT", "5432"), WAREHOUSE_POSTGRES_DB=db,
                           WAREHOUSE_POSTGRES_USER=env["POSTGRES_USER"],
                           WAREHOUSE_POSTGRES_PASSWORD=os.environ.get("PGPASSWORD", "unused"))
        published = subprocess.run([sys.executable, str(ROOT / "scripts/publish_warehouse_context.py"), "--no-doc"],
                                   env=publish_env, capture_output=True, text=True)
        self.assertEqual(published.returncode, 0, published.stderr[-500:])
        verify = subprocess.run([sys.executable, str(DEPLOY), "--verify"], env=publish_env, capture_output=True, text=True)
        self.assertIn(verify.returncode, (0, 2), verify.stdout + verify.stderr[-500:])
        self.assertIn("PRÊT", verify.stdout)
        method = subprocess.run(["psql", "-X", "-At", "-d", db, "-c", "SELECT method || ':' || migration_count "
                                 "FROM explore.warehouse_release"], env=env, capture_output=True, text=True).stdout.strip()
        self.assertEqual(method, f"docker-init:{len(initdb) - 1 + 2}")
        navigator = subprocess.run(["psql", "-X", "-At", "-d", db, "-U", "warehouse_navigator", "-c",
                                    "SELECT count(*) >= 0 FROM warehouse.dataset_version"],
                                   env=dict(env, PGPASSWORD="navigator-pw"), capture_output=True, text=True)
        self.assertEqual(navigator.stdout.strip(), "t", navigator.stderr)


if __name__ == "__main__":
    unittest.main()
