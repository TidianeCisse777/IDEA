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
        tables = re.findall(r"\(\'(\w+)\',\n\s+\'(?:warehouse\.row_allowed|EXISTS)", ACCESS)
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

    def test_no_psql_meta_commands_so_psycopg_can_apply_it(self):
        self.assertNotRegex(ACCESS, r"(?m)^\\")

    def test_grants_are_revoked_not_deleted(self):
        self.assertIn("revoked_at timestamptz", ACCESS)
        self.assertNotRegex(ACCESS, r"(?i)DELETE\s+FROM\s+warehouse\.access_grant")

    def test_roles_file_requires_the_access_file_first(self):
        self.assertIn("apply docs/warehouse_access_control.sql before", ROLES)
        names = re.findall(r"/docker-entrypoint-initdb\.d/(\d+_\w+)", COMPOSE)
        self.assertLess(names.index("005_warehouse_access"), names.index("006_warehouse_roles"))


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

    def test_zz_audit_flags_a_leaking_view_until_a_replay_fixes_it(self):
        if not hasattr(type(self), "tag"):
            self.seed_access_data()
        self.owner("CREATE VIEW explore.acl_leak AS SELECT sample_id FROM warehouse.ecotaxa_sample")
        code, out = self.owner("SELECT object_name FROM explore.access_audit")
        if os.environ.get("PGUSER") and self.owner("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")[1] == "t":
            self.assertIn("acl_leak", out)
        subprocess.run([sys.executable, str(DEPLOY)], env=self.deploy_env, check=True, capture_output=True)
        self.assertEqual(self.owner("SELECT count(*) FROM explore.access_audit"), (0, "0"))
        self.owner("DROP VIEW explore.acl_leak")

    def test_zz_no_protected_table_is_left_without_row_security(self):
        code, out = self.owner("SELECT count(*) FROM explore.access_audit WHERE problem = 'table without row security'")
        self.assertEqual((code, out), (0, "0"))


if __name__ == "__main__":
    unittest.main()
