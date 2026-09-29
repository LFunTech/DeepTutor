import asyncio
import importlib.util
import uuid

import psycopg
import pytest

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio

EXPECTED_MIGRATIONS = [
    "0001_identity_sessions",
    "0002_account_profiles_devices",
    "0003_device_usage_precision",
    "0004_notebook_entries_categories",
    "0005_learning",
    "0006_reading",
    "0007_session_resources",
    "0008_cron",
    "0009_partner_runtime_status",
    "0010_matrix_store",
    "0011_marginnote_store",
    "0012_offline_import_stage",
    "0013_courses",
    "0014_externalized_runtime",
    "0015_remove_legacy_database_functions",
    "0016_relocate_database_business_rules",
]
EXPECTED_EXTENSION_MIGRATIONS = [
    "0001_federated_access",
    "0002_profile_permission_snapshots",
    "0003_revocation_state",
    "0004_audit_export_jobs",
    "0005_lifecycle_inbox",
    "0006_lifecycle_binding_proof",
    "0007_actor_candidate_terminal_state",
    "0008_webhook_authority",
    "0009_school_projection_management_read",
    "0010_school_database_onboarding",
    "0011_webhook_school_controls",
    "0012_remove_legacy_database_function",
    "0013_relocate_database_business_rules",
    "oms/0001_ledger_base",
    "oms/0002_grant_source",
    "oms/0003_grant_command_idempotency",
    "oms/0004_attempt_lifecycle",
    "oms/0005_command_result_summary",
    "oms/0006_append_only_facts",
    "oms/0007_supply_evidence",
    "oms/0008_quota_expiry",
    "oms/0009_entitlement_commands",
    "oms/0010_quota_adjustment",
    "oms/0011_school_binding",
    "oms/0012_school_binding_version_guard",
    "oms/0013_global_model_catalog",
    "oms/0014_skill_packages",
    "oms/0015_remove_fact_mutation_function",
    "oms/0016_skill_review_publication_fences",
    "oms/0017_relocate_database_business_rules",
    "oms/0018_tenant_service_access_grants",
    "oms/0019_provider_settings_configs",
    "management/0001_authorization_base",
    "management/0002_approval_delegation_guards",
    "management/0003_assignment_school_binding_version",
    "management/0004_oms_skill_actions",
    "management/0005_remove_immutable_fact_function",
    "management/0006_remove_role_action_function",
    "management/0007_custom_role_school_owner",
    "management/0008_relocate_database_business_rules",
]


BUSINESS_RULE_CHECK_NAMES = {
    ("eduplus2", "audit_events", "audit_events_result_check"),
    ("eduplus2", "audit_export_jobs", "audit_export_jobs_format_check"),
    ("eduplus2", "audit_export_jobs", "audit_export_jobs_status_check"),
    (
        "eduplus2",
        "external_client_registrations",
        "external_client_registrations_registered_by_surface_check",
    ),
    ("eduplus2", "external_client_registrations", "external_client_registrations_status_check"),
    ("eduplus2", "external_client_registrations", "external_client_registrations_provider_check"),
    ("eduplus2", "identity_bindings", "identity_bindings_status_check"),
    ("eduplus2", "identity_bindings", "identity_bindings_provider_check"),
    ("eduplus2", "lifecycle_actor_candidates", "lifecycle_actor_candidate_resolution_check"),
    ("eduplus2", "lifecycle_actor_candidates", "lifecycle_actor_candidate_status_check"),
    ("eduplus2", "lifecycle_inbox", "lifecycle_inbox_processing_status_check"),
    ("eduplus2", "lifecycle_targets", "lifecycle_allowed_requires_binding_version"),
    ("eduplus2", "lifecycle_targets", "lifecycle_targets_check3"),
    ("eduplus2", "lifecycle_targets", "lifecycle_targets_eligibility_check"),
    ("eduplus2", "permission_snapshots", "permission_snapshots_provider_check"),
    ("eduplus2", "profile_snapshots", "profile_snapshots_status_check"),
    ("eduplus2", "profile_snapshots", "profile_snapshots_provider_check"),
    ("eduplus2", "provider_clients", "provider_clients_status_check"),
    ("eduplus2", "revocation_events", "revocation_events_processing_status_check"),
    ("eduplus2", "revocation_events", "revocation_events_target_kind_check"),
    ("eduplus2", "revocation_state", "revocation_state_check"),
    ("eduplus2", "revocation_state", "revocation_state_check1"),
    ("eduplus2", "revocation_state", "revocation_state_check2"),
    ("eduplus2", "revocation_state", "revocation_state_check3"),
    ("eduplus2", "revocation_state", "revocation_state_check4"),
    ("eduplus2", "revocation_state", "revocation_state_target_kind_check"),
    ("eduplus2", "webhook_school_state", "webhook_school_state_eligibility_check"),
    ("enterprise", "courses", "courses_status_check"),
    ("enterprise", "cron_executions", "cron_executions_check1"),
    ("enterprise", "cron_executions", "cron_executions_status_check"),
    ("enterprise", "cron_jobs", "cron_jobs_check"),
    ("enterprise", "cron_jobs", "cron_jobs_last_status_check"),
    ("enterprise", "cron_jobs", "cron_jobs_schedule_kind_check"),
    ("enterprise", "executor_state", "executor_state_status_check"),
    ("enterprise", "marginnote_objects", "marginnote_objects_object_type_check"),
    ("enterprise", "mastery_interactions", "mastery_interactions_status_check"),
    ("enterprise", "mastery_path_leases", "mastery_path_leases_check"),
    ("enterprise", "mastery_path_leases", "mastery_path_leases_kind_check"),
    ("enterprise", "mastery_path_operations", "mastery_path_operations_check1"),
    ("enterprise", "mastery_path_operations", "mastery_path_operations_status_check"),
    ("enterprise", "mastery_topic_meta", "mastery_topic_meta_status_check"),
    ("enterprise", "mastery_topic_sources", "mastery_topic_sources_check"),
    ("enterprise", "mastery_topic_sources", "mastery_topic_sources_kind_check"),
    ("enterprise", "matrix_device_trust_state", "matrix_device_trust_state_state_check"),
    ("enterprise", "messages", "messages_role_check"),
    ("enterprise", "notebook_entries", "notebook_entries_check"),
    ("enterprise", "notebook_entries", "notebook_entries_score_trend_check"),
    ("enterprise", "notebook_entries", "notebook_entries_source_check"),
    ("enterprise", "notebook_entries", "notebook_mastery_path_required"),
    ("enterprise", "operations", "operations_check"),
    ("enterprise", "operations", "operations_status_check"),
    ("enterprise", "partner_runtime_status", "partner_runtime_status_state_check"),
    ("enterprise", "reading_materials", "reading_materials_source_kind_check"),
    ("enterprise", "reading_materials", "reading_materials_status_check"),
    ("enterprise", "reading_materials", "reading_materials_check"),
    ("enterprise", "resource_cleanup_jobs", "resource_cleanup_jobs_state_check"),
    ("enterprise", "resource_objects", "resource_objects_retention_check"),
    ("enterprise", "resource_objects", "resource_objects_state_check"),
    ("enterprise", "runtime_audit_events", "runtime_audit_events_scope_kind_check"),
    ("enterprise", "runtime_policies", "runtime_policies_status_check"),
    ("enterprise", "runtime_policies", "runtime_policies_subject_kind_check"),
    ("enterprise", "runtime_settings", "runtime_settings_scope_kind_check"),
    ("enterprise", "runtime_settings", "runtime_settings_status_check"),
    ("enterprise", "secret_references", "secret_references_scope_kind_check"),
    ("enterprise", "secret_references", "secret_references_status_check"),
    ("enterprise", "session_objects", "session_objects_state_check"),
    ("enterprise", "session_references", "session_references_kind_check"),
    ("enterprise", "session_references", "session_references_source_kind_check"),
    ("enterprise", "tenants", "tenants_external_eligibility_check"),
    ("enterprise", "tenants", "tenants_provisioning_status_check"),
    ("enterprise", "tenants", "tenants_recovery_state_check"),
    ("enterprise", "turn_commands", "turn_commands_kind_check"),
    ("enterprise", "turns", "turns_status_check"),
    ("enterprise", "users", "users_preset_check"),
    ("enterprise", "users", "users_role_check"),
    ("management", "action_catalog", "action_catalog_allowed_scope_check"),
    ("management", "action_catalog", "action_catalog_application_check"),
    ("management", "action_catalog", "action_catalog_check"),
    ("management", "action_catalog", "action_catalog_check1"),
    ("management", "action_catalog", "action_catalog_status_check"),
    ("management", "approval_requests", "approval_distinct_reviewer"),
    ("management", "approval_requests", "approval_requests_application_check"),
    ("management", "approval_requests", "approval_requests_check"),
    ("management", "approval_requests", "approval_requests_operation_check"),
    ("management", "approval_requests", "approval_requests_status_check"),
    ("management", "assignments", "assignments_application_check"),
    ("management", "assignments", "assignments_check1"),
    ("management", "assignments", "assignments_check2"),
    ("management", "assignments", "assignments_school_binding_version_valid"),
    ("management", "assignments", "assignments_scope_kind_check"),
    ("management", "assignments", "assignments_status_check"),
    ("management", "audit_events", "audit_events_application_check"),
    ("management", "audit_events", "audit_events_check2"),
    ("management", "audit_events", "audit_events_result_check"),
    ("management", "delegation_policies", "delegation_policies_application_check"),
    ("management", "delegation_policies", "delegation_policies_check1"),
    ("management", "delegation_policies", "delegation_policies_scope_kind_check"),
    ("management", "delegation_policies", "delegation_policies_status_check"),
    ("management", "principals", "principals_application_check"),
    ("management", "principals", "principals_check"),
    ("management", "principals", "principals_status_check"),
    ("management", "role_versions", "role_versions_application_check"),
    ("management", "role_versions", "role_versions_check"),
    ("management", "role_versions", "role_versions_scope_kind_check"),
    ("oms", "attempt_evidence_events", "attempt_evidence_events_event_kind_check"),
    ("oms", "audit_events", "audit_events_result_check"),
    ("oms", "grant_commands", "grant_commands_result_check"),
    ("oms", "quota_grants", "quota_grants_acquisition_method_check"),
    ("oms", "quota_grants", "quota_grants_status_check"),
    ("oms", "school_bindings", "school_bindings_status_check"),
    ("oms", "school_bindings", "school_bindings_check"),
    ("oms", "service_definitions", "service_definitions_resource_category_check"),
    ("oms", "supply_lots", "supply_lots_status_check"),
    ("oms", "supply_lots", "supply_lots_verified_native"),
    ("oms", "tenant_service_entitlements", "tenant_service_entitlements_status_check"),
    ("oms", "usage_attempts", "usage_attempts_status_check"),
    ("oms", "usage_attempts", "usage_attempts_subject_kind_check"),
}


def module(name):
    assert importlib.util.find_spec("deeptutor_enterprise." + name) is not None, (
        "企业持久化组件尚未实现: " + name
    )
    return __import__("deeptutor_enterprise." + name, fromlist=["*"])


async def migrated(dsn):
    migration = module("migrations.runner")
    runner = migration.MigrationRunner(dsn)
    assert await runner.plan() == EXPECTED_MIGRATIONS + EXPECTED_EXTENSION_MIGRATIONS
    await runner.apply()
    await runner.verify()
    return runner


async def test_final_schema_has_no_database_owned_business_rules(pg_dsn):
    runner = await migrated(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        routines = await (
            await c.execute(
                """
                SELECT n.nspname,p.proname
                  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                 WHERE n.nspname = ANY(%s) AND p.prokind IN ('f','p')
                 ORDER BY n.nspname,p.proname
                """,
                (["enterprise", "eduplus2", "oms", "management"],),
            )
        ).fetchall()
        triggers = await (
            await c.execute(
                """
                SELECT n.nspname,r.relname,t.tgname
                  FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid
                  JOIN pg_namespace n ON n.oid=r.relnamespace
                 WHERE n.nspname = ANY(%s) AND NOT t.tgisinternal
                 ORDER BY n.nspname,r.relname,t.tgname
                """,
                (["enterprise", "eduplus2", "oms", "management"],),
            )
        ).fetchall()
        enum_types = await (
            await c.execute(
                """
                SELECT n.nspname,t.typname
                  FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                 WHERE n.nspname = ANY(%s) AND t.typtype='e'
                 ORDER BY n.nspname,t.typname
                """,
                (["enterprise", "eduplus2", "oms", "management"],),
            )
        ).fetchall()
        checks = await (
            await c.execute(
                """
                SELECT n.nspname,r.relname,co.conname,pg_get_constraintdef(co.oid,false)
                  FROM pg_constraint co JOIN pg_class r ON r.oid=co.conrelid
                  JOIN pg_namespace n ON n.oid=r.relnamespace
                 WHERE n.nspname = ANY(%s) AND co.contype='c'
                 ORDER BY n.nspname,r.relname,co.conname
                """,
                (["enterprise", "eduplus2", "oms", "management"],),
            )
        ).fetchall()

    assert routines == []
    assert triggers == []
    assert enum_types == []
    business_checks = [
        row
        for row in checks
        if "ANY (ARRAY" in row[3] or (row[0], row[1], row[2]) in BUSINESS_RULE_CHECK_NAMES
    ]
    assert business_checks == []


async def test_migrations_repeat_concurrent_and_runtime_ddl(pg_dsn):
    runner = await migrated(pg_dsn)
    await asyncio.gather(runner.apply(), runner.apply())
    assert await runner.plan() == []
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        role = await (
            await c.execute("SELECT rolname FROM pg_roles WHERE rolname='dt_enterprise_app'")
        ).fetchone()
        assert role is None
    pool = module("stores.postgres.connection").Database(
        single_database_user_dsn(pg_dsn), resource="test"
    )
    async with pool:
        scope = module("scope").TenantScope(str(uuid.uuid4()), "u1")
        async with pool.transaction(scope) as c:
            assert (await (await c.execute("SELECT current_user AS user")).fetchone())[
                "user"
            ].startswith("owner_")


async def test_eduplus2_extension_catalog_drift_blocks_verify(pg_dsn):
    runner = await migrated(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("ALTER TABLE eduplus2.audit_export_jobs DISABLE ROW LEVEL SECURITY")
    with pytest.raises(RuntimeError, match="eduplus2 schema drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="eduplus2 schema drift"):
        await runner.apply()


async def test_webhook_binding_version_catalog_drift_blocks_verify(pg_dsn):
    runner = await migrated(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("ALTER TABLE eduplus2.webhook_school_state DROP COLUMN binding_version")
    with pytest.raises(RuntimeError, match="eduplus2 schema drift"):
        await runner.verify()


async def test_webhook_external_school_uniqueness_drift_blocks_verify(pg_dsn):
    runner = await migrated(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("DROP INDEX enterprise.enterprise_external_tid_unique")
    with pytest.raises(RuntimeError, match="eduplus2 schema drift"):
        await runner.verify()


async def test_provider_client_maintenance_values_are_verified(pg_dsn):
    runner = await migrated(pg_dsn)
    tenant_id = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) VALUES(%s,'not_required','synthetic')",
            (tenant_id,),
        )
        await c.execute(
            "INSERT INTO eduplus2.provider_clients"
            "(tenant_id,client_id,secret_ref,issuer,base_url,redirect_uri,status) "
            "VALUES(%s,'client-a','secret://a','https://issuer','https://base',"
            "'https://redirect','future-status')",
            (tenant_id,),
        )
    with pytest.raises(RuntimeError, match="provider client"):
        await runner.verify()


async def test_lifecycle_migration_failure_rolls_back_inbox_and_history(pg_dsn):
    runner_type = module("migrations.runner").MigrationRunner

    class FailingRunner(runner_type):
        def _extension_migrations(self):
            return super()._extension_migrations() + [("0008_forced_failure", "SELECT 1/0;")]

    with pytest.raises(psycopg.errors.DivisionByZero):
        await FailingRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        inbox = await (await c.execute("SELECT to_regclass('eduplus2.lifecycle_inbox')")).fetchone()
        history = await (
            await c.execute("SELECT to_regclass('eduplus2.schema_history')")
        ).fetchone()
    assert inbox == (None,)
    assert history == (None,)
    await runner_type(pg_dsn).apply()
    await runner_type(pg_dsn).verify()


async def test_lifecycle_migration_preserves_legacy_fixed_school_eligibility(pg_dsn):
    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner as CoreRunner

    runner_type = module("migrations.runner").MigrationRunner
    await CoreRunner(pg_dsn).apply()
    school_id = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "INSERT INTO enterprise.tenants(id,external_eligibility,auth_epoch) "
            "VALUES(%s,'not_required','synthetic-epoch')",
            (school_id,),
        )
    await runner_type(pg_dsn).apply()
    await runner_type(pg_dsn).verify()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        tenant = await (
            await c.execute(
                "SELECT external_eligibility,external_tid,external_version "
                "FROM enterprise.tenants WHERE id=%s",
                (school_id,),
            )
        ).fetchone()
        target_count = await (
            await c.execute("SELECT count(*) FROM eduplus2.lifecycle_targets")
        ).fetchone()
    assert tenant == ("not_required", None, 1)
    assert target_count == (0,)


async def test_lifecycle_due_proof_has_expiry_index(pg_dsn):
    runner = module("migrations.runner").MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        indexes = await (
            await c.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname='eduplus2' "
                "AND tablename='lifecycle_targets'"
            )
        ).fetchall()
    assert ("eduplus2_lifecycle_targets_expiry",) in indexes


async def test_lifecycle_index_drift_blocks_verify(pg_dsn):
    runner = module("migrations.runner").MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("DROP INDEX eduplus2.eduplus2_lifecycle_targets_expiry")
    with pytest.raises(RuntimeError, match="lifecycle indexes"):
        await runner.verify()


async def test_lifecycle_binding_proof_column_drift_blocks_verify(pg_dsn):
    runner = module("migrations.runner").MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("ALTER TABLE eduplus2.lifecycle_targets DROP COLUMN binding_version")
    with pytest.raises(RuntimeError, match="lifecycle binding proof"):
        await runner.verify()


async def test_lifecycle_actor_terminal_column_drift_blocks_verify(pg_dsn):
    runner = module("migrations.runner").MigrationRunner(pg_dsn)
    await runner.apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("ALTER TABLE eduplus2.lifecycle_actor_candidates DROP COLUMN resolved_at")
    with pytest.raises(RuntimeError, match="actor terminal state"):
        await runner.verify()


async def test_drift_blocks_start(pg_dsn):
    runner = await migrated(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("UPDATE enterprise.schema_history SET checksum='changed'")
    with pytest.raises(RuntimeError, match="drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="drift"):
        await runner.apply()


async def test_scope_reuse_cancel_rollback_and_missing_scope(pg_dsn):
    await migrated(pg_dsn)
    mod = module("stores.postgres.connection")
    Scope = module("scope").TenantScope
    async with mod.Database(single_database_user_dsn(pg_dsn), resource="test", max_size=1) as db:
        a, b = Scope(str(uuid.uuid4()), "same-user"), Scope(str(uuid.uuid4()), "same-user")

        async def settings(scope):
            async with db.transaction(scope) as c:
                return await (
                    await c.execute(
                        "SELECT current_setting('app.tenant_id') AS tenant,current_setting('app.user_id') AS owner"
                    )
                ).fetchone()

        assert tuple((await settings(a)).values()) == (a.tenant_id, "same-user")

        async def cancelled():
            async with db.transaction(a) as c:
                await c.execute("SELECT pg_sleep(5)")

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.1):
                await cancelled()
        assert tuple((await settings(b)).values()) == (b.tenant_id, "same-user")
        with pytest.raises(ValueError, match="scope"):
            async with db.transaction(None):
                pass
        async with db.pool.connection() as c:
            result = await (
                await c.execute("SELECT nullif(current_setting('app.tenant_id',true),'') AS tenant")
            ).fetchone()
            assert result["tenant"] is None
            assert await (await c.execute("SELECT * FROM enterprise.sessions")).fetchall() == []


async def test_runtime_rejects_owner_or_superuser(pg_dsn):
    await migrated(pg_dsn)
    with pytest.raises(RuntimeError, match="restricted"):
        async with module("stores.postgres.connection").Database(pg_dsn, resource="test"):
            pass


@pytest.mark.parametrize(
    "mutation",
    [
        "ALTER TABLE enterprise.tenants DISABLE ROW LEVEL SECURITY",
        "ALTER TABLE enterprise.turns DISABLE ROW LEVEL SECURITY",
        "DROP POLICY owner_scope ON enterprise.messages",
        "ALTER POLICY tenant_scope ON enterprise.sessions USING (true) WITH CHECK (true)",
        "DROP POLICY owner_scope ON enterprise.sessions; CREATE POLICY owner_scope ON enterprise.sessions USING (owner_id=current_setting('app.user_id')) WITH CHECK (owner_id=current_setting('app.user_id'))",
        "CREATE POLICY extra_bypass ON enterprise.sessions USING (true) WITH CHECK (true)",
        "DO $$ DECLARE n text; BEGIN SELECT conname INTO n FROM pg_constraint WHERE conrelid='enterprise.messages'::regclass AND confrelid='enterprise.sessions'::regclass; EXECUTE format('ALTER TABLE enterprise.messages DROP CONSTRAINT %I',n); END $$",
        "DROP INDEX enterprise.one_active_turn",
        "ALTER TABLE enterprise.turns ADD CONSTRAINT turns_status_check CHECK(status IS NOT NULL)",
        "ALTER TABLE enterprise.sessions ALTER COLUMN owner_id DROP NOT NULL",
        "ALTER TABLE enterprise.turns DISABLE TRIGGER ALL",
        "DROP TABLE enterprise.turn_commands",
        "ALTER POLICY tenant_scope ON enterprise.sessions WITH CHECK (true)",
        "DROP INDEX enterprise.one_active_turn; CREATE INDEX one_active_turn ON enterprise.turns(tenant_id,session_id) WHERE status IN ('queued','running','waiting_input')",
        "ALTER TABLE enterprise.turn_commands DROP CONSTRAINT turn_commands_pkey; ALTER TABLE enterprise.turn_commands ADD PRIMARY KEY(owner_id,turn_id,command_id)",
        "DO $$ DECLARE n text; BEGIN SELECT conname INTO n FROM pg_constraint WHERE conrelid='enterprise.messages'::regclass AND confrelid='enterprise.sessions'::regclass; EXECUTE format('ALTER TABLE enterprise.messages DROP CONSTRAINT %I',n); EXECUTE format('ALTER TABLE enterprise.messages ADD CONSTRAINT %I FOREIGN KEY(tenant_id,owner_id,session_id) REFERENCES enterprise.sessions(tenant_id,owner_id,id) ON DELETE CASCADE NOT VALID',n); END $$",
    ],
)
async def test_real_catalog_drift_blocks_verify_even_when_history_unchanged(pg_dsn, mutation):
    runner = await migrated(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(mutation, prepare=False)
    with pytest.raises(RuntimeError, match="drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="drift"):
        await runner.apply()


async def test_verify_catalog_works_without_migration_privileges(pg_dsn):
    await migrated(pg_dsn)
    runner = module("migrations.runner").MigrationRunner(single_database_user_dsn(pg_dsn))
    await runner.verify()


@pytest.mark.parametrize(
    "privilege,path",
    [
        ("SUPERUSER", "set"),
        ("BYPASSRLS", "set"),
        ("CREATEROLE", "set"),
        ("CREATEDB", "set"),
        ("BYPASSRLS", "admin"),
    ],
)
async def test_runtime_rejects_indirect_privileged_role_paths(pg_dsn, privilege, path):
    await migrated(pg_dsn)
    suffix = uuid.uuid4().hex
    login, middle, target = (name + suffix for name in ("login_", "middle_", "target_"))
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            psycopg.sql.SQL("CREATE ROLE {} LOGIN NOINHERIT").format(psycopg.sql.Identifier(login))
        )
        attribute = (
            privilege
            if privilege in ("SUPERUSER", "BYPASSRLS", "CREATEROLE", "CREATEDB")
            else "NOLOGIN"
        )
        await c.execute(
            psycopg.sql.SQL("CREATE ROLE {} {}").format(
                psycopg.sql.Identifier(target), psycopg.sql.SQL(attribute)
            )
        )
        if privilege == "table_owner":
            await c.execute(
                psycopg.sql.SQL("ALTER TABLE enterprise.sessions OWNER TO {}").format(
                    psycopg.sql.Identifier(target)
                )
            )
        elif privilege == "schema_owner":
            await c.execute(
                psycopg.sql.SQL("ALTER SCHEMA enterprise OWNER TO {}").format(
                    psycopg.sql.Identifier(target)
                )
            )
        if path == "mixed":
            await c.execute(
                psycopg.sql.SQL("CREATE ROLE {} NOINHERIT").format(psycopg.sql.Identifier(middle))
            )
            await c.execute(
                psycopg.sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE").format(
                    psycopg.sql.Identifier(middle), psycopg.sql.Identifier(login)
                )
            )
            await c.execute(
                psycopg.sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE").format(
                    psycopg.sql.Identifier(target), psycopg.sql.Identifier(middle)
                )
            )
        else:
            options = {
                "set": "INHERIT FALSE, SET TRUE",
                "inherit": "INHERIT TRUE, SET FALSE",
                "admin": "INHERIT FALSE, SET FALSE, ADMIN TRUE",
            }[path]
            await c.execute(
                psycopg.sql.SQL("GRANT {} TO {} WITH {}").format(
                    psycopg.sql.Identifier(target),
                    psycopg.sql.Identifier(login),
                    psycopg.sql.SQL(options),
                )
            )
    with pytest.raises(RuntimeError, match="restricted"):
        async with module("stores.postgres.connection").Database(
            pg_dsn.replace("user=postgres", f"user={login}"), resource="test"
        ):
            pass


async def test_runtime_allows_nonprivileged_memberships_and_inaccessible_roles(pg_dsn):
    await migrated(pg_dsn)
    suffix = uuid.uuid4().hex
    login, target = "safe_" + suffix, "unavailable_" + suffix
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            psycopg.sql.SQL("CREATE ROLE {} LOGIN NOINHERIT").format(psycopg.sql.Identifier(login))
        )
        await c.execute(
            psycopg.sql.SQL("CREATE ROLE {} BYPASSRLS").format(psycopg.sql.Identifier(target))
        )
        await c.execute(
            psycopg.sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET FALSE, ADMIN FALSE").format(
                psycopg.sql.Identifier(target), psycopg.sql.Identifier(login)
            )
        )
    async with module("stores.postgres.connection").Database(
        pg_dsn.replace("user=postgres", f"user={login}"), resource="test"
    ) as db:
        scope = module("scope").TenantScope(str(uuid.uuid4()), "u1")
        async with db.transaction(scope) as c:
            assert (await (await c.execute("SELECT 42 AS answer")).fetchone())["answer"] == 42


@pytest.mark.parametrize("already_applied", [False, True])
async def test_migration_sql_failure_rolls_back_ddl_data_and_history(pg_dsn, already_applied):
    base = module("migrations.runner").MigrationRunner
    if already_applied:
        await migrated(pg_dsn)

    class FailingArtifactRunner(base):
        def _migrations(self):
            return super()._migrations() + [
                (
                    "0008_failure",
                    """
                CREATE TABLE enterprise.uncommitted_probe (id integer PRIMARY KEY);
                INSERT INTO enterprise.executor_state(resource,execution_id,status)
                    VALUES ('must-rollback','00000000-0000-0000-0000-000000000001','active');
                SELECT 1/0;
            """,
                )
            ]

    with pytest.raises(psycopg.errors.DivisionByZero):
        await FailingArtifactRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        assert (
            await (await c.execute("SELECT to_regclass('enterprise.uncommitted_probe')")).fetchone()
        )[0] is None
        if already_applied:
            assert (
                await (
                    await c.execute(
                        "SELECT resource FROM enterprise.executor_state WHERE resource='must-rollback'"
                    )
                ).fetchall()
                == []
            )
            assert await (
                await c.execute("SELECT version FROM enterprise.schema_history ORDER BY version")
            ).fetchall() == [(version,) for version in EXPECTED_MIGRATIONS]
        else:
            assert (await (await c.execute("SELECT to_regnamespace('enterprise')")).fetchone())[
                0
            ] is None
    await base(pg_dsn).apply()
    await base(pg_dsn).verify()


async def test_forged_success_history_without_real_schema_is_not_verified(pg_dsn):
    import hashlib

    runner = module("migrations.runner").MigrationRunner(pg_dsn)
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute("CREATE SCHEMA enterprise")
        await c.execute(
            "CREATE TABLE enterprise.schema_history(version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for version, artifact in runner._migrations():
            await c.execute(
                "INSERT INTO enterprise.schema_history(version,checksum) VALUES(%s,%s)",
                (version, hashlib.sha256(artifact.encode()).hexdigest()),
            )
    with pytest.raises(RuntimeError, match="drift"):
        await runner.verify()
    with pytest.raises(RuntimeError, match="drift"):
        await runner.apply()


async def test_runtime_rejects_privileged_session_user_hidden_by_startup_role(pg_dsn):
    await migrated(pg_dsn)
    safe_role = "safe_" + uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            psycopg.sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(psycopg.sql.Identifier(safe_role))
        )
    dsn = psycopg.conninfo.make_conninfo(pg_dsn, options=f"-c role={safe_role}")
    with pytest.raises(RuntimeError, match="restricted"):
        async with module("stores.postgres.connection").Database(dsn, resource="test"):
            pass
