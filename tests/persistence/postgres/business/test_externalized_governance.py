from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_governance_settings_secret_audit_and_usage_are_scoped_and_redacted(
    pg_session_store_factory, business_actors
):
    """若 TMS/OMS 配置、Secret、审计或用量治理泄漏明文/串租户，本测试应失败。"""

    from deeptutor.persistence.postgres.governance import RuntimeGovernanceStore

    actor = business_actors.tenants[0].admin
    foreign = business_actors.tenants[1].admin
    store = RuntimeGovernanceStore(pg_session_store_factory(actor))
    foreign_store = RuntimeGovernanceStore(pg_session_store_factory(foreign))

    setting = await store.save_setting(
        key="model.default",
        desired={"model": "gpt-4.1", "api_key": "sk-must-not-persist"},
        actor_id=actor.user_id,
    )
    assert setting["status"] == "saved"
    assert setting["desired"] == {"model": "gpt-4.1", "api_key": "<secret-ref-required>"}
    active = await store.mark_active("model.default", actor_id=actor.user_id)
    assert active["status"] == "active"

    secret = await store.upsert_secret_reference(
        name="objectstore.primary",
        provider="env",
        reference="DEEPTUTOR_OBJECTSTORE_SECRET_KEY",
        actor_id=actor.user_id,
        status="active",
    )
    assert secret["redacted_summary"] == "env:DEEPTUTOR_OBJECTSTORE_SECRET_KEY:active"
    assert "SECRET_VALUE" not in str(secret)

    audit = await store.list_audit(limit=10)
    assert {row["event_kind"] for row in audit} >= {"settings.saved", "settings.active", "secret_ref.saved"}
    assert "sk-must-not-persist" not in str(audit)

    usage = await store.usage_summary()
    assert usage["tenant_id"] == actor.tenant_id
    assert "private_body" not in str(usage)
    assert await foreign_store.list_audit(limit=10) == []


async def test_tms_oms_governance_api_contracts_are_scoped_and_redacted(
    pg_session_store_factory, business_actors
):
    """若 /api/v1/tms 或 /api/v1/oms 缺失、越权写入或泄漏 Secret，本测试应失败。"""

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from deeptutor.api.routers import auth
    from deeptutor.api.routers.governance import oms_router, tms_router
    from deeptutor.core.providers import ApplicationProviders
    from deeptutor.services.auth import TokenPayload

    actor = business_actors.tenants[0].admin
    app = FastAPI()
    app.state.application_container = type(
        "Container",
        (),
        {"providers": ApplicationProviders(store=pg_session_store_factory(actor))},
    )()
    app.include_router(tms_router, prefix="/api/v1/tms")
    app.include_router(oms_router, prefix="/api/v1/oms")

    async def admin_payload():
        return TokenPayload(
            username=actor.username,
            role="tenant_admin",
            user_id=actor.user_id,
            tenant_id=actor.tenant_id,
        )

    async def ordinary_payload():
        return TokenPayload(
            username="learner",
            role="user",
            user_id="not-admin",
            tenant_id=actor.tenant_id,
        )

    app.dependency_overrides[auth.require_auth] = admin_payload
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        saved = await client.put(
            "/api/v1/tms/settings/model.default",
            json={"desired": {"model": "gpt-4.1", "api_key": "sk-do-not-return"}},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["desired"]["api_key"] == "<secret-ref-required>"
        assert "sk-do-not-return" not in saved.text

        active = await client.post("/api/v1/tms/settings/model.default/activate")
        assert active.status_code == 200, active.text
        assert active.json()["status"] == "active"

        secret = await client.put(
            "/api/v1/oms/secrets/objectstore.primary",
            json={
                "provider": "env",
                "reference": "DEEPTUTOR_OBJECTSTORE_SECRET_KEY",
                "status": "active",
            },
        )
        assert secret.status_code == 200, secret.text
        assert secret.json()["redacted_summary"] == "env:DEEPTUTOR_OBJECTSTORE_SECRET_KEY:active"

        audit = await client.get("/api/v1/oms/audit")
        assert audit.status_code == 200, audit.text
        assert {"settings.saved", "settings.active", "secret_ref.saved"} <= {
            row["event_kind"] for row in audit.json()["events"]
        }
        assert "sk-do-not-return" not in audit.text

        usage = await client.get("/api/v1/oms/usage")
        assert usage.status_code == 200, usage.text
        assert usage.json()["tenant_id"] == actor.tenant_id

    app.dependency_overrides[auth.require_auth] = ordinary_payload
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        forbidden = await client.put(
            "/api/v1/tms/settings/model.default",
            json={"desired": {"model": "gpt-4.1-mini"}},
        )
        assert forbidden.status_code == 403
