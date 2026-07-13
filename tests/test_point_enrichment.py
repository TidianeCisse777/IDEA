"""Contract tests for the point-enrichment shell (run_point_enrichment).

The shell is exercised through an in-memory FakeMatcher — no network, no real
source. This is the test surface the deep module buys us: the 12-step sequence
is verified once here; each real matcher tests only its MATCH.
"""
import pandas as pd
import pytest

from core.environment_resolver.coords import CoordsValidation
from tools.point_enrichment import (
    MatchResult,
    NO_COORDINATES_STATUS,
    QueryPoints,
    RequiredCoords,
    run_point_enrichment,
)
from tools.session_store import SessionStore


class FakeMatcher:
    """Records the QueryPoints it receives and returns one value per point."""

    prefix = "fake"
    label = "Fake Source"

    def __init__(self):
        self.seen: QueryPoints | None = None

    def required_coords(self) -> RequiredCoords:
        return RequiredCoords(lat=True, lon=True)

    def dedup_keys(self, coords: CoordsValidation) -> pd.Series:
        keys = []
        for lat, lon in zip(coords.latitude, coords.longitude):
            if pd.isna(lat) or pd.isna(lon):
                keys.append(pd.NA)
            else:
                keys.append((round(float(lat), 4), round(float(lon), 4)))
        return pd.Series(keys, index=coords.latitude.index)

    def match(self, points: QueryPoints) -> MatchResult:
        self.seen = points
        n = len(points)
        columns = pd.DataFrame({"fake_value": [100 + i for i in range(n)]})
        statuses = pd.Series(["matched"] * n)
        return MatchResult(
            columns=columns,
            statuses=statuses,
            method_lines=["Fake: valeur synthétique par point."],
            n_matched=n,
        )


def _store_with(df: pd.DataFrame, thread_id="thr-pe") -> SessionStore:
    store = SessionStore()
    store.set(thread_id, df, {"variable_name": "df_file_test"})
    return store


def test_shell_dedups_remaps_and_adds_status_column():
    # rows 0 and 2 share coords → 1 unique; row 1 distinct; row 3 invalid coords
    df = pd.DataFrame({
        "latitude": [60.0, 61.0, 60.0, None],
        "longitude": [-80.0, -81.0, -80.0, None],
        "payload": ["a", "b", "c", "d"],
    })
    store = _store_with(df)
    matcher = FakeMatcher()

    summary = run_point_enrichment(store, "thr-pe", matcher=matcher)

    # matcher saw only the 2 valid unique points
    assert matcher.seen is not None
    assert len(matcher.seen) == 2

    enriched = store.get("thr-pe:dataset:df_file_test")["df"]
    assert "fake_value" in enriched.columns
    assert "fake_match_status" in enriched.columns
    # duplicate coords (rows 0 & 2) got the SAME value (remap unique→row)
    assert enriched.loc[0, "fake_value"] == enriched.loc[2, "fake_value"]
    assert enriched.loc[0, "fake_match_status"] == "matched"
    # invalid-coord row got the shell status, no value
    assert enriched.loc[3, "fake_match_status"] == NO_COORDINATES_STATUS
    assert pd.isna(enriched.loc[3, "fake_value"])
    # coverage line surfaced
    assert "match" in summary.lower()


def test_shell_no_source_loaded():
    store = SessionStore()
    out = run_point_enrichment(store, "empty-thread", matcher=FakeMatcher())
    assert "aucune table" in out.lower()


def test_shell_missing_lat_lon_uses_label():
    df = pd.DataFrame({"foo": [1, 2], "bar": [3, 4]})
    store = _store_with(df)
    out = run_point_enrichment(store, "thr-pe", matcher=FakeMatcher())
    assert "Fake Source" in out
    assert "latitude" in out.lower()


def test_shell_empty_coords_uses_label():
    df = pd.DataFrame({"latitude": [None, None], "longitude": [None, None]})
    store = _store_with(df)
    out = run_point_enrichment(store, "thr-pe", matcher=FakeMatcher())
    assert "Fake Source" in out
