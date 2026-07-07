"""Tools LangChain pour l'analyse de données — slice 2."""
import io
import uuid
from pathlib import Path
from typing import Any

_GRAPHS_DIR = Path("/tmp/copepod_graphs")
_GRAPHS_DIR.mkdir(exist_ok=True)

import pandas as pd
from langchain_core.tools import tool


def _patch_cartopy_gridliner_polygon() -> None:
    """Workaround : cartopy 0.25 + shapely 2.1 crashent dans `_draw_gridliner`
    quand le path frontière de la carte n'a pas un premier/dernier point
    identique (`GEOSException: Points of LinearRing do not form a closed
    linestring`). Visible sur de nombreuses bbox courantes — Hudson, Ungava…

    On remplace `sgeom.Polygon` dans le namespace de `cartopy.mpl.gridliner`
    par un proxy qui ferme le LinearRing si nécessaire.
    """
    try:
        import cartopy.mpl.gridliner as _gridliner  # type: ignore
    except Exception:
        return
    if getattr(_gridliner, "_idea_polygon_patched", False):
        return

    import numpy as np
    _orig_sgeom = _gridliner.sgeom
    _orig_polygon = _orig_sgeom.Polygon

    def _safe_polygon(shell=None, holes=None):
        try:
            arr = np.asarray(shell)
            if arr.ndim == 2 and arr.shape[0] >= 2 and not np.allclose(arr[0], arr[-1]):
                shell = np.vstack([arr, arr[0:1]])
        except Exception:
            pass
        return _orig_polygon(shell, holes)

    class _SGeomShim:
        def __getattr__(self, name):
            if name == "Polygon":
                return _safe_polygon
            return getattr(_orig_sgeom, name)

    _gridliner.sgeom = _SGeomShim()
    _gridliner._idea_polygon_patched = True

from tools.file_loader import load_file as _load_file
from tools.dataset_registry import (
    SOURCE_ALIASES,
    dataset_variable_name,
    source_variable,
    store_dataset,
)
from tools.public_url import graph_url
from tools.session_store import SessionStore, default_store

# --- Cycle de vie du blocage qualité graphique ----------------------------
# Quand run_graph bloque une figure pour lisibilité, il pose ce flag ; run_pandas
# refuse alors de produire un tableau de repli et renvoie vers run_graph. Le
# blocage ne vaut QUE pour la tentative de graphe en cours : il est effacé au
# succès d'un graphe (run_graph) et au début de chaque nouveau tour utilisateur
# (pre_model_hook), sinon il coince une question chiffrée légitime au tour suivant.
_GRAPH_QUALITY_BLOCKED_KEY = "graph_quality_blocked"


def graph_recovery_pending(meta: dict[str, Any]) -> bool:
    """True si un graphe a été bloqué pour lisibilité et que graph_writer est chargé."""
    return bool(meta.get(_GRAPH_QUALITY_BLOCKED_KEY)) and "graph_writer" in (
        meta.get("loaded_skills") or []
    )


def _mark_graph_quality_blocked(store: SessionStore, thread_id: str) -> None:
    store.update_meta(thread_id, {_GRAPH_QUALITY_BLOCKED_KEY: True})


def _clear_graph_quality_block(store: SessionStore, thread_id: str) -> None:
    store.update_meta(thread_id, {_GRAPH_QUALITY_BLOCKED_KEY: False})


def reset_graph_block_on_new_turn(store: SessionStore, thread_id: str, messages: list) -> None:
    """Efface le blocage graphique au début d'un nouveau tour utilisateur.

    Nouveau tour = le dernier message est un message humain. En milieu de boucle
    ReAct (dernier message = résultat d'outil), on ne touche à rien pour préserver
    la protection anti-repli-tableau de la tentative de graphe en cours.
    """
    from langchain_core.messages import HumanMessage  # noqa: PLC0415

    if not (messages and isinstance(messages[-1], HumanMessage)):
        return
    session = store.get(thread_id)
    if session and (session.get("meta") or {}).get(_GRAPH_QUALITY_BLOCKED_KEY):
        _clear_graph_quality_block(store, thread_id)


def _graph_quality_issue(plt: Any) -> str | None:
    """Return a blocking message when a produced figure is likely unreadable."""
    for fig_num in plt.get_fignums():
        fig = plt.figure(fig_num)
        width, height = fig.get_size_inches()
        if width > 16 or height > 14:
            return (
                "Graph quality blocked: figure size is too large/readability is poor. "
                "Use a compact figsize (max 16 x 14 inches), aggregate groups, or limit labels. "
                "Do not answer with a table; revise the matplotlib code and call run_graph again."
            )
        for ax in fig.axes:
            legend = ax.get_legend()
            if legend is None:
                labels = []
            else:
                labels = [t.get_text() for t in legend.get_texts() if t.get_text()]
                if len(labels) > 15:
                    return (
                        f"Graph quality blocked: {len(labels)} legend entries is too many. "
                        "Omit the legend, aggregate groups, or show only the top 12 groups. "
                        "Do not answer with a table; revise the matplotlib code and call run_graph again."
                    )
            for axis_name, tick_labels in [
                ("x", ax.get_xticklabels()),
                ("y", ax.get_yticklabels()),
            ]:
                visible = [label for label in tick_labels if label.get_visible() and label.get_text()]
                if len(visible) > 50:
                    return (
                        f"Graph quality blocked: {len(visible)} visible {axis_name}-axis tick labels is too many. "
                        "Limit to the top 40 groups, aggregate categories, or show sparse ticks only. "
                        "Do not answer with a table; revise the matplotlib code and call run_graph again."
                    )
                long_labels = [label.get_text() for label in visible if len(label.get_text()) > 45]
                if len(long_labels) > 8:
                    return (
                        f"Graph quality blocked: {len(long_labels)} {axis_name}-axis tick labels are too long. "
                        "Shorten labels to the terminal taxon/station name, wrap text, or truncate to 35 characters. "
                        "Do not answer with a table; revise the matplotlib code and call run_graph again."
                    )
    return None


def _uvp_skill_hint(col_names: list[str]) -> str:
    """Retourne un hint load_skill si le fichier est un export UVP EcoTaxa ou EcoPart.

    Détecte deux familles de fichiers via des signaux **spécifiques** :

    - **EcoPart raw** : colonne ``"Sampled volume [L]"`` + au moins une colonne
      ``"LPM ("`` (nom EcoPart avec espace + crochets).
    - **EcoTaxa UVP raw / taxa_morpho_db** : ``fre_major`` ou ``object_major``
      + ``sample_id`` (colonnes morphométriques en pixels, exclusives à UVP).

    Le routing par **intent** (« calcule l'abondance / la densité copépode ») est
    géré dans le system prompt, pas ici. Détecter ``{sample_id, depth_bin,
    sampled_volume, category}`` au load_file serait trop large — un export
    filet (ZooScan minuscule, etc.) match ces colonnes aussi.
    """
    col_set = set(col_names)
    is_ecopart = "Sampled volume [L]" in col_set and any("LPM (" in c for c in col_set)
    is_ecotaxa_uvp_raw = (
        ("fre_major" in col_set or "object_major" in col_set)
        and "sample_id" in col_set
        and not is_ecopart
    )
    if is_ecopart:
        return (
            "→ Fichier EcoPart UVP détecté. "
            "Charge le skill `uvp_ecopart` pour les méthodes de calcul (m1-m3)."
        )
    if is_ecotaxa_uvp_raw:
        return (
            "→ Fichier EcoTaxa UVP détecté. "
            "Charge le skill `uvp_ecotaxa` pour interpréter les colonnes et calculer m5/m6."
        )
    return ""


def _source_alias_for_loaded_file(path: str, col_names: list[str]) -> str | None:
    """Return a stable latest alias for known uploaded/derived source files."""
    lower_path = str(path).lower()
    col_set = set(col_names)
    if "ogsl" in lower_path or (
        {"cruiseID", "stationID"} & col_set
        and {"TE90", "PSAL", "OXYM", "longitude", "latitude"} & col_set
    ):
        return "ogsl"
    is_ecopart_uvp = "Sampled volume [L]" in col_set and any("LPM (" in c for c in col_set)
    if is_ecopart_uvp:
        return "ecopart"
    is_ecotaxa_uvp = (
        ("fre_major" in col_set or "object_major" in col_set)
        and "sample_id" in col_set
    )
    if is_ecotaxa_uvp:
        return "ecotaxa"
    is_ecotaxa_export = (
        "object_id" in col_set
        and "sample_id" in col_set
        and (
            "object_annotation_category" in col_set
            or "object_annotation_hierarchy" in col_set
            or "object_annotation_status" in col_set
            or "object_annotation_person_name" in col_set
        )
    )
    if is_ecotaxa_export:
        return "ecotaxa"
    return None


def _dataframe_vars(
    store: SessionStore,
    thread_id: str,
    df: pd.DataFrame,
) -> dict[str, Any]:
    """Build the DataFrame namespace shared by pandas and graph tools."""
    local_vars: dict[str, Any] = {"df": df, "pd": pd}
    for alias in SOURCE_ALIASES:
        named = store.get(f"{thread_id}:{alias}")
        if named and named.get("df") is not None:
            local_vars[source_variable(alias)] = named["df"]

    for key in store.keys(f"{thread_id}:dataset:"):
        named = store.get(key)
        variable_name = (named or {}).get("meta", {}).get("variable_name")
        if variable_name and named.get("df") is not None:
            local_vars[variable_name] = named["df"]

    for key in store.keys(f"{thread_id}:ecopart:"):
        project_id = key.rsplit(":", 1)[-1]
        named = store.get(key)
        if project_id.isdigit() and named and named.get("df") is not None:
            local_vars.setdefault(f"df_ecopart_{project_id}", named["df"])
    return local_vars


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

        variable_name = dataset_variable_name("file", Path(path).stem)
        col_names = [c["name"] for c in meta["columns"]]
        source_alias = _source_alias_for_loaded_file(meta["path"], col_names)
        store_dataset(
            _store,
            thread_id,
            df,
            variable_name=variable_name,
            meta={**meta, "source": f"file:{meta['path']}"},
            latest_alias=source_alias,
        )
        cols = ", ".join(col_names)

        hint = _uvp_skill_hint(col_names)
        alias_note = f"\nAlias de session : `{source_alias}`" if source_alias else ""
        route_note = ""
        if source_alias == "ecotaxa":
            route_note = (
                "\nRoute EcoPart : `enrich_ecotaxa_with_ecopart_remote` "
                "(ne pas relancer `query_ecotaxa`)."
            )
        elif source_alias == "ecopart":
            route_note = (
                "\nRoute de jointure : `join_ecotaxa_ecopart` si EcoTaxa est déjà chargé."
            )

        enc_note = f" (encodage : {meta['encoding']})" if meta.get("encoding") else ""
        return (
            f"Fichier chargé : {meta['path']}{enc_note}\n"
            f"{meta['n_rows']} lignes × {meta['n_cols']} colonnes\n"
            f"Variable persistante : `{variable_name}`\n"
            f"Colonnes : {cols}"
            f"{alias_note}"
            f"{route_note}"
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
        - `df_ecotaxa_ecopart`: dernière jointure EcoTaxa + EcoPart
        - `df_ecopart_105`: projet EcoPart 105 (même règle pour chaque ID chargé)
        - `df_ctd_enriched`: dernière table enrichie avec Amundsen CTD
        - `df_bio_oracle`: données Bio-ORACLE (après query_bio_oracle)
        - `df_ogsl`      : dernier fichier OGSL chargé ou dérivé
        - `df_ogsl_enriched`: dernière table enrichie avec OGSL
        - `df_sql`       : dernière copie SQL matérialisée

        Assigne le résultat à la variable `result`.
        Pour une jointure : result = df_ecotaxa.merge(df_ctd, on='station_id', how='left')

        IMPORTANT: each call to run_pandas is isolated — variables computed in a
        previous call (e.g. `station_stats`, `delta_df`) are NOT available in the
        next call. Always recompute or include all required logic in a single call.
        """
        session = _store.get(thread_id)
        if not session or session.get("df") is None:
            return "Aucun fichier chargé. Utilise load_file d'abord."
        meta = session.get("meta") or {}
        if graph_recovery_pending(meta):
            return (
                "Graph quality recovery: the previous graph was blocked for readability. "
                "Do not answer with a table; revise the matplotlib code and call run_graph again."
            )

        df = session["df"]

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.close("all")

            local_vars = _dataframe_vars(_store, thread_id, df)
            local_vars["plt"] = plt
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

        DataFrames are available as `df`, named source aliases such as
        `df_ecopart`, `df_ctd`, `df_bio_oracle`, `df_ogsl`, `df_sql`,
        joined source aliases such as `df_ecotaxa_ecopart`, and
        project-specific variables such as `df_ecopart_105`.
        Write complete matplotlib code using the graph_writer skill template.
        Do NOT call plt.show() or plt.savefig().

        The return value is the graph image — include it verbatim in your response.
        Standalone figures (e.g. cartopy zone maps) work without any loaded file.
        """
        session = _store.get(thread_id)
        df = session.get("df") if session else None
        loaded_skills = ((session or {}).get("meta") or {}).get("loaded_skills") or []
        if loaded_skills and "graph_writer" not in loaded_skills:
            return (
                'Graph workflow blocked: call load_skill("graph_writer") before run_graph. '
                "Loaded analysis/planning skills are not executable graph templates; graph_writer provides the required template."
            )

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.close("all")
            _patch_cartopy_gridliner_polygon()

            if df is not None:
                local_vars = _dataframe_vars(_store, thread_id, df)
            else:
                local_vars = {"pd": pd}
            local_vars["plt"] = plt
            exec(code, local_vars)  # noqa: S102

            if plt.get_fignums():
                quality_issue = _graph_quality_issue(plt)
                if quality_issue:
                    plt.close("all")
                    _mark_graph_quality_blocked(_store, thread_id)
                    return quality_issue
                buf = io.BytesIO()
                plt.savefig(buf, format="png", bbox_inches="tight")
                buf.seek(0)
                plt.close("all")
                graph_id = uuid.uuid4().hex[:12]
                (_GRAPHS_DIR / f"{graph_id}.png").write_bytes(buf.read())
                _clear_graph_quality_block(_store, thread_id)
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
            cols_info = df.dtypes.to_string() if df is not None else "(no file loaded)"
            return f"Error: {type(e).__name__}: {e}\n\nAvailable columns:\n{cols_info}"

    return [load_file, run_pandas, run_graph]
