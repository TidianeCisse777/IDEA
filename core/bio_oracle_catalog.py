"""Validated Bio-ORACLE variables and enrichment selections.

The catalog is deliberately independent from HTTP clients and session state. It
is the single place where user-facing names are translated to Bio-ORACLE ERDDAP
identifiers and where a canonical enrichment request is checked before network
I/O.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import unicodedata
from typing import Iterable


@dataclass(frozen=True)
class CatalogVariable:
    key: str
    erddap_var: str
    label: str
    group: str
    unit: str
    layers: tuple[str, ...]
    statistics: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    recommended_for_copepods: bool = False


_ALL_LAYERS = ("surface", "benthic_min", "benthic_mean", "benthic_max")
_CLIMATE_STATISTICS = ("mean", "min", "max", "lt_min", "lt_max", "range")


def _variable(
    key: str,
    erddap_var: str,
    label: str,
    group: str,
    unit: str,
    *,
    aliases: tuple[str, ...] = (),
    recommended_for_copepods: bool = False,
) -> CatalogVariable:
    return CatalogVariable(
        key=key,
        erddap_var=erddap_var,
        label=label,
        group=group,
        unit=unit,
        layers=_ALL_LAYERS,
        statistics=_CLIMATE_STATISTICS,
        aliases=aliases,
        recommended_for_copepods=recommended_for_copepods,
    )


CATALOG_VARIABLES: tuple[CatalogVariable, ...] = (
    _variable("temperature", "thetao", "Température de l'eau", "physique", "°C", aliases=("temp", "température", "thetao"), recommended_for_copepods=True),
    _variable("salinity", "so", "Salinité", "physique", "PSU", aliases=("salinité", "salinite", "so"), recommended_for_copepods=True),
    _variable("sea_water_speed", "sws", "Vitesse du courant", "physique", "m s-1", aliases=("current_speed", "vitesse courant")),
    _variable("sea_water_direction", "swd", "Direction du courant", "physique", "degrés", aliases=("current_direction", "direction courant")),
    _variable("nitrate", "no3", "Nitrate", "chimique", "mmol m-3", aliases=("no3",), recommended_for_copepods=True),
    _variable("phosphate", "po4", "Phosphate", "chimique", "mmol m-3", aliases=("po4",), recommended_for_copepods=True),
    _variable("silicate", "si", "Silicate", "chimique", "mmol m-3", aliases=("silicium", "si"), recommended_for_copepods=True),
    _variable("oxygen", "o2", "Oxygène dissous", "chimique", "mmol m-3", aliases=("oxygène", "oxygene", "o2"), recommended_for_copepods=True),
    _variable("iron", "dfe", "Fer dissous", "chimique", "mmol m-3", aliases=("fer", "dfe")),
    _variable("primary_productivity", "phyc", "Productivité primaire", "biologique", "mmol m-3", aliases=("productivité primaire", "phyc"), recommended_for_copepods=True),
    _variable("ph", "ph", "pH", "chimique", "-", aliases=("pH",), recommended_for_copepods=True),
    _variable("chlorophyll", "chl", "Chlorophylle", "biologique", "mg m-3", aliases=("chlorophylle", "chl"), recommended_for_copepods=True),
    _variable("sea_ice_thickness", "sithick", "Épaisseur de glace de mer", "glace", "m", aliases=("glace épaisseur",)),
    _variable("sea_ice_cover", "siconc", "Couverture de glace de mer", "glace", "fraction", aliases=("glace couverture",)),
    _variable("cloud_cover", "clt", "Couverture nuageuse", "atmosphère", "%", aliases=("nébulosité", "nuages")),
    _variable("mixed_layer_depth", "mlotst", "Profondeur de couche mélangée", "physique", "m", aliases=("couche mélangée", "mlotst"), recommended_for_copepods=True),
    _variable("air_temperature", "tas", "Température de l'air", "atmosphère", "°C", aliases=("température air",)),
    _variable("par", "par", "Rayonnement photosynthétiquement disponible", "lumière", "E m-2 jour-1", aliases=("rayonnement", "lumière disponible"), recommended_for_copepods=True),
    _variable("diffuse_attenuation", "kdpar_mean", "Atténuation lumineuse diffuse", "lumière", "m-1", aliases=("atténuation lumineuse", "kd", "kdpar"), recommended_for_copepods=True),
)


CATALOG_SCENARIOS: dict[str, str] = {
    "baseline": "baseline",
    "present": "baseline",
    "actuel": "baseline",
    "historique": "baseline",
    "ssp1-1.9": "ssp119",
    "ssp119": "ssp119",
    "ssp1-2.6": "ssp126",
    "ssp126": "ssp126",
    "ssp2-4.5": "ssp245",
    "ssp245": "ssp245",
    "4.5": "ssp245",
    "rcp4.5": "ssp245",
    "ssp3-7.0": "ssp370",
    "ssp370": "ssp370",
    "ssp4-6.0": "ssp460",
    "ssp460": "ssp460",
    "ssp5-8.5": "ssp585",
    "ssp585": "ssp585",
}

SCENARIO_DISPLAY_NAMES: dict[str, str] = {
    "baseline": "baseline",
    "ssp119": "ssp1_1_9",
    "ssp126": "ssp1_2_6",
    "ssp245": "ssp2_4_5",
    "ssp370": "ssp3_7_0",
    "ssp460": "ssp4_6_0",
    "ssp585": "ssp5_8_5",
}

CATALOG_LAYERS: dict[str, str] = {
    "surface": "depthsurf",
    "surf": "depthsurf",
    "benthic_min": "depthmin",
    "benthic_mean": "depthmean",
    "benthic_max": "depthmax",
    "min": "depthmin",
    "mean": "depthmean",
    "max": "depthmax",
}

LAYER_DISPLAY_NAMES: dict[str, str] = {
    "depthsurf": "surface",
    "depthmin": "benthic_min",
    "depthmean": "benthic_mean",
    "depthmax": "benthic_max",
}

_STATISTIC_ALIASES = {
    "moyenne": "mean",
    "minimum": "min",
    "maximum": "max",
    "minimum_long_terme": "lt_min",
    "maximum_long_terme": "lt_max",
    "étendue": "range",
    "etendue": "range",
}
_VARIABLE_BY_ALIAS: dict[str, CatalogVariable] = {}
for _entry in CATALOG_VARIABLES:
    for _alias in (_entry.key, _entry.erddap_var, *_entry.aliases):
        _VARIABLE_BY_ALIAS[_alias] = _entry


def _normalise(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "_".join(text.replace("-", "_").split())


def list_catalog_variables() -> list[dict]:
    """Return user-facing catalog entries without exposing credentials."""
    return [
        {
            **asdict(entry),
            "layers": list(entry.layers),
            "statistics": list(entry.statistics),
            "aliases": list(entry.aliases),
        }
        for entry in CATALOG_VARIABLES
    ]


def resolve_catalog_variable(value: str) -> CatalogVariable:
    """Resolve a friendly or ERDDAP variable name from the catalog."""
    key = _normalise(value)
    try:
        return _VARIABLE_BY_ALIAS[key]
    except KeyError as exc:
        choices = ", ".join(entry.key for entry in CATALOG_VARIABLES)
        raise ValueError(f"Unknown Bio-ORACLE variable {value!r}; choices: {choices}") from exc


def resolve_catalog_statistic(variable: CatalogVariable, value: str) -> str:
    """Resolve one statistic supported by a catalog variable."""
    key = _STATISTIC_ALIASES.get(_normalise(value), _normalise(value))
    if key not in variable.statistics:
        choices = ", ".join(variable.statistics)
        raise ValueError(
            f"Statistic {value!r} is unavailable for {variable.key}; choices: {choices}"
        )
    return key


def _resolve_scenario(value: str) -> str:
    key = _normalise(value).replace("_", "-")
    try:
        return CATALOG_SCENARIOS[key]
    except KeyError as exc:
        choices = ", ".join(sorted(set(CATALOG_SCENARIOS.values())))
        raise ValueError(f"Unknown Bio-ORACLE scenario {value!r}; choices: {choices}") from exc


def _resolve_layer(value: str) -> str:
    key = _normalise(value)
    try:
        return CATALOG_LAYERS[key]
    except KeyError as exc:
        choices = ", ".join(("surface", "benthic_min", "benthic_mean", "benthic_max"))
        raise ValueError(f"Unknown Bio-ORACLE layer {value!r}; choices: {choices}") from exc


def _layer_key(value: str) -> str:
    """Return the catalog-facing layer key for compatibility checks."""
    key = _normalise(value)
    return {
        "surf": "surface",
        "min": "benthic_min",
        "mean": "benthic_mean",
        "max": "benthic_max",
    }.get(key, key)


def _error(code: str, message: str, *, missing: Iterable[str] = ()) -> dict:
    return {
        "ok": False,
        "code": code,
        "message": message,
        "missing": list(missing),
        "remote_io": False,
        "choices": list_catalog_variables(),
    }


def validate_enrichment_selection(
    *,
    variables: list[str] | None,
    scenarios: list[str] | None,
    depth_layer: str | None,
    statistic: str | None,
    target_year: int | None,
) -> dict:
    """Validate and canonicalize the complete user selection before HTTP."""
    missing = [
        name
        for name, value in (
            ("variables", variables),
            ("scenarios", scenarios),
            ("depth_layer", depth_layer),
            ("statistic", statistic),
        )
        if value is None or (isinstance(value, (list, tuple)) and not value)
    ]
    if missing:
        return _error(
            "selection_required",
            "Choisis les variables, scénarios, couche verticale et statistique avant l'enrichissement.",
            missing=missing,
        )

    try:
        variable_specs = [resolve_catalog_variable(value) for value in variables or []]
    except ValueError as exc:
        return _error("unknown_variable", str(exc))
    canonical_variables = list(dict.fromkeys(spec.key for spec in variable_specs))

    try:
        canonical_scenarios = list(dict.fromkeys(_resolve_scenario(value) for value in scenarios or []))
    except ValueError as exc:
        return _error("unknown_scenario", str(exc))

    try:
        canonical_layer = _resolve_layer(depth_layer or "")
    except ValueError as exc:
        return _error("unknown_layer", str(exc))

    try:
        canonical_statistic = resolve_catalog_statistic(variable_specs[0], statistic or "")
        for spec in variable_specs[1:]:
            resolve_catalog_statistic(spec, statistic or "")
    except ValueError as exc:
        return _error("statistic_not_available", str(exc))

    if any(_layer_key(depth_layer or "") not in spec.layers for spec in variable_specs):
        return _error(
            "layer_not_available",
            "La couche verticale choisie n'est pas disponible pour toutes les variables sélectionnées.",
        )

    is_future = any(scenario != "baseline" for scenario in canonical_scenarios)
    if is_future and target_year is None:
        return _error(
            "target_year_required",
            "Une année cible est obligatoire pour les scénarios SSP.",
            missing=("target_year",),
        )
    if target_year is not None:
        try:
            target_year = int(target_year)
        except (TypeError, ValueError):
            return _error("invalid_target_year", f"Année Bio-ORACLE invalide : {target_year!r}.")
        if is_future and target_year not in set(range(2020, 2100, 10)):
            return _error(
                "target_year_unavailable",
                "Les scénarios SSP sont disponibles par tranches décennales de 2020 à 2090.",
            )
        if target_year < 1800 or target_year > 2200:
            return _error("invalid_target_year", f"Année Bio-ORACLE invalide : {target_year}.")

    return {
        "ok": True,
        "variables": canonical_variables,
        "variable_specs": variable_specs,
        "scenarios": canonical_scenarios,
        "scenario_display_names": [
            SCENARIO_DISPLAY_NAMES[scenario] for scenario in canonical_scenarios
        ],
        "depth_layer": canonical_layer,
        "depth_layer_display": LAYER_DISPLAY_NAMES[canonical_layer],
        "statistic": canonical_statistic,
        "target_year": target_year if is_future else None,
        "remote_io": False,
    }
