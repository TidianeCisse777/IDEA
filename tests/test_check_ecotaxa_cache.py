"""Preflight cache validation used by start.sh to gate agent startup."""

from __future__ import annotations

import pytest

from scripts.check_ecotaxa_cache import validate_cache_health


def _payload(**overrides):
    base = {
        "samples_indexed": 2441,
        "projects_indexed": 6,
        "schemas_indexed": 6,
        "last_sync_status": "ok",
        "cache_age_hours": 2.0,
    }
    base.update(overrides)
    return {"status": "ok", "cache": base}


def test_healthy_cache_passes_without_warnings():
    result = validate_cache_health(_payload())
    assert result.ok is True
    assert result.errors == []
    assert result.warnings == []


def test_missing_cache_payload_blocks():
    result = validate_cache_health({"status": "ok", "cache": None})
    assert result.ok is False
    assert any("cache" in e.lower() for e in result.errors)


def test_empty_samples_blocks():
    result = validate_cache_health(_payload(samples_indexed=0))
    assert result.ok is False
    assert any("sample" in e.lower() for e in result.errors)


def test_zero_projects_blocks():
    result = validate_cache_health(_payload(projects_indexed=0))
    assert result.ok is False
    assert any("proj" in e.lower() for e in result.errors)


def test_below_custom_minimum_blocks():
    result = validate_cache_health(_payload(samples_indexed=5), min_samples=100)
    assert result.ok is False


def test_failed_last_sync_warns_but_does_not_block():
    # Usable data from a previous sync must not be gated by a later failed run.
    result = validate_cache_health(_payload(last_sync_status="failed"))
    assert result.ok is True
    assert any("sync" in w.lower() for w in result.warnings)


def test_stale_cache_warns_but_does_not_block():
    result = validate_cache_health(_payload(cache_age_hours=1000.0), max_age_hours=168.0)
    assert result.ok is True
    assert any("stale" in w.lower() or "old" in w.lower() or "âg" in w.lower() or "age" in w.lower()
               for w in result.warnings)


def test_partial_sync_is_acceptable():
    # A partial sync (e.g. one 404 project among many) is a healthy outcome.
    result = validate_cache_health(_payload(last_sync_status="partial"))
    assert result.ok is True
    assert result.warnings == []


def test_none_age_does_not_crash():
    result = validate_cache_health(_payload(cache_age_hours=None))
    assert result.ok is True


def test_malformed_top_level_blocks():
    result = validate_cache_health({"unexpected": True})
    assert result.ok is False
