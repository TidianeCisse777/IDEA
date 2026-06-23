from unittest.mock import Mock

from tools.taxonomy_tool import make_taxonomy_tool


def _response(payload):
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    response.content = b"{}"
    return response


def test_lookup_marine_taxonomy_prefers_rag_definition_and_validates_worms():
    rag_result = [
        {
            "title": "Calanus hyperboreus",
            "doc": "copepodes_domaine.md",
            "content": "Calanus hyperboreus est une espece de copepode arctique.",
            "score": 0.12,
        }
    ]

    def fake_get(url, params=None, timeout=10):
        if "AphiaRecordsByName" in url:
            return _response(
                [
                    {
                        "AphiaID": 104467,
                        "scientificname": "Calanus hyperboreus",
                        "status": "accepted",
                        "rank": "Species",
                        "kingdom": "Animalia",
                        "phylum": "Arthropoda",
                        "class": "Copepoda",
                        "order": "Calanoida",
                        "family": "Calanidae",
                        "genus": "Calanus",
                    }
                ]
            )
        if "AphiaClassificationByAphiaID" in url:
            return _response(
                {
                    "scientificname": "Animalia",
                    "rank": "Kingdom",
                    "AphiaID": 2,
                    "child": {
                        "scientificname": "Arthropoda",
                        "rank": "Phylum",
                        "AphiaID": 1065,
                        "child": {
                            "scientificname": "Copepoda",
                            "rank": "Class",
                            "AphiaID": 1080,
                        },
                    },
                }
            )
        raise AssertionError(f"unexpected URL: {url}")

    tool = make_taxonomy_tool(
        rag_query=lambda *_args, **_kwargs: rag_result,
        http_get=fake_get,
    )
    result = tool.invoke({"term": "Calanus hyperboreus"})

    assert "Calanus hyperboreus est une espece" in result
    assert "RAG local" in result
    assert "AphiaID" in result
    assert "104467" in result
    assert "accepted" in result
    assert "Copepoda" in result


def test_lookup_marine_taxonomy_uses_wikipedia_fallback_when_rag_is_empty():
    calls = []

    def fake_get(url, params=None, timeout=10):
        calls.append((url, params or {}))
        if "AphiaRecordsByName" in url:
            return _response([])
        if "fr.wikipedia.org/w/api.php" in url:
            return _response(
                {
                    "query": {
                        "pages": {
                            "123": {
                                "title": "Copepode",
                                "extract": "Les copepodes sont de petits crustaces.",
                            }
                        }
                    }
                }
            )
        raise AssertionError(f"unexpected URL: {url}")

    tool = make_taxonomy_tool(
        rag_query=lambda *_args, **_kwargs: [],
        http_get=fake_get,
    )
    result = tool.invoke({"term": "copepode gelatineux"})

    assert "Les copepodes sont de petits crustaces." in result
    assert "Wikipedia fallback" in result
    assert "WoRMS n'a pas resolu" in result
    assert any("fr.wikipedia.org/w/api.php" in url for url, _params in calls)


def test_lookup_marine_taxonomy_searches_wikipedia_when_exact_page_is_missing():
    def fake_get(url, params=None, timeout=10):
        params = params or {}
        if "AphiaRecordsByName" in url:
            return _response([])
        if "fr.wikipedia.org/w/api.php" in url and params.get("list") == "search":
            return _response(
                {
                    "query": {
                        "search": [
                            {"title": "Copepode"},
                        ]
                    }
                }
            )
        if "fr.wikipedia.org/w/api.php" in url and params.get("titles") == "copepode gelatineux":
            return _response({"query": {"pages": {"-1": {"missing": ""}}}})
        if "fr.wikipedia.org/w/api.php" in url and params.get("titles") == "Copepode":
            return _response(
                {
                    "query": {
                        "pages": {
                            "456": {
                                "title": "Copepode",
                                "extract": "Les copepodes forment une sous-classe de crustaces.",
                            }
                        }
                    }
                }
            )
        raise AssertionError(f"unexpected request: {url} {params}")

    tool = make_taxonomy_tool(
        rag_query=lambda *_args, **_kwargs: [],
        http_get=fake_get,
    )
    result = tool.invoke({"term": "copepode gelatineux"})

    assert "Les copepodes forment une sous-classe de crustaces." in result
    assert "Wikipedia fallback" in result


def test_lookup_marine_taxonomy_ignores_weak_rag_match_before_wikipedia_fallback():
    weak_rag = [
        {
            "title": "Stades de developpement",
            "doc": "copepodes_domaine.md",
            "content": "Tous les copepodes calanides partagent une sequence ontogenique.",
            "score": 0.48,
        }
    ]

    def fake_get(url, params=None, timeout=10):
        params = params or {}
        if "AphiaRecordsByName" in url:
            return _response([])
        if "fr.wikipedia.org/w/api.php" in url and params.get("list") == "search":
            return _response({"query": {"search": [{"title": "Copepode"}]}})
        if "fr.wikipedia.org/w/api.php" in url and params.get("titles") == "copepode gelatineux":
            return _response({"query": {"pages": {"-1": {"missing": ""}}}})
        if "fr.wikipedia.org/w/api.php" in url and params.get("titles") == "Copepode":
            return _response(
                {
                    "query": {
                        "pages": {
                            "456": {
                                "extract": "Les copepodes sont un groupe de petits crustaces.",
                            }
                        }
                    }
                }
            )
        raise AssertionError(f"unexpected request: {url} {params}")

    tool = make_taxonomy_tool(rag_query=lambda *_args, **_kwargs: weak_rag, http_get=fake_get)
    result = tool.invoke({"term": "copepode gelatineux"})

    assert "Les copepodes sont un groupe de petits crustaces." in result
    assert "Wikipedia fallback" in result
    assert "sequence ontogenique" not in result
