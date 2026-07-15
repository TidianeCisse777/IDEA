"""Stable names and persistence for downloaded DataFrames."""
from __future__ import annotations

import re
from numbers import Real

import pandas as pd

from tools.session_store import SessionStore

# --- Registre des sources fixes -------------------------------------------
# Alias sous lequel chaque source range son dernier résultat dans la session.
# UNE seule liste de référence : le côté écriture (store_dataset via ces
# constantes) et le côté lecture (data_tools._dataframe_vars) la partagent, donc
# une source enregistrée ici est forcément relue — plus de disparition en silence.
# Les noms dynamiques (filtres de zone, projets EcoPart par id) ne sont PAS ici :
# ils passent par le scan de préfixe `dataset:` / `ecopart:`.
ECOTAXA = "ecotaxa"
ECOPART = "ecopart"
CTD = "ctd"
CTD_ENRICHED = "ctd_enriched"
BIO_ORACLE = "bio_oracle"
OGSL = "ogsl"
OGSL_ENRICHED = "ogsl_enriched"
SQL = "sql"
ECOTAXA_ECOPART = "ecotaxa_ecopart"

SOURCE_ALIASES: tuple[str, ...] = (
    ECOTAXA,
    ECOPART,
    CTD,
    CTD_ENRICHED,
    BIO_ORACLE,
    OGSL,
    OGSL_ENRICHED,
    SQL,
    ECOTAXA_ECOPART,
)


def source_variable(alias: str) -> str:
    """Variable exposée à run_pandas/run_graph pour une source : df_{alias}."""
    return f"df_{alias}"


def _identifier_part(value: object) -> str:
    if isinstance(value, Real) and not isinstance(value, bool):
        number = f"{value:g}"
        if number.startswith("-"):
            number = f"m{number[1:]}"
        text = number
    else:
        text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def dataset_variable_name(source: str, *parts: object) -> str:
    """Return a predictable valid Python variable for one downloaded dataset."""
    tokens = [_identifier_part(source), *(_identifier_part(part) for part in parts)]
    tokens = [token for token in tokens if token]
    return f"df_{'_'.join(tokens)}"


# Stable session key that always points at the file the user loaded via
# load_file, even after a derived subset (e.g. filter_dataframe_by_zone) has
# overwritten the *active* df. Lets geographic filtering and the dataset capsule
# re-anchor on the canonical source instead of the last derived subset.
LOADED_FILE_KEY = "loaded_file"


def store_dataset(
    store: SessionStore,
    thread_id: str,
    dataframe: pd.DataFrame,
    *,
    variable_name: str,
    meta: dict,
    latest_alias: str | None = None,
    is_loaded_file: bool = False,
) -> None:
    """Persist a stable dataset and refresh current/latest aliases.

    ``is_loaded_file=True`` (set by load_file) also pins the dataset under the
    stable ``{thread_id}:loaded_file`` key so it stays reachable as the
    canonical source after later subsets take over the active slot.
    """
    dataset_meta = {**meta, "variable_name": variable_name}
    store.set(thread_id, dataframe, dataset_meta)
    if latest_alias:
        store.set(f"{thread_id}:{latest_alias}", dataframe, dataset_meta)
    store.set(f"{thread_id}:dataset:{variable_name}", dataframe, dataset_meta)
    if is_loaded_file:
        store.set(f"{thread_id}:{LOADED_FILE_KEY}", dataframe, dataset_meta)


def loaded_file_dataset(store: SessionStore, thread_id: str) -> dict | None:
    """Return the canonical loaded-file session entry, or None if absent.

    The entry mirrors what ``store.get`` returns elsewhere: a mapping with
    ``df`` and ``meta`` keys.
    """
    entry = store.get(f"{thread_id}:{LOADED_FILE_KEY}")
    if entry and entry.get("df") is not None:
        return entry
    return None


# Column prefixes added by each enrichment tool. Used to surface, in an enrich
# tool's reply, which enrichments the source table already carries — so chaining
# enrichments on the wrong (stale active) table becomes visible instead of silent.
_ENRICHMENT_PREFIXES = ("ecopart_", "amundsen_", "bio_oracle_", "ogsl_")


def enrichment_source_note(
    store: SessionStore,
    thread_id: str,
    source_df: pd.DataFrame,
    source_variable: str | None,
) -> str:
    """One-line provenance note naming the table being enriched and its prior enrichments.

    Call it right after resolving the source dataframe (before the new result is
    stored, which would overwrite the active-df metadata). When ``source_variable``
    is ``None`` the active session df is used and its variable name is read back from
    the session metadata.
    """
    name = source_variable
    if not name:
        session = store.get(thread_id)
        name = (session.get("meta") or {}).get("variable_name") if session else None
    name = name or "df actif"

    already = [
        f"{count} {prefix}*"
        for prefix in _ENRICHMENT_PREFIXES
        if (count := sum(1 for column in source_df.columns if str(column).startswith(prefix)))
    ]
    if already:
        return f"Table enrichie : `{name}` (déjà présent : {', '.join(already)})."
    return f"Table enrichie : `{name}`."
