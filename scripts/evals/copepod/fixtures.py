from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(
    "/Users/tidianecisse/PROJET_INFO/assistant-copepodes-specs/data_exploration/examples_tsv"
)
# ── primary sources (raw, single-origin) ─────────────────────────────────────
ECOTAXA = FIXTURES / "ecotaxa_green_edge_sample_200.tsv"       # EcoTaxa project 2331, Green Edge
ECOTAXA_SMALL = FIXTURES / "ecotaxa_sample_50.tsv"             # EcoTaxa project 1165, 50 objects
ECOTAXA_UVP5 = FIXTURES / "uvp_amundsen_1165_ecotaxa_object_sample.tsv"  # EcoTaxa 1165, UVP5 Amundsen

ECOPART = FIXTURES / "uvp_amundsen_105_ecopart_particles_reduced.tsv"  # EcoPart UVP5 Amundsen 105

AMUNDSEN_CTD = FIXTURES / "amundsen_12713_ctd_2018_sample.tsv"          # CTD Amundsen full survey
AMUNDSEN_CTD_IPS007 = FIXTURES / "amundsen_12713_ctd_ips007_match_sample.tsv"  # CTD matched to station IPS007

NEOLABS_TAXON = FIXTURES / "neolabs_taxon_zooplankton_abundances.csv"   # NeoLabs taxonomy counts
NEOLABS_LOKI = FIXTURES / "neolabs_loki_profils_sample.csv"             # NeoLabs LOKI profil deployments

BIO_ORACLE = FIXTURES / "bio_oracle_si_ssp126_sample.csv"      # Bio-Oracle silicate SSP126 2020
OGSL = FIXTURES / "ogsl_ctd_biodiv_sample.csv"                  # OGSL CTD biodiversity 2024

# ── derived / pre-joined files (enriched or comparison outputs) ───────────────
ECOPART_CTD_COMPARE = FIXTURES / "uvp_amundsen_105_ecopart_vs_amundsen_ctd_compare.tsv"
ECOTAXA_UVP5_ENRICHED = FIXTURES / "uvp_amundsen_1165_105_enriched_nearest_depth.tsv"
ECOTAXA_JOIN_PREVIEW = FIXTURES / "uvp_amundsen_1165_105_join_preview.tsv"


def _stage_fixture(session_id: str, path: Path) -> dict:
    """Copy a fixture into the eval upload directory without hitting the HTTP rate limiter."""
    user_id = "eval-user"
    upload_dir = ROOT / "static" / user_id / session_id / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / path.name
    shutil.copy2(path, destination)
    return {
        "filename": path.name,
        "size": destination.stat().st_size,
        "path": str(destination.relative_to(upload_dir)),
        "scan_result": "Staged locally for eval (HTTP upload bypassed)",
    }


def _upload_fixture(client: Any, session_id: str, path: Path) -> dict:
    """Backward-compatible alias for _stage_fixture."""
    return _stage_fixture(session_id, path)


def _uploaded_path(session_id: str, filename: str) -> Path:
    return Path("static") / "eval-user" / session_id / "uploads" / filename


def _uploaded_path_label(session_id: str, filename: str) -> tuple[str, str]:
    """Return (local_path, canonical_/app/static_path)."""
    local_path = _uploaded_path(session_id, filename).resolve()
    canonical_path = Path("/app/static") / "eval-user" / session_id / "uploads" / filename
    return str(local_path), str(canonical_path)


def _file_entry(path: Path, inspect_report: dict) -> dict:
    return {
        "file_path": str(path),
        "original_filename": path.name,
        "size_bytes": path.stat().st_size,
        "content_hash": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        "uploaded_at": "2026-05-26T12:00:00+00:00",
        "inspection_tool_version": "inspect_file:v1",
        "source_type_guess": inspect_report["source_type_guess"],
    }


def _data_understanding_artifact(tools: dict[str, Any], path: Path) -> dict:
    inspected = tools["inspect_file"](str(path), sample_rows=10)
    roles = tools["infer_column_roles"](inspected["columns"], inspected["metadata"])
    summary = tools["summarize_understanding"](inspected, roles)
    return {
        "files": [
            {
                **_file_entry(path, inspected),
                "columns": inspected["columns"],
                "roles": roles["roles"],
                "taxonomic_validation_status": summary["taxonomic_validation_status"],
                "quality_limits": summary["quality_limits"],
            }
        ],
        "global": {
            "column_catalogue": summary["column_catalogue"],
            "possible_joins_or_couplings": summary["possible_joins_or_couplings"],
            "missing_or_ambiguous_data": summary["missing_or_ambiguous_data"],
        },
        "column_catalogue": summary["column_catalogue"],
        "coverage_assessment": summary["coverage_assessment"],
        "overrides": [],
    }


def _seed_active_data_understanding(
    *,
    client: Any,
    tools: dict[str, Any],
    session_id: str,
    session_key: str,
    fixture_paths: list[Path],
) -> dict[str, Any]:
    uploaded_paths: list[Path] = []
    for path in fixture_paths:
        upload = _stage_fixture(session_id, path)
        uploaded_paths.append(_uploaded_path(session_id, upload["filename"]).resolve())

    draft_payload = {
        "files": [
            {"file_path": str(p), "original_filename": p.name}
            for p in uploaded_paths
        ],
        "global": {},
        "overrides": [],
    }
    du_draft = tools["create_data_understanding_draft"](session_key, draft_payload)
    du_active = tools["activate_data_understanding"](session_key, du_draft["version_id"])
    return {
        "draft": du_draft,
        "active": du_active,
        "uploaded_paths": uploaded_paths,
    }
