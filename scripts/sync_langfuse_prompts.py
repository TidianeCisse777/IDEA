#!/usr/bin/env python3
"""Synchronize repository prompt files to Langfuse as production versions."""

from __future__ import annotations

import os
from pathlib import Path

from langfuse import Langfuse


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = {
    "neolab-terminal-agent-system": ROOT / "langgraph/utils/system_prompt.md",
}


def main() -> int:
    label = os.getenv("IDEA_LANGFUSE_PROMPT_LABEL", "production")
    client = Langfuse()
    changed = 0
    for name, path in PROMPTS.items():
        content = path.read_text(encoding="utf-8")
        try:
            current = client.get_prompt(
                name,
                label=label,
                type="text",
                max_retries=0,
                fetch_timeout_seconds=5,
            )
            if getattr(current, "prompt", None) == content:
                print(f"unchanged {name} v{getattr(current, 'version', '?')}")
                continue
        except Exception:
            pass
        created = client.create_prompt(
            name=name,
            type="text",
            prompt=content,
            labels=[label],
            commit_message=f"Sync {path.relative_to(ROOT)} from repository",
        )
        changed += 1
        print(f"published {name} v{getattr(created, 'version', '?')}")
    client.flush()
    print(f"synchronized {len(PROMPTS)} prompts; new versions={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
