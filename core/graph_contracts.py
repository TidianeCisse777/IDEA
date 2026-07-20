"""Validation pure des contrats déclarés par les graphiques matplotlib."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np


_REQUIRED_FIELDS = {
    "kind",
    "axes",
    "inverted_axes",
    "mappings",
    "zero_policy",
    "source_variables",
}
_ALLOWED_KINDS = {
    "generic",
    "vertical_profile",
    "environment_relationships",
    "temperature_salinity",
    "abundance_environment_map",
    "station_map",
}
# Common chart-type aliases the LLM may emit — all treated as "generic".
_GENERIC_ALIASES = {
    "bar",
    "bar_chart",
    "line",
    "line_chart",
    "scatter",
    "scatter_plot",
    "heatmap",
    "time_series",
    "histogram",
    "boxplot",
    "pie",
    "area",
    "bubble",
}
_ABUNDANCE_ROLES = {"abundance_ind_L", "abundance_ind_m3"}


def _blocked(message: str) -> str:
    return f"graph contract blocked: {message}"


def _declared_inversions(contract: dict) -> set[tuple[int, str]] | str:
    declared: set[tuple[int, str]] = set()
    for item in contract["inverted_axes"]:
        if not isinstance(item, dict):
            return _blocked("inverted_axes entries must be objects")
        axis_index = item.get("axis_index")
        axis_name = item.get("axis")
        if not isinstance(axis_index, int) or axis_name not in {"x", "y"}:
            return _blocked("inverted_axes entries require axis_index and axis x/y")
        declared.add((axis_index, axis_name))
    return declared


def _artist_by_gid(figure: Any, gid: str | None) -> Any | None:
    if not gid:
        return None
    for artist in figure.findobj():
        getter = getattr(artist, "get_gid", None)
        if getter is not None and getter() == gid:
            return artist
    return None


def _mapping_issue(contract: dict, figure: Any, name: str) -> str | None:
    mapping = contract["mappings"].get(name)
    if not isinstance(mapping, dict) or not mapping.get("variable"):
        return _blocked(f"{name} mapping is missing")
    if _artist_by_gid(figure, mapping.get("artist_gid")) is None:
        return _blocked(f"{name} mapping artist is missing")
    return None


def normalize_graph_contract(contract: dict | None, figure: Any) -> dict | None:
    """Bind deterministic station-map mappings to the primary scatter artist."""
    if not isinstance(contract, dict) or contract.get("kind") != "station_map":
        return contract
    normalized = deepcopy(contract)
    axes = normalized.get("axes")
    if not isinstance(axes, list) or len(axes) != 1:
        return normalized
    axis_index = axes[0].get("axis_index") if isinstance(axes[0], dict) else None
    if not isinstance(axis_index, int) or not 0 <= axis_index < len(figure.axes):
        return normalized

    primary = None
    for artist in getattr(figure.axes[axis_index], "collections", []):
        get_offsets = getattr(artist, "get_offsets", None)
        if get_offsets is not None and len(get_offsets()) > 0:
            primary = artist
            break
    if primary is None:
        return normalized

    gid = getattr(primary, "get_gid", lambda: None)() or "station_map_points"
    primary.set_gid(gid)
    mappings = normalized.setdefault("mappings", {})
    position = mappings.get("position")
    if (
        not isinstance(position, dict)
        or position.get("variable") != "longitude_latitude"
        or _artist_by_gid(figure, position.get("artist_gid")) is None
    ):
        mappings["position"] = {
            "variable": "longitude_latitude",
            "artist_gid": gid,
        }
    for name in ("size", "color"):
        mapping = mappings.get(name)
        if (
            isinstance(mapping, dict)
            and mapping.get("variable")
            and _artist_by_gid(figure, mapping.get("artist_gid")) is None
        ):
            mapping["artist_gid"] = gid
    color_mapping = mappings.get("color")
    if isinstance(color_mapping, dict) and color_mapping.get("variable"):
        color_legend = mappings.get("color_legend")
        legend_gid = (
            color_legend.get("artist_gid")
            if isinstance(color_legend, dict) and color_legend.get("artist_gid")
            else "station_color_legend"
        )
        if _artist_by_gid(figure, legend_gid) is None:
            for axis in getattr(figure, "axes", []):
                legend = getattr(axis, "get_legend", lambda: None)()
                if legend is not None:
                    legend.set_gid(legend_gid)
                    break
        if _artist_by_gid(figure, legend_gid) is not None and (
            not isinstance(color_legend, dict) or not color_legend.get("variable")
        ):
            mappings["color_legend"] = {
                "variable": color_mapping["variable"],
                "artist_gid": legend_gid,
            }
    return normalized


def validate_graph_contract(contract: dict | None, figure: Any) -> str | None:
    """Retourne un refus précis, ou ``None`` si la figure respecte le contrat."""
    if contract is None:
        return _blocked("graph_contract is missing")
    if not isinstance(contract, dict):
        return _blocked("graph_contract must be an object")
    missing = sorted(_REQUIRED_FIELDS.difference(contract))
    if missing:
        return _blocked("missing fields: " + ", ".join(missing))
    if contract["kind"] in _GENERIC_ALIASES:
        contract = {**contract, "kind": "generic"}
    if contract["kind"] not in _ALLOWED_KINDS:
        return _blocked(f"unsupported kind: {contract['kind']}")
    if not isinstance(contract["axes"], list) or not contract["axes"]:
        return _blocked("axes must contain at least one data axis")
    if not isinstance(contract["source_variables"], list):
        return _blocked("source_variables must be a list")

    declared = _declared_inversions(contract)
    if isinstance(declared, str):
        return declared

    is_generic = contract["kind"] == "generic"
    axes_by_index: dict[int, dict] = {}
    for axis_contract in contract["axes"]:
        if not isinstance(axis_contract, dict):
            return _blocked("axes entries must be objects")
        axis_index = axis_contract.get("axis_index")
        if not isinstance(axis_index, int) or axis_index < 0:
            return _blocked("axes entries require a non-negative axis_index")
        # Clamp out-of-range axis_index to last available axis rather than blocking.
        if axis_index >= len(figure.axes):
            axis_index = len(figure.axes) - 1
            axis_contract = {**axis_contract, "axis_index": axis_index}
        # For generic charts y is optional (histograms, distribution plots, …).
        if not axis_contract.get("x"):
            if not is_generic:
                return _blocked("axes entries require x and y roles")
        elif not axis_contract.get("y") and not is_generic:
            return _blocked("axes entries require x and y roles")
        axes_by_index[axis_index] = axis_contract

    if contract["kind"] == "vertical_profile":
        if len(axes_by_index) != 1:
            return _blocked("vertical profile requires exactly one data axis")
        axis_index, axis_contract = next(iter(axes_by_index.items()))
        if axis_contract["x"] not in _ABUNDANCE_ROLES:
            return _blocked("vertical profile x-axis must be abundance_ind_L or abundance_ind_m3")
        if axis_contract["y"] != "depth_m":
            return _blocked("vertical profile y-axis must be depth_m")
        if figure.axes[axis_index].xaxis_inverted():
            return _blocked("abundance x-axis must remain normal")
        if declared.difference({(axis_index, "y")}):
            return _blocked("only the depth y-axis may be inverted")

    if contract["kind"] == "environment_relationships":
        panel_indexes = list(axes_by_index)
        for position, left_index in enumerate(panel_indexes):
            left = figure.axes[left_index]
            for right_index in panel_indexes[position + 1:]:
                right = figure.axes[right_index]
                if (
                    left.get_shared_x_axes().joined(left, right)
                    or left.get_shared_y_axes().joined(left, right)
                ):
                    return _blocked("environmental panels must use independent axes")
        for axis_index, axis_contract in axes_by_index.items():
            axis = figure.axes[axis_index]
            if (
                axis_contract.get("x") in _ABUNDANCE_ROLES and axis.xaxis_inverted()
            ) or (
                axis_contract.get("y") in _ABUNDANCE_ROLES and axis.yaxis_inverted()
            ):
                return _blocked("abundance axes must remain normal")

    if contract["kind"] == "temperature_salinity":
        if len(axes_by_index) != 1:
            return _blocked("temperature-salinity diagram requires exactly one data axis")
        _, axis_contract = next(iter(axes_by_index.items()))
        if axis_contract["x"] != "salinity" or axis_contract["y"] != "temperature":
            return _blocked("temperature-salinity axes must be salinity x temperature")
        expected_variables = {
            "size": "abundance_ind_L",
            "color": "depth_m",
            "station": "station",
        }
        for name, expected_variable in expected_variables.items():
            issue = _mapping_issue(contract, figure, name)
            if issue:
                return issue
            if contract["mappings"][name]["variable"] != expected_variable:
                return _blocked(f"{name} mapping must use {expected_variable}")
        zero_policy = contract["zero_policy"]
        # Only enforce hollow-marker check when an artist_gid is declared.
        if zero_policy.get("mode") == "hollow" and zero_policy.get("artist_gid"):
            zero_artist = _artist_by_gid(figure, zero_policy["artist_gid"])
            if zero_artist is not None:
                get_facecolors = getattr(zero_artist, "get_facecolors", None)
                if get_facecolors is not None:
                    facecolors = np.asarray(get_facecolors())
                    is_hollow = facecolors.size == 0 or (
                        facecolors.ndim == 2
                        and facecolors.shape[1] >= 4
                        and bool(np.all(facecolors[:, 3] == 0))
                    )
                    if not is_hollow:
                        return _blocked("zero abundance must use hollow markers")

    if contract["kind"] == "station_map":
        if len(axes_by_index) != 1:
            return _blocked("station map requires exactly one data axis")
        axis_index, axis_contract = next(iter(axes_by_index.items()))
        axis = figure.axes[axis_index]
        if not axis.__class__.__module__.startswith("cartopy."):
            return _blocked("station map requires a Cartopy GeoAxes")
        if axis_contract["x"] != "longitude" or axis_contract["y"] != "latitude":
            return _blocked("station map axes must be longitude x latitude")
        issue = _mapping_issue(contract, figure, "position")
        if issue:
            return issue
        if contract["mappings"]["position"]["variable"] != "longitude_latitude":
            return _blocked("position mapping must use longitude_latitude")
        # size/color are optional and map to any variable (sample_count,
        # n_taxa, richness, …) — a station map must never be forced to invent
        # an abundance_ind_L column just to pass validation. When an encoding
        # legend is present it must describe its own encoding.
        mappings = contract["mappings"]
        for encoding, legend in (("size", "size_legend"), ("color", "color_legend")):
            encoding_map = mappings.get(encoding)
            if not (isinstance(encoding_map, dict) and encoding_map.get("variable")):
                continue
            issue = _mapping_issue(contract, figure, encoding)
            if issue:
                return issue
            legend_map = mappings.get(legend)
            if isinstance(legend_map, dict) and legend_map.get("variable"):
                issue = _mapping_issue(contract, figure, legend)
                if issue:
                    return issue
                if legend_map["variable"] != encoding_map["variable"]:
                    return _blocked(f"{legend} must describe the {encoding} mapping")

    if contract["kind"] == "abundance_environment_map":
        if len(axes_by_index) != 1:
            return _blocked("geographic map requires exactly one data axis")
        axis_index, axis_contract = next(iter(axes_by_index.items()))
        axis = figure.axes[axis_index]
        if not axis.__class__.__module__.startswith("cartopy."):
            return _blocked("geographic map requires a Cartopy GeoAxes")
        if axis_contract["x"] != "longitude" or axis_contract["y"] != "latitude":
            return _blocked("geographic map axes must be longitude x latitude")
        required_mappings = {
            "position": "longitude_latitude",
            "size": "abundance_ind_L",
        }
        for name, expected_variable in required_mappings.items():
            issue = _mapping_issue(contract, figure, name)
            if issue:
                return issue
            if contract["mappings"][name]["variable"] != expected_variable:
                return _blocked(f"{name} mapping must use {expected_variable}")
        # color, size_legend, color_legend are optional — only validate when declared.
        mappings = contract["mappings"]
        color_map = mappings.get("color")
        if isinstance(color_map, dict) and color_map.get("variable"):
            issue = _mapping_issue(contract, figure, "color")
            if issue:
                return issue
            color_legend = mappings.get("color_legend")
            if isinstance(color_legend, dict) and color_legend.get("variable"):
                issue = _mapping_issue(contract, figure, "color_legend")
                if issue:
                    return issue
                if color_legend["variable"] != color_map["variable"]:
                    return _blocked("environment color legend must describe the color mapping")
        size_legend = mappings.get("size_legend")
        if isinstance(size_legend, dict) and size_legend.get("variable"):
            issue = _mapping_issue(contract, figure, "size_legend")
            if issue:
                return issue
            if size_legend["variable"] != "abundance_ind_L":
                return _blocked("size legend must describe abundance_ind_L")

    for axis_index in axes_by_index:
        axis = figure.axes[axis_index]
        for axis_name, observed in (
            ("x", axis.xaxis_inverted()),
            ("y", axis.yaxis_inverted()),
        ):
            expected = (axis_index, axis_name) in declared
            if bool(observed) != expected:
                return _blocked(
                    f"axis {axis_index} {axis_name} inversion differs from graph_contract"
                )
    return None
