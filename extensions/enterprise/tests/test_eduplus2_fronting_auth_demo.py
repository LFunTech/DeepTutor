"""EduPlus2 前置应用统一认证 demo：路由契约先行。"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit
import uuid

import httpx
from jose import jwt
import pytest
from test_application import app as app

pytestmark = pytest.mark.asyncio

EDUPLUS2_KEY = "e" * 48
ISSUER = "https://eduplus2.test"


def user_jwt(*, tid: str, eui: str, azp: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": "eduplus2-api",
            "tid": tid,
            "eui": eui,
            "sub": f"sub-{eui}",
            "eit": "teacher",
            "azp": azp,
            "iat": now,
            "exp": now + 600,
            "jti": f"jti-{uuid.uuid4().hex}",
        },
        EDUPLUS2_KEY,
        algorithm="HS256",
        headers={"kid": "test-kid"},
    )


def oidc_id_token(*, azp: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": azp,
            "sub": f"oidc-sub-{uuid.uuid4().hex}",
            "azp": azp,
            "iat": now,
            "exp": now + 600,
        },
        EDUPLUS2_KEY,
        algorithm="HS256",
        headers={"kid": "test-kid"},
    )


def configure_demo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DT_EDUPLUS2_AUTHORIZATION_ENDPOINT",
        "https://eduplus2.example/oauth2/authorize",
    )
    monkeypatch.setenv("DT_EDUPLUS2_TOKEN_ENDPOINT", "https://eduplus2.example/oauth2/token")
    monkeypatch.setenv("DT_EDUPLUS2_CLIENT_ID", "client-a")
    monkeypatch.setenv("DT_EDUPLUS2_CLIENT_SECRET", "secret-that-must-never-leak")
    monkeypatch.setenv("DT_EDUPLUS2_CLIENT_SECRET_REF", "env:DT_EDUPLUS2_CLIENT_SECRET")
    monkeypatch.setenv(
        "DT_EDUPLUS2_FRONTING_DEMO_RETURN_URL",
        "https://school.example/enterprise/eduplus2/fronting-demo",
    )
    monkeypatch.setenv("DT_EDUPLUS2_DT_TOKEN_TTL_SECONDS", "60")


async def test_select_user_jwt_prefers_access_token_with_exchange_claims():
    """OIDC id_token 可能缺少 tid/eui，demo 应选择带业务 claims 的 access_token。"""

    from deeptutor_enterprise.eduplus2.fronting_demo import select_user_jwt

    access_token = user_jwt(tid="tenant-a", eui="u-demo", azp="client-a")
    selected = select_user_jwt(
        {
            "id_token": oidc_id_token(azp="client-a"),
            "access_token": access_token,
        }
    )

    assert selected == access_token


async def test_token_diagnostics_exposes_only_safe_jwt_metadata():
    """失败摘要要能定位 alg/kid/issuer，但不能泄露 JWT 原文或用户明文标识。"""

    from deeptutor_enterprise.eduplus2.fronting_demo import _token_diagnostics

    id_token = oidc_id_token(azp="client-a")
    access_token = user_jwt(tid="tenant-a", eui="u-demo", azp="client-a")

    diagnostics = _token_diagnostics(
        {"id_token": id_token, "access_token": access_token},
        selected_token_name="access_token",
    )

    assert diagnostics["selected_token"] == "access_token"
    assert diagnostics["access_token"]["has_exchange_claims"] is True
    assert diagnostics["access_token"]["header_alg"] == "HS256"
    assert diagnostics["access_token"]["header_kid_hash"].startswith("sha256:")
    assert diagnostics["access_token"]["claim_issuer"] == ISSUER
    assert diagnostics["access_token"]["claim_tid_hash"].startswith("sha256:")
    assert diagnostics["access_token"]["claim_eui_hash"].startswith("sha256:")
    assert diagnostics["selected_header_alg"] == "HS256"
    assert diagnostics["selected_header_kid_hash"].startswith("sha256:")
    assert diagnostics["selected_claim_issuer"] == ISSUER
    assert diagnostics["selected_claim_azp"] == "client-a"
    assert isinstance(diagnostics["selected_claim_iat_delta_seconds"], int)
    assert diagnostics["selected_claim_exp_delta_seconds"] > 0
    assert access_token not in str(diagnostics)
    assert id_token not in str(diagnostics)
    assert "u-demo" not in str(diagnostics)
    assert "tenant-a" not in str(diagnostics)


async def test_runtime_error_detail_is_specific_and_redacted():
    """service_unavailable 也要能定位外部边界，但不能回显敏感正文。"""

    from deeptutor_enterprise.eduplus2.fronting_demo import _safe_error_detail

    assert (
        _safe_error_detail(RuntimeError("EduPlus2 profile endpoint rejected request: 404"))
        == "eduplus2_profile_endpoint_rejected"
    )
    assert (
        _safe_error_detail(RuntimeError("EduPlus2 permission endpoint is unavailable"))
        == "eduplus2_permission_endpoint_unavailable"
    )
    assert (
        _safe_error_detail(
            RuntimeError("EduPlus2 token endpoint rejected request: 401 secret-value")
        )
        == "eduplus2_token_endpoint_rejected"
    )
    assert _safe_error_detail(RuntimeError("database timeout secret-value")) == "service_unavailable"


async def test_demo_start_redirects_to_eduplus2_with_state_and_pkce(
    app, monkeypatch: pytest.MonkeyPatch
):
    """少传 state/PKCE 或把 secret/verifier 泄露进 URL 都应被该测试抓住。"""

    configure_demo_env(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
        follow_redirects=False,
    ) as client:
        response = await client.get(
            "/api/v1/auth/eduplus2/demo/start",
            params={"return_to": "https://school.example/enterprise/eduplus2/fronting-demo"},
        )

    assert response.status_code in (302, 303, 307), response.text
    location = response.headers["location"]
    parsed = urlsplit(location)
    query = parse_qs(parsed.query)
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https",
        "eduplus2.example",
        "/oauth2/authorize",
    )
    assert query["client_id"] == ["client-a"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid profile offline_access"]
    assert query["code_challenge_method"] == ["S256"]
    assert query.get("state", [""])[0]
    assert query.get("code_challenge", [""])[0]
    assert query["redirect_uri"] == [
        "https://school.example/api/v1/auth/eduplus2/demo/callback"
    ]
    assert "secret-that-must-never-leak" not in location
    assert "code_verifier" not in location


async def test_demo_callback_preserves_trusted_return_to_when_api_origin_is_internal(
    app, monkeypatch: pytest.MonkeyPatch
):
    """Next rewrite 让 API 看到 localhost 时，也必须回到同一可信站点下的发起页面。"""

    configure_demo_env(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:8001",
        follow_redirects=False,
    ) as client:
        start = await client.get(
            "/api/v1/auth/eduplus2/demo/start",
            params={
                "return_to": "https://school.example/enterprise/eduplus2/conversation-test"
            },
        )
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        callback = await client.get(
            "/api/v1/auth/eduplus2/demo/callback",
            params={"state": state, "error": "access_denied"},
        )

    assert callback.status_code in (302, 303, 307), callback.text
    location = callback.headers["location"]
    assert urlsplit(location).scheme == "https"
    assert urlsplit(location).netloc == "school.example"
    assert urlsplit(location).path == "/enterprise/eduplus2/conversation-test"
    assert "demo_session=" in location
    assert "/enterprise/eduplus2/fronting-demo" not in location


async def test_demo_callback_exchanges_code_and_result_keeps_tokens_off_url(
    app, monkeypatch: pytest.MonkeyPatch
):
    """callback 成功时只能把 opaque demo_session 带回页面，token 只在 result JSON 中内存使用。"""

    from deeptutor_enterprise.eduplus2 import fronting_demo
    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

    configure_demo_env(monkeypatch)
    enterprise = app.state.enterprise
    monkeypatch.setattr(
        enterprise,
        "eduplus2_resolver",
        StaticEduPlus2Resolver(
            {
                "client-a": {
                    "client_id": "client-a",
                    "external_tenant_id": "tenant-a",
                    "external_tenant_name": "学校 A",
                    "external_app_id": "app-math",
                    "external_app_name": "数学应用",
                    "status": "active",
                    "subscription_status": "active",
                    "policy": {"scopes": ["chat"]},
                    "version": "v1",
                }
            }
        ),
        raising=False,
    )
    monkeypatch.setattr(enterprise, "eduplus2_signing_key", EDUPLUS2_KEY, raising=False)
    monkeypatch.setattr(enterprise, "eduplus2_issuer", ISSUER, raising=False)
    admin = await enterprise.identity.login("admin", "long-password-1", client="demo-setup")
    await enterprise.eduplus2.register_client(
        admin, "client-a", surface="tms", expected_tenant_id="tenant-a"
    )
    eduplus2_jwt = user_jwt(tid="tenant-a", eui="u-demo", azp="client-a")

    async def fake_code_exchange(_config, _state, code: str):
        assert code == "auth-code-123"
        return {"id_token": eduplus2_jwt, "token_type": "Bearer"}

    monkeypatch.setattr(fronting_demo, "exchange_authorization_code", fake_code_exchange)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
        follow_redirects=False,
    ) as client:
        start = await client.get(
            "/api/v1/auth/eduplus2/demo/start",
            params={"return_to": "https://school.example/enterprise/eduplus2/fronting-demo"},
        )
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        callback = await client.get(
            "/api/v1/auth/eduplus2/demo/callback",
            params={"state": state, "code": "auth-code-123"},
        )
        assert callback.status_code in (302, 303, 307), callback.text
        location = callback.headers["location"]
        assert "auth-code-123" not in location
        assert eduplus2_jwt not in location
        demo_session = parse_qs(urlsplit(location).query)["demo_session"][0]
        result = await client.get(
            "/api/v1/auth/eduplus2/demo/result",
            params={"demo_session": demo_session},
        )
        assert result.status_code == 200, result.text
        payload = result.json()
        status = await client.get(
            "/api/auth/status",
            headers={"Authorization": "Bearer " + payload["dt_token"]},
        )

    assert payload["ok"] is True
    assert payload["token_type"] == "Bearer"
    assert payload["dt_token"]
    assert eduplus2_jwt not in result.text
    assert "auth-code-123" not in result.text
    assert "secret-that-must-never-leak" not in result.text
    assert payload["summary"]["external_user_hash"].startswith("sha256:")
    assert payload["summary"]["internal_user_hash"].startswith("sha256:")
    assert status.json()["authenticated"] is True


async def test_demo_refresh_uses_refresh_token_and_reissues_dt_token(
    app, monkeypatch: pytest.MonkeyPatch
):
    """临期/超时续签必须重新走 EduPlus2 refresh grant + 现有 exchange，且不回显 refresh token。"""

    from deeptutor_enterprise.eduplus2 import fronting_demo
    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

    configure_demo_env(monkeypatch)
    enterprise = app.state.enterprise
    monkeypatch.setattr(
        enterprise,
        "eduplus2_resolver",
        StaticEduPlus2Resolver(
            {
                "client-a": {
                    "client_id": "client-a",
                    "external_tenant_id": "tenant-a",
                    "external_tenant_name": "学校 A",
                    "external_app_id": "app-math",
                    "external_app_name": "数学应用",
                    "status": "active",
                    "subscription_status": "active",
                    "policy": {"scopes": ["chat"]},
                    "version": "v1",
                }
            }
        ),
        raising=False,
    )
    monkeypatch.setattr(enterprise, "eduplus2_signing_key", EDUPLUS2_KEY, raising=False)
    monkeypatch.setattr(enterprise, "eduplus2_issuer", ISSUER, raising=False)
    admin = await enterprise.identity.login("admin", "long-password-1", client="demo-refresh")
    await enterprise.eduplus2.register_client(
        admin, "client-a", surface="tms", expected_tenant_id="tenant-a"
    )
    first_user_jwt = user_jwt(tid="tenant-a", eui="u-refresh", azp="client-a")
    second_user_jwt = user_jwt(tid="tenant-a", eui="u-refresh", azp="client-a")

    async def fake_code_exchange(_config, _state, _code: str):
        return {
            "id_token": first_user_jwt,
            "refresh_token": "refresh-secret-that-must-never-leak",
            "token_type": "Bearer",
        }

    async def fake_refresh_exchange(_config, refresh_token: str):
        assert refresh_token == "refresh-secret-that-must-never-leak"
        return {"id_token": second_user_jwt, "refresh_token": refresh_token}

    monkeypatch.setattr(fronting_demo, "exchange_authorization_code", fake_code_exchange)
    monkeypatch.setattr(fronting_demo, "refresh_user_token", fake_refresh_exchange)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
        follow_redirects=False,
    ) as client:
        start = await client.get("/api/v1/auth/eduplus2/demo/start")
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        callback = await client.get(
            "/api/v1/auth/eduplus2/demo/callback",
            params={"state": state, "code": "auth-code-123"},
        )
        demo_session = parse_qs(urlsplit(callback.headers["location"]).query)["demo_session"][0]
        first = await client.get(
            "/api/v1/auth/eduplus2/demo/result",
            params={"demo_session": demo_session},
        )
        refresh = await client.post(
            "/api/v1/auth/eduplus2/demo/refresh",
            json={"demo_session": demo_session},
        )

    assert refresh.status_code == 200, refresh.text
    payload = refresh.json()
    assert payload["ok"] is True
    assert payload["dt_token"]
    assert payload["dt_token"] != first.json()["dt_token"]
    assert "refresh-secret-that-must-never-leak" not in refresh.text
    assert first_user_jwt not in refresh.text
    assert second_user_jwt not in refresh.text


async def test_demo_refresh_failure_returns_safe_diagnostic_code(
    app, monkeypatch: pytest.MonkeyPatch
):
    """refresh 失败时应返回脱敏诊断码，避免所有 503 都只能看到 service unavailable。"""

    from deeptutor_enterprise.eduplus2 import fronting_demo
    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

    configure_demo_env(monkeypatch)
    enterprise = app.state.enterprise
    monkeypatch.setattr(
        enterprise,
        "eduplus2_resolver",
        StaticEduPlus2Resolver(
            {
                "client-a": {
                    "client_id": "client-a",
                    "external_tenant_id": "tenant-a",
                    "external_tenant_name": "学校 A",
                    "external_app_id": "app-math",
                    "external_app_name": "数学应用",
                    "status": "active",
                    "subscription_status": "active",
                    "policy": {"scopes": ["chat"]},
                    "version": "v1",
                }
            }
        ),
        raising=False,
    )
    monkeypatch.setattr(enterprise, "eduplus2_signing_key", EDUPLUS2_KEY, raising=False)
    monkeypatch.setattr(enterprise, "eduplus2_issuer", ISSUER, raising=False)
    admin = await enterprise.identity.login(
        "admin", "long-password-1", client="demo-refresh-diagnostic"
    )
    await enterprise.eduplus2.register_client(
        admin, "client-a", surface="tms", expected_tenant_id="tenant-a"
    )
    first_user_jwt = user_jwt(tid="tenant-a", eui="u-refresh-diagnostic", azp="client-a")

    async def fake_code_exchange(_config, _state, _code: str):
        return {
            "id_token": first_user_jwt,
            "refresh_token": "refresh-secret-that-must-never-leak",
            "token_type": "Bearer",
        }

    async def failing_refresh(_config, _refresh_token: str):
        raise RuntimeError("EduPlus2 refresh grant failed: refresh-secret-that-must-never-leak")

    monkeypatch.setattr(fronting_demo, "exchange_authorization_code", fake_code_exchange)
    monkeypatch.setattr(fronting_demo, "refresh_user_token", failing_refresh)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
        follow_redirects=False,
    ) as client:
        start = await client.get("/api/v1/auth/eduplus2/demo/start")
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        callback = await client.get(
            "/api/v1/auth/eduplus2/demo/callback",
            params={"state": state, "code": "auth-code-123"},
        )
        demo_session = parse_qs(urlsplit(callback.headers["location"]).query)["demo_session"][0]
        refresh = await client.post(
            "/api/v1/auth/eduplus2/demo/refresh",
            json={"demo_session": demo_session},
        )

    assert refresh.status_code == 503, refresh.text
    assert refresh.json() == {
        "detail": "Service unavailable",
        "error_code": "eduplus2_refresh_grant_failed",
    }
    assert "refresh-secret-that-must-never-leak" not in refresh.text
    assert first_user_jwt not in refresh.text


async def test_demo_result_ttl_can_cover_multi_turn_refresh_window(
    monkeypatch: pytest.MonkeyPatch,
):
    """多轮长对话不能只延长 dt_token；demo_session 的 refresh 窗口也要覆盖。"""

    from deeptutor_enterprise.eduplus2.fronting_demo import DemoResult

    monkeypatch.setenv("DT_EDUPLUS2_FRONTING_DEMO_RESULT_TTL_SECONDS", str(8 * 60 * 60))
    before = time.time()
    result = DemoResult(
        ok=True,
        request_id="demo-ttl",
        token_type="Bearer",
        dt_token="header.payload.signature",
        summary={},
        steps=[],
        refresh_token="refresh-token",
    )

    assert result.expires_at - before >= (8 * 60 * 60) - 5


async def test_demo_callback_rejects_unknown_state_without_exchanging_code(
    app, monkeypatch: pytest.MonkeyPatch
):
    """未知 state 必须 fail closed，不能继续调用 token endpoint 或 exchange。"""

    from deeptutor_enterprise.eduplus2 import fronting_demo

    configure_demo_env(monkeypatch)

    async def forbidden_code_exchange(*_args, **_kwargs):
        raise AssertionError("state mismatch must stop before token exchange")

    monkeypatch.setattr(fronting_demo, "exchange_authorization_code", forbidden_code_exchange)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://school.example",
        follow_redirects=False,
    ) as client:
        response = await client.get(
            "/api/v1/auth/eduplus2/demo/callback",
            params={"state": "unknown", "code": "auth-code-123"},
        )

    assert response.status_code in (302, 303, 307), response.text
    location = response.headers["location"]
    assert "demo_error=state_invalid" in location
    assert "auth-code-123" not in location


async def test_demo_start_missing_config_fails_closed_and_redacts(
    app, monkeypatch: pytest.MonkeyPatch
):
    """缺少授权端点/client/secret 时返回 503，且错误中不带敏感配置值。"""

    for name in (
        "DT_EDUPLUS2_AUTHORIZATION_ENDPOINT",
        "DT_EDUPLUS2_TOKEN_ENDPOINT",
        "DT_EDUPLUS2_CLIENT_ID",
        "DT_EDUPLUS2_CLIENT_SECRET",
        "DT_EDUPLUS2_CLIENT_SECRET_REF",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DT_EDUPLUS2_CLIENT_SECRET", "secret-that-must-never-leak")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        response = await client.get("/api/v1/auth/eduplus2/demo/start")

    assert response.status_code == 503
    assert response.json() == {"detail": "EduPlus2 demo is not configured"}
    assert "secret-that-must-never-leak" not in response.text


async def test_websocket_token_can_be_read_from_subprotocol_without_url_query():
    """浏览器 WS 不能设置 Authorization header；demo 用子协议承载内存 token，禁止 query token。"""

    from deeptutor_enterprise.api.application import bearer_from_headers_or_cookie

    token = "header.payload.signature"
    extracted, uses_bearer = bearer_from_headers_or_cookie(
        {
            "sec-websocket-protocol": f"deeptutor-token, {token}",
        },
        cookies={},
        scope_type="websocket",
    )
    assert extracted == token
    assert uses_bearer is True
    query_token, query_uses_bearer = bearer_from_headers_or_cookie(
        {},
        cookies={},
        scope_type="websocket",
        query={"dt_token": token},
    )
    assert query_token == ""
    assert query_uses_bearer is False
