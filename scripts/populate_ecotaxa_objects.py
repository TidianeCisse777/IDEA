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

Statut d'annotation : obj.classif_qual (V/P/D) devient annotation_status
(validated/predicted/dubious, NULL si jamais classe) et obj.classif_id devient
category_id. Les compteurs nb_validated/nb_predicted/nb_dubious/nb_unclassified
des samples sont recalcules depuis les objets charges. --refresh relit les
objets deja charges pour completer ces champs sans dupliquer de ligne.
En fin de chargement, scripts/populate_ecotaxa_taxonomy.py recompte les objets
par sample et taxon et lit la lignee EcoTaxa des nouvelles categories.
"""
from __future__ import annotations
import argparse, csv, io, json, os, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from dotenv import load_dotenv

BASE='https://ecotaxa.obs-vlfr.fr/api'; PAGE=5000
SIZE_LABELS=('area','esd','major','minor')
# ZooProcess shape and grey-level features kept since 8 novembre 2026 (label -> column), common to UVP5, UVP6
# and Zooscan projects; LOKI names its features otherwise and keeps NULL.
MORPHO_LABELS=(('perim.','perim_px'),('feret','feret_px'),('circ.','circularity'),('elongation','elongation'),('mean','mean_grey'),('convarea','convex_area_px'))
FREE_LABELS=SIZE_LABELS+tuple(lbl for lbl,_ in MORPHO_LABELS)

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

def object_datetime(date, clock):
    """EcoTaxa objdate (YYYY-MM-DD) and objtime (HH:MM[:SS]) as one timestamp; the date alone when the
    time is missing or unreadable, never an invented hour."""
    if not date:
        return None
    clock = (clock or '').strip()
    parts = clock.split(':')
    if len(parts) in (2, 3) and all(x.isdigit() for x in parts) and int(parts[0]) < 24 and all(int(x) < 60 for x in parts[1:]):
        return f"{date} {int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]) if len(parts) == 3 else 0:02d}"
    return date

def login():
    '''Session with ECOTAXA_USERNAME/ECOTAXA_PASSWORD; without them, an anonymous session: public projects
    load, the others answer 403 and are skipped (or reached through a token the environment adds).'''
    s=requests.Session()
    if not os.environ.get('ECOTAXA_USERNAME'):
        print('[objects] sans identifiants EcoTaxa : projets publics seulement',flush=True); return s
    r=s.post(BASE+'/login',json={'username':os.environ['ECOTAXA_USERNAME'],'password':os.environ['ECOTAXA_PASSWORD']},timeout=30); r.raise_for_status(); p=r.json(); t=p.get('token') if isinstance(p,dict) else p; s.headers['Authorization']=f'Bearer {t}'; return s

class ProjectForbidden(Exception):
    pass

# Projects EcoTaxa served only in part (seen 8 novembre 2026: without login, a public project may serve
# only some of its objects, e.g. 24 387 of 65 828 for project 315); listed at the end, exit code 3.
INCOMPLETE=[]

def project_size_labels(s, pid):
    '''Labels among SIZE_LABELS this project actually defines (obj_free_cols), in
    SIZE_LABELS order. A label this project does not have must never be requested:
    EcoTaxa drops it from the row instead of returning null, shifting later columns.'''
    r=s.get(f'{BASE}/projects/{pid}',timeout=30)
    if r.status_code in (401,403): raise ProjectForbidden(pid)
    r.raise_for_status()
    free_cols=r.json().get('obj_free_cols') or {}
    return [lbl for lbl in FREE_LABELS if lbl in free_cols]

ANNOTATION_STATUS={'V':'validated','P':'predicted','D':'dubious'}

def annotation_status(qual):
    '''EcoTaxa classif_qual -> warehouse annotation_status. NULL stays NULL (never
    classified: unknown, not "predicted"); any other code stops the load rather than
    being guessed.'''
    if qual in (None,''): return None
    if qual not in ANNOTATION_STATUS: raise ValueError(f'classif_qual inconnu: {qual!r}')
    return ANNOTATION_STATUS[qual]

def load_project(args,s,pid):
    db=args.database_url or default_database(); total=int(psql(db,f'SELECT object_count::bigint FROM warehouse.ecotaxa_project WHERE project_id={pid}').strip() or 0)
    mapping={line.split('\t')[0]:int(line.split('\t')[1]) for line in psql(db,f"SELECT sample_id,id FROM warehouse.ecotaxa_sample WHERE project_id={pid}").splitlines() if '\t' in line}
    if not mapping: print(f'[objects] projet {pid}: aucun sample parent, ignoré'); return 0
    size_labels=project_size_labels(s,pid)
    # obj.classif_id / obj.classif_qual: documented object fields of /object_set/{id}/query
    # (API spec, "fields"); classif_qual is V (validated), P (predicted), D (dubious) or
    # null (never classified). Kept before the fre.<label> columns, whose count varies.
    # obj.objtime (hour of capture) was not asked for until 7 novembre 2026: every loaded object and sample
    # carried midnight; it is appended last so the earlier positions stay the same.
    # obj.sunpos, classif_who/when/auto_score and img.file_name were added on 8 novembre 2026 (checked live on 149).
    base_fields='obj.orig_id,obj.objdate,obj.depth_min,obj.depth_max,obj.latitude,obj.longitude,txo.display_name,obj.classif_id,obj.classif_qual,obj.objtime,obj.sunpos,obj.classif_who,obj.classif_when,obj.classif_auto_score,img.file_name'
    fields=base_fields + (',' + ','.join(f'fre.{lbl}' for lbl in size_labels) if size_labels else '')
    base_n=15
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
        got=0
        for data in pool.map(fetch_page, starts):
          ids=data.get('object_ids',[]); samples=data.get('sample_ids',[]); acqs=data.get('acquisition_ids',[]); rows=data.get('details',[])
          if not ids: continue
          got+=len(ids)
          buf=io.StringIO(); w=csv.writer(buf,delimiter='\t',lineterminator='\n')
          for i,row in enumerate(rows):
              if i>=len(ids) or i>=len(samples) or str(samples[i]) not in mapping: continue
              sample_pk=mapping[str(samples[i])]
              acq=str(acqs[i]) if i<len(acqs) else None
              size_vals={lbl: (row[base_n+j] if base_n+j<len(row) else None) for j,lbl in enumerate(size_labels)}
              category_id=row[7] if len(row)>7 and row[7] not in (None,'') else None
              vals=[sample_pk,str(ids[i]),acq,None,None if category_id is None else str(category_id),row[6] if len(row)>6 else None,
                    annotation_status(row[8] if len(row)>8 else None),object_datetime(row[1] if len(row)>1 else None,row[9] if len(row)>9 else None),row[2] if len(row)>2 else None,row[3] if len(row)>3 else None,row[4] if len(row)>4 else None,row[5] if len(row)>5 else None,
                    size_vals.get('area'),size_vals.get('esd'),size_vals.get('major'),size_vals.get('minor')]
              at=lambda k: row[k] if len(row)>k else None
              image=at(14)
              sun=(at(10) or '').strip() or None
              vals+=[sun,at(11),at(12),at(13),image or None]+[size_vals.get(lbl) for lbl,_ in MORPHO_LABELS]
              w.writerow(['\\N' if v is None or v=='' else v for v in vals])
          sql=["""CREATE TEMP TABLE stage_ecotaxa_object(sample_id bigint,object_id text,acquisition_id text,process_id text,category_id text,category_name text,annotation_status text,object_datetime timestamptz,depth_min_m double precision,depth_max_m double precision,object_lat double precision,object_lon double precision,area_px double precision,esd_px double precision,major_px double precision,minor_px double precision,sun_position text,classif_who integer,classif_when timestamptz,classif_auto_score double precision,image_file text,perim_px double precision,feret_px double precision,circularity double precision,elongation double precision,mean_grey double precision,convex_area_px double precision)""", """COPY stage_ecotaxa_object FROM STDIN WITH (FORMAT csv,DELIMITER E'\\t',NULL '\\N')""", """INSERT INTO warehouse.ecotaxa_object(sample_id,object_id,acquisition_id,process_id,category_id,category_name,annotation_status,object_datetime,depth_min_m,depth_max_m,object_lat,object_lon,area_px,esd_px,major_px,minor_px,sun_position,classif_who,classif_when,classif_auto_score,image_file,perim_px,feret_px,circularity,elongation,mean_grey,convex_area_px) SELECT sample_id,object_id,acquisition_id,process_id,category_id,category_name,annotation_status,object_datetime,depth_min_m,depth_max_m,object_lat,object_lon,area_px,esd_px,major_px,minor_px,sun_position,classif_who,classif_when,classif_auto_score,image_file,perim_px,feret_px,circularity,elongation,mean_grey,convex_area_px FROM stage_ecotaxa_object ON CONFLICT (sample_id,object_id) DO UPDATE SET acquisition_id=EXCLUDED.acquisition_id,category_id=EXCLUDED.category_id,category_name=EXCLUDED.category_name,annotation_status=EXCLUDED.annotation_status,object_datetime=EXCLUDED.object_datetime,depth_min_m=EXCLUDED.depth_min_m,depth_max_m=EXCLUDED.depth_max_m,object_lat=EXCLUDED.object_lat,object_lon=EXCLUDED.object_lon,area_px=EXCLUDED.area_px,esd_px=EXCLUDED.esd_px,major_px=EXCLUDED.major_px,minor_px=EXCLUDED.minor_px,sun_position=EXCLUDED.sun_position,classif_who=EXCLUDED.classif_who,classif_when=EXCLUDED.classif_when,classif_auto_score=EXCLUDED.classif_auto_score,image_file=EXCLUDED.image_file,perim_px=EXCLUDED.perim_px,feret_px=EXCLUDED.feret_px,circularity=EXCLUDED.circularity,elongation=EXCLUDED.elongation,mean_grey=EXCLUDED.mean_grey,convex_area_px=EXCLUDED.convex_area_px"""]
          psql(db,sql,stdin=buf.getvalue()); loaded += len(ids); offset += len(ids); states[str(pid)]=offset; state.parent.mkdir(parents=True,exist_ok=True); state.write_text(json.dumps(states,indent=2))
          print(f'[objects] projet {pid}: {min(offset,total)}/{total} objets',flush=True)
        if not got:
            # EcoTaxa may serve fewer objects than the warehouse counts (149: 1 520 497 against 1 520 846):
            # stop instead of asking for the same empty window forever.
            print(f'[objects] projet {pid}: EcoTaxa ne renvoie plus d objet après {offset}/{total}; arrêt',flush=True)
            INCOMPLETE.append((pid,offset,total)); break
    if loaded or offset>=total:
        # Sample-level annotation counts, derived from this project's loaded objects
        # (EcoTaxa's own per-sample statistics are not loaded).
        psql(db,f"""UPDATE warehouse.ecotaxa_sample s SET object_count=a.n,nb_validated=a.v,nb_predicted=a.p,nb_dubious=a.d,nb_unclassified=a.u
            FROM (SELECT o.sample_id,count(*) n,count(*) FILTER (WHERE annotation_status='validated') v,
                         count(*) FILTER (WHERE annotation_status='predicted') p,count(*) FILTER (WHERE annotation_status='dubious') d,
                         count(*) FILTER (WHERE annotation_status IS NULL) u
                  FROM warehouse.ecotaxa_object o JOIN warehouse.ecotaxa_sample es ON es.id=o.sample_id
                  WHERE es.project_id={pid} GROUP BY o.sample_id) a WHERE s.id=a.sample_id""")
        psql(db,f"""UPDATE warehouse.ecotaxa_sample s SET datetime_min=a.min_date,datetime_max=a.max_date FROM (SELECT o.sample_id,min(o.object_datetime) AS min_date,max(o.object_datetime) AS max_date FROM warehouse.ecotaxa_object o JOIN warehouse.ecotaxa_sample es ON es.id=o.sample_id WHERE es.project_id={pid} AND o.object_datetime IS NOT NULL GROUP BY o.sample_id) a WHERE s.id=a.sample_id""")
    load_acquisition_pixel_sizes(s, db, pid)
    return loaded

def pixel_size(raw):
    '''EcoTaxa acquisition free column "pixel" -> (pixel_size_mm, unit read).
    Its unit differs by instrument: UVP5 and Zooscan projects give millimetres
    (0.085-0.174 observed), UVP6 projects give micrometres (73 observed, the
    UVP6 nominal pixel size). No real instrument here has a pixel of 1 mm or
    more, so a value >= 1 is read as micrometres. The raw value is kept too.'''
    if raw in (None, ''): return None, None
    value=float(raw)
    return (value/1000, 'um') if value >= 1 else (value, 'mm')

def load_acquisition_pixel_sizes(s, db, pid, batch=1000):
    '''One GET /acquisition/{id} per acquisition of the project not yet stored. The list
    comes from the database, not from the pages fetched in this run, so a run interrupted
    after its objects were loaded still calibrates them on the next run; results are
    written every `batch` acquisitions so an interruption loses at most one batch.
    free_columns.pixel is the pixel calibration EcoTaxa carries on the acquisition (unit: see pixel_size)
    (confirmed live; /acquisitions/search returns free_columns empty, so no bulk path);
    projects that do not define it leave pixel_size_mm NULL, never a guessed value.'''
    rows=[line.split('\t') for line in psql(db, f"""SELECT DISTINCT o.acquisition_id,o.sample_id FROM warehouse.ecotaxa_object o
        JOIN warehouse.ecotaxa_sample s ON s.id=o.sample_id
        WHERE s.project_id={pid} AND o.acquisition_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM warehouse.ecotaxa_acquisition a WHERE a.acquisition_id=o.acquisition_id)""").splitlines() if '\t' in line]
    todo=dict(rows)
    if not todo: return
    def fetch_one(acq_id):
        for attempt in range(1, 4):
            try:
                r=s.get(f'{BASE}/acquisition/{acq_id}',timeout=30); r.raise_for_status()
                pixel=(r.json().get('free_columns') or {}).get('pixel')
                return acq_id, (None if pixel in (None,'') else float(pixel))
            except requests.RequestException:
                if attempt == 3: raise
                time.sleep(attempt * 2)
    def flush(results):
        buf=io.StringIO(); w=csv.writer(buf,delimiter='\t',lineterminator='\n')
        for acq_id, raw in results:
            mm, unit = pixel_size(raw)
            w.writerow([acq_id, todo[acq_id]] + ['\\N' if v is None else v for v in (mm, raw, unit)])
        psql(db,["""CREATE TEMP TABLE stage_ecotaxa_acquisition(acquisition_id text,sample_id bigint,pixel_size_mm double precision,pixel_size_raw double precision,pixel_unit_read text)""",
                 """COPY stage_ecotaxa_acquisition FROM STDIN WITH (FORMAT csv,DELIMITER E'\\t',NULL '\\N')""",
                 """INSERT INTO warehouse.ecotaxa_acquisition(acquisition_id,sample_id,pixel_size_mm,pixel_size_raw,pixel_unit_read) SELECT acquisition_id,sample_id,pixel_size_mm,pixel_size_raw,pixel_unit_read FROM stage_ecotaxa_acquisition ON CONFLICT (acquisition_id) DO UPDATE SET pixel_size_mm=EXCLUDED.pixel_size_mm,pixel_size_raw=EXCLUDED.pixel_size_raw,pixel_unit_read=EXCLUDED.pixel_unit_read"""],
             stdin=buf.getvalue())
    ids=list(todo); done=0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for start in range(0, len(ids), batch):
            results=list(pool.map(fetch_one, ids[start:start+batch]))
            flush(results); done+=len(results)
            print(f'[objects] projet {pid}: calibration pixel {done}/{len(ids)} acquisitions',flush=True)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project-id',type=int); ap.add_argument('--all-projects',action='store_true'); ap.add_argument('--database-url'); ap.add_argument('--state-file',default='data/warehouse_staging/ecotaxa_objects_state.json')
    ap.add_argument('--refresh',action='store_true',help='relire tous les objets deja charges (ex. statut d annotation ajoute) : met a jour en place, reprenable via son propre fichier d etat')
    args=ap.parse_args()
    if args.refresh: args.state_file=str(Path(args.state_file).with_name('ecotaxa_objects_refresh_state.json'))
    if bool(args.project_id)==bool(args.all_projects): raise SystemExit('indiquer exactement --project-id ou --all-projects')
    root=Path(__file__).resolve().parents[1]; load_dotenv(root/'.env',override=True); load_dotenv(root/'.env.warehouse'); s=login(); db=args.database_url or default_database(); ids=[args.project_id]
    if args.all_projects: ids=[int(x) for x in psql(db,'SELECT project_id FROM warehouse.ecotaxa_project ORDER BY project_id').split()]
    total=0
    refused=[]
    for n,pid in enumerate(ids,1):
        print(f'[objects] progression projets {n}/{len(ids)}',flush=True)
        try: total+=load_project(args,s,pid)
        except ProjectForbidden: refused.append(pid); print(f'[objects] projet {pid}: accès refusé par EcoTaxa (identifiants requis), ignoré',flush=True)
    if refused: print(f'[objects] projets non chargés faute de droits EcoTaxa : {refused}',flush=True)
    if INCOMPLETE:
        print('[objects] projets lus en partie (objets servis / attendus) : '
              + ', '.join(f'{pid} ({got}/{want})' for pid,got,want in INCOMPLETE),flush=True)
    print(f'[objects] terminé: {len(ids)} projets, {total} objets traités',flush=True)
    # Per-sample taxon counts and the lineage of any new category (explore.ecotaxa_sample_taxa, ecotaxa_taxa).
    from populate_ecotaxa_taxonomy import load_taxonomy
    taxa,samples=load_taxonomy(db)
    print(f'[objects] taxonomie: {taxa} nouvelle(s) catégorie(s), {samples} sample(s) recompté(s) par taxon',flush=True)
    return 3 if INCOMPLETE or refused else 0
if __name__=='__main__': raise SystemExit(main())
