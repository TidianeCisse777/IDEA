"""Tests du filtrage taxonomique strict des copépodes."""

import pandas as pd
import pytest
import inspect

from core.copepod_taxonomy import copepod_hierarchy_mask


def test_copepod_hierarchy_mask_includes_descendants_and_excludes_substrings():
    df = pd.DataFrame(
        {
            "object_annotation_hierarchy": [
                "Biota>Animalia>Arthropoda>Copepoda>Calanoida",
                "Biota | Animalia | Arthropoda | Copepoda | Cyclopoida",
                "Biota;Animalia;NotCopepoda;Example",
                None,
                "",
            ]
        }
    )

    assert copepod_hierarchy_mask(df).tolist() == [True, True, False, False, False]


def test_copepod_hierarchy_mask_requires_hierarchy_column():
    df = pd.DataFrame({"object_annotation_category": ["Calanoida"]})

    with pytest.raises(ValueError, match="object_annotation_hierarchy"):
        copepod_hierarchy_mask(df)


def test_copepod_hierarchy_mask_does_not_accept_an_alternate_hierarchy_column():
    from core.copepod_taxonomy import copepod_hierarchy_mask

    assert list(inspect.signature(copepod_hierarchy_mask).parameters) == ["df"]
