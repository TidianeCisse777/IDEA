"""Tools LangChain pour l'analyse de données — slice 2."""
import ast
import contextlib
import json
import math
import re
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from cycler import cycler
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command

from agents.exploration_state import IdeaAgentState
from core.environment_resolver.column_detection import (
    DEFAULT_LAT_CANDIDATES,
    DEFAULT_LON_CANDIDATES,
    detect_column,
)
from core.geo import load_registry
from core.runtime_paths import graphs_dir
from tools.domain_profile import detect_domain_profile
from tools.tool_result import blocked, empty, error, success
from tools.persistent_executor import default_executor


_GRAPHS_DIR = graphs_dir()


# Charte visuelle appliquée par l'exécuteur, jamais laissée à la mémoire du LLM.
# Les palettes scientifiques choisies explicitement dans le code (notamment
# cmocean) restent intactes ; cette charte normalise la typographie, le fond et
# les éléments éditoriaux communs à toutes les figures NeoLab.
_NEOLAB_CATEGORICAL_COLORS = (
    "#0072B2",  # blue
    "#D55E00",  # vermilion
    "#009E73",  # green
    "#CC79A7",  # purple
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#6C757D",  # neutral grey
)
_NEOLAB_REPORT_RCPARAMS = {
    "figure.facecolor": "#FFFFFF",
    "axes.facecolor": "#FFFFFF",
    "savefig.facecolor": "#FFFFFF",
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titlesize": 13,
    "axes.titleweight": "semibold",
    "axes.labelsize": 11,
    "axes.labelcolor": "#243447",
    "axes.edgecolor": "#52616B",
    "axes.linewidth": 0.75,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": "#D9E2E8",
    "grid.linewidth": 0.6,
    "grid.alpha": 0.75,
    "xtick.color": "#3E4C59",
    "ytick.color": "#3E4C59",
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "legend.frameon": True,
    "legend.framealpha": 0.94,
    "legend.facecolor": "#FFFFFF",
    "legend.edgecolor": "#C8D2D8",
    "figure.dpi": 150,
    "savefig.dpi": 220,
    "savefig.bbox": "tight",
    "lines.linewidth": 1.8,
    "lines.markersize": 5.0,
}


def _apply_neolab_report_theme(plt: Any) -> None:
    """Install the non-optional NeoLab scientific-report visual baseline."""
    plt.rcParams.update(_NEOLAB_REPORT_RCPARAMS)
    # This cycle applies only when the analysis did not select a semantic
    # colour explicitly. It remains distinct in print and for common colour
    # vision deficiencies, unlike the default red/green pair.
    plt.rcParams["axes.prop_cycle"] = cycler(color=_NEOLAB_CATEGORICAL_COLORS)


def _finalize_neolab_report_figures(plt: Any) -> None:
    """Normalize created figures after agent code without changing their science.

    The model still controls the analytical grain, variables, scales and
    scientific palettes.  This pass makes the publication/report presentation
    deterministic, including figures whose code manually changed rcParams.
    """
    for figure_number in plt.get_fignums():
        figure = plt.figure(figure_number)
        figure.set_facecolor("#FFFFFF")
        for axis in figure.axes:
            is_geoaxes = axis.__class__.__module__.startswith("cartopy.")
            axis.set_facecolor("#EDF5F7" if is_geoaxes else "#FFFFFF")
            axis.tick_params(colors="#3E4C59", labelsize=9, width=0.7)
            axis.xaxis.label.set_color("#243447")
            axis.yaxis.label.set_color("#243447")
            axis.xaxis.label.set_size(11)
            axis.yaxis.label.set_size(11)
            axis.title.set_color("#172B3A")
            axis.title.set_size(13)
            axis.title.set_weight("semibold")
            if not is_geoaxes:
                axis.grid(True, color="#D9E2E8", linewidth=0.6, alpha=0.75)
                for spine_name in ("top", "right"):
                    spine = axis.spines.get(spine_name)
                    if spine is not None:
                        spine.set_visible(False)
                for spine_name in ("bottom", "left"):
                    spine = axis.spines.get(spine_name)
                    if spine is not None:
                        spine.set_color("#52616B")
                        spine.set_linewidth(0.75)
            else:
                # Cartopy keeps its geographic frame.  A restrained blue water
                # background lets observations, coastlines and zone contours
                # carry the visual hierarchy without altering their geometry.
                geo_spine = axis.spines.get("geo")
                if geo_spine is not None:
                    geo_spine.set_color("#52616B")
                    geo_spine.set_linewidth(0.75)
            legend = axis.get_legend()
            if legend is not None:
                frame = legend.get_frame()
                frame.set_facecolor("#FFFFFF")
                frame.set_edgecolor("#C8D2D8")
                frame.set_alpha(0.94)
                frame.set_linewidth(0.7)


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
    # ``None`` and an omitted bbox both fall back to rcParams["savefig.bbox"]
    # in Matplotlib 3.11.  The report theme sets that value to ``tight``;
    # Cartopy can then crop the GeoAxes away and leave only its colorbar.  The
    # figure's original canvas bbox is the explicit, version-stable opt-out.
    return {
        "format": "png",
        "bbox_inches": plt.gcf().bbox_inches,
    } if has_geoaxes else {
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


def _runtime_tool_output(
    output: tuple[Any, dict[str, Any]],
    *,
    runtime: ToolRuntime[None, IdeaAgentState] | None,
    store: SessionStore,
    thread_id: str,
    tool_name: str,
) -> tuple[Any, dict[str, Any]] | ToolMessage | Command:
    """Preserve tool artifacts and atomically publish persisted resources."""
    if runtime is None or runtime.tool_call_id is None:
        return output
    content, artifact = output
    message = ToolMessage(
        content=content,
        artifact=artifact,
        tool_call_id=runtime.tool_call_id,
        name=tool_name,
        status="error" if artifact.get("status") == "error" else "success",
    )
    if not artifact.get("persisted"):
        return message

    from tools.dataframe_cleanup import hidden_dataframes  # noqa: PLC0415
    from tools.resource_inventory import build_resource_inventory  # noqa: PLC0415
    from tools.source_scope import source_decision_for_turn  # noqa: PLC0415

    messages = list(runtime.state.get("messages") or [])
    try:
        authorized_sources = source_decision_for_turn(
            store,
            thread_id,
            messages,
            persist=False,
        ).authorized_sources
    except Exception:
        authorized_sources = ()
    resources = build_resource_inventory(
        store,
        thread_id,
        authorized_sources=authorized_sources,
        excluded_variables=hidden_dataframes(store, thread_id),
    )
    return Command(
        update={
            "messages": [message],
            "exploration": {
                "__resource_patch__": [
                    resource.model_dump(mode="json") for resource in resources
                ]
            },
        }
    )

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
    """Return a compact domain hint for recognized UVP and NeoLabs files.

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
            "Interroge la documentation locale avant tout calcul UVP spécialisé."
        )
    if is_neolabs:
        return (
            "→ Fichier NeoLabs ABONDANCE chargé (1 ligne par taxon×analyse).\n\n"
            + _NEOLABS_ARCHITECTURE
            + "\n\nInspecte d'abord le schéma effectivement chargé. Si la sémantique "
            "d'un champ, d'un stade ou d'une métrique reste inconnue, interroge la "
            "documentation locale ciblée avant de conclure."
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
            "Interroge la documentation locale avant d'interpréter les colonnes ou calculer m5/m6."
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

    ``run_graph`` synchronises only the named DataFrames into its persistent
    worker. This avoids eagerly materialising every historical dataset just to
    draw a figure from a small derived table.
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


def _normalize_abstract_cartopy_crs(code: str) -> str:
    """Repair Cartopy's unusable no-argument CRS constructor.

    ``CRS()`` is an abstract base requiring PROJ parameters, while a plain
    station map has an unambiguous safe default: ``PlateCarree()``. Repair only
    the exact zero-argument misuse; every explicit projection and every CRS
    with parameters remains model-authored code.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    module_aliases: set[str] = set()
    direct_crs_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "cartopy.crs":
                    module_aliases.add(alias.asname or "cartopy")
        elif isinstance(node, ast.ImportFrom) and node.module == "cartopy.crs":
            for alias in node.names:
                if alias.name == "CRS":
                    direct_crs_aliases.add(alias.asname or "CRS")
        elif isinstance(node, ast.ImportFrom) and node.module == "cartopy":
            for alias in node.names:
                if alias.name == "crs":
                    module_aliases.add(alias.asname or "crs")

    replacements: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or node.args or node.keywords:
            continue
        if isinstance(node.func, ast.Name) and node.func.id in direct_crs_aliases:
            replacements.append(ast.get_source_segment(code, node) or "")
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "CRS"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in module_aliases
        ):
            replacements.append(ast.get_source_segment(code, node) or "")

    replacements = [segment for segment in replacements if segment]
    if not replacements:
        return code
    repaired = code
    for segment in set(replacements):
        repaired = repaired.replace(segment, "ccrs.PlateCarree()")
    if not re.search(r"^\s*import\s+cartopy\.crs\s+as\s+ccrs\s*$", repaired, re.MULTILINE):
        repaired = "import cartopy.crs as ccrs\n" + repaired
    return repaired


def _normalize_cartopy_map_projection(code: str, local_vars: dict[str, Any]) -> str:
    """Choose a geographic projection from the plotted coordinates.

    Generated snippets routinely choose ``PlateCarree`` because it is the
    shortest valid Cartopy axis.  It is technically correct, but makes broad
    Arctic panels look flat and makes IHO/MEOW boundaries visually misleading.
    Only the *GeoAxes* projection is normalised here: point and geometry
    transforms remain PlateCarree because their source coordinates are lon/lat.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code

    referenced = _referenced_names(code)
    coordinates: list[tuple[float, float]] = []
    for name, frame in local_vars.items():
        if name not in referenced or not isinstance(frame, pd.DataFrame):
            continue
        columns = _map_coordinate_columns(frame)
        if columns is None:
            continue
        latitude, longitude = columns
        values = pd.DataFrame(
            {
                "lat": pd.to_numeric(frame[latitude], errors="coerce"),
                "lon": pd.to_numeric(frame[longitude], errors="coerce"),
            }
        ).dropna()
        coordinates.extend(
            (float(row.lon), float(row.lat))
            for row in values.itertuples(index=False)
            if -180 <= row.lon <= 180 and -90 <= row.lat <= 90
        )
    if not coordinates:
        return code

    longitudes, latitudes = zip(*coordinates, strict=True)
    # Circular mean avoids making a Chukchi/Bering map centre on Greenwich
    # merely because the source selection crosses the antimeridian.
    sin_mean = sum(math.sin(math.radians(lon)) for lon in longitudes) / len(longitudes)
    cos_mean = sum(math.cos(math.radians(lon)) for lon in longitudes) / len(longitudes)
    central_longitude = math.degrees(math.atan2(sin_mean, cos_mean))
    longitude_offsets = [
        ((lon - central_longitude + 180.0) % 360.0) - 180.0
        for lon in longitudes
    ]
    latitude_span = max(latitudes) - min(latitudes)
    longitude_span = max(longitude_offsets) - min(longitude_offsets)
    central_latitude = (max(latitudes) + min(latitudes)) / 2.0

    if central_latitude >= 60.0 and (latitude_span >= 8.0 or longitude_span >= 28.0):
        projection = f"ccrs.NorthPolarStereo(central_longitude={central_longitude:.3f})"
    elif latitude_span <= 18.0 and longitude_span <= 45.0:
        projection = (
            "ccrs.LambertConformal("
            f"central_longitude={central_longitude:.3f}, "
            f"central_latitude={central_latitude:.3f})"
        )
    else:
        return code

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    line_offsets = [0]
    for line in code.splitlines(keepends=True):
        line_offsets.append(line_offsets[-1] + len(line))
    replacements: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        is_plate_carree = (
            isinstance(node, ast.Call)
            and not node.args
            and not node.keywords
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "PlateCarree"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ccrs"
        )
        if not is_plate_carree:
            continue
        parent = parents.get(node)
        is_projection_keyword = isinstance(parent, ast.keyword) and parent.arg == "projection"
        is_projection_dict_value = (
            isinstance(parent, ast.Dict)
            and any(
                value is node
                and isinstance(key, ast.Constant)
                and key.value == "projection"
                for key, value in zip(parent.keys, parent.values, strict=False)
            )
        )
        if is_projection_keyword or is_projection_dict_value:
            if (
                hasattr(node, "end_lineno")
                and node.end_lineno is not None
                and node.end_col_offset is not None
            ):
                start = line_offsets[node.lineno - 1] + node.col_offset
                end = line_offsets[node.end_lineno - 1] + node.end_col_offset
                replacements.append((start, end))

    if not replacements:
        return code
    normalised = code
    for start, end in sorted(replacements, reverse=True):
        normalised = normalised[:start] + projection + normalised[end:]
    return normalised


def _all_missing_scatter_colour_issue(code: str, local_vars: dict[str, Any]) -> str | None:
    """Reject a scatter whose colour field became entirely missing in ``plot_df``.

    Matplotlib accepts an all-NaN ``c=`` array and can return an apparently blank
    image.  This happens often with cache samples that have positions but no
    object depth.  Inspect the materialised plotting table after execution so
    derived columns such as ``depth_mid`` are covered without guessing.
    """
    plot_df = local_vars.get("plot_df")
    if not isinstance(plot_df, pd.DataFrame):
        return None
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "scatter"
        ):
            continue
        colour = next((item.value for item in node.keywords if item.arg in {"c", "color"}), None)
        if not (
            isinstance(colour, ast.Subscript)
            and isinstance(colour.value, ast.Name)
            and colour.value.id == "plot_df"
            and isinstance(colour.slice, ast.Constant)
            and isinstance(colour.slice.value, str)
        ):
            continue
        column = colour.slice.value
        if column in plot_df.columns and not plot_df[column].notna().any():
            return (
                "Graph blocked: the requested scatter colour field "
                f"`plot_df[{column!r}]` is entirely missing after preparation. "
                "Do not return a blank map: use a fixed colour or choose a real "
                "non-missing field after inspecting `plot_df`."
            )
    return None


_MAP_LATITUDE_CANDIDATES = (*DEFAULT_LAT_CANDIDATES, "lat_avg", "latitude_avg")
_MAP_LONGITUDE_CANDIDATES = (*DEFAULT_LON_CANDIDATES, "lon_avg", "longitude_avg")
_MAP_LATITUDE_MIN_CANDIDATES = ("lat_min", "latitude_min")
_MAP_LATITUDE_MAX_CANDIDATES = ("lat_max", "latitude_max")
_MAP_LONGITUDE_MIN_CANDIDATES = ("lon_min", "longitude_min")
_MAP_LONGITUDE_MAX_CANDIDATES = ("lon_max", "longitude_max")


def _map_coordinate_columns(frame: pd.DataFrame) -> tuple[str, str] | None:
    """Return an explicit latitude/longitude pair, never inferred from values."""
    latitude = detect_column(frame.columns, _MAP_LATITUDE_CANDIDATES)
    longitude = detect_column(frame.columns, _MAP_LONGITUDE_CANDIDATES)
    if latitude is None or longitude is None:
        return None
    return str(latitude), str(longitude)


def _cartopy_coordinate_preflight_issue(
    code: str,
    local_vars: dict[str, Any],
) -> str | None:
    """Explain an impossible map without rejecting derived coordinates."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    uses_cartopy = any(
        (
            isinstance(node, ast.Import)
            and any(
                alias.name == "cartopy" or alias.name.startswith("cartopy.")
                for alias in node.names
            )
        )
        or (
            isinstance(node, ast.ImportFrom)
            and (node.module == "cartopy" or str(node.module or "").startswith("cartopy."))
        )
        or (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "ccrs"
        )
        for node in ast.walk(tree)
    )
    uses_point_layer = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "scatter"
        for node in ast.walk(tree)
    )
    if not uses_cartopy or not uses_point_layer:
        return None

    referenced = _referenced_names(code)
    frames = {
        name: value
        for name, value in local_vars.items()
        if name in referenced and isinstance(value, pd.DataFrame)
    }
    if not frames:
        return None
    if any(_map_coordinate_columns(frame) is not None for frame in frames.values()):
        return None

    referenced_columns = {
        node.value.casefold()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    for frame in frames.values():
        bounds = (
            detect_column(frame.columns, _MAP_LATITUDE_MIN_CANDIDATES),
            detect_column(frame.columns, _MAP_LATITUDE_MAX_CANDIDATES),
            detect_column(frame.columns, _MAP_LONGITUDE_MIN_CANDIDATES),
            detect_column(frame.columns, _MAP_LONGITUDE_MAX_CANDIDATES),
        )
        bounds_are_used = all(
            str(column).casefold() in referenced_columns for column in bounds
        )
        if all(bounds) and bounds_are_used:
            return None

    schemas = "; ".join(
        f"{name}=[{', '.join(map(str, frame.columns))}]"
        for name, frame in frames.items()
    )
    return (
        "Cartopy point map impossible: no usable or safely derivable "
        "latitude/longitude columns were found in the referenced table(s): "
        f"{schemas}. Use a persisted table containing latitude/longitude, or "
        "derive them from verified latitude and longitude bounds before retrying."
    )


def _named_dataset_variables(store: SessionStore, thread_id: str) -> tuple[str, ...]:
    """Return the durable table names that a multi-source operation must name."""
    from tools.dataframe_cleanup import hidden_dataframes

    prefix = f"{thread_id}:dataset:"
    hidden = hidden_dataframes(store, thread_id)
    names = []
    for key in store.keys(prefix):
        entry = store.get(key) or {}
        if not isinstance(entry.get("df"), pd.DataFrame):
            continue
        meta = entry.get("meta") or {}
        variable = str(meta.get("variable_name") or key.removeprefix(prefix))
        if variable not in hidden:
            names.append(variable)
    return tuple(sorted(set(names)))


def _referenced_dataframe_parents(
    code: str,
    local_vars: dict[str, Any],
    persistent_names: tuple[str, ...],
) -> tuple[str, ...]:
    """Return exact persisted DataFrames actually read by pandas code.

    Generic aliases such as ``df`` and ``loaded_file`` are normalized by
    object identity to a durable session variable. Intermediate DataFrames
    created by the code are not eligible parents because they are absent from
    ``persistent_names``.
    """
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return ()
    loaded_names = sorted(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    persistent_frames = {
        name: local_vars.get(name)
        for name in persistent_names
        if isinstance(local_vars.get(name), pd.DataFrame)
    }
    parents: list[str] = []
    for node in loaded_names:
        referenced_name = node.id
        frame = local_vars.get(referenced_name)
        if not isinstance(frame, pd.DataFrame):
            continue
        if referenced_name in persistent_frames:
            canonical_name = referenced_name
        else:
            canonical_name = next(
                (
                    name
                    for name, persisted_frame in persistent_frames.items()
                    if persisted_frame is frame
                ),
                None,
            )
        if canonical_name and canonical_name not in parents:
            parents.append(canonical_name)
    return tuple(parents)


def _clean_dataframe_filters(filters: object) -> dict[str, Any]:
    """Keep only compact JSON-safe filter declarations."""
    if not isinstance(filters, dict):
        return {}
    scalar_types = (str, int, float, bool)
    clean: dict[str, Any] = {}
    for raw_key, value in filters.items():
        key = str(raw_key).strip()[:80]
        if not key:
            continue
        if value is None or isinstance(value, scalar_types):
            clean[key] = value
        elif isinstance(value, (list, tuple)) and all(
            item is None or isinstance(item, scalar_types) for item in value
        ):
            clean[key] = list(value)[:50]
    return clean


def _run_pandas_dataframe_metadata(
    *,
    description: str | None,
    grain: str | None,
    filters: object,
    parent_variables: tuple[str, ...],
    fallback_description: str,
) -> dict[str, Any]:
    """Build metadata shared by every run_pandas persistence path."""
    clean_description = str(description or "").strip()[:500]
    clean_grain = str(grain or "").strip()[:160]
    clean_filters = _clean_dataframe_filters(filters)
    return {
        "description": clean_description or fallback_description,
        **({"grain": clean_grain} if clean_grain else {}),
        **({"filters": clean_filters} if clean_filters else {}),
        **(
            {"parent_variables": list(parent_variables)}
            if parent_variables
            else {}
        ),
    }


def _implicit_df_join_issue(code: str, named_tables: tuple[str, ...]) -> str | None:
    """Require both inputs to a multi-table join to be named explicitly."""
    if len(named_tables) < 2 or "df" not in _referenced_names(code):
        return None
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    uses_df_in_join = any(
        isinstance(node, ast.Call)
        and (
            (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"merge", "join"}
                and any(
                    isinstance(child, ast.Name) and child.id == "df"
                    for child in ast.walk(node)
                )
            )
            or (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "pd"
                and node.func.attr in {"merge", "concat"}
                and any(
                    isinstance(child, ast.Name) and child.id == "df"
                    for child in ast.walk(node)
                )
            )
        )
        for node in ast.walk(tree)
    )
    if not uses_df_in_join:
        return None
    return (
        "Multi-table join blocked: `df` is only a compatibility alias and may "
        "not select a join input when several persisted tables exist. Name both "
        "operands explicitly from: " + ", ".join(f"`{name}`" for name in named_tables) + "."
    )


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
    from tools.dataframe_cleanup import hidden_dataframes

    hidden = hidden_dataframes(store, thread_id)

    def required(name: str) -> bool:
        return required_names is None or name in required_names

    normalized_frames: dict[int, pd.DataFrame] = {}

    def analysis_frame(frame: pd.DataFrame) -> pd.DataFrame:
        """Expose legacy CTD tables with physical columns typed as numeric.

        Older persisted Amundsen enrichments used nullable object columns.  A
        copy is made only for those legacy frames; current enrichments already
        carry the correct dtypes.
        """
        frame_id = id(frame)
        if frame_id in normalized_frames:
            return normalized_frames[frame_id]
        numeric_ctd = (
            "amundsen_distance_km",
            "amundsen_time_delta_min",
            "amundsen_pres_dbar",
            "amundsen_te90_degC",
            "amundsen_psal_psu",
            "amundsen_sigt",
            "amundsen_oxym",
            "amundsen_ph",
            "amundsen_ntra",
            "amundsen_flor",
        )
        needs_normalization = any(
            column in frame.columns and not pd.api.types.is_numeric_dtype(frame[column])
            for column in numeric_ctd
        )
        if needs_normalization:
            from tools.amundsen_sources import coerce_amundsen_numeric_columns

            frame = coerce_amundsen_numeric_columns(frame.copy())
        normalized_frames[frame_id] = frame
        return frame

    local_vars: dict[str, Any] = {"df": analysis_frame(df), "pd": pd}
    if required("loaded_file") or required("loaded_file_variable"):
        loaded = loaded_file_dataset(store, thread_id)
        if loaded and loaded.get("df") is not None:
            # Stable left-hand side for cross-source analysis. This does not
            # replace the active ``df`` after a remote query.
            local_vars["loaded_file"] = analysis_frame(loaded["df"])
            loaded_variable = (loaded.get("meta") or {}).get("variable_name")
            if loaded_variable:
                local_vars["loaded_file_variable"] = loaded_variable
    for alias in SOURCE_ALIASES:
        variable_name = source_variable(alias)
        if not required(variable_name):
            continue
        named = store.get(f"{thread_id}:{alias}")
        if named and named.get("df") is not None:
            local_vars[variable_name] = analysis_frame(named["df"])

    for key in store.keys(f"{thread_id}:dataset:"):
        variable_name = key.removeprefix(f"{thread_id}:dataset:")
        if variable_name in hidden or not required(variable_name):
            continue
        named = store.get(key)
        persisted_name = (named or {}).get("meta", {}).get("variable_name")
        if persisted_name and named.get("df") is not None:
            local_vars[persisted_name] = analysis_frame(named["df"])

    for key in store.keys(f"{thread_id}:ecopart:"):
        project_id = key.rsplit(":", 1)[-1]
        variable_name = f"df_ecopart_{project_id}"
        if not required(variable_name):
            continue
        named = store.get(key)
        if project_id.isdigit() and named and named.get("df") is not None:
            local_vars.setdefault(variable_name, analysis_frame(named["df"]))

    if required("plot_df"):
        last_plot = store.get(f"{thread_id}:last_plot_df")
        plot_variable = str(((last_plot or {}).get("meta") or {}).get("variable_name") or "")
        if plot_variable not in hidden and last_plot and last_plot.get("df") is not None:
            local_vars.setdefault("plot_df", analysis_frame(last_plot["df"]))

    return local_vars


def _zone_geometry_vars(zone_names: set[str] | None = None) -> dict[str, Any]:
    """Expose the registered zone geometries to graph code without serialising WKT.

    Zone polygons are local, trusted registry data. Keeping them out of the
    model-visible tool result avoids sending hundreds of KB of WKT through the
    context while allowing ``run_graph`` to draw the exact registered outlines.
    A literal zone reference lets the worker materialise only that geometry;
    dynamic code falls back to the full registry for correctness.
    """
    registry_path = (
        Path(__file__).parent.parent / "data" / "geo" / "zones_registry.geojson"
    )
    if zone_names:
        from shapely.geometry import shape

        raw = json.loads(registry_path.read_text(encoding="utf-8"))
        selected = [
            feature
            for feature in raw["features"]
            if feature.get("properties", {}).get("canonical") in zone_names
        ]
        return {
            "zone_polygons": {
                feature["properties"]["canonical"]: shape(feature["geometry"])
                for feature in selected
            },
            "zone_sources": {
                feature["properties"]["canonical"]: feature["properties"]["source"]
                for feature in selected
            },
        }

    registry = load_registry(registry_path)
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


_CANONICAL_COLUMN_ALIASES = {
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


def _column_dependency_details(
    missing: str,
    local_vars: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    targets = _CANONICAL_COLUMN_ALIASES.get(missing.casefold(), (missing,))
    target = next(
        (
            candidate
            for candidate in targets
            if any(
                isinstance(value, pd.DataFrame) and candidate in value.columns
                for value in local_vars.values()
            )
        ),
        targets[0],
    )
    holders = tuple(
        sorted(
            name
            for name, value in local_vars.items()
            if isinstance(value, pd.DataFrame) and target in value.columns
        )
    )
    return target, holders


def _column_location_hint(error: Exception, local_vars: dict[str, Any]) -> str:
    """When a column is missing from the active df, name the df_* variables that
    do carry it — so the agent retargets instead of concluding it is absent."""
    missing = _missing_column_name(error)
    if not missing:
        return ""
    target, holders = _column_dependency_details(missing, local_vars)
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


_UNDEFINED_NAME_PATTERN = re.compile(
    r"NameError:.*?name [\"'](?P<name>[A-Za-z_][A-Za-z0-9_]*)[\"'] is not defined",
    re.IGNORECASE | re.DOTALL,
)
_KEY_ERROR_PATTERN = re.compile(
    r"KeyError:\s*[\"'](?P<name>[^\"']+)[\"']",
    re.IGNORECASE,
)
_UNDEFINED_COLUMN_PATTERN = re.compile(
    r"UndefinedVariableError:.*?name [\"'](?P<name>[^\"']+)[\"'] is not defined",
    re.IGNORECASE | re.DOTALL,
)
_DATAFRAME_ATTRIBUTE_PATTERN = re.compile(
    r"DataFrame[\"']? object has no attribute [\"'](?P<name>[A-Za-z_][A-Za-z0-9_]*)[\"']",
    re.IGNORECASE,
)
_TABLEISH_NAME_PATTERN = re.compile(
    r"(^df_|_df$|cache|table|samples?|projects?|profiles?|objects?)",
    re.IGNORECASE,
)


def _missing_column_name(error: Exception) -> str:
    if isinstance(error, KeyError) and error.args:
        return str(error.args[0]).strip("'\"")
    rendered = str(error)
    for pattern in (
        _KEY_ERROR_PATTERN,
        _UNDEFINED_COLUMN_PATTERN,
        _DATAFRAME_ATTRIBUTE_PATTERN,
    ):
        match = pattern.search(rendered)
        if match:
            return match.group("name").strip()
    return ""


def _source_family(source: object, missing_name: str = "") -> str | None:
    normalized = str(source or "").casefold().replace("-", "_")
    if "cache" in missing_name.casefold() and any(
        token in missing_name.casefold()
        for token in ("sample", "project", "profile", "object", "sync")
    ):
        return "ecotaxa"
    for family in ("ecotaxa", "ecopart", "amundsen", "bio_oracle", "ogsl", "sql"):
        if family in normalized:
            return family
    if normalized.startswith("file"):
        return "file"
    return None


def _recovery_tools_for_source(source: str | None) -> tuple[str, ...]:
    return {
        "ecotaxa": (
            "list_ecotaxa_cache_tables",
            "describe_ecotaxa_cache_table",
            "query_ecotaxa_cache",
        ),
        "sql": ("list_sql_tables", "preview_sql_table", "copy_sql_query_to_workspace"),
        "ecopart": ("find_ecopart_project_for_ecotaxa", "preview_ecopart_sample"),
        "amundsen": ("find_amundsen_data_for_table", "enrich_with_amundsen_ctd"),
        "bio_oracle": ("enrich_with_bio_oracle",),
        "ogsl": ("enrich_with_ogsl",),
    }.get(source, ())


def _data_dependency_recovery(
    error: Exception,
    local_vars: dict[str, Any],
    active_source: object,
    store: SessionStore,
    thread_id: str,
) -> dict[str, Any]:
    """Normalize a missing table/column into a resumable data requirement."""
    rendered = str(error)
    missing_column = _missing_column_name(error)
    undefined = _UNDEFINED_NAME_PATTERN.search(rendered)
    missing_table = undefined.group("name") if undefined else ""
    if missing_table and not _TABLEISH_NAME_PATTERN.search(missing_table):
        missing_table = ""
    if not missing_column and not missing_table:
        return {}
    kind = "column" if missing_column else "table"
    missing_name = missing_column or missing_table
    canonical_name = missing_name
    holders: tuple[str, ...] = ()
    if kind == "column":
        canonical_name, holders = _column_dependency_details(missing_name, local_vars)
        persisted_holders = list(holders)
        for key in store.keys():
            if key != thread_id and not key.startswith(f"{thread_id}:"):
                continue
            entry = store.get(key) or {}
            dataframe = entry.get("df")
            if not isinstance(dataframe, pd.DataFrame) or canonical_name not in dataframe.columns:
                continue
            meta = entry.get("meta") or {}
            persisted_holders.append(
                str(meta.get("variable_name") or key.rsplit(":", 1)[-1])
            )
        holders = tuple(dict.fromkeys(persisted_holders))
    source = _source_family(active_source, missing_name)
    if source in {None, "file"}:
        session_sources = {
            family
            for key in store.keys()
            if key == thread_id or key.startswith(f"{thread_id}:")
            for entry in (store.get(key) or {},)
            for family in (_source_family((entry.get("meta") or {}).get("source")),)
            if family not in {None, "file"}
        }
        if len(session_sources) == 1:
            source = next(iter(session_sources))
    recovery_tools = _recovery_tools_for_source(source)
    # A plain local-file column that exists nowhere in the workspace cannot be
    # autonomously recovered. Keep ordinary code repair semantics in that case.
    if not holders and source in {None, "file"}:
        return {}
    return {
        "dependency_recovery": True,
        "missing_names": [missing_name],
        "recovery_source": source,
        "recovery_tools": list(recovery_tools),
        "dependency_requirement": {
            "kind": kind,
            "name": missing_name,
            "canonical_name": canonical_name,
            "source_hint": source,
            "candidate_resources": list(holders),
            "diagnostic": rendered[:2_000],
            "description": (
                f"La colonne `{missing_name}` est nécessaire pour reprendre l'analyse."
                if kind == "column"
                else f"La table `{missing_name}` est nécessaire pour reprendre l'analyse."
            ),
        },
    }


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
        "contre '2185.0' et détruit tous les appariements. Conserve les clés "
        "numériques, normalise-les au besoin avec `pd.to_numeric`, puis joins "
        "sur les deux clés sample + analyse."
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
    profile = (meta.get("domain_profile") or {}).get("name")
    profile_note = "\nProfil biologique : larves de poissons." if profile == "fish_larvae" else ""
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
        f"{alias_note}{reference_note}{profile_note}",
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


    def _load_file_result(path: str):
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
        domain = detect_domain_profile(col_names)
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
            meta={
                **meta,
                "source": f"file:{meta['path']}",
                "description": file_description,
                "domain_profile": domain.as_metadata(),
            },
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
        domain_note = ""
        if domain.domain == "fish_larvae":
            domain_note = (
                "\nProfil biologique : larves de poissons. Colonnes utiles : "
                "taxon, stade larvaire, trait/filet, volume et abondance."
            )
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

        neolabs_abundance = _store.get(f"{thread_id}:dataset:df_file_neolabs_abundance")
        neolabs_sample = _store.get(f"{thread_id}:dataset:df_file_neolabs_sample")
        if neolabs_abundance is not None and neolabs_sample is not None:
            route_note += (
                "\nTables NeoLabs abundance et sample disponibles : utilise "
                "`run_pandas`, normalise les clés numériquement si nécessaire, "
                "puis joins `SAMPLE_ID` + `ANALYSIS_ID` avec `sample_id` + "
                "`analysis_id`."
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
            f"{domain_note}"
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

    @tool(
        description=_load_file_result.__doc__,
        extras={"command_result_schema": "tool_result_v1"},
    )
    def load_file(
        path: str,
        runtime: ToolRuntime[None, IdeaAgentState] = None,
    ):
        return _runtime_tool_output(
            _load_file_result(path),
            runtime=runtime,
            store=_store,
            thread_id=thread_id,
            tool_name="load_file",
        )

    def _run_pandas_result(
        code: str,
        persist_as: str | None = None,
        description: str | None = None,
        grain: str | None = None,
        filters: dict[str, Any] | None = None,
    ):
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
          simultanément réutilisables par leur nom exact dans AVAILABLE DATAFRAMES
        - `df_ecotaxa_cache_query`: alias de la dernière requête cache EcoTaxa

        Pour comparer un fichier et EcoTaxa, utilise `loaded_file` ou le
        `df_file_*` correspondant comme table de gauche et
        `df_ecotaxa_cache_query` comme table de droite. Le `df` actif peut être
        le résultat EcoTaxa et ne remplace jamais `loaded_file`.

        Assigne le résultat à la variable `result`. Les sorties `print(...)`
        exécutées dans le même appel sont également capturées et renvoyées,
        afin qu'un tableau de contrôle préparé explicitement ne soit pas perdu.
        Pour une jointure : result = df_ecotaxa.merge(df_ctd, on='station_id', how='left')

        Pour qualifier un DataFrame candidat avant un calcul, une analyse ou un
        graphique, fais un appel de contrôle ciblé avant l'opération finale.
        Référence le nom `df_*` exact et assigne à `result` un petit dictionnaire
        contenant : `candidate`, `rows`, `missing_required_columns`, preuve de
        cardinalité/doublons des clés, nullité des colonnes pertinentes, preuve
        de portée et `qualified`. N'utilise ni `print`, ni `persist_as`, ni
        calcul scientifique, ni graphique dans cet appel. Attends son résultat
        avant de poursuivre le plan. Une qualification inchangée déjà réussie
        pour la même demande doit être réutilisée.

        Pour conserver explicitement n'importe quel sous-ensemble ou table
        dérivée pour une étape suivante (enrichissement, graphique, export),
        passe `persist_as="df_nom_explicite"`. La table `result` est alors
        persistée exactement sous ce nom. Utilise ensuite ce même nom dans
        `source_variable` de l'outil d'enrichissement ; ne réutilise pas le
        fichier complet par défaut.

        Quand le code crée un DataFrame persistant, renseigne toujours :
        - `description` : phrase courte distinguant la table par ses sources,
          sa transformation, son rôle et ses familles de colonnes utiles ;
        - `grain` : unité exacte représentée par une ligne ;
        - `filters` : objet JSON des filtres réellement appliqués par le code.
        La lignée est détectée automatiquement depuis les DataFrames réellement
        référencés : ne l'invente pas dans ces arguments.

        The controlled worker persists variables computed in this conversation
        (e.g. `station_stats`, `delta_df`) so a following graph can reuse them.
        Durable/reusable results still need an explicit table name: after a
        restart, only the persisted tables below are restored automatically.
        Exceptions persisted automatically and reusable by their exact name in
        later turns:
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
            synthetic_record_guard = _synthetic_record_table_guard(code)
            if synthetic_record_guard:
                return blocked(
                    synthetic_record_guard,
                    retryable=True,
                    method="data lineage validation",
                )
            local_vars = _dataframe_vars(_store, thread_id, df)
            injected_keys = set(local_vars) | {"__builtins__"}
            dataframe_parents = _referenced_dataframe_parents(
                code,
                local_vars,
                _named_dataset_variables(_store, thread_id),
            )

            implicit_join_issue = _implicit_df_join_issue(
                code, _named_dataset_variables(_store, thread_id)
            )
            if implicit_join_issue:
                return blocked(implicit_join_issue, method="explicit dataframe selection")

            guard = _neolabs_join_guard(code, local_vars)
            if guard:
                return blocked(guard, method="controlled pandas execution")

            guard = _neolabs_copepod_guard(code, local_vars)
            if guard:
                return blocked(guard, method="controlled pandas execution")

            execution = default_executor.execute(
                thread_id, "pandas", code, local_vars
            )
            if execution.error:
                raise RuntimeError(execution.error)
            printed_output = execution.stdout
            local_vars.update(execution.dataframes or {})
            if execution.result_available:
                local_vars["result"] = execution.result

            if execution.produced_figure:
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
                        **_run_pandas_dataframe_metadata(
                            description=description,
                            grain=grain,
                            filters=filters,
                            parent_variables=dataframe_parents,
                            fallback_description=(
                                f"Table explicitement persistée : {explicit_variable}"
                            ),
                        ),
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
                        **_run_pandas_dataframe_metadata(
                            description=description,
                            grain=grain,
                            filters=filters,
                            parent_variables=dataframe_parents,
                            fallback_description=_describe_join(code, join_frame),
                        ),
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
                            **_run_pandas_dataframe_metadata(
                                description=description,
                                grain=grain,
                                filters=filters,
                                parent_variables=dataframe_parents,
                                fallback_description=(
                                    derived_description
                                    or f"Table dérivée nommée {derived_name}"
                                ),
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
                # A wide result (for example one CTD statistic per variable and
                # depth bin) used to render every column as Markdown.  That
                # pushed the code's explicit diagnostic prints past the model
                # tool-result cap, which made a successful inspection look like
                # missing data.  Keep the evidence-first output compact.
                preview_column_limit = 20
                preview_frame = result.head(20)
                preview_note = ""
                if n_cols > preview_column_limit:
                    preview_frame = preview_frame.iloc[:, :preview_column_limit]
                    preview_note = (
                        f"\nAperçu limité aux {preview_column_limit} premières colonnes sur "
                        f"{n_cols}; utilise une inspection ciblée pour les autres."
                    )
                preview = preview_frame.to_markdown(index=False)
                suffix = " (aperçu 20 premières lignes)" if n_rows > 20 else ""

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
                )
                if printed_output:
                    summary += "\n\nSortie contrôlée du code :\n" + printed_output
                summary += "\n\nAperçu du résultat :\n" + preview + preview_note
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
            active_source = ((session or {}).get("meta") or {}).get("source")
            recovery_metrics = _data_dependency_recovery(
                e,
                local_vars,
                active_source,
                _store,
                thread_id,
            )
            recovery_hint = (
                "\nUne dépendance de données récupérable a été enregistrée. "
                "Inspecte les ressources disponibles ou récupère la table/colonne "
                "depuis la source autorisée, puis reprends cette analyse."
                if recovery_metrics else ""
            )
            return error(
                f"Erreur : {type(e).__name__}: {e}{hint}"
                f"\n\nColonnes disponibles :\n{cols_info}{recovery_hint}",
                retryable=True,
                method="controlled pandas execution",
                metrics=recovery_metrics,
            )

    @tool(
        description=_run_pandas_result.__doc__,
        extras={"command_result_schema": "tool_result_v1"},
    )
    def run_pandas(
        code: str,
        persist_as: str | None = None,
        description: str | None = None,
        grain: str | None = None,
        filters: dict[str, Any] | None = None,
        runtime: ToolRuntime[None, IdeaAgentState] = None,
    ):
        return _runtime_tool_output(
            _run_pandas_result(code, persist_as, description, grain, filters),
            runtime=runtime,
            store=_store,
            thread_id=thread_id,
            tool_name="run_pandas",
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
        In the same live conversation, named DataFrame intermediates created
        by `run_pandas` (for example `plot_df` or `station_stats`) remain
        available. Persisted `loaded_file`, `df_file_*`, `df_derived_*` and
        named source selections are also available by their exact names; after
        a worker restart, rely on those persisted names rather than a transient
        intermediate. `pd` and `plt` are preloaded; Cartopy/scientific imports
        allowed by the prompt can be imported normally.
        When code explicitly references `zone_polygons` or `zone_sources`, they
        are supplied as trusted local Shapely geometries from the IHO/NeoLab/
        MEOW registry, keyed by canonical zone name. For an IHO/MEOW zone map,
        draw the represented `zone_polygons` with Cartopy `ShapelyFeature`.
        They are loaded only for that call, not serialised in the session
        capsule. Do not claim that a zone contour is unavailable unless a direct
        lookup in `zone_polygons` actually fails.
        Write complete matplotlib code using the compact graph contract already
        active in the session. Server-side validation enforces provenance,
        uncertainty markers, readable output and map/profile safety.
        Do NOT call plt.show() or plt.savefig().

        The return value is the graph image — include it verbatim in your response.
        Standalone figures work without a file only for boundary-only maps. A
        map of samples must use an exact persisted named DataFrame; do not rely
        on bare `df` when the request concerns a source selection.
        """
        session = _store.get(thread_id)
        df = session.get("df") if session else None
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
            effective_code = _normalize_abstract_cartopy_crs(code)
            if df is not None:
                local_vars = _dataframe_vars(
                    _store, thread_id, df, _referenced_names(effective_code)
                )
            else:
                local_vars = {}
            effective_code = _normalize_cartopy_map_projection(
                effective_code, local_vars
            )
            coordinate_issue = _cartopy_coordinate_preflight_issue(
                effective_code, local_vars
            )
            if coordinate_issue:
                return error(
                    coordinate_issue,
                    retryable=True,
                    method="cartography coordinate preflight",
                )
            execution = default_executor.execute(
                thread_id, "graph", effective_code, local_vars
            )
            if execution.error:
                raise RuntimeError(execution.error)
            local_vars.update(execution.dataframes or {})

            missing_colour = _all_missing_scatter_colour_issue(
                effective_code, local_vars
            )
            if missing_colour:
                return error(
                    missing_colour,
                    retryable=True,
                    method="graph encoding preflight",
                )

            if execution.image_png:
                graph_contract = execution.graph_contract
                graph_id = uuid.uuid4().hex[:12]
                (_GRAPHS_DIR / f"{graph_id}.png").write_bytes(execution.image_png)
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
                        "code": effective_code,
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

    return [load_file, run_pandas, run_graph]
