"""Contrats exécutables appliqués aux figures matplotlib."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

from core.graph_contracts import normalize_graph_contract, validate_graph_contract


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


def _environment_contract():
    return {
        "kind": "environment_relationships",
        "axes": [
            {"axis_index": 0, "x": "temperature", "y": "abundance_ind_L"},
            {"axis_index": 1, "x": "salinity", "y": "abundance_ind_L"},
            {"axis_index": 2, "x": "oxygen", "y": "abundance_ind_L"},
        ],
        "inverted_axes": [],
        "mappings": {},
        "zero_policy": {"mode": "include", "artist_gid": None},
        "source_variables": [
            "temperature", "salinity", "oxygen", "abundance_ind_L"
        ],
    }


def _temperature_salinity_contract():
    return {
        "kind": "temperature_salinity",
        "axes": [{"axis_index": 0, "x": "salinity", "y": "temperature"}],
        "inverted_axes": [],
        "mappings": {
            "size": {"variable": "abundance_ind_L", "artist_gid": "ts_points"},
            "color": {"variable": "depth_m", "artist_gid": "ts_points"},
            "station": {"variable": "station", "artist_gid": "station_shapes"},
        },
        "zero_policy": {"mode": "hollow", "artist_gid": "zero_abundance"},
        "source_variables": [
            "salinity", "temperature", "abundance_ind_L", "depth_m", "station"
        ],
    }


def _add_ts_artists(ax, *, hollow_zeros: bool):
    points = ax.scatter([31.0], [-1.2], s=[40], c=[10.0])
    points.set_gid("ts_points")
    stations = ax.scatter([31.1], [-1.1], marker="s")
    stations.set_gid("station_shapes")
    zeros = ax.scatter(
        [31.2],
        [-1.0],
        facecolors="none" if hollow_zeros else "red",
        edgecolors="white",
    )
    zeros.set_gid("zero_abundance")


def _map_contract():
    return {
        "kind": "abundance_environment_map",
        "axes": [{"axis_index": 0, "x": "longitude", "y": "latitude"}],
        "inverted_axes": [],
        "mappings": {
            "position": {
                "variable": "longitude_latitude",
                "artist_gid": "map_points",
            },
            "size": {"variable": "abundance_ind_L", "artist_gid": "map_points"},
            "color": {"variable": "temperature", "artist_gid": "map_points"},
            "size_legend": {
                "variable": "abundance_ind_L",
                "artist_gid": "abundance_size_legend",
            },
            "color_legend": {
                "variable": "temperature",
                "artist_gid": "environment_color_legend",
            },
        },
        "zero_policy": {"mode": "include", "artist_gid": None},
        "source_variables": [
            "longitude", "latitude", "abundance_ind_L", "temperature"
        ],
    }


def _add_map_artists(ax, *, include_color_legend=True):
    points = ax.scatter(
        [-80.2], [74.1], s=[40], c=[-1.2], transform=ccrs.PlateCarree()
    )
    points.set_gid("map_points")
    size_legend = ax.text(0.01, 0.01, "Abondance (ind./L)")
    size_legend.set_gid("abundance_size_legend")
    if include_color_legend:
        color_legend = ax.text(0.01, 0.05, "Température (°C)")
        color_legend.set_gid("environment_color_legend")


def test_station_map_normalizes_omitted_color_legend_mapping():
    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    points = ax.scatter(
        [-80.2], [74.1], s=[40], c=[2014], transform=ccrs.PlateCarree()
    )
    points.set_gid("map_points")
    ax.legend(["2014"], title="Année de déploiement")
    contract = {
        "kind": "station_map",
        "axes": [{"axis_index": 0, "x": "longitude", "y": "latitude"}],
        "inverted_axes": [],
        "mappings": {
            "position": {
                "variable": "longitude_latitude",
                "artist_gid": "map_points",
            },
            "color": {"variable": "deployment_year", "artist_gid": "map_points"},
        },
        "zero_policy": {"mode": "include", "artist_gid": None},
        "source_variables": ["longitude", "latitude", "deployment_year"],
    }

    normalized = normalize_graph_contract(contract, fig)

    assert normalized["mappings"]["color_legend"] == {
        "variable": "deployment_year",
        "artist_gid": "station_color_legend",
    }
    assert validate_graph_contract(normalized, fig) is None


def _station_map_contract(mappings=None):
    return {
        "kind": "station_map",
        "axes": [{"axis_index": 0, "x": "longitude", "y": "latitude"}],
        "inverted_axes": [],
        "mappings": mappings
        if mappings is not None
        else {
            "position": {
                "variable": "longitude_latitude",
                "artist_gid": "map_points",
            }
        },
        "zero_policy": {"mode": "include", "artist_gid": None},
        "source_variables": ["longitude", "latitude", "sample_id"],
    }


def test_station_map_accepts_positions_without_abundance():
    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    points = ax.scatter([-52.8], [58.6], transform=ccrs.PlateCarree())
    points.set_gid("map_points")

    issue = validate_graph_contract(_station_map_contract(), fig)

    assert issue is None
    plt.close(fig)


def test_station_map_normalizer_binds_primary_scatter_to_missing_mappings():
    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    ax.scatter([-52.8], [58.6], s=[40], c=[3.0], transform=ccrs.PlateCarree())
    contract = _station_map_contract(
        mappings={"size": {"variable": "sample_count", "artist_gid": None}}
    )

    normalized = normalize_graph_contract(contract, fig)

    assert normalized["mappings"]["position"] == {
        "variable": "longitude_latitude",
        "artist_gid": "station_map_points",
    }
    assert normalized["mappings"]["size"]["artist_gid"] == "station_map_points"
    assert validate_graph_contract(normalized, fig) is None
    plt.close(fig)


def test_station_map_normalizer_supplies_recoverable_metadata_defaults():
    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    ax.scatter([-52.8], [58.6], transform=ccrs.PlateCarree())
    contract = {
        "kind": "station_map",
        "axes": [{"axis_index": 0, "x": "longitude", "y": "latitude"}],
        "mappings": {"position": {"variable": "longitude_latitude"}},
    }

    normalized = normalize_graph_contract(contract, fig)

    assert normalized["inverted_axes"] == []
    assert normalized["zero_policy"] == {"mode": "include", "artist_gid": None}
    assert normalized["source_variables"] == ["longitude", "latitude"]
    assert validate_graph_contract(normalized, fig) is None
    plt.close(fig)


def test_station_map_normalizer_replaces_invalid_xy_position_mapping():
    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    ax.scatter([-52.8], [58.6], transform=ccrs.PlateCarree())
    contract = _station_map_contract(
        mappings={"position": {"x": "longitude", "y": "latitude"}}
    )

    normalized = normalize_graph_contract(contract, fig)

    assert normalized["mappings"]["position"]["variable"] == "longitude_latitude"
    assert validate_graph_contract(normalized, fig) is None
    plt.close(fig)


def test_station_map_accepts_free_size_and_color_variables():
    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    points = ax.scatter([-52.8], [58.6], s=[40], c=[3.0], transform=ccrs.PlateCarree())
    points.set_gid("map_points")
    legend = ax.text(0.01, 0.01, "Nb de taxons")
    legend.set_gid("taxa_color_legend")

    contract = _station_map_contract(
        mappings={
            "position": {"variable": "longitude_latitude", "artist_gid": "map_points"},
            "size": {"variable": "sample_count", "artist_gid": "map_points"},
            "color": {"variable": "n_taxa", "artist_gid": "map_points"},
            "color_legend": {"variable": "n_taxa", "artist_gid": "taxa_color_legend"},
        }
    )

    issue = validate_graph_contract(contract, fig)

    assert issue is None
    plt.close(fig)


def test_station_map_blocks_plain_matplotlib_axis():
    fig, ax = plt.subplots()
    points = ax.scatter([-52.8], [58.6])
    points.set_gid("map_points")

    issue = validate_graph_contract(_station_map_contract(), fig)

    assert issue == "graph contract blocked: station map requires a Cartopy GeoAxes"
    plt.close(fig)


def test_station_map_blocks_missing_position_artist():
    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    ax.scatter([-52.8], [58.6], transform=ccrs.PlateCarree())  # no gid

    issue = validate_graph_contract(_station_map_contract(), fig)

    assert issue == "graph contract blocked: position mapping artist is missing"
    plt.close(fig)


def test_station_map_blocks_inconsistent_color_legend():
    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    points = ax.scatter([-52.8], [58.6], c=[3.0], transform=ccrs.PlateCarree())
    points.set_gid("map_points")
    legend = ax.text(0.01, 0.01, "legende")
    legend.set_gid("color_legend_gid")

    contract = _station_map_contract(
        mappings={
            "position": {"variable": "longitude_latitude", "artist_gid": "map_points"},
            "color": {"variable": "n_taxa", "artist_gid": "map_points"},
            "color_legend": {"variable": "depth_m", "artist_gid": "color_legend_gid"},
        }
    )

    issue = validate_graph_contract(contract, fig)

    assert issue == "graph contract blocked: color_legend must describe the color mapping"
    plt.close(fig)


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


def test_vertical_profile_normalizes_french_total_abundance_alias():
    fig, ax = plt.subplots()
    ax.invert_yaxis()
    contract = _vertical_contract()
    contract["axes"][0]["x"] = "abondance_totale_ind_m3"
    contract["source_variables"] = ["depth_m", "abondance_totale_ind_m3"]

    normalized = normalize_graph_contract(contract, fig)

    assert normalized["axes"][0]["x"] == "abundance_ind_m3"
    assert normalized["source_variables"] == ["depth_m", "abondance_totale_ind_m3"]
    assert validate_graph_contract(normalized, fig) is None
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


def test_environment_relationships_accept_three_independent_normal_axes():
    fig, _ = plt.subplots(1, 3)

    issue = validate_graph_contract(_environment_contract(), fig)

    assert issue is None
    plt.close(fig)


def test_environment_relationships_block_shared_axes():
    fig, _ = plt.subplots(1, 3, sharey=True)

    issue = validate_graph_contract(_environment_contract(), fig)

    assert issue == "graph contract blocked: environmental panels must use independent axes"
    plt.close(fig)


def test_environment_relationships_block_inverted_abundance_axis():
    fig, axes = plt.subplots(1, 3)
    axes[1].invert_yaxis()
    contract = _environment_contract()
    contract["inverted_axes"] = [{"axis_index": 1, "axis": "y"}]

    issue = validate_graph_contract(contract, fig)

    assert issue == "graph contract blocked: abundance axes must remain normal"
    plt.close(fig)


def test_temperature_salinity_accepts_all_mappings_and_hollow_zeros():
    fig, ax = plt.subplots()
    _add_ts_artists(ax, hollow_zeros=True)

    issue = validate_graph_contract(_temperature_salinity_contract(), fig)

    assert issue is None
    plt.close(fig)


def test_temperature_salinity_blocks_filled_zero_markers():
    fig, ax = plt.subplots()
    _add_ts_artists(ax, hollow_zeros=False)

    issue = validate_graph_contract(_temperature_salinity_contract(), fig)

    assert issue == "graph contract blocked: zero abundance must use hollow markers"
    plt.close(fig)


def test_temperature_salinity_blocks_missing_station_mapping_artist():
    fig, ax = plt.subplots()
    _add_ts_artists(ax, hollow_zeros=True)
    for artist in ax.collections:
        if artist.get_gid() == "station_shapes":
            artist.set_gid(None)

    issue = validate_graph_contract(_temperature_salinity_contract(), fig)

    assert issue == "graph contract blocked: station mapping artist is missing"
    plt.close(fig)


def test_abundance_environment_map_accepts_cartopy_and_complete_mappings():
    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    _add_map_artists(ax)

    issue = validate_graph_contract(_map_contract(), fig)

    assert issue is None
    plt.close(fig)


def test_abundance_environment_map_blocks_plain_matplotlib_axis():
    fig, ax = plt.subplots()
    points = ax.scatter([-80.2], [74.1], s=[40], c=[-1.2])
    points.set_gid("map_points")

    issue = validate_graph_contract(_map_contract(), fig)

    assert issue == "graph contract blocked: geographic map requires a Cartopy GeoAxes"
    plt.close(fig)


def test_abundance_environment_map_blocks_missing_environment_legend():
    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    _add_map_artists(ax, include_color_legend=False)

    issue = validate_graph_contract(_map_contract(), fig)

    assert issue == "graph contract blocked: color_legend mapping artist is missing"
    plt.close(fig)
