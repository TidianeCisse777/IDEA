"""TDD — core/bio_oracle_client.py."""


def test_plan_bio_oracle_request_requires_explicit_scenario_and_depth_layer():
    from core.bio_oracle_client import plan_bio_oracle_request

    result = plan_bio_oracle_request(
        {
            "latitude": 50.2,
            "longitude": -65.8,
            "variable": "thetao",
            "period": {"start": 2041, "end": 2060},
        }
    )

    assert result["source_id"] == "bio_oracle"
    assert result["missing_fields"] == ["scenario", "depth_layer"]
    assert result["recommended_next_step"] == "ask_clarification"


def test_describe_source_bio_oracle_mentions_depth_layer():
    from core.bio_oracle_client import describe_bio_oracle_source

    result = describe_bio_oracle_source()

    assert result["found"] is True
    assert "depth_layer" in result["join_keys"]
    assert "ssp" in result["content_summary"].lower()


def test_plan_bio_oracle_request_accepts_explicit_scenario_and_depth_layer():
    from core.bio_oracle_client import plan_bio_oracle_request

    result = plan_bio_oracle_request(
        {
            "latitude": 50.2,
            "longitude": -65.8,
            "variable": "thetao",
            "scenario": "SSP245",
            "depth_layer": "depthsurf",
            "period": {"start": 2041, "end": 2060},
        }
    )

    assert result["missing_fields"] == []
    assert result["recommended_next_step"] == "proceed"


def test_list_bio_oracle_datasets_normalizes_erddap_response():
    import requests
    from core.bio_oracle_client import list_bio_oracle_datasets
    from unittest.mock import MagicMock, patch

    response = MagicMock()
    response.json.return_value = {
        "table": {
            "columnNames": ["Dataset ID", "Title", "Info", "griddap"],
            "rows": [
                [
                    "thetao_ssp245_2020_2100_depthsurf",
                    "Bio-Oracle Temperature [depthSurf] SSP245 2020-2100",
                    "https://erddap.bio-oracle.org/erddap/info/thetao_ssp245_2020_2100_depthsurf/index.json",
                    "https://erddap.bio-oracle.org/erddap/griddap/thetao_ssp245_2020_2100_depthsurf",
                ],
                [
                    "so_baseline_2000_2019_depthmean",
                    "Bio-Oracle Salinity [depthMean] Baseline 2000-2019",
                    "https://erddap.bio-oracle.org/erddap/info/so_baseline_2000_2019_depthmean/index.json",
                    "https://erddap.bio-oracle.org/erddap/griddap/so_baseline_2000_2019_depthmean",
                ],
            ],
        }
    }

    with patch("core.bio_oracle_client.requests.get", return_value=response) as mock_get:
        datasets = list_bio_oracle_datasets()

    assert mock_get.call_count == 1
    assert datasets == [
        {
            "dataset_id": "thetao_ssp245_2020_2100_depthsurf",
            "title": "Bio-Oracle Temperature [depthSurf] SSP245 2020-2100",
            "griddap": "https://erddap.bio-oracle.org/erddap/griddap/thetao_ssp245_2020_2100_depthsurf",
        },
        {
            "dataset_id": "so_baseline_2000_2019_depthmean",
            "title": "Bio-Oracle Salinity [depthMean] Baseline 2000-2019",
            "griddap": "https://erddap.bio-oracle.org/erddap/griddap/so_baseline_2000_2019_depthmean",
        },
    ]


def test_preview_bio_oracle_point_returns_normalized_sample():
    from core.bio_oracle_client import preview_bio_oracle_point
    from unittest.mock import MagicMock, patch

    query_response = MagicMock()
    query_response.text = (
        "time,latitude,longitude,thetao\n"
        "2041-01-01T00:00:00Z,50.2,-65.8,12.3\n"
    )

    with patch("core.bio_oracle_client._find_dataset_id", return_value="thetao_ssp245_2020_2100_depthsurf"), \
         patch("core.bio_oracle_client.requests.get", return_value=query_response) as mock_get:
        result = preview_bio_oracle_point(
            {
                "latitude": 50.2,
                "longitude": -65.8,
                "variable": "thetao",
                "scenario": "SSP245",
                "depth_layer": "depthsurf",
            }
        )

    assert mock_get.call_count == 1
    assert result["dataset_id"] == "thetao_ssp245_2020_2100_depthsurf"
    assert result["rows"] == [
        {
            "time": "2041-01-01T00:00:00Z",
            "latitude": 50.2,
            "longitude": -65.8,
            "thetao": 12.3,
        }
    ]


def test_preview_bio_oracle_point_uses_requested_target_year():
    from core.bio_oracle_client import preview_bio_oracle_point
    from unittest.mock import MagicMock, patch

    query_response = MagicMock()
    query_response.text = (
        "time,latitude,longitude,thetao\n"
        "2050-01-01T00:00:00Z,50.2,-65.8,13.4\n"
    )

    with patch("core.bio_oracle_client._find_dataset_id", return_value="thetao_ssp126_2020_2100_depthsurf"), \
         patch("core.bio_oracle_client.requests.get", return_value=query_response) as mock_get:
        result = preview_bio_oracle_point(
            {
                "latitude": 50.2,
                "longitude": -65.8,
                "variable": "temperature",
                "scenario": "SSP1-2.6",
                "depth_layer": "surface",
                "target_year": 2050,
            }
        )

    requested_url = mock_get.call_args.args[0]
    assert "[(2050-01-01T00:00:00Z)]" in requested_url
    assert result["rows"][0]["time"] == "2050-01-01T00:00:00Z"


def test_preview_bio_oracle_point_ignores_target_year_for_baseline():
    from core.bio_oracle_client import preview_bio_oracle_point
    from unittest.mock import MagicMock, patch

    query_response = MagicMock()
    query_response.text = (
        "time,latitude,longitude,thetao\n"
        "2010-01-01T00:00:00Z,50.2,-65.8,3.4\n"
    )

    with patch("core.bio_oracle_client._find_dataset_id", return_value="thetao_baseline_2000_2019_depthsurf"), \
         patch("core.bio_oracle_client.requests.get", return_value=query_response) as mock_get:
        result = preview_bio_oracle_point(
            {
                "latitude": 50.2,
                "longitude": -65.8,
                "variable": "temperature",
                "scenario": "baseline",
                "depth_layer": "surface",
                "target_year": 2050,
            }
        )

    requested_url = mock_get.call_args.args[0]
    assert "[(last)]" in requested_url
    assert "2050-01-01" not in requested_url
    assert result["rows"][0]["time"] == "2010-01-01T00:00:00Z"


def test_query_bio_oracle_writes_tsv_and_returns_download_url(tmp_path):
    from core.bio_oracle_client import query_bio_oracle
    from unittest.mock import MagicMock, patch

    query_response = MagicMock()
    query_response.text = (
        "time,latitude,longitude,thetao\n"
        "2041-01-01T00:00:00Z,50.2,-65.8,12.3\n"
    )

    output_path = tmp_path / "bio_oracle.tsv"
    with patch("core.bio_oracle_client._find_dataset_id", return_value="thetao_ssp245_2020_2100_depthsurf"), \
         patch("core.bio_oracle_client.requests.get", return_value=query_response):
        result = query_bio_oracle(
            {
                "latitude": 50.2,
                "longitude": -65.8,
                "variable": "thetao",
                "scenario": "SSP245",
                "depth_layer": "depthsurf",
            },
            output_path=output_path,
        )

    assert output_path.exists()
    assert result["download_url"].endswith("bio_oracle.tsv")
    assert result["row_count"] == 1
