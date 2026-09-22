#!/usr/bin/env python3
"""Load the validated FILET CSV export as a versioned warehouse dataset.

The source values are already calculated by the laboratory.  This loader only
normalizes the wide stage columns into rows; it does not recalculate abundance,
biomass, volumes, or infer links to CTD, EcoTaxa, EcoPart, or UVP.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
from datetime import datetime
from pathlib import Path


from assign_filet_zones import DEFAULT_ZONES, ZONE_VERSION, load_features, zone_for


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path.home() / "Desktop"
PREFIX = "project_IDEA_taxonomy_samples+analyses-data_&_metadata-20260526"
DEFAULT_SAMPLES = DESKTOP / f"{PREFIX}(taxonomy samples-data).csv"
DEFAULT_ABUNDANCE = DESKTOP / f"{PREFIX}(copepod abund&biomass-data).csv"
DEFAULT_DICTIONARY = DESKTOP / f"{PREFIX}(copepod abund&biomass-metadata).csv"

STAGES_WITH_BIOMASS = ("C1", "C2", "C3", "C4", "C5", "M", "F", "COP_NS", "COPEPODID")
STAGES_WITHOUT_BIOMASS = ("N1", "N2", "N3", "N4", "N5", "N6", "NAUP_NS", "NAUPLIUS", "ALL_STAGES")
STAGES = STAGES_WITH_BIOMASS + STAGES_WITHOUT_BIOMASS

SAMPLE_COLUMNS = {
    "sampling_year", "deployment_id", "sampling_platform", "station_name",
    "deployment_datetime_start", "deployment_datetime_end", "gear", "tow_type",
    "cast_number", "latitude", "longitude", "net_mesh_size", "max_sample_depth",
    "min_sample_depth", "depth_calc_net_filtered_vol", "flowmeter_calc_vol",
    "number_of_nets", "sample_nets", "sample_id", "net_sampling_ids",
    "subsampling_quantity", "subsampling_unit", "analysis_id", "analysis_type",
    "analysis_contract", "analysis_datetime", "analysis_protocol_id",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return None if not value or value.upper() in {"NA", "N/A", "NULL"} else value


def number(value: str | None) -> str | None:
    """Return source decimal text unchanged enough for PostgreSQL numeric."""
    return clean(value)


def timestamp(value: str | None) -> datetime | None:
    value = clean(value)
    return datetime.fromisoformat(value) if value else None


def split_nets(value: str | None) -> list[str]:
    """Extract only explicit list separators; the original list remains on sample."""
    value = clean(value)
    if not value:
        return []
    return [item.strip() for item in re.split(r"[;,]", value) if item.strip()]


def stage_columns(stage: str) -> tuple[str, str, str, str | None, str | None]:
    prefix = stage
    return (
        f"{prefix}_SAMPLE_ABUND (nbr of ind.)",
        f"{prefix}_ABUND (ind./m3 depth vol.)",
        f"{prefix}_ABUND (ind./m3 flowmeter vol.)",
        f"{prefix}_BIOMASS (µg C m-3 depth vol.)" if stage in STAGES_WITH_BIOMASS else None,
        f"{prefix}_BIOMASS (µg C m-3 flowmeter vol.)" if stage in STAGES_WITH_BIOMASS else None,
    )


def abundance_rows(path: Path):
    """Yield source-row x stage values, retaining explicit zeros and skipping all-null stages."""
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"SAMPLE_ID", "ANALYSIS_ID", "TAXON_ID"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Colonnes FILET d'abondance requises absentes")
        for source_row_number, raw in enumerate(reader, start=2):
            # ``required`` is a set used only for header validation: preserve
            # this explicit key order for the warehouse grain.
            sample_id = clean(raw["SAMPLE_ID"])
            analysis_id = clean(raw["ANALYSIS_ID"])
            taxon_id = clean(raw["TAXON_ID"])
            if not sample_id or not analysis_id or not taxon_id:
                raise ValueError(f"Clé d'abondance absente à la ligne {source_row_number}")
            for stage in STAGES:
                fields = stage_columns(stage)
                values = tuple(number(raw[field]) if field else None for field in fields)
                if any(value is not None for value in values):
                    yield (source_row_number, sample_id, analysis_id, taxon_id, stage, *values)


def sample_records(path: Path) -> tuple[dict[str, dict], list[dict]]:
    """Collapse repeated sample metadata while retaining every declared analysis."""
    samples: dict[str, dict] = {}
    analyses: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not SAMPLE_COLUMNS.issubset(reader.fieldnames or []):
            raise ValueError("Colonnes FILET d'échantillon requises absentes")
        for raw in reader:
            sample_id = clean(raw["sample_id"])
            deployment_id = clean(raw["deployment_id"])
            if not sample_id or not deployment_id:
                raise ValueError("sample_id ou deployment_id FILET absent")
            metadata = {key: clean(raw[key]) for key in SAMPLE_COLUMNS - {"analysis_id", "analysis_type", "analysis_contract", "analysis_datetime", "analysis_protocol_id"}}
            previous = samples.setdefault(sample_id, metadata)
            if previous != metadata:
                raise ValueError(f"Métadonnées contradictoires pour sample_id={sample_id}")
            analysis_id = clean(raw["analysis_id"])
            if analysis_id:
                analyses.append({
                    "sample_id": sample_id, "analysis_id": analysis_id,
                    "analysis_type": clean(raw["analysis_type"]),
                    "analysis_contract": clean(raw["analysis_contract"]),
                    "analysis_datetime": timestamp(raw["analysis_datetime"]),
                    "analysis_protocol_id": clean(raw["analysis_protocol_id"]),
                })
    if len({(a["sample_id"], a["analysis_id"]) for a in analyses}) != len(analyses):
        raise ValueError("Clé (sample_id, analysis_id) dupliquée")
    return samples, analyses


def connection(database_url: str | None = None):
    import psycopg
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env.warehouse")
    except ImportError:
        pass
    if database_url:
        return psycopg.connect(database_url)
    password = os.getenv("WAREHOUSE_POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("WAREHOUSE_POSTGRES_PASSWORD absent")
    return psycopg.connect(
        host=os.getenv("WAREHOUSE_POSTGRES_HOST", "localhost"),
        port=os.getenv("WAREHOUSE_POSTGRES_PORT", "55432"),
        dbname=os.getenv("WAREHOUSE_POSTGRES_DB", "neolab_warehouse"),
        user=os.getenv("WAREHOUSE_POSTGRES_USER", "neolab"), password=password,
    )


def load(samples_path: Path, abundance_path: Path, dictionary_path: Path, database_url: str | None = None, zones_path: Path = DEFAULT_ZONES) -> dict:
    for path in (samples_path, abundance_path, dictionary_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    hashes = {path.name: sha256(path) for path in (samples_path, abundance_path, dictionary_path)}
    version_hash = hashlib.sha256("".join(f"{name}:{value}\n" for name, value in sorted(hashes.items())).encode()).hexdigest()
    samples, analyses = sample_records(samples_path)
    zones = load_features(zones_path)
    rows = list(abundance_rows(abundance_path))
    manifest = ";".join(str(path.resolve()) for path in (samples_path, abundance_path, dictionary_path))
    with connection(database_url) as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO warehouse.dataset_version
            (source_instance,dataset_key,version_key,file_manifest_uri,sha256)
            VALUES ('filet','neolab-filet','2026-05-26',%s,%s)
            ON CONFLICT (source_instance,dataset_key,version_key) DO UPDATE
              SET file_manifest_uri=EXCLUDED.file_manifest_uri, sha256=EXCLUDED.sha256
            RETURNING id""", (manifest, version_hash))
        version_id = cur.fetchone()[0]
        cur.execute("DELETE FROM warehouse.filet_abundance WHERE dataset_version_id=%s", (version_id,))
        # FILET–UVP and FILET–CTD are derived links. They must be rebuilt after
        # a source reload, before their parent samples are replaced.
        cur.execute("DELETE FROM warehouse.filet_uvp_match WHERE filet_sample_id IN (SELECT id FROM warehouse.filet_sample WHERE dataset_version_id=%s)", (version_id,))
        cur.execute("DELETE FROM warehouse.filet_ctd WHERE filet_sample_id IN (SELECT id FROM warehouse.filet_sample WHERE dataset_version_id=%s)", (version_id,))
        cur.execute("DELETE FROM warehouse.filet_sample_net WHERE sample_ref IN (SELECT id FROM warehouse.filet_sample WHERE dataset_version_id=%s)", (version_id,))
        cur.execute("DELETE FROM warehouse.filet_analysis WHERE dataset_version_id=%s", (version_id,))
        cur.execute("DELETE FROM warehouse.filet_sample WHERE dataset_version_id=%s", (version_id,))
        sample_values = []
        for data in samples.values():
            zone_key, zone_name, zone_source, zone_status = zone_for(number(data["longitude"]), number(data["latitude"]), zones)
            sample_values.append((version_id, data["sample_id"], data["deployment_id"], number(data["sampling_year"]), data["sampling_platform"], data["station_name"], timestamp(data["deployment_datetime_start"]), timestamp(data["deployment_datetime_end"]), data["cast_number"], number(data["latitude"]), number(data["longitude"]), zone_key, zone_name, zone_source, ZONE_VERSION, zone_status, data["gear"], data["tow_type"], number(data["min_sample_depth"]), number(data["max_sample_depth"]), number(data["net_mesh_size"]), number(data["depth_calc_net_filtered_vol"]), number(data["flowmeter_calc_vol"]), number(data["number_of_nets"]), data["sample_nets"], data["net_sampling_ids"], number(data["subsampling_quantity"]), data["subsampling_unit"]))
        cur.executemany("""INSERT INTO warehouse.filet_sample
          (dataset_version_id,sample_id,deployment_id,sampling_year,sampling_platform,station_name,deployment_datetime_start,deployment_datetime_end,cast_number,latitude,longitude,marine_zone_key,marine_zone_name,marine_zone_source,marine_zone_version,marine_zone_assignment_status,gear,tow_type,min_sample_depth,max_sample_depth,net_mesh_size,depth_calc_net_filtered_vol,flowmeter_calc_vol,number_of_nets,sample_nets,net_sampling_ids,subsampling_quantity,subsampling_unit)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", sample_values)
        cur.execute("SELECT id,sample_id FROM warehouse.filet_sample WHERE dataset_version_id=%s", (version_id,))
        sample_ids = {sample_id: sample_ref for sample_ref, sample_id in cur.fetchall()}
        cur.execute("SELECT id,net_sampling_ids FROM warehouse.filet_sample WHERE dataset_version_id=%s", (version_id,))
        net_values = [(sample_ref, net) for sample_ref, raw_nets in cur.fetchall() for net in split_nets(raw_nets)]
        cur.executemany("INSERT INTO warehouse.filet_sample_net (sample_ref,net_sampling_id) VALUES (%s,%s)", net_values)
        cur.executemany("""INSERT INTO warehouse.filet_analysis
          (dataset_version_id,sample_ref,sample_id,analysis_id,analysis_type,analysis_contract,analysis_datetime,analysis_protocol_id)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", [(version_id, sample_ids[a["sample_id"]], a["sample_id"], a["analysis_id"], a["analysis_type"], a["analysis_contract"], a["analysis_datetime"], a["analysis_protocol_id"]) for a in analyses])
        known = {(a["sample_id"], a["analysis_id"]) for a in analyses}
        cur.executemany("""INSERT INTO warehouse.filet_abundance
          (dataset_version_id,source_row_number,sample_id,analysis_id,taxon_id,stage,sample_abundance,abundance_depth_ind_m3,abundance_flowmeter_ind_m3,biomass_depth_ug_c_m3,biomass_flowmeter_ug_c_m3,metadata_dataset_version_id)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [(version_id, *row, version_id if (row[1], row[2]) in known else None) for row in rows])
        return {"dataset_version_id": version_id, "samples": len(samples), "analyses": len(analyses), "abundance_rows": len(rows), "source_abundance_rows": len({row[0] for row in rows}), "hashes": hashes}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--abundance", type=Path, default=DEFAULT_ABUNDANCE)
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY)
    parser.add_argument("--database-url")
    parser.add_argument("--zones", type=Path, default=DEFAULT_ZONES)
    args = parser.parse_args()
    print(load(args.samples, args.abundance, args.dictionary, args.database_url, args.zones))


if __name__ == "__main__":
    main()
