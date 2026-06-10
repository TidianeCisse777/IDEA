"""TDD — core/ecopart_client.py."""
import pytest


def test_login_with_token_env_var_sets_bearer_header():
    from unittest.mock import patch

    from core.ecopart_client import EcopartClient

    with patch.dict("os.environ", {"ECOPART_TOKEN": "tok123"}, clear=False):
        client = EcopartClient()
        client.login()

    assert client._session.headers.get("Authorization") == "Bearer tok123"


def test_login_with_username_password_posts_form_and_sets_cookie():
    from unittest.mock import MagicMock, patch

    from core.ecopart_client import EcopartClient

    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.cookies = {"session": "abc"}
    mock_resp.headers = {"set-cookie": "session=abc"}

    env = {"ECOTAXA_USERNAME": "user@lab.ca", "ECOTAXA_PASSWORD": "s3cr3t", "ECOPART_TOKEN": ""}
    with patch.dict("os.environ", env, clear=False):
        client = EcopartClient()
        client._session.post = MagicMock(return_value=mock_resp)
        client.login()

    client._session.post.assert_called_once()
    call_kwargs = client._session.post.call_args
    assert call_kwargs[1]["data"]["email"] == "user@lab.ca"
    assert call_kwargs[1]["data"]["password"] == "s3cr3t"


def test_login_raises_when_credentials_missing():
    from unittest.mock import patch

    from core.ecopart_client import EcopartClient

    with patch.dict("os.environ", {"ECOPART_TOKEN": "", "ECOTAXA_USERNAME": "", "ECOTAXA_PASSWORD": ""}, clear=False):
        client = EcopartClient()
        with pytest.raises(RuntimeError, match="credentials missing"):
            client.login()


def test_login_raises_on_failed_response():
    from unittest.mock import MagicMock, patch

    from core.ecopart_client import EcopartClient

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.cookies = {}
    mock_resp.headers = {}

    env = {"ECOTAXA_USERNAME": "user@lab.ca", "ECOTAXA_PASSWORD": "wrong"}
    with patch.dict("os.environ", {**env, "ECOPART_TOKEN": ""}, clear=False):
        client = EcopartClient()
        client._session.post = MagicMock(return_value=mock_resp)
        with pytest.raises(RuntimeError, match="login failed"):
            client.login()


def test_list_samples_normalizes_json_response():
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = [
        {"id": 42, "name": "ips_007", "visibility": "YY"},
        {"id": 43, "name": "ips_008", "visibility": "YY"},
    ]

    client = EcopartClient()
    client._session.get = MagicMock(return_value=mock_resp)
    samples = client.list_samples(105)

    client._session.get.assert_called_once()
    url, = client._session.get.call_args[0]
    assert "searchsample" in url
    assert client._session.get.call_args[1]["params"]["filt_uproj"] == "105"

    assert samples == [
        {"id": 42, "name": "ips_007", "visibility": "YY"},
        {"id": 43, "name": "ips_008", "visibility": "YY"},
    ]


def test_list_samples_returns_empty_list_on_empty_response():
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = []

    client = EcopartClient()
    client._session.get = MagicMock(return_value=mock_resp)

    assert client.list_samples(105) == []


def test_get_stats_returns_accessible_true_on_ok_response():
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient

    mock_resp = MagicMock()
    mock_resp.ok = True

    client = EcopartClient()
    client._session.get = MagicMock(return_value=mock_resp)
    stats = client.get_stats(105)

    client._session.get.assert_called_once()
    url, = client._session.get.call_args[0]
    assert "statsample" in url
    assert stats == {"accessible": True}


def test_get_stats_returns_accessible_false_on_error_response():
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient

    mock_resp = MagicMock()
    mock_resp.ok = False

    client = EcopartClient()
    client._session.get = MagicMock(return_value=mock_resp)

    assert client.get_stats(105) == {"accessible": False}


# ── #12 : preview + export + download ────────────────────────────────────────


def test_preview_sample_returns_normalized_dict_from_html():
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.text = """
    <div>
      <b>Sample ips_007</b><br>
      Ecotaxa Project (1165)<br>
      Depth range : 0 - 500 m<br>
    </div>
    """

    client = EcopartClient()
    client._session.get = MagicMock(return_value=mock_resp)
    result = client.preview_sample(42)

    url, = client._session.get.call_args[0]
    assert "getsamplepopover/42" in url
    assert result["sample_id"] == 42
    assert result["accessible"] is True
    assert "ips_007" in result["text"]


def test_start_export_returns_candidate_download_links():
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.headers = {"content-type": "text/html"}
    mock_resp.text = """
    <html><body>
      Export started.
      <a href="/Task/Download/99">Download file</a>
      <a href="/Task/Status/99">Status</a>
    </body></html>
    """

    client = EcopartClient()
    client._session.get = MagicMock(return_value=mock_resp)
    links = client.start_export(105)

    url, = client._session.get.call_args[0]
    assert "TaskPartExport" in url
    assert ("filt_uproj", "105") in client._session.get.call_args[1]["params"]
    assert any("Download" in lnk or "download" in lnk.lower() for lnk in links)


def test_download_tsv_returns_dataframe_from_tsv_response():
    import io
    from unittest.mock import MagicMock

    import pandas as pd

    from core.ecopart_client import EcopartClient

    tsv_content = b"Profile\tDepth [m]\tSampled volume [L]\nips_007\t10.0\t95.3\n"
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.headers = {"content-type": "text/tab-separated-values"}
    mock_resp.content = tsv_content

    client = EcopartClient()
    client._session.get = MagicMock(return_value=mock_resp)
    df = client.download_tsv(["https://ecopart.obs-vlfr.fr/Task/Download/99"])

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["Profile", "Depth [m]", "Sampled volume [L]"]
    assert len(df) == 1


def test_download_tsv_extracts_tsv_from_zip():
    import io
    import zipfile
    from unittest.mock import MagicMock

    import pandas as pd

    from core.ecopart_client import EcopartClient

    tsv_content = b"Profile\tDepth [m]\nips_007\t10.0\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("export.tsv", tsv_content)
    zip_bytes = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.headers = {"content-type": "application/zip"}
    mock_resp.content = zip_bytes

    client = EcopartClient()
    client._session.get = MagicMock(return_value=mock_resp)
    df = client.download_tsv(["https://ecopart.obs-vlfr.fr/Task/Download/99"])

    assert isinstance(df, pd.DataFrame)
    assert "Profile" in df.columns


def test_download_tsv_raises_when_no_links():
    import pytest

    from core.ecopart_client import EcopartClient

    client = EcopartClient()
    with pytest.raises(RuntimeError, match="No download links"):
        client.download_tsv([])
