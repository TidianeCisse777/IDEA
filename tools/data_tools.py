"""Tools LangChain pour l'analyse de données — slice 2."""
import io
import os
import uuid
from pathlib import Path
from typing import Any

_GRAPHS_DIR = Path("/tmp/copepod_graphs")
_GRAPHS_DIR.mkdir(exist_ok=True)

import pandas as pd
from langchain_core.tools import tool

from tools.file_loader import load_file as _load_file
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
        """
        try:
            df, meta = _load_file(path)
        except (FileNotFoundError, ValueError) as e:
            return f"Erreur : {e}"

        _store.set(thread_id, df, meta)
        col_names = [c["name"] for c in meta["columns"]]
        cols = ", ".join(col_names)

        hint = _uvp_skill_hint(col_names)

        return (
            f"Fichier chargé : {meta['path']}\n"
            f"{meta['n_rows']} lignes × {meta['n_cols']} colonnes\n"
            f"Colonnes : {cols}"
            + (f"\n\n{hint}" if hint else "")
        )

    @tool
    def run_pandas(code: str) -> str:
        """Exécute du code Python/pandas sur le fichier chargé.
        Le DataFrame est disponible comme variable `df`.
        Assigne le résultat à la variable `result`.
        Exemple : result = df[df['depth'] < 50]['temperature'].mean()
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
            exec(code, local_vars)  # noqa: S102

            if plt.get_fignums():
                buf = io.BytesIO()
                plt.savefig(buf, format="png", bbox_inches="tight")
                buf.seek(0)
                plt.close("all")
                graph_id = uuid.uuid4().hex[:12]
                (_GRAPHS_DIR / f"{graph_id}.png").write_bytes(buf.read())
                base_url = os.getenv("SERVE_BASE_URL", "http://localhost:8000")
                return f"![graph]({base_url}/graphs/{graph_id}.png)"

            return "Code executed but no figure was produced. Make sure your matplotlib code creates a figure."

        except Exception as e:
            cols_info = df.dtypes.to_string()
            return f"Error: {type(e).__name__}: {e}\n\nAvailable columns:\n{cols_info}"

    return [load_file, run_pandas, run_graph]
