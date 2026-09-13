"""Fast, offline smoke tests for the user-facing microsandbox environment."""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path


IMPORTS = (
    "adjustText",
    "cartopy",
    "cmocean",
    "contextily",
    "copernicusmarine",
    "earthaccess",
    "geopandas",
    "h5py",
    "matplotlib",
    "netCDF4",
    "numpy",
    "openai_codex",
    "pandas",
    "plotly",
    "pymupdf",
    "pytesseract",
    "rasterio",
    "reportlab",
    "rioxarray",
    "scipy",
    "seaborn",
    "sklearn",
    "statsmodels",
    "tadc",
    "utide",
    "xarray",
    "zarr",
)


def main() -> None:
    assert Path(sys.executable).resolve() == Path(
        "/opt/idea-venv/bin/python"
    ), f"unexpected Python executable: {sys.executable}"

    outputs = Path("/outputs")
    assert outputs.is_dir() and os.access(outputs, os.W_OK), (
        "/outputs must be writable by the kernel user"
    )
    output_probe = outputs / ".idea-environment-smoke"
    output_probe.write_text("ok", encoding="utf-8")
    output_probe.unlink()

    for name in IMPORTS:
        importlib.import_module(name)

    geojson_path = Path("/app/data/geo/zones_registry.geojson")
    if os.getenv("IDEA_REQUIRE_SHARED_DATA") == "1":
        assert geojson_path.is_file(), f"missing shared GeoJSON: {geojson_path}"
        payload = json.loads(geojson_path.read_text(encoding="utf-8"))
        assert payload.get("type") == "FeatureCollection"
        assert payload.get("features"), "shared GeoJSON has no features"

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pytesseract
    import xarray as xr
    from reportlab.pdfgen import canvas

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        dataset = xr.Dataset(
            {"sea_level": (("time",), np.asarray([0.1, 0.2, 0.15]))},
            coords={"time": np.arange(3)},
        )
        netcdf_path = root / "sample.nc"
        dataset.to_netcdf(netcdf_path, engine="h5netcdf")
        loaded = xr.open_dataset(netcdf_path, engine="h5netcdf")
        assert loaded.sizes["time"] == 3
        loaded.close()

        figure_path = root / "plot.png"
        plt.plot(dataset["time"], dataset["sea_level"])
        plt.savefig(figure_path)
        plt.close()
        assert figure_path.stat().st_size > 0

        pdf_path = root / "report.pdf"
        report = canvas.Canvas(str(pdf_path))
        report.drawString(72, 720, "IDEA microsandbox smoke test")
        report.save()
        assert pdf_path.stat().st_size > 0

        assert pytesseract.get_tesseract_version()

    print("Python research smoke tests passed")


if __name__ == "__main__":
    main()
