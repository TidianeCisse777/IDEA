#!/usr/bin/env python3
"""Charge un ou tous les projets EcoTaxa et leurs samples dans PostgreSQL."""
from __future__ import annotations
import argparse, csv, hashlib, io, json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from dotenv import load_dotenv
from shapely.geometry import Point, shape

BASE = "https://ecotaxa.obs-vlfr.fr/api"

def sql(value):
    if value is None: return "NULL"
    return "'" + str(value).replace("'", "''") + "'"

def psql(db, statement, stdin=None):
    r = subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-At", db, "-c", statement], input=stdin, text=True, capture_output=True)
    if r.returncode: raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r.stdout.strip()

def zone_for(lon, lat, features):
    if lon is None or lat is None: return (None, None, None, "unresolved")
    point = Point(float(lon), float(lat))
    hits = [(canonical, source) for canonical, source, geometry in features if geometry.covers(point)]
    preferred = [h for h in hits if not str(h[0]).startswith("MEOW:")]
    if len(preferred) == 1: return (preferred[0][0], preferred[0][0], preferred[0][1], "assigned")
    if len(hits) == 1: return (hits[0][0], hits[0][0], hits[0][1], "assigned")
    if len(hits) > 1: return ("AMBIGUOUS", "AMBIGUOUS", "zones_registry.geojson", "ambiguous")
    return ("HORS_ARCTIQUE_CANADIEN", "HORS_ARCTIQUE_CANADIEN", "zones_registry.geojson", "outside")

def login():
    user, password = os.getenv("ECOTAXA_USERNAME"), os.getenv("ECOTAXA_PASSWORD")
    if not user or not password: raise SystemExit("ECOTAXA_USERNAME/ECOTAXA_PASSWORD manquants")
    s = requests.Session(); s.headers["Accept"] = "application/json"
    r = s.post(BASE + "/login", json={"username": user, "password": password}, timeout=30); r.raise_for_status()
    payload = r.json(); token = payload.get("token") if isinstance(payload, dict) else payload
    s.headers["Authorization"] = f"Bearer {token}"; return s

def load_project(args, session, project_id, zones):
    db = args.database_url or os.getenv("WAREHOUSE_DATABASE_URL") or "postgresql://localhost/postgres"
    print(f"[ecotaxa] projet {project_id}: métadonnées", flush=True)
    project = session.get(f"{BASE}/projects/{project_id}", timeout=30); project.raise_for_status(); project = project.json()
    response = session.get(BASE + "/samples/search", params={"project_ids": str(project_id), "id_pattern": "*"}, timeout=30); response.raise_for_status()
    samples = response.json(); detailed = []
    existing = psql(db, f"SELECT count(*) FROM warehouse.ecotaxa_sample WHERE project_id={project_id}")
    if existing.isdigit() and int(existing) == len(samples) and len(samples) > 0:
        print(f"[ecotaxa] projet {project_id}: déjà chargé ({len(samples)} samples), ignoré", flush=True)
        return len(samples)
    def fetch_detail(sample):
        detail = session.get(f"{BASE}/sample/{sample['sampleid']}", timeout=30); detail.raise_for_status(); return detail.json()
    with ThreadPoolExecutor(max_workers=8) as pool:
        for number, detail in enumerate(pool.map(fetch_detail, samples), 1):
            detailed.append(detail)
            if number == 1 or number == len(samples) or number % 25 == 0: print(f"[ecotaxa] projet {project_id}: samples {number}/{len(samples)}", flush=True)
    samples = detailed
    manifest = json.dumps({"project": project, "samples": samples}, sort_keys=True, ensure_ascii=False).encode(); digest = hashlib.sha256(manifest).hexdigest()
    version = psql(db, f"""INSERT INTO warehouse.dataset_version(source_instance,dataset_key,version_key,file_manifest_uri,sha256)
      VALUES ('ecotaxa',{sql(project_id)},{sql('current')},{sql(BASE+'/projects/'+str(project_id))},{sql(digest)})
      ON CONFLICT (source_instance,dataset_key,version_key) DO UPDATE SET file_manifest_uri=EXCLUDED.file_manifest_uri,sha256=EXCLUDED.sha256 RETURNING id""")
    version_id = int(version.splitlines()[0])
    psql(db, """CREATE TABLE IF NOT EXISTS warehouse.ecotaxa_project (project_id bigint PRIMARY KEY,title text NOT NULL,instrument text,status text,object_count bigint,source_instance text NOT NULL,dataset_version_id bigint NOT NULL REFERENCES warehouse.dataset_version)""")
    psql(db, f"""INSERT INTO warehouse.ecotaxa_project(project_id,title,instrument,status,object_count,source_instance,dataset_version_id)
      VALUES ({project_id},{sql(project.get('title'))},{sql(project.get('instrument'))},{sql(project.get('status'))},{sql(int(project['objcount']) if project.get('objcount') is not None else None)},'ecotaxa',{version_id})
      ON CONFLICT (project_id) DO UPDATE SET title=EXCLUDED.title,instrument=EXCLUDED.instrument,status=EXCLUDED.status,object_count=EXCLUDED.object_count,dataset_version_id=EXCLUDED.dataset_version_id""")
    psql(db, f"DELETE FROM warehouse.ecotaxa_sample WHERE dataset_version_id={version_id} AND project_id={project_id}")
    copy_data = io.StringIO(); writer = csv.writer(copy_data, delimiter="\t", lineterminator="\n")
    for number, sample in enumerate(samples, 1):
        free = sample.get("free_columns") or {}; zkey,zname,zsource,zstatus = zone_for(sample.get("longitude"), sample.get("latitude"), zones)
        values = [version_id,project_id,sample.get("sampleid"),sample.get("orig_id") or sample.get("sampleid"),free.get("stationid"),free.get("cruise"),free.get("profileid"),free.get("ctdrosettefilename"),sample.get("latitude"),sample.get("longitude"),zkey,zname,zsource,"registry-v1",zstatus,json.dumps(free,ensure_ascii=False)]
        writer.writerow(["\\N" if v is None or v == "" else v for v in values])
    psql(db, "COPY warehouse.ecotaxa_sample(dataset_version_id,project_id,sample_id,sample_orig_id,station_id,cruise_id,profile_id,ctd_rosette_filename,lat_avg,lon_avg,marine_zone_key,marine_zone_name,marine_zone_source,marine_zone_version,marine_zone_assignment_status,free_fields_json) FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N')", stdin=copy_data.getvalue())
    print(f"[ecotaxa] projet {project_id}: chargé ({len(samples)} samples, version {version_id})", flush=True)
    return len(samples)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--project-id", type=int); ap.add_argument("--all-projects", action="store_true"); ap.add_argument("--database-url"); ap.add_argument("--zones", default="shared_data/geo/zones_registry.geojson"); args = ap.parse_args()
    if bool(args.project_id) == bool(args.all_projects): raise SystemExit("indiquer exactement --project-id ou --all-projects")
    root = Path(__file__).resolve().parents[1]; load_dotenv(root / ".env", override=True)
    raw_zones = json.loads((root / args.zones).read_text(encoding="utf-8"))["features"]
    zones = [(f["properties"].get("canonical"), f["properties"].get("source"), shape(f["geometry"])) for f in raw_zones]
    session = login()
    if args.all_projects:
        response = session.get(BASE + "/projects/search", params={"title_filter":"","instrument_filter":"","window_start":0,"window_size":10000,"order_field":"projid"}, timeout=60); response.raise_for_status(); projects = response.json()
        print(f"[ecotaxa] {len(projects)} projets accessibles", flush=True); total = 0
        for number, item in enumerate(projects, 1):
            pid = int(item.get("projid") or item.get("project_id")); print(f"[ecotaxa] progression projets {number}/{len(projects)}", flush=True); total += load_project(args, session, pid, zones)
        print(f"[ecotaxa] terminé: {len(projects)} projets, {total} samples", flush=True)
    else: load_project(args, session, args.project_id, zones)

if __name__ == "__main__": main()
