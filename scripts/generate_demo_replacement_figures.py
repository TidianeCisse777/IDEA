"""Regenerate the two validated replacement figures for the IDEA demo.

The script is deliberately data-backed: it reads the NeoLabs source table and
the certified Filet–UVP comparison cache, validates their expected scope, then
writes the PNG artefacts used by the demonstration document.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from pandas.core.arrays.string_ import StringDtype


ROOT = Path(__file__).resolve().parents[1]
STATION_OUTPUT = (
    ROOT
    / "data/demo_artifacts/station24_environnement_2018"
    / "station24_carte_locale_deploiements_2018.png"
)
NET_UVP_OUTPUT = (
    ROOT / "data/demo_artifacts/filet_uvp_2024" / "filet_uvp_ecart_2024.png"
)
NET_UVP_CACHE = ROOT / (
    "data/session_store/06d76e6bf9e47c33_dataset_df_filet_uvp_strates_in"
    "--72a458e5fe9468c6e18ae58201a87c282e75104c43409ab8e718421a1ef18bb0.pkl"
)


def read_certified_net_uvp_table() -> pd.DataFrame:
    """Read the persistent table produced with the newer pandas StringDtype."""
    original_init = StringDtype.__init__

    def compatible_init(self: StringDtype, storage: str | None = None, *args: object, **kwargs: object) -> None:
        original_init(self, storage=storage)

    StringDtype.__init__ = compatible_init
    try:
        table = pd.read_pickle(NET_UVP_CACHE)
    finally:
        StringDtype.__init__ = original_init

    calculable = table.loc[table["comparison_calculable"]].copy()
    expected = {"40–60 m", "60–100 m"}
    calculable["stratum"] = calculable.apply(
        lambda row: f"{int(row.net_depth_min_m)}–{int(row.net_depth_max_m)} m", axis=1
    )
    if set(calculable["stratum"]) != expected:
        raise ValueError("La comparaison certifiée doit contenir les strates 40–60 m et 60–100 m.")
    if not (calculable["abundance_delta_ind_m3"] < 0).all():
        raise ValueError("Les écarts attendus doivent être négatifs (UVP/EcoPart inférieur au filet).")
    return calculable.sort_values("net_depth_min_m")


def station24_deployments() -> pd.DataFrame:
    """Return the two actual Station 24 deployment positions for 12 June 2018."""
    samples = pd.read_csv(ROOT / "data/neolabs/neolabs_sample.csv")
    subset = samples.loc[
        samples["station_name"].astype(str).eq("24")
        & samples["deployment_datetime_start"].astype(str).str.startswith("2018-06-12"),
        [
            "deployment_datetime_start",
            "latitude",
            "longitude",
            "min_sample_depth",
            "max_sample_depth",
        ],
    ].copy()
    deployments = (
        subset.groupby(["deployment_datetime_start", "latitude", "longitude"], as_index=False)
        .agg(
            n_strata=("max_sample_depth", "size"),
            min_depth_m=("min_sample_depth", "min"),
            max_depth_m=("max_sample_depth", "max"),
        )
        .sort_values("deployment_datetime_start")
    )
    if len(deployments) != 2 or deployments["n_strata"].sum() != 12:
        raise ValueError("Station 24 doit contenir deux déploiements totalisant douze strates.")
    return deployments


def plot_station24_map(deployments: pd.DataFrame) -> None:
    """Show the coast–sea context and the two real Station 24 deployments."""
    fig = plt.figure(figsize=(12, 6.6), layout="constrained")
    grid = fig.add_gridspec(1, 2, width_ratios=(1.1, 1))
    overview = fig.add_subplot(grid[0], projection=ccrs.PlateCarree())
    detail = fig.add_subplot(grid[1])
    lon_padding, south_padding, north_padding = 1.2, 0.8, 2.0
    extent = [
        deployments["longitude"].min() - lon_padding,
        deployments["longitude"].max() + lon_padding,
        deployments["latitude"].min() - south_padding,
        deployments["latitude"].max() + north_padding,
    ]
    overview.set_extent(extent, crs=ccrs.PlateCarree())
    overview.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor="#DCEEFF", zorder=0)
    overview.add_feature(cfeature.LAND.with_scale("10m"), facecolor="#F1E8D0", zorder=1)
    overview.coastlines(resolution="10m", color="#475569", linewidth=0.8, zorder=2)
    station_lon = deployments["longitude"].mean()
    station_lat = deployments["latitude"].mean()
    overview.scatter(
        station_lon,
        station_lat,
        s=260,
        color="#DC2626",
        edgecolors="white",
        linewidths=1.8,
        zorder=3,
        transform=ccrs.PlateCarree(),
    )
    overview.annotate(
        "Station 24\n2 déploiements · 12 tranches",
        (station_lon, station_lat),
        xytext=(16, 18),
        textcoords="offset points",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.28", "fc": "white", "ec": "#94A3B8", "alpha": 0.96},
        arrowprops={"arrowstyle": "-", "color": "#475569", "lw": 1},
        zorder=4,
        transform=ccrs.PlateCarree(),
    )
    gridlines = overview.gridlines(
        draw_labels=True,
        linewidth=0.6,
        color="#94A3B8",
        alpha=0.55,
        linestyle="--",
    )
    gridlines.top_labels = False
    gridlines.right_labels = False
    overview.set_title("Contexte côte–mer", fontsize=11, pad=10)

    local_lon_padding, local_lat_padding = 0.003, 0.003
    scatter = detail.scatter(
        deployments["longitude"],
        deployments["latitude"],
        s=deployments["n_strata"] * 115,
        c=deployments["max_depth_m"],
        cmap="viridis",
        edgecolors="#17365D",
        linewidths=1.2,
        zorder=3,
    )
    offsets = [(-110, 16), (12, -34)]
    for deployment, offset in zip(deployments.itertuples(index=False), offsets, strict=True):
        time = pd.Timestamp(deployment.deployment_datetime_start).strftime("%H:%M")
        detail.annotate(
            f"{time} — {deployment.n_strata} tranches\n{int(deployment.min_depth_m)}–{int(deployment.max_depth_m)} m",
            (deployment.longitude, deployment.latitude),
            xytext=offset,
            textcoords="offset points",
            fontsize=9.5,
            bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "#94A3B8", "alpha": 0.96},
            arrowprops={"arrowstyle": "-", "color": "#475569", "lw": 1},
            zorder=4,
        )
    detail.set_xlim(deployments["longitude"].min() - local_lon_padding, deployments["longitude"].max() + local_lon_padding)
    detail.set_ylim(deployments["latitude"].min() - local_lat_padding, deployments["latitude"].max() + local_lat_padding)
    detail.grid(True, color="#CBD5E1", alpha=0.7)
    detail.set_xlabel("Longitude (°)")
    detail.set_ylabel("Latitude (°)")
    detail.set_title("Détail local des déploiements", fontsize=11, pad=10)
    colorbar = fig.colorbar(scatter, ax=detail, shrink=0.82, pad=0.03)
    colorbar.set_label("Profondeur maximale (m)")
    fig.suptitle("Station 24 — deux déploiements du 12 juin 2018", fontweight="bold", fontsize=16)
    fig.savefig(STATION_OUTPUT, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_net_uvp_delta(table: pd.DataFrame) -> None:
    """Plot the two certified absolute differences with labels clear of the axis."""
    fig, ax = plt.subplots(figsize=(10, 5.8), layout="constrained")
    labels = table["stratum"].tolist()
    values = table["abundance_delta_ind_m3"].tolist()
    bars = ax.barh(labels, values, color="#C81E1E", height=0.56)
    ax.axvline(0, color="#334155", linewidth=1.4)
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            value / 2,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.1f}",
            ha="center",
            va="center",
            color="white",
            fontsize=12,
            fontweight="bold",
        )
    left = min(values) * 1.16
    ax.set_xlim(left, max(30, abs(left) * 0.09))
    ax.grid(axis="x", color="#CBD5E1", alpha=0.7)
    ax.set_axisbelow(True)
    ax.set_xlabel("Écart d’abondance UVP/EcoPart − filet (ind./m³)")
    ax.set_ylabel("Strate de profondeur")
    ax.set_title("Écart absolu Filet–UVP — RA62, 2024", fontweight="bold", pad=14)
    ax.text(
        0.5,
        1.01,
        "Comparaison certifiée ; valeurs négatives : abondance UVP/EcoPart inférieure au filet.",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=10,
        color="#475569",
    )
    fig.savefig(NET_UVP_OUTPUT, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    plot_station24_map(station24_deployments())
    plot_net_uvp_delta(read_certified_net_uvp_table())
    print(f"Generated {STATION_OUTPUT}")
    print(f"Generated {NET_UVP_OUTPUT}")


if __name__ == "__main__":
    main()
