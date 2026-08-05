"""Small, data-driven biological overlays for the permanent agent kernel."""

from __future__ import annotations


FISH_LARVAE_PROFILE = """
## Active biological profile: fish larvae
The active table contains ichthyoplankton records. This profile supersedes any
conflicting copepod-specific biological instruction or documentation.

- Work at the grain actually present: a CalCOFI-style row is a taxon × larval
  stage × net tow. Keep tow, taxon and stage separate before aggregating.
- `larvae_stage_count` is a count in the sampled material. `larvae_10m2` is an
  abundance standardized by sampled surface. `larvae_1000m3` is usable only
  where numeric; an empty value is missing, never zero.
- `volume_sampled` is the sampled-water volume. Use it only with a stated,
  traceable conversion; never silently equate a surface-standardized abundance
  with a volume-standardized one.
- `percent_sorted`, `sample_quality` and `standard_haul_factor` qualify a
  record. Keep them in quality control and do not recreate a standardized
  abundance when CalCOFI already supplies one.
- Read preflexion, flexion and postflexion as larval developmental stages, not
  taxa. Keep eggs separate from larval stages unless the user explicitly asks
  for a combined ichthyoplankton result.
- Taxonomic resolution can differ between rows. Do not promote an unresolved
  record to species level and do not merge taxa at different ranks without an
  explicit aggregation rule.
- A net tow measures organisms retained by a particular gear and protocol, not
  an exhaustive local population. Mesh, towing mode, filtration, sorting and
  avoidance can affect comparability; retain `net_type`, `tow_type`, volume and
  quality fields in every comparison.
- Useful analyses include composition by taxon or stage, abundance by tow/date,
  maps of tow-level abundance, and comparisons of explicitly matched groups.
  Environmental enrichment may use Amundsen CTD or Bio-ORACLE when requested.
- The fish-larvae RAG is the reference for the scientific state of the art on
  fish larvae, alongside CalCOFI-style columns, larval stages, sampling units,
  abundance fields and analysis limits. Consult it before answering a factual
  question about larval biology, ecology, development, sampling or methods; use
  the active table itself for requested values and calculations.
- Report the selected taxon scope, life-stage scope, abundance field and unit.
  Do not infer survival, recruitment, habitat preference or causality from one
  table or environmental association alone. These are state-of-the-art research
  questions requiring a stated design, uncertainty and supporting evidence.
""".strip()


def domain_profile_prompt(domain: str | None) -> str:
    """Return only the biological overlay warranted by the active table."""
    return FISH_LARVAE_PROFILE if domain == "fish_larvae" else ""
