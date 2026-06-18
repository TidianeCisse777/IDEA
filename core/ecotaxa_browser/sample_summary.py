"""EcoTaxa sample-level summary — V/P/D counts + top taxa per sample.

Light, read-only entry point used to *scan* a list of samples (typically the
output of ``samples_in_region``) before deciding which ones are worth a
full export via ``query_ecotaxa``. Hits the EcoTaxa endpoint
``/sample_set/taxo_stats`` once for the batch.
"""

from __future__ import annotations

from tools.ecotaxa_client import EcotaxaClient


def summarize_samples(sample_ids: list[int]) -> list[dict]:
    """Return per-sample classification breakdown.

    Args:
        sample_ids: EcoTaxa sample IDs to summarise.

    Returns:
        One dict per sample with:
        - ``sample_id`` (int)
        - ``projid`` (int)
        - ``nb_validated``, ``nb_predicted``, ``nb_dubious``,
          ``nb_unclassified`` (int) — aggregated across all taxa in the sample
        - ``used_taxa`` (list[int]) — taxon IDs observed in the sample
        - ``per_taxon`` (list[dict]) — ``[{taxon_id, name}, ...]`` resolved
          via the EcoTaxa taxonomy autocomplete (counts per taxon are NOT
          available at the sample level via this endpoint — use
          ``count_ecotaxa_taxa`` on the parent project for that)
    """
    if not sample_ids:
        return []

    client = EcotaxaClient()
    client.login()
    raw = client.sample_taxo_stats(sample_ids)

    # Collect all taxon IDs once, resolve names in a single pass.
    taxon_ids: set[int] = set()
    for entry in raw:
        for tid in entry.get("used_taxa") or []:
            if tid is not None:
                taxon_ids.add(int(tid))

    name_by_id: dict[int, str] = {}
    for tid in taxon_ids:
        try:
            taxon = client.get_taxon(tid)
            name_by_id[tid] = str(
                taxon.get("display_name")
                or taxon.get("text")
                or taxon.get("name")
                or tid
            )
        except Exception:
            name_by_id[tid] = str(tid)

    out: list[dict] = []
    for entry in raw:
        used = [int(t) for t in (entry.get("used_taxa") or []) if t is not None]
        out.append({
            "sample_id": int(entry["sample_id"]),
            "projid": int(entry.get("projid") or entry.get("project_id") or 0),
            "nb_validated": int(entry.get("nb_validated") or 0),
            "nb_predicted": int(entry.get("nb_predicted") or 0),
            "nb_dubious": int(entry.get("nb_dubious") or 0),
            "nb_unclassified": int(entry.get("nb_unclassified") or 0),
            "used_taxa": used,
            "per_taxon": [
                {"taxon_id": tid, "name": name_by_id.get(tid, str(tid))}
                for tid in used
            ],
        })
    return out
