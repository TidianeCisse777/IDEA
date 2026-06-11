#!/usr/bin/env python3
"""Sync Open WebUI feedback exports into LangSmith."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openwebui.feedback_pipeline import fetch_openwebui_feedback_export, sync_openwebui_feedback_export


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openwebui-base-url", default=os.getenv("OPENWEBUI_BASE_URL", "http://localhost:3000"))
    parser.add_argument("--backend-base-url", default=os.getenv("COPEPOD_BACKEND_URL", "http://localhost:8000"))
    parser.add_argument("--auth-token", default=os.getenv("OPENWEBUI_API_TOKEN") or os.getenv("OPENWEBUI_TOKEN"))
    parser.add_argument(
        "--state-path",
        default=os.getenv("OPENWEBUI_FEEDBACK_SYNC_STATE", ".cache/openwebui_feedback_synced.json"),
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    export_rows = fetch_openwebui_feedback_export(
        args.openwebui_base_url,
        auth_token=args.auth_token,
        timeout=args.timeout,
    )
    summary = sync_openwebui_feedback_export(
        export_rows,
        args.backend_base_url,
        state_path=Path(args.state_path),
        timeout=args.timeout,
    )

    print(
        f"processed={summary['processed']} forwarded={summary['forwarded']} "
        f"skipped={summary['skipped']} seen_total={summary['seen_total']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
