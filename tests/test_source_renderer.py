from tools.source_renderer import render_sources


def test_local_file_sources_do_not_invent_project_urls():
    text = render_sources({
        "source": "file:/app/hawke.tsv",
        "encoding": "latin-1",
    })

    assert "/app/hawke.tsv" in text
    assert "latin-1" in text
    assert "/prj/" not in text


def test_proven_ecopart_project_id_renders_canonical_url():
    text = render_sources({"source": "ecopart:1004", "project_id": 1004})

    assert "https://ecopart.obs-vlfr.fr/prj/1004" in text


def test_project_url_without_matching_project_metadata_is_removed():
    text = render_sources({
        "source": "file:/app/hawke.tsv",
        "url": "https://ecopart.obs-vlfr.fr/prj/42",
    })

    assert "/app/hawke.tsv" in text
    assert "/prj/42" not in text
