#!/usr/bin/env python3
"""Download linked EcoPart projects and load a versioned PostgreSQL warehouse.

Historical contracts: origin/main (475af5d), core/ecopart_client.py and
core/ecotaxa_ecopart_join.py. No dependency on the former agent/runtime.
Credentials are read from the local .env; never written to the manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import psycopg
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from psycopg.rows import dict_row
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://ecopart.obs-vlfr.fr"
ROOT = Path(__file__).resolve().parents[1]


def log(message: str) -> None:
    print(f"[ecopart] {message}", flush=True)


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def parse_export(content: bytes) -> list[dict]:
    """Keep native values; reject nonfinite volumes and duplicate normalized bins."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    required = {"Profile", "Depth [m]", "Sampled volume [L]"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Colonnes EcoPart requises absentes")
    result, keys = [], set()
    for raw in reader:
        profile = raw["Profile"].strip()
        depth, volume = float(raw["Depth [m]"]), float(raw["Sampled volume [L]"])
        if (
            not profile
            or not math.isfinite(depth)
            or not math.isfinite(volume)
            or volume <= 0
        ):
            raise ValueError("Profil, profondeur ou volume EcoPart invalide")
        lower = math.floor(depth / 5) * 5
        key = (profile, lower)
        if key in keys:
            raise ValueError(f"Bin normalisé dupliqué: {key}")
        keys.add(key)
        result.append(
            {
                "profile": profile,
                "depth_min": lower,
                "depth_max": lower + 5,
                "source_depth": depth,
                "volume": volume,
                "raw": raw,
            }
        )
    if not result:
        raise ValueError("Export EcoPart vide")
    return result


def resolve_sample_links(
    samples: list[dict], profiles: set[str]
) -> tuple[list[dict], list[int]]:
    """Only exact native sample/profile keys inside an explicitly linked project."""
    links, missing = [], []
    for sample in samples:
        hits = {
            str(sample[key]).strip(): key
            for key in ("profile_id", "sample_orig_id")
            if sample.get(key) is not None and str(sample[key]).strip() in profiles
        }
        if len(hits) > 1:
            raise ValueError(f"Lien ambigu pour sample {sample['id']}")
        if not hits:
            missing.append(sample["id"])
            continue
        profile, key = next(iter(hits.items()))
        links.append({"sample_id": sample["id"], "profile": profile, "key": key})
    return links, missing


def task_link_from_response(url: str, html: str) -> str:
    """Never pick an arbitrary task from the account's global task list."""
    match = re.fullmatch(r"/Task/Show/\d+", urlparse(url).path)
    if match:
        return match.group()
    links = set(re.findall(r"""href=['"](/Task/Show/\d+)['"]""", html))
    if len(links) != 1:
        raise ValueError("Identité de la tâche export absente ou ambiguë")
    return links.pop()


def task_parameters(html: str, project_id: int) -> dict:
    """Verify the server task's exact project and export mode."""
    soup = BeautifulSoup(html, "html.parser")
    label = soup.find("th", string=lambda t: t and t.strip() == "Input Param")
    if label is None:
        raise ValueError("Paramètres de tâche absents")
    params = json.loads(label.find_next_sibling("td").get_text())
    if (
        params.get("filtres") != {"filt_uproj": str(project_id)}
        or params.get("what") != "RED"
        or params.get("fileformat") != "TSV"
    ):
        raise ValueError("Tâche export hors du périmètre demandé")
    return {k: v for k, v in params.items() if k not in ("user_name", "user_email")}


class Client:
    """Cookie client ported from the historical EcoPart tool."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "idea-warehouse-ecopart/1.0"
        retry = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=["GET"],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def login(self) -> None:
        if os.getenv("ECOPART_TOKEN"):
            self.session.headers["Authorization"] = (
                "Bearer " + os.environ["ECOPART_TOKEN"]
            )
            return
        username, password = (
            os.getenv("ECOTAXA_USERNAME"),
            os.getenv("ECOTAXA_PASSWORD"),
        )
        if not username or not password:
            raise RuntimeError("Identifiants EcoPart absents")
        response = self.session.post(
            BASE + "/login",
            data={"email": username, "password": password},
            timeout=(15, 90),
            allow_redirects=False,
        )
        if response.status_code not in (200, 302) or not response.cookies:
            raise RuntimeError(
                f"Authentification EcoPart échouée: HTTP {response.status_code}"
            )

    def get(self, path: str, **kwargs) -> requests.Response:
        url = urljoin(BASE, path)
        if urlparse(url).netloc != urlparse(BASE).netloc:
            raise ValueError("URL export hors du serveur EcoPart")
        response = self.session.get(url, timeout=(20, 180), **kwargs)
        response.raise_for_status()
        return response

    def samples(self, **params) -> list[dict]:
        result = self.get("/searchsample", params=params).json()
        if not isinstance(result, list):
            raise TypeError("Réponse searchsample invalide")
        return result

    def metadata(self, sample_id: int) -> dict:
        text = BeautifulSoup(
            self.get(f"/getsamplepopover/{sample_id}").text, "html.parser"
        ).get_text(" ", strip=True)
        result = {"id": sample_id, "raw": text}
        for key, pattern in {
            "profile": r"Profile ID\s*:\s*([^\s]+)",
            "ecopart_project_id": r"Project\s*:\s*.+?\((\d+)\)",
            "ecotaxa_project_id": r"Ecotaxa Project\s*:\s*.+?\((\d+)\)",
        }.items():
            match = re.search(pattern, text)
            if match:
                result[key] = int(match[1]) if key.endswith("_id") else match[1]
        if "ecopart_project_id" not in result:
            raise ValueError(f"Projet absent des métadonnées sample {sample_id}")
        return result

    def export(self, project_id: int, directory: Path, state: dict) -> Path:
        """Resume a saved export task and preserve the exact downloaded bytes."""
        path = directory / f"project-{project_id}.zip"
        if state.get("sha256") and path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() == state["sha256"]:
                return path
            raise ValueError("Empreinte export local incorrecte")
        if not state.get("task"):
            params = [("filt_uproj", str(project_id))]
            params += [
                ("ctd", v)
                for v in ["depth", "datetime", "temperature", "practical_salinity"]
            ]
            params += [("gpr", v) for v in ["cl6", "cl7", "cl8", "bv6", "bv7", "bv8"]]
            form = self.get("/Task/Create/TaskPartExport", params=params)
            soup = BeautifulSoup(form.text, "html.parser")
            field = soup.find("input", {"name": "backurl"})
            before = set(re.findall(r"/Task/Show/\d+", self.get("/Task/listall").text))
            log(f"projet {project_id}: création export RED/TSV")
            response = self.session.post(
                BASE + "/Task/Create/TaskPartExport",
                params=params,
                data={
                    "backurl": field.get("value")
                    if field
                    else f"/?filt_uproj={project_id}",
                    "what": "RED",
                    "fileformat": "TSV",
                    "starttask": "Y",
                },
                timeout=(20, 180),
            )
            response.raise_for_status()
            (directory / f"project-{project_id}-task-response.html").write_text(
                response.text
            )
            try:
                task = task_link_from_response(response.url, response.text)
            except ValueError:
                after = set(
                    re.findall(r"/Task/Show/\d+", self.get("/Task/listall").text)
                )
                candidates = []
                for candidate in after - before:
                    page = self.get(candidate)
                    try:
                        task_parameters(page.text, project_id)
                    except ValueError:
                        continue
                    candidates.append(candidate)
                if len(candidates) != 1:
                    raise ValueError(
                        "Nouvelle tâche export absente ou ambiguë"
                    ) from None
                task = candidates[0]
            state["task"] = task
            save_json(directory / f"project-{project_id}.json", state)
        for attempt in range(180):
            response = self.get(state["task"])
            state["task_parameters"] = task_parameters(response.text, project_id)
            save_json(directory / f"project-{project_id}.json", state)
            soup = BeautifulSoup(response.text, "html.parser")
            links = [
                a["href"]
                for a in soup.find_all("a", href=True)
                if "/Task/GetFile/" in a["href"]
            ]
            if links:
                response = self.get(links[0])
                if "html" in response.headers.get("Content-Type", "").lower():
                    raise ValueError("HTML reçu à la place du fichier export")
                temporary = path.with_suffix(".part")
                temporary.write_bytes(response.content)
                temporary.replace(path)
                state.update(
                    sha256=hashlib.sha256(response.content).hexdigest(),
                    bytes=len(response.content),
                    download_url=links[0],
                )
                save_json(directory / f"project-{project_id}.json", state)
                return path
            if re.search(
                r"\bState\s+Error\b", soup.get_text(" ", strip=True), re.IGNORECASE
            ):
                raise RuntimeError(f"Export serveur en erreur: {state['task']}")
            if attempt % 10 == 0:
                log(f"projet {project_id}: attente export {state['task']}")
            time.sleep(3)
        raise TimeoutError(f"Export non terminé: {state['task']}")


def connection() -> psycopg.Connection:
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.warehouse")
    if os.getenv("WAREHOUSE_DATABASE_URL"):
        return psycopg.connect(
            os.environ["WAREHOUSE_DATABASE_URL"], row_factory=dict_row
        )
    return psycopg.connect(
        host="localhost",
        port=55432,
        user="neolab",
        dbname="neolab_warehouse",
        password=os.getenv("WAREHOUSE_POSTGRES_PASSWORD"),
        row_factory=dict_row,
    )


def discover(client: Client, conn: psycopg.Connection, directory: Path) -> dict:
    """Resolve every loaded EcoTaxa project from server evidence or explicit title."""
    path = directory / "discovery.json"
    state = json.loads(path.read_text()) if path.exists() else {}
    projects = conn.execute(
        "SELECT project_id,title FROM warehouse.ecotaxa_project ORDER BY project_id"
    ).fetchall()
    conn.commit()

    def resolve(project: dict) -> tuple[str, dict]:
        worker = Client()
        worker.session.cookies.update(client.session.cookies)
        worker.session.headers.update(client.session.headers)
        client_for_project = worker
        pid = project["project_id"]
        log(f"découverte EcoTaxa {pid}: {project['title']}")
        try:
            samples = client_for_project.samples(filt_proj=pid)
            evidence, ep_ids = [], set()
            # Identify each project represented, then subtract its complete sample set.
            remaining = {s["id"] for s in samples}
            while remaining:
                metadata = client_for_project.metadata(min(remaining))
                ep_id = metadata["ecopart_project_id"]
                if metadata.get("ecotaxa_project_id") != pid:
                    raise ValueError("Lien serveur et métadonnées incohérents")
                ep_samples = client_for_project.samples(filt_uproj=ep_id)
                covered = remaining.intersection(s["id"] for s in ep_samples)
                if not covered:
                    raise ValueError("Sample absent de son projet EcoPart")
                remaining -= covered
                evidence.append(metadata)
                ep_ids.add(ep_id)
                save_json(directory / f"samples-{ep_id}.json", ep_samples)
            match = re.search(r"Ecopart\s+id\s+(\d+)", project["title"], re.IGNORECASE)
            if not ep_ids and match:
                ep_id = int(match[1])
                ep_samples = client_for_project.samples(filt_uproj=ep_id)
                if not ep_samples:
                    raise ValueError("Projet EcoPart du titre sans sample accessible")
                ep_ids.add(ep_id)
                evidence.append({"title": project["title"], "method": "explicit_title"})
                save_json(directory / f"samples-{ep_id}.json", ep_samples)
            result = {
                **project,
                "status": "resolved" if ep_ids else "no_server_link",
                "ecopart_projects": sorted(ep_ids),
                "linked_samples": samples,
                "evidence": evidence,
            }
            log(f"EcoTaxa {pid} → {sorted(ep_ids) or 'aucun lien serveur'}")
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            result = {
                **project,
                "status": "error",
                "error": type(exc).__name__,
            }
            log(f"EcoTaxa {pid}: échec {type(exc).__name__}")
        return str(pid), result

    pending = [
        p
        for p in projects
        if str(p["project_id"]) not in state
        or state[str(p["project_id"])].get("status") == "error"
    ]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(resolve, p) for p in pending]
        for future in as_completed(futures):
            pid, result = future.result()
            state[pid] = result
            save_json(path, state)
    return state


def archive_tables(path: Path) -> tuple[dict[str, bytes], list[str]]:
    """Deduplicate identical ZIP members only; reject conflicting duplicate names."""
    content = path.read_bytes()
    if not zipfile.is_zipfile(io.BytesIO(content)):
        return {path.name: content}, []
    members, duplicates = {}, []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for info in archive.infolist():
            if not info.filename.lower().endswith((".tsv", ".csv")):
                continue
            data = archive.read(info)
            if info.filename in members:
                if members[info.filename] != data:
                    raise ValueError("Membres ZIP homonymes avec contenus différents")
                duplicates.append(info.filename)
            else:
                members[info.filename] = data
    return members, duplicates


def export_rows(path: Path) -> list[dict]:
    """Load PAR volumes only; ZOO abundance exports have a different grain."""
    members, _ = archive_tables(path)
    tables = {
        name: data
        for name, data in members.items()
        if "_PAR_" in name
        or (len(members) == 1 and "_ZOO_" not in name and "summary" not in name)
    }
    if not tables:
        raise ValueError("Archive sans données particulaires PAR")
    rows = []
    for name, data in tables.items():
        for row in parse_export(data):
            row["member"] = name
            rows.append(row)
    if len({(r["profile"], r["depth_min"]) for r in rows}) != len(rows):
        raise ValueError("Bins dupliqués entre fichiers export")
    return rows


def particle_values(raw: dict) -> list[tuple]:
    """Normalize only bounded source size classes; preserve all other raw fields."""
    values = []
    pattern = r"^LPM \(([\d.]+)-([\d.]+) (µm|μm|mm)\) \[# l-1\]$"
    for column, value in raw.items():
        match = re.match(pattern, column)
        if match and value.strip():
            concentration = float(value)
            if not math.isfinite(concentration) or concentration < 0:
                raise ValueError("Concentration particulaire invalide")
            scale = 1000 if match[3] == "mm" else 1
            lower, upper = float(match[1]) * scale, float(match[2]) * scale
            if lower >= upper:
                raise ValueError("Classe de taille invalide")
            values.append(
                (
                    column,
                    lower,
                    upper,
                    "source export EcoPart: " + column,
                    concentration,
                    "# l-1",
                )
            )
    return values


def load_project(
    conn: psycopg.Connection,
    path: Path,
    ep_id: int,
    et_projects: list[int],
    evidence: dict,
) -> dict:
    """Atomic project import. Failed loads leave no partially populated version."""
    from psycopg.types.json import Jsonb

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = export_rows(path)
    profiles = {row["profile"] for row in rows}
    task_state_path = path.with_suffix('.json')
    task_state = json.loads(task_state_path.read_text()) if task_state_path.exists() else {}
    source_samples = task_state.get('task_parameters', {}).get('samples', [])
    expected_profiles = {sample[5] for sample in source_samples}
    missing_source_profiles = sorted(expected_profiles - profiles)
    unexpected_source_profiles = sorted(profiles - expected_profiles) if source_samples else []
    if unexpected_source_profiles:
        raise ValueError('Export contenant des profils hors de la sélection serveur')
    samples = conn.execute(
        "SELECT * FROM warehouse.ecotaxa_sample WHERE project_id=ANY(%s)",
        (et_projects,),
    ).fetchall()
    links, missing = resolve_sample_links(samples, profiles)
    by_sample = {s["id"]: s for s in samples}
    # Two samples from the same EcoTaxa project must not double-count a profile.
    keys = [(by_sample[l["sample_id"]]["project_id"], l["profile"]) for l in links]
    if len(keys) != len(set(keys)):
        raise ValueError(
            "Plusieurs samples du même projet EcoTaxa pour un profil EcoPart"
        )
    existing = conn.execute(
        """SELECT i.manifest_json FROM warehouse.ecopart_project_import i
        JOIN warehouse.dataset_version v ON v.id=i.dataset_version_id
        WHERE v.source_instance='ecopart' AND v.dataset_key=%s AND v.sha256=%s""",
        (str(ep_id), digest),
    ).fetchone()
    if existing:
        conn.commit()
        if existing["manifest_json"]["ecotaxa_projects"] != et_projects:
            raise ValueError(
                "Périmètre EcoTaxa changé: réconciliation explicite requise"
            )
        log(f"projet {ep_id}: version complète déjà chargée")
        return existing["manifest_json"]
    conn.commit()
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(4172026)")
        version = conn.execute(
            """INSERT INTO warehouse.dataset_version
            (source_instance,dataset_key,version_key,file_manifest_uri,sha256)
            VALUES ('ecopart',%s,%s,%s,%s)
            ON CONFLICT (source_instance,dataset_key,version_key) DO UPDATE
            SET file_manifest_uri=EXCLUDED.file_manifest_uri RETURNING id""",
            (str(ep_id), digest[:16], str(path.resolve()), digest),
        ).fetchone()["id"]
        members, duplicate_members = archive_tables(path)
        auxiliary_count = 0
        with (
            conn.cursor().copy("""COPY warehouse.ecopart_auxiliary_row
            (dataset_version_id,member_name,row_number,content_kind,profile_name,source_row_json) FROM STDIN""") as copy
        ):
            for name, data in members.items():
                kind = (
                    "metadata"
                    if "summary" in name.lower()
                    else "zooplankton"
                    if "_ZOO_" in name
                    else None
                )
                if kind is None:
                    continue
                try:
                    text = data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = data.decode("cp1252")
                for number, raw in enumerate(
                    csv.DictReader(io.StringIO(text), delimiter="\t"), 1
                ):
                    copy.write_row(
                        (version, name, number, kind, raw.get("Profile"), Jsonb(raw))
                    )
                    auxiliary_count += 1
        profile_ids = {}
        for profile in sorted(profiles):
            linked = [
                by_sample[l["sample_id"]] for l in links if l["profile"] == profile
            ]

            def common(key, linked=linked):
                values = {s[key] for s in linked if s.get(key) is not None}
                return next(iter(values)) if len(values) == 1 else None

            profile_ids[profile] = conn.execute(
                """INSERT INTO warehouse.uvp_profile
                (dataset_version_id,ecopart_project_id,ecopart_sample_id,sample_name,
                 ecotaxa_project_id,cruise_key,station_key,cast_key,latitude,longitude,
                 sampled_at,marine_zone_key,marine_zone_name,marine_zone_source,
                 marine_zone_version,marine_zone_assignment_status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (
                    version,
                    ep_id,
                    profile,
                    profile,
                    common("project_id"),
                    common("cruise_id"),
                    common("station_id"),
                    common("profile_id"),
                    common("lat_avg"),
                    common("lon_avg"),
                    common("datetime_min"),
                    common("marine_zone_key"),
                    common("marine_zone_name"),
                    common("marine_zone_source"),
                    common("marine_zone_version"),
                    common("marine_zone_assignment_status"),
                ),
            ).fetchone()["id"]
        with (
            conn.cursor().copy("""COPY warehouse.uvp_bin
                (profile_id,source_bin_key,depth_min_m,depth_max_m,sampled_volume_l) FROM STDIN""") as copy
        ):
            for row in rows:
                copy.write_row(
                    (
                        profile_ids[row["profile"]],
                        f"{row['profile']}:{row['source_depth']:g}",
                        row["depth_min"],
                        row["depth_max"],
                        row["volume"],
                    )
                )
        bins = conn.execute(
            """SELECT b.id,b.profile_id,b.depth_min_m FROM warehouse.uvp_bin b
            JOIN warehouse.uvp_profile p ON p.id=b.profile_id WHERE p.dataset_version_id=%s""",
            (version,),
        ).fetchall()
        bin_ids = {(b["profile_id"], b["depth_min_m"]): b["id"] for b in bins}
        with conn.cursor().copy(
            "COPY warehouse.ecopart_bin_source (bin_id,source_depth_m,source_row_json) FROM STDIN"
        ) as copy:
            for row in rows:
                copy.write_row(
                    (
                        bin_ids[profile_ids[row["profile"]], row["depth_min"]],
                        row["source_depth"],
                        Jsonb(row["raw"]),
                    )
                )
        n_particles = 0
        with (
            conn.cursor().copy("""COPY warehouse.uvp_particle
            (bin_id,size_class_key,size_min_um,size_max_um,size_definition,supplied_concentration,concentration_unit) FROM STDIN""") as copy
        ):
            for row in rows:
                for value in particle_values(row["raw"]):
                    copy.write_row(
                        (bin_ids[profile_ids[row["profile"]], row["depth_min"]], *value)
                    )
                    n_particles += 1
        with conn.cursor().copy(
            "COPY warehouse.uvp_ecotaxa (uvp_profile_id,ecotaxa_sample_id,source_evidence) FROM STDIN"
        ) as copy:
            for link in links:
                proof = {
                    "project_resolution": evidence[
                        str(by_sample[link["sample_id"]]["project_id"])
                    ]["evidence"],
                    "key": link["key"],
                    "value": link["profile"],
                    "archive_sha256": digest,
                }
                copy.write_row(
                    (profile_ids[link["profile"]], link["sample_id"], json.dumps(proof))
                )
        log(
            f"projet {ep_id}: {len(profiles)} profils, {len(rows)} bins; rattachement des objets"
        )
        mapped = conn.execute(
            """INSERT INTO warehouse.uvp_object_bin
            (ecotaxa_object_id,uvp_bin_id,depth_delta_m,mapping_method,mapping_status)
            SELECT o.id,b.id,abs(o.depth_min_m-(b.depth_min_m+2.5)),
                   'exact_profile+floor(object_depth_min/5)*5;legacy-7a7751f','accepted'
            FROM warehouse.uvp_profile p
            JOIN warehouse.uvp_ecotaxa l ON l.uvp_profile_id=p.id
            JOIN warehouse.ecotaxa_object o ON o.sample_id=l.ecotaxa_sample_id
            JOIN warehouse.uvp_bin b ON b.profile_id=p.id
                AND b.depth_min_m=floor(o.depth_min_m/5)*5
            WHERE p.dataset_version_id=%s""",
            (version,),
        ).rowcount
        log(f"projet {ep_id}: {mapped} objets reliés; abondances par source EcoTaxa")
        # Persist positive counts; all sampled bins remain in uvp_bin. The view
        # below exposes zeros for each taxon observed in that profile/source.
        abundance = conn.execute(
            """INSERT INTO warehouse.uvp_taxon_abundance
            (dataset_version_id,profile_id,bin_id,taxon_key,annotation_policy,
             n_objects_taxon,sampled_volume_l,calculation_version)
            SELECT %s,b.profile_id,b.id,
                CASE WHEN o.category_id IS NOT NULL THEN 'ecotaxa:id:'||o.category_id
                     WHEN o.category_name IS NOT NULL THEN 'ecotaxa:name:'||o.category_name
                     ELSE 'warehouse:unclassified' END,
                'all_loaded_objects:ecotaxa_project='||s.project_id,
                count(*),b.sampled_volume_l,'ecopart-warehouse-v1-sparse'
            FROM warehouse.uvp_bin b
            JOIN warehouse.uvp_profile p ON p.id=b.profile_id
            JOIN warehouse.uvp_object_bin m ON m.uvp_bin_id=b.id
            JOIN warehouse.ecotaxa_object o ON o.id=m.ecotaxa_object_id
            JOIN warehouse.ecotaxa_sample s ON s.id=o.sample_id
            WHERE p.dataset_version_id=%s
            GROUP BY 2,3,4,5""",
            (version, version),
        ).rowcount
        ctd = conn.execute(
            """INSERT INTO warehouse.uvp_ctd
            (uvp_profile_id,ctd_profile_id,source_evidence)
            SELECT DISTINCT l.uvp_profile_id,c.ctd_profile_id,
                'Transitive accepted EcoTaxa–CTD link; exact EcoPart profile; see uvp_ecotaxa and ecotaxa_ctd'
            FROM warehouse.uvp_ecotaxa l
            JOIN warehouse.uvp_profile p ON p.id=l.uvp_profile_id
            JOIN warehouse.ecotaxa_ctd c ON c.ecotaxa_sample_id=l.ecotaxa_sample_id
            WHERE p.dataset_version_id=%s AND c.match_status='accepted'
            ON CONFLICT DO NOTHING""",
            (version,),
        ).rowcount
        total_objects = conn.execute(
            """SELECT count(*) AS n FROM warehouse.ecotaxa_object
            WHERE sample_id=ANY(%s)""",
            ([l["sample_id"] for l in links],),
        ).fetchone()["n"]
        report = {
            "ecopart_project": ep_id,
            "ecotaxa_projects": et_projects,
            "dataset_version_id": version,
            "sha256": digest,
            "profiles": len(profiles),
            "server_selected_profiles": len(expected_profiles),
            "missing_source_profiles": missing_source_profiles,
            "duplicate_archive_members": duplicate_members,
            "auxiliary_source_rows": auxiliary_count,
            "bins": len(rows),
            "sample_links": len(links),
            "missing_ecotaxa_sample_ids": missing,
            "particle_values": n_particles,
            "linked_sample_objects": total_objects,
            "mapped_objects": mapped,
            "unmapped_objects": total_objects - mapped,
            "positive_abundance_rows": abundance,
            "ctd_links": ctd,
        }
        conn.execute(
            """INSERT INTO warehouse.ecopart_project_import
            (dataset_version_id,ecopart_project_id,ecotaxa_project_ids,manifest_json)
            VALUES (%s,%s,%s,%s)""",
            (version, ep_id, et_projects, Jsonb(report)),
        )
    log(f"projet {ep_id}: transaction validée")
    return report


def ingest(
    client: Client, conn: psycopg.Connection, directory: Path, discovery: dict
) -> None:
    """Download/load each resolved project; retain per-project failures for retry."""
    conn.execute((ROOT / "docs/warehouse_ecopart_migration.sql").read_text())
    conn.commit()
    projects = {}
    for pid, info in discovery.items():
        for ep_id in info.get("ecopart_projects", []):
            projects.setdefault(ep_id, []).append(int(pid))
    failures = []
    for ep_id, et_ids in sorted(projects.items()):
        path = directory / f"project-{ep_id}.json"
        state = json.loads(path.read_text()) if path.exists() else {}
        try:
            archive = client.export(ep_id, directory, state)
            state["import"] = load_project(
                conn, archive, ep_id, sorted(et_ids), discovery
            )
            state["status"] = "complete"
            state.pop("error", None)
        except (
            requests.RequestException,
            ValueError,
            RuntimeError,
            OSError,
            psycopg.Error,
        ) as exc:
            conn.rollback()
            state.update(status="error", error=type(exc).__name__)
            log(f"projet {ep_id}: {type(exc).__name__}: {str(exc)[:200]}")
            failures.append(ep_id)
        save_json(path, state)
    if failures:
        raise SystemExit(f"Projets incomplets: {failures}; relancer pour reprendre")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument(
        "--directory", type=Path, default=ROOT / "data/warehouse_ecopart"
    )
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    with connection() as conn:
        client = Client()
        client.login()
        state = discover(client, conn, args.directory)
        if not args.discover_only:
            ingest(client, conn, args.directory, state)
        if any(p["status"] == "error" for p in state.values()):
            raise SystemExit("Découverte incomplète; relancer pour reprendre")


if __name__ == "__main__":
    main()
