#!/usr/bin/env python3
"""Run the pre-analysis test case against the OpenWebUI backend API.

Scripts the parcours documented in ``docs/preanalyse_test_case.md``: exploration
EcoTaxa -> enrichissement (les deux entrees) -> connaissance taxonomique, i.e.
everything BEFORE the numeric analyses.

Like ``run_ecotaxa_exploration_ui_tests.py`` it drives the same
OpenAI-compatible streaming endpoint Open WebUI uses, captures the streamed
markdown/tool progress and validates expected routes plus key answer content.

Difference: a case can carry several ``setup_prompts`` played on the SAME
``chat_id`` before (and including) the tested prompt. The whole parcours
transcript is concatenated and validated together, so a case can assert
``query_ecotaxa`` in one turn and ``enrich_ecotaxa_with_ecopart_remote`` in the
next.

Grounding rule (same as the rest of the suite): we assert ROUTING and
GUARDRAILS, never live EcoPart numbers (they depend on the campaign and would
make the test lie on the next run).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Server-side demo files used by the "load a file -> enrich" path (chemin B).
# load_file takes a path, so the agent can read these directly.
#
# WARNING: these two demo files are from DIFFERENT campaigns (EcoTaxa sample =
# ArcticNet 2013, EcoPart = Hawke Channel 2024) -> the join yields 0 match by
# construction. Chemin B here therefore validates ONLY the routing (bon tool
# selon la session) and the 0-match guardrail ("verifie meme campagne"), NOT a
# non-zero enrichment. For a positive match, swap in an EcoTaxa/EcoPart pair
# from the SAME campaign.
ECOTAXA_DEMO_FILE = "data/demo/ecotaxa_sample_50.tsv"
ECOPART_DEMO_FILE = "data/demo/ecopart_hawkechannel_30jan.tsv"

# Unique user id per process run. The agent injects long-term memories keyed by
# user_id into the system prompt; a FIXED user accumulates stale memories across
# runs (e.g. a now-dead example project) that then poison routing. A fresh user
# per run keeps the test hermetic. Override with PREANALYSE_USER_ID if you need
# to reproduce a specific user's memory state.
RUN_USER_ID = os.getenv("PREANALYSE_USER_ID") or f"preanalyse-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class CheckCase:
    case_id: str
    prompt: str
    expect: tuple[str, ...] = ()
    forbid: tuple[str, ...] = ()
    expect_regex: tuple[str, ...] = ()
    # Substrings that must appear in this relative order in the transcript.
    # Used to enforce "exploration BEFORE export BEFORE enrich".
    expect_order: tuple[str, ...] = ()
    # Turns played on the same chat_id before `prompt`. All transcripts
    # (setup turns + final prompt) are concatenated and validated together.
    setup_prompts: tuple[str, ...] = ()
    description: str = ""


CASES: tuple[CheckCase, ...] = (
    # --- Exploration EcoTaxa ---------------------------------------------
    CheckCase(
        "P1",
        "Quels projets EcoTaxa sont accessibles ?",
        expect=("list_ecotaxa_projects",),
        forbid=("query_ecotaxa", "run_pandas"),
        description="Decouverte des projets accessibles (read-only).",
    ),
    CheckCase(
        "P3",
        "Fais-moi un etat des lieux du projet 17498 : combien de samples, "
        "quel instrument, et les comptes valides / predits.",
        # NB: on ne demande PAS de ratio calcule -> pas de run_pandas legitime a
        # interdire. Valeurs V/P live (capturees le 2026-07-10) : volatiles car
        # 17498 est en cours d'annotation ; a rafraichir si le test derive.
        expect=(
            "summarize_ecotaxa_project",
            "17498",
            "UVP6",
            "357440",
            "1878169",
        ),
        forbid=("query_ecotaxa",),
        description="Profil d'un projet candidat (17498, encore accessible).",
    ),
    # --- Connaissance taxonomique : KB / WoRMS, PAS EcoTaxa --------------
    CheckCase(
        "P4",
        "Qu'est-ce que Calanus hyperboreus et ou vit cette espece ?",
        expect=("query_copepod_knowledge_base",),
        forbid=(
            "count_ecotaxa_taxa",
            "find_ecotaxa_observations",
            "query_ecotaxa",
        ),
        description="Definition/ecologie -> KB, jamais un projet EcoTaxa.",
    ),
    CheckCase(
        "P5",
        "Le nom \"Calanus finmarchicus\" est-il valide, et quelle est sa "
        "classification ?",
        expect=("lookup_marine_taxonomy",),
        forbid=("count_ecotaxa_taxa", "query_ecotaxa"),
        description="Validation d'un nom via WoRMS, pas d'exploration EcoTaxa.",
    ),
    # --- Pont taxonomie -> exploration : routage selon l'intention -------
    CheckCase(
        "P6",
        "Dans le projet 17498, combien de copepodes sont valides ?",
        expect=(
            "count_ecotaxa_taxa",
            "Copepoda<Multicrustacea",
            "25828",
            "1204",  # validated live 2026-07-10
            "23400",  # predicted live
            "24604",  # total live
        ),
        forbid=("query_copepod_knowledge_base", "query_ecotaxa"),
        description="'dans le projet X' -> EcoTaxa, pas la KB.",
    ),
    CheckCase(
        "P7",
        "Scanne les samples 17498000001, 17498000002 et 17498000003.",
        expect=(
            "summarize_ecotaxa_samples",
            "17498000001",
            "95509",  # predicted live 2026-07-10
            "17498000002",
            "12781",
            "17498000003",
            "7398",
        ),
        forbid=("query_ecotaxa_sample", "query_ecotaxa"),
        description="Scan des samples avant de preparer l'enrichissement.",
    ),
    # --- COEUR : Chemin A -- explorer EcoTaxa -> figer scope -> enrichir --
    CheckCase(
        "P8A",
        "Maintenant enrichis-les avec les profils EcoPart correspondants.",
        setup_prompts=(
            # Exploration D'ABORD : cadrer le projet via un tool d'exploration...
            "Fais-moi un resume du projet 17498.",
            # ...PUIS figer le scope avec l'export.
            "Exporte les copepodes du projet 17498 pour qu'on puisse les enrichir.",
        ),
        expect=(
            "summarize_ecotaxa_project",
            "query_ecotaxa",
            "enrich_ecotaxa_with_ecopart_remote",
        ),
        # L'ordre est la garantie : exploration -> export -> enrich.
        expect_order=(
            "summarize_ecotaxa_project",
            "query_ecotaxa",
            "enrich_ecotaxa_with_ecopart_remote",
        ),
        # Op lourde -> confirmation attendue avant execution reelle.
        expect_regex=(r"confirm|t[ée]l[ée]charg|lourde|valide[rz]?|go\b",),
        forbid=("join_ecotaxa_ecopart",),
        description="Chemin A : exploration AVANT export, puis enrich sans ID.",
    ),
    CheckCase(
        "P9",
        "Oui, vas-y.",
        setup_prompts=(
            "Fais-moi un resume du projet 17498.",
            "Exporte les copepodes du projet 17498 pour qu'on puisse les enrichir.",
            "Maintenant enrichis-les avec les profils EcoPart correspondants.",
        ),
        expect=("enrich_ecotaxa_with_ecopart_remote",),
        expect_order=(
            "summarize_ecotaxa_project",
            "query_ecotaxa",
            "enrich_ecotaxa_with_ecopart_remote",
        ),
        # Honnetete du taux de match : rapporte un match OU avertit d'aucun match.
        expect_regex=(r"match|correspond|aucun|bin",),
        description="Chemin A execute apres confirmation + honnetete du taux de match.",
    ),
    # --- COEUR : Chemin B -- charger un fichier -> enrichir --------------
    CheckCase(
        "P8Ba",
        "Enrichis le fichier EcoTaxa avec le fichier EcoPart charge.",
        setup_prompts=(
            f"Charge le fichier {ECOTAXA_DEMO_FILE}.",
            f"Charge aussi le fichier {ECOPART_DEMO_FILE}.",
        ),
        expect=("load_file", "join_ecotaxa_ecopart"),
        # Workflow 1 = jointure locale d'abord. Les fichiers demo etant de
        # campagnes differentes, le join renvoie 0 match -> l'agent PEUT ensuite
        # appliquer le fallback 0-match documente (prompt ligne ~216) vers
        # enrich_..._remote. On ne l'interdit donc pas ; on exige juste que la
        # jointure locale ait ete tentee ET que le garde-fou 0-match soit dit.
        expect_regex=(r"correspond|aucun|match|campagne",),
        description="Chemin B / workflow 1 : join local d'abord (fallback remote OK).",
    ),
    CheckCase(
        "P8Bb",
        "Enrichis ce fichier EcoTaxa avec les profils EcoPart correspondants.",
        setup_prompts=(f"Charge le fichier {ECOTAXA_DEMO_FILE}.",),
        expect=("load_file", "enrich_ecotaxa_with_ecopart_remote"),
        # EcoPart pas en session -> remote ; resolution par bbox/labels.
        expect_regex=(r"confirm|t[ée]l[ée]charg|lourde|valide[rz]?|go\b",),
        forbid=("join_ecotaxa_ecopart",),
        description="Chemin B / workflow 2 : fichier EcoTaxa seul -> enrich remote.",
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
            "X-OpenWebUI-User-Id": RUN_USER_ID,
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


def _run_case(base_url: str, case: CheckCase, *, timeout: int) -> str:
    """Play setup turns + final prompt on one chat_id, return full transcript."""
    chat_id = f"preanalyse-{case.case_id.lower()}-{uuid.uuid4().hex[:8]}"
    transcripts: list[str] = []
    for turn in (*case.setup_prompts, case.prompt):
        transcripts.append(_post_stream(base_url, turn, chat_id=chat_id, timeout=timeout))
    return "\n\n".join(transcripts)


def _selected_cases(case_ids: Iterable[str] | None) -> list[CheckCase]:
    if not case_ids:
        return list(CASES)
    wanted = {case_id.upper() for case_id in case_ids}
    known = {case.case_id.upper() for case in CASES}
    unknown = sorted(wanted - known)
    if unknown:
        raise SystemExit(f"Unknown case id(s): {', '.join(unknown)}")
    return [case for case in CASES if case.case_id.upper() in wanted]


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
    # Ordering: each item must first appear after the previous one.
    cursor = 0
    for token in case.expect_order:
        idx = transcript.find(token, cursor)
        if idx == -1:
            failures.append(f"out-of-order or missing (expected after previous): {token!r}")
            break
        cursor = idx + len(token)
    return failures


def _print_case_result(
    case: CheckCase, ok: bool, failures: list[str], transcript: str, *, verbose: bool
) -> None:
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
    parser.add_argument(
        "--case", action="append", dest="cases", help="Run one case id, e.g. P8A. Repeatable."
    )
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    selected = _selected_cases(args.cases)
    passed = 0
    failed = 0
    started = time.time()

    for case in selected:
        n_turns = len(case.setup_prompts) + 1
        print(f"[RUN] {case.case_id} ({n_turns} turn(s)) — {case.description or case.prompt}", flush=True)
        try:
            transcript = _run_case(args.base_url, case, timeout=args.timeout)
        except (HTTPError, URLError, TimeoutError) as exc:
            _print_case_result(case, False, [f"request failed: {exc}"], "", verbose=args.verbose)
            failed += 1
            if args.fail_fast:
                break
            continue

        failures = _validate(case, transcript)
        ok = not failures
        _print_case_result(case, ok, failures, transcript, verbose=args.verbose)
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
    raise SystemExit(main())
