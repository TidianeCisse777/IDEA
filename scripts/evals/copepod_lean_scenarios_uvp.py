from __future__ import annotations

from pathlib import Path
from typing import Any


def build_uvp_understanding_scenarios(
    *,
    LeanScenario: Any,
    ECOTAXA_UVP5: Path,
    ECOPART: Path,
) -> list[Any]:
    return [
        LeanScenario(
            slug="uvp5_morphometric_column",
            fixtures=[ECOTAXA_UVP5],
            user_message_template=(
                "Voici un fichier EcoTaxa UVP5.\n"
                "Fichier : {paths}\n"
                "Que signifient les colonnes `fre_major` et `fre_esd` dans ce fichier ?"
            ),
            expect_inspect_per_file=True,
            expect_self_summary=False,
            expect_tools_called=["inspect_and_report"],
            expect_reply_mentions=["major", "axe", "ellipse", "morphométr", "taille", "µm", "ESD", "diamètre", "équivalent", "sphère"],
        ),
        LeanScenario(
            slug="ecopart_lpm_depth_profile",
            fixtures=[ECOPART],
            user_message_template=(
                "Voici un fichier EcoPart.\n"
                "Fichier : {paths}\n"
                "Que représentent les colonnes LPM et comment est structuré un profil de profondeur dans ce fichier ?"
            ),
            expect_inspect_per_file=True,
            expect_tools_called=["inspect_and_report"],
            expect_reply_mentions=["profondeur", "taille", "particule", "concentration", "µm", "mm", "profil", "volume", "LPM", "classe"],
            forbidden_terms_in_reply=["copépode", "taxonomie", "annotation"],
        ),
        LeanScenario(
            slug="uvp5_ecopart_join_key",
            fixtures=[ECOTAXA_UVP5, ECOPART],
            user_message_template=(
                "Voici deux fichiers : un export EcoTaxa UVP5 et un export EcoPart.\n"
                "Fichiers : {paths}\n"
                "Comment relier ces deux fichiers ? Quelle colonne sert de clé de jointure ?"
            ),
            expect_inspect_per_file=True,
            expect_tools_called=["inspect_and_report"],
            expect_reply_mentions=["obj_orig_id", "Profile", "profil", "jointure", "ips_007", "clé", "lier", "relier"],
        ),
    ]
