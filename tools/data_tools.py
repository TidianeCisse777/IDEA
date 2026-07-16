"""Tools LangChain pour l'analyse de données — slice 2."""
import contextlib
import io
import json
import re
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from langchain_core.tools import tool

from core.cartography import configure_offline_cartopy
from core.graph_contracts import normalize_graph_contract, validate_graph_contract
from core.runtime_paths import graphs_dir
from tools.tool_result import blocked, empty, error, success
from tools.code_sandbox import apply_restricted_builtins


_GRAPHS_DIR = graphs_dir()


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

    def _finite_closed_ring(coordinates):
        arr = np.asarray(coordinates)
        if arr.ndim != 2 or arr.shape[0] < 3:
            return None
        finite = arr[np.isfinite(arr).all(axis=1)]
        if finite.shape[0] < 3:
            return None
        if not np.array_equal(finite[0], finite[-1]):
            finite = np.vstack([finite, finite[0:1]])
        return finite

    def _safe_polygon(shell=None, holes=None):
        try:
            shell = _finite_closed_ring(shell)
            if shell is None:
                return _orig_polygon()
            if holes is not None:
                holes = [
                    ring for hole in holes
                    if (ring := _finite_closed_ring(hole)) is not None
                ]
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


def _graph_savefig_kwargs(plt) -> dict:
    """Avoid Matplotlib 3.11 tight-bbox failures on Cartopy GeoAxes."""
    has_geoaxes = any(
        axis.__class__.__module__.startswith("cartopy.")
        for figure_number in plt.get_fignums()
        for axis in plt.figure(figure_number).axes
    )
    return {"format": "png"} if has_geoaxes else {
        "format": "png",
        "bbox_inches": "tight",
    }


@contextlib.contextmanager
def _cartopy_safe_tight_layout(plt):
    """Ignore model-generated tight_layout calls only when GeoAxes exist."""
    original = plt.tight_layout

    def safe_tight_layout(*args, **kwargs):
        has_geoaxes = any(
            axis.__class__.__module__.startswith("cartopy.")
            for figure_number in plt.get_fignums()
            for axis in plt.figure(figure_number).axes
        )
        if has_geoaxes:
            return None
        return original(*args, **kwargs)

    plt.tight_layout = safe_tight_layout
    try:
        yield
    finally:
        plt.tight_layout = original

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
    # NeoLabs taxonomy net file : signal exclusif (abondance ind./m³ depth vol +
    # taxon-level rows + classe taxonomique). Sans ce hint, l'agent tombait sur un
    # run_pandas libre et faisait une moyenne tous-taxons fausse.
    is_neolabs = (
        "Total abundance (ind./m3 depth vol)" in col_set
        and "TAXON_ID" in col_set
        and ("CLASS" in col_set or "ZOOPLANKTON_CATEGORY" in col_set)
    )
    if is_ecopart:
        return (
            "→ Fichier EcoPart UVP détecté. "
            "Charge le skill `uvp_ecopart` pour les méthodes de calcul (m1-m3)."
        )
    if is_neolabs:
        return (
            "→ Fichier NeoLabs taxonomy détecté. Charge le skill "
            "`neolabs_abundance_analysis`. Pour une densité de copépodes, utilise le "
            "contrat déterministe `neolabs_copepod_density` de `core.neolabs_abundance` "
            "(filtre CLASS==Copepoda, somme par sample, moyenne par station) — ne fais "
            "PAS une moyenne tous-taxons sur les lignes brutes."
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


_CANONICAL_COLUMNS = frozenset(
    {
        "sample_id",
        "depth_bin",
        "copepod_count",
        "sampled_volume_L",
        "abundance_ind_L",
        "abundance_ind_m3",
        "canonical_method_version",
    }
)


def _is_canonical_sample_depth(value: Any) -> bool:
    """True if `value` is a canonical sample-depth DataFrame (v1)."""
    return (
        isinstance(value, pd.DataFrame)
        and _CANONICAL_COLUMNS.issubset(value.columns)
        and len(value) > 0
        and value["canonical_method_version"].eq("copepod-sample-depth-v1").all()
    )


def _column_location_hint(error: Exception, local_vars: dict[str, Any]) -> str:
    """When a column is missing from the active df, name the df_* variables that
    do carry it — so the agent retargets instead of concluding it is absent."""
    if not isinstance(error, KeyError):
        return ""
    missing = str(error.args[0]) if error.args else ""
    if not missing:
        return ""
    holders = sorted(
        name
        for name, value in local_vars.items()
        if name.startswith("df_")
        and isinstance(value, pd.DataFrame)
        and missing in value.columns
    )
    if not holders:
        return ""
    return (
        f"\nLa colonne `{missing}` est absente de la table active `df` mais "
        f"présente dans : {', '.join(holders)}. Cible la variable explicite."
    )


_JOIN_CODE_PATTERN = re.compile(
    r"\.merge\s*\(|\bpd\.merge\s*\(|\bpd\.concat\s*\(|\.join\s*\(|\bmerge_asof\s*\(",
    re.IGNORECASE,
)


def _is_join_code(code: str) -> bool:
    """True when the executed code builds a joined/merged/concatenated table."""
    return bool(_JOIN_CODE_PATTERN.search(code or ""))


def _is_neolabs_columns(columns) -> bool:
    """True si les colonnes trahissent une table NeoLabs taxonomy."""
    cols = set(columns)
    return (
        "Total abundance (ind./m3 depth vol)" in cols
        and "TAXON_ID" in cols
        and ("CLASS" in cols or "ZOOPLANKTON_CATEGORY" in cols)
    )


def _neolabs_copepod_guard(code: str, local_vars: dict[str, Any]) -> str | None:
    """Bloque une densité de copépodes NeoLabs calculée à la main.

    Force le passage par le contrat déterministe `neolabs_copepod_density` : sinon
    l'agent somme les samples ou brasse les taxons et produit une densité fausse.
    Ne se déclenche que si (a) un DataFrame NeoLabs est chargé, (b) le code filtre
    les copépodes ET agrège l'abondance par groupby, (c) sans appeler le contrat.
    """
    if "neolabs_copepod_density" in code:
        return None
    has_neolabs = any(
        isinstance(value, pd.DataFrame) and _is_neolabs_columns(value.columns)
        for value in local_vars.values()
    )
    if not has_neolabs:
        return None
    lowered = code.lower()
    filters_copepods = "copepoda" in lowered
    aggregates_abundance = "total abundance" in lowered and "groupby" in lowered
    if filters_copepods and aggregates_abundance:
        return (
            "run_pandas bloqué : densité de copépodes NeoLabs calculée à la main. "
            "Utilise le contrat déterministe (filtre CLASS==Copepoda, somme par "
            "SAMPLE_ID, puis moyenne par station) — ne somme PAS les samples et ne "
            "compte PAS les lignes comme des stations :\n"
            "from core.neolabs_abundance import neolabs_copepod_density\n"
            "result = neolabs_copepod_density(df_file_...)"
        )
    return None


def _persist_canonical_sample_depth(
    store: SessionStore,
    thread_id: str,
    local_vars: dict[str, Any],
    result: Any,
) -> str:
    """Persist the widest canonical sample-depth table built in this call.

    Scans `result` and every intermediate DataFrame in `local_vars`, so a
    canonical table carrying extra columns (e.g. environmental variables) is kept
    for later turns even when `result` is a correlation or another object.
    Returns a reuse note, or an empty string when no canonical table was built.
    """
    candidates = [result, *local_vars.values()]
    canonical = [df for df in candidates if _is_canonical_sample_depth(df)]
    if not canonical:
        return ""
    # Widest table wins: it carries the most columns (env variables included).
    widest = max(canonical, key=lambda df: df.shape[1])
    n_zero_abundance = int(widest["copepod_count"].eq(0).sum())
    store_dataset(
        store,
        thread_id,
        widest,
        variable_name="df_canonical_sample_depth",
        meta={
            "source": "analysis:canonical-sample-depth",
            "method_version": "copepod-sample-depth-v1",
            "n_rows": int(len(widest)),
            "n_zero_abundance": n_zero_abundance,
        },
    )
    return (
        "\nVariable persistante : `df_canonical_sample_depth` — réutiliser "
        "cette table sans reconstruire les bins. "
        f"n_rows={len(widest)} ; n_zero_abundance={n_zero_abundance}."
    )


def _reuse_loaded_file(
    store: SessionStore,
    thread_id: str,
    variable_name: str,
    cached: dict,
    requested_path: str,
):
    """Return the already-loaded file as the active dataset, without re-reading.

    Used when `load_file` is called for a path whose DataFrame is already in the
    session: reuse avoids duplicate I/O and survives an upload path that has
    since expired.
    """
    meta = dict(cached.get("meta") or {})
    df = cached["df"]
    col_names = list(df.columns)
    resolved_path = meta.get("path", requested_path)
    source_alias = _source_alias_for_loaded_file(str(resolved_path), col_names)
    store_dataset(
        store,
        thread_id,
        df,
        variable_name=variable_name,
        meta=meta,
        latest_alias=source_alias,
        is_loaded_file=True,
    )
    from tools.source_scope import activate_file_source  # noqa: PLC0415

    activate_file_source(store, thread_id, origin_user_text=str(resolved_path))
    n_rows = meta.get("n_rows", len(df))
    n_cols = meta.get("n_cols", len(col_names))
    alias_note = f"\nAlias de session : `{source_alias}`" if source_alias else ""
    return success(
        "Fichier déjà chargé en session — réutilisé sans relecture.\n"
        f"{n_rows} lignes × {n_cols} colonnes\n"
        f"Variable persistante : `{variable_name}`\n"
        f"Colonnes : {', '.join(map(str, col_names))}"
        f"{alias_note}",
        data_ref=variable_name,
        provenance={"source": "file", "path": str(resolved_path)},
        persisted=True,
        method="file loader (session cache)",
    )


def make_tools(thread_id: str, store: SessionStore | None = None) -> list:
    """Crée les tools data pour un thread donné.

    Args:
        thread_id: Identifiant de session.
        store: SessionStore à utiliser (défaut : default_store global).
    """
    _store = store or default_store

    @tool(response_format="content_and_artifact")
    def load_file(path: str) -> str:
        """Charge un fichier de données (CSV, TSV, Excel, JSON, Parquet) pour l'analyser.

        Utilise cet outil quand l'utilisateur mentionne un fichier ou fournit un chemin.
        Pour CSV/TSV, l'encodage est détecté automatiquement (utf-8, latin-1, cp1252…).

        Si le chargement échoue :
        - Vérifie que le chemin est correct (utilise le chemin exact fourni dans le contexte).
        - Essaie une variante du chemin si le fichier est dans /tmp/webui_uploads/.
        - Ne signale l'erreur à l'utilisateur qu'après avoir épuisé ces options.
        """
        variable_name = dataset_variable_name("file", Path(path).stem)

        # Idempotent: a file already loaded in this session is reused instead of
        # being re-read. Avoids wasted I/O across turns and, crucially, avoids
        # failing when an upload path has since expired while the DataFrame is
        # still in session.
        cached = _store.get(f"{thread_id}:dataset:{variable_name}")
        if cached is not None and cached.get("df") is not None:
            return _reuse_loaded_file(
                _store, thread_id, variable_name, cached, path
            )

        try:
            df, meta = _load_file(path)
        except (FileNotFoundError, ValueError) as e:
            return error(
                f"Erreur : {e}",
                provenance={"source": "file", "path": path},
                retryable=True,
                method="file loader",
            )

        col_names = [c["name"] for c in meta["columns"]]
        source_alias = _source_alias_for_loaded_file(meta["path"], col_names)
        store_dataset(
            _store,
            thread_id,
            df,
            variable_name=variable_name,
            meta={**meta, "source": f"file:{meta['path']}"},
            latest_alias=source_alias,
            is_loaded_file=True,
        )
        from tools.source_scope import activate_file_source  # noqa: PLC0415

        activate_file_source(
            _store,
            thread_id,
            origin_user_text=str(meta["path"]),
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
                "\nRoute de jointure locale : `join_ecotaxa_ecopart` sans "
                "`project_id` si EcoTaxa est déjà chargé ; passe les variables "
                "de fichiers explicites si plusieurs datasets sont présents."
            )

        enc_note = f" (encodage : {meta['encoding']})" if meta.get("encoding") else ""
        summary = (
            f"Fichier chargé : {meta['path']}{enc_note}\n"
            f"{meta['n_rows']} lignes × {meta['n_cols']} colonnes\n"
            f"Variable persistante : `{variable_name}`\n"
            f"Colonnes : {cols}"
            f"{alias_note}"
            f"{route_note}"
            + (f"\n\n{hint}" if hint else "")
        )
        return success(
            summary,
            data_ref=variable_name,
            provenance={"source": "file", "path": str(meta["path"])},
            persisted=True,
            method="file loader",
            metrics={"rows": int(meta["n_rows"]), "columns": int(meta["n_cols"])},
        )

    @tool(response_format="content_and_artifact")
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
        next call. Exceptions persisted automatically and reusable by their exact
        name in later turns:
        - a canonical sample-depth DataFrame → `df_canonical_sample_depth`;
        - a join/merge/concat result → a new `df_join_*` table (reuse it instead
          of re-joining the source files).
        Every DataFrame output states `Persistence: persisted=true|false`; never
        describe an ephemeral (`false`) result as saved.
        """
        session = _store.get(thread_id)
        if not session or session.get("df") is None:
            return blocked("Aucun fichier chargé. Utilise load_file d'abord.")
        meta = session.get("meta") or {}
        if graph_recovery_pending(meta):
            return blocked(
                "Graph quality recovery: the previous graph was blocked for readability. "
                "Do not answer with a table; revise the matplotlib code and call run_graph again."
            )

        df = session["df"]
        local_vars: dict[str, Any] = {}

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.close("all")

            local_vars = _dataframe_vars(_store, thread_id, df)
            local_vars["plt"] = plt
            injected_keys = set(local_vars) | {"__builtins__"}

            guard = _neolabs_copepod_guard(code, local_vars)
            if guard:
                return blocked(guard, method="controlled pandas execution")

            apply_restricted_builtins(local_vars)
            exec(code, local_vars)  # noqa: S102

            if plt.get_fignums():
                plt.close("all")
                return blocked(
                    "Error: run_pandas produced a matplotlib figure. "
                    "Use run_graph instead to execute visualization code."
                )

            result = local_vars.get("result")

            # Persist any canonical sample-depth table built in this call — even
            # when it is only an intermediate and `result` is something else
            # (e.g. correlations). Keep the widest one, so environmental columns
            # carried onto the canonical table survive for later turns.
            new_vars = {
                key: value
                for key, value in local_vars.items()
                if key not in injected_keys
            }
            canonical_note = _persist_canonical_sample_depth(
                _store, thread_id, new_vars, result
            )

            if result is None:
                if canonical_note:
                    return success(
                        "Code exécuté." + canonical_note,
                        data_ref="df_canonical_sample_depth",
                        persisted=True,
                        method="controlled pandas execution",
                    )
                return success(
                    "Code exécuté (aucune variable `result` assignée).",
                    method="controlled pandas execution",
                )
            if isinstance(result, pd.DataFrame):
                n_rows, n_cols = result.shape
                preview = result.head(20).to_markdown(index=False)
                suffix = " (aperçu 20 premières)" if n_rows > 20 else ""

                # A join/merge/concat result is a durable new table the user will
                # reuse — persist it under its own name so later turns can target
                # it, instead of forcing a re-join. Canonical sample-depth tables
                # already have their own persistence path above.
                join_variable = None
                if not canonical_note and _is_join_code(code):
                    join_variable = dataset_variable_name("join", uuid.uuid4().hex[:12])
                    store_dataset(
                        _store, thread_id, result,
                        variable_name=join_variable,
                        meta={
                            "source": "analysis:join",
                            "n_rows": int(n_rows),
                            "n_cols": int(n_cols),
                        },
                        latest_alias=join_variable,
                    )

                persisted_variable = (
                    "df_canonical_sample_depth" if canonical_note else join_variable
                )
                if persisted_variable:
                    persistence_contract = (
                        f"\nPersistence: persisted=true; variable={persisted_variable}"
                    )
                else:
                    persistence_contract = (
                        "\nPersistence: persisted=false; variable=null — "
                        "résultat éphémère à cet appel"
                    )
                join_note = (
                    f"\nVariable persistante : `{join_variable}` — table jointe "
                    "réutilisable dans les prochains tours."
                    if join_variable
                    else ""
                )
                attrs_note = ""
                if result.attrs:
                    attrs_note = (
                        "\nAttributs d'analyse : "
                        + json.dumps(
                            result.attrs,
                            ensure_ascii=False,
                            sort_keys=True,
                            default=str,
                        )
                    )
                summary = (
                    f"{n_rows} lignes × {n_cols} colonnes{suffix}"
                    f"{canonical_note}{join_note}{persistence_contract}{attrs_note}"
                    f"\n\n{preview}"
                )
                return success(
                    summary,
                    data_ref=persisted_variable,
                    persisted=bool(persisted_variable),
                    method="controlled pandas execution",
                    metrics={"rows": int(n_rows), "columns": int(n_cols)},
                )
            return success(
                str(result) + canonical_note,
                data_ref="df_canonical_sample_depth" if canonical_note else None,
                persisted=bool(canonical_note),
                method="controlled pandas execution",
            )

        except Exception as e:
            cols_info = df.dtypes.to_string()
            hint = _column_location_hint(e, local_vars)
            return error(
                f"Erreur : {type(e).__name__}: {e}{hint}"
                f"\n\nColonnes disponibles :\n{cols_info}",
                retryable=True,
                method="controlled pandas execution",
            )

    @tool(response_format="content_and_artifact")
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
        if "graph_writer" not in loaded_skills:
            return blocked(
                'Graph workflow blocked: call load_skill("graph_writer") before run_graph. '
                "Loaded analysis/planning skills are not executable graph templates; graph_writer provides the required template."
            )

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.close("all")
            configure_offline_cartopy()
            _patch_cartopy_gridliner_polygon()

            if df is not None:
                local_vars = _dataframe_vars(_store, thread_id, df)
            else:
                local_vars = {"pd": pd}
            local_vars["plt"] = plt
            apply_restricted_builtins(local_vars)
            with _cartopy_safe_tight_layout(plt):
                exec(code, local_vars)  # noqa: S102

            if plt.get_fignums():
                graph_contract = local_vars.get("graph_contract")
                for fig_num in plt.get_fignums():
                    figure = plt.figure(fig_num)
                    graph_contract = normalize_graph_contract(graph_contract, figure)
                    contract_issue = validate_graph_contract(graph_contract, figure)
                    if contract_issue:
                        plt.close("all")
                        _mark_graph_quality_blocked(_store, thread_id)
                        return blocked(str(contract_issue), method="graph contract validation")
                quality_issue = _graph_quality_issue(plt)
                if quality_issue:
                    plt.close("all")
                    _mark_graph_quality_blocked(_store, thread_id)
                    return blocked(str(quality_issue), method="graph quality validation")
                buf = io.BytesIO()
                plt.savefig(buf, **_graph_savefig_kwargs(plt))
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
                    summary = f"{image_markdown}\n\n{explanation}"
                    return success(
                        summary,
                        artifact_refs=(graph_url(f"{graph_id}.png"),),
                        persisted=True,
                        method="controlled matplotlib execution",
                    )
                return success(
                    image_markdown,
                    artifact_refs=(graph_url(f"{graph_id}.png"),),
                    persisted=True,
                    method="controlled matplotlib execution",
                )

            return empty(
                "Code executed but no figure was produced. Make sure your matplotlib code creates a figure.",
                retryable=True,
                method="controlled matplotlib execution",
            )

        except Exception as e:
            # Only surface the columns hint when a loaded dataframe is actually
            # in play. For standalone figures (e.g. cartopy zone maps) there is
            # no file, and appending "(no file loaded)" wrongly suggests the
            # error is a missing file rather than a plotting bug.
            if df is not None:
                return error(
                    f"Error: {type(e).__name__}: {e}\n\n"
                    f"Available columns:\n{df.dtypes.to_string()}",
                    retryable=True,
                    method="controlled matplotlib execution",
                )
            return error(
                f"Error: {type(e).__name__}: {e}",
                retryable=True,
                method="controlled matplotlib execution",
            )

    return [load_file, run_pandas, run_graph]
