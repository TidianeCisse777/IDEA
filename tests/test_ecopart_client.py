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
