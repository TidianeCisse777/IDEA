"""The real loaders, run against a full v1 deployment with simulated source APIs.

Nothing is downloaded: EcoTaxa and the Amundsen ERDDAP are replaced by in-process
fakes that answer in the shapes the loaders parse, and EcoPart and FILET read
local fixture files. Each loader runs unchanged, as the warehouse owner, under
row-level security, in the order of the runbook; then the deployment is replayed
and checked, and access is verified for a scoped account.

Two owners are covered: a superuser (Docker) and a non-superuser with
CREATEROLE (managed hosting), where PostgreSQL refuses COPY FROM on protected
tables. Enable with WAREHOUSE_TEST_LIVE=1 and PG* variables of a role that can
create databases and roles.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DEPLOY = SCRIPTS / "deploy_warehouse_postgres.py"
BAFFIN = (76.0338, -66.36355)        # inside "Baie de Baffin" in the zone registry
PACIFIC = (0.0, -150.0)              # outside the registry
LIVE = os.environ.get("WAREHOUSE_TEST_LIVE") == "1"


def load_module(name):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload=None, text=None, status=200):
        self.payload, self.text, self.status_code = payload, text or "", status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(response=self)

    def json(self):
        return self.payload


class FakeEcoTaxa:
    """Answers the EcoTaxa endpoints the two EcoTaxa loaders call."""

    def __init__(self, projects):
        self.projects = projects  # pid -> {"title", "samples": [{...}], "objects": [{...}]}
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        if url.endswith("/samples/search"):
            pid = int(params["project_ids"])
            return FakeResponse([{"sampleid": s["sampleid"]} for s in self.projects[pid]["samples"]])
        if "/acquisition/" in url:
            # Real API: pixel calibration lives on the acquisition's free_columns,
            # not on the object (confirmed live, see ROADMAP 30 octobre 2026).
            return FakeResponse({"free_columns": {"pixel": "0.01"}})
        if "/sample/" in url:
            sid = int(url.rsplit("/", 1)[1])
            return FakeResponse(next(s for p in self.projects.values() for s in p["samples"] if s["sampleid"] == sid))
        pid = int(url.rsplit("/", 1)[1])
        project = self.projects[pid]
        return FakeResponse({"projid": pid, "title": project["title"], "instrument": "UVP5", "status": "Annotate",
                             "objcount": len(project["objects"]), "obj_free_cols": project.get("obj_free_cols", {})})

    def post(self, url, params=None, json=None, timeout=None):
        pid = int(url.split("/object_set/")[1].split("/")[0])
        start, size = params["window_start"], params["window_size"]
        page = self.projects[pid]["objects"][start:start + size]
        # fields: obj.orig_id,obj.objdate,obj.depth_min,obj.depth_max,obj.latitude,obj.longitude,txo.display_name[,fre.<label>...]
        # A requested fre.<label> is appended in request order, exactly like the real
        # API: the loader itself only ever requests labels this project's obj_free_cols
        # has, so nothing here needs to be dropped to reproduce that behaviour.
        # Each requested field is answered in request order, like the real API.
        self.fields = params["fields"].split(",")
        def value(o, field):
            prefix, name = field.split(".", 1)
            if prefix == "fre":
                return o["sizes"][name]
            return {"obj.orig_id": f"o{o['objid']}", "obj.objdate": o["date"], "obj.depth_min": o["depth"],
                    "obj.depth_max": o["depth"] + 1, "obj.latitude": None, "obj.longitude": None,
                    "txo.display_name": o["taxon"], "obj.classif_id": o["classif_id"],
                    "obj.classif_qual": o["qual"]}[field]
        return FakeResponse({"object_ids": [o["objid"] for o in page], "sample_ids": [o["sampleid"] for o in page],
                             "acquisition_ids": [f"acq{o['sampleid']}" for o in page],
                             "details": [[value(o, f) for f in self.fields] for o in page]})


def erddap_csv(columns, units, rows):
    lines = [",".join(columns), ",".join(units)]
    lines += [",".join(str(v) for v in row) for row in rows]
    return "\n".join(lines) + "\n"


def fake_erddap(url, timeout=None):
    """Amundsen ERDDAP: the year scan and the profile fetch the CTD loader issues."""
    if "PRES=3" in url:
        return FakeResponse(text=erddap_csv(["filename", "time", "latitude", "longitude", "station", "cast_number", "PRES"],
                                            ["", "UTC", "deg", "deg", "", "", "dbar"],
                                            [["2024_001.int.nc", "2024-07-01T00:00:00Z", BAFFIN[0], BAFFIN[1], "G1", 1, 3]]))
    variables = ["PRES", "TE90", "PSAL", "SIGT", "OXYM", "pH", "NTRA", "FLOR"]
    rows = [["2024_001.int.nc", "2024-07-01T00:00:00Z", BAFFIN[0], BAFFIN[1], "G1", 1, depth, -1.2, 32.1, 25.9,
             300, 8.0, 5.0, 0.4] for depth in (3, 10, 20)]
    return FakeResponse(text=erddap_csv(["filename", "time", "latitude", "longitude", "station", "cast_number", *variables],
                                        ["", "UTC", "deg", "deg", "", "", *(["x"] * len(variables))], rows))


def ecotaxa_fixture():
    def sample(sid, orig, position, contract_note):
        lat, lon = position if position else (None, None)
        return {"sampleid": sid, "orig_id": orig, "latitude": lat, "longitude": lon,
                "free_columns": {"stationid": "G1", "cruise": "AM2024", "profileid": orig,
                                 "ctdrosettefilename": "2024_001.int.nc", "note": contract_note}}
    # One validated, one predicted, one dubious, one validated object per sample (classif_qual V/P/D).
    taxon_ids = {"Calanus": 45072, "Oithona": 61993}
    objects = lambda sid, base: [{"objid": base + i, "sampleid": sid, "date": "2024-07-01",
                                  "depth": d, "taxon": t, "classif_id": taxon_ids[t], "qual": q,
                                  "sizes": {"area": 90.0 + i, "esd": 10.0 + i, "major": 20.0 + i, "minor": 5.0 + i}}
                                 for i, (d, t, q) in enumerate([(0, "Calanus", "V"), (4.999, "Calanus", "P"),
                                                                (5, "Oithona", "D"), (15, "Calanus", "V")])]
    return {
        # 101 and 102 are under contract C1 and C2; 103 carries the EcoPart fixture profile.
        # obj_free_cols differs per project, as it does for real EcoTaxa projects: 101 has
        # no esd (like the lab's UVP6 projects), 102 has no size columns at all, 103 has all four.
        101: {"title": "Projet C1", "obj_free_cols": {"area": "n01", "major": "n16", "minor": "n17"},
              "samples": [sample(1001, "c1_baffin", BAFFIN, "C1"),
                         sample(1002, "c1_pacific", PACIFIC, "C1"),
                         sample(1003, "c1_nocoord", None, "C1")],
              "objects": objects(1001, 10_000) + objects(1002, 20_000)},
        102: {"title": "Projet C2", "obj_free_cols": {},
              "samples": [sample(2001, "c2_baffin", BAFFIN, "C2")],
              "objects": objects(2001, 30_000)},
        103: {"title": "Projet UVP C1", "obj_free_cols": {"area": "n01", "esd": "n02", "major": "n03", "minor": "n04"},
              "samples": [sample(100, "001_profile", BAFFIN, "C1")],
              "objects": objects(100, 40_000)},
    }


def filet_fixture(directory):
    """Smallest FILET export the loader accepts: one sample, one analysis, one taxon."""
    loader = load_module("populate_filet")
    columns = sorted(loader.SAMPLE_COLUMNS)
    sample = {c: "" for c in columns}
    sample.update(sample_id="F1", deployment_id="D1", sampling_year="2024", station_name="G1",
                  deployment_datetime_start="2024-07-01 02:00:00", latitude=str(BAFFIN[0]), longitude=str(BAFFIN[1]),
                  analysis_id="A1", analysis_type="taxonomy", analysis_contract="C1", net_sampling_ids="1")
    samples = directory / "samples.csv"
    samples.write_text(",".join(columns) + "\n" + ",".join(sample[c] for c in columns) + "\n", encoding="utf-8")
    header, values = ["SAMPLE_ID", "ANALYSIS_ID", "TAXON_ID"], ["F1", "A1", "Calanus finmarchicus"]
    for stage in loader.STAGES:
        for column in loader.stage_columns(stage):
            if column:
                header.append(column)
                values.append("3" if stage == "C5" else "")
    abundance = directory / "abundance.csv"
    abundance.write_text(",".join(f'"{h}"' for h in header) + "\n" + ",".join(values) + "\n", encoding="utf-8")
    dictionary = directory / "dictionary.csv"
    dictionary.write_text("column,definition\nC5_ABUND (ind./m3 depth vol.),abondance\n", encoding="utf-8")
    return samples, abundance, dictionary


@unittest.skipUnless(LIVE, "WAREHOUSE_TEST_LIVE=1 requis")
class LoaderChainTests(unittest.TestCase):
    def admin(self, db, sql, check=True):
        return subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", db, "-c", sql],
                              env=self.admin_env, check=check, capture_output=True, text=True)

    def owner_sql(self, sql):
        result = subprocess.run(["psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", self.dsn, "-c", sql],
                                env=dict(self.admin_env, PGPASSWORD=self.owner_pw), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def as_role(self, role, sql, password):
        result = subprocess.run(["psql", "-X", "-At", "-d", self.db, "-U", role, "-c", sql],
                                env=dict(self.admin_env, PGPASSWORD=password), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def setUp(self):
        self.admin_env = dict(os.environ)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def prepare(self, superuser):
        tag = uuid.uuid4().hex[:6]
        self.db = f"loaders_{tag}"
        self.owner = os.environ.get("PGUSER", "neolab") if superuser else f"ldowner_{tag}"
        self.owner_pw = os.environ.get("PGPASSWORD", "o") if superuser else "o"
        self.scoped = f"ldscoped_{tag}"
        if not superuser:
            self.admin("postgres", f"CREATE ROLE {self.owner} LOGIN PASSWORD 'o' CREATEDB CREATEROLE NOSUPERUSER")
            for role in ("warehouse_data_owner", "warehouse_all_access", "warehouse_explore_reader",
                         "warehouse_reader", "warehouse_navigator"):
                self.admin("postgres", f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                                       f"THEN GRANT {role} TO {self.owner} WITH ADMIN OPTION; END IF; END $$")
        self.admin("postgres", f"CREATE DATABASE {self.db} OWNER {self.owner}")
        self.addCleanup(self.cleanup, superuser)
        host, port = os.environ.get("PGHOST", "127.0.0.1"), os.environ.get("PGPORT", "5432")
        self.dsn = f"host={host} port={port} dbname={self.db} user={self.owner}"
        self.deploy_env = dict(os.environ, WAREHOUSE_POSTGRES_HOST=host, WAREHOUSE_POSTGRES_PORT=port,
                               WAREHOUSE_POSTGRES_DB=self.db, WAREHOUSE_POSTGRES_USER=self.owner,
                               WAREHOUSE_POSTGRES_PASSWORD=self.owner_pw,
                               WAREHOUSE_READER_PASSWORD="reader-pw", WAREHOUSE_NAVIGATOR_PASSWORD="navigator-pw")
        first = subprocess.run([sys.executable, str(DEPLOY)], env=self.deploy_env, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr[-600:])

    def cleanup(self, superuser):
        self.admin(self.db, f"DROP OWNED BY {self.scoped}", check=False)
        self.admin("postgres", f"DROP DATABASE IF EXISTS {self.db} WITH (FORCE)", check=False)
        self.admin("postgres", f"DROP ROLE IF EXISTS {self.scoped}", check=False)
        if not superuser:
            self.admin("postgres", f"DROP OWNED BY {self.owner}", check=False)
            self.admin("postgres", f"DROP ROLE IF EXISTS {self.owner}", check=False)

    def run_chain(self):
        from unittest import mock
        # Loaders connect with libpq: the owner's password travels through PGPASSWORD.
        # In real use WAREHOUSE_POSTGRES_PASSWORD is the loading owner's password, which
        # some loaders copy into PGPASSWORD themselves.
        for key in ("PGPASSWORD", "WAREHOUSE_POSTGRES_PASSWORD"):
            previous = os.environ.get(key)
            os.environ[key] = self.owner_pw
            self.addCleanup(lambda k=key, v=previous: os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v))
        projects = ecotaxa_fixture()
        fake = FakeEcoTaxa(projects)
        args = type("Args", (), {"database_url": self.dsn, "state_file": str(self.tmp / "objects_state.json")})()

        # 1. EcoTaxa samples (zones from the real registry, as the loader's main does).
        samples_loader = load_module("populate_ecotaxa_samples")
        from shapely.geometry import shape
        features = json.loads((ROOT / "shared_data/geo/zones_registry.geojson").read_text(encoding="utf-8"))["features"]
        zones = [(f["properties"].get("canonical"), f["properties"].get("source"), shape(f["geometry"])) for f in features]
        for pid in projects:
            with contextlib.redirect_stdout(io.StringIO()):
                samples_loader.load_project(args, fake, pid, zones)
        # 2. EcoTaxa objects, which also date the samples.
        objects_loader = load_module("populate_ecotaxa_objects")
        for pid in projects:
            with contextlib.redirect_stdout(io.StringIO()):
                objects_loader.load_project(args, fake, pid)
        # 3. EcoPart: the fixture profile is linked to EcoTaxa project 103.
        import psycopg
        from psycopg.rows import dict_row
        ecopart = load_module("populate_ecopart")
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn, contextlib.redirect_stdout(io.StringIO()):
            result = ecopart.load_project(conn, ROOT / "tests/fixtures/ecopart/bins.tsv", 10, [103],
                                          {"103": {"evidence": [{"method": "fixture"}]}})
            conn.commit()
        self.assertEqual(result["mapped_objects"], 3)
        # The real loader (ingest) replays the EcoPart migration after all others: it must apply cleanly.
        with psycopg.connect(self.dsn) as conn:
            conn.execute((ROOT / "docs/warehouse_ecopart_migration.sql").read_text())
            conn.commit()
        # 4. Amundsen CTD (ERDDAP simulated), then 5. CTD zones from coordinates.
        ctd = load_module("populate_amundsen_ctd")
        with mock.patch.object(ctd.requests, "get", side_effect=fake_erddap), \
                mock.patch.object(sys, "argv", ["populate_amundsen_ctd.py", "--database-url", self.dsn]), \
                contextlib.redirect_stdout(io.StringIO()):
            ctd.main()
        zones_script = load_module("assign_filet_zones")
        counts = zones_script.assign(database_url=self.dsn, table="ctd_profile")
        self.assertEqual(counts.get("assigned"), 1)
        # Zone contours (full resolution kept for explore.zone_membership), as load_warehouse.py does.
        # Without PostGIS (non-superuser managed hosting) the table does not exist and
        # load_marine_zones.py skips; zone_membership is then absent too.
        self.postgis = self.owner_sql("SELECT to_regclass('warehouse.marine_zone') IS NOT NULL") == "t"
        zones_loader = load_module("load_marine_zones")
        if self.postgis:
          with psycopg.connect(self.dsn) as conn:
            self.assertGreater(zones_loader.load(conn, ROOT / "shared_data/geo/zones_registry.geojson",
                                                 zones_loader.DEFAULT_TOLERANCE_DEG,
                                                 zones_loader.DEFAULT_MIN_HOLE_AREA_DEG2), 60)
        # 6. FILET from a minimal export, then 7. FILET-UVP candidates.
        samples_csv, abundance_csv, dictionary_csv = filet_fixture(self.tmp)
        filet = load_module("populate_filet")
        loaded = filet.load(samples_csv, abundance_csv, dictionary_csv, self.dsn)
        self.assertEqual((loaded["samples"], loaded["analyses"]), (1, 1))
        matches = subprocess.run([sys.executable, str(SCRIPTS / "populate_filet_uvp_matches.py"), "--database-url", self.dsn],
                                 env=dict(self.admin_env, PGPASSWORD=self.owner_pw), capture_output=True, text=True)
        self.assertEqual(matches.returncode, 0, matches.stderr[-400:])
        # 8. Replay the deployment: catalog entries, ownership, context, release.
        replay = subprocess.run([sys.executable, str(DEPLOY), "--check"], env=self.deploy_env, capture_output=True, text=True)
        self.assertIn(replay.returncode, (0, 2), replay.stdout[-800:] + replay.stderr[-400:])
        self.assertIn("PRÊT", replay.stdout)

    def check_data_and_access(self):
        # Quality: every EcoTaxa sample, object and link arrived exactly once.
        self.assertEqual(self.owner_sql("SELECT count(*) FROM warehouse.ecotaxa_sample"), "5")
        self.assertEqual(self.owner_sql("SELECT count(*) FROM warehouse.ecotaxa_object"), "16")
        self.assertEqual(self.owner_sql("SELECT count(*) FROM (SELECT project_id, sample_id FROM warehouse.ecotaxa_sample "
                                        "GROUP BY 1, 2 HAVING count(*) > 1) d"), "0")
        self.assertEqual(self.owner_sql("SELECT string_agg(marine_zone_assignment_status, ',' ORDER BY sample_id) "
                                        "FROM warehouse.ecotaxa_sample WHERE project_id = 101"), "assigned,outside,unresolved")
        self.assertEqual(self.owner_sql("SELECT count(*) FROM warehouse.ecotaxa_sample WHERE datetime_min IS NULL "
                                        "AND sample_id IN ('1001','1002','2001','100')"), "0")
        # Object size enrichment: per-project obj_free_cols decides what is populated.
        # 101 has no esd (like the lab's UVP6 projects), 102 has no size columns at all,
        # 103 (the UVP project) has all four — area_px/major_px/minor_px on 101's 8 objects
        # plus 103's 4, esd_px on 103's 4 only, nothing on 102's 4.
        self.assertEqual(self.owner_sql("SELECT count(*) FROM warehouse.ecotaxa_object WHERE area_px IS NOT NULL"), "12")
        self.assertEqual(self.owner_sql("SELECT count(*) FROM warehouse.ecotaxa_object WHERE esd_px IS NOT NULL"), "4")
        self.assertEqual(self.owner_sql("SELECT count(*) FROM warehouse.ecotaxa_acquisition"), "4")
        # Annotation status and taxon id from classif_qual/classif_id (V, P, D, V per sample).
        self.assertEqual(self.owner_sql("SELECT string_agg(annotation_status || '=' || n, ',' ORDER BY annotation_status) FROM "
                                        "(SELECT annotation_status, count(*) n FROM warehouse.ecotaxa_object GROUP BY 1) c"),
                         "dubious=4,predicted=4,validated=8")
        self.assertEqual(self.owner_sql("SELECT count(*) FROM warehouse.ecotaxa_object WHERE category_id IS NULL"), "0")
        self.assertEqual(self.owner_sql("SELECT nb_validated || '/' || nb_predicted || '/' || nb_dubious || '/' || nb_unclassified "
                                        "FROM warehouse.ecotaxa_sample WHERE sample_id = '100'"), "2/1/1/0")
        # Abundance under both policies: profile 001 has 3 mapped objects (Calanus V at 0 m and P at 4.999 m,
        # Oithona D at 5 m): validated_only keeps the one validated Calanus.
        self.assertEqual(self.owner_sql("SELECT string_agg(split_part(annotation_policy, ':', 1) || '=' || n, ',' ORDER BY annotation_policy) FROM "
                                        "(SELECT annotation_policy, sum(n_objects_taxon) n FROM warehouse.uvp_taxon_abundance GROUP BY 1) c"),
                         "all_loaded_objects=3,validated_only=1")
        self.assertEqual(self.owner_sql("SELECT DISTINCT taxon_key FROM warehouse.uvp_taxon_abundance "
                                        "WHERE annotation_policy LIKE 'validated_only:%'"), "ecotaxa:id:45072")
        self.assertEqual(self.owner_sql("SELECT string_agg(DISTINCT taxon_key || '=' || taxon_name, ',') FROM explore.uvp_taxon_abundance"),
                         "ecotaxa:id:45072=Calanus,ecotaxa:id:61993=Oithona")
        # Recomputing from loaded objects (after a --refresh) gives the same rows.
        before = self.owner_sql("SELECT md5(string_agg(concat_ws('|', bin_id, taxon_key, annotation_policy, n_objects_taxon), ',' "
                                "ORDER BY bin_id, taxon_key, annotation_policy)) FROM warehouse.uvp_taxon_abundance")
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn, contextlib.redirect_stdout(io.StringIO()):
            load_module("populate_ecopart").recompute_abundance(conn)
        self.assertEqual(before, self.owner_sql("SELECT md5(string_agg(concat_ws('|', bin_id, taxon_key, annotation_policy, n_objects_taxon), ',' "
                                                "ORDER BY bin_id, taxon_key, annotation_policy)) FROM warehouse.uvp_taxon_abundance"))
        # Zones: every zone covering a point, computed in PostGIS on the full-resolution contour.
        self.assertEqual(self.owner_sql("SELECT array_to_string(marine_zone_keys, ',') FROM explore.uvp_projects "
                                        "WHERE ecotaxa_project_id = 103"), "Baie de Baffin")
        if not self.postgis:
            self.assertEqual(self.owner_sql("SELECT to_regclass('explore.zone_membership') IS NULL"), "t")
        else:
          # The fixture point is in Baie de Baffin and in the MEOW West Greenland Shelf ecoregion: the
          # loaders keep the NeoLab zone (priority over MEOW), the view lists both.
          self.assertEqual(self.owner_sql("SELECT string_agg(zone_key || ':' || geometry_resolution, ',' ORDER BY zone_key) "
                                          "FROM explore.zone_membership WHERE row_kind = 'uvp_profile'"),
                           "Baie de Baffin:full,MEOW: West Greenland Shelf:full")
          # A row without coordinates keeps its upstream zone, flagged as such (sample 1003 has none
          # and no zone, so it stays out).
          self.assertEqual(self.owner_sql("SELECT count(*) FROM explore.zone_membership m JOIN warehouse.ecotaxa_sample s "
                                          "ON m.row_kind = 'ecotaxa_sample' AND m.row_id = s.id WHERE s.sample_id = '1003'"), "0")
          self.owner_sql("UPDATE warehouse.uvp_profile SET latitude = NULL")
          self.assertEqual(self.owner_sql("SELECT string_agg(zone_key || ':' || geometry_resolution, ',') FROM explore.zone_membership "
                                          "WHERE row_kind = 'uvp_profile'"), "Baie de Baffin:assigned_without_coordinates")
          self.owner_sql(f"UPDATE warehouse.uvp_profile SET latitude = {BAFFIN[0]}")
          # Every zone a loader assigned is among the zones PostGIS finds for that point.
          self.assertEqual(self.owner_sql("SELECT count(*) FROM warehouse.ecotaxa_sample s WHERE s.marine_zone_assignment_status = 'assigned' "
                                          "AND NOT EXISTS (SELECT 1 FROM explore.zone_membership m WHERE m.row_kind = 'ecotaxa_sample' "
                                          "AND m.row_id = s.id AND m.zone_key = s.marine_zone_key)"), "0")
        self.assertEqual(self.owner_sql("SELECT count(DISTINCT pixel_size_mm) FROM warehouse.ecotaxa_acquisition"), "1")
        self.assertEqual(self.owner_sql("SELECT count(*) FROM warehouse.ecotaxa_ctd"), "5")
        self.assertEqual(self.owner_sql("SELECT count(*) FROM warehouse.ctd_measurement"), "24")
        self.assertEqual(self.owner_sql("SELECT marine_zone_key FROM warehouse.ctd_profile"), "Baie de Baffin")
        # Every loaded version has a catalog entry to carry its contract.
        self.assertEqual(self.owner_sql("SELECT count(*) FROM warehouse.dataset_version v WHERE NOT EXISTS "
                                        "(SELECT 1 FROM warehouse.dataset_metadata m WHERE m.dataset_version_id = v.id)"), "0")
        # Contracts on the loaded versions, then a scoped account: C1, Baffin, 2024.
        for key, contract in (("101", "C1"), ("102", "C2"), ("103", "C1"), ("10", "C1"), ("amundsen12713", "C1"),
                              ("neolab-filet", "C1")):
            out = subprocess.run([sys.executable, str(SCRIPTS / "warehouse_user.py"), "contract", "--dataset-key", key,
                                  "--contract", contract], env=self.deploy_env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
        user = subprocess.run([sys.executable, str(SCRIPTS / "warehouse_user.py"), "create", self.scoped,
                               "--source", "ecotaxa,ecopart", "--contract", "C1", "--zone", "Baie de Baffin",
                               "--year-min", "2024", "--year-max", "2024", "--out-dir", str(self.tmp)],
                              env=self.deploy_env, capture_output=True, text=True)
        self.assertEqual(user.returncode, 0, user.stderr)
        self.owner_sql(f"SELECT 1")  # owner still writes and reads after all replays
        bundle = (self.tmp / f"{self.scoped}.env").read_text(encoding="utf-8")
        scoped_pw = next(line.split("=", 1)[1] for line in bundle.splitlines() if line.startswith("WAREHOUSE_DB_PASSWORD="))
        scoped = lambda sql: self.as_role(self.scoped, sql, scoped_pw)
        self.assertEqual(scoped("SELECT string_agg(DISTINCT ecotaxa_native_sample_id, ',') FROM explore.uvp_samples"), "100")
        self.assertEqual(scoped("SELECT count(*) FROM explore.uvp_objects"), "4")
        # Real-unit size, scoped: only project 103's objects, converted via the
        # acquisition's calibration (major_px 20.0 * pixel_size_mm 0.01 * 1000 = 200 um).
        self.assertEqual(scoped("SELECT count(*) FROM explore.uvp_object_sizes"), "4")
        self.assertEqual(scoped("SELECT major_um FROM explore.uvp_object_sizes WHERE object_id = '40000'"), "200")
        self.assertEqual(scoped("SELECT pixel_size_mm FROM explore.uvp_object_sizes WHERE object_id = '40000'"), "0.01")
        self.assertEqual(scoped("SELECT count(*) FROM explore.uvp_taxon_abundance WHERE n_objects_taxon > 0") != "0", True)
        # Read-time zeros: every bin of the profile carries each observed taxon, even without objects.
        self.assertNotEqual(scoped("SELECT count(*) FROM explore.uvp_taxon_abundance WHERE n_objects_taxon = 0"), "0")
        self.assertEqual(scoped("SELECT count(*) FROM explore.uvp_projects WHERE ecotaxa_project_id = 103"), "1")
        self.assertEqual(scoped("SELECT my_scope FROM explore.my_datasets WHERE dataset_key = '102'"), "aucun")
        # Views over every EcoTaxa project and CTD profile, not only the UVP-linked ones
        # (3 novembre 2026): the owner sees all three projects and their 16 objects, with
        # object_count filled; the scoped account sees only its C1/Baffin/2024 samples
        # (1001 and 100) and no CTD (source not granted).
        self.assertEqual(self.owner_sql("SELECT count(*) || '/' || sum(n_objects) || '/' || sum(n_validated) FROM explore.ecotaxa_projects"), "3/16/8")
        self.assertEqual(self.owner_sql("SELECT count(*) FROM explore.ecotaxa_samples WHERE object_count = 4"), "4")
        self.assertEqual(self.owner_sql("SELECT count(*) FROM explore.ctd_profiles"), "1")
        self.assertEqual(self.owner_sql("SELECT count(DISTINCT variable_name) FROM explore.ctd_measurements"), "8")
        self.assertEqual(scoped("SELECT string_agg(ecotaxa_native_sample_id, ',' ORDER BY ecotaxa_native_sample_id) FROM explore.ecotaxa_samples"), "100,1001")
        self.assertEqual(scoped("SELECT count(*) FROM explore.ecotaxa_objects"), "8")
        self.assertEqual(scoped("SELECT count(*) FROM explore.ctd_profiles"), "0")
        # A person opening explore in a SQL client finds every view and column described.
        self.assertEqual(self.owner_sql("SELECT count(*) FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid "
                                        "AND a.attnum > 0 AND NOT a.attisdropped WHERE c.relnamespace = 'explore'::regnamespace "
                                        "AND c.relkind = 'v' AND col_description(c.oid, a.attnum) IS NULL"), "0")
        # Catalog titles name the source instead of a placeholder.
        self.assertEqual(scoped("SELECT title FROM explore.my_datasets WHERE dataset_key = '101'"), "EcoTaxa 101 — Projet C1")
        reader = self.as_role("warehouse_reader", "SELECT count(*) FROM explore.uvp_objects", "reader-pw")
        self.assertEqual(reader, "4")  # only project 103 has a UVP profile; the reader sees it all
        verify = subprocess.run([sys.executable, str(DEPLOY), "--verify"], env=self.deploy_env, capture_output=True, text=True)
        self.assertIn(verify.returncode, (0, 2), verify.stdout[-800:])
        # The post-load quality audit runs as the read-only role, as load_warehouse.py does.
        audit_env = dict(self.deploy_env, WAREHOUSE_READER_HOST=self.deploy_env["WAREHOUSE_POSTGRES_HOST"],
                         WAREHOUSE_READER_PORT=self.deploy_env["WAREHOUSE_POSTGRES_PORT"], WAREHOUSE_READER_DB=self.db)
        audit = subprocess.run([sys.executable, str(SCRIPTS / "audit_warehouse.py")], env=audit_env,
                               capture_output=True, text=True)
        self.assertEqual(audit.returncode, 0, audit.stderr[-400:] + audit.stdout[-400:])
        self.assertIn('"uvp_objects"', audit.stdout)

    def test_superuser_owner_docker_case(self):
        self.prepare(superuser=True)
        self.run_chain()
        self.check_data_and_access()

    def test_non_superuser_owner_managed_hosting_case(self):
        self.prepare(superuser=False)
        self.run_chain()
        self.check_data_and_access()


class LoadRunbookTests(unittest.TestCase):
    """scripts/load_warehouse.py: preflight and plan, without loading anything."""

    def runbook(self):
        return load_module("load_warehouse")

    def test_plan_follows_the_dependency_order(self):
        module = self.runbook()
        args = type("A", (), dict(all_projects=False, project_id=149, filet_dir=None))()
        labels = [label for label, _ in module.steps(args, "host=h dbname=d")]
        self.assertEqual(labels[:5], ["échantillons EcoTaxa", "objets EcoTaxa", "profils EcoPart liés",
                                      "profils CTD Amundsen", "zones des profils CTD"])
        self.assertEqual(labels[-2:], ["contours des zones maritimes", "rejeu du déploiement et rapport"])
        self.assertNotIn("FILET", labels)

    def test_filet_runs_only_when_its_three_exports_are_present(self):
        module = self.runbook()
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        args = type("A", (), dict(all_projects=True, project_id=None, filet_dir=str(directory)))()
        prefix = "project_IDEA_taxonomy_samples+analyses-data_&_metadata-20260526"
        for suffix in list(module.FILET_SUFFIXES.values())[:2]:
            (directory / (prefix + suffix)).write_text("x")
        self.assertNotIn("FILET", [label for label, _ in module.steps(args, "c")])
        (directory / (prefix + list(module.FILET_SUFFIXES.values())[2])).write_text("x")
        labels = [label for label, _ in module.steps(args, "c")]
        self.assertLess(labels.index("FILET"), labels.index("appariements FILET–UVP"))

    def test_preflight_refuses_without_source_credentials_and_never_prints_secrets(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ECOTAXA_", "WAREHOUSE_", "PG"))}
        env["WAREHOUSE_POSTGRES_PASSWORD"] = "s3cr3t-owner"
        env["WAREHOUSE_POSTGRES_HOST"] = "host-inexistant.invalid"
        result = subprocess.run([sys.executable, str(SCRIPTS / "load_warehouse.py"), "--preflight"], env=env,
                                capture_output=True, text=True, cwd=tempfile.gettempdir())
        self.assertEqual(result.returncode, 1)
        self.assertIn("ECOTAXA_USERNAME", result.stdout)
        self.assertNotIn("s3cr3t-owner", result.stdout + result.stderr)

    def test_every_loader_uses_the_warehouse_database_by_default(self):
        for name in ("populate_ecotaxa_samples", "populate_ecotaxa_objects"):
            source = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
            self.assertNotIn("postgresql://localhost/postgres", source, name)
        self.assertIn('os.getenv("WAREHOUSE_POSTGRES_HOST"', (SCRIPTS / "populate_ecopart.py").read_text(encoding="utf-8"))

    def test_no_loader_copies_directly_into_a_protected_table(self):
        import re
        for path in SCRIPTS.glob("populate_*.py"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"COPY warehouse\.", path.name)

    def test_loader_dependencies_are_declared(self):
        declared = (SCRIPTS / "requirements-warehouse.txt").read_text(encoding="utf-8").lower()
        for package in ("pandas", "shapely", "psycopg", "requests", "python-dotenv", "beautifulsoup4"):
            self.assertIn(package, declared)


if __name__ == "__main__":
    unittest.main()
