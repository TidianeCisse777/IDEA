from __future__ import annotations

from pathlib import Path
from typing import Any


def build_graph_happy_path_scenarios(
    *,
    LeanScenario: Any,
    ECOTAXA_UVP5: Path,
    ECOTAXA_UVP5_ENRICHED: Path,
    NEOLABS_TAXON_AMUNDSEN_CTD: Path,
) -> list[Any]:
    return [
        LeanScenario(
            slug="ecotaxa_simple_reasoning_code",
            fixtures=[ECOTAXA_UVP5],
            user_message_template=(
                "Voici un export EcoTaxa UVP5.\n"
                "Fichier : {paths}\n"
                "Fais un graphique de obj_depth_max en fonction de obj_depth_min — les colonnes sont confirmées.\n"
                "Donne un plan puis le code Python."
            ),
            expect_inspect_per_file=True,
            expect_self_summary=False,
            expect_tools_called=["inspect_and_report", "graph_readiness"],
            expect_reply_mentions=["**Plan**", "```python", "obj_depth_min", "obj_depth_max", "python"],
            expect_reply_all_of=["emit_deliverable(", "summary=", 'type="graph"'],
            forbidden_terms_in_reply=["je ne peux pas", "uploadez un fichier", "colonne non reconnue"],
        ),
        LeanScenario(
            slug="uvp_enriched_reasoning_code",
            fixtures=[ECOTAXA_UVP5_ENRICHED],
            user_message_template=(
                "Voici un fichier UVP enrichi.\n"
                "Fichier : {paths}\n"
                "Fais un graphique de ecopart_temperature_degC en fonction de object_depth — les colonnes sont confirmées.\n"
                "Donne un plan puis le code Python."
            ),
            expect_inspect_per_file=True,
            expect_self_summary=False,
            expect_tools_called=["inspect_and_report", "graph_readiness"],
            expect_reply_mentions=["**Plan**", "```python", "ecopart_temperature_degC", "object_depth", "python"],
            forbidden_terms_in_reply=["je ne peux pas", "uploadez un fichier", "colonne non reconnue"],
        ),
        LeanScenario(
            slug="neolabs_ctd_production_flow",
            fixtures=[NEOLABS_TAXON_AMUNDSEN_CTD],
            user_message_template=(
                "Voici une table NeoLabs enrichie avec la CTD Amundsen.\n"
                "Fichier : {paths}\n"
                "Fais un graphique de Total abundance (ind./m3 depth vol) en fonction de "
                "amundsen_temperature_degC_nearest — les colonnes sont confirmées.\n"
                "Donne un plan puis le code Python."
            ),
            expect_inspect_per_file=True,
            expect_self_summary=False,
            expect_tools_called=["inspect_and_report", "graph_readiness"],
            expect_reply_mentions=[
                "**Plan**",
                "```python",
                "Total abundance (ind./m3 depth vol)",
                "amundsen_temperature_degC_nearest",
                "python",
            ],
            forbidden_terms_in_reply=["je ne peux pas", "uploadez un fichier", "colonne non reconnue"],
        ),
    ]
