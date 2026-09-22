"""Contracts for the FILET wide-to-long source representation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from populate_filet import STAGES, abundance_rows, stage_columns


def test_stage_contract_preserves_aggregate_and_missing_biomass_columns():
    assert STAGES[-1] == "ALL_STAGES"
    assert stage_columns("C1")[-2:] == (
        "C1_BIOMASS (µg C m-3 depth vol.)",
        "C1_BIOMASS (µg C m-3 flowmeter vol.)",
    )
    assert stage_columns("N1")[-2:] == (None, None)


def test_abundance_parser_keeps_explicit_zero_and_native_keys(tmp_path):
    header = ["SAMPLE_ID", "ANALYSIS_ID", "TAXON_ID"]
    values = ["42", "13", "Calanus sp."]
    for stage in STAGES:
        header.extend(column for column in stage_columns(stage) if column)
        values.extend("0" for column in stage_columns(stage) if column)
    path = tmp_path / "abundance.csv"
    path.write_text(",".join(header) + "\n" + ",".join(values) + "\n", encoding="utf-8")
    rows = list(abundance_rows(path))
    assert len(rows) == len(STAGES)
    assert rows[0][:6] == (2, "42", "13", "Calanus sp.", "C1", "0")
    assert rows[-1][4] == "ALL_STAGES"


def test_filet_zone_assignment_prefers_named_zone_and_preserves_statuses():
    from assign_filet_zones import zone_for

    named = ("Baie de Baffin", "IHO", {"type": "Polygon", "coordinates": [[[-2, -2], [2, -2], [2, 2], [-2, 2], [-2, -2]]]})
    meow = ("MEOW: Baffin Bay - Davis Strait", "MEOW", {"type": "Polygon", "coordinates": [[[-2, -2], [2, -2], [2, 2], [-2, 2], [-2, -2]]]})
    other = ("Détroit de Davis", "IHO", {"type": "Polygon", "coordinates": [[[-1, -1], [3, -1], [3, 3], [-1, 3], [-1, -1]]]})

    assert zone_for(0, 0, [named, meow]) == ("Baie de Baffin", "Baie de Baffin", "IHO", "assigned")
    assert zone_for(0, 0, [named, other])[3] == "ambiguous"
    assert zone_for(10, 10, [named])[3] == "outside"
    assert zone_for(None, 10, [named])[3] == "unresolved"
