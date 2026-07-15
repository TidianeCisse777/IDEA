"""Configuration Cartopy autonome pour les cartes IDEA."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_CARTOPY_DATA_DIR = PROJECT_ROOT / "assets" / "cartopy"
_NATURAL_EARTH_ROOT = Path("shapefiles") / "natural_earth"
_REQUIRED_EXTENSIONS = (".shp", ".shx", ".dbf", ".prj", ".cpg")
# Scales vendored offline, coarsest first. 50m is the finest available and the
# default for IDEA's regional maps; 110m is the whole-basin fallback.
VENDORED_SCALES = ("110m", "50m")
_FINEST_VENDORED_SCALE = VENDORED_SCALES[-1]
_REQUIRED_LAYERS = tuple(
    (category, f"ne_{scale}_{layer}")
    for scale in VENDORED_SCALES
    for category, layer in (
        ("physical", "land"),
        ("physical", "ocean"),
        ("physical", "coastline"),
        ("cultural", "admin_0_boundary_lines_land"),
    )
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


def _install_scale_guard() -> None:
    """Pin every requested Natural Earth scale to a vendored one, once.

    Two paths can request a non-bundled scale and trigger a runtime download
    that fails on an offline install (see the offline-cartography diagnosis):

    1. Free-form ``NaturalEarthFeature(..., "10m")`` / ``.with_scale("10m")`` /
       ``ax.coastlines(resolution="10m")`` — pinned by wrapping ``__init__``.
    2. The bare singletons ``cfeature.LAND/OCEAN/COASTLINE/BORDERS`` carry an
       ``AdaptiveScaler`` that, at draw time, re-selects the scale from the map
       extent — a zoomed regional map resolves to ``"10m"`` regardless of the
       ``"110m"`` default. This is the path the ``graph_writer`` templates use.
       Pinned by clamping ``AdaptiveScaler.scale_from_extent``.

    Anything outside :data:`VENDORED_SCALES` is coerced to the finest vendored
    scale before any geometry loads, so cartopy only ever reads bundled files.
    """
    import cartopy.feature as cfeature

    original_init = cfeature.NaturalEarthFeature.__init__
    if not getattr(original_init, "_idea_scale_guard", False):

        def guarded_init(self, category, name, scale, **kwargs):  # type: ignore[no-untyped-def]
            if scale not in VENDORED_SCALES:
                scale = _FINEST_VENDORED_SCALE
            original_init(self, category, name, scale, **kwargs)

        guarded_init._idea_scale_guard = True  # type: ignore[attr-defined]
        cfeature.NaturalEarthFeature.__init__ = guarded_init  # type: ignore[method-assign]

    original_scale_from_extent = cfeature.AdaptiveScaler.scale_from_extent
    if not getattr(original_scale_from_extent, "_idea_scale_guard", False):

        def guarded_scale_from_extent(self, extent):  # type: ignore[no-untyped-def]
            scale = original_scale_from_extent(self, extent)
            if scale not in VENDORED_SCALES:
                scale = _FINEST_VENDORED_SCALE
                self._scale = scale
            return scale

        guarded_scale_from_extent._idea_scale_guard = True  # type: ignore[attr-defined]
        cfeature.AdaptiveScaler.scale_from_extent = guarded_scale_from_extent  # type: ignore[method-assign]


def configure_offline_cartopy(data_dir: Path | None = None) -> Path:
    """Point Cartopy at IDEA's validated, bundled Natural Earth directory."""
    root = Path(data_dir) if data_dir is not None else BUNDLED_CARTOPY_DATA_DIR
    validate_cartopy_assets(root)

    import cartopy

    cartopy.config["pre_existing_data_dir"] = root
    _install_scale_guard()
    return root
