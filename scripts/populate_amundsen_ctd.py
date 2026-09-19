#!/usr/bin/env python3
"""Charge les profils CTD Amundsen correspondant aux fichiers EcoTaxa."""
from __future__ import annotations
import argparse,csv,hashlib,io,os,re,subprocess,time
from collections import defaultdict
from pathlib import Path
import pandas as pd, requests
from dotenv import load_dotenv

BASE='https://erddap.amundsenscience.com/erddap/tabledap/amundsen12713.csv'; BATCH=20
VARS={'PRES':('pression / profondeur','dbar'),'TE90':('température','degC'),'PSAL':('salinité','PSU'),'SIGT':('densité','kg/m3'),'OXYM':('oxygène','uM'),'pH':('pH','1'),'NTRA':('nitrate','mmol/m3'),'FLOR':('fluorescence','ug/L')}

def psql(db,sql,stdin=None):
 env=os.environ.copy();
 if os.getenv('WAREHOUSE_POSTGRES_PASSWORD'): env['PGPASSWORD']=os.getenv('WAREHOUSE_POSTGRES_PASSWORD')
 r=subprocess.run(['psql','-X','-v','ON_ERROR_STOP=1','-At','-F','\t',db,'-c',sql],input=stdin,text=True,capture_output=True,env=env)
 if r.returncode: raise RuntimeError(r.stderr.strip() or r.stdout.strip())
 return r.stdout

def norm(v):
 s=str(v).strip(); m=re.fullmatch(r'(\d{4})(\d{3})',s)
 return f'{m.group(1)}_{m.group(2)}.int.nc' if m else s

def fetch(names):
 regex='^('+'|'.join(re.escape(n) for n in names)+')$'; q='filename,time,latitude,longitude,station,cast_number,'+','.join(VARS)
 url=BASE+'?'+q+'&filename=~"'+regex+'"'
 for attempt in range(3):
  try:
   r=requests.get(url,timeout=180); r.raise_for_status(); lines=r.text.splitlines(); return pd.read_csv(io.StringIO('\n'.join([lines[0]]+lines[2:])))
  except requests.HTTPError as exc:
   if exc.response is not None and exc.response.status_code == 404: return pd.DataFrame()
   if attempt==2: raise
   time.sleep(2*(attempt+1))

def resolve_by_position(samples):
 """Résout les codes courts par jour + position dans l'ERDDAP Amundsen."""
 byday=defaultdict(list)
 for s in samples:
  try:
   if s[4] and s[5] and s[6]:
    s = list(s); s[5] = float(s[5]); s[6] = float(s[6]); byday[s[4][:10]].append(s)
  except (ValueError, TypeError):
   continue
 resolved={}; byyear=defaultdict(list)
 for day, group in byday.items(): byyear[day[:4]].extend(group)
 frames={}
 for year in [y for y in byyear if y in {'2023','2024'}]:
  url=f"{BASE}?filename,time,latitude,longitude,station,cast_number,PRES&time>={year}-01-01T00:00:00Z&time<={year}-12-31T23:59:59Z&PRES=3"
  frames[year]=pd.DataFrame()
  for attempt in range(3):
   try:
    r=requests.get(url,timeout=(10,45)); lines=r.text.splitlines()
    frames[year]=pd.read_csv(io.StringIO('\n'.join([lines[0]]+lines[2:]))) if r.status_code==200 and len(lines)>2 else pd.DataFrame()
    break
   except requests.RequestException:
    if attempt < 2: time.sleep(2*(attempt+1))
 for day,group in byday.items():
  frame=frames.get(day[:4],pd.DataFrame())
  if frame.empty: continue
  frame=frame[frame.time.astype(str).str[:10] == day]
  for s in group:
   if frame.empty: continue
   distance=((frame.latitude-s[5])**2+(frame.longitude-s[6])**2).pow(.5); idx=distance.idxmin(); km=float(distance.loc[idx])*80
   if km <= 20: resolved[s[2]]=str(frame.loc[idx,'filename'])
 return resolved

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--database-url',default='postgresql://neolab@localhost:55432/neolab_warehouse'); ap.add_argument('--batch-size',type=int,default=BATCH); args=ap.parse_args()
 root=Path(__file__).resolve().parents[1]; load_dotenv(root/'.env',override=True); load_dotenv(root/'.env.warehouse',override=True); db=args.database_url
 raw=psql(db,"SELECT id,project_id,sample_id,ctd_rosette_filename,COALESCE(datetime_min,datetime_max),lat_avg,lon_avg FROM warehouse.ecotaxa_sample WHERE ctd_rosette_filename IS NOT NULL AND ctd_rosette_filename<>''")
 samples=[]
 for line in raw.splitlines():
  parts=line.split('\t');
  if len(parts)>=7: samples.append(parts)
 resolved=resolve_by_position(samples)
 print(f'[ctd] références filename={len(samples)}, résolues date+position={len(resolved)}',flush=True)
 names=sorted({norm(x[3]) for x in samples if re.fullmatch(r'(?:\d{6,7}|\d{4}_\d{3}\.int\.nc)', str(x[3]).strip())} | set(resolved.values())); digest=hashlib.sha256(('\\n'.join(names)).encode()).hexdigest()
 vid=int(psql(db,f"INSERT INTO warehouse.dataset_version(source_instance,dataset_key,version_key,file_manifest_uri,sha256) VALUES ('amundsen_ctd','amundsen12713','current',{repr(BASE)},{repr(digest)}) ON CONFLICT (source_instance,dataset_key,version_key) DO UPDATE SET sha256=EXCLUDED.sha256 RETURNING id").splitlines()[0])
 for code,(name,unit) in VARS.items(): psql(db,f"INSERT INTO warehouse.ctd_variable(variable_key,canonical_name,canonical_unit,description,source_code,source_instance) VALUES ({repr(code)},{repr(name)},{repr(unit)},{repr(name)},{repr(code)},'amundsen') ON CONFLICT(variable_key) DO UPDATE SET canonical_unit=EXCLUDED.canonical_unit")
 total_profiles=total_rows=0
 for start in range(0,len(names),args.batch_size):
  batch=names[start:start+args.batch_size]; frame=fetch(batch)
  if frame.empty: print(f'[ctd] profils {start}/{len(names)}: aucune donnée',flush=True); continue
  profiles=frame.drop_duplicates('filename')
  for _,r in profiles.iterrows():
   filename=str(r['filename']); psql(db,f"INSERT INTO warehouse.ctd_profile(dataset_version_id,source_profile_key,station_key,sampled_at,latitude,longitude) VALUES ({vid},{repr(filename)},{repr(str(r.get('station','')))},NULLIF({repr(str(r.get('time','')))},'NaT')::timestamptz,{('NULL' if pd.isna(r.get('latitude')) else repr(float(r['latitude'])))},{('NULL' if pd.isna(r.get('longitude')) else repr(float(r['longitude'])))}) ON CONFLICT(dataset_version_id,source_profile_key) DO UPDATE SET station_key=EXCLUDED.station_key,sampled_at=EXCLUDED.sampled_at,latitude=EXCLUDED.latitude,longitude=EXCLUDED.longitude")
  idrows=psql(db,f"SELECT id,source_profile_key FROM warehouse.ctd_profile WHERE dataset_version_id={vid} AND source_profile_key IN ({','.join(repr(x) for x in batch)})")
  ids={x.split('\t')[1]:int(x.split('\t')[0]) for x in idrows.splitlines() if '\t' in x}; buf=io.StringIO(); w=csv.writer(buf,delimiter='\t',lineterminator='\n')
  for filename,g in frame.groupby('filename'):
   pid=ids.get(str(filename));
   if not pid: continue
   for idx,row in g.reset_index(drop=True).iterrows():
    pressure=row.get('PRES');
    for code in VARS:
     val=row.get(code); 
     if pd.isna(val): continue
     w.writerow([pid,f'{filename}:{idx}:{code}',str(idx),('\\N' if pd.isna(pressure) else pressure),('\\N' if code!='PRES' or pd.isna(pressure) else pressure),code,VARS[code][0],code,str(float(val)),VARS[code][1],'\\N'])
  sql="""CREATE TEMP TABLE stage_ctd(profile_id bigint,source_row_key text,scan_key text,depth_m double precision,pressure_dbar double precision,variable_key text,variable_definition text,sensor_channel text,value double precision,unit text,qc text) ON COMMIT DROP; COPY stage_ctd FROM STDIN WITH (FORMAT csv,DELIMITER E'\\t',NULL '\\N'); INSERT INTO warehouse.ctd_measurement(profile_id,source_row_key,scan_key,depth_m,pressure_dbar,variable_key,variable_definition,sensor_channel,value,unit,qc) SELECT profile_id,source_row_key,scan_key,depth_m,pressure_dbar,variable_key,variable_definition,sensor_channel,value,unit,qc FROM stage_ctd ON CONFLICT(profile_id,source_row_key) DO UPDATE SET value=EXCLUDED.value,depth_m=EXCLUDED.depth_m,pressure_dbar=EXCLUDED.pressure_dbar;"""
  psql(db,sql,stdin=buf.getvalue()); total_profiles+=len(profiles); total_rows+=len(frame); print(f'[ctd] {min(start+len(batch),len(names))}/{len(names)} profils, {len(frame)} mesures lignes',flush=True)
 # Join EcoTaxa samples to CTD profiles by exact normalized filename.
 for sample in samples:
  sid,proj,native,rawname,when,lat,lon=sample; filename=resolved.get(native,norm(rawname)); pid=ids.get(filename)
  if pid is None:
   out=psql(db,f"SELECT id FROM warehouse.ctd_profile WHERE dataset_version_id={vid} AND source_profile_key={repr(filename)}")
   pid=int(out.strip()) if out.strip() else None
  if pid:
   psql(db,f"INSERT INTO warehouse.ecotaxa_ctd(ecotaxa_sample_id,ctd_profile_id,relation_type,filename_match,station_match,distance_km,time_gap_minutes,match_status,evidence) VALUES ({sid},{pid},'filename_exact',TRUE,NULL,NULL,NULL,'accepted','EcoTaxa ctd_rosette_filename normalisé vers Amundsen filename') ON CONFLICT(ecotaxa_sample_id,ctd_profile_id) DO UPDATE SET match_status='accepted',filename_match=TRUE")
 print(f'[ctd] terminé: {total_profiles} profils, {total_rows} lignes source, samples référencés={len(samples)}')
if __name__=='__main__': main()
