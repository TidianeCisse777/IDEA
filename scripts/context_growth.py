#!/usr/bin/env python3
"""Show context growth per turn for one or several sessions.

Usage:
    python scripts/context_growth.py                        # all sessions in logs/sessions/
    python scripts/context_growth.py session-6qc7ngzqa      # specific session
    python scripts/context_growth.py session-abc session-def # multiple
"""

import json
import re
import sys
from pathlib import Path

LOGS_ROOT = Path(__file__).parent.parent / "logs" / "sessions"

_TURN_END_RE = re.compile(
    r"status=\S+\s+duration_ms=([\d.]+)\s+retries=\d+"
    r"(?:\s+ctx_payload≈(\d+)tok \((\d+)ch\))?"
    r"(?:\s*\|\s*prompt=(\d+)tok)?"
    r"(?:\s*\|\s*completion=(\d+)tok)?",
)

_TURN_HEADER_RE = re.compile(r"=== TURN (\d+) session=(\S+) agent=(\S+) ===")
_USER_RE = re.compile(r"--- USER ---\n(.*?)--- TOOL CALLS ---", re.DOTALL)
_CODE_RE = re.compile(r"\[CODE\]")


def _parse_turns_log(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"(?==== TURN \d+)", text)
    turns = []
    for block in blocks:
        hm = _TURN_HEADER_RE.search(block)
        if not hm:
            continue
        turn_idx = int(hm.group(1))
        user_m = _USER_RE.search(block)
        user_msg = user_m.group(1).strip()[:60] if user_m else ""
        end_m = _TURN_END_RE.search(block)
        ctx_tok = int(end_m.group(2)) if end_m and end_m.group(2) else None
        ctx_chars = int(end_m.group(3)) if end_m and end_m.group(3) else None
        prompt_tok = int(end_m.group(4)) if end_m and end_m.group(4) else None
        completion_tok = int(end_m.group(5)) if end_m and end_m.group(5) else None
        duration_ms = float(end_m.group(1)) if end_m else None
        had_code = bool(_CODE_RE.search(block))
        turns.append({
            "turn": turn_idx,
            "user": user_msg,
            "ctx_tok": ctx_tok,
            "ctx_chars": ctx_chars,
            "prompt_tok": prompt_tok,
            "completion_tok": completion_tok,
            "duration_ms": duration_ms,
            "had_code": had_code,
        })
    return sorted(turns, key=lambda t: t["turn"])


def _fmt(n: int | None, unit: str = "") -> str:
    if n is None:
        return "  —  "
    return f"{n:>6}{unit}"


def _bar(value: int | None, max_val: int, width: int = 20) -> str:
    if value is None or max_val == 0:
        return " " * width
    filled = round(value / max_val * width)
    return "█" * filled + "░" * (width - filled)


def show_session(session_id: str) -> None:
    turns_path = LOGS_ROOT / session_id / "turns.log"
    if not turns_path.exists():
        print(f"  [not found] {turns_path}")
        return

    turns = _parse_turns_log(turns_path)
    if not turns:
        print("  (no turns parsed)")
        return

    # Determine what columns we have
    has_ctx = any(t["ctx_tok"] is not None for t in turns)
    has_prompt = any(t["prompt_tok"] is not None for t in turns)
    max_ctx = max((t["ctx_tok"] or 0) for t in turns) or 1
    max_prompt = max((t["prompt_tok"] or 0) for t in turns) or 1

    print(f"\n{'─'*80}")
    print(f"  Session: {session_id}  ({len(turns)} turns)")

    if not has_ctx and not has_prompt:
        print("  ⚠  No context/token data logged yet — restart the container after this update.")
        # Still show turn/code structure from existing logs
        print(f"\n  {'T':>3}  {'CODE':5}  {'USER':<50}")
        print(f"  {'─'*3}  {'─'*5}  {'─'*50}")
        for t in turns:
            code_flag = "✓" if t["had_code"] else "✗"
            print(f"  {t['turn']:>3}  {'CODE '+code_flag:5}  {t['user']:<50}")
        return

    col = "ctx_tok" if has_ctx else "prompt_tok"
    max_v = max_ctx if has_ctx else max_prompt
    label = "ctx≈tok" if has_ctx else "prompt_tok"

    print(f"\n  {'T':>3}  {label:>8}  {'bar':<22}  {'CODE':5}  {'USER':<40}")
    print(f"  {'─'*3}  {'─'*8}  {'─'*22}  {'─'*5}  {'─'*40}")
    for t in turns:
        v = t[col]
        bar = _bar(v, max_v)
        code_flag = "✓" if t["had_code"] else "✗"
        vtxt = f"{v:>7}" if v is not None else "      —"
        print(f"  {t['turn']:>3}  {vtxt}  {bar}  {'CODE '+code_flag:5}  {t['user']:<40}")

    if has_ctx and has_prompt:
        print(f"\n  {'T':>3}  {'prompt_tok':>10}  {'completion_tok':>14}")
        print(f"  {'─'*3}  {'─'*10}  {'─'*14}")
        for t in turns:
            print(f"  {t['turn']:>3}  {_fmt(t['prompt_tok']):>10}  {_fmt(t['completion_tok']):>14}")


def main() -> None:
    args = sys.argv[1:]
    if args:
        sessions = args
    else:
        sessions = sorted(p.name for p in LOGS_ROOT.iterdir() if p.is_dir())

    if not sessions:
        print(f"No sessions found in {LOGS_ROOT}")
        return

    for s in sessions:
        show_session(s)

    print(f"\n{'─'*80}")
    print("Legend: ctx_tok = estimated input tokens (payload chars / 4)")
    print("        CODE ✓  = model emitted a code block  |  ✗ = prose only")


if __name__ == "__main__":
    main()
