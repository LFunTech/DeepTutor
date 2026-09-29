"""OMS OAuth browser flow keeps the callback boundary in the frontend."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.datastructures import URL, QueryParams

pytestmark = pytest.mark.asyncio


class _StartRequest:
    query_params = QueryParams({"return_to": "https://llm-agent-test.f123.pub/oms"})
    url = URL("https://llm-agent-test.f123.pub/api/v1/oms/auth/start")

    def url_for(self, _name: str) -> URL:
        return URL("https://llm-agent-test.f123.pub/api/v1/oms/auth/callback")


class _CallbackRequest:
    query_params = QueryParams()
    url = URL("https://llm-agent-test.f123.pub/api/v1/oms/auth/callback")

    def __init__(self, payload: dict[str, str]):
        self._payload = payload

    async def json(self) -> dict[str, str]:
        return self._payload


def _location_query(response) -> dict[str, list[str]]:
    location = response.headers["location"]
    return parse_qs(urlsplit(location).query)


def _set_cookie_text(response) -> str:
    return "\n".join(
        value.decode("latin1")
        for key, value in response.raw_headers
        if key.lower() == b"set-cookie"
    )


def _set_cookie_headers(response) -> list[str]:
    return [
        value.decode("latin1")
        for key, value in response.raw_headers
        if key.lower() == b"set-cookie"
    ]


def _base_oauth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DT_EDUPLUS2_OMS_AUTHORIZATION_ENDPOINT",
        "https://eduplus-auth-test.f123.pub/realms/eduplus/protocol/openid-connect/auth",
    )
    monkeypatch.setenv(
        "DT_EDUPLUS2_OMS_TOKEN_ENDPOINT",
        "https://eduplus-auth-test.f123.pub/realms/eduplus/protocol/openid-connect/token",
    )
    monkeypatch.setenv("DT_EDUPLUS2_OMS_CLIENT_ID", "eduplus-platform-admin")
    monkeypatch.delenv("DT_EDUPLUS2_OMS_REDIRECT_URI", raising=False)


async def test_oms_authorization_start_uses_frontend_callback_by_default(monkeypatch):
    from deeptutor_enterprise.oms import oauth

    _base_oauth_env(monkeypatch)
    oauth._STATE_STORE.clear()

    response = oauth.create_authorization_redirect(_StartRequest())

    assert response.status_code == 303
    query = _location_query(response)
    assert query["redirect_uri"] == ["https://llm-agent-test.f123.pub/oms/auth/callback"]
    assert query["client_id"] == ["eduplus-platform-admin"]


async def test_frontend_callback_post_exchanges_code_and_sets_httponly_session(
    monkeypatch,
):
    from deeptutor_enterprise.oms import oauth

    _base_oauth_env(monkeypatch)
    oauth._STATE_STORE.clear()
    start_response = oauth.create_authorization_redirect(_StartRequest())
    state = _location_query(start_response)["state"][0]

    async def exchange_code(config, login_state, code):
        assert code == "auth-code"
        assert login_state.redirect_uri == "https://llm-agent-test.f123.pub/oms/auth/callback"
        assert config.client_id == "eduplus-platform-admin"
        return {"access_token": "provider.jwt.token", "refresh_token": "provider.refresh.token"}

    async def select_verified_token(_enterprise, payload):
        assert payload == {
            "access_token": "provider.jwt.token",
            "refresh_token": "provider.refresh.token",
        }
        return "verified.platform.jwt"

    monkeypatch.setattr(oauth, "_exchange_code", exchange_code)
    monkeypatch.setattr(oauth, "_select_verified_token", select_verified_token)
    monkeypatch.setattr(oauth, "_max_age_from_token", lambda _token: 600)

    response = await oauth.handle_frontend_callback(
        _CallbackRequest({"state": state, "code": "auth-code"}), object()
    )

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body == {
        "authenticated": True,
        "return_url": "https://llm-agent-test.f123.pub/oms",
    }
    assert "verified.platform.jwt" not in response.body.decode()
    assert "provider.refresh.token" not in response.body.decode()
    set_cookie = _set_cookie_text(response)
    assert "dt_oms_token=verified.platform.jwt" in set_cookie
    assert "dt_oms_refresh=provider.refresh.token" in set_cookie
    assert "HttpOnly" in set_cookie


async def test_frontend_callback_sets_frontend_readable_oms_csrf_cookie(monkeypatch):
    """OMS BFF 写接口的 CSRF cookie 必须能被 `/oms` 前端读取。"""

    from deeptutor_enterprise.oms import oauth

    _base_oauth_env(monkeypatch)
    oauth._STATE_STORE.clear()
    start_response = oauth.create_authorization_redirect(_StartRequest())
    state = _location_query(start_response)["state"][0]

    async def exchange_code(_config, _login_state, _code):
        return {"access_token": "provider.jwt.token", "refresh_token": "provider.refresh.token"}

    async def select_verified_token(_enterprise, _payload):
        return "verified.platform.jwt"

    monkeypatch.setattr(oauth, "_exchange_code", exchange_code)
    monkeypatch.setattr(oauth, "_select_verified_token", select_verified_token)
    monkeypatch.setattr(oauth, "_max_age_from_token", lambda _token: 600)

    response = await oauth.handle_frontend_callback(
        _CallbackRequest({"state": state, "code": "auth-code"}), object()
    )

    headers = _set_cookie_headers(response)
    csrf_headers = [header for header in headers if header.startswith("dt_oms_csrf=")]
    assert any("Path=/;" in header for header in csrf_headers)
    assert all("HttpOnly" not in header for header in csrf_headers)
    assert any(
        header.startswith("dt_oms_csrf=")
        and "Max-Age=0" in header
        and "Path=/api/v1/oms;" in header
        for header in headers
    )


async def test_refresh_endpoint_uses_httponly_refresh_token_without_exposing_tokens(
    monkeypatch,
):
    from deeptutor_enterprise.oms import oauth

    _base_oauth_env(monkeypatch)

    async def refresh_access_token(config, refresh_token):
        assert config.client_id == "eduplus-platform-admin"
        assert refresh_token == "old.refresh.token"
        return {"access_token": "new.provider.jwt", "refresh_token": "new.refresh.token"}

    async def select_verified_token(_enterprise, payload):
        assert payload == {
            "access_token": "new.provider.jwt",
            "refresh_token": "new.refresh.token",
        }
        return "new.verified.platform.jwt"

    monkeypatch.setattr(oauth, "_refresh_access_token", refresh_access_token)
    monkeypatch.setattr(oauth, "_select_verified_token", select_verified_token)
    monkeypatch.setattr(oauth, "_max_age_from_token", lambda _token: 600)

    class RefreshRequest:
        query_params = QueryParams()
        url = URL("https://llm-agent-test.f123.pub/api/v1/oms/auth/refresh")
        headers = {"x-csrf-token": "csrf-token"}
        cookies = {"dt_oms_refresh": "old.refresh.token", "dt_oms_csrf": "csrf-token"}

    response = await oauth.refresh_session(RefreshRequest(), object())

    assert response.status_code == 200
    assert json.loads(response.body) == {"authenticated": True}
    assert "new.verified.platform.jwt" not in response.body.decode()
    assert "new.refresh.token" not in response.body.decode()
    set_cookie = _set_cookie_text(response)
    assert "dt_oms_token=new.verified.platform.jwt" in set_cookie
    assert "dt_oms_refresh=new.refresh.token" in set_cookie
    assert "HttpOnly" in set_cookie


async def test_refresh_endpoint_requires_bff_csrf_header(monkeypatch):
    from deeptutor_enterprise.oms import oauth

    _base_oauth_env(monkeypatch)

    class RefreshRequest:
        query_params = QueryParams()
        url = URL("https://llm-agent-test.f123.pub/api/v1/oms/auth/refresh")
        headers = {}
        cookies = {"dt_oms_refresh": "old.refresh.token", "dt_oms_csrf": "csrf-token"}

    response = await oauth.refresh_session(RefreshRequest(), object())

    assert response.status_code == 403
    assert json.loads(response.body) == {"detail": "csrf_invalid"}
