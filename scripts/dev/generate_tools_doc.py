#!/usr/bin/env python3
"""Generate or verify the policy inventory embedded in TOOLS.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.tool_catalog import OPTIONAL_SQL_TOOL_NAMES, TOOL_POLICIES  # noqa: E402
from tools.tool_docs import render_tool_inventory, replace_generated_inventory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--path", type=Path, default=ROOT / "TOOLS.md")
    args = parser.parse_args()

    path = args.path.resolve()
    current = path.read_text(encoding="utf-8")
    inventory = render_tool_inventory(TOOL_POLICIES, OPTIONAL_SQL_TOOL_NAMES)
    expected = replace_generated_inventory(current, inventory)
    if args.check:
        if current != expected:
            print(f"Inventaire des tools désynchronisé : {path}", file=sys.stderr)
            return 1
        print(f"Inventaire des tools synchronisé : {path}")
        return 0
    path.write_text(expected, encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
