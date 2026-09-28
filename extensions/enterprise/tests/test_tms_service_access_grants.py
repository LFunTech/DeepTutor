"""TMS 服务访问 grant 只是调用资格，不是配额授予或用量。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.scope import TenantScope
from deeptutor_enterprise.stores.postgres.connection import Database
import psycopg
import pytest
from test_management_authorization import _assignment, _identity, _principal, _tenant

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


async def _seed_school_with_service(connection, school_id):
    await _tenant(connection, school_id)
    await connection.execute(
        "INSERT INTO oms.school_bindings"
        "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
        "VALUES(%s,91001,'verified',now(),'synthetic-verifier','synthetic://school')",
        (school_id,),
    )
    await connection.execute(
        "INSERT INTO oms.service_definitions(service_id,unit_code,resource_category,enabled) "
        "VALUES('ocr','page','tool_integration',true)"
    )
    await connection.execute(
        "INSERT INTO oms.tenant_service_entitlements"
        "(tenant_id,service_id,status,starts_at,expires_at,created_by) "
        "VALUES(%s,'ocr','active',now()-interval '1 minute',now()+interval '7 days','oms')",
        (school_id,),
    )


async def _side_effect_counts(connection):
    rows = {}
    for name in ("quota_grants", "grant_commitments", "usage_attempts", "attempt_allocations"):
        value = await (await connection.execute(f"SELECT count(*) AS n FROM oms.{name}")).fetchone()
        rows[name] = value["n"]
    return rows


async def test_tms_service_access_grant_is_permissioned_versioned_and_quota_neutral(pg_dsn):
    """防止：给成员/应用开服务访问资格时误生成额度、预留或用量。"""

    from deeptutor_enterprise.oms.service_access import (
        ServiceAccessGrantRequest,
        ServiceAccessLedger,
        ServiceAccessRejected,
        ServiceAccessRevokeRequest,
    )

    await MigrationRunner(pg_dsn).apply()
    school_id = uuid.uuid4()
    admin_subject = "school-admin"
    auditor_subject = "school-auditor"
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await _seed_school_with_service(c, school_id)
        admin = await _principal(c, "tms", admin_subject, school_id)
        await _assignment(c, "tms", admin, "school_admin", "school", school_id)
        auditor = await _principal(c, "tms", auditor_subject, school_id)
        await _assignment(c, "tms", auditor, "school_auditor", "school", school_id)

    db = Database(single_database_user_dsn(pg_dsn), resource="tms-service-access-test")
    grant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with db:
        async with db.transaction(TenantScope(str(school_id), "@counts-before")) as c:
            before = await _side_effect_counts(c)
        ledger = ServiceAccessLedger(db)
        denied = ServiceAccessGrantRequest(
            grant_id=uuid.uuid4(),
            service_id="ocr",
            subject_kind="member",
            subject_id="learner-1",
            starts_at=now,
            expires_at=now + timedelta(days=1),
            expected_entitlement_version=1,
            reason="无权成员不能发服务访问资格",
        )
        with pytest.raises(ServiceAccessRejected, match="Permission denied"):
            await ledger.grant(
                TenantScope(str(school_id), auditor_subject),
                _identity("tms", auditor_subject, school_id),
                denied,
            )

        member = await ledger.grant(
            TenantScope(str(school_id), admin_subject),
            _identity("tms", admin_subject, school_id),
            ServiceAccessGrantRequest(
                grant_id=grant_id,
                service_id="ocr",
                subject_kind="member",
                subject_id="learner-1",
                starts_at=now,
                expires_at=now + timedelta(days=1),
                expected_entitlement_version=1,
                reason="允许成员使用 OCR",
            ),
        )
        assert member.grant_id == grant_id
        assert member.status == "active"
        assert member.version == 1
        assert member.sync_status == "local_ready"

        app = await ledger.grant(
            TenantScope(str(school_id), admin_subject),
            _identity("tms", admin_subject, school_id),
            ServiceAccessGrantRequest(
                grant_id=uuid.uuid4(),
                service_id="ocr",
                subject_kind="application",
                subject_id="agent-app-1",
                starts_at=now,
                expires_at=now + timedelta(days=1),
                expected_entitlement_version=1,
                reason="允许应用使用 OCR",
            ),
        )
        assert app.subject_kind == "application"

        with pytest.raises(ServiceAccessRejected, match="active service access grant exists"):
            await ledger.grant(
                TenantScope(str(school_id), admin_subject),
                _identity("tms", admin_subject, school_id),
                ServiceAccessGrantRequest(
                    grant_id=uuid.uuid4(),
                    service_id="ocr",
                    subject_kind="member",
                    subject_id="learner-1",
                    starts_at=now,
                    expires_at=now + timedelta(days=1),
                    expected_entitlement_version=1,
                    reason="重复资格不能覆盖",
                ),
            )

        revoked = await ledger.revoke(
            TenantScope(str(school_id), admin_subject),
            _identity("tms", admin_subject, school_id),
            ServiceAccessRevokeRequest(
                grant_id=grant_id,
                expected_version=1,
                reason="撤销成员 OCR 访问资格",
            ),
        )
        assert revoked.status == "revoked"
        assert revoked.version == 2

        async with db.transaction(TenantScope(str(school_id), "@counts-after")) as c:
            after = await _side_effect_counts(c)
            access_rows = await (
                await c.execute(
                    "SELECT subject_kind,subject_id,status,version,sync_status "
                    "FROM oms.tenant_service_access_grants ORDER BY subject_kind,subject_id"
                )
            ).fetchall()
    assert after == before
    assert access_rows == [
        {
            "subject_kind": "application",
            "subject_id": "agent-app-1",
            "status": "active",
            "version": 1,
            "sync_status": "local_ready",
        },
        {
            "subject_kind": "member",
            "subject_id": "learner-1",
            "status": "revoked",
            "version": 2,
            "sync_status": "local_ready",
        },
    ]
