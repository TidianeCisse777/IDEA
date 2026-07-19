#!/usr/bin/env python3
"""Load test the running copepod-agent with N concurrent simulated users.

Token-safe by default: the default mode hammers the health endpoint (``GET /``)
and measures how the server behaves under concurrency — zero provider tokens.
The real chat path is opt-in (``--chat``) and prints a cost warning, because it
calls the LLM once per request.

Examples
--------
    # 10 concurrent users, 5 rounds each, health only (no tokens):
    python scripts/load_test_agent.py --users 10 --rounds 5

    # Real chat under load (BURNS TOKENS — asks for confirmation):
    python scripts/load_test_agent.py --users 10 --rounds 1 --chat

    # Point at a remote deployment:
    python scripts/load_test_agent.py --base-url https://agent.example.org --users 10
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[k]


def _health_call(base_url: str, timeout: float) -> tuple[bool, float, str]:
    start = time.monotonic()
    try:
        r = requests.get(f"{base_url}/", timeout=timeout)
        return r.ok, time.monotonic() - start, "" if r.ok else f"HTTP {r.status_code}"
    except Exception as exc:  # noqa: BLE001
        return False, time.monotonic() - start, f"{type(exc).__name__}: {exc}"


def _chat_call(base_url: str, user_idx: int, message: str, timeout: float) -> tuple[bool, float, str]:
    chat_id = f"loadtest-{user_idx}-{uuid.uuid4().hex[:6]}"
    payload = {
        "model": "copepod-agent",
        "stream": False,
        "chat_id": chat_id,
        "messages": [{"role": "user", "content": message}],
    }
    start = time.monotonic()
    try:
        r = requests.post(
            f"{base_url}/v1/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer copepod-key"},
            timeout=timeout,
        )
        if not r.ok:
            return False, time.monotonic() - start, f"HTTP {r.status_code}"
        content = r.json()["choices"][0]["message"]["content"]
        ok = bool(content and content.strip())
        return ok, time.monotonic() - start, "" if ok else "empty response"
    except Exception as exc:  # noqa: BLE001
        return False, time.monotonic() - start, f"{type(exc).__name__}: {exc}"


def run(args: argparse.Namespace) -> int:
    mode = "chat" if args.chat else "health"
    total = args.users * args.rounds

    def _task(i: int) -> tuple[bool, float, str]:
        if args.chat:
            return _chat_call(args.base_url, i % args.users, args.message, args.timeout)
        return _health_call(args.base_url, args.timeout)

    print(
        f"[load] mode={mode} users={args.users} rounds={args.rounds} "
        f"total_requests={total} target={args.base_url}"
    )

    latencies: list[float] = []
    errors: list[str] = []
    ok_count = 0

    wall_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.users) as pool:
        futures = [pool.submit(_task, i) for i in range(total)]
        for fut in as_completed(futures):
            ok, latency, err = fut.result()
            latencies.append(latency)
            if ok:
                ok_count += 1
            else:
                errors.append(err)
    wall = time.monotonic() - wall_start

    print("\n===== RESULTATS =====")
    print(f"requetes        : {total}")
    print(f"OK              : {ok_count}")
    print(f"erreurs         : {len(errors)}")
    if latencies:
        print(f"latence p50     : {_percentile(latencies, 50) * 1000:.0f} ms")
        print(f"latence p95     : {_percentile(latencies, 95) * 1000:.0f} ms")
        print(f"latence max     : {max(latencies) * 1000:.0f} ms")
        print(f"latence moyenne : {statistics.mean(latencies) * 1000:.0f} ms")
    print(f"debit           : {total / wall:.1f} req/s ({wall:.1f}s au total)")
    if errors:
        shown = {}
        for e in errors:
            shown[e] = shown.get(e, 0) + 1
        print("\ntop erreurs :")
        for msg, count in sorted(shown.items(), key=lambda kv: -kv[1])[:5]:
            print(f"  {count:>4}x  {msg}")
    print("=====================")

    return 0 if not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--users", type=int, default=10, help="concurrents simultanes")
    parser.add_argument("--rounds", type=int, default=5, help="requetes par utilisateur")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--chat",
        action="store_true",
        help="teste le vrai endpoint chat (APPELLE LE LLM, consomme des tokens)",
    )
    parser.add_argument(
        "--message",
        default="Bonjour, reponds simplement OK.",
        help="message envoye en mode --chat",
    )
    parser.add_argument("--yes", action="store_true", help="ne pas demander confirmation pour --chat")
    args = parser.parse_args()

    if args.chat and not args.yes:
        total = args.users * args.rounds
        print(
            f"⚠️  --chat va envoyer {total} requetes au LLM (tokens consommes).\n"
            f"    Relance avec --yes pour confirmer, ou retire --chat pour le mode health (0 token)."
        )
        return 2

    return run(args)


if __name__ == "__main__":
    sys.exit(main())
