"""隔离合成 PG 中验证学校角色 owner、版本固定与重复迁移。"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from deeptutor_enterprise.management.authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
    require_management_permission,
)
from deeptutor_enterprise.management.grants import GrantRoleCommand, grant_management_role
from deeptutor_enterprise.management.roles import PublishCustomRoleCommand, publish_custom_role
from deeptutor_enterprise.migrations.runner import MigrationRunner
import psycopg
import pytest

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio
_SCHOOL_A = UUID("10000000-0000-0000-0000-000000000001")
_SCHOOL_B = UUID("10000000-0000-0000-0000-000000000002")
_ISSUER = "https://synthetic-issuer.example"


def _identity(subject: str, school_id: UUID, version: int) -> ManagementIdentity:
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="tms",
        issuer=_ISSUER,
        subject=subject,
        school_id=school_id,
        policy_version=version,
        school_binding_version=1,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )


async def _setup_school(connection, school_id: UUID, external_id: int, subject: str):
    await connection.execute(
        "INSERT INTO enterprise.tenants"
        "(id,external_eligibility,auth_epoch,bootstrap_completed,local_enabled,"
        "provisioning_status) VALUES(%s,'allowed','synthetic',true,true,'ready')",
        (school_id,),
    )
    await connection.execute(
        "INSERT INTO oms.school_bindings"
        "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
        "VALUES(%s,%s,'verified',now(),'synthetic-verifier','synthetic://school')",
        (school_id, external_id),
    )
    principal_id = uuid4()
    await connection.execute(
        "INSERT INTO management.principals"
        "(id,application,issuer,subject,school_id,status) "
        "VALUES(%s,'tms',%s,%s,%s,'active')",
        (principal_id, _ISSUER, subject, school_id),
    )
    await connection.execute(
        "INSERT INTO management.assignments"
        "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
        "school_binding_version,valid_from,expires_at,command_id,created_by) "
        "VALUES(%s,'tms',%s,'school_admin',1,'school',%s,1,"
        "now()-interval '1 minute',now()+interval '2 hours',%s,'synthetic-setup')",
        (uuid4(), principal_id, school_id, uuid4()),
    )
    for action in ("tenant.members.read", "tenant.usage.read"):
        await connection.execute(
            "INSERT INTO management.delegation_policies"
            "(id,application,principal_id,action_key,scope_kind,school_id,"
            "valid_from,expires_at) VALUES(%s,'tms',%s,%s,'school',%s,"
            "now()-interval '1 minute',now()+interval '2 hours')",
            (uuid4(), principal_id, action, school_id),
        )
    version = await (
        await connection.execute(
            "SELECT policy_version FROM management.principals WHERE id=%s", (principal_id,)
        )
    ).fetchone()
    return version[0]


def _role_command(school_id: UUID, *, expected_version: int, actions: tuple[str, ...]):
    return PublishCustomRoleCommand(
        role_key="custom_readers",
        scope_kind="school",
        target_school_id=school_id,
        action_keys=actions,
        expected_version=expected_version,
        command_id=uuid4(),
        reason="隔离合成角色发布",
        request_id="synthetic-role-request",
    )


async def test_tms_custom_roles_are_school_owned_and_old_assignments_do_not_expand(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        version_a = await _setup_school(connection, _SCHOOL_A, 101, "admin-a")
        version_b = await _setup_school(connection, _SCHOOL_B, 102, "admin-b")
        target_a = uuid4()
        target_b = uuid4()
        for principal_id, school_id, subject in (
            (target_a, _SCHOOL_A, "member-a"),
            (target_b, _SCHOOL_B, "member-b"),
        ):
            await connection.execute(
                "INSERT INTO management.principals"
                "(id,application,issuer,subject,school_id,status) "
                "VALUES(%s,'tms',%s,%s,%s,'pending')",
                (principal_id, _ISSUER, subject, school_id),
            )

    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(_SCHOOL_A),))
        actor_a = _identity("admin-a", _SCHOOL_A, version_a)
        role_a = await publish_custom_role(
            connection,
            actor_a,
            _role_command(_SCHOOL_A, expected_version=0, actions=("tenant.members.read",)),
        )
        assert role_a.role_key == f"custom_{_SCHOOL_A.hex}_readers"
        assert role_a.version == 1
        grant = await grant_management_role(
            connection,
            actor_a,
            _identity("member-a", _SCHOOL_A, 1),
            GrantRoleCommand(
                target_principal_id=target_a,
                role_key=role_a.role_key,
                role_version=1,
                target_school_id=_SCHOOL_A,
                expected_target_policy_version=1,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                command_id=uuid4(),
                reason="隔离合成角色授予",
                request_id="synthetic-grant-request",
            ),
        )
        assert grant.target_policy_version == 2
        role_a_v2 = await publish_custom_role(
            connection,
            actor_a,
            _role_command(
                _SCHOOL_A,
                expected_version=1,
                actions=("tenant.members.read", "tenant.usage.read"),
            ),
        )
        assert role_a_v2.version == 2
        with pytest.raises(ManagementAuthorizationDenied, match="not granted"):
            await require_management_permission(
                connection,
                _identity("member-a", _SCHOOL_A, 2),
                "tenant.usage.read",
                target_school_id=_SCHOOL_A,
                write=True,
            )

    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(_SCHOOL_B),))
        actor_b = _identity("admin-b", _SCHOOL_B, version_b)
        role_b = await publish_custom_role(
            connection,
            actor_b,
            _role_command(_SCHOOL_B, expected_version=0, actions=("tenant.members.read",)),
        )
        assert role_b.role_key == f"custom_{_SCHOOL_B.hex}_readers"
        assert role_b.role_key != role_a.role_key
        with pytest.raises(ManagementAuthorizationDenied, match="role version or school owner"):
            await grant_management_role(
                connection,
                actor_b,
                _identity("member-b", _SCHOOL_B, 1),
                GrantRoleCommand(
                    target_principal_id=target_b,
                    role_key=role_a.role_key,
                    role_version=1,
                    target_school_id=_SCHOOL_B,
                    expected_target_policy_version=1,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    command_id=uuid4(),
                    reason="跨校角色授予应拒绝",
                    request_id="synthetic-cross-school",
                ),
            )

    await runner.apply()
    await runner.verify()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        rows = await (
            await connection.execute(
                "SELECT role_key,owner_school_id,version FROM management.role_versions "
                "WHERE application='tms' AND role_key LIKE 'custom_%' ORDER BY role_key,version"
            )
        ).fetchall()
    assert rows == [
        (role_a.role_key, _SCHOOL_A, 1),
        (role_a.role_key, _SCHOOL_A, 2),
        (role_b.role_key, _SCHOOL_B, 1),
    ]
