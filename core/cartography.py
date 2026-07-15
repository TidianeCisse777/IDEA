"""Configuration Cartopy autonome pour les cartes IDEA."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_CARTOPY_DATA_DIR = PROJECT_ROOT / "assets" / "cartopy"
_NATURAL_EARTH_ROOT = Path("shapefiles") / "natural_earth"
_REQUIRED_EXTENSIONS = (".shp", ".shx", ".dbf", ".prj", ".cpg")
_REQUIRED_LAYERS = (
    ("physical", "ne_110m_land"),
    ("physical", "ne_110m_ocean"),
    ("physical", "ne_110m_coastline"),
    ("cultural", "ne_110m_admin_0_boundary_lines_land"),
)


class CartographyAssetsError(RuntimeError):
    """Raised when IDEA's bundled Natural Earth assets are incomplete."""


def required_cartopy_asset_paths(data_dir: Path | None = None) -> tuple[Path, ...]:
    """Return every file required by IDEA's four Natural Earth 110m layers."""
    root = Path(data_dir) if data_dir is not None else BUNDLED_CARTOPY_DATA_DIR
    return tuple(
        root / _NATURAL_EARTH_ROOT / category / f"{layer}{extension}"
        for category, layer in _REQUIRED_LAYERS
        for extension in _REQUIRED_EXTENSIONS
    )


def validate_cartopy_assets(data_dir: Path | None = None) -> tuple[Path, ...]:
    """Validate bundled assets and return their paths, or raise a clear error."""
    paths = required_cartopy_asset_paths(data_dir)
    missing = tuple(path for path in paths if not path.is_file())
    if missing:
        details = "\n".join(f"- {path}" for path in missing)
        raise CartographyAssetsError(
            "Fonds cartographiques IDEA incomplets. Fichiers Natural Earth "
            f"110m manquants :\n{details}\n"
            "Réinstallez le projet depuis une archive ou un clone complet."
        )
    return paths


def configure_offline_cartopy(data_dir: Path | None = None) -> Path:
    """Point Cartopy at IDEA's validated, bundled Natural Earth directory."""
    root = Path(data_dir) if data_dir is not None else BUNDLED_CARTOPY_DATA_DIR
    validate_cartopy_assets(root)

    import cartopy

    cartopy.config["pre_existing_data_dir"] = root
    return root
