"""Tests for the FastMCP lifespan-managed nightly sync scheduler."""

import pytest


def test_nightly_scheduler_registers_3am_cron_job(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(tmp_path / "cache.sqlite"))

    from core.mcp.ecotaxa_server import build_nightly_scheduler

    triggered: list[str] = []
    scheduler = build_nightly_scheduler(
        cache_db=str(tmp_path / "cache.sqlite"),
        runner=lambda path: triggered.append(path),
        cron_hour=3,
    )

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    cron = jobs[0].trigger
    # Inspect the CronTrigger fields
    fields = {f.name: str(f) for f in cron.fields}
    assert fields["hour"] == "3"
    assert fields["minute"] == "0"


def test_nightly_scheduler_can_run_job_synchronously(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("ECOTAXA_CACHE_DB", str(tmp_path / "cache.sqlite"))

    from core.mcp.ecotaxa_server import build_nightly_scheduler

    triggered: list[str] = []
    scheduler = build_nightly_scheduler(
        cache_db="/tmp/test_cache.sqlite",
        runner=lambda path: triggered.append(path),
        cron_hour=3,
    )

    # Run the registered job directly without waiting for the trigger.
    job = scheduler.get_jobs()[0]
    job.func(*job.args, **job.kwargs)
    assert triggered == ["/tmp/test_cache.sqlite"]
