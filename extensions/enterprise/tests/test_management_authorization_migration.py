"""OMS/TMS 授权底座仅在临时 PostgreSQL 中验证。"""

from __future__ import annotations

import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
import psycopg
from psycopg import sql
import pytest

from deeptutor.persistence.postgres.migrations.runner import MigrationRunner as CoreMigrationRunner
from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio


async def test_management_schema_is_versioned_repeatable_and_default_deny(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    assert "management/0001_authorization_base" in await runner.plan()

    await runner.apply()
    await runner.apply()
    await runner.verify()
    assert await runner.plan() == []

    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        history = await (
            await connection.execute("SELECT version FROM management.schema_history")
        ).fetchall()
        principals = await (
            await connection.execute("SELECT count(*) FROM management.principals")
        ).fetchone()
        assignments = await (
            await connection.execute("SELECT count(*) FROM management.assignments")
        ).fetchone()
        tables = await (
            await connection.execute(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='management' AND c.relkind='r'"
            )
        ).fetchall()
    assert history == [
        ("0001_authorization_base",),
        ("0002_approval_delegation_guards",),
        ("0003_assignment_school_binding_version",),
    ]
    assert principals == (0,)
    assert assignments == (0,)
    scoped = {
        "principals",
        "action_catalog",
        "role_versions",
        "role_actions",
        "assignments",
        "delegation_policies",
        "approval_requests",
        "audit_events",
    }
    assert {name for name, *_ in tables} == {"schema_history", *scoped}
    assert all(rls and force for name, rls, force in tables if name in scoped)


async def test_management_migration_failure_rolls_back_schema_and_history(pg_dsn):
    class FailingRunner(MigrationRunner):
        def _management_migrations(self):
            return super()._management_migrations() + [
                (
                    "0002_forced_failure",
                    "CREATE TABLE management.uncommitted_probe(id int); SELECT 1/0;",
                )
            ]

    with pytest.raises(psycopg.errors.DivisionByZero):
        await FailingRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        assert (
            await (await connection.execute("SELECT to_regnamespace('management')")).fetchone()
        ) == (None,)
    await MigrationRunner(pg_dsn).apply()
    await MigrationRunner(pg_dsn).verify()


async def test_management_rls_separates_apps_and_schools(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    school_a, school_b = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        for school in (school_a, school_b):
            await connection.execute(
                "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
                "VALUES(%s,'allowed','synthetic')",
                (school,),
            )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.management_app','tms',true)")
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_a),))
        await connection.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,school_id) "
            "VALUES(%s,'tms','https://issuer.example','subject-a',%s)",
            (uuid.uuid4(), school_a),
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            await connection.execute(
                "INSERT INTO management.principals(id,application,issuer,subject,school_id) "
                "VALUES(%s,'tms','https://issuer.example','subject-b',%s)",
                (uuid.uuid4(), school_b),
            )


async def test_management_schema_drift_and_audit_mutation_fail_closed(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute("ALTER TABLE management.assignments DISABLE ROW LEVEL SECURITY")
    with pytest.raises(RuntimeError, match="management schema drift"):
        await runner.verify()


async def test_management_rls_policy_expression_drift_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute("DROP POLICY management_scope ON management.assignments")
        await connection.execute(
            "CREATE POLICY management_scope ON management.assignments "
            "USING (true) WITH CHECK (true)"
        )
    with pytest.raises(RuntimeError, match="management schema drift"):
        await runner.verify()


async def test_management_action_domain_constraint_drift_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid='management.action_catalog'::regclass "
                "AND pg_get_constraintdef(oid) LIKE '%ops.%'"
            )
        ).fetchone()
        assert row is not None
        await connection.execute(
            sql.SQL("ALTER TABLE management.action_catalog DROP CONSTRAINT {}").format(
                sql.Identifier(row[0])
            )
        )
    with pytest.raises(RuntimeError, match="management schema drift"):
        await runner.verify()


async def test_role_action_scope_cannot_cross_platform_and_school(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            await connection.execute(
                "INSERT INTO management.role_actions"
                "(application,role_key,role_version,action_key) "
                "VALUES('oms','platform_security_admin',1,'ops.tenants.read')"
            )


async def test_last_active_school_admin_cannot_be_revoked(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    principal = uuid.uuid4()
    assignment = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','synthetic')",
            (school,),
        )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.management_app','tms',true)")
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        await connection.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,school_id,status) "
            "VALUES(%s,'tms','https://issuer.example','school-lead',%s,'active')",
            (principal, school),
        )
        await connection.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'tms',%s,'school_admin',1,'school',%s,now()-interval '1 day',"
            "now()+interval '1 day',%s,'synthetic-approval')",
            (assignment, principal, school, uuid.uuid4()),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            await connection.execute(
                "UPDATE management.assignments SET status='revoked',revoked_at=now() WHERE id=%s",
                (assignment,),
            )


async def test_last_school_admin_cannot_be_removed_by_expiry_or_principal_disable(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    school, principal, assignment = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','synthetic')",
            (school,),
        )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as connection:
        await connection.execute("SELECT set_config('app.management_app','tms',true)")
        await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        await connection.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,school_id,status) "
            "VALUES(%s,'tms','https://issuer.example','school-admin',%s,'active')",
            (principal, school),
        )
        await connection.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'tms',%s,'school_admin',1,'school',%s,now()-interval '1 day',"
            "now()+interval '1 day',%s,'synthetic-approval')",
            (assignment, principal, school, uuid.uuid4()),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            async with connection.transaction():
                await connection.execute(
                    "UPDATE management.assignments SET expires_at=now()+interval '1 second' "
                    "WHERE id=%s",
                    (assignment,),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            async with connection.transaction():
                await connection.execute(
                    "UPDATE management.principals SET status='disabled' WHERE id=%s",
                    (principal,),
                )


async def test_last_platform_security_admin_cannot_be_revoked_or_disabled(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    principal, assignment = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms','https://issuer.example','platform-admin','active')",
            (principal,),
        )
        await connection.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_security_admin',1,'platform',"
            "now()-interval '1 day',now()+interval '1 day',%s,'synthetic-approval')",
            (assignment, principal, uuid.uuid4()),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            async with connection.transaction():
                await connection.execute(
                    "UPDATE management.assignments SET status='revoked',revoked_at=now() "
                    "WHERE id=%s",
                    (assignment,),
                )
        with pytest.raises(psycopg.errors.CheckViolation):
            async with connection.transaction():
                await connection.execute(
                    "UPDATE management.principals SET status='disabled' WHERE id=%s",
                    (principal,),
                )


async def test_role_name_without_management_action_is_not_replacement_admin(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    original, impostor = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) VALUES "
            "(%s,'oms','https://issuer.example','original','active'),"
            "(%s,'oms','https://issuer.example','impostor','active')",
            (original, impostor),
        )
        await connection.execute(
            "INSERT INTO management.role_versions(application,role_key,version,scope_kind) "
            "VALUES('oms','platform_security_admin',2,'platform')"
        )
        original_assignment = uuid.uuid4()
        for principal, version, assignment in (
            (original, 1, original_assignment),
            (impostor, 2, uuid.uuid4()),
        ):
            await connection.execute(
                "INSERT INTO management.assignments"
                "(id,application,principal_id,role_key,role_version,scope_kind,"
                "valid_from,expires_at,command_id,created_by) "
                "VALUES(%s,'oms',%s,'platform_security_admin',%s,'platform',"
                "now()-interval '1 day',now()+interval '1 day',%s,'synthetic-approval')",
                (assignment, principal, version, uuid.uuid4()),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            await connection.execute(
                "UPDATE management.assignments SET status='revoked',revoked_at=now() WHERE id=%s",
                (original_assignment,),
            )


async def test_management_governance_action_cannot_be_retired_in_place(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        for application, action in (
            ("oms", "ops.permissions.manage"),
            ("tms", "tenant.permissions.manage"),
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                async with connection.transaction():
                    await connection.execute(
                        "UPDATE management.action_catalog SET status='retired' "
                        "WHERE application=%s AND action_key=%s",
                        (application, action),
                    )


async def test_assignment_changes_advance_principal_policy_version(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    principal = uuid.uuid4()
    assignment = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms','https://issuer.example','operator','active')",
            (principal,),
        )
        await connection.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_config_admin',1,'platform',"
            "now()-interval '1 day',now()+interval '1 day',%s,'synthetic-approval')",
            (assignment, principal, uuid.uuid4()),
        )
        granted = await (
            await connection.execute(
                "SELECT policy_version FROM management.principals WHERE id=%s", (principal,)
            )
        ).fetchone()
        await connection.execute(
            "UPDATE management.assignments SET status='revoked',revoked_at=now() WHERE id=%s",
            (assignment,),
        )
        revoked = await (
            await connection.execute(
                "SELECT policy_version FROM management.principals WHERE id=%s", (principal,)
            )
        ).fetchone()
        await connection.execute("DELETE FROM management.assignments WHERE id=%s", (assignment,))
        deleted = await (
            await connection.execute(
                "SELECT policy_version FROM management.principals WHERE id=%s", (principal,)
            )
        ).fetchone()
    assert granted == (2,)
    assert revoked == (3,)
    assert deleted == (4,)


async def test_approved_request_requires_distinct_complete_reviewer(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    principal = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms','https://issuer.example','candidate','active')",
            (principal,),
        )
        for reviewer_issuer, reviewer_subject in (
            (None, "proposer"),
            ("https://issuer.example", None),
            ("https://issuer.example", "proposer"),
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                async with connection.transaction():
                    await connection.execute(
                        "INSERT INTO management.approval_requests"
                        "(id,application,operation,target_principal_id,proposer_issuer,"
                        "proposer_subject,reviewer_issuer,reviewer_subject,expected_policy_version,"
                        "status,expires_at,idempotency_key,reason,request_id,decided_at) "
                        "VALUES(%s,'oms','platform_grant',%s,'https://issuer.example',"
                        "'proposer',%s,%s,1,'approved',now()+interval '1 day',%s,"
                        "'synthetic-test',%s,now())",
                        (
                            uuid.uuid4(),
                            principal,
                            reviewer_issuer,
                            reviewer_subject,
                            str(uuid.uuid4()),
                            str(uuid.uuid4()),
                        ),
                    )
        await connection.execute(
            "INSERT INTO management.approval_requests"
            "(id,application,operation,target_principal_id,proposer_issuer,"
            "proposer_subject,reviewer_issuer,reviewer_subject,expected_policy_version,"
            "status,expires_at,idempotency_key,reason,request_id,decided_at) "
            "VALUES(%s,'oms','platform_grant',%s,'https://issuer.example',"
            "'proposer','https://issuer.example','reviewer',1,'approved',"
            "now()+interval '1 day',%s,'synthetic-test',%s,now())",
            (uuid.uuid4(), principal, str(uuid.uuid4()), str(uuid.uuid4())),
        )


async def test_tms_delegation_cannot_target_another_school(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    school_a, school_b, principal = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        for school in (school_a, school_b):
            await connection.execute(
                "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
                "VALUES(%s,'allowed','synthetic')",
                (school,),
            )
        await connection.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,school_id,status) "
            "VALUES(%s,'tms','https://issuer.example','school-admin',%s,'active')",
            (principal, school_a),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            async with connection.transaction():
                await connection.execute(
                    "INSERT INTO management.delegation_policies"
                    "(id,application,principal_id,action_key,scope_kind,school_id,valid_from,expires_at) "
                    "VALUES(%s,'tms',%s,'tenant.permissions.manage','school',%s,"
                    "now()-interval '1 day',now()+interval '1 day')",
                    (uuid.uuid4(), principal, school_b),
                )
        await connection.execute(
            "INSERT INTO management.delegation_policies"
            "(id,application,principal_id,action_key,scope_kind,school_id,valid_from,expires_at) "
            "VALUES(%s,'tms',%s,'tenant.permissions.manage','school',%s,"
            "now()-interval '1 day',now()+interval '1 day')",
            (uuid.uuid4(), principal, school_a),
        )


async def test_delegation_action_scope_must_match_catalog(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    school, principal = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','synthetic')",
            (school,),
        )
        await connection.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms','https://issuer.example','operator','active')",
            (principal,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            await connection.execute(
                "INSERT INTO management.delegation_policies"
                "(id,application,principal_id,action_key,scope_kind,school_id,valid_from,expires_at) "
                "VALUES(%s,'oms',%s,'ops.credentials.manage','school',%s,"
                "now()-interval '1 day',now()+interval '1 day')",
                (uuid.uuid4(), principal, school),
            )


async def test_legacy_tenant_admin_is_not_promoted_by_management_migration(pg_dsn):
    await CoreMigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','synthetic')",
            (school,),
        )
        await connection.execute(
            "INSERT INTO enterprise.users(tenant_id,id,username,role) "
            "VALUES(%s,'legacy-admin','legacy-admin','tenant_admin')",
            (school,),
        )
    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        assert (
            await (
                await connection.execute("SELECT count(*) FROM management.principals")
            ).fetchone()
        ) == (0,)
        assert (
            await (
                await connection.execute("SELECT count(*) FROM management.assignments")
            ).fetchone()
        ) == (0,)


async def test_management_assignment_command_id_is_unique(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    principal, command = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms','https://issuer.example','operator','active')",
            (principal,),
        )
        await connection.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_config_admin',1,'platform',"
            "now()-interval '1 day',now()+interval '1 day',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, command),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            await connection.execute(
                "INSERT INTO management.assignments"
                "(id,application,principal_id,role_key,role_version,scope_kind,"
                "valid_from,expires_at,command_id,created_by) "
                "VALUES(%s,'oms',%s,'platform_security_admin',1,'platform',"
                "now()-interval '1 day',now()+interval '1 day',%s,'synthetic-approval')",
                (uuid.uuid4(), principal, command),
            )


async def test_management_approval_idempotency_key_is_unique(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    principal = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO management.principals(id,application,issuer,subject,status) "
            "VALUES(%s,'oms','https://issuer.example','candidate','active')",
            (principal,),
        )
        key = str(uuid.uuid4())
        command = (
            "INSERT INTO management.approval_requests"
            "(id,application,operation,target_principal_id,proposer_issuer,"
            "proposer_subject,expected_policy_version,expires_at,idempotency_key,"
            "reason,request_id) VALUES(%s,'oms','platform_grant',%s,"
            "'https://issuer.example','proposer',1,now()+interval '1 day',"
            "%s,'synthetic-test',%s)"
        )
        await connection.execute(command, (uuid.uuid4(), principal, key, str(uuid.uuid4())))
        with pytest.raises(psycopg.errors.UniqueViolation):
            async with connection.transaction():
                await connection.execute(command, (uuid.uuid4(), principal, key, str(uuid.uuid4())))


async def test_management_audit_fact_is_append_only(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    event = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO management.audit_events"
            "(id,application,actor_issuer,actor_subject,action_key,target_kind,target_id,"
            "request_id,result,reason) "
            "VALUES(%s,'oms','https://issuer.example','operator',"
            "'ops.permissions.manage','principal','candidate','request-1','denied','synthetic')",
            (event,),
        )
        with pytest.raises(psycopg.errors.RaiseException):
            async with connection.transaction():
                await connection.execute(
                    "UPDATE management.audit_events SET reason='rewritten' WHERE id=%s",
                    (event,),
                )
        with pytest.raises(psycopg.errors.RaiseException):
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM management.audit_events WHERE id=%s", (event,)
                )


async def test_management_approval_guard_drift_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "ALTER TABLE management.approval_requests DROP CONSTRAINT approval_distinct_reviewer"
        )
    with pytest.raises(RuntimeError, match="management schema drift"):
        await runner.verify()
