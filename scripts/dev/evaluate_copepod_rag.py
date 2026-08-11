#!/usr/bin/env python3
"""Offline retrieval benchmark for the copepod knowledge base.

No LLM or network call is performed. Rebuild the index first with:
``python core/copepod_rag/build_index.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.copepod_rag.query import query_copepod_rag  # noqa: E402


@dataclass(frozen=True)
class RetrievalCase:
    question: str
    expected_docs: frozenset[str]
    preferred_title_terms: tuple[str, ...] = ()
    required_terms: tuple[str, ...] = ()


def _normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


CASES = (
    RetrievalCase(
        "Que signifie obj_orig_id dans un export EcoTaxa ?",
        frozenset({"colonnes_sources.md", "colonnes_instruments.md"}),
    ),
    RetrievalCase(
        "Que signifie acq_pixel dans un export UVP5 ?",
        frozenset({"colonnes_instruments.md"}),
    ),
    RetrievalCase(
        "Comment calculer une abondance en individus par m3 depuis EcoTaxa et EcoPart ?",
        frozenset({"methodes_calcul.md", "colonnes_labo.md"}),
    ),
    RetrievalCase(
        "Pourquoi EcoTaxa seul ne suffit pas pour calculer une concentration ?",
        frozenset({"methodes_calcul.md"}),
    ),
    RetrievalCase(
        "Comment joindre EcoTaxa avec EcoPart et vérifier la qualité de la jointure ?",
        frozenset({"jointures_environnementales.md", "colonnes_sources.md"}),
    ),
    RetrievalCase(
        "Comment joindre un DataFrame pandas dans query_ecotaxa_cache avec dataframe_refs ?",
        frozenset({"ecotaxa_cache_sql.md"}),
    ),
    RetrievalCase(
        "Comment comparer des prélèvements filet NeoLabs aux profils UVP de même station dans une fenêtre de 10 heures ?",
        frozenset(
            {"comparaison_filet_uvp_calanus.md", "jointures_environnementales.md"}
        ),
    ),
    RetrievalCase(
        "Quelle source utiliser pour obtenir la température future en 2050 ?",
        frozenset({"sources_en_ligne.md"}),
        preferred_title_terms=("quelle source utiliser",),
        required_terms=("bio-oracle",),
    ),
    RetrievalCase(
        "Quelle source utiliser pour une CTD mesurée près d'une station ?",
        frozenset({"sources_en_ligne.md", "jointures_environnementales.md"}),
        preferred_title_terms=("quelle source utiliser",),
        required_terms=("amundsen",),
    ),
    RetrievalCase(
        "Comment filtrer des stations dans la baie de Baffin ?",
        frozenset(
            {
                "zones_geographiques.md",
                "geographie_nord_quebec.md",
                "ecoregions_meow.md",
            }
        ),
        preferred_title_terms=("zones géographiques",),
        required_terms=("get_zone_info", "baie de baffin"),
    ),
    RetrievalCase(
        "Quel graphique choisir pour un profil vertical de température ?",
        frozenset({"visualisation_graphes.md"}),
    ),
    RetrievalCase(
        "Comment orienter l'axe de profondeur sur un profil vertical ?",
        frozenset({"visualisation_graphes.md"}),
    ),
    RetrievalCase(
        "Quels sont les stades de développement des copépodes ?",
        frozenset({"copepodes_domaine.md"}),
    ),
    RetrievalCase(
        "Comment calculer m5 et m6 pour les profils UVP ?",
        frozenset({"methodes_calcul.md"}),
        preferred_title_terms=("calculer m5 et m6",),
        required_terms=("m5_cop_dens", "m6_largecop_dens"),
    ),
    RetrievalCase(
        "Comment est calculée l'abondance NeoLabs normalisée par DEPTH_CALC_NET_FILTERED_VOL ?",
        frozenset({"methodes_calcul.md"}),
    ),
    RetrievalCase(
        "Quel est le grain de samples_cache dans le cache EcoTaxa ?",
        frozenset({"ecotaxa_cache_sql.md"}),
        preferred_title_terms=("tables centrales et grain",),
        required_terms=("une ligne par échantillon",),
    ),
    RetrievalCase(
        "Où trouver le taxon validé dans un export EcoTaxa ?",
        frozenset({"colonnes_sources.md"}),
    ),
    RetrievalCase(
        "Quel est l'AphiaID de Calanus glacialis ?",
        frozenset({"taxonomie_worms.md"}),
        preferred_title_terms=("calanus",),
        required_terms=("104465",),
    ),
    RetrievalCase(
        "Quels sont les noms et unités des variables OGSL de salinité et température ?",
        frozenset({"sources_en_ligne.md"}),
    ),
    RetrievalCase(
        "Quelles variables Bio-ORACLE utiliser pour la chlorophylle et quels scénarios existent ?",
        frozenset({"sources_en_ligne.md"}),
    ),
)


def evaluate(top_k: int = 3) -> dict:
    rows = []
    top1_hits = 0
    topk_hits = 0
    evidence_hits = 0
    for case in CASES:
        results = query_copepod_rag(case.question, top_k=top_k)
        docs = [str(result["doc"]) for result in results]
        top1_title = _normalized(results[0]["title"]) if results else ""
        preferred_titles = tuple(
            _normalized(term) for term in case.preferred_title_terms
        )
        title_hit = not preferred_titles or any(
            term in top1_title for term in preferred_titles
        )
        top1 = bool(docs and docs[0] in case.expected_docs and title_hit)
        topk = bool(set(docs) & case.expected_docs)
        evidence = _normalized(
            "\n".join(f"{result['title']}\n{result['content']}" for result in results)
        )
        required_terms = tuple(_normalized(term) for term in case.required_terms)
        evidence_hit = all(term in evidence for term in required_terms)
        top1_hits += int(top1)
        topk_hits += int(topk)
        evidence_hits += int(evidence_hit)
        rows.append(
            {
                "question": case.question,
                "expected_docs": sorted(case.expected_docs),
                "preferred_title_terms": list(case.preferred_title_terms),
                "required_terms": list(case.required_terms),
                "top1_hit": top1,
                "topk_hit": topk,
                "evidence_hit": evidence_hit,
                "results": [
                    {
                        "rank": rank,
                        "doc": result["doc"],
                        "title": result["title"],
                        "score": result["score"],
                    }
                    for rank, result in enumerate(results, start=1)
                ],
            }
        )

    total = len(CASES)
    return {
        "offline": True,
        "llm_calls": 0,
        "total": total,
        "top1_hits": top1_hits,
        "topk_hits": topk_hits,
        "evidence_hits": evidence_hits,
        "top1_rate": top1_hits / total,
        "topk_rate": topk_hits / total,
        "evidence_rate": evidence_hits / total,
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--min-top1", type=float, default=0.90)
    parser.add_argument("--min-topk", type=float, default=1.00)
    parser.add_argument("--min-evidence", type=float, default=1.00)
    args = parser.parse_args()

    report = evaluate(top_k=args.top_k)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for case in report["cases"]:
            marker = (
                "TOP1"
                if case["top1_hit"] and case["evidence_hit"]
                else ("TOPK" if case["topk_hit"] and case["evidence_hit"] else "MISS")
            )
            first = case["results"][0] if case["results"] else {}
            print(f"[{marker}] {case['question']}")
            print(f"  {first.get('doc', '—')} — {first.get('title', '—')}")
        print(
            f"Top-1: {report['top1_hits']}/{report['total']} "
            f"({report['top1_rate']:.0%}) | "
            f"Top-{args.top_k}: {report['topk_hits']}/{report['total']} "
            f"({report['topk_rate']:.0%}) | "
            f"Evidence: {report['evidence_hits']}/{report['total']} "
            f"({report['evidence_rate']:.0%})"
        )

    return int(
        report["top1_rate"] < args.min_top1
        or report["topk_rate"] < args.min_topk
        or report["evidence_rate"] < args.min_evidence
    )


if __name__ == "__main__":
    raise SystemExit(main())
