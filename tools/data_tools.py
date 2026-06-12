"""Tools LangChain pour l'analyse de données — slice 2."""
import io
import uuid
from pathlib import Path
from typing import Any

_GRAPHS_DIR = Path("/tmp/copepod_graphs")
_GRAPHS_DIR.mkdir(exist_ok=True)

import pandas as pd
from langchain_core.tools import tool

from tools.file_loader import load_file as _load_file
from tools.public_url import graph_url
from tools.session_store import SessionStore, default_store


def _uvp_skill_hint(col_names: list[str]) -> str:
    """Retourne un hint load_skill si le fichier est un export UVP EcoTaxa ou EcoPart."""
    col_set = set(col_names)
    is_ecopart  = "Sampled volume [L]" in col_set and any("LPM (" in c for c in col_set)
    is_ecotaxa_uvp = (
        ("fre_major" in col_set or "object_major" in col_set)
        and "sample_id" in col_set
        and not is_ecopart
    )
    if is_ecopart:
        return (
            "→ Fichier EcoPart UVP détecté. "
            "Charge le skill `uvp_ecopart` pour les méthodes de calcul (m1-m3)."
        )
    if is_ecotaxa_uvp:
        return (
            "→ Fichier EcoTaxa UVP détecté. "
            "Charge le skill `uvp_ecotaxa` pour interpréter les colonnes et calculer m5/m6."
        )
    return ""


def make_tools(thread_id: str, store: SessionStore | None = None) -> list:
    """Crée les tools data pour un thread donné.

    Args:
        thread_id: Identifiant de session.
        store: SessionStore à utiliser (défaut : default_store global).
    """
    _store = store or default_store

    @tool
    def load_file(path: str) -> str:
        """Charge un fichier de données (CSV, TSV, Excel, JSON, Parquet) pour l'analyser.

        Utilise cet outil quand l'utilisateur mentionne un fichier ou fournit un chemin.
        Pour CSV/TSV, l'encodage est détecté automatiquement (utf-8, latin-1, cp1252…).

        Si le chargement échoue :
        - Vérifie que le chemin est correct (utilise le chemin exact fourni dans le contexte).
        - Essaie une variante du chemin si le fichier est dans /tmp/webui_uploads/.
        - Ne signale l'erreur à l'utilisateur qu'après avoir épuisé ces options.
        """
        try:
            df, meta = _load_file(path)
        except (FileNotFoundError, ValueError) as e:
            return f"Erreur : {e}"

        _store.set(thread_id, df, meta)
        col_names = [c["name"] for c in meta["columns"]]
        cols = ", ".join(col_names)

        hint = _uvp_skill_hint(col_names)

        enc_note = f" (encodage : {meta['encoding']})" if meta.get("encoding") else ""
        return (
            f"Fichier chargé : {meta['path']}{enc_note}\n"
            f"{meta['n_rows']} lignes × {meta['n_cols']} colonnes\n"
            f"Colonnes : {cols}"
            + (f"\n\n{hint}" if hint else "")
        )

    @tool
    def run_pandas(code: str) -> str:
        """Exécute du code Python/pandas sur le(s) DataFrame(s) chargés.

        Variables disponibles selon ce qui a été chargé dans la session :
        - `df`           : dernier DataFrame chargé (load_file ou dernier query_*)
        - `df_ecotaxa`   : données EcoTaxa (après query_ecotaxa)
        - `df_ctd`       : données CTD Amundsen (après query_amundsen_ctd)
        - `df_ecopart`   : données EcoPart (après query_ecopart)
        - `df_bio_oracle`: données Bio-ORACLE (après query_bio_oracle)

        Assigne le résultat à la variable `result`.
        Pour une jointure : result = df_ecotaxa.merge(df_ctd, on='station_id', how='left')
        """
        session = _store.get(thread_id)
        if not session or session.get("df") is None:
            return "Aucun fichier chargé. Utilise load_file d'abord."

        df = session["df"]

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.close("all")

            local_vars: dict[str, Any] = {"df": df, "pd": pd, "plt": plt}
            for source, var in [("ecotaxa", "df_ecotaxa"), ("ctd", "df_ctd"), ("ecopart", "df_ecopart"), ("bio_oracle", "df_bio_oracle")]:
                named = _store.get(f"{thread_id}:{source}")
                if named and named.get("df") is not None:
                    local_vars[var] = named["df"]
            exec(code, local_vars)  # noqa: S102

            if plt.get_fignums():
                plt.close("all")
                return (
                    "Error: run_pandas produced a matplotlib figure. "
                    "Use run_graph instead to execute visualization code."
                )

            result = local_vars.get("result")
            if result is None:
                return "Code exécuté (aucune variable `result` assignée)."
            if isinstance(result, pd.DataFrame):
                n_rows, n_cols = result.shape
                preview = result.head(20).to_markdown(index=False)
                suffix = " (aperçu 20 premières)" if n_rows > 20 else ""
                return f"{n_rows} lignes × {n_cols} colonnes{suffix}\n\n{preview}"
            return str(result)

        except Exception as e:
            cols_info = df.dtypes.to_string()
            return f"Erreur : {type(e).__name__}: {e}\n\nColonnes disponibles :\n{cols_info}"

    @tool
    def run_graph(code: str) -> str:
        """Execute matplotlib code on the loaded file and return the graph image.

        Use this tool ONLY for visualization — when you need to produce a chart or map.
        For data analysis (numbers, tables), use run_pandas instead.

        The DataFrame is available as `df`. Write complete matplotlib code using the
        graph_writer skill template. Do NOT call plt.show() or plt.savefig().

        The return value is the graph image — include it verbatim in your response.
        """
        session = _store.get(thread_id)
        if not session or session.get("df") is None:
            return "No file loaded. Use load_file first."

        df = session["df"]

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.close("all")

            local_vars: dict[str, Any] = {"df": df, "pd": pd, "plt": plt}
            for source, var in [("ecotaxa", "df_ecotaxa"), ("ctd", "df_ctd"), ("ecopart", "df_ecopart"), ("bio_oracle", "df_bio_oracle")]:
                named = _store.get(f"{thread_id}:{source}")
                if named and named.get("df") is not None:
                    local_vars[var] = named["df"]
            exec(code, local_vars)  # noqa: S102

            if plt.get_fignums():
                buf = io.BytesIO()
                plt.savefig(buf, format="png", bbox_inches="tight")
                buf.seek(0)
                plt.close("all")
                graph_id = uuid.uuid4().hex[:12]
                (_GRAPHS_DIR / f"{graph_id}.png").write_bytes(buf.read())
                image_markdown = f"![graph]({graph_url(f'{graph_id}.png')})"
                graph_explanation = local_vars.get("graph_explanation")
                if isinstance(graph_explanation, str) and graph_explanation.strip():
                    explanation = graph_explanation.strip()
                    if not explanation.lower().startswith("lecture rapide"):
                        explanation = f"Lecture rapide:\n{explanation}"
                    return f"{image_markdown}\n\n{explanation}"
                return image_markdown

            return "Code executed but no figure was produced. Make sure your matplotlib code creates a figure."

        except Exception as e:
            cols_info = df.dtypes.to_string()
            return f"Error: {type(e).__name__}: {e}\n\nAvailable columns:\n{cols_info}"

    return [load_file, run_pandas, run_graph]
