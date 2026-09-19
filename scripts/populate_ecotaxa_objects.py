#!/usr/bin/env python3
"""Charge les objets EcoTaxa par pages de 5 000 et enrichit les dates sample."""
from __future__ import annotations
import argparse, csv, io, json, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from dotenv import load_dotenv

BASE='https://ecotaxa.obs-vlfr.fr/api'; PAGE=5000

def psql(db, sql, stdin=None):
    r=subprocess.run(['psql','-X','-v','ON_ERROR_STOP=1','-At','-F','\t',db,'-c',sql],input=stdin,text=True,capture_output=True)
    if r.returncode: raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r.stdout

def login():
    s=requests.Session(); r=s.post(BASE+'/login',json={'username':os.environ['ECOTAXA_USERNAME'],'password':os.environ['ECOTAXA_PASSWORD']},timeout=30); r.raise_for_status(); p=r.json(); t=p.get('token') if isinstance(p,dict) else p; s.headers['Authorization']=f'Bearer {t}'; return s

def load_project(args,s,pid):
    db=args.database_url or 'postgresql://localhost/postgres'; total=int(psql(db,f'SELECT object_count::bigint FROM warehouse.ecotaxa_project WHERE project_id={pid}').strip() or 0)
    mapping={line.split('\t')[0]:int(line.split('\t')[1]) for line in psql(db,f"SELECT sample_id,id FROM warehouse.ecotaxa_sample WHERE project_id={pid}").splitlines() if '\t' in line}
    if not mapping: print(f'[objects] projet {pid}: aucun sample parent, ignoré'); return 0
    fields='obj.orig_id,obj.objdate,obj.depth_min,obj.depth_max,obj.latitude,obj.longitude,txo.display_name'
    loaded=0; state=Path(args.state_file); states=json.loads(state.read_text()) if state.exists() else {}; offset=int(states.get(str(pid),0))
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
              vals=[mapping[str(samples[i])],str(ids[i]),str(acqs[i]) if i<len(acqs) else None,None,None,row[6] if len(row)>6 else None,None,row[1] if len(row)>1 else None,row[2] if len(row)>2 else None,row[3] if len(row)>3 else None,row[4] if len(row)>4 else None,row[5] if len(row)>5 else None]
              w.writerow(['\\N' if v is None or v=='' else v for v in vals])
          sql="""CREATE TEMP TABLE stage_ecotaxa_object(sample_id bigint,object_id text,acquisition_id text,process_id text,category_id text,category_name text,annotation_status text,object_datetime timestamptz,depth_min_m double precision,depth_max_m double precision,object_lat double precision,object_lon double precision) ON COMMIT DROP; COPY stage_ecotaxa_object FROM STDIN WITH (FORMAT csv,DELIMITER E'\\t',NULL '\\N'); INSERT INTO warehouse.ecotaxa_object(sample_id,object_id,acquisition_id,process_id,category_id,category_name,annotation_status,object_datetime,depth_min_m,depth_max_m,object_lat,object_lon) SELECT sample_id,object_id,acquisition_id,process_id,category_id,category_name,annotation_status,object_datetime,depth_min_m,depth_max_m,object_lat,object_lon FROM stage_ecotaxa_object ON CONFLICT (sample_id,object_id) DO UPDATE SET acquisition_id=EXCLUDED.acquisition_id,category_name=EXCLUDED.category_name,object_datetime=EXCLUDED.object_datetime,depth_min_m=EXCLUDED.depth_min_m,depth_max_m=EXCLUDED.depth_max_m,object_lat=EXCLUDED.object_lat,object_lon=EXCLUDED.object_lon;"""
          psql(db,sql,stdin=buf.getvalue()); loaded += len(ids); offset += len(ids); states[str(pid)]=offset; state.parent.mkdir(parents=True,exist_ok=True); state.write_text(json.dumps(states,indent=2))
          print(f'[objects] projet {pid}: {min(offset,total)}/{total} objets',flush=True)
    if loaded or offset>=total:
        psql(db,f"""UPDATE warehouse.ecotaxa_sample s SET datetime_min=a.min_date,datetime_max=a.max_date FROM (SELECT o.sample_id,min(o.object_datetime) AS min_date,max(o.object_datetime) AS max_date FROM warehouse.ecotaxa_object o JOIN warehouse.ecotaxa_sample es ON es.id=o.sample_id WHERE es.project_id={pid} AND o.object_datetime IS NOT NULL GROUP BY o.sample_id) a WHERE s.id=a.sample_id""")
    return loaded

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project-id',type=int); ap.add_argument('--all-projects',action='store_true'); ap.add_argument('--database-url'); ap.add_argument('--state-file',default='data/warehouse_staging/ecotaxa_objects_state.json'); args=ap.parse_args()
    if bool(args.project_id)==bool(args.all_projects): raise SystemExit('indiquer exactement --project-id ou --all-projects')
    root=Path(__file__).resolve().parents[1]; load_dotenv(root/'.env',override=True); s=login(); db=args.database_url or 'postgresql://localhost/postgres'; ids=[args.project_id]
    if args.all_projects: ids=[int(x) for x in psql(db,'SELECT project_id FROM warehouse.ecotaxa_project ORDER BY project_id').split()]
    total=0
    for n,pid in enumerate(ids,1): print(f'[objects] progression projets {n}/{len(ids)}',flush=True); total+=load_project(args,s,pid)
    print(f'[objects] terminé: {len(ids)} projets, {total} objets traités',flush=True)
if __name__=='__main__': main()
