"""Management 枚举/条件 CHECK 退役后的程序值域防线。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
import psycopg
import pytest

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio

ISSUER = "https://issuer.example"
SCHOOL = uuid.UUID("10000000-0000-0000-0000-000000000001")


async def _drop(c, table: str, constraint: str) -> None:
    await c.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")


def _identity(*, subject="operator", version=2):
    from deeptutor_enterprise.management.authorization import ManagementIdentity

    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="oms",
        issuer=ISSUER,
        subject=subject,
        school_id=None,
        policy_version=version,
        school_binding_version=None,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )


async def _seed_oms_permission(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    principal = uuid.uuid4()
    assignment = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms',%s,'operator','active')",
            (principal, ISSUER),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_security_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic')",
            (assignment, principal, uuid.uuid4()),
        )
        await c.execute(
            "INSERT INTO management.delegation_policies"
            "(id,application,principal_id,action_key,scope_kind,school_id,"
            "valid_from,expires_at,status) "
            "VALUES(%s,'oms',%s,'ops.oms.access','platform',NULL,"
            "now()-interval '1 minute',now()+interval '1 hour','active')",
            (uuid.uuid4(), principal),
        )
        await c.execute(
            "UPDATE management.principals SET policy_version=policy_version+2 "
            "WHERE id=%s",
            (principal,),
        )
    return principal, assignment


async def test_permission_rejects_unknown_principal_status_without_db_check(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    principal, _ = await _seed_oms_permission(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await _drop(c, "management.principals", "principals_status_check")
        await c.execute(
            "UPDATE management.principals SET status='future-status' WHERE id=%s",
            (principal,),
        )
    async with await psycopg.AsyncConnection.connect(single_database_user_dsn(pg_dsn)) as c:
        with pytest.raises(ManagementAuthorizationDenied, match="principal fact"):
            await require_management_permission(c, _identity(version=3), "ops.oms.access", write=True)


async def test_permission_rejects_unknown_action_and_role_values_without_db_checks(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await _seed_oms_permission(pg_dsn)
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        decision = await require_management_permission(c, _identity(version=3), "ops.oms.access", write=True)
        assert decision.action == "ops.oms.access"
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await _drop(c, "management.action_catalog", "action_catalog_allowed_scope_check")
        await c.execute(
            "UPDATE management.action_catalog SET allowed_scope='future-scope' "
            "WHERE application='oms' AND action_key='ops.oms.access'"
        )
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        with pytest.raises(ManagementAuthorizationDenied, match="action catalog fact"):
            await require_management_permission(c, _identity(version=3), "ops.oms.access", write=True)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "UPDATE management.action_catalog SET allowed_scope='platform' "
            "WHERE application='oms' AND action_key='ops.oms.access'"
        )
        await _drop(c, "management.role_versions", "role_versions_scope_kind_check")
        await c.execute("ALTER TABLE management.role_versions DISABLE TRIGGER USER")
        await c.execute(
            "UPDATE management.role_versions SET scope_kind='future-scope' "
            "WHERE application='oms' AND role_key='platform_security_admin' AND version=1"
        )
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        with pytest.raises(ManagementAuthorizationDenied, match="role version fact"):
            await require_management_permission(c, _identity(version=3), "ops.oms.access", write=True)


async def test_approval_request_value_validator_rejects_enum_and_reviewer_shape():
    now = datetime.now(timezone.utc)
    valid = {
        "id": uuid.uuid4(),
        "application": "tms",
        "operation": "school_activation",
        "school_id": SCHOOL,
        "proposer_issuer": ISSUER,
        "proposer_subject": "proposer",
        "reviewer_issuer": ISSUER,
        "reviewer_subject": "reviewer",
        "expected_policy_version": 1,
        "status": "approved",
        "expires_at": now + timedelta(hours=1),
        "decided_at": now,
    }
    MigrationRunner._validate_management_approval_snapshot({valid["id"]: valid})
    for change in (
        {"status": "future-status"},
        {"operation": "platform_grant"},
        {"reviewer_subject": "proposer"},
        {"reviewer_issuer": None},
        {"decided_at": None},
    ):
        bad = dict(valid, **change)
        with pytest.raises(RuntimeError, match="approval"):
            MigrationRunner._validate_management_approval_snapshot({bad["id"]: bad})


async def test_custom_role_replay_rejects_unknown_audit_result_without_db_check(pg_dsn):
    from deeptutor_enterprise.management.roles import (
        CustomRoleConflict,
        PublishCustomRoleCommand,
        publish_custom_role,
    )

    await _seed_oms_permission(pg_dsn)
    command_id = uuid.uuid4()
    command = PublishCustomRoleCommand(
        role_key="custom_support",
        scope_kind="platform",
        target_school_id=None,
        action_keys=("ops.oms.access",),
        expected_version=0,
        command_id=command_id,
        reason="synthetic",
        request_id="role-1",
    )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        async with c.transaction():
            result = await publish_custom_role(c, _identity(version=3), command)
            assert result.version == 1
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await _drop(c, "management.audit_events", "audit_events_result_check")
        await c.execute("ALTER TABLE management.audit_events DISABLE TRIGGER USER")
        await c.execute(
            "UPDATE management.audit_events SET result='future-result' WHERE id=%s",
            (command_id,),
        )
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        async with c.transaction():
            with pytest.raises(CustomRoleConflict, match="audit fact"):
                await publish_custom_role(c, _identity(version=3), command)
