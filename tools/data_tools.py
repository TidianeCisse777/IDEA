"""Tools LangChain pour l'analyse de données — slice 2."""
import io
import base64
from typing import Any

import pandas as pd
from langchain_core.tools import tool

from tools.file_loader import load_file as _load_file

# Store mutable par session : thread_id → {df, meta}
_sessions: dict[str, dict[str, Any]] = {}


def make_tools(thread_id: str) -> list:
    """Crée les tools data pour un thread donné (thread_id capturé en closure)."""

    @tool
    def load_file(path: str) -> str:
        """Charge un fichier de données (CSV, TSV, Excel, JSON, Parquet) pour l'analyser.
        Utilise cet outil quand l'utilisateur mentionne un fichier ou fournit un chemin.
        """
        try:
            df, meta = _load_file(path)
        except (FileNotFoundError, ValueError) as e:
            return f"Erreur : {e}"

        _sessions[thread_id] = {"df": df, "meta": meta}
        cols = ", ".join(c["name"] for c in meta["columns"])
        return (
            f"Fichier chargé : {meta['path']}\n"
            f"{meta['n_rows']} lignes × {meta['n_cols']} colonnes\n"
            f"Colonnes : {cols}"
        )

    @tool
    def run_pandas(code: str) -> str:
        """Exécute du code Python/pandas sur le fichier chargé.
        Le DataFrame est disponible comme variable `df`.
        Assigne le résultat à la variable `result`.
        Exemple : result = df[df['depth'] < 50]['temperature'].mean()
        """
        session = _sessions.get(thread_id)
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

            # Figure matplotlib → base64 PNG
            if plt.get_fignums():
                buf = io.BytesIO()
                plt.savefig(buf, format="png", bbox_inches="tight")
                buf.seek(0)
                b64 = base64.b64encode(buf.read()).decode()
                plt.close("all")
                return f"![graphe](data:image/png;base64,{b64})"

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

    return [load_file, run_pandas]
