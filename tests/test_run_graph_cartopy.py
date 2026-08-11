"""Regression tests for Cartopy rendering from safely derived coordinates."""

import pandas as pd


def test_run_graph_accepts_coordinates_derived_from_persisted_bounds(tmp_path):
    from tools.data_tools import make_tools
    from tools.dataset_registry import store_dataset
    from tools.session_store import SessionStore

    thread_id = "thread-cartopy-derived-coordinates"
    store = SessionStore(storage_dir=tmp_path)
    source = pd.DataFrame(
        {
            "station_id": ["A", "B"],
            "lat_min": [65.0, 66.0],
            "lat_max": [65.2, 66.2],
            "lon_min": [-60.0, -61.0],
            "lon_max": [-59.8, -60.8],
        }
    )
    store_dataset(
        store,
        thread_id,
        source,
        variable_name="df_station_bounds",
        meta={"source": "test", "grain": "station"},
        latest_alias="df_station_bounds",
        is_loaded_file=True,
    )
    run_graph = next(
        tool for tool in make_tools(thread_id, store=store) if tool.name == "run_graph"
    )

    result = run_graph.invoke(
        {
            "code": """
import pandas as pd
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

plot_df = df_station_bounds.copy()
plot_df['latitude'] = (
    pd.to_numeric(plot_df['lat_min'], errors='coerce')
    + pd.to_numeric(plot_df['lat_max'], errors='coerce')
) / 2
plot_df['longitude'] = (
    pd.to_numeric(plot_df['lon_min'], errors='coerce')
    + pd.to_numeric(plot_df['lon_max'], errors='coerce')
) / 2
plot_df = plot_df.dropna(subset=['latitude', 'longitude'])

fig = plt.figure(figsize=(6, 4))
ax = plt.axes(projection=ccrs.PlateCarree())
ax.scatter(
    plot_df['longitude'],
    plot_df['latitude'],
    transform=ccrs.PlateCarree(),
)
plt.tight_layout()
"""
        }
    )

    assert result.startswith("![graph](")


def test_run_graph_rejects_cartopy_points_without_coordinate_source(tmp_path):
    from tools.data_tools import make_tools
    from tools.dataset_registry import store_dataset
    from tools.session_store import SessionStore

    thread_id = "thread-cartopy-missing-coordinates"
    store = SessionStore(storage_dir=tmp_path)
    source = pd.DataFrame(
        {
            "station_id": ["A", "B"],
            "n_samples": [12, 8],
        }
    )
    store_dataset(
        store,
        thread_id,
        source,
        variable_name="df_station_summary",
        meta={"source": "test", "grain": "station"},
        latest_alias="df_station_summary",
        is_loaded_file=True,
    )
    run_graph = next(
        tool for tool in make_tools(thread_id, store=store) if tool.name == "run_graph"
    )

    result = run_graph.invoke(
        {
            "code": """
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

plot_df = df_station_summary.copy()
fig = plt.figure(figsize=(6, 4))
ax = plt.axes(projection=ccrs.PlateCarree())
ax.scatter(
    range(len(plot_df)),
    plot_df['n_samples'],
    transform=ccrs.PlateCarree(),
)
plt.tight_layout()
"""
        }
    )

    assert result.startswith(
        "Cartopy point map impossible: no usable or safely derivable "
        "latitude/longitude columns"
    )
