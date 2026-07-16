"""TDD contract for the central runtime and presentation tool catalog."""

import sqlite3

import pytest

from tools import tool_catalog
from tools.tool_catalog import (
    LocalizedText,
    ToolPresentation,
    build_tool_catalog,
    resolve_user_language,
    validate_catalog,
)


@pytest.mark.parametrize(
    ("metadata", "accept_language", "expected"),
    [
        ({"language": "en"}, "fr-CA", "en"),
        ({"locale": "fr-CA"}, "en-US", "fr"),
        (None, "en-US,en;q=0.9", "en"),
        (None, "fr-CA;q=0,en-US;q=0.8", "en"),
        (None, "en-US;q=2", "fr"),
        (None, "de-DE", "fr"),
        ({"language": "de"}, "en-CA", "en"),
        (None, None, "fr"),
    ],
)
def test_resolve_user_language(metadata, accept_language, expected):
    assert resolve_user_language(metadata, accept_language) == expected


def test_localized_text_falls_back_to_french():
    label = LocalizedText(fr="Chargement", en="Loading")

    assert label.for_language("en") == "Loading"
    assert label.for_language("fr") == "Chargement"
    assert label.for_language("de") == "Chargement"


def test_validate_catalog_rejects_missing_metadata(monkeypatch):
    monkeypatch.setattr(tool_catalog, "TOOL_PRESENTATION", {})

    with pytest.raises(ValueError, match="missing metadata.*load_file"):
        validate_catalog({"load_file"})


def test_validate_catalog_rejects_orphan_metadata(monkeypatch):
    monkeypatch.setattr(
        tool_catalog,
        "TOOL_PRESENTATION",
        {
            "ghost_tool": ToolPresentation(
                label=LocalizedText(fr="Fantôme", en="Ghost"),
                family="core",
            )
        },
    )

    with pytest.raises(ValueError, match="orphan metadata.*ghost_tool"):
        validate_catalog(set())


def test_validate_catalog_rejects_source_result_without_source_identity(monkeypatch):
    monkeypatch.setattr(
        tool_catalog,
        "TOOL_PRESENTATION",
        {
            "source_tool": ToolPresentation(
                label=LocalizedText(fr="Source", en="Source"),
                family="source",
                source_result=True,
            )
        },
    )

    with pytest.raises(ValueError, match="source identity.*source_tool"):
        validate_catalog({"source_tool"})


@pytest.mark.parametrize(
    "presentation",
    [
        ToolPresentation(
            label=LocalizedText(fr="", en="Loading"),
            family="data",
        ),
        ToolPresentation(
            label=LocalizedText(fr="Chargement", en="Loading"),
            family="",
        ),
        ToolPresentation(
            label=LocalizedText(fr="Chargement", en="Loading"),
            family="data",
            progress=LocalizedText(fr="En cours", en=""),
        ),
    ],
)
def test_validate_catalog_rejects_incomplete_presentation(
    monkeypatch,
    presentation,
):
    monkeypatch.setattr(
        tool_catalog,
        "TOOL_PRESENTATION",
        {"load_file": presentation},
    )

    with pytest.raises(ValueError, match="incomplete presentation.*load_file"):
        validate_catalog({"load_file"})


def test_presentation_builder_rejects_one_sided_progress_translation():
    with pytest.raises(ValueError, match="progress requires both French and English"):
        tool_catalog._presentation(
            "Chargement",
            "Loading",
            "data",
            progress_fr="En cours",
        )


def test_build_tool_catalog_has_exact_mandatory_tool_count(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")  # "" présent = non configuré, résiste à load_dotenv

    catalog = build_tool_catalog("catalog-no-sql")

    assert len(catalog.tools) == 62
    assert len(catalog.names) == 62
    assert {tool.name for tool in catalog.tools} == catalog.names
    assert all(catalog.presentation(name) for name in catalog.names)


def test_build_tool_catalog_adds_exactly_three_optional_sql_tools(tmp_path, monkeypatch):
    db_path = tmp_path / "source.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE casts (id INTEGER PRIMARY KEY, station TEXT)")
    connection.commit()
    connection.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SQL_WORKSPACE_DIR", str(tmp_path / "workspace"))

    catalog = build_tool_catalog("catalog-with-sql")

    assert len(catalog.tools) == 65
    assert len(catalog.names) == 65
    assert {
        "list_sql_tables",
        "preview_sql_table",
        "copy_sql_query_to_workspace",
    } <= catalog.names
    assert all(
        catalog.presentation(name).label.fr.strip()
        and catalog.presentation(name).label.en.strip()
        for name in {
            "list_sql_tables",
            "preview_sql_table",
            "copy_sql_query_to_workspace",
        }
    )


def test_build_tool_catalog_propagates_unexpected_sql_construction_error(monkeypatch):
    monkeypatch.setattr(
        tool_catalog,
        "make_sql_tools",
        lambda thread_id: (_ for _ in ()).throw(ValueError("invalid SQL catalog")),
    )

    with pytest.raises(ValueError, match="invalid SQL catalog"):
        build_tool_catalog("catalog-invalid-sql")


def test_build_tool_catalog_rejects_duplicate_runtime_names(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")  # "" présent = non configuré, résiste à load_dotenv
    monkeypatch.setattr(
        tool_catalog,
        "make_geo_tools",
        lambda thread_id: [tool_catalog.get_zone_info],
    )

    with pytest.raises(ValueError, match="duplicate runtime names.*get_zone_info"):
        build_tool_catalog("catalog-duplicate")


FORMERLY_OMITTED_SOURCE_RESULTS = {
    "enrich_ecotaxa_with_ecopart_remote",
    "enrich_with_amundsen_ctd",
    "enrich_with_bio_oracle",
    "enrich_with_ogsl",
    "find_amundsen_data_for_table",
    "find_bio_oracle_data_for_table",
    "find_ecopart_project_for_ecotaxa",
    "group_ecotaxa_project_samples_by_region",
    "group_ecotaxa_samples_by_year",
    "rank_ecotaxa_samples_by_region",
    "search_ecotaxa_taxa",
}


def test_all_data_source_tools_have_explicit_visibility_decisions(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")  # "" présent = non configuré, résiste à load_dotenv
    catalog = build_tool_catalog("catalog-source-decisions")
    source_metadata = [
        catalog.presentation(name)
        for name in catalog.names
        if catalog.presentation(name).family
        in {"ecotaxa", "ecopart", "amundsen", "bio_oracle", "ogsl"}
    ]

    assert len(source_metadata) == 52
    assert all(item.source_label is not None for item in source_metadata)
    assert all(catalog.presentation(name).source_result for name in FORMERLY_OMITTED_SOURCE_RESULTS)


def test_every_catalog_label_is_bilingual_and_hides_runtime_name(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")  # "" présent = non configuré, résiste à load_dotenv
    catalog = build_tool_catalog("catalog-labels")

    for name in catalog.names:
        presentation = catalog.presentation(name)
        assert presentation.label.fr.strip()
        assert presentation.label.en.strip()
        assert name not in presentation.label.fr
        assert name not in presentation.label.en


def test_catalog_presentation_mappings_are_immutable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")  # "" présent = non configuré, résiste à load_dotenv
    catalog = build_tool_catalog("catalog-immutable")

    with pytest.raises(TypeError):
        catalog.presentations["load_file"] = catalog.presentation("load_file")
    with pytest.raises(TypeError):
        tool_catalog.TOOL_PRESENTATION["load_file"] = catalog.presentation(
            "load_file"
        )
