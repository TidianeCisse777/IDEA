"""Regression coverage for IDEA's bundled, offline Cartopy runtime."""

import io
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")

from core.cartography import (
    BUNDLED_CARTOPY_DATA_DIR,
    CartographyAssetsError,
    configure_offline_cartopy,
    required_cartopy_asset_paths,
    validate_cartopy_assets,
)
from core.runtime_paths import graphs_dir


def test_bundled_cartopy_manifest_is_complete():
    paths = validate_cartopy_assets()

    assert len(paths) == 20
    assert all(path.is_file() for path in paths)
    assert all(BUNDLED_CARTOPY_DATA_DIR in path.parents for path in paths)


def test_cartopy_validation_reports_every_missing_asset(tmp_path):
    expected = required_cartopy_asset_paths(tmp_path)

    with pytest.raises(CartographyAssetsError) as exc_info:
        validate_cartopy_assets(tmp_path)

    assert str(expected[0]) in str(exc_info.value)
    assert "clone complet" in str(exc_info.value)


def test_bundled_layers_render_without_calling_cartopy_downloader(monkeypatch):
    import cartopy
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    import cartopy.io.shapereader as shapereader
    import matplotlib.pyplot as plt

    def reject_download(*args, **kwargs):
        raise AssertionError("Cartopy attempted a runtime download")

    monkeypatch.setattr(shapereader.NEShpDownloader, "acquire_resource", reject_download)
    monkeypatch.setitem(cartopy.config, "data_dir", Path("/nonexistent-cartopy-cache"))
    monkeypatch.setitem(cartopy.config, "pre_existing_data_dir", Path(""))
    configured = configure_offline_cartopy()

    fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    for category, name in (
        ("physical", "land"),
        ("physical", "ocean"),
        ("physical", "coastline"),
        ("cultural", "admin_0_boundary_lines_land"),
    ):
        ax.add_feature(cfeature.NaturalEarthFeature(category, name, "110m"))
    output = io.BytesIO()
    fig.savefig(output, format="png")
    plt.close(fig)

    assert configured == BUNDLED_CARTOPY_DATA_DIR
    assert output.getbuffer().nbytes > 0


def test_graphs_dir_uses_environment_override(monkeypatch, tmp_path):
    target = tmp_path / "persistent-graphs"
    monkeypatch.setenv("GRAPHS_DIR", str(target))

    assert graphs_dir() == target
    assert target.is_dir()


def test_docker_distribution_keeps_assets_outside_runtime_volume():
    project_root = Path(__file__).resolve().parent.parent

    assert BUNDLED_CARTOPY_DATA_DIR == project_root / "assets" / "cartopy"
    assert "configure_offline_cartopy" in (project_root / "Dockerfile").read_text()
    for compose_name in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = (project_root / compose_name).read_text()
        assert "GRAPHS_DIR=/app/data/graphs" in compose
        assert ":/app/data" in compose
