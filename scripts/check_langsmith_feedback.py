#!/usr/bin/env python3
"""Check whether a LangSmith feedback entry is visible for a given run."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the repo importable when running the script directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.feedback import list_feedback_for_run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", help="LangSmith run_id to inspect")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    feedbacks = list_feedback_for_run(args.run_id, limit=args.limit)
    print(f"run_id={args.run_id} feedback_count={len(feedbacks)}")
    for fb in feedbacks:
        fb_id = getattr(fb, "id", None) or getattr(fb, "feedback_id", None)
        score = getattr(fb, "score", None)
        comment = getattr(fb, "comment", None)
        print(f"- id={fb_id} score={score} comment={comment}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
