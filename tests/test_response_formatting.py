from core.response_formatting import format_assistant_text


def test_format_assistant_text_collapses_blank_lines_and_trailing_whitespace():
    raw = "First line.  \n\n\nSecond line.\t\n"
    assert format_assistant_text(raw) == "First line.\n\nSecond line."


def test_format_assistant_text_fixes_obvious_punctuation_spacing():
    raw = "Bonjour,monde!Comment ca va?"
    assert format_assistant_text(raw) == "Bonjour, monde! Comment ca va?"


def test_format_assistant_text_preserves_fenced_code_blocks():
    raw = "Intro.\n```python\nprint('hi')\n```\nOutro."
    assert format_assistant_text(raw) == raw


def test_format_assistant_text_repairs_copepod_plan_identifier_spacing():
    raw = (
        "Plan: je reprends la jointure entresample_id etSAMPLE_ID.\n"
        "Fichier 1: source_typelikely_neolabs_taxon; "
        "colonnes utiles:SAMPLE_ID,ANALYSIS_ID.\n"
        "Blocage: lecture enWindows-1252 avecprofile_join_keys."
    )

    assert format_assistant_text(raw) == (
        "Plan: je reprends la jointure entre `sample_id` et `SAMPLE_ID`.\n"
        "Fichier 1: source_type `likely_neolabs_taxon`; "
        "colonnes utiles: `SAMPLE_ID`, `ANALYSIS_ID`.\n"
        "Blocage: lecture en `Windows-1252` avec `profile_join_keys`."
    )


def test_format_assistant_text_formats_compact_inspection_summary():
    raw = (
        "Inspection terminée:donne_sample.csv est un CSV de6105 × 33, source "
        "détectéelikely_neolabs_taxon avec confiancehigh, encodageWindows-1252. "
        "Colonnes clés déjà reconnues:sample_id,analysis_id,station_name,latitude,longitude,"
        "deployment_datetime_start,deployment_datetime_end,gear,tow_type. "
        "Colonne encore à clarifier si nécessaire:sample_nets`. "
        "Le bloc affiché correspond au rapport complet d’inspection; il n’y a pas d’erreur bloquante."
    )

    assert format_assistant_text(raw) == (
        "**Inspection**\n"
        "- Fichier : `donne_sample.csv`\n"
        "- Format : CSV, 6105 × 33\n"
        "- Source détectée : `likely_neolabs_taxon` (confiance : `high`)\n"
        "- Encodage : `Windows-1252`\n"
        "- Colonnes clés : `sample_id`, `analysis_id`, `station_name`, `latitude`, `longitude`, "
        "`deployment_datetime_start`, `deployment_datetime_end`, `gear`, `tow_type`\n"
        "- À clarifier si nécessaire : `sample_nets`\n"
        "- Statut : aucune erreur bloquante."
    )


def test_format_assistant_text_formats_inspection_summary_with_variant_wording():
    raw = (
        "Inspection terminée pour donne_sample.csv : 6105 lignes × 33 colonnes, "
        "source détectée likely_neolabs_taxon (confiance haute), encodage Windows-1252. "
        "Colonnes utiles : sample_id, station_name, latitude. "
        "sample_nets reste à clarifier si elle devient nécessaire. "
        "Aucune erreur bloquante."
    )

    assert format_assistant_text(raw) == (
        "**Inspection**\n"
        "- Fichier : `donne_sample.csv`\n"
        "- Dimensions : 6105 × 33\n"
        "- Source détectée : `likely_neolabs_taxon` (confiance : haute)\n"
        "- Encodage : `Windows-1252`\n"
        "- Colonnes clés : `sample_id`, `station_name`, `latitude`\n"
        "- À clarifier si nécessaire : `sample_nets`\n"
        "- Statut : aucune erreur bloquante."
    )


def test_format_assistant_text_formats_reference_columns_and_remaining_blocker():
    raw = (
        "Inspection terminée :donne_sample.csv est un CSV de6105 × 33, source "
        "détectéelikely_neolabs_taxon avec confiancehigh, encodageWindows-1252`. "
        "Colonnes de référence disponibles :sample_id,station_name,latitude,longitude,"
        "deployment_datetime_start,deployment_datetime_end,analysis_id. "
        "Blocage restant :sample_nets est la seule colonne à clarifier si elle est nécessaire."
    )

    assert format_assistant_text(raw) == (
        "**Inspection**\n"
        "- Fichier : `donne_sample.csv`\n"
        "- Format : CSV, 6105 × 33\n"
        "- Source détectée : `likely_neolabs_taxon` (confiance : `high`)\n"
        "- Encodage : `Windows-1252`\n"
        "- Colonnes clés : `sample_id`, `station_name`, `latitude`, `longitude`, "
        "`deployment_datetime_start`, `deployment_datetime_end`, `analysis_id`\n"
        "- À clarifier si nécessaire : `sample_nets`"
    )
