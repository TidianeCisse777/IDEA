"""Deterministic biological profile selection for a loaded table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence


DomainName = Literal["copepods", "fish_larvae", "generic"]
Confidence = Literal["high", "low"]


@dataclass(frozen=True)
class DomainDetection:
    """One explainable profile selected from a table schema."""

    domain: DomainName
    confidence: Confidence
    evidence: tuple[str, ...]

    def as_metadata(self) -> dict[str, object]:
        return {
            "name": self.domain,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }


def _columns(columns: Sequence[object]) -> set[str]:
    return {str(column).strip().casefold() for column in columns}


def detect_domain_profile(columns: Sequence[object]) -> DomainDetection:
    """Classify only distinctive table schemas; never use the file name.

    Fish-larvae classification requires independent evidence for larval records,
    a net tow, and biological identification.  This prevents a generic plankton
    table with only a taxon column from being misclassified.
    """
    names = _columns(columns)
    larval = {
        "larvae_stage",
        "larvae_stage_count",
        "larvae_10m2",
        "larvae_1000m3",
    } & names
    tow = {"tow_type", "net_type", "volume_sampled"} & names
    taxonomy = {
        "scientific_name",
        "common_name",
        "itis_tsn",
        "calcofi_species_code",
    } & names
    if larval and tow and taxonomy:
        return DomainDetection(
            domain="fish_larvae",
            confidence="high",
            evidence=(
                f"larval records: {', '.join(sorted(larval))}",
                f"net tow: {', '.join(sorted(tow))}",
                f"taxonomy: {', '.join(sorted(taxonomy))}",
            ),
        )

    copepod = {"copepod_count", "copepod_abundance", "copepod_density"} & names
    if copepod:
        return DomainDetection(
            domain="copepods",
            confidence="high",
            evidence=(f"copepod metric: {', '.join(sorted(copepod))}",),
        )
    return DomainDetection(domain="generic", confidence="low", evidence=())
