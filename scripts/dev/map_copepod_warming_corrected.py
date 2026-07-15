"""Carte corrigée — densité copépode (juste) x réchauffement projeté 2050.

Déterministe et traçable : aucune passe LLM.
- Abondance : filtre CLASS == 'Copepoda', densité par sample (somme des taxons
  copépodes), puis moyenne par station. On trace les STATIONS réelles (en mer),
  pas des centroïdes de zone (qui tombent sur la terre / des cellules masquées).
- Environnement : enrichissement via le tool `query_bio_oracle` (baseline vs
  SSP5-8.5 2050, température de surface) à chaque station.
- Les zones nommées ne servent qu'aux étiquettes.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from core.geo import load_registry
from shapely import contains_xy

FILE = "data/demo/neolabs_taxonomy_2014_2020.tsv"
ABUND = "Total abundance (ind./m3 depth vol)"
OUT = "docs/e2e/bio-oracle-futur-2026/figures/carte_corrigee_copepodes_2050.png"


def copepod_density_by_station() -> pd.DataFrame:
    df = pd.read_csv(FILE, sep="\t")
    cop = df[df["CLASS"] == "Copepoda"].copy()
    per_sample = cop.groupby("SAMPLE_ID").agg(
        station=("STATION_NAME", "first"),
        lat=("latitude", "first"),
        lon=("longitude", "first"),
        cop_density=(ABUND, "sum"),
    ).reset_index()
    per_station = per_sample.groupby("station").agg(
        lat=("lat", "mean"),
        lon=("lon", "mean"),
        cop_density=("cop_density", "mean"),
    ).reset_index()

    registry = load_registry(Path("data/geo/zones_registry.geojson"))

    def zone_of(lat: float, lon: float) -> str:
        hits = [z.canonical for z in registry.zones if contains_xy(z.polygon, lon, lat)]
        primary = [h for h in hits if not h.startswith("MEOW") and h not in ("Arctique", "Nunavik")]
        return (primary or hits or ["(hors zone)"])[0]

    per_station["zone"] = [zone_of(r.lat, r.lon) for r in per_station.itertuples()]
    return per_station


def _fetch_region(scenario: str, year, bbox: dict, stride: int = 4) -> pd.DataFrame:
    """UNE tuile Bio-ORACLE couvrant toute l'emprise, échantillonnée au pas
    `stride` (grille ~0,05° => stride 4 ≈ 0,2°). Une seule requête HTTP.
    Réutilise les résolveurs du module d'enrichissement Bio-ORACLE."""
    import io
    import requests
    from tools.bio_oracle_sources import (
        _ERDDAP_BASE, _find_dataset_id, _resolve_var, _resolve_scenario,
        _resolve_depth, _time_selector,
    )
    var = _resolve_var("temperature")
    scen = _resolve_scenario(scenario)
    depth = _resolve_depth("surface")
    dataset_id = _find_dataset_id(var, scen, depth)
    qvar = f"{var}_mean"
    tsel = _time_selector({"target_year": year}, scenario=scen)
    url = (
        f"{_ERDDAP_BASE}/griddap/{dataset_id}.csv?{qvar}"
        f"[({tsel})]"
        f"[({bbox['lat_min']:.4f}):{stride}:({bbox['lat_max']:.4f})]"
        f"[({bbox['lon_min']:.4f}):{stride}:({bbox['lon_max']:.4f})]"
    )
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    lines = r.text.splitlines()
    body = "\n".join([lines[0]] + lines[2:]) if len(lines) > 2 else r.text
    raw = pd.read_csv(io.StringIO(body))
    vcol = qvar if qvar in raw.columns else raw.columns[-1]
    out = raw.rename(columns={vcol: "value"})[["latitude", "longitude", "value"]].dropna()
    return out.reset_index(drop=True)


def _nearest(grid: pd.DataFrame, lat: float, lon: float) -> float:
    dlat = grid["latitude"].to_numpy() - lat
    dlon = grid["longitude"].to_numpy() - lon
    i = int((dlat * dlat + dlon * dlon).argmin())
    return float(grid["value"].iloc[i])


def enrich_warming(stations: pd.DataFrame) -> pd.DataFrame:
    """Réchauffement PAR STATION : delta Bio-ORACLE propre à chaque point (champ
    lisse, sans saut aux frontières de zones). 2 requêtes (1 grande tuile par
    scénario) + lookup local => rapide."""
    stations = stations.reset_index(drop=True)
    pad = 1.0
    bbox = {
        "lat_min": float(stations["lat"].min() - pad),
        "lat_max": float(stations["lat"].max() + pad),
        "lon_min": float(stations["lon"].min() - pad),
        "lon_max": float(stations["lon"].max() + pad),
    }
    base_grid = _fetch_region("baseline", None, bbox)
    fut_grid = _fetch_region("SSP5-8.5", 2050, bbox)
    stations["delta_2050"] = [
        _nearest(fut_grid, r.lat, r.lon) - _nearest(base_grid, r.lat, r.lon)
        for r in stations.itertuples()
    ]
    return stations


def draw_map(stations: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    halo = [pe.withStroke(linewidth=2.5, foreground="black")]
    s = stations.dropna(subset=["delta_2050", "cop_density"]).copy()
    fig = plt.figure(figsize=(12, 9))
    ax = plt.axes(projection=ccrs.NorthPolarStereo(central_longitude=-95))
    ax.set_extent([-140, -55, 55, 84], crs=ccrs.PlateCarree())
    ax.add_feature(cfeature.LAND, facecolor="#2b2b2b")
    ax.add_feature(cfeature.OCEAN, facecolor="#0d1b2a")
    ax.add_feature(cfeature.COASTLINE, linewidth=0.4, edgecolor="#888")
    ax.gridlines(linewidth=0.2, color="#555")

    dmax = s["cop_density"].max()
    sizes = 20 + 700 * (s["cop_density"] / dmax) ** 0.5
    sc = ax.scatter(
        s["lon"], s["lat"], s=sizes, c=s["delta_2050"], cmap="RdBu_r",
        transform=ccrs.PlateCarree(), edgecolor="white", linewidth=0.4,
        alpha=0.85, zorder=5,
    )
    cbar = plt.colorbar(sc, ax=ax, shrink=0.7, pad=0.02)
    cbar.set_label("Réchauffement projeté 2050 (°C, SSP5-8.5)", color="white")
    cbar.ax.yaxis.set_tick_params(color="white")
    plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color="white")

    # Étiquette de zone au centroïde des stations de chaque zone — halo noir
    # pour rester lisible sur tout fond (fini le blanc sur blanc).
    for zone, g in s.groupby("zone"):
        ax.annotate(
            zone, (g["lon"].mean(), g["lat"].mean()),
            transform=ccrs.PlateCarree(), fontsize=7.5, color="white",
            ha="center", weight="bold", zorder=7, path_effects=halo,
        )

    for d in (200, 1000, 5000, 15000):
        ax.scatter([], [], s=20 + 700 * (d / dmax) ** 0.5, c="none",
                   edgecolor="white", label=f"{d:,} ind/m³".replace(",", " "))
    leg = ax.legend(title="Densité copépode par station (corrigée)", loc="lower left",
                    labelspacing=1.6, framealpha=0.35, fontsize=8, title_fontsize=8)
    leg.get_frame().set_facecolor("#222")
    leg.get_title().set_color("white")
    for txt in leg.get_texts():
        txt.set_color("white")
    ax.set_title(
        "Densité copépode corrigée (Copepoda) et réchauffement projeté 2050 par station\n"
        f"{len(s)} stations — priorisation des futures expéditions, Arctique canadien",
        fontsize=11, color="white",
    )
    plt.savefig(OUT, dpi=130, bbox_inches="tight", facecolor="#111")
    print("carte:", OUT, "|", len(s), "stations tracées")


if __name__ == "__main__":
    st = copepod_density_by_station()
    print(f"{len(st)} stations copépodes")
    st = enrich_warming(st)
    ok = st.dropna(subset=["delta_2050"])
    print(f"enrichies avec delta: {len(ok)}/{len(st)}")
    # résumé par zone (pour le journal)
    by_zone = ok.groupby("zone").agg(
        n_stations=("station", "size"),
        cop_density_moy=("cop_density", "mean"),
        delta_moy=("delta_2050", "mean"),
    ).reset_index().sort_values("cop_density_moy", ascending=False)
    print(by_zone.round(2).to_string(index=False))
    draw_map(st)
