"""OMS/TMS 授权底座仅在临时 PostgreSQL 中验证。"""

from __future__ import annotations

from pathlib import Path
import re
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
        ("0004_oms_skill_actions",),
        ("0005_remove_immutable_fact_function",),
        ("0006_remove_role_action_function",),
        ("0007_custom_role_school_owner",),
        ("0008_relocate_database_business_rules",),
        ("0009_approval_apply_payload",),
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


async def test_management_forward_migration_removes_immutable_fact_function(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        function = await (
            await connection.execute("SELECT to_regprocedure('management.reject_immutable_fact()')")
        ).fetchone()
        triggers = await (
            await connection.execute(
                "SELECT t.tgname FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=r.relnamespace "
                "WHERE n.nspname='management' AND r.relname IN "
                "('role_versions','role_actions','audit_events') AND NOT t.tgisinternal "
                "AND t.tgname LIKE '%append_only'"
            )
        ).fetchall()
    assert function == (None,)
    assert triggers == []


async def test_role_action_scope_is_verified_by_application_runner_without_trigger(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        trigger = await (
            await connection.execute(
                "SELECT to_regprocedure('management.validate_role_action()')"
            )
        ).fetchone()
        assert trigger == (None,)
        await connection.execute(
            "INSERT INTO management.role_actions"
            "(application,role_key,role_version,action_key) "
            "VALUES('oms','platform_security_admin',1,'ops.tenants.read')"
        )
    with pytest.raises(RuntimeError, match="role action scope"):
        await runner.verify()


async def test_oms_skill_actions_are_versioned_without_granting_existing_subjects(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    await runner.verify()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        actions = await (
            await connection.execute(
                "SELECT action_key,allowed_scope,sensitive FROM management.action_catalog "
                "WHERE application='oms' AND action_key LIKE 'ops.skills.%' ORDER BY action_key"
            )
        ).fetchall()
        roles = await (
            await connection.execute(
                "SELECT ra.role_key,ra.role_version,rv.scope_kind,ra.action_key "
                "FROM management.role_actions ra JOIN management.role_versions rv "
                "ON rv.application=ra.application AND rv.role_key=ra.role_key "
                "AND rv.version=ra.role_version "
                "WHERE ra.application='oms' AND ra.action_key LIKE 'ops.skills.%' "
                "ORDER BY ra.role_key,ra.action_key"
            )
        ).fetchall()
        assignments = await (
            await connection.execute("SELECT count(*) FROM management.assignments")
        ).fetchone()
    assert actions == [
        ("ops.skills.grant", "school", True),
        ("ops.skills.manage", "platform", True),
        ("ops.skills.publish", "platform", True),
        ("ops.skills.read", "platform", False),
        ("ops.skills.review", "platform", True),
    ]
    assert roles == [
        ("platform_config_admin", 2, "platform", "ops.skills.manage"),
        ("platform_config_admin", 2, "platform", "ops.skills.publish"),
        ("platform_config_admin", 2, "platform", "ops.skills.read"),
        ("platform_operator", 2, "school", "ops.skills.grant"),
        ("platform_security_admin", 2, "platform", "ops.skills.read"),
        ("platform_security_admin", 2, "platform", "ops.skills.review"),
    ]
    assert assignments == (0,)


async def test_oms_skill_action_catalog_drift_blocks_verification(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "UPDATE management.action_catalog SET status='retired' "
            "WHERE application='oms' AND action_key='ops.skills.review'"
        )
    with pytest.raises(RuntimeError, match="management schema drift"):
        await runner.verify()


async def test_oms_skill_migration_applies_for_single_database_runtime_owner(pg_dsn):
    runtime_dsn = single_database_user_dsn(pg_dsn)
    runner = MigrationRunner(runtime_dsn)
    await runner.apply()
    await runner.apply()
    await runner.verify()
    assert await runner.plan() == []


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


async def test_management_runner_rejects_illegal_action_catalog_transition_without_trigger(pg_dsn):
    await MigrationRunner(pg_dsn).apply()

    class IllegalCatalogRunner(MigrationRunner):
        def _management_migrations(self):
            return super()._management_migrations() + [
                (
                    "0007_illegal_action_change",
                    "SELECT set_config('app.management_app','oms',true); "
                    "UPDATE management.action_catalog SET sensitive=true "
                    "WHERE application='oms' AND action_key='ops.providers.read';",
                )
            ]

    with pytest.raises(RuntimeError, match="action catalog transition"):
        await IllegalCatalogRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT sensitive FROM management.action_catalog "
                "WHERE application='oms' AND action_key='ops.providers.read'"
            )
        ).fetchone()
    assert row == (False,)
    await MigrationRunner(pg_dsn).verify()


async def test_management_action_retirement_is_one_way_across_separate_migrations(pg_dsn):
    await MigrationRunner(pg_dsn).apply()

    class RetirementRunner(MigrationRunner):
        def _management_migrations(self):
            return super()._management_migrations() + [
                (
                    "0007_retire_synthetic_action",
                    "SELECT set_config('app.management_app','oms',true); "
                    "UPDATE management.action_catalog SET status='retired' "
                    "WHERE application='oms' AND action_key='ops.providers.read';",
                )
            ]

    retired = RetirementRunner(pg_dsn)
    await retired.apply()
    await retired.verify()

    class ResurrectionRunner(RetirementRunner):
        def _management_migrations(self):
            return super()._management_migrations() + [
                (
                    "0008_resurrect_synthetic_action",
                    "SELECT set_config('app.management_app','oms',true); "
                    "UPDATE management.action_catalog SET status='active' "
                    "WHERE application='oms' AND action_key='ops.providers.read';",
                )
            ]

    with pytest.raises(RuntimeError, match="action catalog transition"):
        await ResurrectionRunner(pg_dsn).apply()
    await retired.verify()


async def test_management_runner_rejects_role_template_mutation_without_db_trigger(pg_dsn):
    await MigrationRunner(pg_dsn).apply()

    class IllegalRoleRunner(MigrationRunner):
        def _management_migrations(self):
            return super()._management_migrations() + [
                (
                    "0007_illegal_role_mutation",
                    "SELECT set_config('app.management_app','tms',true); "
                    "UPDATE management.role_versions SET is_template=false "
                    "WHERE application='tms' AND role_key='school_auditor' AND version=1;",
                )
            ]

    with pytest.raises(RuntimeError, match="role catalog transition"):
        await IllegalRoleRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT is_template FROM management.role_versions "
                "WHERE application='tms' AND role_key='school_auditor' AND version=1"
            )
        ).fetchone()
    assert row == (True,)


async def test_management_runner_rejects_retired_action_on_new_role_version(pg_dsn):
    await MigrationRunner(pg_dsn).apply()

    class IllegalRoleActionRunner(MigrationRunner):
        def _management_migrations(self):
            return super()._management_migrations() + [
                (
                    "0007_illegal_retired_role_action",
                    "SELECT set_config('app.management_app','oms',true); "
                    "UPDATE management.action_catalog SET status='retired' "
                    "WHERE application='oms' AND action_key='ops.providers.read'; "
                    "INSERT INTO management.role_versions"
                    "(application,role_key,version,scope_kind,is_template) "
                    "VALUES('oms','synthetic_retired_reader',1,'platform',false); "
                    "INSERT INTO management.role_actions"
                    "(application,role_key,role_version,action_key) "
                    "VALUES('oms','synthetic_retired_reader',1,'ops.providers.read');",
                )
            ]

    with pytest.raises(RuntimeError, match="role catalog transition"):
        await IllegalRoleActionRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT status FROM management.action_catalog "
                "WHERE application='oms' AND action_key='ops.providers.read'"
            )
        ).fetchone()
    assert row == ("active",)


async def test_management_runner_rejects_action_added_to_published_role_version(pg_dsn):
    await MigrationRunner(pg_dsn).apply()

    class PublishedRoleMutationRunner(MigrationRunner):
        def _management_migrations(self):
            return super()._management_migrations() + [
                (
                    "0007_expand_published_role",
                    "SELECT set_config('app.management_app','oms',true); "
                    "INSERT INTO management.role_actions"
                    "(application,role_key,role_version,action_key) "
                    "VALUES('oms','platform_config_admin',1,'ops.skills.read');",
                )
            ]

    with pytest.raises(RuntimeError, match="role catalog transition"):
        await PublishedRoleMutationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        row = await (
            await connection.execute(
                "SELECT count(*) FROM management.role_actions "
                "WHERE application='oms' AND role_key='platform_config_admin' "
                "AND role_version=1 AND action_key='ops.skills.read'"
            )
        ).fetchone()
    assert row == (0,)


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


async def test_management_action_domain_check_reintroduction_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "ALTER TABLE management.action_catalog ADD CONSTRAINT action_catalog_check "
            "CHECK (action_key IS NOT NULL)"
        )
    with pytest.raises(RuntimeError, match="database-owned business rules"):
        await runner.verify()


async def test_role_action_scope_cannot_cross_platform_and_school(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO management.role_actions"
            "(application,role_key,role_version,action_key) "
            "VALUES('oms','platform_security_admin',1,'ops.tenants.read')"
        )
    with pytest.raises(RuntimeError, match="role action scope"):
        await runner.verify()


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
        await connection.execute(
            "UPDATE management.assignments SET status='revoked',revoked_at=now() WHERE id=%s",
            (assignment,),
        )
    with pytest.raises(RuntimeError, match="last administrator"):
        await MigrationRunner(pg_dsn).verify()


async def test_last_school_admin_cannot_be_removed_by_expiry_or_principal_disable(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    school, principal, assignment = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'allowed','synthetic')",
            (school,),
        )
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
        await connection.execute("UPDATE management.principals SET status='disabled' WHERE id=%s", (principal,))
    with pytest.raises(RuntimeError, match="last administrator"):
        await MigrationRunner(pg_dsn).verify()


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
        await connection.execute(
            "UPDATE management.assignments SET status='revoked',revoked_at=now() WHERE id=%s",
            (assignment,),
        )
    with pytest.raises(RuntimeError, match="last administrator"):
        await MigrationRunner(pg_dsn).verify()


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
            "VALUES('oms','platform_security_admin',3,'platform')"
        )
        original_assignment = uuid.uuid4()
        for principal, version, assignment in (
            (original, 1, original_assignment),
            (impostor, 3, uuid.uuid4()),
        ):
            await connection.execute(
                "INSERT INTO management.assignments"
                "(id,application,principal_id,role_key,role_version,scope_kind,"
                "valid_from,expires_at,command_id,created_by) "
                "VALUES(%s,'oms',%s,'platform_security_admin',%s,'platform',"
                "now()-interval '1 day',now()+interval '1 day',%s,'synthetic-approval')",
                (assignment, principal, version, uuid.uuid4()),
            )
        await connection.execute(
            "UPDATE management.assignments SET status='revoked',revoked_at=now() WHERE id=%s",
            (original_assignment,),
        )
    with pytest.raises(RuntimeError, match="last administrator"):
        await MigrationRunner(pg_dsn).verify()


async def test_management_governance_action_cannot_be_retired_in_place(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "UPDATE management.action_catalog SET status='retired' "
            "WHERE application='oms' AND action_key='ops.permissions.manage'"
        )
    with pytest.raises(RuntimeError, match="action catalog fact"):
        await MigrationRunner(pg_dsn).verify()


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
    assert granted == (1,)
    assert revoked == (1,)
    assert deleted == (1,)


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
        await connection.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'tms',%s,'school_admin',1,'school',%s,"
            "now()-interval '1 day',now()+interval '1 day',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, school_a, uuid.uuid4()),
        )
        await connection.execute(
            "INSERT INTO management.delegation_policies"
            "(id,application,principal_id,action_key,scope_kind,school_id,valid_from,expires_at) "
            "VALUES(%s,'tms',%s,'tenant.permissions.manage','school',%s,"
            "now()-interval '1 day',now()+interval '1 day')",
            (uuid.uuid4(), principal, school_b),
        )
    with pytest.raises(RuntimeError, match="delegation relation"):
        await MigrationRunner(pg_dsn).verify()


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
        await connection.execute(
            "INSERT INTO management.assignments"
            "(id,application,principal_id,role_key,role_version,scope_kind,"
            "valid_from,expires_at,command_id,created_by) "
            "VALUES(%s,'oms',%s,'platform_security_admin',1,'platform',"
            "now()-interval '1 day',now()+interval '1 day',%s,'synthetic-approval')",
            (uuid.uuid4(), principal, uuid.uuid4()),
        )
        await connection.execute(
            "INSERT INTO management.delegation_policies"
            "(id,application,principal_id,action_key,scope_kind,school_id,valid_from,expires_at) "
            "VALUES(%s,'oms',%s,'ops.credentials.manage','school',%s,"
            "now()-interval '1 day',now()+interval '1 day')",
            (uuid.uuid4(), principal, school),
        )
    with pytest.raises(RuntimeError, match="delegation relation"):
        await MigrationRunner(pg_dsn).verify()


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
        assert (
            await (
                await connection.execute(
                    "SELECT reason FROM management.audit_events WHERE id=%s", (event,)
                )
            ).fetchone()
        ) == ("synthetic",)
    source = Path(__file__).parents[1] / "src/deeptutor_enterprise/management"
    forbidden = re.compile(
        r"\b(?:UPDATE|DELETE\s+FROM)\s+management\."
        r"(?:role_versions|role_actions|audit_events)\b",
        re.IGNORECASE,
    )
    for path in source.rglob("*.py"):
        content = path.read_text(encoding="utf8")
        assert not forbidden.search(content), path
        if path.name != "roles.py":
            assert not re.search(r"\bINSERT\s+INTO\s+management\.role_actions\b", content, re.I), path


async def test_management_approval_guard_reintroduction_blocks_verify(pg_dsn):
    runner = MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as connection:
        await connection.execute(
            "ALTER TABLE management.approval_requests ADD CONSTRAINT approval_distinct_reviewer "
            "CHECK (status IS NOT NULL)"
        )
    with pytest.raises(RuntimeError, match="database-owned business rules"):
        await runner.verify()
