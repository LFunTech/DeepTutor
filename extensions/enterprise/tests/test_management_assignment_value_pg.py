"""在隔离合成 PG 去掉状态 CHECK 后，管理 PEP 仍拒绝旧未知事实。"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from deeptutor_enterprise.management.authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
    require_management_permission,
)
from deeptutor_enterprise.migrations.runner import MigrationRunner
import psycopg
import pytest

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


def _identity():
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application="oms",
        issuer="https://synthetic-issuer.example",
        subject="synthetic-config-admin",
        school_id=None,
        policy_version=2,
        school_binding_version=None,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=1),
    )


async def test_assignment_unknown_status_is_denied_without_database_enum_check(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    principal_id, assignment_id = uuid4(), uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,status) "
            "VALUES(%s,'oms',%s,%s,'active')",
            (
                principal_id,
                "https://synthetic-issuer.example",
                "synthetic-config-admin",
            ),
        )
        await c.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_config_admin',1,'platform',"
            "now()-interval '1 minute',now()+interval '1 hour',%s,'synthetic')",
            (assignment_id, principal_id, uuid4()),
        )
        await c.execute(
            "UPDATE management.principals SET policy_version=policy_version+1 "
            "WHERE id=%s",
            (principal_id,),
        )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        granted = await require_management_permission(c, _identity(), "ops.oms.access", write=True)
        assert granted.assignment_id == assignment_id

    # 仅在独立合成库中模拟移除数据库枚举 CHECK 后的异常历史值；正式迁移
    # 仍须等待整个管理域程序接管及预检完成，不能据此提前 DROP。
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "ALTER TABLE management.assignments DROP CONSTRAINT IF EXISTS assignments_status_check"
        )
        await c.execute("ALTER TABLE management.assignments DROP CONSTRAINT IF EXISTS assignments_check2")
        await c.execute(
            "UPDATE management.assignments SET status='future_status' WHERE id=%s",
            (assignment_id,),
        )
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        with pytest.raises(ManagementAuthorizationDenied, match="assignment fact"):
            await require_management_permission(c, _identity(), "ops.oms.access", write=True)
