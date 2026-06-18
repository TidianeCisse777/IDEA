"""EcoTaxa project-level summary — overview without full export.

Mirror of :mod:`sample_summary` at the project level. Combines the local
cache (sample envelope : count, dates, bbox, instruments) with the live
EcoTaxa endpoint ``/project_set/taxo_stats`` (project-level V/P/D/U counts
and per-taxon stats).

Used to scan candidate projects before drilling into their samples or
launching a full export.
"""

from __future__ import annotations

from core.ecotaxa_browser.cache.repo import query_project_envelopes
from tools.ecotaxa_client import EcotaxaClient


def _open_cache():
    # Indirection so the cache path can be patched per-test via the same
    # _cache_db_path() symbol used by region/observations.
    from core.ecotaxa_browser.region import _open_cache as _shared_open
    return _shared_open()


def summarize_projects(project_ids: list[int]) -> list[dict]:
    """Return one overview dict per project.

    Args:
        project_ids: EcoTaxa project IDs to summarise.

    Returns:
        One dict per project (projects absent from the cache are skipped)
        with the following keys :
        - ``project_id`` (int)
        - ``n_samples`` (int) — from cache
        - ``date_min`` / ``date_max`` (ISO str) — from cache
        - ``bbox`` (dict ``{south, west, north, east}``) — from cache
        - ``instruments`` (list[str]) — from cache
        - ``nb_validated``, ``nb_predicted``, ``nb_dubious``,
          ``nb_unclassified`` (int) — project-level counts via
          ``/project_set/taxo_stats``
        - ``used_taxa`` (list[int]) — taxa reported by EcoTaxa for the project
        - ``per_taxon`` (list[dict]) — names and counts for taxa, sorted by
          descending V+P+D+U
    """
    if not project_ids:
        return []

    conn = _open_cache()
    try:
        envelopes = query_project_envelopes(conn, project_ids)
    finally:
        conn.close()

    if not envelopes:
        return []

    client = EcotaxaClient()
    client.login()
    cached_project_ids = [int(pid) for pid in project_ids if pid in envelopes]
    aggregate_rows = client.project_taxo_stats(cached_project_ids)
    taxon_rows = client.project_taxo_stats(cached_project_ids, taxa_ids="all")

    by_project_total: dict[int, dict] = {}
    for row in aggregate_rows:
        pid = int(row.get("projid") or row.get("project_id") or 0)
        if pid in envelopes:
            by_project_total[pid] = row

    by_project_taxa: dict[int, list[dict]] = {pid: [] for pid in envelopes}
    for row in taxon_rows:
        pid = int(row.get("projid") or row.get("project_id") or 0)
        if pid in by_project_taxa:
            by_project_taxa[pid].append(row)

    # Resolve all unique taxon IDs in one pass.
    taxon_ids: set[int] = set()
    for rows in by_project_taxa.values():
        for r in rows:
            for tid in r.get("used_taxa") or []:
                if tid is not None:
                    taxon_ids.add(int(tid))
    name_by_id: dict[int, str] = {}
    for tid in taxon_ids:
        try:
            taxon = client.get_taxon(tid)
            name_by_id[tid] = str(
                taxon.get("display_name") or taxon.get("text")
                or taxon.get("name") or tid
            )
        except Exception:
            name_by_id[tid] = str(tid)

    out: list[dict] = []
    for pid in project_ids:
        env = envelopes.get(pid)
        if env is None:
            continue
        total = by_project_total.get(pid) or {}
        v = int(total.get("nb_validated") or 0)
        p = int(total.get("nb_predicted") or 0)
        d = int(total.get("nb_dubious") or 0)
        u = int(total.get("nb_unclassified") or 0)
        per_taxon: list[dict] = []
        for r in by_project_taxa.get(pid, []):
            for tid in r.get("used_taxa") or []:
                if tid is not None:
                    taxon_id = int(tid)
                    tv = int(r.get("nb_validated") or 0)
                    tp = int(r.get("nb_predicted") or 0)
                    td = int(r.get("nb_dubious") or 0)
                    tu = int(r.get("nb_unclassified") or 0)
                    per_taxon.append({
                        "taxon_id": taxon_id,
                        "name": name_by_id.get(taxon_id, str(taxon_id)),
                        "nb_validated": tv,
                        "nb_predicted": tp,
                        "nb_dubious": td,
                        "nb_unclassified": tu,
                        "total": tv + tp + td + tu,
                    })
        per_taxon.sort(key=lambda t: (-int(t.get("total") or 0), str(t.get("name") or "")))
        used_sorted = [int(t["taxon_id"]) for t in per_taxon]
        out.append({
            "project_id": pid,
            "n_samples": env["n_samples"],
            "instruments": env["instruments"],
            "date_min": env["date_min"],
            "date_max": env["date_max"],
            "bbox": env["bbox"],
            "nb_validated": v,
            "nb_predicted": p,
            "nb_dubious": d,
            "nb_unclassified": u,
            "used_taxa": used_sorted,
            "per_taxon": per_taxon,
        })
    return out
