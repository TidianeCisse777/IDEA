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

    form_resp = MagicMock()
    form_resp.ok = True
    form_resp.text = """
    <form method="post">
      <input name="backurl" value="/?filt_uproj=105">
      <input name="starttask" value="Y">
    </form>
    """
    task_resp = MagicMock()
    task_resp.ok = True
    task_resp.text = """
    <html><body>
      <a href="/Task/Show/99">99 View</a>
    </body></html>
    """

    client = EcopartClient()
    client._session.get = MagicMock(return_value=form_resp)
    client._session.post = MagicMock(return_value=task_resp)
    links = client.start_export(105)

    url, = client._session.get.call_args[0]
    assert "TaskPartExport" in url
    assert ("filt_uproj", "105") in client._session.get.call_args[1]["params"]
    client._session.post.assert_called_once()
    assert client._session.post.call_args[1]["data"]["starttask"] == "Y"
    assert client._session.post.call_args[1]["data"]["what"] == "RED"
    assert client._session.post.call_args[1]["data"]["fileformat"] == "TSV"
    assert links == ["/Task/Show/99"]


def test_start_export_finds_task_from_list_after_confirmation_page():
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient

    form_resp = MagicMock(ok=True, text='<input name="backurl" value="/?filt_uproj=105">')
    confirmation_resp = MagicMock(ok=True, text="<p>Leave this page to continue working in EcoPart</p>")
    task_list_resp = MagicMock(
        ok=True,
        text='<a href="/Task/Show/98">old</a><a href="/Task/Show/101">new</a>',
    )

    client = EcopartClient()
    client._session.get = MagicMock(side_effect=[form_resp, task_list_resp])
    client._session.post = MagicMock(return_value=confirmation_resp)

    links = client.start_export(105)

    assert links == ["/Task/Show/101"]
    assert client._session.get.call_args_list[1].args[0].endswith("/Task/listall")


def test_download_tsv_resolves_completed_task_to_zip(monkeypatch):
    import io
    import zipfile
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient

    task_resp = MagicMock()
    task_resp.ok = True
    task_resp.headers = {"content-type": "text/html"}
    task_resp.content = b"""
    <html><body>
      <p>State Done</p>
      <a href="/Task/GetFile/99/export.zip">Get file export.zip</a>
    </body></html>
    """
    task_resp.text = task_resp.content.decode()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("export.tsv", b"Profile\tDepth [m]\nips_007\t10.0\n")
    zip_resp = MagicMock()
    zip_resp.ok = True
    zip_resp.headers = {"content-type": "application/zip"}
    zip_resp.content = buf.getvalue()

    client = EcopartClient()
    client._session.get = MagicMock(side_effect=[task_resp, zip_resp])
    monkeypatch.setattr("core.ecopart_client.time.sleep", lambda _: None)

    df = client.download_tsv(["/Task/Show/99"])

    assert list(df.columns) == ["Profile", "Depth [m]"]
    assert len(df) == 1
    assert "GetFile/99/export.zip" in client._session.get.call_args_list[1].args[0]


def test_download_tsv_rejects_html_instead_of_parsing_it_as_csv():
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient

    html_resp = MagicMock()
    html_resp.ok = True
    html_resp.headers = {"content-type": "text/html; charset=utf-8"}
    html_resp.content = b"<html><body>Task page, not tabular data</body></html>"
    html_resp.text = html_resp.content.decode()

    client = EcopartClient()
    client._session.get = MagicMock(return_value=html_resp)

    with pytest.raises(RuntimeError, match="HTML"):
        client.download_tsv(["https://ecopart.obs-vlfr.fr/not-a-download"])


def test_download_tsv_detects_tabs_even_when_content_type_says_csv():
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient

    content = b"Profile\tDepth [m]\nips_007\t18,5\n"
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.headers = {"content-type": "text/csv"}
    mock_resp.content = content

    client = EcopartClient()
    client._session.get = MagicMock(return_value=mock_resp)
    df = client.download_tsv(["https://ecopart.obs-vlfr.fr/export.csv"])

    assert list(df.columns) == ["Profile", "Depth [m]"]
    assert df.iloc[0]["Depth [m]"] == "18,5"


def test_download_tsv_reads_ecopart_cp1252_characters():
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient

    content = "Profile\tPixel size [µm]\nips_007\t92\n".encode("cp1252")
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.headers = {"content-type": "text/tab-separated-values"}
    mock_resp.content = content

    client = EcopartClient()
    client._session.get = MagicMock(return_value=mock_resp)
    df = client.download_tsv(["https://ecopart.obs-vlfr.fr/export.tsv"])

    assert list(df.columns) == ["Profile", "Pixel size [µm]"]


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


def test_parse_ecopart_task_error_classifies_empty_sample_set():
    from core.ecopart_client import _parse_ecopart_task_error

    page = (
        "Task ID 60808 Class TaskPartExport State Error Step 1 Progress -1% "
        "Message Unhandled SubProcess Exception : (<class 'psycopg2.errors.SyntaxError'>, "
        "SyntaxError('ERREUR: erreur de syntaxe sur ou près de « ) » LINE 9: "
        "where s.psampleid in ()'),"
    )
    kind, message, task_id = _parse_ecopart_task_error(page)

    assert kind == "empty_sample_set"
    assert task_id == 60808
    assert "aucun sample exportable" in message
    assert "VN" in message


def test_parse_ecopart_task_error_classifies_db_error_without_empty_set_signature():
    from core.ecopart_client import _parse_ecopart_task_error

    page = "Task ID 4242 State Error psycopg2 internal failure during export"
    kind, message, task_id = _parse_ecopart_task_error(page)

    assert kind == "db_error"
    assert task_id == 4242
    assert "erreur interne" in message


def test_wait_for_export_raises_ecopart_export_error_with_kind():
    from unittest.mock import MagicMock

    from core.ecopart_client import EcopartClient, EcopartExportError

    error_html = """
    <html><body>
      Task ID 60808 State Error
      Message Unhandled SubProcess Exception psycopg2.errors.SyntaxError
      where s.psampleid in ()
    </body></html>
    """
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = error_html

    import core.ecopart_client as ecopart_mod
    orig_interval = ecopart_mod._EXPORT_POLL_INTERVAL
    ecopart_mod._EXPORT_POLL_INTERVAL = 0
    try:
        client = EcopartClient()
        client._session.get = MagicMock(return_value=mock_resp)

        import pytest
        with pytest.raises(EcopartExportError) as exc_info:
            client._wait_for_export("/Task/Show/60808")

        assert exc_info.value.kind == "empty_sample_set"
        assert exc_info.value.task_id == 60808
        assert "VN" in exc_info.value.message
    finally:
        ecopart_mod._EXPORT_POLL_INTERVAL = orig_interval
