"""Activation contracts for skills that access external data sources."""

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "filename,source",
    [
        ("ecotaxa_navigation.md", "EcoTaxa"),
        ("ecotaxa_query.md", "EcoTaxa"),
        ("ecopart_query.md", "EcoPart"),
        ("amundsen_ctd_query.md", "Amundsen CTD"),
        ("bio_oracle_query.md", "Bio-ORACLE"),
    ],
)
def test_external_skill_requires_explicit_source(filename, source):
    text = (Path("agents/skills") / filename).read_text()
    head = " ".join(text[:1200].split())
    assert "## Activation precondition" in head
    assert f"explicitly names {source}" in head
    assert "Do not load or apply this skill for generic" in head
