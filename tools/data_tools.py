"""Tools LangChain pour l'analyse de données — slice 2."""
import ast
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
from core.geo import load_registry
from core.graph_contracts import normalize_graph_contract, validate_graph_contract
from core.runtime_paths import graphs_dir
from tools.tool_result import blocked, empty, error, success
from tools.code_sandbox import apply_restricted_builtins


_GRAPHS_DIR = graphs_dir()


def _synthetic_record_table_guard(code: str) -> str | None:
    """Reject a DataFrame made entirely from literal records without lineage."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    def is_dataframe_call(node: ast.Call) -> bool:
        return (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "DataFrame"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"pd", "pandas"}
        )

    def is_literal_sequence(node: ast.AST) -> bool:
        return isinstance(node, (ast.List, ast.Tuple, ast.Set)) and all(
            isinstance(value, ast.Constant) for value in node.elts
        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_dataframe_call(node):
            continue
        payload = node.args[0] if node.args else next(
            (keyword.value for keyword in node.keywords if keyword.arg == "data"),
            None,
        )
        if isinstance(payload, ast.Dict) and payload.values and all(
            is_literal_sequence(value) for value in payload.values
        ):
            return (
                "Record labels must be retrieved from a persisted dataset or source "
                "query, not synthesized from literal values. Retrieve linked metadata "
                "before deriving or rendering."
            )
    return None


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
    loaded_file_dataset,
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
# Conservative overplotting threshold: below this a scatter stays readable even
# opaque; above it, opaque points hide the distribution and must use transparency
# or aggregation. Set high to avoid catching legitimately dense station maps.
_OVERPLOT_POINT_THRESHOLD = 1500


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


def _legend_column_count(legend: Any) -> int:
    """Return a matplotlib legend's declared column count across versions."""
    getter = getattr(legend, "get_ncols", None)
    value = getter() if callable(getter) else getattr(legend, "_ncols", 1)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _graph_quality_issue(plt: Any, graph_contract: dict | None = None) -> str | None:
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
                    compact_vertical_profile = (
                        graph_contract is not None
                        and graph_contract.get("kind") == "vertical_profile"
                        and len(labels) <= 30
                        and _legend_column_count(legend) >= 2
                    )
                    if not compact_vertical_profile:
                        return (
                            f"Graph quality blocked: {len(labels)} legend entries is too many. "
                            "For a vertical profile, use at most 30 entries in at least two legend columns; "
                            "otherwise omit the legend, aggregate groups, or show only the top 12 groups. "
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
            # Overplotting guard (conservative): a scatter with a large number of
            # fully opaque points renders an unreadable blob. Only block clearly
            # egregious cases — a high point count AND no transparency — so a
            # legitimately dense map with alpha is not caught.
            from matplotlib.collections import PathCollection
            for collection in ax.collections:
                # Only scatter (PathCollection). hexbin/aggregations are
                # PolyCollections — never block them, they ARE the fix.
                if not isinstance(collection, PathCollection):
                    continue
                try:
                    n_points = len(collection.get_offsets())
                except (TypeError, ValueError):
                    continue
                alpha = collection.get_alpha()
                opaque = alpha is None or alpha >= 0.95
                if n_points > _OVERPLOT_POINT_THRESHOLD and opaque:
                    return (
                        f"Graph quality blocked: {n_points} overplotted points with no transparency "
                        "hide the distribution. Add alpha (e.g. alpha=0.3-0.6), use smaller markers, "
                        "or aggregate (hexbin / 2D density / per-cell counts). "
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
    loaded = loaded_file_dataset(store, thread_id)
    if loaded and loaded.get("df") is not None:
        # Stable left-hand side for cross-source analysis. This does not
        # replace the active ``df`` after a remote query.
        local_vars["loaded_file"] = loaded["df"]
        loaded_variable = (loaded.get("meta") or {}).get("variable_name")
        if loaded_variable:
            local_vars["loaded_file_variable"] = loaded_variable
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


def _zone_geometry_vars() -> dict[str, Any]:
    """Expose the registered zone geometries to graph code without serialising WKT.

    Zone polygons are local, trusted registry data. Keeping them out of the
    model-visible tool result avoids sending hundreds of KB of WKT through the
    context while allowing ``run_graph`` to draw the exact registered outlines.
    """
    registry = load_registry(
        Path(__file__).parent.parent / "data" / "geo" / "zones_registry.geojson"
    )
    return {
        "zone_polygons": {zone.canonical: zone.polygon for zone in registry.zones},
        "zone_sources": {zone.canonical: zone.source for zone in registry.zones},
    }


def _infer_station_map_contract(figure: Any) -> dict[str, Any] | None:
    """Infer the safe default contract for a point map when the model omitted it."""
    axes = [
        axis for axis in getattr(figure, "axes", [])
        if axis.__class__.__module__.startswith("cartopy.")
    ]
    if len(axes) != 1:
        return None
    point_artist = next(
        (
            artist for artist in getattr(axes[0], "collections", [])
            if getattr(artist, "get_offsets", None) is not None
            and len(artist.get_offsets()) > 0
        ),
        None,
    )
    if point_artist is None:
        return None
    point_artist.set_gid("station_map_points")
    return {
        "kind": "station_map",
        "axes": [{"axis_index": 0, "x": "longitude", "y": "latitude"}],
        "inverted_axes": [],
        "mappings": {
            "position": {
                "variable": "longitude_latitude",
                "artist_gid": "station_map_points",
            },
        },
        "zero_policy": {"mode": "include", "artist_gid": None},
        "source_variables": ["longitude", "latitude"],
    }


def _infer_generic_contract(figure: Any) -> dict[str, Any] | None:
    """Minimal graph_contract for a plain matplotlib figure with no Cartopy axes.

    Used as a last-resort fallback when the model omitted graph_contract entirely.
    Reads x/y labels from the first axis to fill the role fields.
    """
    axes = list(getattr(figure, "axes", []))
    if not axes:
        return None
    if any(a.__class__.__module__.startswith("cartopy.") for a in axes):
        return None
    axis = axes[0]
    x_role = str(axis.get_xlabel() or "x").strip() or "x"
    y_role = str(axis.get_ylabel() or "y").strip() or "y"
    return {
        "kind": "generic",
        "axes": [{"axis_index": 0, "x": x_role, "y": y_role}],
        "inverted_axes": [],
        "mappings": {},
        "zero_policy": {"mode": "include", "artist_gid": None},
        "source_variables": [x_role, y_role],
    }


def _upgrade_plain_lat_lon_scatter_to_station_map(figure: Any, plt: Any) -> Any | None:
    """Convert an unambiguous longitude/latitude scatter into a safe map.

    This is deliberately narrower than a generic graph fallback: it accepts one
    ordinary Matplotlib axis, one non-empty scatter, and explicit longitude and
    latitude labels.  That is the exact shape emitted for EcoTaxa cast maps
    when the model omits the Cartopy template and graph contract.  Other
    contract omissions remain blocked.
    """
    axes = list(getattr(figure, "axes", []))
    if len(axes) != 1 or axes[0].__class__.__module__.startswith("cartopy."):
        return None
    axis = axes[0]
    x_label = str(axis.get_xlabel() or "").strip().lower()
    y_label = str(axis.get_ylabel() or "").strip().lower()
    if not ("longitude" in x_label and "latitude" in y_label):
        return None
    collections = [
        artist for artist in getattr(axis, "collections", [])
        if getattr(artist, "get_offsets", None) is not None
        and len(artist.get_offsets()) > 0
    ]
    if len(collections) != 1 or getattr(axis, "lines", []):
        return None

    import numpy as np
    import cartopy.crs as ccrs

    offsets = np.asarray(collections[0].get_offsets(), dtype=float)
    finite = offsets[np.isfinite(offsets).all(axis=1)]
    if finite.size == 0:
        return None
    lon, lat = finite[:, 0], finite[:, 1]
    if not (np.all((-180 <= lon) & (lon <= 180)) and np.all((-90 <= lat) & (lat <= 90))):
        return None

    map_figure, map_axis = plt.subplots(
        figsize=figure.get_size_inches(), subplot_kw={"projection": ccrs.PlateCarree()}
    )
    lon_span = max(float(lon.max() - lon.min()), 0.25)
    lat_span = max(float(lat.max() - lat.min()), 0.25)
    map_axis.set_extent(
        [lon.min() - lon_span * 0.12, lon.max() + lon_span * 0.12,
         lat.min() - lat_span * 0.12, lat.max() + lat_span * 0.12],
        crs=ccrs.PlateCarree(),
    )
    points = map_axis.scatter(
        lon, lat, s=collections[0].get_sizes() or 36, color="tab:blue",
        alpha=0.8, edgecolors="black", linewidths=0.3,
        transform=ccrs.PlateCarree(),
    )
    points.set_gid("station_map_points")
    map_axis.set_title(axis.get_title() or "Carte des stations")
    map_axis.gridlines(draw_labels=True, linestyle=":", linewidth=0.5, alpha=0.6)
    plt.close(figure)
    return map_figure


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


def _result_is_direct_join(code: str) -> bool:
    """Return whether ``result`` itself is assigned from a join operation.

    Analytical merges (for example, joining yearly denominators onto a control
    table) must not silently replace the active source dataset. A direct
    ``result = left.merge(right, ...)`` remains a genuine join workflow.
    AST inspection keeps this distinction semantic instead of matching domain
    words or variable names.
    """
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "result" for target in node.targets):
            continue
        value = node.value
        if isinstance(value, ast.Call):
            if isinstance(value.func, ast.Attribute) and value.func.attr in {"merge", "join", "concat"}:
                return True
            if isinstance(value.func, ast.Attribute) and value.func.attr == "merge":
                return True
            if isinstance(value.func, ast.Name) and value.func.id in {"merge", "concat"}:
                return True
    return False


def _modified_source_variable(
    result: Any,
    local_vars: dict[str, Any],
    injected_keys: set[str],
    code: str,
) -> str | None:
    """Return the named session table from which ``result`` is a changed copy.

    A table update commonly follows ``df = df_join_*.copy(); ...; result = df``.
    It is neither a new join nor an analytical aggregation, so the existing
    persistence paths do not recognise it. Keep this rule narrow: only a
    same-index, same-granularity result retaining every source column becomes a
    persisted derived table. Aggregations, previews, and filtered subsets keep
    their existing ephemeral contract.
    """
    if not isinstance(result, pd.DataFrame):
        return None

    for name in sorted(injected_keys):
        source = local_vars.get(name)
        if (
            not name.startswith("df_")
            or not isinstance(source, pd.DataFrame)
            or result is source
            or not re.search(rf"\b{re.escape(name)}\b", code)
        ):
            continue
        if (
            result.index.equals(source.index)
            and source.columns.isin(result.columns).all()
            and not result.equals(source)
        ):
            return name
    return None


def _ast_operand_name(node: ast.AST) -> str | None:
    """Best-effort readable name for a merge/join operand AST node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return _ast_operand_name(node.func.value)
    return None


def _ast_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        parts = [_ast_literal(elt) for elt in node.elts]
        joined = ",".join(part for part in parts if part)
        return joined or None
    return None


def _describe_join(code: str, frame: "pd.DataFrame") -> str:
    """Readable description of a persisted join, for the dataset state capsule.

    Extracts the operands, the join key (``on``/``left_on``) and ``how`` from the
    merge/join/concat call so a persisted ``df_join_*`` reads as *what* it is
    (parity with EcoTaxa selections) instead of only an opaque hash name.
    Falls back to a shape summary when the call cannot be parsed.
    """
    left = right = key = how = None
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        tree = None
    for node in ast.walk(tree) if tree else []:
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name)):
                pass
            else:
                continue
        func = node.func
        attr = getattr(func, "attr", None) or getattr(func, "id", None)
        if attr in {"merge", "join", "merge_asof"}:
            left = _ast_operand_name(func.value) if isinstance(func, ast.Attribute) else None
            if node.args:
                right = _ast_operand_name(node.args[0])
            for kw in node.keywords:
                if kw.arg in {"on", "left_on"} and key is None:
                    key = _ast_literal(kw.value)
                elif kw.arg == "how":
                    how = _ast_literal(kw.value)
            break
        if attr == "concat":
            operands = node.args[0] if node.args else None
            if isinstance(operands, (ast.List, ast.Tuple)):
                names = [_ast_operand_name(elt) for elt in operands.elts]
                joined = " + ".join(name for name in names if name)
                left = joined or None
            how = how or "concat"
            break
    rows, cols = frame.shape
    if left and right:
        head = f"Jointure {left} × {right}"
    elif left:
        head = f"Concat {left}" if how == "concat" else f"Jointure {left}"
    else:
        head = "Table jointe"
    extras = []
    if key:
        extras.append(f"clé={key}")
    if how and how != "concat":
        extras.append(f"type={how}")
    extras.append(f"{rows}×{cols}")
    return head + " — " + ", ".join(extras)


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
        preview_cols = ", ".join(col_names[:6]) + ("…" if len(col_names) > 6 else "")
        file_description = (
            f"{Path(meta['path']).name} — {df.shape[0]} lignes × {df.shape[1]} "
            f"colonnes ({preview_cols})"
        )
        store_dataset(
            _store,
            thread_id,
            df,
            variable_name=variable_name,
            meta={**meta, "source": f"file:{meta['path']}", "description": file_description},
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
        - `loaded_file`  : fichier original chargé, immuable comme table de référence
        - `df_file_*`    : fichiers chargés, y compris après une requête EcoTaxa
        - `df_derived_*` : copies modifiées de tables de session, persistées sous
          le nom exact retourné par l'appel précédent
        - `df_ecotaxa_selection_*`: sélections cache EcoTaxa persistantes et
          simultanément réutilisables par leur nom exact dans WORKING TABLES
        - `df_ecotaxa_cache_query`: alias de la dernière requête cache EcoTaxa

        Pour comparer un fichier et EcoTaxa, utilise `loaded_file` ou le
        `df_file_*` correspondant comme table de gauche et
        `df_ecotaxa_cache_query` comme table de droite. Le `df` actif peut être
        le résultat EcoTaxa et ne remplace jamais `loaded_file`.

        Assigne le résultat à la variable `result`. Les sorties `print(...)`
        exécutées dans le même appel sont également capturées et renvoyées,
        afin qu'un tableau de contrôle préparé explicitement ne soit pas perdu.
        Pour une jointure : result = df_ecotaxa.merge(df_ctd, on='station_id', how='left')

        IMPORTANT: each call to run_pandas is isolated — variables computed in a
        previous call (e.g. `station_stats`, `delta_df`) are NOT available in the
        next call. Exceptions persisted automatically and reusable by their exact
        name in later turns:
        - a canonical sample-depth DataFrame → `df_canonical_sample_depth`;
        - a join/merge/concat result → a new `df_join_*` table (reuse it instead
          of re-joining the source files).
        - a modified same-granularity copy of a named `df_*` table → a new
          `df_derived_*` table (reuse the exact returned name in later calls).
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
            code_lower = code.lower()
            synthetic_record_guard = _synthetic_record_table_guard(code)
            if synthetic_record_guard:
                return blocked(
                    synthetic_record_guard,
                    retryable=True,
                    method="data lineage validation",
                )
            if (
                "bbox" in code_lower
                and (
                    "ax.plot" in code_lower
                    or "rectangle" in code_lower
                    or "mplpolygon" in code_lower
                    or "add_patch" in code_lower
                )
                and ("sample" in code_lower or "plot_df" in code_lower)
            ):
                _mark_graph_quality_blocked(_store, thread_id)
                return blocked(
                    "named-zone sample maps must draw the exact `zone_polygons` "
                    "geometries with Cartopy ShapelyFeature; do not draw bbox "
                    "rectangles. Retry exactly once with the same active dataframe.",
                    retryable=True,
                    method="registered zone boundary validation",
                )
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
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exec(code, local_vars)  # noqa: S102
            printed_output = stdout.getvalue().strip()

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

            # A join workflow may keep the joined DataFrame in a named
            # intermediate (`joined`, `merged`, or `result_df`) while assigning
            # a compact summary dict to `result`. Persist that named table too;
            # otherwise the next turn cannot reuse the active joined file.
            join_variable = None
            join_frame = None
            if not canonical_note and _is_join_code(code):
                preferred_join = next(
                    (
                        new_vars[name]
                        for name in ("joined", "merged", "result_df")
                        if isinstance(new_vars.get(name), pd.DataFrame)
                    ),
                    None,
                )
                if isinstance(result, pd.DataFrame) and (
                    _result_is_direct_join(code) or preferred_join is not None
                ):
                    join_frame = result
                else:
                    join_frame = preferred_join
                if join_frame is not None:
                    join_variable = dataset_variable_name(
                        "join", uuid.uuid4().hex[:12]
                    )
                    store_dataset(
                        _store,
                        thread_id,
                        join_frame,
                        variable_name=join_variable,
                        meta={
                            "source": "analysis:join",
                            "n_rows": int(join_frame.shape[0]),
                            "n_cols": int(join_frame.shape[1]),
                            "description": _describe_join(code, join_frame),
                        },
                        latest_alias=join_variable,
                    )

            derived_variable = None
            if not canonical_note and not join_variable and isinstance(result, pd.DataFrame):
                derived_name = _modified_source_variable(
                    result, local_vars, injected_keys, code
                )
                derived_description = None
                if derived_name:
                    derived_description = f"Table dérivée modifiée depuis {derived_name}"
                else:
                    derived_name = next(
                        (
                            name
                            for name in (
                                "derived_df",
                                "result_df",
                                "profile_df",
                                "abundance_df",
                            )
                            if new_vars.get(name) is result
                        ),
                        None,
                    )
                if derived_name:
                    derived_variable = dataset_variable_name("derived", derived_name)
                    store_dataset(
                        _store,
                        thread_id,
                        result,
                        variable_name=derived_variable,
                        meta={
                            "source": "analysis:derived",
                            "n_rows": int(result.shape[0]),
                            "n_cols": int(result.shape[1]),
                            "description": (
                                derived_description
                                or f"Table dérivée nommée {derived_name}"
                            ),
                        },
                        latest_alias=derived_variable,
                    )

            if result is None:
                printed_note = (
                    "\n\nSortie contrôlée du code :\n" + printed_output
                    if printed_output else ""
                )
                if canonical_note:
                    return success(
                        "Code exécuté." + canonical_note + printed_note,
                        data_ref="df_canonical_sample_depth",
                        persisted=True,
                        method="controlled pandas execution",
                    )
                return success(
                    "Code exécuté (aucune variable `result` assignée)." + printed_note,
                    method="controlled pandas execution",
                )
            if isinstance(result, pd.DataFrame):
                n_rows, n_cols = result.shape
                preview = result.head(20).to_markdown(index=False)
                suffix = " (aperçu 20 premières)" if n_rows > 20 else ""

                persisted_variable = (
                    "df_canonical_sample_depth"
                    if canonical_note
                    else (join_variable or derived_variable)
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
                persistence_note = (
                    f"\nVariable persistante : `{join_variable}` — table jointe "
                    "réutilisable dans les prochains tours."
                    if join_variable
                    else (
                        f"\nVariable persistante : `{derived_variable}` — table dérivée "
                        "réutilisable dans les prochains tours."
                        if derived_variable
                        else ""
                    )
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
                    f"{canonical_note}{persistence_note}{persistence_contract}{attrs_note}"
                    f"\n\n{preview}"
                )
                if printed_output:
                    summary += "\n\nSortie contrôlée du code :\n" + printed_output
                if n_rows > 20:
                    summary += (
                        "\n\nAttention : ce tableau est un aperçu des 20 premières "
                        "lignes seulement. Ne complète pas les lignes absentes ; "
                        "utilise un nouveau run_pandas ciblé pour obtenir une autre "
                        "page ou un agrégat vérifiable."
                    )
                return success(
                    summary,
                    data_ref=persisted_variable,
                    persisted=bool(persisted_variable),
                    method="controlled pandas execution",
                    metrics={"rows": int(n_rows), "columns": int(n_cols)},
                )
            persistence_note = ""
            if join_variable:
                persistence_note = (
                    f"\nVariable persistante : `{join_variable}` — table jointe "
                    "réutilisable dans les prochains tours."
                    f"\nPersistence: persisted=true; variable={join_variable}"
                )
            return success(
                str(result) + canonical_note + persistence_note,
                data_ref=(
                    "df_canonical_sample_depth"
                    if canonical_note
                    else join_variable
                ),
                persisted=bool(canonical_note or join_variable),
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
        Standalone figures work without a file only for boundary-only maps. A
        map of samples must use an exact persisted named DataFrame; do not rely
        on bare `df` when the request concerns a source selection.
        """
        session = _store.get(thread_id)
        df = session.get("df") if session else None
        loaded_skills = ((session or {}).get("meta") or {}).get("loaded_skills") or []
        if "graph_writer" not in loaded_skills:
            # Recover the common model-routing slip locally. The model already
            # supplied executable graph code; activating the reviewed writer
            # skill lets the render attempt continue instead of ending the
            # whole user turn on a recoverable sequencing error.
            from tools.skill_manifest import load_skill_document
            from tools.skill_tool import SKILLS_DIR, _record_loaded_skill

            _record_loaded_skill(
                _store, thread_id, "graph_writer",
                load_skill_document(SKILLS_DIR / "graph_writer.md"),
            )
            loaded_skills = [*loaded_skills, "graph_writer"]

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
            local_vars.update(_zone_geometry_vars())
            local_vars["plt"] = plt
            apply_restricted_builtins(local_vars)
            with _cartopy_safe_tight_layout(plt):
                exec(code, local_vars)  # noqa: S102

            if plt.get_fignums():
                graph_contract = local_vars.get("graph_contract")
                for fig_num in plt.get_fignums():
                    figure = plt.figure(fig_num)
                    graph_contract = normalize_graph_contract(graph_contract, figure)
                    if graph_contract is None:
                        graph_contract = _infer_station_map_contract(figure)
                    if graph_contract is None:
                        upgraded_figure = _upgrade_plain_lat_lon_scatter_to_station_map(
                            figure, plt
                        )
                        if upgraded_figure is not None:
                            figure = upgraded_figure
                            graph_contract = _infer_station_map_contract(figure)
                    # Last-resort fallback: plain matplotlib figure, no contract → infer generic.
                    if graph_contract is None:
                        graph_contract = _infer_generic_contract(figure)
                    contract_issue = validate_graph_contract(graph_contract, figure)
                    if contract_issue:
                        plt.close("all")
                        _mark_graph_quality_blocked(_store, thread_id)
                        return blocked(
                            f"{contract_issue} Retry exactly once: revise the graph code using this diagnostic, "
                            "reuse the same active dataframe, and call run_graph again. Do not answer with a table.",
                            retryable=True,
                            method="graph contract validation",
                        )
                quality_issue = _graph_quality_issue(plt, graph_contract)
                if quality_issue:
                    plt.close("all")
                    _mark_graph_quality_blocked(_store, thread_id)
                    return blocked(
                            f"{quality_issue} Retry exactly once: revise the graph code using this diagnostic, "
                            "reuse the same active dataframe, and call run_graph again. Do not answer with a table.",
                            retryable=True,
                            method="graph quality validation",
                        )
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
            # A confirmed EcoTaxa export is object-grain data.  A vertical
            # profile needs a derived abundance metric, not an invented source
            # column.  This is detected from the failing operation and the
            # actual schema, rather than from the user's wording, so every
            # language and paraphrase follows the same recovery path.
            raw_object_export = bool(
                df is not None
                and {"object_id", "object_depth_min"}.issubset(df.columns)
                and any(
                    column in df.columns
                    for column in (
                        "object_annotation_category",
                        "object_annotation_hierarchy",
                    )
                )
            )
            if (
                raw_object_export
                and isinstance(e, ValueError)
                and "abundance column" in str(e).casefold()
            ):
                return blocked(
                    "The current table is one object per row, not a precomputed abundance table. "
                    "Before retrying the graph, use run_pandas on this exact table: select one "
                    "observed annotation, count object_id by sample_id and object_depth_min, "
                    "and persist the resulting profile table. Then render from that table.",
                    retryable=True,
                    method="object-grain abundance precondition",
                )
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
