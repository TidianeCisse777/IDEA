#!/usr/bin/env python3
"""Charge les objets EcoTaxa par pages de 5 000 et enrichit les dates sample.

Taille des objets : EcoTaxa stocke area/esd/major/minor comme des "colonnes
libres" nommees par projet (obj_free_cols mappe un libelle stable vers un
slot propre au projet). Un libelle absent du projet est retire en silence de
la ligne au lieu de revenir NULL, ce qui decale les colonnes suivantes : on
ne doit donc jamais demander une liste fixe, mais determiner par projet quels
libelles existent (une fois, via GET /projects/{id}) puis parser en
consequence. Confirme en direct sur l'API reelle (voir ROADMAP, 30 octobre
2026). La calibration pixel->mm n'est pas un champ d'objet : elle vit sur
l'acquisition (GET /acquisition/{id}.free_columns.pixel, en mm/pixel) et est
recuperee une fois par acquisition, pas par objet.
"""
from __future__ import annotations
import argparse, csv, io, json, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from dotenv import load_dotenv

BASE='https://ecotaxa.obs-vlfr.fr/api'; PAGE=5000
SIZE_LABELS=('area','esd','major','minor')

def psql(db, sql, stdin=None):
    # A list runs as successive -c in one session: psql refuses COPY FROM STDIN
    # inside a single multi-statement -c ("unexpected COPY_IN result").
    commands=[part for item in ([sql] if isinstance(sql,str) else sql) for part in ('-c',item)]
    r=subprocess.run(['psql','-X','-v','ON_ERROR_STOP=1','-At','-F','\t',db,*commands],input=stdin,text=True,capture_output=True)
    if r.returncode: raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r.stdout

def default_database():
    '''Same connection as the other warehouse scripts: WAREHOUSE_DATABASE_URL, or the
    WAREHOUSE_POSTGRES_* variables (password through PGPASSWORD, never in argv).'''
    if os.getenv('WAREHOUSE_DATABASE_URL'):
        return os.environ['WAREHOUSE_DATABASE_URL']
    if os.getenv('WAREHOUSE_POSTGRES_PASSWORD'):
        os.environ.setdefault('PGPASSWORD', os.environ['WAREHOUSE_POSTGRES_PASSWORD'])
    return 'host=%s port=%s dbname=%s user=%s' % (
        os.getenv('WAREHOUSE_POSTGRES_HOST', 'localhost'), os.getenv('WAREHOUSE_POSTGRES_PORT', '55432'),
        os.getenv('WAREHOUSE_POSTGRES_DB', 'neolab_warehouse'), os.getenv('WAREHOUSE_POSTGRES_USER', 'neolab'))

def login():
    s=requests.Session(); r=s.post(BASE+'/login',json={'username':os.environ['ECOTAXA_USERNAME'],'password':os.environ['ECOTAXA_PASSWORD']},timeout=30); r.raise_for_status(); p=r.json(); t=p.get('token') if isinstance(p,dict) else p; s.headers['Authorization']=f'Bearer {t}'; return s

def project_size_labels(s, pid):
    '''Labels among SIZE_LABELS this project actually defines (obj_free_cols), in
    SIZE_LABELS order. A label this project does not have must never be requested:
    EcoTaxa drops it from the row instead of returning null, shifting later columns.'''
    r=s.get(f'{BASE}/projects/{pid}',timeout=30); r.raise_for_status()
    free_cols=r.json().get('obj_free_cols') or {}
    return [lbl for lbl in SIZE_LABELS if lbl in free_cols]

def load_project(args,s,pid):
    db=args.database_url or default_database(); total=int(psql(db,f'SELECT object_count::bigint FROM warehouse.ecotaxa_project WHERE project_id={pid}').strip() or 0)
    mapping={line.split('\t')[0]:int(line.split('\t')[1]) for line in psql(db,f"SELECT sample_id,id FROM warehouse.ecotaxa_sample WHERE project_id={pid}").splitlines() if '\t' in line}
    if not mapping: print(f'[objects] projet {pid}: aucun sample parent, ignoré'); return 0
    size_labels=project_size_labels(s,pid)
    base_fields='obj.orig_id,obj.objdate,obj.depth_min,obj.depth_max,obj.latitude,obj.longitude,txo.display_name'
    fields=base_fields + (',' + ','.join(f'fre.{lbl}' for lbl in size_labels) if size_labels else '')
    base_n=7
    loaded=0; state=Path(args.state_file); states=json.loads(state.read_text()) if state.exists() else {}; offset=int(states.get(str(pid),0))
    acquisitions_seen={}  # acquisition_id -> internal sample_id, for the pixel-size pass at the end
    def fetch_page(start):
        for attempt in range(1, 4):
            try:
                r=s.post(f'{BASE}/object_set/{pid}/query',params={'fields':fields,'order_field':'obj.objid','window_start':start,'window_size':PAGE},json={},timeout=180); r.raise_for_status(); return r.json()
            except requests.RequestException:
                if attempt == 3: raise
                time.sleep(attempt * 2)
    with ThreadPoolExecutor(max_workers=6) as pool:
      while offset < total:
        starts=list(range(offset,min(total,offset+PAGE*6),PAGE))
        for data in pool.map(fetch_page, starts):
          ids=data.get('object_ids',[]); samples=data.get('sample_ids',[]); acqs=data.get('acquisition_ids',[]); rows=data.get('details',[])
          if not ids: continue
          buf=io.StringIO(); w=csv.writer(buf,delimiter='\t',lineterminator='\n')
          for i,row in enumerate(rows):
              if i>=len(ids) or i>=len(samples) or str(samples[i]) not in mapping: continue
              sample_pk=mapping[str(samples[i])]
              acq=str(acqs[i]) if i<len(acqs) else None
              if acq: acquisitions_seen[acq]=sample_pk
              size_vals={lbl: (row[base_n+j] if base_n+j<len(row) else None) for j,lbl in enumerate(size_labels)}
              vals=[sample_pk,str(ids[i]),acq,None,None,row[6] if len(row)>6 else None,None,row[1] if len(row)>1 else None,row[2] if len(row)>2 else None,row[3] if len(row)>3 else None,row[4] if len(row)>4 else None,row[5] if len(row)>5 else None,
                    size_vals.get('area'),size_vals.get('esd'),size_vals.get('major'),size_vals.get('minor')]
              w.writerow(['\\N' if v is None or v=='' else v for v in vals])
          sql=["""CREATE TEMP TABLE stage_ecotaxa_object(sample_id bigint,object_id text,acquisition_id text,process_id text,category_id text,category_name text,annotation_status text,object_datetime timestamptz,depth_min_m double precision,depth_max_m double precision,object_lat double precision,object_lon double precision,area_px double precision,esd_px double precision,major_px double precision,minor_px double precision)""", """COPY stage_ecotaxa_object FROM STDIN WITH (FORMAT csv,DELIMITER E'\\t',NULL '\\N')""", """INSERT INTO warehouse.ecotaxa_object(sample_id,object_id,acquisition_id,process_id,category_id,category_name,annotation_status,object_datetime,depth_min_m,depth_max_m,object_lat,object_lon,area_px,esd_px,major_px,minor_px) SELECT sample_id,object_id,acquisition_id,process_id,category_id,category_name,annotation_status,object_datetime,depth_min_m,depth_max_m,object_lat,object_lon,area_px,esd_px,major_px,minor_px FROM stage_ecotaxa_object ON CONFLICT (sample_id,object_id) DO UPDATE SET acquisition_id=EXCLUDED.acquisition_id,category_name=EXCLUDED.category_name,object_datetime=EXCLUDED.object_datetime,depth_min_m=EXCLUDED.depth_min_m,depth_max_m=EXCLUDED.depth_max_m,object_lat=EXCLUDED.object_lat,object_lon=EXCLUDED.object_lon,area_px=EXCLUDED.area_px,esd_px=EXCLUDED.esd_px,major_px=EXCLUDED.major_px,minor_px=EXCLUDED.minor_px"""]
          psql(db,sql,stdin=buf.getvalue()); loaded += len(ids); offset += len(ids); states[str(pid)]=offset; state.parent.mkdir(parents=True,exist_ok=True); state.write_text(json.dumps(states,indent=2))
          print(f'[objects] projet {pid}: {min(offset,total)}/{total} objets',flush=True)
    if loaded or offset>=total:
        psql(db,f"""UPDATE warehouse.ecotaxa_sample s SET datetime_min=a.min_date,datetime_max=a.max_date FROM (SELECT o.sample_id,min(o.object_datetime) AS min_date,max(o.object_datetime) AS max_date FROM warehouse.ecotaxa_object o JOIN warehouse.ecotaxa_sample es ON es.id=o.sample_id WHERE es.project_id={pid} AND o.object_datetime IS NOT NULL GROUP BY o.sample_id) a WHERE s.id=a.sample_id""")
    load_acquisition_pixel_sizes(s, db, acquisitions_seen)
    return loaded

def load_acquisition_pixel_sizes(s, db, acquisitions_seen):
    '''One GET /acquisition/{id} per distinct acquisition not already stored, threaded
    like the object pages. free_columns.pixel is the mm/pixel calibration EcoTaxa
    carries on the acquisition (confirmed live, not documented in the object schema);
    projects that do not define it leave pixel_size_mm NULL, never a guessed value.'''
    if not acquisitions_seen: return
    known=set(psql(db, "SELECT acquisition_id FROM warehouse.ecotaxa_acquisition").split())
    todo=[a for a in acquisitions_seen if a not in known]
    if not todo: return
    def fetch_one(acq_id):
        for attempt in range(1, 4):
            try:
                r=s.get(f'{BASE}/acquisition/{acq_id}',timeout=30); r.raise_for_status()
                pixel=(r.json().get('free_columns') or {}).get('pixel')
                return acq_id, (float(pixel) if pixel not in (None,'') else None)
            except requests.RequestException:
                if attempt == 3: raise
                time.sleep(attempt * 2)
    buf=io.StringIO(); w=csv.writer(buf,delimiter='\t',lineterminator='\n'); n=0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for acq_id, pixel_mm in pool.map(fetch_one, todo):
            w.writerow([acq_id, acquisitions_seen[acq_id], '\\N' if pixel_mm is None else pixel_mm]); n+=1
    if n:
        sql=["""CREATE TEMP TABLE stage_ecotaxa_acquisition(acquisition_id text,sample_id bigint,pixel_size_mm double precision)""",
             """COPY stage_ecotaxa_acquisition FROM STDIN WITH (FORMAT csv,DELIMITER E'\\t',NULL '\\N')""",
             """INSERT INTO warehouse.ecotaxa_acquisition(acquisition_id,sample_id,pixel_size_mm) SELECT acquisition_id,sample_id,pixel_size_mm FROM stage_ecotaxa_acquisition ON CONFLICT (acquisition_id) DO UPDATE SET pixel_size_mm=EXCLUDED.pixel_size_mm"""]
        psql(db,sql,stdin=buf.getvalue())
        print(f'[objects] calibration pixel: {n} acquisitions',flush=True)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project-id',type=int); ap.add_argument('--all-projects',action='store_true'); ap.add_argument('--database-url'); ap.add_argument('--state-file',default='data/warehouse_staging/ecotaxa_objects_state.json'); args=ap.parse_args()
    if bool(args.project_id)==bool(args.all_projects): raise SystemExit('indiquer exactement --project-id ou --all-projects')
    root=Path(__file__).resolve().parents[1]; load_dotenv(root/'.env',override=True); load_dotenv(root/'.env.warehouse'); s=login(); db=args.database_url or default_database(); ids=[args.project_id]
    if args.all_projects: ids=[int(x) for x in psql(db,'SELECT project_id FROM warehouse.ecotaxa_project ORDER BY project_id').split()]
    total=0
    for n,pid in enumerate(ids,1): print(f'[objects] progression projets {n}/{len(ids)}',flush=True); total+=load_project(args,s,pid)
    print(f'[objects] terminé: {len(ids)} projets, {total} objets traités',flush=True)
if __name__=='__main__': main()
