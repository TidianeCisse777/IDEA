#!/usr/bin/env python3
"""Run scripted EcoTaxa↔EcoPart enrichment checks against the agent SSE endpoint.

Mirrors `scripts/run_ecotaxa_exploration_ui_tests.py` but targets the 3
enrichment workflows plus the warning surfaces exercised by
`tests/test_enrichment_workflows_integration.py`.

Validates routing (which tools are called with which args) and that key
warnings/labels reach the user. Does NOT assert on scientific values —
demo files are intentionally misaligned (see WF1 case).

Usage:
    LANGCHAIN_TRACING_V2=false python scripts/run_enrichment_workflows_ui_tests.py
    python scripts/run_enrichment_workflows_ui_tests.py --case WF1
    python scripts/run_enrichment_workflows_ui_tests.py --case WF2 --verbose
    python scripts/run_enrichment_workflows_ui_tests.py --fail-fast
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class CheckCase:
    case_id: str
    prompt: str
    expect: tuple[str, ...] = ()
    forbid: tuple[str, ...] = ()
    expect_regex: tuple[str, ...] = ()
    setup_prompt: str | None = None
    same_chat_as_setup: bool = True
    description: str = ""


_ECOTAXA_DEMO = "data/demo/ecotaxa_sample_50.tsv"
_ECOTAXA_ALIGNED = "UVP_metrics_for_MCA/data/ecotaxa_hawkechannel_30jan.tsv"
_ECOPART_ALIGNED = "UVP_metrics_for_MCA/data/ecopart_hawkechannel_30jan.tsv"
_ECOPART_DEMO = "data/demo/ecopart_hawkechannel_30jan.tsv"


CASES: tuple[CheckCase, ...] = (
    CheckCase(
        "WF1",
        prompt=(
            "J'ai deux fichiers locaux à croiser : "
            f"un EcoTaxa `{_ECOTAXA_DEMO}` et un EcoPart `{_ECOPART_DEMO}`. "
            "Charge-les tous les deux, puis fais le join EcoTaxa ↔ EcoPart."
        ),
        expect=(
            "🔧 load_file",
            "ecotaxa_sample_50.tsv",
            "ecopart_hawkechannel_30jan.tsv",
            "🔧 join_ecotaxa_ecopart",
        ),
        forbid=(
            "🔧 enrich_ecotaxa_with_ecopart_remote",
            "🔧 query_ecotaxa",
        ),
        description="WF1 — deux fichiers locaux → join_ecotaxa_ecopart (pas de fetch remote).",
    ),
    CheckCase(
        "WF1-ALIGNED",
        prompt=(
            f"J'ai un EcoTaxa Hawke Channel 2024 : `{_ECOTAXA_ALIGNED}` "
            f"et le fichier EcoPart correspondant `{_ECOPART_ALIGNED}`. "
            "Charge-les et fais le join EcoTaxa ↔ EcoPart. Donne-moi le nombre "
            "de lignes matchées."
        ),
        expect=(
            "🔧 load_file",
            "ecotaxa_hawkechannel_30jan.tsv",
            "ecopart_hawkechannel_30jan.tsv",
            "🔧 join_ecotaxa_ecopart",
        ),
        forbid=(
            "🔧 enrich_ecotaxa_with_ecopart_remote",
            "🔧 query_ecotaxa",
            "Aucune correspondance",
        ),
        expect_regex=(
            # Vrai jeu Hawke Channel 2024 : 137128 objets EcoTaxa, 30 profils partages
            # avec EcoPart. On attend un match massif — au moins 10000 lignes matchees.
            r"\b\d{4,}\s+.{0,40}match",
        ),
        description="WF1-ALIGNED — vrai Hawke Channel 2024 (137k rows EcoTaxa × 30 profils EcoPart).",
    ),
    CheckCase(
        "WF2",
        prompt=(
            f"Charge le fichier EcoTaxa local `{_ECOTAXA_ALIGNED}` (Hawke Channel 2024), "
            "puis enrichis-le avec les données EcoPart du même projet en récupérant "
            "EcoPart à distance."
        ),
        expect=(
            "🔧 load_file",
            "ecotaxa_hawkechannel_30jan.tsv",
            "🔧 enrich_ecotaxa_with_ecopart_remote",
        ),
        forbid=(
            "🔧 query_ecotaxa",
        ),
        description="WF2 — EcoTaxa local Hawke Channel + enrich_remote (EcoPart fetch distant).",
    ),
    CheckCase(
        "WF3",
        prompt=(
            "Récupère uniquement le sample 14853000001 du projet EcoTaxa 14853 "
            "(taxon Copepoda, statut validé), puis enrichis-le avec EcoPart en distant."
        ),
        expect=(
            "🔧 query_ecotaxa",
            "project_id=`14853`",
            "🔧 enrich_ecotaxa_with_ecopart_remote",
        ),
        forbid=(
            "🔧 load_file",
        ),
        description="WF3 — query_ecotaxa 14853 (1 sample Copepoda V) puis enrich_remote.",
    ),
    CheckCase(
        "WF-WARN-MISMATCH",
        prompt=(
            f"Charge `{_ECOTAXA_DEMO}` et `{_ECOPART_DEMO}` puis join. "
            "Ces deux fichiers ne partagent aucun profil. Signale-moi le problème "
            "clairement dans ta réponse."
        ),
        # Routing libre : l'agent peut passer par join_ecotaxa_ecopart OU
        # court-circuiter via run_pandas si le prompt lui dit deja qu'il n'y
        # aura pas de match. On valide seulement que le mismatch est surface.
        expect_regex=(
            r"(mismatch|aucun\s+profil|no\s+overlap|zero\s+match|aucune\s+correspondance|campagne|campaign|join\s+impossible)",
        ),
        description="Warning campaign mismatch — l'agent doit surface le zéro-match.",
    ),
    CheckCase(
        "WF-WARN-DEPTH",
        prompt=(
            "Après un join EcoTaxa↔EcoPart, si des objets EcoTaxa sont plus hauts que "
            "le premier bin EcoPart, quels champs de résultat me disent combien de "
            "lignes sont en couverture partielle ? Réponds sans lancer d'outil."
        ),
        expect_regex=(
            r"(partial|partielle|couverture|coverage|NaN|non\s+match)",
        ),
        description="Warning partial depth coverage — vérifie que l'agent connaît la sémantique.",
    ),
)


def _post_stream(base_url: str, prompt: str, *, chat_id: str, timeout: int) -> str:
    payload = {
        "model": "copepod-agent",
        "stream": True,
        "chat_id": chat_id,
        "messages": [{"role": "user", "content": prompt}],
    }
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-OpenWebUI-Chat-Id": chat_id,
            "X-OpenWebUI-User-Id": "enrichment-ui-test",
        },
        method="POST",
    )

    chunks: list[str] = []
    with urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = obj.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content")
            if content:
                chunks.append(content)
    return "".join(chunks)


def _selected_cases(case_ids: Iterable[str] | None) -> list[CheckCase]:
    if not case_ids:
        return list(CASES)
    wanted = {case_id.upper() for case_id in case_ids}
    known = {case.case_id for case in CASES}
    unknown = sorted(wanted - known)
    if unknown:
        raise SystemExit(f"Unknown case id(s): {', '.join(unknown)}")
    return [case for case in CASES if case.case_id in wanted]


def _validate(case: CheckCase, transcript: str) -> list[str]:
    failures: list[str] = []
    for expected in case.expect:
        if expected not in transcript:
            failures.append(f"missing substring: {expected!r}")
    for forbidden in case.forbid:
        if forbidden in transcript:
            failures.append(f"forbidden substring present: {forbidden!r}")
    for pattern in case.expect_regex:
        if not re.search(pattern, transcript, flags=re.IGNORECASE | re.MULTILINE):
            failures.append(f"missing regex: {pattern!r}")
    return failures


def _print_case_result(case: CheckCase, ok: bool, failures: list[str], transcript: str, *, verbose: bool) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {case.case_id} — {case.description or case.prompt}")
    for failure in failures:
        print(f"  - {failure}")
    if verbose or not ok:
        excerpt = transcript[-2500:] if len(transcript) > 2500 else transcript
        print("  transcript excerpt:")
        for line in excerpt.splitlines() or [""]:
            print(f"    {line}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--case", action="append", dest="cases",
                        help="Run one case id, e.g. WF1. Repeatable.")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Per-request timeout in seconds. Bump for slow remote fetches.")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    selected = _selected_cases(args.cases)
    passed = 0
    failed = 0
    started = time.time()

    for case in selected:
        print(f"[RUN] {case.case_id} — {case.description or case.prompt}", flush=True)
        chat_id = f"enrichment-ui-{case.case_id.lower()}-{uuid.uuid4().hex[:8]}"
        case_started = time.time()
        try:
            if case.setup_prompt:
                _post_stream(args.base_url, case.setup_prompt, chat_id=chat_id, timeout=args.timeout)
                if not case.same_chat_as_setup:
                    chat_id = f"enrichment-ui-{case.case_id.lower()}-{uuid.uuid4().hex[:8]}"
            transcript = _post_stream(args.base_url, case.prompt, chat_id=chat_id, timeout=args.timeout)
        except (HTTPError, URLError, TimeoutError) as exc:
            failures = [f"request failed: {exc}"]
            _print_case_result(case, False, failures, "", verbose=args.verbose)
            failed += 1
            if args.fail_fast:
                break
            continue

        case_elapsed = time.time() - case_started
        failures = _validate(case, transcript)
        ok = not failures
        _print_case_result(case, ok, failures, transcript, verbose=args.verbose)
        print(f"  ({case_elapsed:.1f}s)")
        if ok:
            passed += 1
        else:
            failed += 1
            if args.fail_fast:
                break

    elapsed = time.time() - started
    print(f"\n{passed} passed, {failed} failed in {elapsed:.1f}s")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
