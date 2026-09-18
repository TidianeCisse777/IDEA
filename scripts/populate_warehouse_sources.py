#!/usr/bin/env python3
"""Populate the first warehouse source slice: EcoPart profiles and Amundsen CTD.

This deliberately uses the existing ``psql`` CLI instead of adding a second
database driver to the IDEA runtime. Raw downloads are copied to a staging
directory, hashed, registered in ``warehouse.dataset_version``, then loaded
into the normalized PostgreSQL tables.

Examples:
    python scripts/populate_warehouse_sources.py \
        --database-url "$WAREHOUSE_DATABASE_URL" \
        --ecopart-tsv /data/ecopart.tsv --ecopart-project-id 12 \
        --ctd-url 'https://.../amundsen12713.csv?...'
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd


ECOPART_REQUIRED = {"Profile", "Depth [m]", "Sampled volume [L]"}
CTD_CODES = {
    "PRES": ("pressure / depth", "dbar"),
    "TE90": ("temperature", "degC"),
    "PSAL": ("salinity", "PSU"),
    "SIGT": ("density", None),
    "OXYM": ("oxygen", None),
    "pH": ("pH", None),
    "NTRA": ("nitrate", None),
    "FLOR": ("fluorescence", None),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def progress(message: str) -> None:
    print(f"[warehouse] {message}", flush=True)


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"État de reprise illisible : {path} ({exc})") from exc
    return value if isinstance(value, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def fetch(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "idea-warehouse-loader/1.0"})
    with urlopen(request, timeout=180) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)
    return destination


def psql(database_url: str, statement: str, *, stdin: str | None = None) -> str:
    command = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-At", database_url, "-c", statement]
    result = subprocess.run(command, input=stdin, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def sql_literal(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def returned_id(output: str) -> int:
    """Extract a PostgreSQL RETURNING id from psql's data plus command tag."""
    for line in output.splitlines():
        value = line.strip()
        if value.isdigit():
            return int(value)
    raise RuntimeError(f"Aucun identifiant retourné par PostgreSQL : {output!r}")


def register_version(database_url: str, *, source: str, key: str, path: Path) -> int:
    digest = sha256(path)
    manifest_uri = str(path.resolve())
    statement = f"""
        INSERT INTO warehouse.dataset_version
            (source_instance, dataset_key, version_key, file_manifest_uri, sha256)
        VALUES ({sql_literal(source)}, {sql_literal(key)}, {sql_literal(digest[:16])},
                {sql_literal(manifest_uri)}, {sql_literal(digest)})
        ON CONFLICT (source_instance, dataset_key, version_key)
        DO UPDATE SET file_manifest_uri = EXCLUDED.file_manifest_uri,
                      sha256 = EXCLUDED.sha256
        RETURNING id
    """
    output = psql(database_url, statement)
    if not output:
        raise RuntimeError(f"Impossible d'enregistrer la version {source}/{key}")
    return returned_id(output)


def load_ecopart(database_url: str, path: Path, *, project_id: int, ecotaxa_project_id: int | None, encoding: str = "utf-8") -> dict:
    header = pd.read_csv(path, sep="\t", nrows=0, encoding=encoding)
    missing = sorted(ECOPART_REQUIRED.difference(map(str, header.columns)))
    if missing:
        raise ValueError("Export EcoPart invalide, colonnes absentes : " + ", ".join(missing))
    frame = pd.read_csv(path, sep="\t", encoding=encoding)
    frame["Profile"] = frame["Profile"].astype(str).str.strip()
    frame["Depth [m]"] = pd.to_numeric(frame["Depth [m]"], errors="coerce")
    frame["Sampled volume [L]"] = pd.to_numeric(frame["Sampled volume [L]"], errors="coerce")
    if frame["Profile"].eq("").any() or frame["Depth [m]"].isna().any():
        raise ValueError("EcoPart contient un profil ou une profondeur vide")
    if (frame["Sampled volume [L]"] <= 0).any():
        raise ValueError("EcoPart contient un volume nul ou négatif")
    if frame.duplicated(["Profile", "Depth [m]"]).any():
        raise ValueError("EcoPart contient des doublons (Profile, Depth [m])")

    progress(f"EcoPart : manifeste du projet {project_id}")
    version_id = register_version(database_url, source="ecopart", key=str(project_id), path=path)
    profiles = frame[["Profile"]].drop_duplicates().sort_values("Profile")
    total_profiles = len(profiles)
    profile_ids: dict[str, int] = {}
    for number, profile in enumerate(profiles["Profile"], start=1):
        statement = f"""
            INSERT INTO warehouse.uvp_profile
                (dataset_version_id, ecopart_project_id, ecopart_sample_id, sample_name)
            VALUES ({version_id}, {project_id}, {sql_literal(profile)}, {sql_literal(profile)})
            ON CONFLICT (dataset_version_id, ecopart_project_id, ecopart_sample_id)
            DO UPDATE SET sample_name = EXCLUDED.sample_name
            RETURNING id
        """
        profile_ids[profile] = returned_id(psql(database_url, statement))
        if number == 1 or number == total_profiles or number % 100 == 0:
            progress(f"EcoPart : profils {number}/{total_profiles}")

    psql(
        database_url,
        "DELETE FROM warehouse.uvp_bin WHERE profile_id IN ("
        + ",".join(str(value) for value in profile_ids.values())
        + ")",
    )
    bin_rows = []
    for index, row in frame.iterrows():
        profile_id = profile_ids[str(row["Profile"])]
        source_key = f"{row['Profile']}:{row['Depth [m]']}"
        bin_rows.append(
            f"{profile_id}\t{csv_escape(source_key)}\t{row['Depth [m]'] - 2.5:g}\t"
            f"{row['Depth [m]'] + 2.5:g}\t" + r"\N" + f"\t{row['Sampled volume [L]']!r}"
        )
    copy_sql = (
        "COPY warehouse.uvp_bin(profile_id,source_bin_key,depth_min_m,depth_max_m," 
        "pressure_dbar,sampled_volume_l) FROM STDIN WITH (FORMAT text)"
    )
    progress(f"EcoPart : chargement de {len(bin_rows)} bins")
    psql(database_url, copy_sql, stdin="\n".join(bin_rows) + "\n")
    return {"dataset_version_id": version_id, "profiles": len(profile_ids), "bins": len(frame)}


def csv_escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def load_ctd(database_url: str, path: Path, *, dataset_key: str) -> dict:
    frame = pd.read_csv(path)
    required = {"station", "cast_number", "PRES"}
    missing = sorted(required.difference(map(str, frame.columns)))
    if missing:
        raise ValueError("Export CTD invalide, colonnes absentes : " + ", ".join(missing))
    progress(f"CTD : manifeste {dataset_key}")
    version_id = register_version(database_url, source="amundsen_ctd", key=dataset_key, path=path)
    for code, (name, unit) in CTD_CODES.items():
        if code not in frame.columns:
            continue
        statement = f"""
            INSERT INTO warehouse.ctd_variable
                (variable_key, canonical_name, canonical_unit, description, source_code, source_instance)
            VALUES ({sql_literal(code)}, {sql_literal(name)}, {sql_literal(unit)},
                    {sql_literal(name)}, {sql_literal(code)}, 'amundsen')
            ON CONFLICT (variable_key) DO UPDATE SET canonical_unit = EXCLUDED.canonical_unit
        """
        psql(database_url, statement)

    profile_ids: dict[tuple[str, str], int] = {}
    groups = list(frame.groupby(["station", "cast_number"], dropna=False))
    for number, ((station, cast), group) in enumerate(groups, start=1):
        first = group.iloc[0]
        source_key = f"{station}-{cast}"
        sampled_at = first.get("time")
        statement = f"""
            INSERT INTO warehouse.ctd_profile
                (dataset_version_id, source_profile_key, station_key, sampled_at,
                 latitude, longitude)
            VALUES ({version_id}, {sql_literal(source_key)}, {sql_literal(station)},
                    {sql_literal(sampled_at)}, {sql_literal(first.get('latitude'))},
                    {sql_literal(first.get('longitude'))})
            ON CONFLICT (dataset_version_id, source_profile_key)
            DO UPDATE SET station_key = EXCLUDED.station_key
            RETURNING id
        """
        profile_ids[(str(station), str(cast))] = returned_id(psql(database_url, statement))
        if number == 1 or number == len(groups) or number % 25 == 0:
            progress(f"CTD : profils {number}/{len(groups)}")

    if profile_ids:
        psql(
            database_url,
            "DELETE FROM warehouse.ctd_measurement WHERE profile_id IN ("
            + ",".join(str(value) for value in profile_ids.values())
            + ")",
        )
    rows = []
    for index, row in frame.iterrows():
        profile_id = profile_ids[(str(row["station"]), str(row["cast_number"]))]
        depth = row.get("PRES")
        for code in CTD_CODES:
            if code not in frame.columns or pd.isna(row[code]):
                continue
            rows.append(
                "\t".join(
                    map(str, [
                        profile_id,
                        f"{index}:{code}",
                        index,
                        r"\N",
                        depth,
                        code,
                        CTD_CODES[code][0],
                        "",
                        row[code],
                        CTD_CODES[code][1] or "unknown",
                    ])
                )
            )
    if rows:
        progress(f"CTD : chargement de {len(rows)} mesures")
        copy_sql = (
            "COPY warehouse.ctd_measurement(profile_id,source_row_key,scan_key,depth_m,pressure_dbar,"
            "variable_key,variable_definition,sensor_channel,value,unit) FROM STDIN WITH (FORMAT text)"
        )
        psql(database_url, copy_sql, stdin="\n".join(rows) + "\n")
    return {"dataset_version_id": version_id, "profiles": len(profile_ids), "measurements": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("WAREHOUSE_DATABASE_URL"), required=False)
    parser.add_argument("--staging-dir", type=Path, default=Path("data/warehouse_staging"))
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--ecopart-tsv", type=Path)
    parser.add_argument("--ecopart-url")
    parser.add_argument("--ecopart-encoding", default="utf-8")
    parser.add_argument("--ecopart-project-id", type=int)
    parser.add_argument("--ecotaxa-project-id", type=int)
    parser.add_argument("--ctd-tsv", type=Path)
    parser.add_argument("--ctd-url")
    parser.add_argument("--ctd-dataset-key", default="amundsen12713")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url ou WAREHOUSE_DATABASE_URL est requis")
    args.staging_dir.mkdir(parents=True, exist_ok=True)
    state_file = args.state_file or (args.staging_dir / "load_state.json")
    state = load_state(state_file)
    target_key = hashlib.sha256(args.database_url.encode()).hexdigest()
    if state.get("target_key") != target_key:
        state = {"target_key": target_key}
    if (args.ecopart_tsv or args.ecopart_url) and args.ecopart_project_id is None:
        parser.error("--ecopart-project-id est requis pour EcoPart")
    if args.ecopart_project_id and not (args.ecopart_tsv or args.ecopart_url):
        parser.error("--ecopart-project-id nécessite --ecopart-tsv ou --ecopart-url")
    if not (args.ecopart_tsv or args.ecopart_url or args.ctd_tsv or args.ctd_url):
        parser.error("fournir au moins une source EcoPart ou CTD")

    results = {}
    if args.ecopart_tsv or args.ecopart_url:
        path = args.ecopart_tsv
        if path is None:
            path = fetch(args.ecopart_url, args.staging_dir / "ecopart.tsv")
        digest = sha256(path)
        previous = state.get("ecopart") or {}
        if previous.get("status") == "complete" and previous.get("sha256") == digest:
            progress("EcoPart : déjà terminé, reprise ignorée")
            results["ecopart"] = previous.get("result", {})
        else:
            try:
                results["ecopart"] = load_ecopart(
                    args.database_url, path,
                    project_id=args.ecopart_project_id,
                    ecotaxa_project_id=args.ecotaxa_project_id,
                    encoding=args.ecopart_encoding,
                )
            except Exception:
                state["ecopart"] = {"status": "failed", "sha256": digest}
                save_state(state_file, state)
                raise
            state["ecopart"] = {"status": "complete", "sha256": digest, "result": results["ecopart"]}
            save_state(state_file, state)
            progress("EcoPart : terminé")
    if args.ctd_tsv or args.ctd_url:
        path = args.ctd_tsv
        if path is None:
            path = fetch(args.ctd_url, args.staging_dir / "amundsen_ctd.csv")
        digest = sha256(path)
        previous = state.get("ctd") or {}
        if previous.get("status") == "complete" and previous.get("sha256") == digest:
            progress("CTD : déjà terminé, reprise ignorée")
            results["ctd"] = previous.get("result", {})
        else:
            try:
                results["ctd"] = load_ctd(args.database_url, path, dataset_key=args.ctd_dataset_key)
            except Exception:
                state["ctd"] = {"status": "failed", "sha256": digest}
                save_state(state_file, state)
                raise
            state["ctd"] = {"status": "complete", "sha256": digest, "result": results["ctd"]}
            save_state(state_file, state)
            progress("CTD : terminé")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
