from __future__ import annotations

import psycopg
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


async def test_governance_rejects_unknown_status_and_wrong_scope_before_sql(
    pg_session_store_factory, business_actors
):
    from deeptutor.persistence.postgres.governance import RuntimeGovernanceStore

    actor = business_actors.tenants[0].admin
    store = RuntimeGovernanceStore(pg_session_store_factory(actor))
    with pytest.raises(ValueError, match="status"):
        await store.upsert_secret_reference(
            name="invalid.secret", provider="env", reference="INVALID_SECRET",
            actor_id=actor.user_id, status="unknown",
        )
    with pytest.raises(ValueError, match="scope"):
        await store.save_setting(
            key="invalid.scope", desired={}, actor_id=actor.user_id,
            scope_kind="resource", scope_id="resource-1",
        )
    with pytest.raises(ValueError, match="scope"):
        await store.record_event("unknown.scope", actor_id=actor.user_id, scope_kind="unknown")
    assert await store.list_audit() == []


async def test_governance_never_overwrites_unknown_persisted_status_without_db_checks(
    pg_session_store_factory, business_actors, migrated_pg
):
    from deeptutor.persistence.postgres.governance import RuntimeGovernanceStore

    actor = business_actors.tenants[0].admin
    store = RuntimeGovernanceStore(pg_session_store_factory(actor))
    await store.save_setting(key="unknown.setting", desired={}, actor_id=actor.user_id)
    await store.upsert_secret_reference(
        name="unknown.secret", provider="env", reference="TEST_SECRET", actor_id=actor.user_id
    )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as c:
        await c.execute(
            "ALTER TABLE enterprise.runtime_settings DROP CONSTRAINT IF EXISTS runtime_settings_status_check"
        )
        await c.execute(
            "ALTER TABLE enterprise.secret_references "
            "DROP CONSTRAINT IF EXISTS secret_references_status_check"
        )
        await c.execute(
            "UPDATE enterprise.runtime_settings SET status='unknown' WHERE key='unknown.setting'"
        )
        await c.execute(
            "UPDATE enterprise.secret_references SET status='unknown' "
            "WHERE name='unknown.secret'"
        )
    with pytest.raises(ValueError, match="status"):
        await store.mark_active("unknown.setting", actor_id=actor.user_id)
    with pytest.raises(ValueError, match="status"):
        await store.save_setting(key="unknown.setting", desired={}, actor_id=actor.user_id)
    with pytest.raises(ValueError, match="status"):
        await store.upsert_secret_reference(
            name="unknown.secret", provider="env", reference="TEST_SECRET", actor_id=actor.user_id
        )


@pytest.mark.parametrize(
    ("constraint", "column", "value", "message"),
    [
        (
            "runtime_policies_status_check",
            "status",
            "future-status",
            "unknown persisted status",
        ),
        (
            "runtime_policies_subject_kind_check",
            "subject_kind",
            "future-kind",
            "unknown persisted subject kind",
        ),
    ],
)
async def test_runtime_policy_grants_reject_unknown_values_without_db_checks(
    monkeypatch,
    business_sync_database,
    business_actors,
    migrated_pg,
    constraint,
    column,
    value,
    message,
):
    """用户 grant 读写必须扫描目标 subject 的异常旧行，而不是靠 PG CHECK。"""

    from deeptutor.multi_user import grants

    actor = business_actors.tenants[0].admin
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as c:
        await c.execute(f"ALTER TABLE enterprise.runtime_policies DROP CONSTRAINT IF EXISTS {constraint}")
        await c.execute(
            "INSERT INTO enterprise.runtime_policies"
            "(tenant_id,policy_kind,subject_kind,subject_id,document,status,updated_by) "
            "VALUES(%s,'user_grant','owner',%s,'{}'::jsonb,'active',%s)",
            (actor.tenant_id, actor.user_id, actor.user_id),
        )
        await c.execute(
            f"UPDATE enterprise.runtime_policies SET {column}=%s "
            "WHERE tenant_id=%s AND policy_kind='user_grant' AND subject_id=%s",
            (value, actor.tenant_id, actor.user_id),
        )
    monkeypatch.setattr(grants, "_pg_runtime", lambda: (business_sync_database, actor.scope))

    with pytest.raises(ValueError, match=message):
        grants._load_pg_grant(actor.user_id)
    with pytest.raises(ValueError, match=message):
        grants._save_pg_grant(actor.user_id, grants.empty_grant(actor.user_id))


async def test_governance_audit_list_rejects_unknown_scope_without_db_check(
    pg_session_store_factory, business_actors, migrated_pg
):
    from deeptutor.persistence.postgres.governance import RuntimeGovernanceStore

    actor = business_actors.tenants[0].admin
    store = RuntimeGovernanceStore(pg_session_store_factory(actor))
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as c:
        await c.execute(
            "ALTER TABLE enterprise.runtime_audit_events "
            "DROP CONSTRAINT IF EXISTS runtime_audit_events_scope_kind_check"
        )
        await c.execute(
            "INSERT INTO enterprise.runtime_audit_events"
            "(tenant_id,id,event_kind,actor_id,scope_kind,scope_id,summary) "
            "VALUES(%s,gen_random_uuid(),'scope.future',%s,'future-scope','','{}'::jsonb)",
            (actor.tenant_id, actor.user_id),
        )

    with pytest.raises(ValueError, match="scope"):
        await store.list_audit()


async def test_governance_write_scope_validation_does_not_depend_on_db_checks(
    pg_session_store_factory, business_actors, migrated_pg
):
    from deeptutor.persistence.postgres.governance import RuntimeGovernanceStore

    actor = business_actors.tenants[0].admin
    store = RuntimeGovernanceStore(pg_session_store_factory(actor))
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as c:
        for table, constraint in (
            ("runtime_settings", "runtime_settings_scope_kind_check"),
            ("secret_references", "secret_references_scope_kind_check"),
            ("runtime_audit_events", "runtime_audit_events_scope_kind_check"),
        ):
            await c.execute(f"ALTER TABLE enterprise.{table} DROP CONSTRAINT IF EXISTS {constraint}")

    with pytest.raises(ValueError, match="scope"):
        await store.save_setting(
            key="future.scope",
            desired={},
            actor_id=actor.user_id,
            scope_kind="future-scope",
            scope_id="future",
        )
    with pytest.raises(ValueError, match="scope"):
        await store.upsert_secret_reference(
            name="future.scope",
            provider="env",
            reference="FUTURE_SECRET",
            actor_id=actor.user_id,
            scope_kind="future-scope",
            scope_id="future",
        )
    with pytest.raises(ValueError, match="scope"):
        await store.record_event(
            "future.scope",
            actor_id=actor.user_id,
            scope_kind="future-scope",
            scope_id="future",
        )
    async with await psycopg.AsyncConnection.connect(migrated_pg.admin_dsn) as c:
        for table in ("runtime_settings", "secret_references", "runtime_audit_events"):
            assert not await (
                await c.execute(
                    f"SELECT 1 FROM enterprise.{table} "
                    "WHERE tenant_id=%s AND scope_kind='future-scope'",
                    (actor.tenant_id,),
                )
            ).fetchone()


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
