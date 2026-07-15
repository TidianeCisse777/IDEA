#!/usr/bin/env python3
"""Rejeu E2E — cartes de samples depuis un fichier TSV (scénario superviseur).

Reproduit, sur notre repo, la conversation du professeur (transcript brut :
``docs/Test_Portable/``) qui a révélé le gros défaut de comportement : l'agent
déclenche EcoTaxa pour rien, ne voit / n'utilise pas le fichier chargé, et
hardcode des coordonnées. Voir ``docs/e2e/cartes-samples-labrador-2026/``.

Le runner pilote le vrai ``agent.py`` (via checkpointer, un tour à la fois) et
**assert sur les appels d'outils**, pas sur la prose — c'est le signal
déterministe dont un diagnostic comportemental a besoin :

- **file_used**   : au moins un tool a lu le df chargé (run_pandas / run_graph /
  filter_dataframe_by_zone) sur ce tour.
- **ecotaxa_drift**: un tool EcoTaxa/EcoPart a été appelé alors que la demande
  porte sur le fichier (defect D-CL3).
- **map_kind_bad**: le code run_graph contient ``kind:"map"`` / ``kind:"scatter"``
  (defect D-CL1).
- **hardcoded**   : le code run_graph fabrique un DataFrame de coordonnées en dur
  (defect D-CL2).

Usage :
    export OPENAI_API_KEY=...        # + OPENAI_BASE_URL=... si OpenRouter
    export LLM_MODEL=...             # défaut gpt-5.4-mini
    python scripts/run_cartes_labrador_e2e.py [--user-id run-YYYYMMDD-hhmm]

Sans clé LLM, le script s'arrête proprement en expliquant ce qu'il attend.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
DEMO_TSV = "data/demo/neolabs_taxonomy_2014_2020.tsv"
SCENARIO_DIR = _ROOT / "docs" / "e2e" / "cartes-samples-labrador-2026"

FILE_TOOLS = {"load_file", "run_pandas", "run_graph", "filter_dataframe_by_zone", "get_zone_info"}
EXTERNAL_TOOLS_RE = re.compile(r"^(find_ecotaxa|summarize_ecotaxa|list_ecotaxa|preview_ecotaxa|"
                               r"query_ecotaxa|count_ecotaxa|export_ecotaxa|inspect_ecotaxa|"
                               r".*ecopart|.*amundsen|.*bio_oracle|.*ogsl)", re.IGNORECASE)


@dataclass
class Turn:
    name: str
    prompt: str
    # what the turn is *supposed* to do, to grade behaviour
    expect_file_use: bool = True
    forbid_external: bool = True


# Turn 0 stands in for the Open WebUI upload: the professor's file is placed in
# session by an explicit load. Turns 1..N are his messages, condensed to the
# ones that exercise the defect.
SCENARIO: tuple[Turn, ...] = (
    Turn("upload", f"Charge le fichier {DEMO_TSV}.", expect_file_use=True, forbid_external=True),
    Turn("baffin_positions",
         "Je veux une carte avec les positions de tous les échantillons situés dans la "
         "Baie de Baffin. Utilise une légende qui change la taille du point selon le "
         "nombre d'échantillons prélevés à la même position."),
    Turn("labrador_color_taxa",
         "Je veux une carte des positions des échantillons (samples) situés dans la mer "
         "du Labrador, avec une légende de couleur indiquant le nombre de taxons "
         "identifiés pour chaque échantillon."),
    Turn("tsv_only_directive",
         "Utilise seulement le fichier .tsv que je t'ai fourni. N'utilise en aucun cas "
         "les skills ou méthodes pour EcoTaxa. As-tu compris ?",
         expect_file_use=False),
    Turn("labrador_positions_tsv",
         "Parfait. Je veux une carte avec les positions des échantillons situés dans la "
         "mer du Labrador."),
    Turn("file_name",
         "Quel est le nom du fichier que je t'ai donné ?",
         expect_file_use=False, forbid_external=True),
    Turn("add_coast", "Ajoute la côte à cette carte."),
)


@dataclass
class TurnResult:
    name: str
    prompt: str
    answer: str
    tool_calls: list[tuple[str, str]] = field(default_factory=list)
    defects: list[str] = field(default_factory=list)


def _grade(turn: Turn, calls: list[tuple[str, str]]) -> list[str]:
    names = [n for n, _ in calls]
    codes = " \n".join(a for n, a in calls if n == "run_graph")
    defects: list[str] = []
    if turn.forbid_external and any(EXTERNAL_TOOLS_RE.match(n) for n in names):
        hit = [n for n in names if EXTERNAL_TOOLS_RE.match(n)]
        defects.append(f"D-CL3 ecotaxa_drift: {hit}")
    if turn.expect_file_use and not (set(names) & (FILE_TOOLS - {"get_zone_info"})):
        defects.append("D-CL3 file_not_used: aucun tool n'a lu le df chargé")
    if re.search(r'["\']kind["\']\s*:\s*["\'](map|scatter)["\']', codes):
        defects.append("D-CL1 map_kind_bad: kind:'map'/'scatter' émis")
    if re.search(r"pd\.DataFrame\(\s*[\[{].{0,400}?(lat|lon|latitude|longitude)", codes, re.DOTALL):
        defects.append("D-CL2 hardcoded: DataFrame de coordonnées en dur")
    return defects


def _run() -> int:
    # Load the project's .env (OPENAI_API_KEY, LLM_MODEL, base URL) before the
    # key check — same mechanism agent.py uses.
    try:
        from dotenv import load_dotenv
        load_dotenv(_ROOT / ".env")
    except Exception:
        pass
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY absente — impossible de piloter le LLM.\n"
              "  export OPENAI_API_KEY=...   (+ OPENAI_BASE_URL=... si OpenRouter)\n"
              "  export LLM_MODEL=...        (défaut gpt-5.4-mini)\n"
              "puis relance ce script.", file=sys.stderr)
        return 2

    sys.path.insert(0, str(_ROOT))
    from agent import make_agent, repair_invalid_tool_history  # noqa: E402

    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", default=f"run-{datetime.now():%Y%m%d-%H%M%S}",
                        help="user_id unique (évite l'empoisonnement mémoire long-terme)")
    parser.add_argument("--thread-id", default=f"e2e-cartes-labrador-{uuid.uuid4().hex[:8]}")
    args = parser.parse_args()

    print(f"thread={args.thread_id}  user={args.user_id}  model={os.getenv('LLM_MODEL', 'gpt-5.4-mini')}",
          file=sys.stderr)
    agent = make_agent(args.thread_id, user_id=args.user_id)
    config = {"configurable": {"thread_id": args.thread_id}}

    results: list[TurnResult] = []
    for i, turn in enumerate(SCENARIO):
        repair_invalid_tool_history(agent, config)
        print(f"\n=== Tour {i} — {turn.name} ===", file=sys.stderr)
        # stream_mode="values" returns the complete message history in every
        # chunk. Start after the existing history so a turn is graded only on
        # its own tool calls (otherwise old calls are replayed on every turn).
        state = agent.get_state(config)
        seen = len(state.values.get("messages", [])) if state.values else 0
        last, calls = None, []
        t0 = time.monotonic()
        for chunk in agent.stream({"messages": [{"role": "user", "content": turn.prompt}]},
                                  config=config, stream_mode="values"):
            msgs = chunk.get("messages", [])
            for m in msgs[seen:]:
                for c in (getattr(m, "tool_calls", None) or []):
                    name = c.get("name") if isinstance(c, dict) else getattr(c, "name", "?")
                    a = c.get("args") if isinstance(c, dict) else getattr(c, "args", {})
                    code = a.get("code", "") if isinstance(a, dict) else ""
                    calls.append((name, code or str(a)))
                    print(f"  → {name}", file=sys.stderr)
            if len(msgs) > seen:
                seen, last = len(msgs), msgs[-1]
        answer = getattr(last, "content", "") if last is not None else ""
        defects = _grade(turn, calls)
        results.append(TurnResult(turn.name, turn.prompt, answer, calls, defects))
        flag = "  ".join(defects) if defects else "clean"
        print(f"  [{time.monotonic()-t0:5.1f}s] défauts: {flag}", file=sys.stderr)

    _write_conversation(results, args.thread_id)
    n_def = sum(len(r.defects) for r in results)
    print(f"\nScénario terminé — {n_def} défaut(s) détecté(s). "
          f"Voir {SCENARIO_DIR/'conversation.md'}", file=sys.stderr)
    return 1 if n_def else 0


def _write_conversation(results: list[TurnResult], thread_id: str) -> None:
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    out = [f"# Conversation E2E — cartes de samples (`{thread_id}`)", "",
           f"Rejeu automatique du scénario superviseur, {datetime.now():%Y-%m-%d %H:%M}.", ""]
    for i, r in enumerate(results):
        out += [f"## Tour {i} — {r.name}", "", f"**User :** {r.prompt}", ""]
        if r.tool_calls:
            out.append("**Outils appelés :** " + ", ".join(n for n, _ in r.tool_calls))
            out.append("")
            out.append("<details><summary>Arguments des outils</summary>")
            out.append("")
            for name, args in r.tool_calls:
                out += [f"`{name}`", "", "```python", args, "```", ""]
            out += ["</details>", ""]
        out += ["**Réponse :**", "", r.answer or "_(vide)_", ""]
        out.append("**Défauts :** " + ("; ".join(r.defects) if r.defects else "aucun"))
        out.append("")
    (SCENARIO_DIR / "conversation.md").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(_run())
