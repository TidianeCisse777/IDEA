#!/usr/bin/env python3
"""
Langfuse live logger — poll l'API toutes les 5s et écrit les traces/observations
dans IDEA/logs/langfuse_live.log (+ stdout).

Format : groupé par round — LLM dit quoi → CODE généré → EXEC output → IMG → TOOL calls.

Usage:
    python scripts/langfuse_live_log.py
    python scripts/langfuse_live_log.py --tail       # stdout seulement
    python scripts/langfuse_live_log.py --limit 50   # nb de traces (défaut: 30)

Suivre en temps réel :
    tail -f logs/langfuse_live.log
"""

import argparse
import json
import os
import re
import time
import urllib.request
import urllib.parse
from base64 import b64encode
from datetime import datetime
from pathlib import Path

# ── Credentials ──────────────────────────────────────────────────────────────

LANGFUSE_HOST = os.getenv("LANGFUSE_HOST_LOCAL", "http://localhost:3001")
PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "pk-lf-5eef31e0-bc8e-43ea-a38d-c7b751f96fc1")
SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "sk-lf-c2769510-e147-4f0c-9125-ef2adbf6a565")

AUTH = b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode()
LOG_PATH = Path(__file__).parent.parent / "logs" / "langfuse_live.log"
DIVIDER = "─" * 72
POLL_INTERVAL = 5


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _get(path: str, params: dict | None = None) -> dict:
    url = f"{LANGFUSE_HOST}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {AUTH}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%H:%M:%S")
    except Exception:
        return iso[:8]


def _short(obj, max_len: int = 200) -> str:
    if obj is None:
        return "—"
    s = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    return s if len(s) <= max_len else s[:max_len] + " …"


def _extract_round(name: str) -> int | None:
    m = re.match(r"^round-(\d+)", name or "")
    return int(m.group(1)) if m else None


# ── Formatters ────────────────────────────────────────────────────────────────

def _fmt_runtime_trace(trace: dict, observations: list[dict]) -> str:
    """Format idea-chat-runtime traces grouped by round."""
    ts = _ts(trace.get("timestamp") or "")
    session = (trace.get("sessionId") or "—")
    tags = trace.get("tags") or []
    tag_str = f"  tags=[{', '.join(tags)}]" if tags else ""
    trace_id = trace.get("id", "?")

    parts = [
        DIVIDER,
        f"[{ts}] TRACE  idea-chat-runtime  session={session}{tag_str}",
        f"         id={trace_id}",
        "",
    ]

    # Group by round number
    rounds: dict[int, list[dict]] = {}
    for obs in sorted(observations, key=lambda o: o.get("startTime") or ""):
        r = _extract_round(obs.get("name") or "")
        if r is not None:
            rounds.setdefault(r, []).append(obs)

    for r_num in sorted(rounds.keys()):
        obs_list = rounds[r_num]
        parts.append(f"  ── ROUND {r_num} " + "─" * 54)

        llm_reply = None
        code_blocks: list[str] = []
        console_outputs: list[str] = []
        has_image = False
        tool_calls: list[tuple] = []

        llm_replies: list[str] = []

        for obs in obs_list:
            name = obs.get("name") or ""
            out = obs.get("output")

            # LLM reply — GENERATION ou SPAN avec output string sur round-N exact
            if name == f"round-{r_num}":
                text = None
                if obs.get("type", "").upper() == "GENERATION":
                    text = out.get("content") if isinstance(out, dict) else (out if isinstance(out, str) else None)
                elif isinstance(out, str) and out.strip():
                    text = out
                if text:
                    llm_replies.append(text)

            elif name.endswith("/runtime/generated_code"):
                if isinstance(out, dict) and out.get("content"):
                    code_blocks.append(out["content"])

            # console output réel → code_output ou console avec format=output
            elif name.endswith("/runtime/code_output") or name.endswith("/runtime/console"):
                if isinstance(out, dict) and out.get("format") == "output" and out.get("content"):
                    console_outputs.append(str(out["content"]).strip())

            elif name.endswith("/runtime/image"):
                if isinstance(out, dict) and isinstance(out.get("content"), str) \
                        and out["content"].startswith("iVBOR"):
                    has_image = True

            elif "/tool/" in name:
                tool_name = name.split("/tool/")[-1]
                tool_calls.append((tool_name, obs.get("input"), out, obs.get("level", "")))

        # Garder seulement la dernière reply LLM (la finale)
        llm_reply = llm_replies[-1] if llm_replies else None

        ts_r = _ts(obs_list[0].get("startTime") or "")

        if llm_reply:
            short_reply = llm_reply[:250] + (" …" if len(llm_reply) > 250 else "")
            parts.append(f"  [{ts_r}] LLM  → \"{short_reply}\"")

        for code in code_blocks:
            lines = code.strip().splitlines()
            parts.append(f"  [{ts_r}] CODE → {lines[0]}")
            for line in lines[1:min(10, len(lines))]:
                parts.append(f"               {line}")
            if len(lines) > 10:
                parts.append(f"               … ({len(lines)} lignes total)")

        for cout in console_outputs:
            cout_lines = cout.splitlines()
            is_err = _is_error_output(cout)
            prefix = "  [{ts_r}] ERR  →" if is_err else f"  [{ts_r}] EXEC →"
            prefix = f"  [{ts_r}] {'ERR *** ' if is_err else 'EXEC'} → "
            parts.append(f"{prefix}{cout_lines[0]}")
            for line in cout_lines[1:min(10 if is_err else 6, len(cout_lines))]:
                parts.append(f"               {line}")
            if len(cout_lines) > (10 if is_err else 6):
                parts.append(f"               … ({len(cout_lines)} lignes)")

        if has_image:
            parts.append(f"  [{ts_r}] IMG  → image générée (PNG)")

        for tool_name, inp, out, level in tool_calls:
            err = "  *** ERROR ***" if level == "ERROR" else ""
            parts.append(f"  [{ts_r}] TOOL → {tool_name}{err}")
            if inp:
                parts.append(f"               IN  {_short(inp)}")
            if out:
                out_str = _short(out)
                if _is_error_output(out_str):
                    parts.append(f"               OUT *** {out_str}")
                else:
                    parts.append(f"               OUT {out_str}")

        parts.append("")

    if not rounds:
        parts.append("  (aucun round tracé)")
        parts.append("")

    return "\n".join(parts)


def _is_error_output(text: str) -> bool:
    return any(k in text for k in ("Traceback", "Error:", "Exception:", "SyntaxError", "ModuleNotFoundError"))


def _fmt_llm_trace(trace: dict, observations: list[dict]) -> str:
    """Format litellm-completion traces — skip if empty."""
    generations = [o for o in observations if o.get("type", "").upper() == "GENERATION"]
    if not generations:
        return ""

    ts = _ts(trace.get("timestamp") or "")
    trace_id = trace.get("id", "?")
    parts = []

    for obs in generations:
        usage = obs.get("usage") or {}
        tokens = usage.get("totalTokens") or usage.get("total") or "?"
        model = obs.get("model") or "?"
        inp = obs.get("input") or {}
        out = obs.get("output") or {}
        level = obs.get("level") or ""

        reply = out.get("content") if isinstance(out, dict) else str(out) if out else ""
        if not reply:
            continue

        error_flag = "  *** ERROR ***" if level == "ERROR" else ""
        parts.append(DIVIDER)
        parts.append(f"[{ts}] LLM CALL  model={model}  tokens={tokens}{error_flag}  id={trace_id}")

        messages = inp.get("messages") or []
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content") or ""
                if isinstance(content, list):
                    content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                parts.append(f"  USER   → {_short(content, 300)}")
                break

        parts.append(f"  REPLY  → {_short(reply, 300)}")
        parts.append("")

    return "\n".join(parts) if parts else ""


def _fmt_trace(trace: dict, observations: list[dict]) -> str:
    name = trace.get("name") or ""
    if name == "idea-chat-runtime":
        return _fmt_runtime_trace(trace, observations)
    return _fmt_llm_trace(trace, observations)


# ── Polling loop ──────────────────────────────────────────────────────────────

def run(limit: int = 30, tail_only: bool = False) -> None:
    log_file = None if tail_only else open(LOG_PATH, "a", encoding="utf-8")

    # Traces déjà loggées définitivement
    logged_trace_ids: set[str] = set()
    # Traces en attente de stabilité : trace_id → {"obs_count": int, "stable_polls": int, "trace": dict, "observations": list}
    pending: dict = {}

    def emit(text: str) -> None:
        print(text)
        if log_file:
            log_file.write(text + "\n")
            log_file.flush()

    emit(f"\n{'═' * 72}")
    emit(f"  Langfuse live log — démarré le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    emit(f"  Host : {LANGFUSE_HOST}  |  log : {LOG_PATH if not tail_only else 'stdout seulement'}")
    emit(f"{'═' * 72}\n")

    try:
        while True:
            try:
                data = _get("/api/public/traces", {"limit": limit, "orderBy": "timestamp.desc"})
                traces = data.get("data") or []
            except Exception as exc:
                emit(f"[{datetime.now().strftime('%H:%M:%S')}] ERREUR API : {exc}")
                time.sleep(POLL_INTERVAL)
                continue

            for trace in reversed(traces):
                trace_id = trace.get("id")
                if not trace_id or trace_id in logged_trace_ids:
                    continue

                try:
                    obs_data = _get("/api/public/observations", {"traceId": trace_id, "limit": 100})
                    observations = obs_data.get("data") or []
                except Exception:
                    observations = []

                is_runtime = (trace.get("name") or "") == "idea-chat-runtime"

                if is_runtime:
                    # Stratégie "stable" : logger seulement quand les obs ne bougent plus
                    prev = pending.get(trace_id, {})
                    prev_count = prev.get("obs_count", -1)
                    curr_count = len(observations)

                    if curr_count == prev_count:
                        stable_polls = prev.get("stable_polls", 0) + 1
                    else:
                        stable_polls = 0

                    pending[trace_id] = {
                        "obs_count": curr_count,
                        "stable_polls": stable_polls,
                        "trace": trace,
                        "observations": observations,
                    }

                    # Logger quand stable depuis 2 polls consécutifs ET au moins 1 obs
                    if stable_polls >= 2 and curr_count > 0:
                        formatted = _fmt_trace(trace, observations)
                        if formatted.strip():
                            emit(formatted)
                        logged_trace_ids.add(trace_id)
                        del pending[trace_id]
                else:
                    # litellm-completion et autres : logger immédiatement
                    formatted = _fmt_trace(trace, observations)
                    if formatted.strip():
                        emit(formatted)
                    logged_trace_ids.add(trace_id)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        emit(f"\n[{datetime.now().strftime('%H:%M:%S')}] Arrêt du logger.")
        # Vider les traces pending au moment de l'arrêt
        for p in pending.values():
            formatted = _fmt_trace(p["trace"], p["observations"])
            if formatted.strip():
                emit(formatted)
    finally:
        if log_file:
            log_file.close()


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Langfuse live logger")
    parser.add_argument("--tail", action="store_true", help="stdout seulement, pas de fichier")
    parser.add_argument("--limit", type=int, default=30, help="nb de traces à surveiller (défaut: 30)")
    args = parser.parse_args()

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    run(limit=args.limit, tail_only=args.tail)
