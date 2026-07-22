"""Geographic zone tool for NeoLab copepod data.

Backed by core.geo + the polygon registry built from IHO Marine Regions v3 +
NeoLab cuts (Cap Henrietta Maria → Pointe Louis-XIV for James/Hudson; Cap
Hopes Advance → Cape Chidley for Ungava/Hudson Strait).

Replaces the old `get_zone_filter` (hand-typed bboxes) — bbox values are now
derived from the actual polygons so they are tight and accurate. The polygon
WKT is also returned so downstream tools (or run_pandas) can apply a precise
in-polygon filter rather than a loose bbox filter.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from langchain_core.tools import tool
from shapely.geometry.base import BaseGeometry

from core.geo import (
    Registry,
    assign_zones,
    filter_by_zone as _core_filter_by_zone,
    load_registry,
    resolve_zone,
    zone_family,
)
from tools.dataset_registry import (
    dataset_variable_name,
    loaded_file_dataset,
    store_dataset,
)
from tools.session_store import SessionStore, default_store
from tools.tool_result import blocked, success


_REGISTRY_PATH = Path(__file__).parent.parent / "data" / "geo" / "zones_registry.geojson"


@lru_cache(maxsize=1)
def _registry() -> Registry:
    return load_registry(_REGISTRY_PATH)


def _normalise(text: str) -> str:
    return re.sub(r"[''`]", "'", text.lower().strip())


def _match_canonical(zone_name: str) -> str | None:
    """Résout un nom utilisateur vers le canonical du registry, via aliases.

    Stratégie : match exact (normalisé) sur canonical ou aliases, puis
    fallback substring (tolérant aux fautes courantes type 'baie ungava').
    """
    key = _normalise(zone_name)
    reg = _registry()
    for zone in reg.zones:
        if key == _normalise(zone.canonical):
            return zone.canonical
        for alias in zone.aliases:
            if key == _normalise(alias):
                return zone.canonical
    for zone in reg.zones:
        candidates = [zone.canonical, *zone.aliases]
        for cand in candidates:
            n = _normalise(cand)
            if key in n or n in key:
                return zone.canonical
    return None


def _bbox_from_polygon(polygon: BaseGeometry) -> dict[str, float]:
    minx, miny, maxx, maxy = polygon.bounds
    return {"south": miny, "west": minx, "north": maxy, "east": maxx}


@tool(response_format="content_and_artifact")
def get_zone_info(zone_name: str) -> dict:
    """Resolve a named NeoLab zone to canonical name, bbox, aliases and filter.

    Two layered families coexist :
    - IHO zones (mers/baies/détroits physiques) : "Baie d'Ungava",
      "Mer du Labrador", "Hudson Bay", "Hawke Channel", "Arctique"…
    - MEOW ecoregions (écorégions Spalding 2007, peer-reviewed) : passe le
      nom ECOREGION exact (ex. "Hudson Complex", "Northern Labrador",
      "Lancaster Sound", "West Greenland Shelf", "Gulf of St. Lawrence -
      Eastern Scotian Shelf") OU avec le préfixe explicite "MEOW: <ECOREGION>".

    Pour downstream EcoTaxa / Bio-ORACLE / filter_dataframe_by_zone : passer
    `zone_name` plutôt que copier le WKT. `polygon_wkt_preview` est debug-only ;
    `bbox` est en degrés décimaux.
    """
    canonical = _match_canonical(zone_name)
    if canonical is None:
        payload = {
            "error": f"Zone '{zone_name}' not recognised.",
            "available_zones": [z.canonical for z in _registry().zones],
        }
        return blocked(
            payload["error"],
            content=payload,
            provenance={"source": "NeoLab zone registry"},
        )

    zone = resolve_zone(canonical, registry=_registry())
    polygon = zone["polygon"]
    bbox = _bbox_from_polygon(polygon)

    aliases = next(
        (z.aliases for z in _registry().zones if z.canonical == canonical),
        (),
    )

    # Le WKT complet d'une zone IHO peut atteindre 480 KB (Baie d'Hudson),
    # ce qui sature le contexte LLM et se fait tronquer par MAX_TOOL_RESULT_CHARS.
    # On expose seulement un preview pour log / debug ; les tools aval
    # (find_ecotaxa_*_in_region, query_bio_oracle_zones) prennent `zone_name`
    # directement et résolvent le polygone côté Python sans passer par le LLM.
    full_wkt = polygon.wkt
    preview = full_wkt[:160] + (
        f"... ({len(full_wkt)} chars total — pass zone_name to downstream tools)"
        if len(full_wkt) > 160 else ""
    )

    payload = {
        "canonical": canonical,
        "source": zone["source"],
        "bbox": bbox,
        "polygon_wkt_preview": preview,
        "aliases": list(aliases),
        "usage_hint": (
            f"For a loaded local file, call filter_dataframe_by_zone with "
            f"zone_name='{canonical}'. For EcoTaxa / Bio-ORACLE queries, pass "
            f"zone_name='{canonical}' to the downstream tool. Do NOT copy the "
            "polygon_wkt through the LLM."
        ),
    }
    return success(
        f"Zone résolue : {canonical}.",
        content=payload,
        provenance={"source": str(zone["source"]), "zone": canonical},
        method="polygon registry lookup",
        metrics={"bbox": bbox},
    )


def make_geo_tools(thread_id: str, *, store: SessionStore | None = None) -> list:
    """Session-aware geo tools (filter_dataframe_by_zone).

    Returned alongside the stateless module-level ``get_zone_info`` in
    ``agent.py``. The filter tool needs the per-thread SessionStore to read
    the latest loaded DataFrame and persist the filtered subset under a new
    variable name.
    """
    _store = store or default_store

    @tool(response_format="content_and_artifact")
    def filter_dataframe_by_zone(
        zone_name: str,
        lat_col: str = "latitude",
        lon_col: str = "longitude",
        source_variable: str | None = None,
    ) -> dict:
        """Filtre le DataFrame chargé pour ne garder que les lignes dont
        (lat, lon) tombent **strictement dans le polygone IHO** de la zone.

        Précision polygone (point-in-polygon shapely) — pas un filtre bbox.
        Utilise ce tool dès que l'utilisateur demande de filtrer / découper /
        garder uniquement les stations d'une zone nommée sur un fichier
        chargé. N'utilise PAS run_pandas + shapely.wkt à la main : ce tool
        résout le polygone côté Python sans transporter le WKT par le LLM.

        Parameters
        ----------
        zone_name : str
            Nom de la zone (FR/EN/alias). Mêmes zones supportées que
            ``get_zone_info``.
        lat_col, lon_col : str
            Noms des colonnes lat/lon dans le df. Défaut : 'latitude'
            / 'longitude' (convention NeoLab EcoTaxa/Amundsen).
        source_variable : str, optional
            Variable persistante à filtrer. Par défaut, le filtre repart du
            **fichier chargé** (load_file), pas du dernier sous-ensemble actif :
            filtrer une zone à l'intérieur d'un sous-ensemble d'une AUTRE zone
            donnerait 0 ligne. Passe ce paramètre pour filtrer explicitement un
            sous-ensemble précédent.

        Returns
        -------
        dict : {zone_canonical, variable_name, n_in, n_out, lat_col, lon_col}
            ``variable_name`` est le nom du df filtré dans la session
            (accessible via run_pandas / run_graph). ``rebased_on`` indique le
            nom de la variable réellement filtrée quand le défaut a re-ancré sur
            le fichier chargé plutôt que sur le df actif.
        """
        session = _store.get(thread_id)
        if not session or session.get("df") is None:
            return blocked("Aucun fichier chargé. Utilise load_file d'abord.")

        rebased_from: str | None = None
        if source_variable:
            source_session = _store.get(f"{thread_id}:dataset:{source_variable}")
            if not source_session or source_session.get("df") is None:
                return blocked(
                    f"Variable source inconnue : {source_variable}. "
                    "Utilise le nom exact retourné par load_file ou un tool précédent."
                )
        else:
            source_session = session

        # A zone filter must start from the loaded file, never from a subset of
        # another zone (see docs/e2e/cartes-samples-labrador-2026). If the
        # resolved source — whether the active df or an explicitly passed
        # subset — is itself a zone-derived subset, re-anchor on the canonical
        # loaded file. Filtering a zone from the full file is always at least as
        # correct as filtering it from a subset of a different zone: a subset
        # can only drop rows the file has, producing the false "0 in N" the
        # agent kept reporting.
        resolved_meta = source_session.get("meta") or {}
        resolved_var = resolved_meta.get("variable_name")
        if str(resolved_meta.get("source", "")).startswith("filter_by_zone:"):
            loaded = loaded_file_dataset(_store, thread_id)
            loaded_var = ((loaded or {}).get("meta") or {}).get("variable_name")
            if loaded and loaded_var and loaded_var != resolved_var:
                rebased_from = resolved_var
                source_session = loaded
        df = source_session["df"]

        canonical = _match_canonical(zone_name)
        if canonical is None:
            return blocked(
                f"Zone '{zone_name}' inconnue du registry. "
                f"Zones disponibles : {[z.canonical for z in _registry().zones]}"
            )

        missing = [c for c in (lat_col, lon_col) if c not in df.columns]
        if missing:
            return blocked(
                f"Colonnes absentes du DataFrame : {missing}. "
                f"Colonnes disponibles : {list(df.columns)}. "
                "Passe lat_col / lon_col explicites."
            )

        kept = _core_filter_by_zone(
            df, canonical, lat_col=lat_col, lon_col=lon_col, registry=_registry(),
        )

        source_details = source_session.get("meta") or {}
        source_meta = source_details.get("source", "df")
        source_stem = source_meta.split(":", 1)[-1]
        variable_name = dataset_variable_name(
            "in", canonical, source_stem,
        )
        store_dataset(
            _store, thread_id, kept,
            variable_name=variable_name,
            meta={
                "source": f"filter_by_zone:{canonical}",
                "parent_source": source_meta,
                "zone_canonical": canonical,
                "lat_col": lat_col,
                "lon_col": lon_col,
                "n_rows": int(len(kept)),
            },
            # Keep the source table active. The zone subset remains available
            # under its explicit variable name and must be selected explicitly
            # by downstream analysis; otherwise a geographic exploration can
            # silently replace an active join/file.
            latest_alias=None,
            set_active=False,
        )

        result = {
            "zone_canonical": canonical,
            "variable_name": variable_name,
            "n_in": int(len(kept)),
            "n_out": int(len(df) - len(kept)),
            "lat_col": lat_col,
            "lon_col": lon_col,
            "source_variable": source_details.get("variable_name") or source_variable,
        }
        if rebased_from is not None:
            result["rebased_on"] = source_details.get("variable_name")
            result["note"] = (
                f"Filtre re-ancré sur le fichier chargé "
                f"`{result['source_variable']}` au lieu du sous-ensemble de zone "
                f"`{rebased_from}` : un filtre de zone repart toujours du fichier "
                f"de travail, jamais d'un sous-ensemble d'une autre zone."
            )
        return success(
            f"{len(kept)} lignes conservées dans `{variable_name}` pour {canonical}.",
            content=result,
            data_ref=variable_name,
            provenance={"source": str(source_meta), "zone": canonical},
            persisted=True,
            method="polygon point-in-polygon filter",
            metrics={"rows_in": int(len(kept)), "rows_out": int(len(df) - len(kept))},
        )

    _FAMILY_LABELS = {
        "auto": "mers/baies/détroits (IHO) + écorégions MEOW en complément",
        "iho": "mers / baies / détroits (IHO)",
        "meow": "écorégions marines (MEOW Spalding 2007)",
        "composite": "zones composites NeoLab (Nunavik, Arctique, Hawke Channel)",
        "all": "toutes les zones (plus spécifique en cas de chevauchement)",
    }

    @tool(response_format="content_and_artifact")
    def split_dataframe_by_zone(
        lat_col: str = "latitude",
        lon_col: str = "longitude",
        family: str = "auto",
        station_col: str | None = None,
        source_variable: str | None = None,
    ) -> dict:
        """Découpe le DataFrame chargé par zone aquatique et l'annote d'une
        colonne `zone`, puis renvoie le regroupement par zone.

        À utiliser dès que l'utilisateur demande de **découper / répartir /
        ventiler / grouper les stations par mer, baie, détroit, secteur ou
        zone** sur un fichier chargé — c.-à-d. quand il n'y a PAS de nom de zone
        unique à filtrer (sinon utilise `filter_dataframe_by_zone`). Chaque ligne
        est rattachée par point-in-polygon à la zone du registre IHO/NeoLab dans
        laquelle elle tombe (la plus spécifique en cas de chevauchement).

        N'utilise PAS `run_pandas` avec `STATION_NAME` comme substitut de zone :
        une station n'est pas une zone géographique. Ce tool crée la vraie
        colonne `zone`, réutilisable ensuite dans `run_graph` (couleur par zone,
        petits multiples par zone) ou `run_pandas`.

        Parameters
        ----------
        lat_col, lon_col : str
            Colonnes lat/lon. Défaut : 'latitude' / 'longitude'.
        family : str
            Découpage : 'auto' (défaut, couverture maximale : mers/baies/détroits
            IHO puis écorégions MEOW pour les points hors IHO), 'iho'
            (mers/baies/détroits physiques seulement), 'meow' (écorégions
            seulement), 'composite' (Nunavik/Arctique/Hawke Channel), ou 'all'.
        station_col : str, optional
            Si fourni, chaque zone rapporte aussi le nombre de stations
            distinctes (pas seulement le nombre de lignes).
        source_variable : str, optional
            Variable persistante à découper. Par défaut, repart du fichier
            chargé (jamais d'un sous-ensemble déjà filtré sur une seule zone,
            qui ne donnerait qu'une zone).

        Returns
        -------
        dict : {variable_name, zone_column, family, n_rows, n_missing,
            n_outside, groups}
            `groups` liste `{zone, n_rows[, n_stations]}` triée par n_rows
            décroissant, avec les buckets explicites `Hors zone référencée`
            (point hors registre) et `Sans coordonnées`. `variable_name` est le
            df annoté persisté dans la session (accessible via run_pandas /
            run_graph).
        """
        family = (family or "iho").strip().lower()
        if family not in _FAMILY_LABELS:
            return blocked(
                f"Famille de découpage inconnue : '{family}'. "
                f"Valeurs acceptées : {sorted(_FAMILY_LABELS)}."
            )

        session = _store.get(thread_id)
        if not session or session.get("df") is None:
            return blocked("Aucun fichier chargé. Utilise load_file d'abord.")

        if source_variable:
            source_session = _store.get(f"{thread_id}:dataset:{source_variable}")
            if not source_session or source_session.get("df") is None:
                return blocked(
                    f"Variable source inconnue : {source_variable}. "
                    "Utilise le nom exact retourné par load_file ou un tool précédent."
                )
        else:
            source_session = session

        # Un découpage par zone repart du fichier chargé, jamais d'un sous-ensemble
        # déjà restreint à une seule zone (qui ne produirait qu'un groupe). Même
        # re-ancrage que filter_dataframe_by_zone (docs/e2e/cartes-samples-labrador).
        rebased_from: str | None = None
        resolved_meta = source_session.get("meta") or {}
        resolved_var = resolved_meta.get("variable_name")
        if str(resolved_meta.get("source", "")).startswith("filter_by_zone:"):
            loaded = loaded_file_dataset(_store, thread_id)
            loaded_var = ((loaded or {}).get("meta") or {}).get("variable_name")
            if loaded and loaded_var and loaded_var != resolved_var:
                rebased_from = resolved_var
                source_session = loaded
        df = source_session["df"]

        needed = [lat_col, lon_col] + ([station_col] if station_col else [])
        missing_cols = [c for c in needed if c not in df.columns]
        if missing_cols:
            return blocked(
                f"Colonnes absentes du DataFrame : {missing_cols}. "
                f"Colonnes disponibles : {list(df.columns)}. "
                "Passe lat_col / lon_col / station_col explicites."
            )

        labels = assign_zones(
            df, _registry(), lat_col=lat_col, lon_col=lon_col, family=family,
        )
        annotated = df.copy()
        annotated["zone"] = labels.to_numpy()

        counts = labels.value_counts()
        station_counts = None
        if station_col:
            station_counts = (
                annotated.groupby("zone")[station_col].nunique().to_dict()
            )

        groups: list[dict] = []
        for zone_name, n_rows in counts.items():
            entry = {"zone": zone_name, "n_rows": int(n_rows)}
            if station_counts is not None:
                entry["n_stations"] = int(station_counts.get(zone_name, 0))
            groups.append(entry)

        n_missing = int((labels == "Sans coordonnées").sum())
        n_outside = int((labels == "Hors zone référencée").sum())

        source_details = source_session.get("meta") or {}
        source_meta = source_details.get("source", "df")
        source_stem = source_meta.split(":", 1)[-1]
        variable_name = dataset_variable_name("zoned", family, source_stem)
        store_dataset(
            _store, thread_id, annotated,
            variable_name=variable_name,
            meta={
                "source": f"split_by_zone:{family}",
                "parent_source": source_meta,
                "zone_column": "zone",
                "family": family,
                "lat_col": lat_col,
                "lon_col": lon_col,
                "n_rows": int(len(annotated)),
            },
            latest_alias=variable_name,
        )

        named_zones = [g for g in groups if g["zone"] not in
                       ("Hors zone référencée", "Sans coordonnées")]
        located = int(len(annotated)) - n_missing
        outside_ratio = round(n_outside / located, 3) if located else 0.0
        result = {
            "variable_name": variable_name,
            "zone_column": "zone",
            "family": family,
            "family_label": _FAMILY_LABELS[family],
            "n_rows": int(len(annotated)),
            "n_zones": len(named_zones),
            "n_missing": n_missing,
            "n_outside": n_outside,
            "outside_ratio": outside_ratio,
            "groups": groups,
        }
        # Aucun tuilage ne couvre tout l'océan (côtes, estuaires, haute mer).
        # Au-delà de 25 % hors zone, proposer un découpage plus couvrant.
        _WIDER_FAMILY = {"iho": "auto", "composite": "auto", "auto": "all"}
        if family in _WIDER_FAMILY and outside_ratio >= 0.25:
            alt = _WIDER_FAMILY[family]
            result["coverage_suggestion"] = (
                f"{n_outside}/{located} lignes géolocalisées hors des zones "
                f"'{_FAMILY_LABELS[family]}'. Pour une couverture plus large, "
                f"relancer avec family='{alt}'."
            )
        if rebased_from is not None:
            result["rebased_on"] = source_details.get("variable_name")
            result["note"] = (
                f"Découpage re-ancré sur le fichier chargé au lieu du "
                f"sous-ensemble de zone `{rebased_from}`."
            )

        # Le message visible est une table markdown prête à recopier telle
        # quelle : le modèle doit restituer ces zones/valeurs sans les
        # reconstruire de mémoire (sinon il fabrique des zones et des comptes
        # inexistants — défaut de restitution observé en e2e). Les données
        # structurées restent dans l'artifact `metrics` pour l'aval.
        header = ["Zone", "Lignes"] + (["Stations"] if station_col else [])
        sep = ["---", "---:"] + (["---:"] if station_col else [])
        lines = [
            f"# Découpage par {_FAMILY_LABELS[family]} — `{variable_name}`",
            "",
            f"{len(annotated)} lignes · {len(named_zones)} zone(s) · "
            f"{n_outside} hors zone · {n_missing} sans coordonnées.",
            "",
            "| " + " | ".join(header) + " |",
            "|" + "|".join(sep) + "|",
        ]
        for g in groups:
            cells = [g["zone"], str(g["n_rows"])]
            if station_col:
                cells.append(str(g.get("n_stations", 0)))
            lines.append("| " + " | ".join(cells) + " |")
        if "coverage_suggestion" in result:
            lines += ["", f"⚠️ {result['coverage_suggestion']}"]
        if "note" in result:
            lines += ["", result["note"]]
        markdown = "\n".join(lines)

        return success(
            markdown,
            content=markdown,
            data_ref=variable_name,
            provenance={"source": str(source_meta), "family": family},
            persisted=True,
            method="polygon point-in-polygon assignment",
            metrics={
                "zones": len(named_zones),
                "outside": n_outside,
                "missing": n_missing,
                "outside_ratio": outside_ratio,
                "structured": result,
            },
        )

    return [filter_dataframe_by_zone, split_dataframe_by_zone]
