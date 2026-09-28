"""管理授权只消费可信身份和本仓库 PG 事实，不消费外部权限端点。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
import psycopg
import pytest

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


def _api():
    from deeptutor_enterprise.management import authorization

    return authorization


def _identity(app: str, subject: str, school_id=None, version=2, active=True):
    return _api().ManagementIdentity(
        application=app,
        issuer="https://issuer.example",
        subject=subject,
        school_id=school_id,
        policy_version=version,
        school_binding_version=1 if school_id is not None else None,
        external_active=active,
        external_checked_at=datetime.now(timezone.utc),
        external_verified_until=datetime.now(timezone.utc) + timedelta(minutes=1),
    )


async def _tenant(connection, school_id, *, ready=True):
    await connection.execute(
        "INSERT INTO enterprise.tenants"
        "(id,external_eligibility,auth_epoch,bootstrap_completed,local_enabled,"
        "provisioning_status) VALUES(%s,'allowed','synthetic',%s,%s,%s)",
        (school_id, ready, ready, "ready" if ready else "pending"),
    )


async def _principal(connection, app, subject, school_id=None, active=True):
    principal_id = uuid.uuid4()
    await connection.execute(
        "INSERT INTO management.principals"
        "(id,application,issuer,subject,school_id,status) VALUES(%s,%s,%s,%s,%s,%s)",
        (
            principal_id,
            app,
            "https://issuer.example",
            subject,
            school_id,
            "active" if active else "pending",
        ),
    )
    return principal_id


async def _bump_policy_version(connection, principal_id, *, times=1):
    await connection.execute(
        "UPDATE management.principals SET policy_version=policy_version+%s "
        "WHERE id=%s",
        (times, principal_id),
    )


async def _assignment(
    connection, app, principal_id, role, scope, school_id=None, *, binding_fenced=True
):
    assignment_id = uuid.uuid4()
    await connection.execute(
        "INSERT INTO management.assignments"
        "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
        "school_binding_version,"
        "valid_from,expires_at,command_id,created_by) "
        "VALUES(%s,%s,%s,%s,1,%s,%s,%s,now()-interval '1 day',"
        "now()+interval '1 day',%s,'synthetic-approval')",
        (
            assignment_id,
            app,
            principal_id,
            role,
            scope,
            school_id,
            1 if school_id is not None and binding_fenced else None,
            uuid.uuid4(),
        ),
    )
    await _bump_policy_version(connection, principal_id)
    return assignment_id


async def test_default_deny_and_oms_platform_scope(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        principal = await _principal(connection, "oms", "operator")
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection, _identity("oms", "operator", version=1), "ops.oms.access"
            )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _assignment(connection, "oms", principal, "platform_security_admin", "platform")
        await _principal(connection, "oms", "unassigned")
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        # 相同 PG runtime 用户和可见动作目录不构成任何操作者授权。
        await connection.execute("SELECT set_config('app.management_app','oms',true)")
        visible = await (
            await connection.execute(
                "SELECT count(*) FROM management.action_catalog WHERE action_key='ops.oms.access'"
            )
        ).fetchone()
        assert visible[0] == 1
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection, _identity("oms", "unassigned", version=1), "ops.oms.access"
            )
        decision = await require_management_permission(
            connection, _identity("oms", "operator"), "ops.oms.access"
        )
        assert decision.application == "oms"
        assert decision.policy_version == 2
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection, _identity("oms", "operator"), "ops.credentials.manage"
            )


async def test_principal_disable_keeps_last_admin_without_database_trigger(pg_dsn):
    from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied
    from deeptutor_enterprise.management.principals import (
        DisablePrincipalCommand,
        disable_management_principal,
    )

    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        original = await _principal(connection, "oms", "original-admin")
        await _assignment(connection, "oms", original, "platform_security_admin", "platform")
    runtime_dsn = single_database_user_dsn(pg_dsn)
    command = DisablePrincipalCommand(
        target_principal_id=original,
        target_school_id=None,
        expected_policy_version=2,
        reason="合成停用验收",
        request_id="synthetic-disable-1",
    )
    try:
        async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
            with pytest.raises(ManagementAuthorizationDenied, match="last active"):
                await disable_management_principal(
                    connection, _identity("oms", "original-admin"), command
                )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
            second = await _principal(connection, "oms", "second-admin")
            await _assignment(connection, "oms", second, "platform_security_admin", "platform")
        async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
            result = await disable_management_principal(
                connection, _identity("oms", "original-admin"), command
            )
            assert result.target_policy_version == 3
        async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
            row = await (
                await connection.execute(
                    "SELECT status,policy_version FROM management.principals WHERE id=%s",
                    (original,),
                )
            ).fetchone()
            assert row == ("disabled", 3)
    finally:
        async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
            pass


async def test_school_principal_disable_is_school_scoped_and_versioned(pg_dsn):
    from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied
    from deeptutor_enterprise.management.principals import (
        DisablePrincipalCommand,
        disable_management_principal,
    )

    await MigrationRunner(pg_dsn).apply()
    school, other_school = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await _tenant(connection, other_school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic','synthetic://a'),"
            "(%s,102,'verified',now(),'synthetic','synthetic://b')",
            (school, other_school),
        )
        first = await _principal(connection, "tms", "first", school)
        await _assignment(connection, "tms", first, "school_admin", "school", school)
        second = await _principal(connection, "tms", "second", school)
        await _assignment(connection, "tms", second, "school_admin", "school", school)
    command = DisablePrincipalCommand(
        target_principal_id=first, target_school_id=school, expected_policy_version=2,
        reason="合成学校管理员停用", request_id="synthetic-disable-school",
    )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    try:
        async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
            await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
            with pytest.raises(ManagementAuthorizationDenied):
                await disable_management_principal(
                    connection,
                    _identity("tms", "first", school),
                    DisablePrincipalCommand(
                        target_principal_id=first, target_school_id=other_school,
                        expected_policy_version=2, reason="跨校", request_id="synthetic-cross-school",
                    ),
                )
            result = await disable_management_principal(
                connection, _identity("tms", "first", school), command
            )
            assert result.target_policy_version == 3
        async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
            await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
            with pytest.raises(ManagementAuthorizationDenied):
                await disable_management_principal(
                    connection, _identity("tms", "second", school),
                    DisablePrincipalCommand(
                        target_principal_id=second, target_school_id=school,
                        expected_policy_version=2, reason="最后管理员",
                        request_id="synthetic-last-school",
                    ),
                )
        async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
            rows = await (
                await connection.execute(
                    "SELECT subject,status,policy_version FROM management.principals "
                    "WHERE id IN (%s,%s) ORDER BY subject", (first, second)
                )
            ).fetchall()
            assert rows == [("first", "disabled", 3), ("second", "active", 2)]
    finally:
        async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
            pass


async def test_concurrent_principal_disables_leave_one_admin_without_trigger(pg_dsn):
    from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied
    from deeptutor_enterprise.management.principals import (
        DisablePrincipalCommand,
        disable_management_principal,
    )

    await MigrationRunner(pg_dsn).apply()
    principals = []
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        for subject in ("first", "second"):
            principal = await _principal(connection, "oms", subject)
            await _assignment(connection, "oms", principal, "platform_security_admin", "platform")
            principals.append((subject, principal))

    runtime_dsn = single_database_user_dsn(pg_dsn)

    async def disable(subject, principal):
        async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
            try:
                await disable_management_principal(
                    connection,
                    _identity("oms", subject),
                    DisablePrincipalCommand(
                        target_principal_id=principal, target_school_id=None,
                        expected_policy_version=2, reason="并发停用",
                        request_id=f"synthetic-concurrent-{subject}",
                    ),
                )
                return True
            except ManagementAuthorizationDenied:
                return False

    try:
        assert sorted(await asyncio.gather(*(disable(*p) for p in principals))) == [False, True]
        async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
            rows = await (
                await connection.execute(
                    "SELECT status FROM management.principals WHERE id IN (%s,%s)",
                    (principals[0][1], principals[1][1]),
                )
            ).fetchall()
            assert sorted(row[0] for row in rows) == ["active", "disabled"]
    finally:
        async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
            pass


async def test_tms_current_school_only_and_old_policy_version_denied(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    school_a, school_b = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school_a)
        await _tenant(connection, school_b)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school-a')",
            (school_a,),
        )
        principal = await _principal(connection, "tms", "teacher", school_a)
        await _assignment(connection, "tms", principal, "school_operator", "school", school_a)
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_a),))
        decision = await require_management_permission(
            connection,
            _identity("tms", "teacher", school_a),
            "tenant.members.read",
            target_school_id=school_a,
        )
        assert decision.school_id == school_a
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection,
                _identity("tms", "teacher", school_a),
                "tenant.members.read",
                target_school_id=school_b,
            )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "UPDATE management.principals SET policy_version=3 WHERE id=%s", (principal,)
        )
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_a),))
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection,
                _identity("tms", "teacher", school_a),
                "tenant.members.read",
                target_school_id=school_a,
            )


@pytest.mark.parametrize(
    "blocked_state",
    (
        "bootstrap_completed=false",
        "local_enabled=false",
        "provisioning_status='pending'",
        "recovery_state='quarantined'",
    ),
)
async def test_tms_unavailable_school_denies_management_access(pg_dsn, blocked_state):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            f"UPDATE enterprise.tenants SET {blocked_state} WHERE id=%s", (school,)
        )
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        principal = await _principal(connection, "tms", "teacher", school)
        await _assignment(connection, "tms", principal, "school_operator", "school", school)

    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        with pytest.raises(ManagementAuthorizationDenied, match="school"):
            await require_management_permission(
                connection,
                _identity("tms", "teacher", school),
                "tenant.members.read",
                target_school_id=school,
            )


@pytest.mark.parametrize(
    ("field", "constraint"),
    [
        ("external_eligibility", "tenants_external_eligibility_check"),
        ("provisioning_status", "tenants_provisioning_status_check"),
        ("recovery_state", "tenants_recovery_state_check"),
    ],
)
async def test_lifecycle_governance_rejects_unknown_school_value_without_db_check(
    pg_dsn, field, constraint
):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        principal = await _principal(connection, "oms", "reconcile-operator")
        await _assignment(connection, "oms", principal, "platform_operator", "school", school)
        await connection.execute(f"ALTER TABLE enterprise.tenants DROP CONSTRAINT IF EXISTS {constraint}")
        await connection.execute(
            f"UPDATE enterprise.tenants SET {field}='future-value' WHERE id=%s",
            (school,),
        )

    async with await psycopg.AsyncConnection.connect(single_database_user_dsn(pg_dsn)) as c:
        with pytest.raises(ManagementAuthorizationDenied, match="school business state"):
            await require_management_permission(
                c,
                _identity("oms", "reconcile-operator"),
                "ops.reconciliation.manage",
                target_school_id=school,
                write=True,
            )


async def test_oms_school_write_denied_when_locally_disabled(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        principal = await _principal(connection, "oms", "scoped-operator")
        await _assignment(connection, "oms", principal, "platform_operator", "school", school)
        await connection.execute(
            "UPDATE enterprise.tenants SET local_enabled=false WHERE id=%s", (school,)
        )

    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        with pytest.raises(ManagementAuthorizationDenied, match="school"):
            await require_management_permission(
                connection,
                _identity("oms", "scoped-operator"),
                "ops.entitlements.manage",
                target_school_id=school,
                write=True,
            )


async def test_oms_school_grant_does_not_survive_external_school_rebinding(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school-a')",
            (school,),
        )
        principal = await _principal(connection, "oms", "scoped-operator")
        await _assignment(connection, "oms", principal, "platform_operator", "school", school)
        legacy = await _principal(connection, "oms", "legacy-operator")
        await _assignment(
            connection,
            "oms",
            legacy,
            "platform_operator",
            "school",
            school,
            binding_fenced=False,
        )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        with pytest.raises(ManagementAuthorizationDenied, match="assignment fact is invalid"):
            await require_management_permission(
                connection,
                _identity("oms", "legacy-operator"),
                "ops.entitlements.manage",
                target_school_id=school,
                write=True,
            )
        decision = await require_management_permission(
            connection,
            _identity("oms", "scoped-operator"),
            "ops.entitlements.manage",
            target_school_id=school,
            write=True,
        )
        assert decision.school_binding_version == 1
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "UPDATE oms.school_bindings SET eduplus_tenant_id=202,version=2,"
            "verified_at=now(),source_ref='synthetic://school-b' WHERE tenant_id=%s",
            (school,),
        )
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        with pytest.raises(ManagementAuthorizationDenied, match="not granted"):
            await require_management_permission(
                connection,
                _identity("oms", "scoped-operator"),
                "ops.entitlements.manage",
                target_school_id=school,
                write=True,
            )


async def test_oms_governance_does_not_imply_delegation_or_business_execution(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_delegation,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        actor = await _principal(connection, "oms", "security-admin")
        await _assignment(connection, "oms", actor, "platform_security_admin", "platform")
    runtime_dsn = single_database_user_dsn(pg_dsn)
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        with pytest.raises(ManagementAuthorizationDenied, match="delegation"):
            await require_management_delegation(
                connection,
                _identity("oms", "security-admin"),
                "ops.entitlements.manage",
                target_school_id=school,
                grant_expires_at=expiry,
            )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO management.delegation_policies"
            "(id,application,principal_id,action_key,scope_kind,school_id,"
            "valid_from,expires_at) "
            "VALUES(%s,'oms',%s,'ops.entitlements.manage','school',%s,"
            "now()-interval '1 minute',now()+interval '2 hours')",
            (uuid.uuid4(), actor, school),
        )
        await _bump_policy_version(connection, actor)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        decision = await require_management_delegation(
            connection,
            _identity("oms", "security-admin", version=3),
            "ops.entitlements.manage",
            target_school_id=school,
            grant_expires_at=expiry,
        )
        assert decision.delegated_action == "ops.entitlements.manage"
        assert decision.school_id == school
        with pytest.raises(ManagementAuthorizationDenied, match="not granted"):
            await require_management_permission(
                connection,
                _identity("oms", "security-admin", version=3),
                "ops.entitlements.manage",
                target_school_id=school,
                write=True,
            )


@pytest.mark.parametrize("disable_db_bump", [False, True])
async def test_tms_grant_requires_explicit_delegation_and_is_idempotent(
    pg_dsn, disable_db_bump
):
    from dataclasses import replace

    from deeptutor_enterprise.management.grants import (
        GrantRoleCommand,
        ManagementGrantConflict,
        grant_management_role,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    actor_subject = "school-admin"
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        actor = await _principal(connection, "tms", actor_subject, school)
        await _assignment(connection, "tms", actor, "school_admin", "school", school)
        target = await _principal(connection, "tms", "new-teacher", school, active=False)
        actions = await (
            await connection.execute(
                "SELECT action_key FROM management.role_actions "
                "WHERE application='tms' AND role_key='school_auditor' ORDER BY action_key"
            )
        ).fetchall()
        for (action,) in actions:
            await connection.execute(
                "INSERT INTO management.delegation_policies"
                "(id,application,principal_id,action_key,scope_kind,school_id,"
                "valid_from,expires_at) "
                "VALUES(%s,'tms',%s,%s,'school',%s,"
                "now()-interval '1 minute',now()+interval '2 hours')",
                (uuid.uuid4(), actor, action, school),
            )
            await _bump_policy_version(connection, actor)
        actor_version = 2 + len(actions)
    if disable_db_bump:
        # 目标 schema 已无数据库触发器；该参数保留，用同一路径证明程序逻辑独立生效。
        pass

    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    command = GrantRoleCommand(
        target_principal_id=target,
        role_key="school_auditor",
        role_version=1,
        target_school_id=school,
        expected_target_policy_version=1,
        expires_at=expiry,
        command_id=uuid.uuid4(),
        reason="合成学校角色授权",
        request_id="synthetic-request",
    )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        result = await grant_management_role(
            connection,
            _identity("tms", actor_subject, school, version=actor_version),
            _identity("tms", "new-teacher", school, version=1),
            command,
        )
        assert result.target_policy_version == 2
        assert result.replayed is False
        replay = await grant_management_role(
            connection,
            _identity("tms", actor_subject, school, version=actor_version),
            _identity("tms", "new-teacher", school, version=2),
            command,
        )
        assert replay.assignment_id == result.assignment_id
        assert replay.replayed is True
        with pytest.raises(ManagementGrantConflict, match="idempotency"):
            await grant_management_role(
                connection,
                _identity("tms", actor_subject, school, version=actor_version),
                _identity("tms", "new-teacher", school, version=2),
                replace(command, reason="冲突的重放"),
            )
        with pytest.raises(ManagementGrantConflict, match="idempotency"):
            await grant_management_role(
                connection,
                _identity("tms", actor_subject, school, version=actor_version),
                _identity("tms", "new-teacher", school, version=2),
                replace(command, expected_target_policy_version=2),
            )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        rows = await (
            await connection.execute(
                "SELECT school_binding_version FROM management.assignments WHERE id=%s",
                (result.assignment_id,),
            )
        ).fetchall()
        audits = await (
            await connection.execute(
                "SELECT action_key,result,request_id FROM management.audit_events "
                "WHERE target_id=%s",
                (str(result.assignment_id),),
            )
        ).fetchall()
        assert rows == [(1,)]
        assert audits == [("tenant.permissions.manage", "success", "synthetic-request")]
        await connection.execute(
            "UPDATE management.principals SET policy_version=policy_version+1 WHERE id=%s",
            (target,),
        )
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        later_replay = await grant_management_role(
            connection,
            _identity("tms", actor_subject, school, version=actor_version),
            _identity("tms", "new-teacher", school, version=3),
            command,
        )
        assert later_replay.replayed is True
        assert later_replay.target_policy_version == 2


async def test_management_grant_rejects_missing_delegation_and_sensitive_role(pg_dsn):
    from dataclasses import replace

    from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied
    from deeptutor_enterprise.management.grants import GrantRoleCommand, grant_management_role

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        actor = await _principal(connection, "tms", "admin", school)
        await _assignment(connection, "tms", actor, "school_admin", "school", school)
        target = await _principal(connection, "tms", "candidate", school, active=False)
        await connection.execute(
            "INSERT INTO management.delegation_policies"
            "(id,application,principal_id,action_key,scope_kind,school_id,"
            "valid_from,expires_at) "
            "VALUES(%s,'tms',%s,'tenant.tms.access','school',%s,"
            "now()-interval '1 minute',now()+interval '2 hours')",
            (uuid.uuid4(), actor, school),
        )
        await _bump_policy_version(connection, actor)
    command = GrantRoleCommand(
        target_principal_id=target,
        role_key="school_auditor",
        role_version=1,
        target_school_id=school,
        expected_target_policy_version=1,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        command_id=uuid.uuid4(),
        reason="合成拒绝测试",
        request_id="synthetic-denied",
    )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        with pytest.raises(ManagementAuthorizationDenied, match="delegation"):
            await grant_management_role(
                connection,
                _identity("tms", "admin", school, version=3),
                _identity("tms", "candidate", school, version=1),
                command,
            )
        with pytest.raises(ManagementAuthorizationDenied, match="independent approval"):
            await grant_management_role(
                connection,
                _identity("tms", "admin", school, version=3),
                _identity("tms", "candidate", school, version=1),
                replace(command, role_key="school_operator", command_id=uuid.uuid4()),
            )
        with pytest.raises(ManagementAuthorizationDenied, match="self grant"):
            await grant_management_role(
                connection,
                _identity("tms", "admin", school, version=3),
                _identity("tms", "admin", school, version=2),
                replace(
                    command,
                    target_principal_id=actor,
                    expected_target_policy_version=2,
                    command_id=uuid.uuid4(),
                ),
            )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        assignments = await (
            await connection.execute(
                "SELECT count(*) FROM management.assignments WHERE principal_id=%s", (target,)
            )
        ).fetchone()
        assert assignments == (0,)


async def test_oms_governance_can_grant_only_delegated_school_role(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )
    from deeptutor_enterprise.management.grants import GrantRoleCommand, grant_management_role

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        actor = await _principal(connection, "oms", "security-admin")
        await _assignment(connection, "oms", actor, "platform_security_admin", "platform")
        target = await _principal(connection, "oms", "auditor", active=False)
        actions = await (
            await connection.execute(
                "SELECT action_key FROM management.role_actions "
                "WHERE application='oms' AND role_key='platform_auditor' ORDER BY action_key"
            )
        ).fetchall()
        for (action,) in actions:
            await connection.execute(
                "INSERT INTO management.delegation_policies"
                "(id,application,principal_id,action_key,scope_kind,school_id,"
                "valid_from,expires_at) "
                "VALUES(%s,'oms',%s,%s,'school',%s,"
                "now()-interval '1 minute',now()+interval '2 hours')",
                (uuid.uuid4(), actor, action, school),
            )
            await _bump_policy_version(connection, actor)
        actor_version = 2 + len(actions)
    command = GrantRoleCommand(
        target_principal_id=target,
        role_key="platform_auditor",
        role_version=1,
        target_school_id=school,
        expected_target_policy_version=1,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        command_id=uuid.uuid4(),
        reason="合成平台学校范围授予",
        request_id="synthetic-oms-request",
    )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        result = await grant_management_role(
            connection,
            _identity("oms", "security-admin", version=actor_version),
            _identity("oms", "auditor", version=1),
            command,
        )
        assert result.target_policy_version == 2
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection,
                _identity("oms", "security-admin", version=actor_version),
                "ops.audit.read",
                target_school_id=school,
            )


@pytest.mark.parametrize("disable_db_bump", [False, True])
async def test_tms_role_revoke_invalidates_old_session_and_replays_once(
    pg_dsn, disable_db_bump
):
    from dataclasses import replace

    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )
    from deeptutor_enterprise.management.grants import (
        ManagementGrantConflict,
        RevokeRoleCommand,
        revoke_management_role,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        actor = await _principal(connection, "tms", "school-admin", school)
        await _assignment(connection, "tms", actor, "school_admin", "school", school)
        target = await _principal(connection, "tms", "school-auditor", school)
        target_assignment = await _assignment(
            connection, "tms", target, "school_auditor", "school", school
        )
    if disable_db_bump:
        # 目标 schema 已无数据库触发器；该参数保留，用同一路径证明程序逻辑独立生效。
        pass
    command = RevokeRoleCommand(
        assignment_id=target_assignment,
        target_school_id=school,
        expected_assignment_version=1,
        expected_target_policy_version=2,
        command_id=uuid.uuid4(),
        reason="合成撤权",
        request_id="synthetic-revoke",
    )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        result = await revoke_management_role(
            connection, _identity("tms", "school-admin", school), command
        )
        assert result.assignment_version == 2
        assert result.target_policy_version == 3
        assert result.replayed is False
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection,
                _identity("tms", "school-auditor", school, version=2),
                "tenant.members.read",
                target_school_id=school,
            )
        replay = await revoke_management_role(
            connection, _identity("tms", "school-admin", school), command
        )
        assert replay.replayed is True
        assert replay.assignment_version == result.assignment_version
        with pytest.raises(ManagementGrantConflict, match="idempotency"):
            await revoke_management_role(
                connection,
                _identity("tms", "school-admin", school),
                replace(command, expected_assignment_version=2),
            )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        rows = await (
            await connection.execute(
                "SELECT status,version,revoked_at IS NOT NULL FROM management.assignments "
                "WHERE id=%s",
                (target_assignment,),
            )
        ).fetchall()
        audits = await (
            await connection.execute(
                "SELECT action_key,result,request_id,before_version,after_version "
                "FROM management.audit_events WHERE id=%s",
                (command.command_id,),
            )
        ).fetchall()
        assert rows == [("revoked", 2, True)]
        assert audits == [("tenant.permissions.manage", "success", "synthetic-revoke", 2, 3)]
        await connection.execute(
            "UPDATE management.principals SET policy_version=policy_version+1 WHERE id=%s",
            (target,),
        )
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        later_replay = await revoke_management_role(
            connection, _identity("tms", "school-admin", school), command
        )
        assert later_replay.replayed is True
        assert later_replay.target_policy_version == 3


@pytest.mark.parametrize("disable_db_guard", [False, True])
async def test_last_school_admin_revoke_is_conflict_without_poisoning_transaction(
    pg_dsn, disable_db_guard
):
    from deeptutor_enterprise.management.authorization import require_management_permission
    from deeptutor_enterprise.management.grants import (
        ManagementGrantConflict,
        RevokeRoleCommand,
        revoke_management_role,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        actor = await _principal(connection, "tms", "only-admin", school)
        assignment = await _assignment(connection, "tms", actor, "school_admin", "school", school)
    if disable_db_guard:
        # 目标 schema 已无数据库触发器；该参数保留，用同一路径证明程序逻辑独立生效。
        pass
    command = RevokeRoleCommand(
        assignment_id=assignment,
        target_school_id=school,
        expected_assignment_version=1,
        expected_target_policy_version=2,
        command_id=uuid.uuid4(),
        reason="最后管理员不可撤权",
        request_id="synthetic-last-admin",
    )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        with pytest.raises(ManagementGrantConflict, match="last"):
            await revoke_management_role(
                connection, _identity("tms", "only-admin", school), command
            )
        decision = await require_management_permission(
            connection,
            _identity("tms", "only-admin", school),
            "tenant.permissions.manage",
            target_school_id=school,
            write=True,
        )
        assert decision.assignment_id == assignment


async def test_last_platform_security_admin_revoke_is_blocked_by_application(pg_dsn):
    from deeptutor_enterprise.management.grants import (
        ManagementGrantConflict,
        RevokeRoleCommand,
        revoke_management_role,
    )

    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        principal = await _principal(connection, "oms", "only-security-admin")
        assignment = await _assignment(
            connection, "oms", principal, "platform_security_admin", "platform"
        )
    command = RevokeRoleCommand(
        assignment_id=assignment,
        target_school_id=None,
        expected_assignment_version=1,
        expected_target_policy_version=2,
        command_id=uuid.uuid4(),
        reason="平台最后管理员不可撤权",
        request_id="synthetic-last-platform-admin",
    )
    async with await psycopg.AsyncConnection.connect(single_database_user_dsn(pg_dsn)) as c:
        with pytest.raises(ManagementGrantConflict, match="last"):
            await revoke_management_role(c, _identity("oms", "only-security-admin"), command)


async def test_two_administrators_cannot_revoke_each_other_concurrently_without_db_guard(
    pg_dsn,
):
    from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied
    from deeptutor_enterprise.management.grants import (
        ManagementGrantConflict,
        RevokeRoleCommand,
        revoke_management_role,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await _tenant(c, school)
        await c.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        first = await _principal(c, "tms", "admin-one", school)
        second = await _principal(c, "tms", "admin-two", school)
        first_assignment = await _assignment(c, "tms", first, "school_admin", "school", school)
        second_assignment = await _assignment(c, "tms", second, "school_admin", "school", school)
    runtime_dsn = single_database_user_dsn(pg_dsn)

    async def revoke_as(subject: str, assignment_id: uuid.UUID):
        command = RevokeRoleCommand(
            assignment_id=assignment_id,
            target_school_id=school,
            expected_assignment_version=1,
            expected_target_policy_version=2,
            command_id=uuid.uuid4(),
            reason="合成双管理员互撤",
            request_id=f"synthetic-revoke-{subject}",
        )
        try:
            async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
                await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
                await revoke_management_role(c, _identity("tms", subject, school), command)
            return "revoked"
        except (ManagementAuthorizationDenied, ManagementGrantConflict):
            return "denied"

    outcomes = await asyncio.wait_for(
        asyncio.gather(
            revoke_as("admin-one", second_assignment),
            revoke_as("admin-two", first_assignment),
        ),
        timeout=5,
    )
    assert sorted(outcomes) == ["denied", "revoked"]
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        active = await (
            await c.execute(
                "SELECT count(*) FROM management.assignments WHERE application='tms' "
                "AND school_id=%s AND role_key='school_admin' AND status='active'",
                (school,),
            )
        ).fetchone()
    assert active == (1,)


async def test_revoke_waits_for_inflight_management_write_and_blocks_old_version(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )
    from deeptutor_enterprise.management.grants import RevokeRoleCommand, revoke_management_role

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        actor = await _principal(connection, "tms", "school-admin", school)
        await _assignment(connection, "tms", actor, "school_admin", "school", school)
        target = await _principal(connection, "tms", "school-auditor", school)
        assignment = await _assignment(
            connection, "tms", target, "school_auditor", "school", school
        )
    command = RevokeRoleCommand(
        assignment_id=assignment,
        target_school_id=school,
        expected_assignment_version=1,
        expected_target_policy_version=2,
        command_id=uuid.uuid4(),
        reason="并发撤权",
        request_id="synthetic-race",
    )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    writer = await psycopg.AsyncConnection.connect(runtime_dsn)
    revoker = await psycopg.AsyncConnection.connect(runtime_dsn)
    try:
        await writer.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        await revoker.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        await require_management_permission(
            writer,
            _identity("tms", "school-auditor", school, version=2),
            "tenant.members.read",
            target_school_id=school,
            write=True,
        )
        revoke_task = asyncio.create_task(
            revoke_management_role(revoker, _identity("tms", "school-admin", school), command)
        )
        await asyncio.sleep(0.1)
        assert not revoke_task.done()
        await writer.commit()
        result = await asyncio.wait_for(revoke_task, timeout=3)
        assert result.target_policy_version == 3
        await revoker.commit()
    finally:
        await writer.close()
        await revoker.close()
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection,
                _identity("tms", "school-auditor", school, version=2),
                "tenant.members.read",
                target_school_id=school,
                write=True,
            )


async def test_tms_role_revoke_cannot_target_another_school(pg_dsn):
    from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied
    from deeptutor_enterprise.management.grants import RevokeRoleCommand, revoke_management_role

    await MigrationRunner(pg_dsn).apply()
    school_a, school_b = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        for school, external_id in ((school_a, 101), (school_b, 202)):
            await _tenant(connection, school)
            await connection.execute(
                "INSERT INTO oms.school_bindings"
                "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
                "VALUES(%s,%s,'verified',now(),'synthetic-verifier','synthetic://school')",
                (school, external_id),
            )
        actor = await _principal(connection, "tms", "school-a-admin", school_a)
        await _assignment(connection, "tms", actor, "school_admin", "school", school_a)
        target = await _principal(connection, "tms", "school-b-auditor", school_b)
        assignment = await _assignment(
            connection, "tms", target, "school_auditor", "school", school_b
        )
    command = RevokeRoleCommand(
        assignment_id=assignment,
        target_school_id=school_b,
        expected_assignment_version=1,
        expected_target_policy_version=2,
        command_id=uuid.uuid4(),
        reason="禁止跨校撤权",
        request_id="synthetic-cross-school",
    )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_a),))
        with pytest.raises(ManagementAuthorizationDenied, match="school"):
            await revoke_management_role(
                connection, _identity("tms", "school-a-admin", school_a), command
            )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT status FROM management.assignments WHERE id=%s", (assignment,)
            )
        ).fetchone()
        assert row == ("active",)


async def test_unverified_external_status_never_authorizes(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        principal = await _principal(connection, "oms", "operator")
        await _assignment(connection, "oms", principal, "platform_security_admin", "platform")
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection, _identity("oms", "operator", active=False), "ops.oms.access"
            )


async def test_stale_external_check_cannot_authorize_management_write(pg_dsn):
    from dataclasses import replace

    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        principal = await _principal(connection, "oms", "operator")
        await _assignment(connection, "oms", principal, "platform_security_admin", "platform")
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        stale = replace(
            _identity("oms", "operator"),
            external_checked_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection,
                stale,
                "ops.permissions.manage",
                write=True,
            )


async def test_management_write_rejects_autocommit_without_transaction_lock(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        principal = await _principal(connection, "oms", "operator")
        await _assignment(connection, "oms", principal, "platform_security_admin", "platform")
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn, autocommit=True) as connection:
        with pytest.raises(ManagementAuthorizationDenied, match="transaction"):
            await require_management_permission(
                connection,
                _identity("oms", "operator"),
                "ops.permissions.manage",
                write=True,
            )


async def test_custom_oms_role_is_explicit_and_school_scope_is_not_platform(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        principal = await _principal(connection, "oms", "scoped-operator")
        await connection.execute(
            "INSERT INTO management.role_versions"
            "(application,role_key,version,scope_kind) "
            "VALUES('oms','custom_school_quota',1,'school')"
        )
        await connection.execute(
            "INSERT INTO management.role_actions"
            "(application,role_key,role_version,action_key) "
            "VALUES('oms','custom_school_quota',1,'ops.quotas.manage')"
        )
        await _assignment(connection, "oms", principal, "custom_school_quota", "school", school)
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        decision = await require_management_permission(
            connection,
            _identity("oms", "scoped-operator"),
            "ops.quotas.manage",
            target_school_id=school,
            write=True,
        )
        assert decision.school_id == school
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection, _identity("oms", "scoped-operator"), "ops.oms.access"
            )
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection,
                _identity("oms", "scoped-operator"),
                "tenant.permissions.manage",
                target_school_id=school,
            )


async def test_school_scoped_oms_operator_can_enter_only_its_school(pg_dsn):
    from deeptutor_enterprise.management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await _tenant(connection, school)
        await connection.execute(
            "INSERT INTO oms.school_bindings"
            "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
            "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
            (school,),
        )
        principal = await _principal(connection, "oms", "school-operator")
        await _assignment(connection, "oms", principal, "platform_operator", "school", school)
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        decision = await require_management_permission(
            connection,
            _identity("oms", "school-operator"),
            "ops.oms.access",
            target_school_id=school,
        )
        assert decision.school_id == school
        with pytest.raises(ManagementAuthorizationDenied):
            await require_management_permission(
                connection, _identity("oms", "school-operator"), "ops.oms.access"
            )
