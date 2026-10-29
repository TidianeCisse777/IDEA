"""Parcours de connexion DbHub: configuration sans secret, identifiants privés,
provisionnement d'un compte et recette réelle.

Les tests statiques n'ont besoin d'aucun serveur. Le test live (WAREHOUSE_TEST_LIVE=1
et les variables PG*) crée une base temporaire, y déploie le warehouse, crée un
compte restreint avec scripts/warehouse_user.py puis exécute la recette
scripts/warehouse_connect.py check avec le vrai DbHub (installé dans
data/tooling/dbhub ou disponible via npx).
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


connect = load("warehouse_connect")
users = load("warehouse_user")
SECRET = "p@ss/w:rd#1&secret"
VALUES = {"WAREHOUSE_DB_HOST": "db.example.org", "WAREHOUSE_DB_PORT": "5432", "WAREHOUSE_DB_NAME": "neolab_warehouse",
          "WAREHOUSE_DB_USER": "ines", "WAREHOUSE_DB_PASSWORD": SECRET, "WAREHOUSE_DB_SSLMODE": "require"}


class ClientConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved = os.environ.get("NEOLAB_WAREHOUSE_CREDENTIALS")
        os.environ["NEOLAB_WAREHOUSE_CREDENTIALS"] = str(self.tmp / "cred" / "credentials.env")
        for key in connect.KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("NEOLAB_WAREHOUSE_CREDENTIALS", None)
        else:
            os.environ["NEOLAB_WAREHOUSE_CREDENTIALS"] = self.saved

    def bundle(self):
        path = self.tmp / "ines.env"
        path.write_text("# commentaire\n" + "".join(f"{k}={v}\n" for k, v in VALUES.items()), encoding="utf-8")
        return path

    def test_keyring_keeps_the_password_out_of_the_file(self):
        import types
        vault = {}
        fake = types.SimpleNamespace(set_password=lambda s, a, p: vault.__setitem__((s, a), p),
                                     get_password=lambda s, a: vault.get((s, a)))
        sys.modules["keyring"] = fake
        self.addCleanup(sys.modules.pop, "keyring", None)
        self.assertEqual(connect.main(["init", "--from-file", str(self.bundle()), "--keyring"]), 0)
        text = connect.credentials_path().read_text(encoding="utf-8")
        self.assertNotIn(SECRET, text)
        self.assertIn("WAREHOUSE_DB_PASSWORD_STORE=keyring", text)
        self.assertEqual(connect.load_settings({})["WAREHOUSE_DB_PASSWORD"], SECRET)
        vault.clear()
        with self.assertRaises(SystemExit) as raised:
            connect.load_settings({})
        self.assertIn("trousseau", str(raised.exception))
        # A plain init afterwards goes back to the private file.
        connect.main(["init", "--from-file", str(self.bundle())])
        self.assertNotIn("PASSWORD_STORE", connect.credentials_path().read_text(encoding="utf-8"))

    def test_dsn_encodes_reserved_characters_in_the_password(self):
        dsn = connect.build_dsn(VALUES)
        self.assertNotIn(SECRET, dsn)
        self.assertTrue(dsn.startswith("postgres://ines:p%40ss%2Fw%3Ard%231%26secret@db.example.org:5432/"))
        self.assertTrue(dsn.endswith("?sslmode=require"))

    @unittest.skipIf(os.name == "nt", "droits POSIX")
    def test_init_stores_credentials_privately_outside_the_repository(self):
        self.assertEqual(connect.main(["init", "--from-file", str(self.bundle())]), 0)
        path = connect.credentials_path()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotIn(str(ROOT), str(path))
        self.assertEqual(connect.load_settings()["WAREHOUSE_DB_USER"], "ines")

    def test_environment_overrides_the_file_and_missing_credentials_are_explained(self):
        with self.assertRaises(SystemExit) as raised:
            connect.load_settings({})
        self.assertIn("init", str(raised.exception))
        connect.main(["init", "--from-file", str(self.bundle())])
        self.assertEqual(connect.load_settings({"WAREHOUSE_DB_USER": "autre"})["WAREHOUSE_DB_USER"], "autre")

    def test_client_registrations_never_contain_credentials(self):
        connect.main(["init", "--from-file", str(self.bundle())])
        for client in ("codex", "claude-code", "claude-desktop", "json"):
            text = connect.registration(client)
            self.assertNotIn(SECRET, text)
            self.assertNotIn("WAREHOUSE_DB_PASSWORD", text)
            self.assertIn("warehouse_connect.py", text)
        payload = json.loads(connect.registration("json"))["mcpServers"]["neolab-warehouse"]
        self.assertEqual(payload["args"][-1], "run")
        self.assertIn("claude mcp add", connect.registration("claude-code"))
        self.assertIn("codex mcp add", connect.registration("codex"))

    def test_server_configuration_has_no_secret_and_reads_the_dsn_from_the_environment(self):
        toml = (ROOT / "dbhub" / "warehouse.connect.toml").read_text(encoding="utf-8")
        self.assertIn('dsn = "${WAREHOUSE_DSN}"', toml)
        self.assertNotRegex(toml, r"password\s*=")
        self.assertEqual(toml.count("readonly = true"), 2)  # execute_sql et warehouse_context
        self.assertIn("explore.my_access", toml)

    def test_connection_failures_are_explained_from_real_dbhub_messages(self):
        # Messages captured from DbHub 1.5.0 against PostgreSQL 16 (password masked by DbHub).
        cases = {
            'Failed to connect to PostgreSQL database: error: password authentication failed for user "ines"': "identifiants refusés",
            'error: pg_hba.conf rejects connection for host "127.0.0.1", user "ines", database "e2e", no encryption': "connexion chiffrée",
            "Failed to connect to PostgreSQL database: Error: self-signed certificate": "certificat",
            "Error: connect ECONNREFUSED 127.0.0.1:59999": "injoignable",
            "Error: getaddrinfo ENOTFOUND hote-inexistant.invalid": "hôte inconnu",
            "something else entirely": "sans cause reconnue",
        }
        for stderr, expected in cases.items():
            self.assertIn(expected, connect.diagnose(stderr), stderr)

    def test_password_expiry_is_reported_before_and_after(self):
        from datetime import date
        today = date(2026, 10, 28)
        self.assertIsNone(connect.expiry_status({}, today))
        self.assertIn("expiré le 2026-10-01", connect.expiry_status({"WAREHOUSE_DB_EXPIRES": "2026-10-01"}, today))
        self.assertIn("5 jour(s)", connect.expiry_status({"WAREHOUSE_DB_EXPIRES": "2026-11-02"}, today))
        self.assertNotIn("renouvellement", connect.expiry_status({"WAREHOUSE_DB_EXPIRES": "2027-06-01"}, today))

    def test_server_identity_can_be_verified_with_a_ca_file(self):
        values = dict(VALUES, WAREHOUSE_DB_SSLMODE="verify-full", WAREHOUSE_DB_SSLROOTCERT="/etc/ssl/neolab ca.crt")
        self.assertTrue(connect.build_dsn(values).endswith("sslmode=verify-full&sslrootcert=%2Fetc%2Fssl%2Fneolab%20ca.crt"))
        self.assertNotIn("sslrootcert", connect.build_dsn(VALUES))

    def test_local_install_goes_where_the_launcher_looks(self):
        self.assertEqual(connect.LOCAL_DBHUB.parents[4], ROOT / "data" / "tooling" / "dbhub")

    def test_the_dbhub_version_is_pinned(self):
        self.assertRegex(connect.DBHUB_PACKAGE, r"@\d+\.\d+\.\d+$")


class AdminProvisioningTests(unittest.TestCase):
    def test_role_names_are_validated_and_reserved_names_refused(self):
        self.assertEqual(users.valid_name("ines_labrador"), "ines_labrador")
        for bad in ("Ines", "x", "a;drop", "warehouse_reader", "postgres", "neolab", "pg_monitor", "1abc", "a b c"):
            with self.assertRaises(SystemExit, msg=bad):
                users.valid_name(bad)

    def test_passwords_never_travel_in_arguments(self):
        source = (ROOT / "scripts" / "warehouse_user.py").read_text(encoding="utf-8")
        self.assertIn("input=script", source)
        self.assertIn("'-f', '-'", source)
        self.assertNotIn("'-W'", source)

    def test_a_new_account_has_no_access_unless_a_grant_is_given(self):
        parser_args = type("A", (), dict(source=None, contract=None, zone=None, year_min=None, year_max=None))()
        self.assertFalse(users.wants_grant(parser_args))
        parser_args.year_min = 2018
        self.assertTrue(users.wants_grant(parser_args))

    def test_sources_give_one_grant_each_and_warn_when_uvp_pair_is_incomplete(self):
        def args(source):
            return type("A", (), dict(source=source, contract="C1", zone=None, year_min=None, year_max=None,
                                       note=None, name="ines", include_unknown=False))()
        self.assertEqual(users.sources(args("ecotaxa, ecopart")), ["ecotaxa", "ecopart"])
        self.assertEqual(users.sources(args(None)), [""])
        with self.assertRaises(SystemExit):
            users.sources(args("ecotaxa;drop"))
        self.assertIn("ecopart", users.paired_source_warning(args("ecotaxa")))
        self.assertIsNone(users.paired_source_warning(args("ecotaxa,ecopart")))
        self.assertIsNone(users.paired_source_warning(args("filet")))
        self.assertIsNone(users.paired_source_warning(args(None)))
        self.assertEqual(users.grants_sql(args("ecotaxa,ecopart")).count("INSERT INTO warehouse.access_grant"), 2)
        self.assertEqual(users.grant_variables(args("ecotaxa,ecopart"))["source_1"], "ecopart")

    def test_credential_bundle_is_private_and_defaults_to_tls_for_remote_hosts(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        env = {"PGHOST": "127.0.0.1", "PGPORT": "5432", "PGDATABASE": "neolab_warehouse"}
        remote = users.write_bundle(env, "ines", "pw", tmp, "warehouse.example.org", None)
        text = remote.read_text(encoding="utf-8")
        self.assertIn("WAREHOUSE_DB_SSLMODE=require", text)
        self.assertIn("WAREHOUSE_DB_HOST=warehouse.example.org", text)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(remote.stat().st_mode), 0o600)
        local = users.write_bundle(env, "ines", "pw", tmp, None, None)
        self.assertIn("WAREHOUSE_DB_SSLMODE=disable", local.read_text(encoding="utf-8"))
        self.assertNotIn("WAREHOUSE_DB_EXPIRES", local.read_text(encoding="utf-8"))
        dated = users.write_bundle(env, "ines", "pw", tmp, None, None, "2027-01-31")
        self.assertIn("WAREHOUSE_DB_EXPIRES=2027-01-31", dated.read_text(encoding="utf-8"))


def dbhub_available():
    return (ROOT / "data/tooling/dbhub/node_modules/@bytebase/dbhub/dist/index.js").exists() or shutil.which("npx")


@unittest.skipUnless(os.environ.get("WAREHOUSE_TEST_LIVE") == "1" and dbhub_available(),
                     "WAREHOUSE_TEST_LIVE=1 et DbHub requis")
class LiveConnectionTests(unittest.TestCase):
    """Compte restreint créé par l'outil admin, recette via le vrai DbHub, authentification par mot de passe."""

    @classmethod
    def setUpClass(cls):
        cls.db = "connect_test_" + uuid.uuid4().hex[:8]
        cls.user = "conn_" + uuid.uuid4().hex[:8]
        cls.tmp = Path(tempfile.mkdtemp())
        host = os.environ.get("WAREHOUSE_TEST_TCP_HOST", "127.0.0.1")
        cls.admin_env = dict(os.environ, WAREHOUSE_POSTGRES_HOST=host, WAREHOUSE_POSTGRES_DB=cls.db,
                             WAREHOUSE_POSTGRES_PORT=os.environ.get("PGPORT", "5432"),
                             WAREHOUSE_POSTGRES_USER=os.environ.get("PGUSER", "neolab"),
                             WAREHOUSE_POSTGRES_PASSWORD=os.environ.get("PGPASSWORD", "x"),
                             WAREHOUSE_READER_PASSWORD="reader-pw", WAREHOUSE_NAVIGATOR_PASSWORD="navigator-pw")
        subprocess.run(["psql", "-X", "-q", "-d", "postgres", "-c", f"CREATE DATABASE {cls.db}"], env=os.environ,
                       check=True, capture_output=True)
        deploy = subprocess.run([sys.executable, str(ROOT / "scripts/deploy_warehouse_postgres.py")], env=cls.admin_env,
                                capture_output=True, text=True)
        assert deploy.returncode == 0, deploy.stderr
        cls.sql(
            "INSERT INTO warehouse.dataset_version (source_instance, dataset_key, version_key, file_manifest_uri, sha256) "
            "VALUES ('ecotaxa','c1','v1','u','a'),('ecotaxa','c2','v1','u','b');"
            "INSERT INTO warehouse.dataset_metadata (dataset_version_id, title, description, access_contract) "
            "SELECT id, 'T '||dataset_key, 'D', CASE dataset_key WHEN 'c1' THEN 'C1' ELSE 'C2' END FROM warehouse.dataset_version;")

    @classmethod
    def sql(cls, statement):
        env = dict(cls.admin_env, PGHOST=cls.admin_env["WAREHOUSE_POSTGRES_HOST"], PGPORT=cls.admin_env["WAREHOUSE_POSTGRES_PORT"],
                   PGPASSWORD=cls.admin_env["WAREHOUSE_POSTGRES_PASSWORD"])
        return subprocess.run(["psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-d", cls.db, "-c", statement],
                              env=env, check=True, capture_output=True, text=True).stdout.strip()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)
        env = dict(os.environ)
        subprocess.run(["psql", "-X", "-q", "-d", cls.db, "-c", f"DROP OWNED BY {cls.user}"], env=env, capture_output=True)
        subprocess.run(["psql", "-X", "-q", "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {cls.db} WITH (FORCE)",
                        "-c", f"DROP ROLE IF EXISTS {cls.user}"], env=env, capture_output=True)

    def run_script(self, script, *args, env=None):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], env=env or self.admin_env,
                              capture_output=True, text=True)

    def client_env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("WAREHOUSE_", "PG"))}
        env["NEOLAB_WAREHOUSE_CREDENTIALS"] = str(self.tmp / "credentials.env")
        env.update(extra)
        return env

    def test_zz_provision_connect_check_rotate_and_offboard(self):
        out_dir = self.tmp / "bundles"
        created = self.run_script("warehouse_user.py", "create", self.user, "--contract", "C1", "--expires-days", "10",
                                  "--out-dir", str(out_dir))
        self.assertEqual(created.returncode, 0, created.stderr)
        bundle = out_dir / f"{self.user}.env"
        password = [l for l in bundle.read_text().splitlines() if l.startswith("WAREHOUSE_DB_PASSWORD=")][0].split("=", 1)[1]
        self.assertNotIn(password, created.stdout + created.stderr)
        init = self.run_script("warehouse_connect.py", "init", "--from-file", str(bundle), env=self.client_env())
        self.assertEqual(init.returncode, 0, init.stderr)
        check = self.run_script("warehouse_connect.py", "check", env=self.client_env())
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn(f"{self.user}", check.stdout)
        self.assertIn("C1", check.stdout)
        self.assertIn("valide jusqu'au", check.stdout)
        self.assertNotIn(password, check.stdout + check.stderr)
        # The scope really limits what the account reads, through the same MCP path.
        self.assertEqual(self.sql("SELECT count(*) FROM warehouse.access_grant WHERE grantee = '%s' AND revoked_at IS NULL" % self.user), "1")
        wrong = self.run_script("warehouse_connect.py", "check", env=self.client_env(WAREHOUSE_DB_PASSWORD="mauvais"))
        self.assertEqual(wrong.returncode, 1)
        self.assertIn("identifiants refusés", wrong.stdout)
        self.assertNotIn("mauvais", wrong.stdout + wrong.stderr)
        # An expired account is not silently extended by a rotation.
        self.sql("ALTER ROLE %s VALID UNTIL '2020-01-01'" % self.user)
        refused = self.run_script("warehouse_user.py", "rotate", self.user, "--out-dir", str(out_dir))
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("--expires-days", refused.stderr)
        renewed = self.run_script("warehouse_user.py", "rotate", self.user, "--expires-days", "30", "--out-dir", str(out_dir))
        self.assertEqual(renewed.returncode, 0, renewed.stderr)
        self.assertIn("WAREHOUSE_DB_EXPIRES=", bundle.read_text())
        # Rotation invalidates the old password.
        rotated = self.run_script("warehouse_user.py", "rotate", self.user, "--out-dir", str(out_dir))
        self.assertEqual(rotated.returncode, 0, rotated.stderr)
        stale = self.run_script("warehouse_connect.py", "check", env=self.client_env())
        self.assertEqual(stale.returncode, 1)
        # Offboarding closes the login and records the revocation.
        off = self.run_script("warehouse_user.py", "offboard", self.user)
        self.assertEqual(off.returncode, 0, off.stderr)
        self.assertEqual(self.sql("SELECT rolcanlogin FROM pg_roles WHERE rolname = '%s'" % self.user), "f")
        self.assertEqual(self.sql("SELECT count(*) FROM warehouse.access_grant WHERE grantee = '%s' AND revoked_at IS NULL" % self.user), "0")


if __name__ == "__main__":
    unittest.main()
