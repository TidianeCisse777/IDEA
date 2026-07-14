"""Contrats exécutables appliqués aux figures matplotlib."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from core.graph_contracts import validate_graph_contract


def _vertical_contract(*, inverted_axes=None):
    return {
        "kind": "vertical_profile",
        "axes": [
            {
                "axis_index": 0,
                "x": "abundance_ind_L",
                "y": "depth_m",
            }
        ],
        "inverted_axes": (
            [{"axis_index": 0, "axis": "y"}]
            if inverted_axes is None
            else inverted_axes
        ),
        "mappings": {},
        "zero_policy": {"mode": "include", "artist_gid": None},
        "source_variables": ["depth_m", "abundance_ind_L"],
    }


def test_missing_contract_is_blocked():
    fig, _ = plt.subplots()

    issue = validate_graph_contract(None, fig)

    assert issue == "graph contract blocked: graph_contract is missing"
    plt.close(fig)


def test_vertical_profile_accepts_only_inverted_depth_y_axis():
    fig, ax = plt.subplots()
    ax.invert_yaxis()

    issue = validate_graph_contract(_vertical_contract(), fig)

    assert issue is None
    plt.close(fig)


def test_vertical_profile_blocks_inverted_abundance_x_axis():
    fig, ax = plt.subplots()
    ax.invert_xaxis()
    ax.invert_yaxis()

    issue = validate_graph_contract(_vertical_contract(), fig)

    assert issue == "graph contract blocked: abundance x-axis must remain normal"
    plt.close(fig)


def test_vertical_profile_blocks_contract_that_does_not_declare_depth_inversion():
    fig, ax = plt.subplots()
    ax.invert_yaxis()

    issue = validate_graph_contract(_vertical_contract(inverted_axes=[]), fig)

    assert issue == (
        "graph contract blocked: axis 0 y inversion differs from graph_contract"
    )
    plt.close(fig)
