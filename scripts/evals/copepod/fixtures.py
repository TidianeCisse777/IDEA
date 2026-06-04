"""Shared file-path constants and upload helpers for copepod evals."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _resolve_copepod_specs_root() -> Path | None:
    candidates = []
    env_root = os.getenv("COPEPOD_SPECS_DIR")
    if env_root:
        candidates.append(Path(env_root))
    candidates.append(ROOT.parent / "assistant-copepodes-specs")
    for root in candidates:
        if root.exists():
            return root
    return None


_SPECS_ROOT = _resolve_copepod_specs_root()
if _SPECS_ROOT is None:
    raise FileNotFoundError(
        "Copepod fixture repo not found. Clone assistant-copepodes-specs beside IDEA or set COPEPOD_SPECS_DIR."
    )

FIXTURES = _SPECS_ROOT / "data_exploration/examples_tsv"

# Primary sources (raw, single-origin)
ECOTAXA = FIXTURES / "ecotaxa_green_edge_sample_200.tsv"
ECOTAXA_SMALL = FIXTURES / "ecotaxa_sample_50.tsv"
ECOTAXA_UVP5 = FIXTURES / "uvp_amundsen_1165_ecotaxa_object_sample.tsv"
ECOPART = FIXTURES / "uvp_amundsen_105_ecopart_particles_reduced.tsv"
AMUNDSEN_CTD = FIXTURES / "amundsen_12713_ctd_2018_sample.tsv"
AMUNDSEN_CTD_IPS007 = FIXTURES / "amundsen_12713_ctd_ips007_match_sample.tsv"
NEOLABS_TAXON = FIXTURES / "neolabs_taxon_zooplankton_abundances.csv"
NEOLABS_LOKI = FIXTURES / "neolabs_loki_profils_sample.csv"
BIO_ORACLE = FIXTURES / "bio_oracle_si_ssp126_sample.csv"
OGSL = FIXTURES / "ogsl_ctd_biodiv_sample.csv"

# Derived / pre-joined files
ECOPART_CTD_COMPARE = FIXTURES / "uvp_amundsen_105_ecopart_vs_amundsen_ctd_compare.tsv"
ECOTAXA_UVP5_ENRICHED = FIXTURES / "uvp_amundsen_1165_105_enriched_nearest_depth.tsv"
ECOTAXA_JOIN_PREVIEW = FIXTURES / "uvp_amundsen_1165_105_join_preview.tsv"
NEOLABS_TAXON_AMUNDSEN_CTD = FIXTURES / "neolabs_taxonomy_abundance_amundsen_ctd.tsv"


def stage_fixture(session_id: str, path: Path, user_id: str = "eval-user") -> dict:
    """Copy a fixture into the eval upload directory without hitting any HTTP layer."""
    upload_dir = ROOT / "static" / user_id / session_id / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / path.name
    shutil.copy2(path, destination)
    return {
        "filename": path.name,
        "size": destination.stat().st_size,
        "local_path": str(destination.resolve()),
        "canonical_path": f"/app/static/{user_id}/{session_id}/uploads/{path.name}",
    }
