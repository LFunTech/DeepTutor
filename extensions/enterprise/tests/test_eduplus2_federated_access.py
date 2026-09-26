"""EduPlus2 联邦接入：先锁定安全契约，再实现。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.scope import TenantScope
from deeptutor_enterprise.stores.postgres.connection import Database
import httpx
from jose import jwt
import pytest
from test_application import app as app

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio

SIGNING_KEY = "s" * 48
EDUPLUS2_KEY = "e" * 48
BOOTSTRAP_SECRET = "b" * 48
ISSUER = "https://eduplus2.test"


@pytest.fixture
async def enterprise_db(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    async with Database(
        single_database_user_dsn(pg_dsn), resource="eduplus2-test"
    ) as db:
        yield db


@pytest.fixture
async def identity(enterprise_db):
    from deeptutor_enterprise.identity.service import IdentityService

    tenant_id = str(uuid.uuid4())
    service = IdentityService(
        enterprise_db,
        tenant_id=tenant_id,
        signing_key=SIGNING_KEY,
        auth_epoch="epoch-eduplus2",
        bootstrap_secret=BOOTSTRAP_SECRET,
        token_seconds=900,
    )
    await service.bootstrap("admin", "long-password-1", secret=BOOTSTRAP_SECRET)
    return service


def user_jwt(*, tid: str, eui: str, azp: str, sub: str | None = None, iat: int | None = None):
    now = int(time.time()) if iat is None else iat
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": "eduplus2-api",
            "tid": tid,
            "eui": eui,
            "sub": sub or f"sub-{eui}",
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


def future_timestamp(days: int = 30) -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(days=days))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


async def test_eduplus2_migration_is_versioned_and_redacts_secret_material(enterprise_db, identity):
    async with enterprise_db.transaction(TenantScope(identity.tenant_id, identity.tenant_id)) as c:
        history = await (
            await c.execute("SELECT version FROM eduplus2.schema_history ORDER BY version")
        ).fetchall()
        assert [row["version"] for row in history] == [
            "0001_federated_access",
            "0002_profile_permission_snapshots",
            "0003_revocation_state",
            "0004_audit_export_jobs",
        ]
        await c.execute(
            """
            INSERT INTO eduplus2.provider_clients(
              tenant_id, client_id, secret_ref, issuer, base_url, redirect_uri,
              version, secret_fingerprint, installed_by
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                identity.tenant_id,
                "deeptutor-self",
                "secret://eduplus2/current",
                ISSUER,
                "https://eduplus2.test",
                "https://deeptutor.test/tms/callback",
                1,
                "fingerprint-only",
                "ops",
            ),
        )
        rows = await (await c.execute("SELECT * FROM eduplus2.provider_clients")).fetchall()
    rendered = str(rows)
    assert "client-secret-plain" not in rendered
    assert "secret://eduplus2/current" in rendered


async def test_register_client_requires_resolve_tenant_and_unique_active_registration(
    enterprise_db, identity
):
    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import (
        StaticEduPlus2PermissionClient,
        StaticEduPlus2ProfileClient,
        StaticEduPlus2Resolver,
    )

    resolver = StaticEduPlus2Resolver(
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
            },
            "client-b": {
                "client_id": "client-b",
                "external_tenant_id": "tenant-a",
                "external_tenant_name": "学校 A",
                "external_app_id": "app-math",
                "external_app_name": "数学应用",
                "status": "active",
                "subscription_status": "active",
                "policy": {"scopes": ["chat"]},
                "version": "v2",
            },
            "client-other": {
                "client_id": "client-other",
                "external_tenant_id": "tenant-other",
                "external_tenant_name": "其他学校",
                "external_app_id": "app-other",
                "external_app_name": "其他应用",
                "status": "active",
                "subscription_status": "active",
                "policy": {"scopes": ["chat"]},
                "version": "v1",
            },
        }
    )
    service = EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=resolver,
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
    )

    admin = await identity.login("admin", "long-password-1", client="test-register")
    first = await service.register_client(
        admin,
        "client-a",
        surface="tms",
        expected_tenant_id="tenant-a",
    )
    assert first["client_id"] == "client-a"
    with pytest.raises(ValueError, match="active registration"):
        await service.register_client(
            admin,
            "client-b",
            surface="tms",
            expected_tenant_id="tenant-a",
        )
    with pytest.raises(PermissionError, match="tenant"):
        await service.register_client(
            admin,
            "client-other",
            surface="tms",
            expected_tenant_id="tenant-a",
        )


async def test_exchange_uses_authorization_bearer_azp_and_issues_short_dt_token(
    enterprise_db, identity
):
    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

    resolver = StaticEduPlus2Resolver(
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
    )
    service = EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=resolver,
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
        dt_token_seconds=900,
    )
    admin = await identity.login("admin", "long-password-1", client="test-exchange")
    await service.register_client(admin, "client-a", surface="tms", expected_tenant_id="tenant-a")

    exchanged = await service.exchange_user_jwt(
        user_jwt(tid="tenant-a", eui="u-001", azp="client-a"), request_id="req-1"
    )
    assert exchanged["token_type"] == "Bearer"
    assert exchanged["expires_in"] <= 900
    assert "eduplus2_token" not in exchanged
    claims = jwt.get_unverified_claims(exchanged["dt_token"])
    assert claims["eduplus2"]["client_registration_id"]
    assert claims["eduplus2"]["external_tenant_id"] == "tenant-a"
    authenticated = await identity.authenticate(exchanged["dt_token"])
    assert authenticated.username == "u-001"
    assert authenticated.tenant_id == identity.tenant_id

    with pytest.raises(PermissionError, match="azp"):
        await service.exchange_user_jwt(user_jwt(tid="tenant-a", eui="u-001", azp="unknown"))
    with pytest.raises(PermissionError, match="tenant"):
        await service.exchange_user_jwt(user_jwt(tid="tenant-other", eui="u-001", azp="client-a"))
    with pytest.raises(PermissionError, match="required"):
        token = jwt.encode(
            {
                "iss": ISSUER,
                "tid": "tenant-a",
                "eui": "u-001",
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
            },
            EDUPLUS2_KEY,
            algorithm="HS256",
        )
        await service.exchange_user_jwt(token)

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, identity.tenant_id)) as c:
        rows = await (
            await c.execute(
                "SELECT event_kind, result, request_id, summary FROM eduplus2.audit_events"
            )
        ).fetchall()
        local_credentials = await (
            await c.execute(
                "SELECT * FROM enterprise.local_credentials WHERE tenant_id=%s AND user_id=%s",
                (identity.tenant_id, authenticated.user_id),
            )
        ).fetchall()
    assert local_credentials == []
    rendered = str(rows)
    assert "req-1" in rendered
    assert exchanged["dt_token"] not in rendered
    assert EDUPLUS2_KEY not in rendered
    assert "Bearer" not in rendered


async def test_exchange_rejects_invalid_jwt_and_inactive_registration(enterprise_db, identity):
    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

    resolver = StaticEduPlus2Resolver(
        {
            "client-a": {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "status": "active",
                "subscription_status": "active",
                "policy": {"scopes": ["chat"]},
                "version": "v1",
            }
        }
    )
    service = EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=resolver,
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
    )
    admin = await identity.login("admin", "long-password-1", client="test-invalid-jwt")
    await service.register_client(admin, "client-a", surface="tms", expected_tenant_id="tenant-a")

    valid = user_jwt(tid="tenant-a", eui="u-invalid", azp="client-a")
    with pytest.raises(PermissionError, match="verification"):
        await service.exchange_user_jwt(valid[:-2] + "xx")
    with pytest.raises(PermissionError, match="verification|issuer mismatch"):
        await service.exchange_user_jwt(
            jwt.encode(
                {
                    "iss": ISSUER + "/wrong",
                    "tid": "tenant-a",
                    "eui": "u-invalid",
                    "sub": "sub-invalid",
                    "azp": "client-a",
                    "iat": int(time.time()),
                    "exp": int(time.time()) + 600,
                },
                EDUPLUS2_KEY,
                algorithm="HS256",
            )
        )
    with pytest.raises(PermissionError, match="expired"):
        await service.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-invalid", azp="client-a", iat=int(time.time()) - 700)
        )
    with pytest.raises(PermissionError, match="future"):
        await service.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-invalid", azp="client-a", iat=int(time.time()) + 60)
        )

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, identity.tenant_id)) as c:
        await c.execute(
            """
            UPDATE eduplus2.external_client_registrations
               SET status='suspended'
             WHERE tenant_id=%s AND client_id='client-a'
            """,
            (identity.tenant_id,),
        )
    with pytest.raises(PermissionError, match="azp"):
        await service.exchange_user_jwt(valid)


async def test_exchange_rejects_token_replay_and_rate_limit(enterprise_db, identity):
    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

    resolver = StaticEduPlus2Resolver(
        {
            "client-a": {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "status": "active",
                "subscription_status": "active",
                "policy": {"scopes": ["chat"]},
                "version": "v1",
            }
        }
    )
    service = EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=resolver,
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
        exchange_rate_limit_per_minute=1,
    )
    admin = await identity.login("admin", "long-password-1", client="test-replay")
    await service.register_client(admin, "client-a", surface="tms", expected_tenant_id="tenant-a")

    token = user_jwt(tid="tenant-a", eui="u-replay", azp="client-a")
    assert (await service.exchange_user_jwt(token))["dt_token"]
    with pytest.raises(PermissionError, match="replay"):
        await service.exchange_user_jwt(token)
    with pytest.raises(PermissionError, match="rate"):
        await service.exchange_user_jwt(user_jwt(tid="tenant-a", eui="u-replay", azp="client-a"))


async def test_exchange_api_rejects_body_identity_and_returns_sanitized_errors(app, monkeypatch):
    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

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

    admin = await enterprise.identity.login("admin", "long-password-1", client="api-setup")
    await enterprise.eduplus2.register_client(
        admin, "client-a", surface="tms", expected_tenant_id="tenant-a"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        no_bearer = await client.post(
            "/api/v1/auth/eduplus2/exchange",
            headers={"Origin": "https://school.example"},
            json={"token": user_jwt(tid="tenant-a", eui="u-body", azp="client-a")},
        )
        assert no_bearer.status_code == 401
        ok = await client.post(
            "/api/v1/auth/eduplus2/exchange",
            headers={
                "Origin": "https://school.example",
                "Authorization": "Bearer " + user_jwt(tid="tenant-a", eui="u-api", azp="client-a"),
            },
            json={"tenant_id": "forged", "client_id": "forged"},
        )
        assert ok.status_code == 200, ok.text
        assert "dt_token" in ok.json()
        wrong = await client.post(
            "/api/v1/auth/eduplus2/exchange",
            headers={
                "Origin": "https://school.example",
                "Authorization": "Bearer "
                + user_jwt(tid="tenant-other", eui="u-api", azp="client-a"),
            },
        )
        assert wrong.status_code == 409
        assert EDUPLUS2_KEY not in wrong.text
        unknown = await client.post(
            "/api/v1/auth/eduplus2/exchange",
            headers={
                "Origin": "https://school.example",
                "Authorization": "Bearer "
                + user_jwt(tid="tenant-a", eui="u-api", azp="unknown-client"),
            },
        )
        assert unknown.status_code == 403
        assert EDUPLUS2_KEY not in unknown.text


async def test_eduplus2_dt_token_uses_existing_owner_guard(app, monkeypatch):
    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

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

    admin = await enterprise.identity.login("admin", "long-password-1", client="guard-setup")
    await enterprise.eduplus2.register_client(
        admin, "client-a", surface="tms", expected_tenant_id="tenant-a"
    )
    token_a = (
        await enterprise.eduplus2.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-owner-a", azp="client-a")
        )
    )["dt_token"]
    exchanged_b = await enterprise.eduplus2.exchange_user_jwt(
        user_jwt(tid="tenant-a", eui="u-owner-b", azp="client-a")
    )
    token_b = exchanged_b["dt_token"]
    async with enterprise.sdk(token_a):
        from deeptutor.services.session import get_session_store

        session = await get_session_store().create_session(title="owner-only")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        own = await client.get(
            "/api/sessions/" + session["id"], headers={"Authorization": "Bearer " + token_a}
        )
        other = await client.get(
            "/api/sessions/" + session["id"], headers={"Authorization": "Bearer " + token_b}
        )
    assert own.status_code == 200
    assert other.status_code == 404
    async with enterprise.db.transaction(TenantScope(enterprise.identity.tenant_id, "@audit")) as c:
        denied = await (
            await c.execute(
                """
                SELECT event_kind,client_id,external_user_id,internal_user_id,result,reason,summary
                  FROM eduplus2.audit_events
                 WHERE event_kind='authz.denied' AND internal_user_id=%s
                """,
                (exchanged_b["user_id"],),
            )
        ).fetchone()
    assert dict(denied) | {"summary": dict(denied["summary"])} == {
        "event_kind": "authz.denied",
        "client_id": "client-a",
        "external_user_id": "u-owner-b",
        "internal_user_id": exchanged_b["user_id"],
        "result": "denied",
        "reason": "http.404",
        "summary": {"path": "/api/sessions/" + session["id"], "status": 404},
    }


async def test_ws_auth_refresh_accepts_only_same_eduplus2_identity(app, monkeypatch):
    """防止 WS refresh 用另一个 EduPlus2 用户的 dt_token 扩权或换人。"""

    from deeptutor_enterprise.api.application import SocketAuthentication
    from deeptutor_enterprise.eduplus2.testing import (
        StaticEduPlus2PermissionClient,
        StaticEduPlus2ProfileClient,
        StaticEduPlus2Resolver,
    )

    enterprise = app.state.enterprise
    monkeypatch.setattr(
        enterprise,
        "eduplus2_resolver",
        StaticEduPlus2Resolver(
            {
                "client-a": {
                    "client_id": "client-a",
                    "external_tenant_id": "tenant-a",
                    "external_app_id": "app-math",
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

    admin = await enterprise.identity.login("admin", "long-password-1", client="ws-refresh-setup")
    await enterprise.eduplus2.register_client(
        admin, "client-a", surface="tms", expected_tenant_id="tenant-a"
    )
    old_token = (
        await enterprise.eduplus2.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-ws-refresh", azp="client-a")
        )
    )["dt_token"]
    new_token = (
        await enterprise.eduplus2.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-ws-refresh", azp="client-a")
        )
    )["dt_token"]
    other_token = (
        await enterprise.eduplus2.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-ws-other", azp="client-a")
        )
    )["dt_token"]

    ws = SimpleNamespace(
        state=SimpleNamespace(
            enterprise_token=old_token,
            enterprise_identity=await enterprise.identity.authenticate(old_token),
        )
    )
    ack = await SocketAuthentication(enterprise).refresh(
        ws,
        {"command_id": "refresh-1", "dt_token": new_token},
    )
    assert ws.state.enterprise_token == new_token
    assert ack["expires_at"] >= int(time.time())
    assert ack["session_id"]
    async with enterprise.db.transaction(TenantScope(enterprise.identity.tenant_id, "@audit")) as c:
        refresh_audit = await (
            await c.execute(
                """
                SELECT event_kind,result,reason FROM eduplus2.audit_events
                 WHERE event_kind='token.refresh' AND request_id='refresh-1'
                """
            )
        ).fetchone()
    assert dict(refresh_audit) == {
        "event_kind": "token.refresh",
        "result": "success",
        "reason": "dt_token",
    }

    monkeypatch.setattr(
        enterprise,
        "eduplus2_profile_client",
        StaticEduPlus2ProfileClient(
            {
                ("tenant-a", "u-ws-refresh"): {
                    "external_tenant_id": "tenant-a",
                    "external_user_id": "u-ws-refresh",
                    "external_subject": "sub-u-ws-refresh",
                    "external_identity_type": "teacher",
                    "status": "active",
                    "version": "pv-refresh",
                }
            }
        ),
        raising=False,
    )
    monkeypatch.setattr(
        enterprise,
        "eduplus2_permission_client",
        StaticEduPlus2PermissionClient(
            {
                ("tenant-a", "u-ws-refresh", "client-a", "app-math"): {
                    "allowed": True,
                    "reason": "ok",
                    "allowed_usages": ["deeptutor.chat", "oms.admin"],
                    "scopes": ["chat"],
                    "version": "perm-refresh",
                }
            }
        ),
        raising=False,
    )
    jwt_ack = await SocketAuthentication(enterprise).refresh(
        ws,
        {
            "command_id": "refresh-eduplus2-jwt",
            "external_token": user_jwt(tid="tenant-a", eui="u-ws-refresh", azp="client-a"),
        },
    )
    assert ws.state.enterprise_token != new_token
    assert jwt_ack["expires_at"] >= int(time.time())
    refreshed_claims = jwt.get_unverified_claims(ws.state.enterprise_token)
    assert refreshed_claims["eduplus2"]["allowed_usages"] == ["deeptutor.chat"]
    async with enterprise.db.transaction(TenantScope(enterprise.identity.tenant_id, "@audit")) as c:
        profile = await (
            await c.execute(
                """
                SELECT profile_version FROM eduplus2.profile_snapshots
                 WHERE external_user_id='u-ws-refresh'
                """
            )
        ).fetchone()
        permission = await (
            await c.execute(
                """
                SELECT permission_version FROM eduplus2.permission_snapshots
                 WHERE external_user_id='u-ws-refresh'
                """
            )
        ).fetchone()
    assert profile["profile_version"] == "pv-refresh"
    assert permission["permission_version"] == "perm-refresh"

    with pytest.raises(PermissionError, match="identity"):
        await SocketAuthentication(enterprise).refresh(
            ws,
            {"command_id": "refresh-2", "dt_token": other_token},
        )


def _b64url_uint(value: int) -> str:
    import base64

    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


async def test_oidc_jwks_verifier_accepts_rs256_and_rejects_missing_azp():
    """防止生产 verifier 退化为测试 HS256 key 或跳过 azp 主校验。"""

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from deeptutor_enterprise.eduplus2.client import EduPlus2OidcJwtVerifier

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "rs-kid-1",
        "use": "sig",
        "alg": "RS256",
        "n": _b64url_uint(public_numbers.n),
        "e": _b64url_uint(public_numbers.e),
    }
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "jwks_uri": "https://eduplus2.test/protocol/openid-connect/certs",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if request.url.path.endswith("/protocol/openid-connect/certs"):
            return httpx.Response(200, json={"keys": [jwk]})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        verifier = EduPlus2OidcJwtVerifier(
            discovery_url=ISSUER + "/.well-known/openid-configuration",
            issuer=ISSUER,
            http_client=http_client,
        )
        now = int(time.time())
        token = jwt.encode(
            {
                "iss": ISSUER,
                "tid": "tenant-a",
                "eui": "u-rsa",
                "sub": "sub-rsa",
                "azp": "client-a",
                "iat": now,
                "nbf": now - 1,
                "exp": now + 600,
            },
            private_pem,
            algorithm="RS256",
            headers={"kid": "rs-kid-1"},
        )
        verified = await verifier.verify(token)
        assert verified.claims["azp"] == "client-a"
        assert verified.header["kid"] == "rs-kid-1"
        assert verified.token_hash and token not in verified.token_hash

        id_token_with_at_hash = jwt.encode(
            {
                "iss": ISSUER,
                "tid": "tenant-a",
                "eui": "u-rsa",
                "sub": "sub-rsa",
                "azp": "client-a",
                "aud": "client-a",
                "iat": now,
                "nbf": now - 1,
                "exp": now + 600,
                "at_hash": "provider-access-token-hash",
            },
            private_pem,
            algorithm="RS256",
            headers={"kid": "rs-kid-1"},
        )
        verified_id_token = await verifier.verify(id_token_with_at_hash)
        assert verified_id_token.claims["at_hash"] == "provider-access-token-hash"

        missing_azp = jwt.encode(
            {
                "iss": ISSUER,
                "tid": "tenant-a",
                "eui": "u-rsa",
                "sub": "sub-rsa",
                "iat": now,
                "exp": now + 600,
            },
            private_pem,
            algorithm="RS256",
            headers={"kid": "rs-kid-1"},
        )
        with pytest.raises(PermissionError, match="required"):
            await verifier.verify(missing_azp)

        wrong_issuer = jwt.encode(
            {
                "iss": ISSUER + "/other",
                "tid": "tenant-a",
                "eui": "u-rsa",
                "sub": "sub-rsa",
                "azp": "client-a",
                "iat": now,
                "exp": now + 600,
            },
            private_pem,
            algorithm="RS256",
            headers={"kid": "rs-kid-1"},
        )
        with pytest.raises(PermissionError, match="token issuer mismatch"):
            await verifier.verify(wrong_issuer)

        expired = jwt.encode(
            {
                "iss": ISSUER,
                "tid": "tenant-a",
                "eui": "u-rsa",
                "sub": "sub-rsa",
                "azp": "client-a",
                "iat": now - 1200,
                "exp": now - 600,
            },
            private_pem,
            algorithm="RS256",
            headers={"kid": "rs-kid-1"},
        )
        with pytest.raises(PermissionError, match="expired"):
            await verifier.verify(expired)


async def test_resolve_client_uses_m2m_token_and_normalizes_nested_response():
    """防止 resolve client 使用调用方 JWT、泄露 secret 或依赖扁平测试替身结构。"""

    from deeptutor_enterprise.eduplus2.client import EduPlus2ResolveClient

    calls: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        content = await request.aread()
        calls.append((request.method, request.url.path, content))
        if request.url.path.endswith("/protocol/openid-connect/token"):
            assert request.headers.get("authorization", "").lower().startswith("basic ")
            return httpx.Response(200, json={"access_token": "m2m-token", "expires_in": 300})
        if request.url.path.endswith("/api/v1/open/oauth-clients/resolve"):
            assert request.headers.get("authorization") == "Bearer m2m-token"
            assert b"super-secret" not in content
            if b"expected_tenant_id" in content:
                assert b"tenant-a" in content
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "success",
                    "data": {
                        "verified": True,
                        "reason": "ok",
                        "version": "rv-1",
                        "client": {"client_id": "client-a", "status": "active"},
                        "tenant": {"id": "tenant-a", "name": "学校 A", "status": "active"},
                        "app": {"id": "app-math", "name": "数学应用", "status": "active"},
                        "oauth": {"allowed_grant_types": ["authorization_code"]},
                        "policy": {"subscription_status": "active", "scopes": ["chat"]},
                    },
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = EduPlus2ResolveClient(
            token_url="https://eduplus-auth-test.f123.pub/realms/eduplus/protocol/openid-connect/token",
            resolve_url="https://eduplus-test.f123.pub/api/v1/open/oauth-clients/resolve",
            client_id="m2m-client",
            client_secret="super-secret",
            http_client=http_client,
        )
        first = await client.resolve_client("client-a")
        second = await client.resolve_client("client-a")
        third = await client.resolve_client("client-a", expected_tenant_id="tenant-a")

    assert first == second
    assert third == first
    assert first["client_id"] == "client-a"
    assert first["external_tenant_id"] == "tenant-a"
    assert first["external_tenant_name"] == "学校 A"
    assert first["external_app_id"] == "app-math"
    assert first["status"] == "active"
    assert first["tenant_status"] == "active"
    assert first["app_status"] == "active"
    assert first["subscription_status"] == "active"
    assert first["version"] == "rv-1"
    assert first["policy"]["scopes"] == ["chat"]
    assert len([call for call in calls if call[1].endswith("/token")]) == 1


async def test_resolve_client_error_messages_redact_m2m_secret_and_token():
    """防止外部失败路径把 client secret 或 M2M access token 写入异常/日志消息。"""

    from deeptutor_enterprise.eduplus2.client import EduPlus2ResolveClient

    async def token_rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(token_rejected)) as http_client:
        client = EduPlus2ResolveClient(
            token_url="https://issuer.test/token",
            resolve_url="https://api.test/resolve",
            client_id="m2m-client",
            client_secret="super-secret",
            http_client=http_client,
        )
        with pytest.raises(RuntimeError) as error:
            await client.resolve_client("client-a")
    assert "super-secret" not in str(error.value)

    async def resolve_rejected(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "m2m-token", "expires_in": 300})
        return httpx.Response(503, json={"message": "temporarily unavailable"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(resolve_rejected)) as http_client:
        client = EduPlus2ResolveClient(
            token_url="https://issuer.test/token",
            resolve_url="https://api.test/resolve",
            client_id="m2m-client",
            client_secret="super-secret",
            http_client=http_client,
        )
        with pytest.raises(RuntimeError) as error:
            await client.resolve_client("client-a")
    assert "super-secret" not in str(error.value)
    assert "m2m-token" not in str(error.value)


async def test_profile_client_uses_m2m_token_and_normalizes_minimal_snapshot():
    """防止 profile 接入保存敏感原文，或绕过服务端 M2M 鉴权。"""

    from deeptutor_enterprise.eduplus2.client import EduPlus2ProfileClient

    calls: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        content = await request.aread()
        calls.append((request.method, request.url.path, content))
        if request.url.path.endswith("/token"):
            assert request.headers.get("authorization", "").lower().startswith("basic ")
            return httpx.Response(200, json={"access_token": "profile-m2m", "expires_in": 300})
        if request.url.path.endswith("/profile"):
            assert request.headers.get("authorization") == "Bearer profile-m2m"
            assert b"profile-secret" not in content
            assert b"tenant-a" in content
            assert b"u-profile" in content
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "verified": True,
                        "profile": {
                            "tenant_id": "tenant-a",
                            "user_id": "u-profile",
                            "subject": "sub-profile",
                            "identity_type": "teacher",
                            "display_name": "王老师",
                            "status": "active",
                            "version": "pv-1",
                            "phone": "should-not-be-kept",
                        },
                    },
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = EduPlus2ProfileClient(
            token_url="https://issuer.test/token",
            profile_url="https://api.test/profile",
            client_id="m2m-client",
            client_secret="profile-secret",
            http_client=http_client,
        )
        profile = await client.fetch_profile(
            external_tenant_id="tenant-a",
            external_user_id="u-profile",
            external_subject="sub-profile",
            client_id="client-a",
            external_app_id="app-math",
        )

    assert profile == {
        "external_tenant_id": "tenant-a",
        "external_user_id": "u-profile",
        "external_subject": "sub-profile",
        "external_identity_type": "teacher",
        "display_name": "王老师",
        "status": "active",
        "version": "pv-1",
        "summary": {
            "external_tenant_id": "tenant-a",
            "external_user_id": "u-profile",
            "external_subject": "sub-profile",
            "external_identity_type": "teacher",
            "display_name": "王老师",
            "status": "active",
            "version": "pv-1",
        },
    }
    assert len([call for call in calls if call[1].endswith("/token")]) == 1


async def test_permission_client_uses_m2m_token_and_normalizes_allowed_usages():
    """防止 permission 接入依赖测试扁平结构或泄露 M2M 凭据。"""

    from deeptutor_enterprise.eduplus2.client import EduPlus2PermissionClient

    expires_at = future_timestamp()

    async def handler(request: httpx.Request) -> httpx.Response:
        content = await request.aread()
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "permission-m2m", "expires_in": 300})
        if request.url.path.endswith("/permissions/check"):
            assert request.headers.get("authorization") == "Bearer permission-m2m"
            assert b"permission-secret" not in content
            assert b"deeptutor.chat" in content
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "allowed": True,
                        "reason": "ok",
                        "tenant": {"id": "tenant-a"},
                        "user": {"id": "u-permission", "subject": "sub-permission"},
                        "client": {"client_id": "client-a"},
                        "app": {"id": "app-math"},
                        "permission": {
                            "version": "perm-v1",
                            "allowed_usages": ["deeptutor.chat", "tms.manage"],
                            "scopes": ["chat", "oms.admin"],
                            "expires_at": expires_at,
                        },
                    },
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = EduPlus2PermissionClient(
            token_url="https://issuer.test/token",
            permission_url="https://api.test/permissions/check",
            client_id="m2m-client",
            client_secret="permission-secret",
            http_client=http_client,
        )
        permission = await client.check_permission(
            external_tenant_id="tenant-a",
            external_user_id="u-permission",
            external_subject="sub-permission",
            client_id="client-a",
            external_app_id="app-math",
            requested_usages=("deeptutor.chat",),
        )

    assert permission["allowed"] is True
    assert permission["external_tenant_id"] == "tenant-a"
    assert permission["external_user_id"] == "u-permission"
    assert permission["client_id"] == "client-a"
    assert permission["external_app_id"] == "app-math"
    assert permission["version"] == "perm-v1"
    assert permission["allowed_usages"] == ["deeptutor.chat", "tms.manage"]
    assert permission["scopes"] == ["chat", "oms.admin"]
    assert permission["expires_at"] == expires_at


async def test_exchange_auto_upserts_allowlisted_client_and_caches_resolve(enterprise_db, identity):
    """防止 B1-lite 在没有 TMS/OMS 预注册页面时无法完成首次合法换票。"""

    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

    class CountingResolver(StaticEduPlus2Resolver):
        def __init__(self, clients):
            super().__init__(clients)
            self.count = 0

        async def resolve_client(self, client_id: str) -> dict:
            self.count += 1
            return await super().resolve_client(client_id)

    resolver = CountingResolver(
        {
            "client-allowed": {
                "client_id": "client-allowed",
                "external_tenant_id": "tenant-a",
                "external_tenant_name": "学校 A",
                "external_app_id": "app-math",
                "external_app_name": "数学应用",
                "status": "active",
                "subscription_status": "active",
                "policy": {"scopes": ["chat"]},
                "version": "v1",
            },
            "client-other-app": {
                "client_id": "client-other-app",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-other",
                "status": "active",
                "subscription_status": "active",
                "policy": {"scopes": ["chat"]},
                "version": "v1",
            },
        }
    )
    service = EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=resolver,
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
        allowed_clients=(
            {
                "client_id": "client-allowed",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "internal_tenant_id": identity.tenant_id,
                "source": "env_allowlist",
            },
        ),
        resolve_cache_seconds=60,
    )

    first = await service.exchange_user_jwt(
        user_jwt(tid="tenant-a", eui="u-auto", azp="client-allowed"), request_id="req-auto-1"
    )
    second = await service.exchange_user_jwt(
        user_jwt(tid="tenant-a", eui="u-auto", azp="client-allowed"), request_id="req-auto-2"
    )
    assert first["client_registration_id"] == second["client_registration_id"]
    assert resolver.count == 1

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, identity.tenant_id)) as c:
        registrations = await (
            await c.execute(
                """
                SELECT client_id,external_tenant_id,external_app_id,registered_by_surface,status
                  FROM eduplus2.external_client_registrations
                 WHERE client_id='client-allowed'
                """
            )
        ).fetchall()
    assert [dict(row) for row in registrations] == [
        {
            "client_id": "client-allowed",
            "external_tenant_id": "tenant-a",
            "external_app_id": "app-math",
            "registered_by_surface": "env_allowlist",
            "status": "active",
        }
    ]

    with pytest.raises(PermissionError, match="azp"):
        await service.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-auto", azp="client-other-app")
        )


async def test_exchange_checks_profile_permission_and_persists_snapshots(enterprise_db, identity):
    """防止换票只校验 client，不复核外部用户状态和能力边界。"""

    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import (
        StaticEduPlus2PermissionClient,
        StaticEduPlus2ProfileClient,
        StaticEduPlus2Resolver,
    )

    permission_expires_at = future_timestamp()
    resolver = StaticEduPlus2Resolver(
        {
            "client-a": {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "status": "active",
                "subscription_status": "active",
                "policy": {"scopes": ["chat"]},
                "version": "rv-profile-permission",
            }
        }
    )
    service = EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=resolver,
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
        allowed_clients=(
            {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "internal_tenant_id": identity.tenant_id,
            },
        ),
        profile_client=StaticEduPlus2ProfileClient(
            {
                ("tenant-a", "u-profile"): {
                    "external_tenant_id": "tenant-a",
                    "external_user_id": "u-profile",
                    "external_subject": "sub-u-profile",
                    "external_identity_type": "teacher",
                    "display_name": "王老师",
                    "status": "active",
                    "version": "pv-1",
                },
                ("tenant-a", "u-mismatch"): {
                    "external_tenant_id": "tenant-other",
                    "external_user_id": "u-mismatch",
                    "external_subject": "sub-u-mismatch",
                    "status": "active",
                    "version": "pv-mismatch",
                },
                ("tenant-a", "u-disabled"): {
                    "external_tenant_id": "tenant-a",
                    "external_user_id": "u-disabled",
                    "external_subject": "sub-u-disabled",
                    "status": "disabled",
                    "version": "pv-disabled",
                },
            }
        ),
        permission_client=StaticEduPlus2PermissionClient(
            {
                ("tenant-a", "u-profile", "client-a", "app-math"): {
                    "allowed": True,
                    "reason": "ok",
                    "allowed_usages": ["deeptutor.chat", "tms.manage", "oms.admin"],
                    "scopes": ["chat"],
                    "version": "perm-v1",
                    "expires_at": permission_expires_at,
                },
                ("tenant-a", "u-disabled", "client-a", "app-math"): {
                    "allowed": True,
                    "reason": "ok",
                    "allowed_usages": ["deeptutor.chat"],
                    "scopes": ["chat"],
                    "version": "perm-disabled",
                },
            }
        ),
    )

    exchanged = await service.exchange_user_jwt(
        user_jwt(tid="tenant-a", eui="u-profile", sub="sub-u-profile", azp="client-a"),
        request_id="req-profile-permission",
    )
    claims = jwt.get_unverified_claims(exchanged["dt_token"])
    assert claims["eduplus2"]["allowed_usages"] == ["deeptutor.chat"]
    assert "tms.manage" not in claims["eduplus2"]["allowed_usages"]
    assert "oms.admin" not in claims["eduplus2"]["allowed_usages"]

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, identity.tenant_id)) as c:
        profile = await (
            await c.execute(
                """
                SELECT external_user_id,external_subject,external_identity_type,status,
                       profile_version,profile_snapshot
                  FROM eduplus2.profile_snapshots
                 WHERE external_user_id='u-profile'
                """
            )
        ).fetchone()
        permission = await (
            await c.execute(
                """
                SELECT external_user_id,client_registration_id,allowed,reason,
                       allowed_usages,scopes,permission_version,permission_snapshot
                  FROM eduplus2.permission_snapshots
                 WHERE external_user_id='u-profile'
                """
            )
        ).fetchone()
        audit_kinds = [
            row["event_kind"]
            for row in await (
                await c.execute(
                    """
                    SELECT event_kind FROM eduplus2.audit_events
                     WHERE request_id='req-profile-permission'
                     ORDER BY created_at
                    """
                )
            ).fetchall()
        ]
    assert dict(profile) | {"profile_snapshot": dict(profile["profile_snapshot"])} == {
        "external_user_id": "u-profile",
        "external_subject": "sub-u-profile",
        "external_identity_type": "teacher",
        "status": "active",
        "profile_version": "pv-1",
        "profile_snapshot": {
            "display_name": "王老师",
            "external_identity_type": "teacher",
            "external_subject": "sub-u-profile",
            "external_tenant_id": "tenant-a",
            "external_user_id": "u-profile",
            "status": "active",
            "version": "pv-1",
        },
    }
    assert permission["client_registration_id"] == uuid.UUID(exchanged["client_registration_id"])
    assert permission["allowed"] is True
    assert permission["reason"] == "ok"
    assert permission["allowed_usages"] == ["deeptutor.chat", "tms.manage", "oms.admin"]
    assert permission["scopes"] == ["chat"]
    assert permission["permission_version"] == "perm-v1"
    assert "profile.fetch" in audit_kinds
    assert "permission.check" in audit_kinds

    with pytest.raises(PermissionError, match="profile"):
        await service.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-mismatch", sub="sub-u-mismatch", azp="client-a")
        )
    with pytest.raises(PermissionError, match="profile"):
        await service.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-disabled", sub="sub-u-disabled", azp="client-a")
        )


async def test_exchange_denies_permission_api_denied_result(enterprise_db, identity):
    """防止 permission API denied 时仍签发 DeepTutor token。"""

    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import (
        StaticEduPlus2PermissionClient,
        StaticEduPlus2ProfileClient,
        StaticEduPlus2Resolver,
    )

    resolver = StaticEduPlus2Resolver(
        {
            "client-a": {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "status": "active",
                "subscription_status": "active",
                "policy": {"scopes": ["chat"]},
                "version": "rv-denied",
            }
        }
    )
    service = EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=resolver,
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
        allowed_clients=(
            {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "internal_tenant_id": identity.tenant_id,
            },
        ),
        profile_client=StaticEduPlus2ProfileClient(
            {
                ("tenant-a", "u-denied"): {
                    "external_tenant_id": "tenant-a",
                    "external_user_id": "u-denied",
                    "external_subject": "sub-u-denied",
                    "status": "active",
                    "version": "pv-denied",
                }
            }
        ),
        permission_client=StaticEduPlus2PermissionClient(
            {
                ("tenant-a", "u-denied", "client-a", "app-math"): {
                    "allowed": False,
                    "reason": "permission_revoked",
                    "allowed_usages": [],
                    "scopes": [],
                    "version": "perm-denied",
                }
            }
        ),
    )

    with pytest.raises(PermissionError, match="permission"):
        await service.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-denied", sub="sub-u-denied", azp="client-a"),
            request_id="req-permission-denied",
        )

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, identity.tenant_id)) as c:
        bindings = await (
            await c.execute(
                """
                SELECT * FROM eduplus2.identity_bindings
                 WHERE external_tenant_id='tenant-a' AND external_user_id='u-denied'
                """
            )
        ).fetchall()
        denied = await (
            await c.execute(
                """
                SELECT event_kind,result,reason FROM eduplus2.audit_events
                 WHERE request_id='req-permission-denied' AND event_kind='permission.check'
                """
            )
        ).fetchone()
    assert bindings == []
    assert dict(denied) == {
        "event_kind": "permission.check",
        "result": "denied",
        "reason": "permission_revoked",
    }


async def test_exchange_fails_closed_when_profile_or_permission_unavailable_or_expired(
    enterprise_db, identity
):
    """防止 profile/permission 外部不可用或权限快照过期时继续签发 token。"""

    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import (
        StaticEduPlus2PermissionClient,
        StaticEduPlus2ProfileClient,
        StaticEduPlus2Resolver,
    )

    resolver = StaticEduPlus2Resolver(
        {
            "client-a": {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "status": "active",
                "subscription_status": "active",
                "policy": {"scopes": ["chat"]},
                "version": "rv-fail-closed",
            }
        }
    )
    common = {
        "identity": identity,
        "resolver": resolver,
        "eduplus2_signing_key": EDUPLUS2_KEY,
        "eduplus2_issuer": ISSUER,
        "allowed_clients": (
            {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "internal_tenant_id": identity.tenant_id,
            },
        ),
    }

    missing_profile = EduPlus2AccessService(
        enterprise_db,
        **common,
        profile_client=StaticEduPlus2ProfileClient({}),
    )
    with pytest.raises(RuntimeError, match="profile unavailable"):
        await missing_profile.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-no-profile", azp="client-a")
        )

    missing_permission = EduPlus2AccessService(
        enterprise_db,
        **common,
        profile_client=StaticEduPlus2ProfileClient(
            {
                ("tenant-a", "u-no-permission"): {
                    "external_tenant_id": "tenant-a",
                    "external_user_id": "u-no-permission",
                    "external_subject": "sub-u-no-permission",
                    "status": "active",
                    "version": "pv-no-permission",
                }
            }
        ),
        permission_client=StaticEduPlus2PermissionClient({}),
    )
    with pytest.raises(RuntimeError, match="permission unavailable"):
        await missing_permission.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-no-permission", azp="client-a")
        )

    expired_permission = EduPlus2AccessService(
        enterprise_db,
        **common,
        profile_client=StaticEduPlus2ProfileClient(
            {
                ("tenant-a", "u-expired-permission"): {
                    "external_tenant_id": "tenant-a",
                    "external_user_id": "u-expired-permission",
                    "external_subject": "sub-u-expired-permission",
                    "status": "active",
                    "version": "pv-expired-permission",
                }
            }
        ),
        permission_client=StaticEduPlus2PermissionClient(
            {
                ("tenant-a", "u-expired-permission", "client-a", "app-math"): {
                    "allowed": True,
                    "reason": "stale",
                    "allowed_usages": ["deeptutor.chat"],
                    "scopes": ["chat"],
                    "version": "perm-expired",
                    "expires_at": "2000-01-01T00:00:00Z",
                }
            }
        ),
    )
    with pytest.raises(PermissionError, match="permission"):
        await expired_permission.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-expired-permission", azp="client-a")
        )


async def test_revocation_event_rejects_new_exchange_and_existing_token(enterprise_db, identity):
    """防止 EduPlus2 撤权后旧 token 或新 exchange 继续可用。"""

    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

    resolver = StaticEduPlus2Resolver(
        {
            "client-a": {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "status": "active",
                "subscription_status": "active",
                "policy": {"scopes": ["chat"]},
                "version": "rv-revocation",
            }
        }
    )
    service = EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=resolver,
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
        allowed_clients=(
            {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "internal_tenant_id": identity.tenant_id,
            },
        ),
    )
    exchanged = await service.exchange_user_jwt(
        user_jwt(tid="tenant-a", eui="u-revoked", azp="client-a"),
        request_id="req-before-revoke",
    )
    applied = await service.apply_revocation_event(
        {
            "event_id": "evt-revoke-user-1",
            "event_type": "permission.revoked",
            "external_tenant_id": "tenant-a",
            "external_user_id": "u-revoked",
            "client_id": "client-a",
            "external_app_id": "app-math",
            "reason": "permission_revoked",
        },
        request_id="req-revoke",
    )
    duplicate = await service.apply_revocation_event(
        {
            "event_id": "evt-revoke-user-1",
            "event_type": "permission.revoked",
            "external_tenant_id": "tenant-a",
            "external_user_id": "u-revoked",
            "client_id": "client-a",
            "external_app_id": "app-math",
            "reason": "permission_revoked",
        },
        request_id="req-revoke-replay",
    )

    assert applied["status"] == "applied"
    assert duplicate["status"] == "duplicate"
    with pytest.raises(PermissionError, match="revoked"):
        await service.ensure_token_allowed(exchanged["dt_token"])
    with pytest.raises(PermissionError, match="revoked"):
        await service.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-revoked", azp="client-a"),
            request_id="req-after-revoke",
        )

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, identity.tenant_id)) as c:
        events = await (
            await c.execute(
                """
                SELECT event_id,event_type,processing_status FROM eduplus2.revocation_events
                 WHERE event_id='evt-revoke-user-1'
                """
            )
        ).fetchall()
        state = await (
            await c.execute(
                """
                SELECT target_kind,external_user_id,client_id,active,reason
                  FROM eduplus2.revocation_state
                 WHERE event_id='evt-revoke-user-1'
                """
            )
        ).fetchone()
        audit = await (
            await c.execute(
                """
                SELECT event_kind,result,reason FROM eduplus2.audit_events
                 WHERE event_kind='revocation.apply' AND request_id='req-revoke'
                """
            )
        ).fetchone()
    assert len(events) == 1
    assert dict(state) == {
        "target_kind": "permission",
        "external_user_id": "u-revoked",
        "client_id": "client-a",
        "active": True,
        "reason": "permission_revoked",
    }
    assert dict(audit) == {
        "event_kind": "revocation.apply",
        "result": "success",
        "reason": "permission_revoked",
    }


async def test_token_check_revalidates_stale_permission_snapshot_without_webhook(
    enterprise_db, identity
):
    """防止无 webhook 时旧 permission snapshot 一直放行敏感操作。"""

    from deeptutor_enterprise.eduplus2.client import normalize_permission_response
    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import (
        StaticEduPlus2ProfileClient,
        StaticEduPlus2Resolver,
    )

    class MutablePermissionClient:
        revoked = False

        async def check_permission(
            self,
            *,
            external_tenant_id: str,
            external_user_id: str,
            external_subject: str,
            client_id: str,
            external_app_id: str,
            requested_usages: tuple[str, ...] = ("deeptutor.chat",),
        ) -> dict:
            return normalize_permission_response(
                external_tenant_id=external_tenant_id,
                external_user_id=external_user_id,
                external_subject=external_subject,
                client_id=client_id,
                external_app_id=external_app_id,
                payload={
                    "data": {
                        "allowed": not self.revoked,
                        "reason": "permission_revoked" if self.revoked else "ok",
                        "tenant": {"id": external_tenant_id},
                        "user": {"id": external_user_id, "subject": external_subject},
                        "client": {"client_id": client_id},
                        "app": {"id": external_app_id},
                        "permission": {
                            "allowed": not self.revoked,
                            "reason": "permission_revoked" if self.revoked else "ok",
                            "allowed_usages": list(requested_usages),
                            "scopes": ["chat"],
                            "version": "perm-revoked" if self.revoked else "perm-ok",
                        },
                        "requested_usages": list(requested_usages),
                    }
                },
            )

    permission_client = MutablePermissionClient()
    service = EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=StaticEduPlus2Resolver(
            {
                "client-a": {
                    "client_id": "client-a",
                    "external_tenant_id": "tenant-a",
                    "external_app_id": "app-math",
                    "status": "active",
                    "subscription_status": "active",
                    "policy": {"scopes": ["chat"]},
                    "version": "rv-poll",
                }
            }
        ),
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
        allowed_clients=(
            {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "internal_tenant_id": identity.tenant_id,
            },
        ),
        profile_client=StaticEduPlus2ProfileClient(
            {
                ("tenant-a", "u-poll"): {
                    "external_tenant_id": "tenant-a",
                    "external_user_id": "u-poll",
                    "external_subject": "sub-u-poll",
                    "status": "active",
                    "version": "profile-ok",
                }
            }
        ),
        permission_client=permission_client,
    )

    exchanged = await service.exchange_user_jwt(
        user_jwt(tid="tenant-a", eui="u-poll", azp="client-a"),
        request_id="req-poll-before",
    )
    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await c.execute(
            """
            UPDATE eduplus2.permission_snapshots
               SET fetched_at=now() - interval '2 hours',
                   updated_at=now() - interval '2 hours'
             WHERE external_user_id='u-poll'
            """
        )

    permission_client.revoked = True
    with pytest.raises(PermissionError, match="permission"):
        await service.ensure_token_allowed(exchanged["dt_token"])


async def test_revocation_webhook_requires_hmac_timestamp_and_rejects_replay(app, monkeypatch):
    """防止无签名/错误签名/重放 webhook 修改本地撤权状态。"""

    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

    enterprise = app.state.enterprise
    monkeypatch.setattr(
        enterprise,
        "eduplus2_resolver",
        StaticEduPlus2Resolver(
            {
                "client-a": {
                    "client_id": "client-a",
                    "external_tenant_id": "tenant-a",
                    "external_app_id": "app-math",
                    "status": "active",
                    "subscription_status": "active",
                    "policy": {"scopes": ["chat"]},
                    "version": "rv-webhook",
                }
            }
        ),
        raising=False,
    )
    monkeypatch.setattr(enterprise, "eduplus2_signing_key", EDUPLUS2_KEY, raising=False)
    monkeypatch.setattr(enterprise, "eduplus2_issuer", ISSUER, raising=False)
    monkeypatch.setattr(enterprise, "eduplus2_revocation_webhook_secret", "webhook-secret")

    payload = {
        "event_id": "evt-webhook-1",
        "event_type": "client.revoked",
        "external_tenant_id": "tenant-a",
        "client_id": "client-a",
        "reason": "client_revoked",
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        b"webhook-secret",
        timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        missing = await client.post(
            "/api/v1/auth/eduplus2/revocations",
            headers={"Origin": "https://school.example"},
            content=raw,
        )
        bad = await client.post(
            "/api/v1/auth/eduplus2/revocations",
            headers={
                "Origin": "https://school.example",
                "X-EduPlus2-Timestamp": timestamp,
                "X-EduPlus2-Signature": "bad",
            },
            content=raw,
        )
        ok = await client.post(
            "/api/v1/auth/eduplus2/revocations",
            headers={
                "Origin": "https://school.example",
                "X-EduPlus2-Timestamp": timestamp,
                "X-EduPlus2-Signature": "sha256=" + signature,
            },
            content=raw,
        )
        replay = await client.post(
            "/api/v1/auth/eduplus2/revocations",
            headers={
                "Origin": "https://school.example",
                "X-EduPlus2-Timestamp": timestamp,
                "X-EduPlus2-Signature": "sha256=" + signature,
            },
            content=raw,
        )

    assert missing.status_code == 401
    assert bad.status_code == 401
    assert ok.status_code == 200
    assert ok.json()["status"] == "applied"
    assert replay.status_code == 200
    assert replay.json()["status"] == "duplicate"


async def test_audit_query_and_export_api_requires_tenant_admin(app, monkeypatch):
    """防止普通 EduPlus2 用户导出企业审计，且导出内容必须脱敏。"""

    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

    enterprise = app.state.enterprise
    monkeypatch.setattr(
        enterprise,
        "eduplus2_resolver",
        StaticEduPlus2Resolver(
            {
                "client-a": {
                    "client_id": "client-a",
                    "external_tenant_id": "tenant-a",
                    "external_app_id": "app-math",
                    "status": "active",
                    "subscription_status": "active",
                    "policy": {"scopes": ["chat"]},
                    "version": "rv-audit",
                }
            }
        ),
        raising=False,
    )
    monkeypatch.setattr(enterprise, "eduplus2_signing_key", EDUPLUS2_KEY, raising=False)
    monkeypatch.setattr(enterprise, "eduplus2_issuer", ISSUER, raising=False)
    monkeypatch.setattr(
        enterprise,
        "eduplus2_allowed_clients",
        (
            {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "internal_tenant_id": enterprise.identity.tenant_id,
                "source": "env_allowlist",
                "status": "active",
            },
        ),
        raising=False,
    )

    admin = await enterprise.identity.login("admin", "long-password-1", client="audit-admin")
    user_token = (
        await enterprise.eduplus2.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-audit", azp="client-a"),
            request_id="req-audit-query",
        )
    )["dt_token"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        denied = await client.get(
            "/api/v1/enterprise/audit/eduplus2/events",
            headers={"Authorization": "Bearer " + user_token},
        )
        listed = await client.get(
            "/api/v1/enterprise/audit/eduplus2/events?event_kind=token.exchange&limit=10",
            headers={"Authorization": "Bearer " + admin},
        )
        exported = await client.post(
            "/api/v1/enterprise/audit/eduplus2/exports",
            headers={"Authorization": "Bearer " + admin},
            json={"format": "jsonl", "event_kind": "token.exchange"},
        )

    assert denied.status_code == 403
    assert listed.status_code == 200, listed.text
    events = listed.json()["items"]
    assert any(item["request_id"] == "req-audit-query" for item in events)
    rendered = json.dumps(listed.json(), ensure_ascii=False)
    assert user_token not in rendered
    assert EDUPLUS2_KEY not in rendered
    assert exported.status_code == 200, exported.text
    job = exported.json()
    assert job["status"] == "completed"
    assert job["format"] == "jsonl"
    assert job["file_ref"].startswith("db://eduplus2/audit-export/")
    assert job["row_count"] >= 1
    assert "req-audit-query" in job["preview"]
    assert user_token not in job["preview"]


async def test_permission_snapshot_rechecked_for_http_ws_and_sdk(app, monkeypatch):
    """防止已签发 token 在 permission snapshot 被撤销后继续访问敏感入口。"""

    from deeptutor_enterprise.api.application import SocketAuthentication
    from deeptutor_enterprise.eduplus2.testing import (
        StaticEduPlus2PermissionClient,
        StaticEduPlus2ProfileClient,
        StaticEduPlus2Resolver,
    )

    enterprise = app.state.enterprise
    monkeypatch.setattr(
        enterprise,
        "eduplus2_resolver",
        StaticEduPlus2Resolver(
            {
                "client-a": {
                    "client_id": "client-a",
                    "external_tenant_id": "tenant-a",
                    "external_app_id": "app-math",
                    "status": "active",
                    "subscription_status": "active",
                    "policy": {"scopes": ["chat"]},
                    "version": "rv-sensitive",
                }
            }
        ),
        raising=False,
    )
    monkeypatch.setattr(enterprise, "eduplus2_signing_key", EDUPLUS2_KEY, raising=False)
    monkeypatch.setattr(enterprise, "eduplus2_issuer", ISSUER, raising=False)
    monkeypatch.setattr(
        enterprise,
        "eduplus2_allowed_clients",
        (
            {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "internal_tenant_id": enterprise.identity.tenant_id,
                "source": "env_allowlist",
                "status": "active",
            },
        ),
        raising=False,
    )
    monkeypatch.setattr(
        enterprise,
        "eduplus2_profile_client",
        StaticEduPlus2ProfileClient(
            {
                ("tenant-a", "u-sensitive"): {
                    "external_tenant_id": "tenant-a",
                    "external_user_id": "u-sensitive",
                    "external_subject": "sub-u-sensitive",
                    "status": "active",
                    "version": "pv-sensitive",
                }
            }
        ),
        raising=False,
    )
    monkeypatch.setattr(
        enterprise,
        "eduplus2_permission_client",
        StaticEduPlus2PermissionClient(
            {
                ("tenant-a", "u-sensitive", "client-a", "app-math"): {
                    "allowed": True,
                    "reason": "ok",
                    "allowed_usages": ["deeptutor.chat"],
                    "scopes": ["chat"],
                    "version": "perm-sensitive",
                }
            }
        ),
        raising=False,
    )
    token = (
        await enterprise.eduplus2.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-sensitive", azp="client-a")
        )
    )["dt_token"]
    async with enterprise.db.transaction(TenantScope(enterprise.identity.tenant_id, "@test")) as c:
        await c.execute(
            """
            UPDATE eduplus2.permission_snapshots
               SET allowed=false, reason='permission_revoked', updated_at=now()
             WHERE external_user_id='u-sensitive'
            """
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://school.example"
    ) as client:
        http_denied = await client.get(
            "/api/sessions/not-found",
            headers={"Authorization": "Bearer " + token},
        )
    assert http_denied.status_code == 401

    ws = SimpleNamespace(
        state=SimpleNamespace(
            enterprise_token=token,
            enterprise_identity=await enterprise.identity.authenticate(token),
        )
    )
    with pytest.raises(PermissionError, match="permission"):
        await SocketAuthentication(enterprise).revalidate(ws)

    with pytest.raises(PermissionError, match="permission"):
        async with enterprise.sdk(token):
            pass

    from deeptutor_enterprise.context import identity_context

    with identity_context(await enterprise.identity.authenticate(token), token):
        with pytest.raises(PermissionError, match="permission"):
            await enterprise.authorize()


async def test_concurrent_first_exchange_upserts_registration_and_binding_once(
    enterprise_db, identity
):
    """防止并发首次换票创建重复 registration 或 identity binding。"""

    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import StaticEduPlus2Resolver

    class SlowResolver(StaticEduPlus2Resolver):
        async def resolve_client(self, client_id: str) -> dict:
            await asyncio.sleep(0.05)
            return await super().resolve_client(client_id)

    resolver = SlowResolver(
        {
            "client-concurrent": {
                "client_id": "client-concurrent",
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
    )
    service = EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=resolver,
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
        allowed_clients=(
            {
                "client_id": "client-concurrent",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "internal_tenant_id": identity.tenant_id,
                "source": "env_allowlist",
            },
        ),
    )

    first, second = await asyncio.gather(
        service.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-concurrent", azp="client-concurrent")
        ),
        service.exchange_user_jwt(
            user_jwt(tid="tenant-a", eui="u-concurrent", azp="client-concurrent")
        ),
    )

    assert first["client_registration_id"] == second["client_registration_id"]
    assert first["user_id"] == second["user_id"]
    async with enterprise_db.transaction(TenantScope(identity.tenant_id, identity.tenant_id)) as c:
        registration_count = await (
            await c.execute(
                """
                SELECT count(*) FROM eduplus2.external_client_registrations
                 WHERE client_id='client-concurrent'
                """
            )
        ).fetchone()
        binding_count = await (
            await c.execute(
                """
                SELECT count(*) FROM eduplus2.identity_bindings
                 WHERE external_tenant_id='tenant-a' AND external_user_id='u-concurrent'
                """
            )
        ).fetchone()
    assert registration_count["count"] == 1
    assert binding_count["count"] == 1


async def test_enterprise_wires_eduplus2_provider_from_env(monkeypatch):
    """防止 B1-lite 只能靠测试 monkeypatch 装配，无法读取 local/test secrets。"""

    from deeptutor_enterprise.bootstrap import Enterprise
    from deeptutor_enterprise.configuration import DeploymentConfig
    from deeptutor_enterprise.eduplus2.client import (
        EduPlus2OidcJwtVerifier,
        EduPlus2PermissionClient,
        EduPlus2ProfileClient,
        EduPlus2ResolveClient,
    )

    for name, value in {
        "DT_TEST_DB": "postgresql://deeptutor:pass@127.0.0.1:5432/deeptutor",
        "DT_TEST_SIGN": "s" * 48,
        "DT_TEST_EPOCH": "epoch-env",
        "DT_TEST_MODEL": "model-secret",
        "DT_EDUPLUS2_DISCOVERY_URL": ISSUER + "/.well-known/openid-configuration",
        "DT_EDUPLUS2_OIDC_ISSUER": ISSUER,
        "DT_EDUPLUS2_JWKS_URI": ISSUER + "/protocol/openid-connect/certs",
        "DT_EDUPLUS2_TOKEN_ENDPOINT": ISSUER + "/protocol/openid-connect/token",
        "DT_EDUPLUS2_RESOLVE_URL": "https://eduplus2.test/api/v1/open/oauth-clients/resolve",
        "DT_EDUPLUS2_PROFILE_URL": "https://eduplus2.test/api/v1/open/profile",
        "DT_EDUPLUS2_PERMISSION_URL": "https://eduplus2.test/api/v1/open/permissions/check",
        "DT_EDUPLUS2_CLIENT_ID": "m2m-client",
        "DT_EDUPLUS2_CLIENT_SECRET_REF": "env:DT_EDUPLUS2_CLIENT_SECRET",
        "DT_EDUPLUS2_CLIENT_SECRET": "m2m-secret",
        "DT_EDUPLUS2_REVOCATION_WEBHOOK_SECRET_REF": "env:DT_EDUPLUS2_WEBHOOK_SECRET",
        "DT_EDUPLUS2_WEBHOOK_SECRET": "webhook-secret",
        "DT_EDUPLUS2_ALLOWED_CLIENTS": (
            '[{"client_id":"client-a","external_tenant_id":"tenant-a",'
            '"external_app_id":"app-math"}]'
        ),
        "DT_EDUPLUS2_DT_TOKEN_TTL_SECONDS": "600",
        "DT_EDUPLUS2_REFRESH_DEADLINE_LEEWAY_SECONDS": "45",
        "DT_EDUPLUS2_REVOCATION_CACHE_TTL_SECONDS": "20",
        "DT_EDUPLUS2_AUDIT_EXPORT_STORAGE_REF": "s3://audit-bucket/eduplus2",
    }.items():
        monkeypatch.setenv(name, value)

    deployment = DeploymentConfig(
        version=1,
        tenant_id=uuid.uuid4(),
        resource="env-test",
        database_secret="env:DT_TEST_DB",
        signing_secret="env:DT_TEST_SIGN",
        auth_epoch_secret="env:DT_TEST_EPOCH",
        origins=("https://school.example",),
        models=(
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": "some-model",
                "base_url": "https://model.example/v1",
                "secret": "env:DT_TEST_MODEL",
                "allowed_roles": ("user", "tenant_admin"),
            },
        ),
    )
    enterprise = Enterprise(deployment)

    assert isinstance(enterprise.eduplus2_resolver, EduPlus2ResolveClient)
    assert isinstance(enterprise.eduplus2_verifier, EduPlus2OidcJwtVerifier)
    assert isinstance(enterprise.eduplus2_profile_client, EduPlus2ProfileClient)
    assert isinstance(enterprise.eduplus2_permission_client, EduPlus2PermissionClient)
    assert enterprise.eduplus2_allowed_clients == (
        {
            "client_id": "client-a",
            "external_tenant_id": "tenant-a",
            "external_app_id": "app-math",
            "internal_tenant_id": str(deployment.tenant_id),
            "source": "env_allowlist",
            "status": "active",
        },
    )
    assert enterprise.eduplus2_dt_token_seconds == 600
    assert enterprise.eduplus2_refresh_deadline_leeway_seconds == 45
    assert enterprise.eduplus2_revocation_cache_ttl_seconds == 20
    assert enterprise.eduplus2_audit_export_storage_ref == "s3://audit-bucket/eduplus2"
    assert enterprise.eduplus2_revocation_webhook_secret == "webhook-secret"
    assert enterprise.eduplus2_webhook_secret == "webhook-secret"


async def test_enterprise_env_can_disable_optional_eduplus2_profile_permission_clients(
    monkeypatch,
):
    """local/demo 环境可在保留 base URL 派生 resolve 的同时关闭可选复核客户端。"""

    from deeptutor_enterprise.bootstrap import Enterprise
    from deeptutor_enterprise.configuration import DeploymentConfig
    from deeptutor_enterprise.eduplus2.client import (
        EduPlus2OidcJwtVerifier,
        EduPlus2ResolveClient,
    )

    for name, value in {
        "DT_TEST_DB": "postgresql://deeptutor:pass@127.0.0.1:5432/deeptutor",
        "DT_TEST_SIGN": "s" * 48,
        "DT_TEST_EPOCH": "epoch-env",
        "DT_TEST_MODEL": "model-secret",
        "DT_EDUPLUS2_BASE_URL": "https://eduplus2.test",
        "DT_EDUPLUS2_DISCOVERY_URL": ISSUER + "/.well-known/openid-configuration",
        "DT_EDUPLUS2_TOKEN_ENDPOINT": ISSUER + "/protocol/openid-connect/token",
        "DT_EDUPLUS2_CLIENT_ID": "m2m-client",
        "DT_EDUPLUS2_CLIENT_SECRET_REF": "env:DT_EDUPLUS2_CLIENT_SECRET",
        "DT_EDUPLUS2_CLIENT_SECRET": "m2m-secret",
        "DT_EDUPLUS2_PROFILE_URL": "off",
        "DT_EDUPLUS2_PERMISSION_URL": "off",
    }.items():
        monkeypatch.setenv(name, value)

    deployment = DeploymentConfig(
        version=1,
        tenant_id=uuid.uuid4(),
        resource="env-disable-optional-test",
        database_secret="env:DT_TEST_DB",
        signing_secret="env:DT_TEST_SIGN",
        auth_epoch_secret="env:DT_TEST_EPOCH",
        origins=("https://school.example",),
        models=(
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": "some-model",
                "base_url": "https://model.example/v1",
                "secret": "env:DT_TEST_MODEL",
                "allowed_roles": ("user", "tenant_admin"),
            },
        ),
    )

    enterprise = Enterprise(deployment)

    assert isinstance(enterprise.eduplus2_resolver, EduPlus2ResolveClient)
    assert isinstance(enterprise.eduplus2_verifier, EduPlus2OidcJwtVerifier)
    assert enterprise.eduplus2_profile_client is None
    assert enterprise.eduplus2_permission_client is None
