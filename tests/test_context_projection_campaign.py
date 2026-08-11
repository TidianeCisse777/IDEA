"""The complete context projection campaign runs offline as one contract."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_context_projection_campaign_is_offline_and_green():
    completed = subprocess.run(
        [sys.executable, "scripts/dev/run_context_projection_campaign.py", "--json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    report = json.loads(completed.stdout)

    assert report["offline"] is True
    assert report["llm_calls"] == 0
    assert report["network_calls"] == 0
    assert report["summary"]["failed"] == 0
    assert report["summary"]["passed"] == report["summary"]["total"]
