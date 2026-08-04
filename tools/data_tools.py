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
    """Compatibility facade: rendered graphs are no longer quality-gated."""
    return False


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


_NEOLABS_ARCHITECTURE = """Modèle de données NeoLabs (deux fichiers joignables) :

DEPLOYMENT (deployment_id) — un trait d'engin à une station
  = station_name + cast_number + datetime + gear + tow_type
  · tow_type : V-Tow (vertical) | O-Tow (oblique)
  · gear     : Hydrobios / Bioness / 4x1m2 / 2x1m2 (multinet) | Ringnet (mono-filet)
  │
  ├─ NET SAMPLE (sample_id ≈ net_sampling_id) — 1 filet = 1 strate de profondeur
  │    [min_sample_depth, max_sample_depth] ; sample_nets = position/maille du filet
  │    → PROFIL VERTICAL : un deployment multinet (Hydrobios, Bioness, 4x1m2…)
  │      ouvre/ferme plusieurs filets à des profondeurs successives, donc
  │      1 deployment = 1 profil = PLUSIEURS net samples (un par strate).
  │      Ex. deployment de 9 filets : 2-10 m, 10-20 m, 20-30 m … 115-125 m.
  │      Un mono-filet (Ringnet) ou un V-Tow intégré = 1 seul net sample.
  │      ⇒ RÈGLE PROFIL : UN profil vertical = UN seul deployment (station+cast),
  │        ses net samples empilés par strate de profondeur. JAMAIS pooler des
  │        deployments/stations différents sur un même profil. Si aucun deployment
  │        n'est nommé, DEMANDER lequel (ou en proposer un par station si l'ensemble
  │        est petit) — ne trace pas MAX_SAMPLE_DEPTH sur toutes les lignes.
  │    │
  │    └─ ANALYSIS (analysis_id, analysis_type) — analyse taxonomique d'un sample
  │         · tous les samples ne sont PAS analysés (0 à 2 analyses / sample)
  │         │
  │         └─ ABONDANCE — 1 ligne par TAXON, clé SAMPLE_ID + ANALYSIS_ID + TAXON_ID

Vocabulaire :
- V-Tow (trait vertical) : filet descendu à la profondeur max puis remonté droit
  vers la surface — intègre la colonne d'eau ; avec un multinet à filets fermables,
  chaque filet isole une strate discrète. Majorité des traits.
- O-Tow (trait oblique) : filet remorqué en biais, navire en route — intègre à la
  fois la profondeur et une distance horizontale (pas un point vertical strict).
- Maille (`net_mesh_size`, µm) : 50 / 64 = petits copépodes & nauplii, 200 =
  copépodes standard, 500 / 750 = plus gros zooplancton. `net_mouth_aperture` =
  surface d'ouverture du filet (m²), sert au volume filtré.
- `sample_nets` : le(s) filet(s) du prélèvement ; ex. `200-RED` = filet maille
  200 µm (repère couleur), `1`…`9` = position dans le multinet, `1+2+3` = filets
  combinés (poolés) en un seul net sample.
- Engins (`gear`) : Hydrobios (jusqu'à 9 filets fermables), Bioness, 4x1m2 / 2x1m2
  (± LOKI) = multinets (plusieurs strates) ; Ringnet 1 m / 50 cm = mono-filet.

Deux fichiers, deux grains :
- neolabs_sample.csv  (colonnes minuscules) : 1 ligne / net sample ; deployment,
  station, cast, gear, tow, filet, profondeurs, LATITUDE/LONGITUDE, volumes filtrés.
- neolabs_abundance.csv (colonnes MAJUSCULES) : 1 ligne / taxon×analyse ; abondance
  et biomasse par stade. `ALL_STAGES` = total de la ligne — NE PAS le sommer avec ses
  composants (C1-C5 / M / F / COP_NS / COPEPODID) ; `X_SAMPLE_ABUND` = comptage brut,
  `X_ABUND (ind./m3 …)` = densité (métrique comparable, défaut depth vol).
- Jointure : `SAMPLE_ID = sample_id` (+ `ANALYSIS_ID`). lat/lon UNIQUEMENT côté sample
  → toute carte ou analyse spatiale NeoLabs exige cette jointure d'abord."""


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
    # NeoLabs abundance file: taxon-level rows with per-stage abundance. Accept
    # BOTH the normalized single-total export and the raw WIDE per-stage export
    # (columns like `ALL_STAGES_ABUND (ind./m3 depth vol.)`). The earlier check
    # required the phantom `Total abundance` column and silently missed the real
    # wide file, so the load hint never fired.
    has_stage_density = any(
        c.endswith("_ABUND (ind./m3 depth vol.)") for c in col_set
    )
    is_neolabs = (
        "TAXON_ID" in col_set
        and ("CLASS" in col_set or "ZOOPLANKTON_CATEGORY" in col_set)
        and ("Total abundance (ind./m3 depth vol)" in col_set or has_stage_density)
    )
    # NeoLabs sample file: one row per net sample — the deployment/net/depth/coords
    # metadata the abundance file must join to for any spatial or vertical work.
    is_neolabs_sample = (
        "sample_id" in col_set
        and "deployment_id" in col_set
        and "net_sampling_ids" in col_set
        and "tow_type" in col_set
    )
    if is_ecopart:
        return (
            "→ Fichier EcoPart UVP détecté. "
            "Charge le skill `uvp_ecopart` pour les méthodes de calcul (m1-m3)."
        )
    if is_neolabs:
        return (
            "→ Fichier NeoLabs ABONDANCE chargé (1 ligne par taxon×analyse).\n\n"
            + _NEOLABS_ARCHITECTURE
            + "\n\nCharge `neolabs_abundance_analysis` ; pour une densité de "
            "copépodes utilise le contrat `neolabs_copepod_density` — ne fais pas "
            "une moyenne tous-taxons sur les lignes brutes."
        )
    if is_neolabs_sample:
        return (
            "→ Fichier NeoLabs SAMPLE chargé (1 ligne par net sample ; fournit les "
            "latitude/longitude et les strates de profondeur absentes du fichier "
            "abondance).\n\n"
            + _NEOLABS_ARCHITECTURE
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


def _file_variable_name(path: str) -> str:
    """Return the stable session name for a loaded file.

    NeoLabs files are frequently uploaded with a UUID prepended to their
    filename. Keep their semantic names stable so the model and user can refer
    to the sample and abundance tables unambiguously across upload methods.
    """
    stem = Path(path).stem.lower()
    if stem.endswith("neolabs_sample"):
        return "df_file_neolabs_sample"
    if stem.endswith("neolabs_abundance"):
        return "df_file_neolabs_abundance"
    return dataset_variable_name("file", Path(path).stem)


def _referenced_names(code: str) -> set[str]:
    """Return identifiers explicitly read by a user-provided Python snippet.

    ``run_graph`` executes one isolated snippet, so its DataFrame namespace can
    be limited to the names that snippet actually reads.  This avoids eagerly
    unpickling every historical dataset in a session just to draw a figure from
    a small derived table.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }


def _dataframe_vars(
    store: SessionStore,
    thread_id: str,
    df: pd.DataFrame,
    required_names: set[str] | None = None,
) -> dict[str, Any]:
    """Build the DataFrame namespace shared by pandas and graph tools.

    ``run_pandas`` keeps the historical all-datasets namespace so analysis can
    freely combine persisted inputs.  ``run_graph`` supplies its parsed names:
    only the explicitly referenced DataFrames are then materialised.
    """
    def required(name: str) -> bool:
        return required_names is None or name in required_names

    local_vars: dict[str, Any] = {"df": df, "pd": pd}
    if required("loaded_file") or required("loaded_file_variable"):
        loaded = loaded_file_dataset(store, thread_id)
        if loaded and loaded.get("df") is not None:
            # Stable left-hand side for cross-source analysis. This does not
            # replace the active ``df`` after a remote query.
            local_vars["loaded_file"] = loaded["df"]
            loaded_variable = (loaded.get("meta") or {}).get("variable_name")
            if loaded_variable:
                local_vars["loaded_file_variable"] = loaded_variable
    for alias in SOURCE_ALIASES:
        variable_name = source_variable(alias)
        if not required(variable_name):
            continue
        named = store.get(f"{thread_id}:{alias}")
        if named and named.get("df") is not None:
            local_vars[variable_name] = named["df"]

    for key in store.keys(f"{thread_id}:dataset:"):
        variable_name = key.removeprefix(f"{thread_id}:dataset:")
        if not required(variable_name):
            continue
        named = store.get(key)
        persisted_name = (named or {}).get("meta", {}).get("variable_name")
        if persisted_name and named.get("df") is not None:
            local_vars[persisted_name] = named["df"]

    for key in store.keys(f"{thread_id}:ecopart:"):
        project_id = key.rsplit(":", 1)[-1]
        variable_name = f"df_ecopart_{project_id}"
        if not required(variable_name):
            continue
        named = store.get(key)
        if project_id.isdigit() and named and named.get("df") is not None:
            local_vars.setdefault(variable_name, named["df"])

    if required("plot_df"):
        last_plot = store.get(f"{thread_id}:last_plot_df")
        if last_plot and last_plot.get("df") is not None:
            local_vars.setdefault("plot_df", last_plot["df"])

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
    # Use the first Cartopy axis even when the figure also carries an inset or a
    # second GeoAxes: a rendered map must not be blocked for missing bookkeeping
    # just because it has more than one geo panel.
    if not axes:
        return None
    point_artist = next(
        (
            artist for axis in axes
            for artist in getattr(axis, "collections", [])
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
    """Guaranteed last-resort graph_contract for any rendered figure with an axis.

    When the model omits ``graph_contract`` entirely and no kind-specific
    inference applies, a successfully rendered figure must still not be blocked
    for missing bookkeeping — the code is good, only the metadata is absent. This
    always returns a structurally valid ``generic`` contract as long as the
    figure has at least one axis, including Cartopy maps (roles longitude/latitude).
    Semantic guarantees (depth inversion, independent panels, hollow zeros) live
    in the kind-specific validation paths and are never bypassed by this fallback,
    which only ever fires when the model supplied no contract at all.
    """
    axes = list(getattr(figure, "axes", []))
    if not axes:
        return None
    axis = axes[0]
    if axis.__class__.__module__.startswith("cartopy."):
        x_role, y_role = "longitude", "latitude"
    else:
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


def _can_fallback_to_generic_contract(contract: Any, figure: Any) -> bool:
    """Whether malformed metadata may safely yield to a rendered generic chart.

    The contract vocabulary is deliberately finite, whereas legitimate
    matplotlib chart families are not.  Keep strict semantic validation for
    geographic maps and depth profiles; for other plain non-geographic figures,
    the visible axes and quality guards are the authoritative truth.
    """
    if any(
        axis.__class__.__module__.startswith("cartopy.")
        for axis in getattr(figure, "axes", [])
    ):
        return False
    if not isinstance(contract, dict):
        return True
    return contract.get("kind") not in {
        "vertical_profile",
        "station_map",
        "abundance_environment_map",
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
    canonical_aliases = {
        "te90": ("amundsen_te90_degC", "temperature_degC"),
        "temp": ("amundsen_te90_degC", "temperature_degC"),
        "temperature": ("amundsen_te90_degC", "temperature_degC"),
        "psal": ("amundsen_psal_psu", "salinity_psu"),
        "sal": ("amundsen_psal_psu", "salinity_psu"),
        "salinity": ("amundsen_psal_psu", "salinity_psu"),
        "salinite": ("amundsen_psal_psu", "salinity_psu"),
        "pres": ("amundsen_pres_dbar", "depth_m"),
        "pressure": ("amundsen_pres_dbar", "depth_m"),
        "pression": ("amundsen_pres_dbar", "depth_m"),
        "sigt": ("amundsen_sigt", "density_sigt"),
        "density": ("amundsen_sigt", "density_sigt"),
        "densite": ("amundsen_sigt", "density_sigt"),
        "oxym": ("amundsen_oxym", "oxygen_oxym"),
        "oxygen": ("amundsen_oxym", "oxygen_oxym"),
        "oxygene": ("amundsen_oxym", "oxygen_oxym"),
        "ph": ("amundsen_ph", "ph"),
        "ntra": ("amundsen_ntra", "nitrate_ntra"),
        "nitrate": ("amundsen_ntra", "nitrate_ntra"),
        "flor": ("amundsen_flor", "fluorescence_flor"),
        "fluorescence": ("amundsen_flor", "fluorescence_flor"),
    }
    targets = canonical_aliases.get(missing.casefold(), (missing,))
    target = next(
        (
            candidate
            for candidate in targets
            if any(
                name.startswith("df_")
                and isinstance(value, pd.DataFrame)
                and candidate in value.columns
                for name, value in local_vars.items()
            )
        ),
        targets[0],
    )
    holders = sorted(
        name
        for name, value in local_vars.items()
        if name.startswith("df_")
        and isinstance(value, pd.DataFrame)
        and target in value.columns
    )
    if not holders:
        return ""
    alias_note = (
        f" La colonne canonique correspondante est `{target}`."
        if target != missing else ""
    )
    return (
        f"\nLa colonne `{missing}` est absente de la table active `df` mais "
        f"sa donnée est présente dans : {', '.join(holders)}.{alias_note} "
        "Cible la variable et la colonne explicites."
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
    """True si les colonnes trahissent une table NeoLabs taxonomy.

    Reconnaît le format normalisé (`Total abundance …`) ET le format wide brut
    (colonnes par stade `X_ABUND (ind./m3 depth vol.)`).
    """
    cols = set(columns)
    has_total = "Total abundance (ind./m3 depth vol)" in cols
    has_stage_density = any(
        str(c).endswith("_ABUND (ind./m3 depth vol.)") for c in cols
    )
    return (
        "TAXON_ID" in cols
        and ("CLASS" in cols or "ZOOPLANKTON_CATEGORY" in cols)
        and (has_total or has_stage_density)
    )


def _is_neolabs_sample_columns(columns) -> bool:
    """True pour la table NeoLabs sample au grain filet/analyse."""
    cols = set(columns)
    return {
        "sample_id",
        "analysis_id",
        "deployment_id",
        "net_sampling_ids",
        "tow_type",
    }.issubset(cols)


def _neolabs_join_guard(code: str, local_vars: dict[str, Any]) -> str | None:
    """Refuse la conversion texte destructive des clés avant une jointure NeoLabs."""
    if not _is_join_code(code):
        return None
    has_abundance = any(
        isinstance(value, pd.DataFrame) and _is_neolabs_columns(value.columns)
        for value in local_vars.values()
    )
    has_samples = any(
        isinstance(value, pd.DataFrame)
        and _is_neolabs_sample_columns(value.columns)
        for value in local_vars.values()
    )
    if not (has_abundance and has_samples):
        return None

    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return None

    key_columns = {"SAMPLE_ID", "ANALYSIS_ID", "sample_id", "analysis_id"}
    unsafe_columns: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "astype":
            continue
        if not call.args:
            continue
        dtype = call.args[0]
        is_string_cast = (
            isinstance(dtype, ast.Name) and dtype.id == "str"
        ) or (
            isinstance(dtype, ast.Constant)
            and str(dtype.value).casefold() in {"str", "string"}
        )
        if not is_string_cast:
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            column = target.slice
            if isinstance(column, ast.Constant) and column.value in key_columns:
                unsafe_columns.add(str(column.value))

    if not unsafe_columns:
        return None
    return (
        "run_pandas bloqué : ne convertis jamais les clés de jointure NeoLabs "
        f"avec astype(str) ({', '.join(sorted(unsafe_columns))}). "
        "`ANALYSIS_ID` est entier côté abondance tandis que `analysis_id` peut "
        "être flottant côté sample : la conversion produit par exemple '2185' "
        "contre '2185.0' et détruit tous les appariements. Utilise "
        "`prepare_neolabs_analysis` avec les deux chemins chargés. Si une "
        "jointure manuelle est indispensable, conserve les clés numériques."
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
    reference_note = (
        f"\nTable à citer dans une prochaine demande : `{variable_name}`"
        if len(store.keys(f"{thread_id}:dataset:")) > 1 else ""
    )
    return success(
        "Fichier déjà chargé en session — réutilisé sans relecture.\n"
        f"{n_rows} lignes × {n_cols} colonnes\n"
        f"Table de session disponible : `{variable_name}`\n"
        f"Colonnes : {', '.join(map(str, col_names))}"
        f"{alias_note}{reference_note}",
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
    def prepare_neolabs_analysis(
        abundance_path: str = "data/neolabs/neolabs_abundance.csv",
        sample_path: str = "data/neolabs/neolabs_sample.csv",
    ) -> str:
        """Prépare en un appel le parcours local NeoLabs pour analyses et graphes.

        Charge les deux fichiers officiels, effectue une jointure externe sur
        sample + analyse, calcule la densité totale de copépodes uniquement pour
        les couples calculables, puis persiste la couverture et une table prête
        pour les cartes. Toutes les lignes sources restent traçables par leur
        statut; une abondance absente n'est jamais remplacée par zéro.
        """
        from core.demo_workflows import (  # noqa: PLC0415
            NEOLABS_COLUMN_DESCRIPTIONS,
            NEOLABS_DEMO_METHOD_VERSION,
            prepare_neolabs_tables,
        )

        try:
            abundance, abundance_meta = _load_file(abundance_path)
            samples, sample_meta = _load_file(sample_path)
            tables = prepare_neolabs_tables(abundance, samples)
        except (FileNotFoundError, ValueError) as exc:
            return error(
                f"Préparation NeoLabs impossible : {exc}",
                provenance={"source": "file"},
                retryable=isinstance(exc, FileNotFoundError),
                method=NEOLABS_DEMO_METHOD_VERSION,
            )

        def _schema_metadata(frame: pd.DataFrame, description: str) -> dict:
            descriptions = {
                column: NEOLABS_COLUMN_DESCRIPTIONS[column]
                for column in frame.columns
                if column in NEOLABS_COLUMN_DESCRIPTIONS
            }
            return {
                "n_rows": int(len(frame)),
                "n_cols": int(len(frame.columns)),
                "columns": [
                    {"name": column, "dtype": str(frame[column].dtype)}
                    for column in frame.columns
                ],
                "important_columns": list(descriptions),
                "column_descriptions": descriptions,
                "description": description,
            }

        shared_provenance = {
            "source": "analysis:neolabs",
            "abundance_path": str(abundance_meta["path"]),
            "sample_path": str(sample_meta["path"]),
            "method_version": NEOLABS_DEMO_METHOD_VERSION,
        }
        store_dataset(
            _store,
            thread_id,
            abundance,
            variable_name="df_file_neolabs_abundance",
            meta={
                **abundance_meta,
                "source": f"file:{abundance_meta['path']}",
                "method_version": NEOLABS_DEMO_METHOD_VERSION,
                **_schema_metadata(
                    abundance,
                    "Table source NeoLabs au grain taxon × sample × analyse.",
                ),
            },
            set_active=False,
        )
        store_dataset(
            _store,
            thread_id,
            samples,
            variable_name="df_file_neolabs_sample",
            meta={
                **sample_meta,
                "source": f"file:{sample_meta['path']}",
                "method_version": NEOLABS_DEMO_METHOD_VERSION,
                **_schema_metadata(
                    samples,
                    "Table source NeoLabs des samples, déploiements et analyses.",
                ),
            },
            set_active=False,
        )
        for name, frame, description in (
            (
                "df_neolabs_samples",
                tables["samples"],
                "Une ligne par couple sample-analyse avec densité et statut de calcul.",
            ),
            (
                "df_neolabs_coverage",
                tables["coverage"],
                "Couverture groupée des jointures et des densités calculables ou manquantes.",
            ),
            (
                "df_neolabs_graph",
                tables["graph"],
                "Couples calculables avec coordonnées, prêts pour cartes, profils et graphiques.",
            ),
        ):
            store_dataset(
                _store,
                thread_id,
                frame,
                variable_name=name,
                meta={
                    **shared_provenance,
                    **_schema_metadata(frame, description),
                },
                set_active=False,
            )
        working = tables["working"]
        store_dataset(
            _store,
            thread_id,
            working,
            variable_name="df_neolabs_working",
            meta={
                **shared_provenance,
                **_schema_metadata(
                    working,
                    "Jointure externe traçable de toutes les lignes NeoLabs source.",
                ),
            },
            is_loaded_file=True,
        )
        from tools.source_scope import activate_file_source  # noqa: PLC0415

        activate_file_source(
            _store,
            thread_id,
            origin_user_text="NeoLabs abundance + sample",
        )

        join_counts = working["join_status"].value_counts().to_dict()
        sample_summary = tables["samples"]
        pair_join_counts = sample_summary["join_status"].value_counts().to_dict()
        n_matched_pairs = int(pair_join_counts.get("matched", 0))
        n_calculable = int(sample_summary["density_status"].eq("calculated").sum())
        n_missing = int(sample_summary["density_status"].eq("no_value").sum())
        n_not_applicable = int(
            sample_summary["density_status"].eq("not_applicable").sum()
        )
        return success(
            (
                f"Préparation NeoLabs terminée : {len(abundance)} lignes abondance "
                f"et {len(samples)} lignes sample; aucune ligne source écartée.\n"
                f"Jointure des lignes d'abondance : {join_counts.get('matched', 0)} "
                "appariées, "
                f"{join_counts.get('abundance_without_sample', 0)} sans ligne sample.\n"
                f"Couples uniques sample + analyse : {n_matched_pairs} appariés, "
                f"{pair_join_counts.get('abundance_without_sample', 0)} avec abondance "
                "sans sample, "
                f"{pair_join_counts.get('sample_without_abundance', 0)} avec sample "
                "sans abondance.\n"
                f"Densité sur les couples appariés : {n_calculable}/{n_matched_pairs} "
                f"calculable; valeurs manquantes : {n_missing}; "
                f"non appariés (hors dénominateur) : {n_not_applicable}.\n"
                "Définition obligatoire : une ligne appariée vérifie "
                "`join_status == 'matched'`; ne l'infère jamais de la seule "
                "présence d'identifiants non nuls.\n"
                "Tables : `df_neolabs_working`, `df_neolabs_samples`, "
                "`df_neolabs_coverage`, `df_neolabs_graph`."
            ),
            data_ref="df_neolabs_working",
            provenance=shared_provenance,
            persisted=True,
            method=NEOLABS_DEMO_METHOD_VERSION,
            metrics={
                "abundance_rows": int(len(abundance)),
                "sample_rows": int(len(samples)),
                "working_rows": int(len(working)),
                "matched_rows": int(join_counts.get("matched", 0)),
                "matched_pairs": n_matched_pairs,
                "abundance_without_sample_rows": int(
                    join_counts.get("abundance_without_sample", 0)
                ),
                "sample_without_abundance_rows": int(
                    join_counts.get("sample_without_abundance", 0)
                ),
                "calculable": n_calculable,
                "missing": n_missing,
                "density_denominator": n_matched_pairs,
                "not_applicable": n_not_applicable,
            },
        )

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
        variable_name = _file_variable_name(path)

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

        neolabs_abundance = _store.get(
            f"{thread_id}:dataset:df_file_neolabs_abundance"
        )
        neolabs_sample = _store.get(
            f"{thread_id}:dataset:df_file_neolabs_sample"
        )
        if neolabs_abundance is not None and neolabs_sample is not None:
            abundance_meta = neolabs_abundance.get("meta") or {}
            sample_meta = neolabs_sample.get("meta") or {}
            abundance_source_path = abundance_meta.get("path") or str(
                abundance_meta.get("source", "")
            ).removeprefix("file:")
            sample_source_path = sample_meta.get("path") or str(
                sample_meta.get("source", "")
            ).removeprefix("file:")
            route_note += (
                "\nRoute NeoLabs obligatoire : appelle "
                "`prepare_neolabs_analysis` avec "
                f"`abundance_path={abundance_source_path!r}` et "
                f"`sample_path={sample_source_path!r}`. Ne reconstruis pas cette "
                "jointure avec `run_pandas` et ne convertis jamais "
                "`ANALYSIS_ID`/`analysis_id` avec `astype(str)`."
            )

        enc_note = f" (encodage : {meta['encoding']})" if meta.get("encoding") else ""
        live_tables_before_load = len(_store.keys(f"{thread_id}:dataset:"))
        reference_note = (
            f"\nTable à citer dans une prochaine demande : `{variable_name}`"
            if live_tables_before_load > 1 else ""
        )
        summary = (
            f"Fichier chargé : {meta['path']}{enc_note}\n"
            f"{meta['n_rows']} lignes × {meta['n_cols']} colonnes\n"
            f"Nouvelle table disponible : `{variable_name}`\n"
            f"Colonnes : {cols}"
            f"{alias_note}"
            f"{route_note}"
            f"{reference_note}"
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
    def run_pandas(code: str, persist_as: str | None = None) -> str:
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

        Pour conserver explicitement n'importe quel sous-ensemble ou table
        dérivée pour une étape suivante (enrichissement, graphique, export),
        passe `persist_as="df_nom_explicite"`. La table `result` est alors
        persistée exactement sous ce nom. Utilise ensuite ce même nom dans
        `source_variable` de l'outil d'enrichissement ; ne réutilise pas le
        fichier complet par défaut.

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
        if persist_as is not None and not re.fullmatch(r"df_[A-Za-z][A-Za-z0-9_]*", persist_as):
            return blocked(
                "`persist_as` doit être un nom de table Python commençant par `df_` "
                "(ex. `df_subset_28853`).",
                retryable=False,
                method="controlled pandas execution",
            )
        session = _store.get(thread_id)
        if not session or session.get("df") is None:
            return blocked("Aucun fichier chargé. Utilise load_file d'abord.")
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
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.close("all")

            local_vars = _dataframe_vars(_store, thread_id, df)
            local_vars["plt"] = plt
            injected_keys = set(local_vars) | {"__builtins__"}

            guard = _neolabs_join_guard(code, local_vars)
            if guard:
                return blocked(guard, method="controlled pandas execution")

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

            # Persist plot_df so run_graph can access it without recomputing.
            plot_df_val = new_vars.get("plot_df")
            if isinstance(plot_df_val, pd.DataFrame):
                _store.set(f"{thread_id}:last_plot_df", plot_df_val, {"source": "analysis:plot_df"})

            # A join workflow may keep the joined DataFrame in a named
            # intermediate (`joined`, `merged`, or `result_df`) while assigning
            # a compact summary dict to `result`. Persist that named table too;
            # otherwise the next turn cannot reuse the active joined file.
            explicit_variable = None
            if persist_as is not None:
                if not isinstance(result, pd.DataFrame):
                    return blocked(
                        "`persist_as` exige que `result` soit un DataFrame.",
                        retryable=True,
                        method="controlled pandas execution",
                    )
                existing = _store.get(f"{thread_id}:dataset:{persist_as}")
                if existing and isinstance(existing.get("df"), pd.DataFrame):
                    return blocked(
                        f"`persist_as={persist_as}` remplacerait une table déjà "
                        "persistée. Conserve la table source et choisis un nouveau "
                        "nom dérivé (par exemple `df_derived_<nom>`).",
                        retryable=True,
                        method="controlled pandas execution",
                    )
                explicit_variable = persist_as
                store_dataset(
                    _store,
                    thread_id,
                    result,
                    variable_name=explicit_variable,
                    meta={
                        "source": "analysis:explicit-derived",
                        "n_rows": int(result.shape[0]),
                        "n_cols": int(result.shape[1]),
                        "description": f"Table explicitement persistée : {explicit_variable}",
                    },
                    latest_alias=explicit_variable,
                )

            join_variable = None
            join_frame = None
            if not canonical_note and not explicit_variable and _is_join_code(code):
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
            if not canonical_note and not explicit_variable and not join_variable and isinstance(result, pd.DataFrame):
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
                if not printed_output:
                    return blocked(
                        "Calcul non vérifiable : aucune variable `result` n'a été "
                        "assignée, donc aucune valeur exploitable n'a été retournée. "
                        "Inspecte d'abord les colonnes nécessaires, puis assigne le "
                        "calcul vérifié à `result`; ne donne aucune valeur à l'utilisateur "
                        "avant ce résultat.",
                        retryable=True,
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
                    else (explicit_variable or join_variable or derived_variable)
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
                    f"\nVariable persistante : `{explicit_variable}` — table sélectionnée "
                    "réutilisable dans les prochains tours."
                    if explicit_variable
                    else (
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

        _fail_key = f"{thread_id}:run_graph_fail_count"

        def _record_graph_failure() -> int:
            """Increment consecutive-failure counter; return new count."""
            stored = _store.get(_fail_key) or {}
            count = (stored.get("meta") or {}).get("count", 0) + 1
            _store.set(_fail_key, None, {"count": count})
            return count

        def _clear_graph_failure() -> None:
            _store.set(_fail_key, None, {"count": 0})

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            plt.close("all")
            configure_offline_cartopy()
            _patch_cartopy_gridliner_polygon()

            if df is not None:
                local_vars = _dataframe_vars(
                    _store, thread_id, df, _referenced_names(code)
                )
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
                buf = io.BytesIO()
                plt.savefig(buf, **_graph_savefig_kwargs(plt))
                buf.seek(0)
                plt.close("all")
                graph_id = uuid.uuid4().hex[:12]
                (_GRAPHS_DIR / f"{graph_id}.png").write_bytes(buf.read())
                _clear_graph_quality_block(_store, thread_id)
                _clear_graph_failure()
                image_markdown = f"![graph]({graph_url(f'{graph_id}.png')})"

                # Grounded facts for the answer's mandatory `Données` line, so the
                # model reports the real plotted count and encodings instead of
                # fabricating them. Stored in session state (NOT in the returned
                # content, which serve.py streams verbatim to the UI); the next
                # model request injects them into context via the middleware.
                grounding_bits: list[str] = []
                plotted_df = local_vars.get("plot_df")
                if isinstance(plotted_df, pd.DataFrame):
                    # A graph is often refined over several user turns (labels,
                    # colour, contour, filters). Keep the exact rendered rows
                    # under their own stable name.  It must not replace the
                    # active analysis table: a follow-up calculation should
                    # still start from the source/derived table selected before
                    # the visual was rendered.
                    parent_variable = ((session or {}).get("meta") or {}).get(
                        "variable_name"
                    )
                    graph_variable = "df_graph_plot"
                    rendered_df = plotted_df.copy()
                    store_dataset(
                        _store,
                        thread_id,
                        rendered_df,
                        variable_name=graph_variable,
                        meta={
                            "source": "analysis:graph-plot",
                            "parent_variable": parent_variable,
                            "graph_id": graph_id,
                            "n_rows": len(rendered_df),
                            "n_cols": len(rendered_df.columns),
                        },
                        set_active=False,
                    )
                    _store.set(
                        f"{thread_id}:last_plot_df",
                        rendered_df,
                        {
                            "source": "analysis:graph-plot",
                            "variable_name": graph_variable,
                            "graph_id": graph_id,
                        },
                    )
                    grounding_bits.append(f"lignes tracées={len(plotted_df)}")
                    grounding_bits.append(
                        "colonnes utilisées=" + ",".join(map(str, plotted_df.columns))
                    )
                    grounding_bits.append(f"table de rendu={graph_variable}")
                if isinstance(graph_contract, dict):
                    mappings = graph_contract.get("mappings")
                    if isinstance(mappings, dict):
                        encodings = [
                            f"{channel}={spec.get('variable')}"
                            for channel, spec in mappings.items()
                            if isinstance(spec, dict) and spec.get("variable")
                        ]
                        if encodings:
                            grounding_bits.append("encodages=" + "; ".join(encodings))
                _store.set(
                    f"{thread_id}:last_graph_grounding",
                    None,
                    {"facts": " · ".join(grounding_bits)} if grounding_bits else {},
                )
                _store.set(
                    f"{thread_id}:last_graph_state",
                    None,
                    {
                        "code": code,
                        "graph_id": graph_id,
                        "plot_data_ref": (
                            "df_graph_plot"
                            if isinstance(plotted_df, pd.DataFrame)
                            else None
                        ),
                        "graph_contract": graph_contract,
                    },
                )

                # Do not echo graph_explanation / "Lecture rapide": serve.py
                # streams this tool content verbatim to the UI, where it would
                # duplicate and compete with the model's Résultat/Données/Méthode/
                # Limite answer. Return the image only; the model writes the caption.
                return success(
                    image_markdown,
                    data_ref=("df_graph_plot" if isinstance(plotted_df, pd.DataFrame) else None),
                    artifact_refs=(graph_url(f"{graph_id}.png"),),
                    persisted=True,
                    method="controlled matplotlib execution",
                    metrics=(
                        {"rows": len(plotted_df), "columns": len(plotted_df.columns)}
                        if isinstance(plotted_df, pd.DataFrame)
                        else {}
                    ),
                )

            fail_count = _record_graph_failure()
            if fail_count >= 2:
                return error(
                    "run_graph failed twice in a row without producing a figure. "
                    "Stop retrying. Report to the user what data was available, "
                    "what you attempted to plot, and why the graph could not be produced.",
                    retryable=False,
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
            fail_count = _record_graph_failure()
            terminal = fail_count >= 2
            diagnostic_suffix = (
                "\n\nStop retrying. Report to the user what data was available, "
                "what you attempted to plot, and why the graph could not be produced."
                if terminal else ""
            )
            if df is not None:
                return error(
                    f"Error: {type(e).__name__}: {e}\n\n"
                    f"Available columns:\n{df.dtypes.to_string()}{diagnostic_suffix}",
                    retryable=not terminal,
                    method="controlled matplotlib execution",
                )
            return error(
                f"Error: {type(e).__name__}: {e}{diagnostic_suffix}",
                retryable=not terminal,
                method="controlled matplotlib execution",
            )

    return [load_file, prepare_neolabs_analysis, run_pandas, run_graph]
