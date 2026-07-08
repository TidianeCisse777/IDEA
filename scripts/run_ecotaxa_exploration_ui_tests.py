#!/usr/bin/env python3
"""Run scripted EcoTaxa exploration checks against the OpenWebUI backend API.

This is an API-level UI test runner: it calls the same OpenAI-compatible
streaming endpoint that Open WebUI uses, captures the streamed markdown/tool
progress, and validates expected routes plus key answer content.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
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


CASES: tuple[CheckCase, ...] = (
    CheckCase(
        "E1",
        "Liste les samples EcoTaxa en Baie de Baffin en 2024.",
        expect=(
            "load_skill",
            "skill_name=`ecotaxa_navigation`",
            "get_zone_info",
            "zone_name=`Baie de Baffin`",
            "find_ecotaxa_samples_in_region",
            "date_range",
            "# 62 samples",
            "14853000003",
            "14853000002",
            "14853000001",
            "17498",
            "14859",
            "14853",
        ),
        forbid=(
            "polygon_wkt",
            "bbox -90.0/-180.0→90.0/180.0",
            "query_ecotaxa",
            "run_pandas",
        ),
        description="Samples Baie de Baffin 2024 depuis le cache/polygone.",
    ),
    CheckCase(
        "E2",
        "Liste les samples LOKI dans la Baie de Baffin en 2024.",
        expect=(
            "load_skill",
            "get_zone_info",
            "find_ecotaxa_samples_in_region",
            "instrument=`Loki`",
            "Aucun sample",
        ),
        forbid=("find_ecotaxa_projects", "polygon_wkt", "query_ecotaxa"),
        description="LOKI doit rester un filtre instrument.",
    ),
    CheckCase(
        "E4",
        "Fais un tableau de stats pour les projets 14853, 2331 et 4042.",
        expect=(
            "load_skill",
            "summarize_ecotaxa_projects",
            "project_ids=`[14853, 2331, 4042]`",
            "14853",
            "2024-10-06",
            "2024-10-11",
            "77218",
            "515419",
            "Projets absents du cache local",
            "2331",
            "4042",
        ),
        forbid=("query_ecotaxa", "run_pandas"),
        description="Résumé projets avec absents du cache.",
    ),
    CheckCase(
        "E5",
        "Parmi les projets 14853, 2331 et 4042, lesquels contiennent le plus d'images non annotées ?",
        expect=(
            "load_skill",
            "summarize_ecotaxa_projects",
            "14853",
            "515419",
            "2331",
            "4042",
        ),
        expect_regex=(r"non[_ -]?annot", r"P\s*\+\s*D\s*\+\s*U|P \\+ D \\+ U|515\s?419"),
        forbid=("query_ecotaxa",),
        description="Ranking opérationnel, pas tableau brut seulement.",
    ),
    CheckCase(
        "E6",
        "Combien de copépodes validés dans le projet 14853 ?",
        expect=(
            "load_skill",
            "count_ecotaxa_taxa",
            "project_ids=`[14853]`",
            "Copepoda<Multicrustacea",
            "25828",
            "2063",
            "15589",
            "17652",
        ),
        forbid=("query_copepod_knowledge_base", "query_ecotaxa"),
        description="Comptage taxon projet avec alias copépodes.",
    ),
    CheckCase(
        "E7",
        "Compare les comptes V/P/D/U de Copepoda dans les projets 14853, 17498 et 14859.",
        expect=(
            "load_skill",
            "count_ecotaxa_taxa",
            "14853",
            "17498",
            "14859",
            "122777",
            "92401",
            "17652",
        ),
        forbid=("query_copepod_knowledge_base", "query_ecotaxa"),
        description="Comparaison Copepoda multi-projets.",
    ),
    CheckCase(
        "E9",
        "Scan les samples 14853000001, 14853000002, 14853000003 avant export.",
        expect=(
            "load_skill",
            "summarize_ecotaxa_samples",
            "14853000001",
            "8428",
            "14853000002",
            "6169",
            "14853000003",
            "19341",
        ),
        forbid=("query_ecotaxa_sample", "query_ecotaxa"),
        description="Résumé sample batch sans export.",
    ),
    CheckCase(
        "E10",
        "Parmi ceux-là, lesquels contiennent le plus d'objets ?",
        setup_prompt="Scan les samples 14853000001, 14853000002, 14853000003 avant export.",
        expect=(
            "load_skill",
            "summarize_ecotaxa_samples",
            "14853000003",
            "19341",
            "14853000001",
            "8428",
            "14853000002",
            "6169",
        ),
        forbid=("bbox -90.0/-180.0→90.0/180.0", "find_ecotaxa_samples_in_region"),
        description="Follow-up clair sur IDs visibles, classement par total.",
    ),
    CheckCase(
        "E11",
        "Parmi les samples présents, lesquels contiennent le plus de copepods ?",
        expect=("présents",),
        expect_regex=(r"cache|tableau|projet|zone", r"pr[ée]cise|clarifi|veux-tu|veux tu|tu veux dire"),
        forbid=("bbox -90.0/-180.0→90.0/180.0", "find_ecotaxa_samples_in_region"),
        description="Ambiguïté samples présents : clarifier, ne pas deviner.",
    ),
    CheckCase(
        "E18",
        "Liste les samples EcoTaxa en Baie de Baffin en 2024.",
        expect=(
            "<summary>load_skill</summary>",
            "<summary>get_zone_info</summary>",
            "<summary>find_ecotaxa_samples_in_region</summary>",
            "Paramètres :",
        ),
        forbid=("<code>load_skill</code>", "<code>find_ecotaxa_samples_in_region</code>", "polygon_wkt"),
        description="UX tool calls : nom visible, paramètres au clic.",
    ),
    CheckCase(
        "E19",
        "Quel projet a le plus de samples parmi 14853, 2331 et 4042 ?",
        expect=(
            "load_skill",
            "summarize_ecotaxa_projects",
            "14853",
            "2",
            "2331",
            "4042",
            "absents du cache",
        ),
        forbid=("query_ecotaxa",),
        description="Réponse directe au projet gagnant disponible.",
    ),
    CheckCase(
        "E20",
        "Quelles zones / mers ont le moins d'échantillons EcoTaxa ? Classe-les croissant.",
        expect=(
            "load_skill",
            "rank_ecotaxa_samples_by_region",
            "sort_by=`sample_count`",
            "sort_order=`asc`",
            "MEOW: Lancaster Sound",
            "Détroit de Davis",
            "Baie de Baffin",
        ),
        forbid=("find_ecotaxa_samples_in_region", "query_ecotaxa", "run_pandas"),
        description="Classement global zones par faible couverture, sans zone inventée.",
    ),
    CheckCase(
        "E21",
        "Quelles zones ont été échantillonnées le plus anciennement ?",
        expect=(
            "load_skill",
            "rank_ecotaxa_samples_by_region",
            "sort_by=`date_min`",
            "sort_order=`asc`",
            "Détroit de Davis",
            "2015-04-19",
        ),
        forbid=("find_ecotaxa_samples_in_region", "query_ecotaxa", "run_pandas"),
        description="Classement global par ancienneté depuis le cache.",
    ),
    CheckCase(
        "E22",
        "Quelles mers ont été échantillonnées le plus récemment ?",
        expect=(
            "load_skill",
            "rank_ecotaxa_samples_by_region",
            "sort_by=`date_max`",
            "sort_order=`desc`",
            "Baie de Baffin",
            "2024-10-11",
        ),
        forbid=("find_ecotaxa_samples_in_region", "query_ecotaxa", "run_pandas"),
        description="Classement global par récence depuis le cache.",
    ),
    CheckCase(
        "E23",
        "Liste les samples EcoTaxa en Baie de Baffin avec leur nom de station.",
        expect=(
            "load_skill",
            "get_zone_info",
            "find_ecotaxa_samples_in_region",
            "| sample_id | projet | station |",
            "am_leg5_TCA_T3_09_02",
            "am_leg4_RA62_1",
        ),
        forbid=("query_ecotaxa", "run_pandas"),
        description="Les noms de station viennent du cache enrichi, sans export.",
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
            "X-OpenWebUI-User-Id": "ecotaxa-ui-test",
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
    parser.add_argument("--case", action="append", dest="cases", help="Run one case id, e.g. E1. Repeatable.")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    selected = _selected_cases(args.cases)
    passed = 0
    failed = 0
    started = time.time()

    for case in selected:
        print(f"[RUN] {case.case_id} — {case.description or case.prompt}", flush=True)
        chat_id = f"ecotaxa-ui-{case.case_id.lower()}-{uuid.uuid4().hex[:8]}"
        try:
            if case.setup_prompt:
                _post_stream(args.base_url, case.setup_prompt, chat_id=chat_id, timeout=args.timeout)
                if not case.same_chat_as_setup:
                    chat_id = f"ecotaxa-ui-{case.case_id.lower()}-{uuid.uuid4().hex[:8]}"
            transcript = _post_stream(args.base_url, case.prompt, chat_id=chat_id, timeout=args.timeout)
        except (HTTPError, URLError, TimeoutError) as exc:
            failures = [f"request failed: {exc}"]
            _print_case_result(case, False, failures, "", verbose=args.verbose)
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
