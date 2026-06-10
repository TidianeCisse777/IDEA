"""TDD — core/amundsen_ctd_client.py."""


def test_list_amundsen_datasets_normalizes_erddap_response():
    from unittest.mock import MagicMock, patch

    from core.amundsen_ctd_client import list_amundsen_datasets

    response = MagicMock()
    response.json.return_value = {
        "table": {
            "columnNames": ["Dataset ID", "Title", "griddap", "tabledap"],
            "rows": [
                [
                    "amundsen12713",
                    "CTD data collected by the CCGS Amundsen in the Canadian Arctic",
                    "",
                    "https://erddap.amundsenscience.com/erddap/tabledap/amundsen12713",
                ]
            ],
        }
    }

    with patch("core.amundsen_ctd_client.requests.get", return_value=response) as mock_get:
        datasets = list_amundsen_datasets()

    assert mock_get.call_count == 1
    assert datasets == [
        {
            "dataset_id": "amundsen12713",
            "title": "CTD data collected by the CCGS Amundsen in the Canadian Arctic",
            "griddap": "",
            "tabledap": "https://erddap.amundsenscience.com/erddap/tabledap/amundsen12713",
        }
    ]


def test_preview_amundsen_profile_returns_raw_rows_and_join_aliases():
    from unittest.mock import MagicMock, patch

    from core.amundsen_ctd_client import preview_amundsen_profile

    search_response = MagicMock()
    search_response.json.return_value = {
        "table": {
            "columnNames": ["Dataset ID", "Title", "griddap", "tabledap"],
            "rows": [
                [
                    "amundsen12713",
                    "CTD data collected by the CCGS Amundsen in the Canadian Arctic",
                    "",
                    "https://erddap.amundsenscience.com/erddap/tabledap/amundsen12713",
                ]
            ],
        }
    }

    query_response = MagicMock()
    query_response.text = (
        "time,latitude,longitude,station,cast_number,Pres,Temp,Sal\n"
        "2013-08-01T12:00:00Z,74.1,-80.2,BRK-15,7,12.0,-1.2,31.4\n"
    )

    with patch("core.amundsen_ctd_client.requests.get", side_effect=[search_response, query_response]) as mock_get:
        result = preview_amundsen_profile({"station": "BRK-15", "cast_number": 7})

    assert mock_get.call_count == 2
    assert result["dataset_id"] == "amundsen12713"
    assert result["aliases"] == {
        "profile_id": "BRK-15-7",
        "station_id": "BRK-15",
        "cast_id": 7,
    }
    assert result["rows"] == [
        {
            "time": "2013-08-01T12:00:00Z",
            "latitude": 74.1,
            "longitude": -80.2,
            "station": "BRK-15",
            "cast_number": 7,
            "Pres": 12.0,
            "Temp": -1.2,
            "Sal": 31.4,
            "depth": 12.0,
            "profile_id": "BRK-15-7",
            "station_id": "BRK-15",
            "cast_id": 7,
        }
    ]


def test_query_amundsen_ctd_writes_tsv_and_returns_download_url(tmp_path):
    from unittest.mock import MagicMock, patch

    from core.amundsen_ctd_client import query_amundsen_ctd

    search_response = MagicMock()
    search_response.json.return_value = {
        "table": {
            "columnNames": ["Dataset ID", "Title", "griddap", "tabledap"],
            "rows": [
                [
                    "amundsen12713",
                    "CTD data collected by the CCGS Amundsen in the Canadian Arctic",
                    "",
                    "https://erddap.amundsenscience.com/erddap/tabledap/amundsen12713",
                ]
            ],
        }
    }

    query_response = MagicMock()
    query_response.text = (
        "time,latitude,longitude,station,cast_number,Pres,Temp,Sal\n"
        "2013-08-01T12:00:00Z,74.1,-80.2,BRK-15,7,12.0,-1.2,31.4\n"
    )

    output_path = tmp_path / "amundsen_ctd.tsv"
    with patch("core.amundsen_ctd_client.requests.get", side_effect=[search_response, query_response]):
        result = query_amundsen_ctd({"station": "BRK-15", "cast_number": 7}, output_path=output_path)

    assert output_path.exists()
    assert result["dataset_id"] == "amundsen12713"
    assert result["download_url"].endswith("amundsen_ctd.tsv")
    assert result["row_count"] == 1
