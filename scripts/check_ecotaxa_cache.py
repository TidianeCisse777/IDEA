#!/usr/bin/env python3
"""EcoTaxa cache preflight — gate agent startup on a healthy cache.

Called by ``start.sh`` after the MCP EcoTaxa server is up and BEFORE the
copepod-agent is launched. Reads the MCP ``/health`` JSON payload (from stdin
or a fetched URL), validates that the cache is populated, and exits non-zero
with a readable message when it is not, so the agent never comes up on top of
an empty or broken cache.

Usage:
    curl -sf http://localhost:8001/health | python3 scripts/check_ecotaxa_cache.py
    python3 scripts/check_ecotaxa_cache.py http://localhost:8001/health

Thresholds (env-overridable):
    ECOTAXA_CACHE_MIN_SAMPLES   default 1
    ECOTAXA_CACHE_MIN_PROJECTS  default 1
    ECOTAXA_CACHE_MAX_AGE_HOURS default 168 (7 days) — warning only
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field


@dataclass
class CacheHealthResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def validate_cache_health(
    payload: dict,
    *,
    min_samples: float | None = None,
    min_projects: float | None = None,
    max_age_hours: float | None = None,
) -> CacheHealthResult:
    """Validate a /health payload. Block on emptiness or a stale schema.

    Blocking (ok=False): missing cache section, stale/unknown schema, samples
    below minimum, or projects below minimum — the cache cannot serve current
    queries.
    Non-blocking (warnings): a later failed sync over still-usable data, or a
    stale cache older than the age threshold.
    """
    if min_samples is None:
        min_samples = _env_float("ECOTAXA_CACHE_MIN_SAMPLES", 1)
    if min_projects is None:
        min_projects = _env_float("ECOTAXA_CACHE_MIN_PROJECTS", 1)
    if max_age_hours is None:
        max_age_hours = _env_float("ECOTAXA_CACHE_MAX_AGE_HOURS", 168.0)

    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(payload, dict) or "cache" not in payload:
        return CacheHealthResult(
            ok=False,
            errors=[
                "Réponse /health inattendue (pas de section `cache`) — "
                "le serveur MCP EcoTaxa n'a pas pu ouvrir le cache."
            ],
        )

    cache = payload.get("cache")
    if not cache:
        return CacheHealthResult(
            ok=False,
            errors=[
                "Cache EcoTaxa illisible ou schéma absent — "
                "impossible d'ouvrir la base ou de lire ses compteurs."
            ],
        )

    samples = cache.get("samples_indexed") or 0
    projects = cache.get("projects_indexed") or 0

    if cache.get("schema_current") is not True:
        errors.append(
            "Schéma du cache EcoTaxa absent ou obsolète "
            f"(version détectée : {cache.get('schema_version', 'inconnue')}). "
            "Attendre la fin d'un sync complet avant de démarrer."
        )

    if samples < min_samples:
        errors.append(
            f"Cache vide ou insuffisant : {samples} samples indexés "
            f"(minimum requis : {int(min_samples)}). Lancer un sync avant de démarrer."
        )
    if projects < min_projects:
        errors.append(
            f"Aucun projet indexé (minimum requis : {int(min_projects)}). "
            "Vérifier les credentials EcoTaxa et relancer un sync."
        )

    last_sync = cache.get("last_sync_status")
    if last_sync == "failed":
        warnings.append(
            "Dernier sync en échec (`failed`) — les données servies proviennent "
            "d'un sync antérieur. Vérifier la connectivité EcoTaxa."
        )

    age = cache.get("cache_age_hours")
    if age is not None and age > max_age_hours:
        warnings.append(
            f"Cache âgé de {age:.0f} h (seuil : {int(max_age_hours)} h). "
            "Envisager un resync pour rafraîchir l'index."
        )

    return CacheHealthResult(ok=not errors, errors=errors, warnings=warnings)


def _load_payload(argv: list[str]) -> dict:
    """Read the health payload from a URL arg or stdin."""
    if len(argv) > 1 and argv[1].startswith(("http://", "https://")):
        import urllib.request

        with urllib.request.urlopen(argv[1], timeout=10) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("aucune donnée /health reçue (stdin vide et pas d'URL)")
    return json.loads(raw)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    try:
        payload = _load_payload(argv)
    except Exception as exc:  # noqa: BLE001 — surface a clear preflight failure
        print(f"[cache-check] ÉCHEC : impossible de lire /health : {exc}", file=sys.stderr)
        return 2

    result = validate_cache_health(payload)
    for warning in result.warnings:
        print(f"[cache-check] AVERTISSEMENT : {warning}", file=sys.stderr)
    if not result.ok:
        for error in result.errors:
            print(f"[cache-check] ÉCHEC : {error}", file=sys.stderr)
        return 1

    cache = payload.get("cache") or {}
    print(
        f"[cache-check] OK — {cache.get('samples_indexed')} samples, "
        f"{cache.get('projects_indexed')} projets indexés."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
