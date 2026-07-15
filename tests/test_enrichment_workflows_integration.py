"""Integration suite — EcoTaxa ↔ EcoPart enrichment, the 3 workflows end-to-end.

Run it with:

    LANGCHAIN_TRACING_V2=false python -m pytest tests/test_enrichment_workflows_integration.py -v

What it checks (against the REAL EcoPart demo file, so the expected values are
derived from the data, not hardcoded):

  1. Binning reproduces the real EcoPart 5 m grid.
  2. Workflow 1 — two local datasets in session → `join_ecotaxa_ecopart`.
  3. Workflow 2 — EcoTaxa local + EcoPart fetched remotely → `enrich_ecotaxa_with_ecopart_remote`.
  4. Workflow 3 — full remote: real `query_ecotaxa` → real `enrich_ecotaxa_with_ecopart_remote`.
  5. Metrics — per-bin copepod density (m5 shape) computes on the joined real-data table.
  6. Warning — campaign mismatch (no shared profile) is surfaced, no join stored.
  7. Warning — partial depth coverage reports a partial match count and leaves NaN.

Every workflow goes through the real tool objects (`make_ecopart_tools`,
`make_source_tools`); only the EcoTaxa/EcoPart HTTP clients are mocked.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tools.session_store import SessionStore

_ECOPART_DEMO = Path("data/demo/ecopart_hawkechannel_30jan.tsv")
_PROFILE = "hc_02_030924"  # a real profile whose cast starts at bin 12.5 m


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch):
    """Fresh in-memory store shared by every tool module (backend-agnostic)."""
    store = SessionStore()
    monkeypatch.setattr("tools.session_store.default_store", store)
    monkeypatch.setattr("tools.ecopart_sources._store", store)
    monkeypatch.setattr("tools.copepod_sources._store", store)
    monkeypatch.setattr("tools.bio_oracle_sources._store", store)
    return store


def _bio_tile(value: float) -> pd.DataFrame:
    """One-row Bio-ORACLE tile DataFrame, shaped like _fetch_bio_oracle_bbox output."""
    tile = pd.DataFrame([
        {"time": "2050-01-01T00:00:00Z", "latitude": 60.0, "longitude": -65.0, "value": value}
    ])
    tile.attrs["dataset_id"] = "thetao_ssp585_2020_2100_depthsurf"
    return tile


def _real_ecopart(profile: str | None = None) -> pd.DataFrame:
    """Load the real EcoPart demo TSV (latin-1), optionally restricted to one profile."""
    df = pd.read_csv(_ECOPART_DEMO, sep="\t", encoding="latin-1")
    if profile is not None:
        df = df[df["Profile"] == profile].copy()
    return df


def _ecotaxa_aligned_to(profile: str, bins: list[float], taxa: list[str]) -> pd.DataFrame:
    """Build an EcoTaxa object table whose objects sit at the given EcoPart bin centers."""
    return pd.DataFrame({
        "obj_orig_id": [f"{profile}_{i}" for i in range(len(bins))],
        "object_depth_min": bins,  # a bin center maps back to itself via (d//5)*5+2.5
        "taxon": taxa,
    })


def _vol_for_bin(ep: pd.DataFrame, profile: str, bin_center: float) -> float:
    """The real EcoPart sampled volume for one (profile, bin)."""
    row = ep[(ep["Profile"] == profile) & (ep["Depth [m]"] == bin_center)]
    return float(row["Sampled volume [L]"].iloc[0])


def _join_tool(thread_id: str):
    from tools.ecopart_sources import make_ecopart_tools
    return next(t for t in make_ecopart_tools(thread_id) if t.name == "join_ecotaxa_ecopart")


def _enrich_tool(thread_id: str):
    from tools.ecopart_sources import make_ecopart_tools
    return next(
        t for t in make_ecopart_tools(thread_id)
        if t.name == "enrich_ecotaxa_with_ecopart_remote"
    )


# --------------------------------------------------------------------------- #
# 1. Binning
# --------------------------------------------------------------------------- #
def test_binning_reproduces_real_ecopart_grid():
    ep = _real_ecopart()
    real_bins = sorted(ep["Depth [m]"].dropna().unique())

    # The join formula must reproduce the real EcoPart bin centers exactly.
    depth = pd.Series(real_bins)
    recomputed = ((depth // 5) * 5 + 2.5).tolist()
    assert recomputed == real_bins
    # And the grid is a regular 5 m grid of x.5 centers.
    assert real_bins[0] == 2.5 or real_bins[0] % 5 == 2.5
    assert all(round(b - a, 2) == 5.0 for a, b in zip(real_bins, real_bins[1:]))


# --------------------------------------------------------------------------- #
# 2. Workflow 1 — two local datasets → local join
# --------------------------------------------------------------------------- #
def test_workflow1_two_local_files_join(_isolated_store):
    ep = _real_ecopart()
    bins = [12.5, 17.5, 22.5]
    et = _ecotaxa_aligned_to(_PROFILE, bins, ["Calanus", "Calanus", "Oithona"])

    _isolated_store.set("wf1:ecotaxa", et, {"source": "ecotaxa:file"})
    _isolated_store.set("wf1:ecopart", ep, {"source": "ecopart:105", "project_id": 105})

    result = _join_tool("wf1").invoke({})

    merged = _isolated_store.get("wf1:ecotaxa_ecopart")["df"]
    assert "depth_bin" in merged.columns
    by_obj = merged.set_index("obj_orig_id")
    for i, b in enumerate(bins):
        assert by_obj.loc[f"{_PROFILE}_{i}", "ecopart_Sampled volume [L]"] == _vol_for_bin(ep, _PROFILE, b)
    assert "3 matchées" in result


# --------------------------------------------------------------------------- #
# 3. Workflow 2 — EcoTaxa local, EcoPart fetched remotely
# --------------------------------------------------------------------------- #
def test_workflow2_ecotaxa_local_then_remote_ecopart(_isolated_store):
    bins = [12.5, 17.5]
    et = _ecotaxa_aligned_to(_PROFILE, bins, ["Calanus", "Oithona"])
    # File-style EcoTaxa with coordinates but no project_id → bbox resolution path.
    et["sample_lat"] = 48.5
    et["sample_long"] = -68.1
    _isolated_store.set("wf2:ecotaxa", et, {"source": "file:ecotaxa.tsv"})

    ep_subset = _real_ecopart(_PROFILE)
    client = MagicMock()
    client.search_samples_by_bbox.return_value = [{"id": 11, "lat": 48.5, "lon": -68.1}]
    client.get_sample_metadata.return_value = {"profile_id": _PROFILE, "ecopart_project_id": 105}
    client.start_export.return_value = ["/Task/Show/42"]
    client.download_tsv.return_value = ep_subset

    with patch("tools.ecopart_sources.EcopartClient", return_value=client):
        result = _enrich_tool("wf2").invoke({"confirmed": True})

    assert "Enrichissement terminé" in result
    merged = _isolated_store.get("wf2:ecotaxa_ecopart")["df"]
    by_obj = merged.set_index("obj_orig_id")
    assert by_obj.loc[f"{_PROFILE}_0", "ecopart_Sampled volume [L]"] == _vol_for_bin(ep_subset, _PROFILE, 12.5)
    assert by_obj.loc[f"{_PROFILE}_1", "ecopart_Sampled volume [L]"] == _vol_for_bin(ep_subset, _PROFILE, 17.5)


def test_remote_enrichment_selects_named_ecotaxa_project_not_latest_alias(
    _isolated_store,
):
    """A multi-project export must join the project requested by the caller."""
    thread_id = "multi-project"
    matching = _ecotaxa_aligned_to(
        _PROFILE,
        [12.5, 17.5],
        ["Calanus", "Oithona"],
    )
    unrelated = _ecotaxa_aligned_to(
        "other_leg_profile",
        [12.5],
        ["Calanus"],
    )
    # The latest alias points at another project, reproducing the Baffin export.
    _isolated_store.set(
        f"{thread_id}:ecotaxa",
        unrelated,
        {"source": "ecotaxa:17498", "project_id": 17498},
    )
    _isolated_store.set(
        f"{thread_id}:dataset:df_ecotaxa_14859_bulk_samples",
        matching,
        {
            "source": "ecotaxa:14859",
            "project_id": 14859,
            "variable_name": "df_ecotaxa_14859_bulk_samples",
        },
    )

    ep_subset = _real_ecopart(_PROFILE)
    client = MagicMock()
    client.start_export.return_value = ["/Task/Show/42"]
    client.download_tsv.return_value = ep_subset

    with patch("tools.ecopart_sources.EcopartClient", return_value=client):
        result = _enrich_tool(thread_id).invoke({
            "ecotaxa_project_id": 14859,
            "ecopart_project_id": 1064,
            "confirmed": True,
        })

    assert "2 matchées" in result
    assert "EcoTaxa projet 14859" in result
    assert "EcoTaxa projet 17498" not in result
    merged = _isolated_store.get(f"{thread_id}:ecotaxa_ecopart")["df"]
    assert set(merged["obj_orig_id"].dropna()) == {
        f"{_PROFILE}_0",
        f"{_PROFILE}_1",
    }
    assert merged["obj_orig_id"].isna().any()


# --------------------------------------------------------------------------- #
# 4. Workflow 3 — full remote: real query_ecotaxa → real enrich_remote
# --------------------------------------------------------------------------- #
def test_workflow3_full_remote_query_then_enrich(_isolated_store):
    from tools.copepod_sources import make_source_tools

    thread_id = "wf3"
    bins = [12.5, 17.5, 22.5]

    # Step 1 — real query_ecotaxa, EcoTaxa HTTP client mocked.
    ecotaxa_client = MagicMock()
    ecotaxa_client.start_export.return_value = "job-1"
    ecotaxa_client.download_tsv.return_value = _ecotaxa_aligned_to(
        _PROFILE, bins, ["Calanus", "Calanus", "Oithona"]
    )
    with patch("tools.copepod_sources.EcotaxaClient", return_value=ecotaxa_client):
        query_ecotaxa = next(t for t in make_source_tools(thread_id) if t.name == "query_ecotaxa")
        et_result = query_ecotaxa.invoke({"project_id": 1165})

    assert "chargé" in et_result
    assert _isolated_store.get(f"{thread_id}:ecotaxa")["meta"]["project_id"] == 1165

    # Step 2 — real enrich_remote, EcoPart HTTP client mocked, no args.
    ep_subset = _real_ecopart(_PROFILE)
    ecopart_client = MagicMock()
    ecopart_client.start_export.return_value = ["/Task/Show/42"]
    ecopart_client.download_tsv.return_value = ep_subset
    with patch("tools.ecopart_sources.EcopartClient", return_value=ecopart_client):
        result = _enrich_tool(thread_id).invoke({"confirmed": True})

    # The remote enrich reused the project_id left by query_ecotaxa.
    ecopart_client.start_export.assert_called_once_with(project_id=None, ecotaxa_project_id=1165)
    assert "Enrichissement terminé" in result
    merged = _isolated_store.get(f"{thread_id}:ecotaxa_ecopart")["df"]
    assert merged.set_index("obj_orig_id").loc[f"{_PROFILE}_0", "ecopart_Sampled volume [L]"] == \
        _vol_for_bin(ep_subset, _PROFILE, 12.5)


# --------------------------------------------------------------------------- #
# 5. Metrics — per-bin density on the joined real-data table
# --------------------------------------------------------------------------- #
def test_metrics_per_bin_density_on_joined_real_data(_isolated_store):
    ep = _real_ecopart()
    bins = [12.5, 12.5, 12.5, 17.5, 17.5, 22.5]
    taxa = ["Calanus"] * 6
    et = _ecotaxa_aligned_to(_PROFILE, bins, taxa)
    _isolated_store.set("m5:ecotaxa", et, {"source": "ecotaxa:file"})
    _isolated_store.set("m5:ecopart", ep, {"source": "ecopart:105", "project_id": 105})

    _join_tool("m5").invoke({})
    merged = _isolated_store.get("m5:ecotaxa_ecopart")["df"]

    # m5-shape: per-bin density = objects in bin / that bin's sampled volume (NOT sum/sum).
    per_bin = (
        merged.groupby(["depth_bin", "ecopart_Sampled volume [L]"])
        .size()
        .reset_index(name="n")
    )
    per_bin["dens"] = per_bin["n"] / per_bin["ecopart_Sampled volume [L]"]

    expected = {
        12.5: 3 / _vol_for_bin(ep, _PROFILE, 12.5),
        17.5: 2 / _vol_for_bin(ep, _PROFILE, 17.5),
        22.5: 1 / _vol_for_bin(ep, _PROFILE, 22.5),
    }
    got = dict(zip(per_bin["depth_bin"], per_bin["dens"]))
    for bin_center, dens in expected.items():
        assert got[bin_center] == pytest.approx(dens)


# --------------------------------------------------------------------------- #
# 6. Warning — campaign mismatch (no shared profile)
# --------------------------------------------------------------------------- #
def test_warning_zero_match_on_campaign_mismatch(_isolated_store):
    ep = _real_ecopart()
    # EcoTaxa from an unrelated campaign: its profile id is not in EcoPart.
    et = _ecotaxa_aligned_to("other_cruise_999", [12.5, 17.5], ["Calanus", "Oithona"])
    _isolated_store.set("mm:ecotaxa", et, {"source": "ecotaxa:file"})
    _isolated_store.set("mm:ecopart", ep, {"source": "ecopart:105", "project_id": 105})

    result = _join_tool("mm").invoke({})

    assert "Aucune correspondance" in result
    # No join table is produced on a zero-overlap result.
    assert not _isolated_store.has("mm:ecotaxa_ecopart")


# --------------------------------------------------------------------------- #
# 8. Local import → environmental enrichment (Amundsen / Bio-ORACLE / OGSL)
# --------------------------------------------------------------------------- #
def test_local_import_then_environmental_enrich(_isolated_store, tmp_path, monkeypatch):
    """A file imported locally via load_file is enrichable with an environmental source.

    Starts from the REAL load_file tool (not a hand-built session), then enriches
    with the REAL enrich_with_bio_oracle (only the ERDDAP fetch is mocked). Also
    checks the provenance note names the imported file variable.
    """
    from tools.data_tools import make_tools
    from tools.bio_oracle_sources import make_bio_oracle_tools

    # A plain station file with coordinates — NOT an EcoTaxa export.
    src = tmp_path / "stations.tsv"
    pd.DataFrame({
        "latitude": [60.0],
        "longitude": [-65.0],
        "object_date": ["2018-06-01"],
    }).to_csv(src, sep="\t", index=False)

    # 1) Real load_file (data tools share the isolated store).
    load_file = next(t for t in make_tools("imp", store=_isolated_store) if t.name == "load_file")
    load_msg = load_file.invoke({"path": str(src)})
    assert "df_file_stations" in load_msg

    # 2) Real enrich_with_bio_oracle on the imported file; ERDDAP fetch mocked.
    monkeypatch.setattr(
        "tools.bio_oracle_sources._fetch_bio_oracle_bbox",
        lambda *, variable, scenario, depth_layer, target_year, tile: _bio_tile(8.42),
    )
    enrich = next(
        t for t in make_bio_oracle_tools("imp") if t.name == "enrich_with_bio_oracle"
    )
    result = enrich.invoke(
        {"variables": ["temperature"], "scenarios": ["SSP5-8.5"], "target_year": 2050}
    )

    # Provenance note names the imported file variable, and the value is attached.
    assert "df_file_stations" in result
    keys = _isolated_store.keys("imp:dataset:df_bio_oracle_enriched_")
    enriched = _isolated_store.get(keys[-1])["df"]
    temp_col = next(c for c in enriched.columns if c.startswith("bio_oracle_temperature"))
    assert enriched[temp_col].tolist() == [8.42]


# --------------------------------------------------------------------------- #
# 7. Warning — partial depth coverage (objects above the cast's first bin)
# --------------------------------------------------------------------------- #
def test_warning_partial_depth_coverage_reports_count(_isolated_store):
    ep = _real_ecopart()
    # Profile starts at 12.5 m: objects at 2.5 and 7.5 have no EcoPart bin → NaN.
    et = _ecotaxa_aligned_to(_PROFILE, [2.5, 7.5, 12.5, 17.5], ["Calanus"] * 4)
    _isolated_store.set("dc:ecotaxa", et, {"source": "ecotaxa:file"})
    _isolated_store.set("dc:ecopart", ep, {"source": "ecopart:105", "project_id": 105})

    result = _join_tool("dc").invoke({})
    merged = _isolated_store.get("dc:ecotaxa_ecopart")["df"]
    by_obj = merged.set_index("obj_orig_id")

    # 2 of 4 objects matched a bin; the message must report a partial count.
    assert "2 matchées" in result
    assert pd.isna(by_obj.loc[f"{_PROFILE}_0", "ecopart_Sampled volume [L]"])  # 2.5 m, uncovered
    assert pd.isna(by_obj.loc[f"{_PROFILE}_1", "ecopart_Sampled volume [L]"])  # 7.5 m, uncovered
    assert by_obj.loc[f"{_PROFILE}_2", "ecopart_Sampled volume [L]"] == _vol_for_bin(ep, _PROFILE, 12.5)
    assert by_obj.loc[f"{_PROFILE}_3", "ecopart_Sampled volume [L]"] == _vol_for_bin(ep, _PROFILE, 17.5)
