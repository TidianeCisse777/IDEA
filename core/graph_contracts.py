"""Validation pure des contrats déclarés par les graphiques matplotlib."""

from __future__ import annotations

from typing import Any


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


def validate_graph_contract(contract: dict | None, figure: Any) -> str | None:
    """Retourne un refus précis, ou ``None`` si la figure respecte le contrat."""
    if contract is None:
        return _blocked("graph_contract is missing")
    if not isinstance(contract, dict):
        return _blocked("graph_contract must be an object")
    missing = sorted(_REQUIRED_FIELDS.difference(contract))
    if missing:
        return _blocked("missing fields: " + ", ".join(missing))
    if contract["kind"] not in _ALLOWED_KINDS:
        return _blocked(f"unsupported kind: {contract['kind']}")
    if not isinstance(contract["axes"], list) or not contract["axes"]:
        return _blocked("axes must contain at least one data axis")
    if not isinstance(contract["source_variables"], list):
        return _blocked("source_variables must be a list")

    declared = _declared_inversions(contract)
    if isinstance(declared, str):
        return declared

    axes_by_index: dict[int, dict] = {}
    for axis_contract in contract["axes"]:
        if not isinstance(axis_contract, dict):
            return _blocked("axes entries must be objects")
        axis_index = axis_contract.get("axis_index")
        if not isinstance(axis_index, int) or axis_index < 0:
            return _blocked("axes entries require a non-negative axis_index")
        if axis_index >= len(figure.axes):
            return _blocked(f"axis_index {axis_index} does not exist")
        if not axis_contract.get("x") or not axis_contract.get("y"):
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
