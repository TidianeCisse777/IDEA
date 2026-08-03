"""Cache persistant des résultats scientifiques distants."""

from __future__ import annotations

import pandas as pd

from core.scientific_result_cache import (
    build_result_cache_key,
    load_result,
    save_result,
)


def test_result_cache_key_changes_with_data_or_scientific_parameters(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ERDDAP_CACHE_PATH", str(tmp_path / "source-cache.sqlite"))
    source = pd.DataFrame({"sample_id": [1, 2], "latitude": [60.0, 61.0]})
    key = build_result_cache_key(source, {"variables": ["temperature"], "year": 2050})
    same = build_result_cache_key(source.copy(), {"year": 2050, "variables": ["temperature"]})
    changed_data = build_result_cache_key(
        source.assign(latitude=[60.0, 62.0]),
        {"variables": ["temperature"], "year": 2050},
    )
    changed_request = build_result_cache_key(
        source,
        {"variables": ["temperature"], "year": 2100},
    )

    assert key == same
    assert key != changed_data
    assert key != changed_request


def test_result_cache_round_trip_keeps_rows_date_and_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("ERDDAP_CACHE_PATH", str(tmp_path / "source-cache.sqlite"))
    source = pd.DataFrame({"sample_id": [1, 2]})
    result = source.assign(match_status=["matched", "no_value"], value=[3.5, pd.NA])
    key = build_result_cache_key(source, {"scenario": "SSP5-8.5"})

    saved = save_result(
        "bio_oracle_enrichment",
        key,
        result,
        provenance={"scenario": "SSP5-8.5", "dataset_ids": ["thetao"]},
    )
    loaded = load_result("bio_oracle_enrichment", key)

    pd.testing.assert_frame_equal(loaded.dataframe, result)
    assert loaded.cached_at == saved.cached_at
    assert loaded.provenance["scenario"] == "SSP5-8.5"
    assert loaded.n_rows == 2
