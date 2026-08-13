"""Rendered evidence from the real offline DataFrame pressure harness."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_pressure_harness_generates_fifty_turn_metrics_and_graphs(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/dev/plot_dataframe_pressure_evolution.py",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )

    report_path = tmp_path / "dataframe_pressure_timeline.json"
    dataframe_graph = tmp_path / "dataframe_pressure_evolution.png"
    context_graph = tmp_path / "context_pressure_evolution.png"
    assert report_path.exists()
    assert dataframe_graph.stat().st_size > 10_000
    assert context_graph.stat().st_size > 10_000

    timeline = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(timeline) == 50
    assert max(item["derived_dataframes_visible"] for item in timeline) <= 20
    assert max(item["dataframe_detailed_count"] for item in timeline) <= 8
    assert max(item["checkpoint_messages_after"] for item in timeline) <= 40
    assert timeline[-1]["dataframes_stored_total"] == 84
    assert "50 tours" in completed.stdout
