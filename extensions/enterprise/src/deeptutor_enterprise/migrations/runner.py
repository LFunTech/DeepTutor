"""企业扩展迁移：core schema + 独立 EduPlus2 extension schema。"""

from __future__ import annotations

from datetime import datetime
import hashlib
from importlib.resources import files
from uuid import UUID

import psycopg

from deeptutor.persistence.postgres.migrations.runner import MigrationRunner as CoreMigrationRunner

_EXTENSION_SCHEMA = "eduplus2"
_EXTENSION_PACKAGE = "deeptutor_enterprise.eduplus2.migrations"
_EXTENSION_LOCK_ID = 0x44544544555032
_OMS_SCHEMA = "oms"
_OMS_PACKAGE = "deeptutor_enterprise.oms.migrations"
_OMS_LOCK_ID = 0x44544F4D5331
_MANAGEMENT_SCHEMA = "management"
_MANAGEMENT_PACKAGE = "deeptutor_enterprise.management.migrations"
_MANAGEMENT_LOCK_ID = 0x44544D474D5431


_BUSINESS_RULE_CHECK_NAMES = frozenset(
    {
        ("eduplus2", "audit_events", "audit_events_result_check"),
        ("eduplus2", "audit_export_jobs", "audit_export_jobs_format_check"),
        ("eduplus2", "audit_export_jobs", "audit_export_jobs_status_check"),
        (
            "eduplus2",
            "external_client_registrations",
            "external_client_registrations_registered_by_surface_check",
        ),
        ("eduplus2", "external_client_registrations", "external_client_registrations_status_check"),
        (
            "eduplus2",
            "external_client_registrations",
            "external_client_registrations_provider_check",
        ),
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
)
_BUSINESS_RULE_SCHEMAS = ("enterprise", _EXTENSION_SCHEMA, _OMS_SCHEMA, _MANAGEMENT_SCHEMA)

# 与 core runner 一致：G1 起新迁移不再向固定 dt_enterprise_app 角色授权；
# 已应用旧 role-grant SQL 的扩展 schema 允许通过 catalog/RLS 校验继续验证。
_EXTENSION_LEGACY_ROLE_GRANT_CHECKSUMS = {
    "0001_federated_access": frozenset(
        {
            "96f03a43b07992cdf3436124aceffb6726470597f1ae9ead1b65193166915b25",
        }
    ),
    "0002_profile_permission_snapshots": frozenset(
        {
            "d5e2db087780e5860e3d38b8c809babf2fc4ee42e5c43031f283ed8a3da84c09",
        }
    ),
    "0003_revocation_state": frozenset(
        {
            "ec55a94bc1be0d4a50477819aa79a8fa32d9ca69f5ec34e6fe93b45774d1fcad",
        }
    ),
    "0004_audit_export_jobs": frozenset(
        {
            "56aa1155679764ef7c4daf0f014dcca69da6049ff76f43e86f329fd5c0982fc8",
        }
    ),
}


def _extension_accepted_checksums(expected):
    return {
        version: frozenset({digest, *_EXTENSION_LEGACY_ROLE_GRANT_CHECKSUMS.get(version, ())})
        for version, digest in expected.items()
    }


class MigrationRunner(CoreMigrationRunner):
    """保留 core runner 语义，并追加 EduPlus2 与 OMS 独立 schema 迁移。"""

    async def _verify_no_database_owned_business_rules(self, c, schema: str) -> None:
        routines = await (
            await c.execute(
                "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname=%s AND p.prokind IN ('f','p')",
                (schema,),
            )
        ).fetchall()
        triggers = await (
            await c.execute(
                "SELECT r.relname,t.tgname FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=r.relnamespace "
                "WHERE n.nspname=%s AND NOT t.tgisinternal",
                (schema,),
            )
        ).fetchall()
        enum_types = await (
            await c.execute(
                "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace "
                "WHERE n.nspname=%s AND t.typtype='e'",
                (schema,),
            )
        ).fetchall()
        checks = await (
            await c.execute(
                "SELECT n.nspname,r.relname,co.conname,pg_get_constraintdef(co.oid,false) "
                "FROM pg_constraint co JOIN pg_class r ON r.oid=co.conrelid "
                "JOIN pg_namespace n ON n.oid=r.relnamespace "
                "WHERE n.nspname=%s AND co.contype='c'",
                (schema,),
            )
        ).fetchall()
        business_checks = [
            row
            for row in checks
            if "ANY (ARRAY" in row[3] or (row[0], row[1], row[2]) in _BUSINESS_RULE_CHECK_NAMES
        ]
        if routines or triggers or enum_types or business_checks:
            raise RuntimeError(f"{schema} schema drift: database-owned business rules remain")

    def _extension_migrations(self):
        return [
            (p.name[:-4], p.read_text(encoding="utf8"))
            for p in sorted(files(_EXTENSION_PACKAGE).iterdir(), key=lambda p: p.name)
            if p.name.endswith(".sql")
        ]

    async def _extension_history(self, c):
        exists = await (
            await c.execute("SELECT to_regclass(%s)", (f"{_EXTENSION_SCHEMA}.schema_history",))
        ).fetchone()
        if not exists[0]:
            return {}
        return dict(
            await (
                await c.execute(
                    f"SELECT version,checksum FROM {_EXTENSION_SCHEMA}.schema_history ORDER BY version"
                )
            ).fetchall()
        )

    async def _extension_plan(self, c):
        history = await self._extension_history(c)
        migrations = self._extension_migrations()
        expected = {
            version: hashlib.sha256(sql.encode()).hexdigest() for version, sql in migrations
        }
        accepted = _extension_accepted_checksums(expected)
        if any(
            version not in accepted or digest not in accepted[version]
            for version, digest in history.items()
        ):
            raise RuntimeError("eduplus2 schema history drift or incompatible version")
        applied = [version for version, _ in migrations if version in history]
        if applied != [version for version, _ in migrations][: len(applied)]:
            raise RuntimeError("eduplus2 schema history drift: non-contiguous versions")
        return [(version, sql) for version, sql in migrations if version not in history]

    async def _verify_extension_schema(self, c):
        if await self._extension_plan(c):
            raise RuntimeError("eduplus2 schema migration required; run maintenance apply")
        rows = await (
            await c.execute(
                """
                SELECT r.relname,r.relkind,r.relrowsecurity,r.relforcerowsecurity
                  FROM pg_class r JOIN pg_namespace n ON n.oid=r.relnamespace
                 WHERE n.nspname=%s AND r.relkind IN ('r','p','v','m','f')
                """,
                (_EXTENSION_SCHEMA,),
            )
        ).fetchall()
        tables = {row[0]: row[1:] for row in rows}
        expected = {
            "schema_history": ("r", False, False),
            "provider_clients": ("r", True, False),
            "external_client_registrations": ("r", True, False),
            "identity_bindings": ("r", True, False),
            "resolve_cache": ("r", True, False),
            "profile_snapshots": ("r", True, False),
            "permission_snapshots": ("r", True, False),
            "revocation_events": ("r", True, False),
            "revocation_state": ("r", True, False),
            "lifecycle_inbox": ("r", True, True),
            "lifecycle_targets": ("r", True, True),
            "lifecycle_actor_candidates": ("r", True, True),
            "webhook_school_state": ("r", True, True),
            "webhook_school_controls": ("r", True, True),
            "webhook_school_control_commands": ("r", True, True),
            "audit_export_jobs": ("r", True, False),
            "audit_events": ("r", True, False),
        }
        if tables != expected:
            raise RuntimeError("eduplus2 schema drift: table set or RLS flags differ")
        policies = await (
            await c.execute(
                """
                SELECT r.relname,p.polname,pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid)
                  FROM pg_policy p JOIN pg_class r ON r.oid=p.polrelid
                  JOIN pg_namespace n ON n.oid=r.relnamespace
                 WHERE n.nspname=%s
                """,
                (_EXTENSION_SCHEMA,),
            )
        ).fetchall()
        tenant_expr = (
            "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"
        )
        actual = {(row[0], row[1], row[2], row[3]) for row in policies}
        expected_policies = {
            (table, "tenant_scope", tenant_expr, tenant_expr)
            for table in expected
            if table != "schema_history"
        }
        expected_policies.add(
            (
                "webhook_school_state",
                "school_projection_read",
                "(school_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
                None,
            )
        )
        expected_policies.add(
            (
                "webhook_school_controls",
                "school_control_read",
                "(school_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
                None,
            )
        )
        if actual != expected_policies:
            raise RuntimeError("eduplus2 schema drift: tenant RLS policies differ")
        provider_clients = await (
            await c.execute(
                "SELECT client_id,secret_ref,issuer,base_url,redirect_uri,enabled,version,status "
                "FROM eduplus2.provider_clients"
            )
        ).fetchall()
        if any(
            not all(isinstance(value, str) and value.strip() for value in row[:5])
            or type(row[5]) is not bool
            or type(row[6]) is not int
            or row[6] < 1
            or row[7] not in {"active", "rotating", "revoked", "disabled"}
            for row in provider_clients
        ):
            raise RuntimeError("eduplus2 provider client fact is invalid")
        indexes = await (
            await c.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname='eduplus2' "
                "AND tablename IN ('lifecycle_inbox','lifecycle_targets',"
                "'lifecycle_actor_candidates','webhook_school_state')"
            )
        ).fetchall()
        required_lifecycle_indexes = {
            "eduplus2_lifecycle_inbox_target_pending",
            "eduplus2_lifecycle_targets_retry",
            "eduplus2_lifecycle_targets_expiry",
            "eduplus2_lifecycle_actor_candidates_school",
            "eduplus2_webhook_school_state_school",
        }
        if not required_lifecycle_indexes.issubset({row[0] for row in indexes}):
            raise RuntimeError("eduplus2 schema drift: lifecycle indexes missing")
        webhook_columns = await (
            await c.execute(
                "SELECT a.attname,a.atttypid::regtype::text,a.attnotnull "
                "FROM pg_attribute a "
                "WHERE a.attrelid='eduplus2.webhook_school_state'::regclass "
                "AND a.attnum>0 AND NOT a.attisdropped"
            )
        ).fetchall()
        required_webhook_columns = {
            "tenant_id": ("uuid", True),
            "external_tenant_id": ("bigint", True),
            "external_app_id": ("bigint", True),
            "school_id": ("uuid", True),
            "school_code": ("text", True),
            "binding_version": ("bigint", True),
            "generation": ("bigint", True),
            "eligibility": ("text", True),
            "external_subscription_id": ("bigint", True),
            "last_event_id": ("text", True),
            "onboarding_event_id": ("text", False),
            "onboarding_completed_at": ("timestamp with time zone", False),
        }
        actual_webhook_columns = {
            name: (data_type, not_null) for name, data_type, not_null in webhook_columns
        }
        if any(
            actual_webhook_columns.get(name) != expected
            for name, expected in required_webhook_columns.items()
        ):
            raise RuntimeError("eduplus2 schema drift: webhook projection columns differ")
        onboarding_constraint = await (
            await c.execute(
                "SELECT convalidated FROM pg_constraint "
                "WHERE conrelid='eduplus2.webhook_school_state'::regclass "
                "AND conname='webhook_school_onboarding_pair' AND contype='c'"
            )
        ).fetchone()
        if onboarding_constraint != (True,):
            raise RuntimeError("eduplus2 schema drift: school onboarding constraint missing")
        school_unique_index = await (
            await c.execute(
                "SELECT i.indisunique,i.indisvalid,pg_get_expr(i.indpred,i.indrelid) "
                "FROM pg_index i JOIN pg_class r ON r.oid=i.indexrelid "
                "WHERE r.oid=to_regclass('enterprise.enterprise_external_tid_unique') "
                "AND i.indrelid='enterprise.tenants'::regclass"
            )
        ).fetchone()
        if school_unique_index != (True, True, "(external_tid IS NOT NULL)"):
            raise RuntimeError("eduplus2 schema drift: external school uniqueness missing")
        proof_column = await (
            await c.execute(
                "SELECT a.atttypid='bigint'::regtype,a.attnotnull "
                "FROM pg_attribute a "
                "WHERE a.attrelid='eduplus2.lifecycle_targets'::regclass "
                "AND a.attname='binding_version' AND NOT a.attisdropped"
            )
        ).fetchone()
        if proof_column != (True, True):
            raise RuntimeError("eduplus2 schema drift: lifecycle binding proof missing")
        actor_column = await (
            await c.execute(
                "SELECT a.atttypid='timestamp with time zone'::regtype "
                "FROM pg_attribute a "
                "WHERE a.attrelid='eduplus2.lifecycle_actor_candidates'::regclass "
                "AND a.attname='resolved_at' AND NOT a.attisdropped"
            )
        ).fetchone()
        actor_trigger = await (
            await c.execute(
                "SELECT tgenabled FROM pg_trigger "
                "WHERE tgrelid='eduplus2.lifecycle_actor_candidates'::regclass "
                "AND tgname='guard_lifecycle_actor_candidate' AND NOT tgisinternal"
            )
        ).fetchone()
        actor_function = await (
            await c.execute("SELECT to_regprocedure('eduplus2.guard_lifecycle_actor_candidate()')")
        ).fetchone()
        if actor_column != (True,) or actor_trigger is not None or actor_function != (None,):
            raise RuntimeError("eduplus2 schema drift: lifecycle actor terminal state missing")
        await self._verify_no_database_owned_business_rules(c, _EXTENSION_SCHEMA)

    def _oms_migrations(self):
        return [
            (p.name[:-4], p.read_text(encoding="utf8"))
            for p in sorted(files(_OMS_PACKAGE).iterdir(), key=lambda p: p.name)
            if p.name.endswith(".sql")
        ]

    async def _oms_history(self, c):
        exists = await (
            await c.execute("SELECT to_regclass(%s)", (f"{_OMS_SCHEMA}.schema_history",))
        ).fetchone()
        if not exists[0]:
            return {}
        return dict(
            await (
                await c.execute("SELECT version,checksum FROM oms.schema_history ORDER BY version")
            ).fetchall()
        )

    async def _oms_plan(self, c):
        history = await self._oms_history(c)
        migrations = self._oms_migrations()
        expected = {
            version: hashlib.sha256(sql.encode()).hexdigest() for version, sql in migrations
        }
        if any(
            version not in expected or digest != expected[version]
            for version, digest in history.items()
        ):
            raise RuntimeError("oms schema history drift or incompatible version")
        applied = [version for version, _ in migrations if version in history]
        if applied != [version for version, _ in migrations][: len(applied)]:
            raise RuntimeError("oms schema history drift: non-contiguous versions")
        return [(version, sql) for version, sql in migrations if version not in history]

    async def _oms_school_binding_snapshot(self, c):
        exists = await (await c.execute("SELECT to_regclass('oms.school_bindings')")).fetchone()
        if exists[0] is None:
            return {}
        rows = await (
            await c.execute(
                "SELECT tenant_id,eduplus_tenant_id,status,version,verified_at,"
                "verified_by,source_ref FROM oms.school_bindings"
            )
        ).fetchall()
        return {row[0]: row[1:] for row in rows}

    @staticmethod
    def _validate_oms_school_binding_facts(bindings):
        for current in bindings.values():
            external_id, status, version, verified_at, verified_by, source_ref = current
            complete_proof = verified_at is not None and bool(verified_by and verified_by.strip())
            absent_proof = verified_at is None and verified_by is None
            if (
                external_id <= 0
                or status not in {"pending", "verified", "revoked"}
                or type(version) is not int
                or version < 1
                or (status == "verified" and not complete_proof)
                or (status != "verified" and not absent_proof)
                or not source_ref.strip()
            ):
                raise RuntimeError("oms school binding fact is invalid")

    @staticmethod
    def _validate_oms_school_binding_transition(before, after):
        if before.keys() - after.keys():
            raise RuntimeError("oms school binding transition is invalid")
        try:
            MigrationRunner._validate_oms_school_binding_facts(after)
        except RuntimeError as exc:
            raise RuntimeError("oms school binding transition is invalid") from exc
        for tenant_id, current in after.items():
            version = current[2]
            old = before.get(tenant_id)
            if old is None:
                if version != 1:
                    raise RuntimeError("oms school binding transition is invalid")
                continue
            old_version = old[2]
            material_changed = (current[0], current[1], *current[3:]) != (old[0], old[1], *old[3:])
            if version != old_version + int(material_changed):
                raise RuntimeError("oms school binding transition is invalid")

    async def _verify_oms_schema(self, c):
        if await self._oms_plan(c):
            raise RuntimeError("oms schema migration required; run maintenance apply")
        rows = await (
            await c.execute(
                """
                SELECT r.relname,r.relkind,r.relrowsecurity,r.relforcerowsecurity
                  FROM pg_class r JOIN pg_namespace n ON n.oid=r.relnamespace
                 WHERE n.nspname='oms' AND r.relkind IN ('r','p','v','m','f')
                """
            )
        ).fetchall()
        tables = {row[0]: row[1:] for row in rows}
        tenant_tables = {
            "tenant_service_entitlements",
            "quota_grants",
            "grant_commitments",
            "usage_attempts",
            "attempt_allocations",
            "attempt_evidence_events",
            "entitlement_commands",
            "tenant_service_access_grants",
            "skill_revisions",
            "skill_publications",
            "skill_grants",
        }
        expected_tables = {
            name: ("r", name in tenant_tables, name in tenant_tables)
            for name in {
                "schema_history",
                "service_definitions",
                "supply_lots",
                "school_bindings",
                "model_catalog_config",
                "provider_setting_configs",
                "provider_setting_confirmations",
                "provider_setting_import_dry_runs",
                "skill_reviews",
                "grant_commands",
                *tenant_tables,
                "audit_events",
            }
        }
        expected_tables["skill_reviews"] = ("r", True, True)
        if tables != expected_tables:
            raise RuntimeError("oms schema drift: table set or RLS flags differ")
        policies = await (
            await c.execute(
                """
                SELECT r.relname,p.polname,pg_get_expr(p.polqual,p.polrelid),
                       pg_get_expr(p.polwithcheck,p.polrelid)
                  FROM pg_policy p JOIN pg_class r ON r.oid=p.polrelid
                  JOIN pg_namespace n ON n.oid=r.relnamespace
                 WHERE n.nspname='oms'
                """
            )
        ).fetchall()
        tenant_expr = (
            "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"
        )
        command_expr = "(target_tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"
        expected_policies = {
            (name, "tenant_scope", tenant_expr, tenant_expr)
            for name in tenant_tables
            if name not in {"entitlement_commands", "skill_revisions", "skill_publications"}
        }
        expected_policies.add(("entitlement_commands", "tenant_scope", command_expr, command_expr))
        skill_owner_expr = (
            "((owner_kind = 'global'::text) OR "
            "(owner_school_id = (NULLIF(current_setting('app.tenant_id'::text, true), "
            "''::text))::uuid))"
        )
        for name in ("skill_revisions", "skill_publications"):
            expected_policies.add((name, "skill_owner_scope", skill_owner_expr, skill_owner_expr))
        review_scope_expr = "(current_setting('app.management_app'::text, true) = 'oms'::text)"
        expected_policies.add(
            ("skill_reviews", "skill_review_oms_scope", review_scope_expr, review_scope_expr)
        )
        if set(map(tuple, policies)) != expected_policies:
            raise RuntimeError("oms schema drift: tenant RLS policies differ")
        indexes = await (
            await c.execute("SELECT indexname FROM pg_indexes WHERE schemaname='oms'")
        ).fetchall()
        required_indexes = {
            "supply_lots_available",
            "quota_grants_pick",
            "usage_attempts_operation",
            "usage_attempts_reconcile",
            "usage_attempts_provider_receipt",
            "audit_events_target_time",
            "attempt_allocations_order",
            "attempt_evidence_by_attempt",
            "entitlement_commands_target_time",
            "skill_global_revision_version",
            "skill_tenant_revision_version",
            "skill_global_publication",
            "skill_tenant_publication",
            "skill_reviews_latest",
            "provider_setting_confirmations_status",
            "provider_setting_import_dry_runs_source",
        }
        if not required_indexes.issubset({row[0] for row in indexes}):
            raise RuntimeError("oms schema drift: required index missing")
        skill_fence_columns = await (
            await c.execute(
                "SELECT table_name,column_name,data_type FROM information_schema.columns "
                "WHERE table_schema='oms' AND ("
                "(table_name='skill_revisions' AND column_name='created_issuer') OR "
                "(table_name='skill_publications' AND column_name='review_id') OR "
                "(table_name='skill_grants' AND column_name='publication_version') OR "
                "(table_name='skill_reviews' AND column_name='revision_id'))"
            )
        ).fetchall()
        if set(map(tuple, skill_fence_columns)) != {
            ("skill_revisions", "created_issuer", "text"),
            ("skill_publications", "review_id", "uuid"),
            ("skill_grants", "publication_version", "bigint"),
            ("skill_reviews", "revision_id", "uuid"),
        }:
            raise RuntimeError("oms schema drift: Skill review/version fences missing")
        source_column = await (
            await c.execute(
                "SELECT data_type,is_nullable FROM information_schema.columns "
                "WHERE table_schema='oms' AND table_name='quota_grants' "
                "AND column_name='source_ref'"
            )
        ).fetchone()
        if source_column != ("text", "YES"):
            raise RuntimeError("oms schema drift: quota grant source reference missing")
        adjustment_column = await (
            await c.execute(
                "SELECT data_type,is_nullable FROM information_schema.columns "
                "WHERE table_schema='oms' AND table_name='quota_grants' "
                "AND column_name='adjustment_released'"
            )
        ).fetchone()
        adjustment_constraint = await (
            await c.execute(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "WHERE c.conrelid='oms.quota_grants'::regclass "
                "AND c.conname='quota_grants_adjustment_released_valid'"
            )
        ).fetchone()
        if (
            adjustment_column != ("numeric", "NO")
            or not adjustment_constraint
            or "adjustment_released" not in adjustment_constraint[0]
            or "quantity" not in adjustment_constraint[0]
        ):
            raise RuntimeError("oms schema drift: quota adjustment constraint missing")
        school_binding = await (
            await c.execute(
                "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid='oms.school_bindings'::regclass"
            )
        ).fetchall()
        binding_constraints = dict(school_binding)
        if not any(
            "UNIQUE (eduplus_tenant_id)" in definition
            for definition in binding_constraints.values()
        ) or not any(
            "eduplus_tenant_id > 0" in definition for definition in binding_constraints.values()
        ):
            raise RuntimeError("oms schema drift: school binding constraints missing")
        self._validate_oms_school_binding_facts(await self._oms_school_binding_snapshot(c))
        binding_guard = await (
            await c.execute(
                "SELECT t.tgname,t.tgenabled,fn.nspname,p.proname "
                "FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid "
                "JOIN pg_proc p ON p.oid=t.tgfoid "
                "JOIN pg_namespace fn ON fn.oid=p.pronamespace "
                "WHERE r.oid='oms.school_bindings'::regclass AND NOT t.tgisinternal"
            )
        ).fetchall()
        if binding_guard:
            raise RuntimeError("oms schema drift: school binding version guard remains")
        supply_columns = await (
            await c.execute(
                "SELECT column_name,data_type,is_nullable FROM information_schema.columns "
                "WHERE table_schema='oms' AND table_name='supply_lots' "
                "AND column_name IN ('supply_basis','verified_at','created_by','version')"
            )
        ).fetchall()
        if set(map(tuple, supply_columns)) != {
            ("supply_basis", "text", "NO"),
            ("verified_at", "timestamp with time zone", "YES"),
            ("created_by", "text", "YES"),
            ("version", "bigint", "NO"),
        }:
            raise RuntimeError("oms schema drift: supply evidence columns differ")
        lifecycle_columns = await (
            await c.execute(
                "SELECT table_name,column_name,data_type,is_nullable "
                "FROM information_schema.columns WHERE table_schema='oms' "
                "AND (table_name,column_name) IN "
                "(('usage_attempts','pool_id'),('usage_attempts','request_hash'),"
                "('attempt_allocations','allocation_order'),"
                "('grant_commands','result_summary'),"
                "('attempt_evidence_events','event_kind'),"
                "('attempt_evidence_events','reference'))"
            )
        ).fetchall()
        if set(map(tuple, lifecycle_columns)) != {
            ("usage_attempts", "pool_id", "text", "YES"),
            ("usage_attempts", "request_hash", "text", "YES"),
            ("attempt_allocations", "allocation_order", "integer", "YES"),
            ("grant_commands", "result_summary", "jsonb", "NO"),
            ("attempt_evidence_events", "event_kind", "text", "NO"),
            ("attempt_evidence_events", "reference", "text", "NO"),
        }:
            raise RuntimeError("oms schema drift: attempt lifecycle columns differ")
        lifecycle_constraints = await (
            await c.execute(
                "SELECT c.conname,pg_get_constraintdef(c.oid) "
                "FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid "
                "JOIN pg_namespace n ON n.oid=r.relnamespace "
                "WHERE n.nspname='oms' AND r.relname IN "
                "('usage_attempts','attempt_allocations','grant_commands') AND c.conname IN "
                "('usage_attempts_request_hash_valid',"
                "'attempt_allocations_order_positive','grant_commands_result_summary_object')"
            )
        ).fetchall()
        constraints = dict(lifecycle_constraints)
        if set(constraints) != {
            "usage_attempts_request_hash_valid",
            "attempt_allocations_order_positive",
            "grant_commands_result_summary_object",
        }:
            raise RuntimeError("oms schema drift: attempt lifecycle constraints differ")
        fact_triggers = await (
            await c.execute(
                "SELECT r.relname,t.tgname,t.tgenabled,fn.nspname,p.proname "
                "FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=r.relnamespace "
                "JOIN pg_proc p ON p.oid=t.tgfoid "
                "JOIN pg_namespace fn ON fn.oid=p.pronamespace "
                "WHERE n.nspname='oms' AND NOT t.tgisinternal "
                "AND r.relname IN ('attempt_evidence_events','audit_events')"
            )
        ).fetchall()
        fact_function = await (
            await c.execute("SELECT to_regprocedure('oms.reject_fact_mutation()')")
        ).fetchone()
        if fact_triggers or fact_function != (None,):
            raise RuntimeError("oms schema drift: retired fact mutation function remains")
        await self._verify_no_database_owned_business_rules(c, _OMS_SCHEMA)

    def _management_migrations(self):
        return [
            (p.name[:-4], p.read_text(encoding="utf8"))
            for p in sorted(files(_MANAGEMENT_PACKAGE).iterdir(), key=lambda p: p.name)
            if p.name.endswith(".sql")
        ]

    async def _management_history(self, c):
        exists = await (
            await c.execute("SELECT to_regclass(%s)", ("management.schema_history",))
        ).fetchone()
        if not exists[0]:
            return {}
        return dict(
            await (
                await c.execute(
                    "SELECT version,checksum FROM management.schema_history ORDER BY version"
                )
            ).fetchall()
        )

    async def _management_plan(self, c):
        history = await self._management_history(c)
        migrations = self._management_migrations()
        expected = {
            version: hashlib.sha256(sql.encode()).hexdigest() for version, sql in migrations
        }
        if any(
            version not in expected or digest != expected[version]
            for version, digest in history.items()
        ):
            raise RuntimeError("management schema history drift or incompatible version")
        applied = [version for version, _ in migrations if version in history]
        if applied != [version for version, _ in migrations][: len(applied)]:
            raise RuntimeError("management schema history drift: non-contiguous versions")
        return [(version, sql) for version, sql in migrations if version not in history]

    async def _management_action_catalog_snapshot(self, c):
        exists = await (
            await c.execute("SELECT to_regclass('management.action_catalog')")
        ).fetchone()
        if exists[0] is None:
            return {}
        snapshot = {}
        for application in ("oms", "tms"):
            await c.execute("SELECT set_config('app.management_app',%s,true)", (application,))
            rows = await (
                await c.execute(
                    "SELECT action_key,allowed_scope,sensitive,status,version "
                    "FROM management.action_catalog WHERE application=%s",
                    (application,),
                )
            ).fetchall()
            snapshot.update({(application, row[0]): row[1:] for row in rows})
        return snapshot

    async def _management_role_catalog_snapshot(self, c):
        exists = await (
            await c.execute("SELECT to_regclass('management.role_versions')")
        ).fetchone()
        if exists[0] is None:
            return {}, set()
        owner_column = await (
            await c.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_attribute "
                "WHERE attrelid='management.role_versions'::regclass "
                "AND attname='owner_school_id' AND NOT attisdropped)"
            )
        ).fetchone()
        owner_expr = "owner_school_id" if owner_column[0] else "NULL::uuid AS owner_school_id"
        roles = {}
        actions = set()
        for application in ("oms", "tms"):
            await c.execute("SELECT set_config('app.management_app',%s,true)", (application,))
            rows = await (
                await c.execute(
                    "SELECT role_key,version,scope_kind,is_template,"
                    f"{owner_expr} FROM management.role_versions WHERE application=%s",
                    (application,),
                )
            ).fetchall()
            roles.update({(application, row[0], row[1]): row[2:] for row in rows})
            rows = await (
                await c.execute(
                    "SELECT role_key,role_version,action_key,"
                    f"{owner_expr} FROM management.role_actions WHERE application=%s",
                    (application,),
                )
            ).fetchall()
            actions.update((application, *row) for row in rows)
        return roles, actions

    async def _management_delegation_snapshot(self, c):
        exists = await (
            await c.execute("SELECT to_regclass('management.delegation_policies')")
        ).fetchone()
        if exists[0] is None:
            return {}
        columns = (
            "application",
            "principal_application",
            "principal_school_id",
            "action_application",
            "action_status",
            "action_allowed_scope",
            "scope_kind",
            "school_id",
            "status",
            "version",
            "valid_from",
            "expires_at",
        )
        snapshot = {}
        for application in ("oms", "tms"):
            await c.execute("SELECT set_config('app.management_app',%s,true)", (application,))
            rows = await (
                await c.execute(
                    "SELECT d.id,d.application,p.application,p.school_id,"
                    "a.application,a.status,a.allowed_scope,d.scope_kind,d.school_id,"
                    "d.status,d.version,d.valid_from,d.expires_at "
                    "FROM management.delegation_policies d "
                    "LEFT JOIN management.principals p ON p.id=d.principal_id "
                    "LEFT JOIN management.action_catalog a ON "
                    "a.application=d.application AND a.action_key=d.action_key "
                    "WHERE d.application=%s",
                    (application,),
                )
            ).fetchall()
            snapshot.update({row[0]: dict(zip(columns, row[1:])) for row in rows})
        return snapshot

    async def _management_assignment_snapshot(self, c):
        exists = await (await c.execute("SELECT to_regclass('management.assignments')")).fetchone()
        if exists[0] is None:
            return {}
        binding_column = await (
            await c.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_attribute "
                "WHERE attrelid='management.assignments'::regclass "
                "AND attname='school_binding_version' AND NOT attisdropped)"
            )
        ).fetchone()
        binding_expr = (
            "a.school_binding_version"
            if binding_column[0]
            else "NULL::bigint AS school_binding_version"
        )
        columns = (
            "application",
            "principal_application",
            "principal_school_id",
            "role_application",
            "role_scope_kind",
            "scope_kind",
            "school_id",
            "status",
            "version",
            "valid_from",
            "expires_at",
            "revoked_at",
            "school_binding_version",
        )
        snapshot = {}
        for application in ("oms", "tms"):
            await c.execute("SELECT set_config('app.management_app',%s,true)", (application,))
            rows = await (
                await c.execute(
                    "SELECT a.id,a.application,p.application,p.school_id,"
                    "rv.application,rv.scope_kind,a.scope_kind,a.school_id,a.status,"
                    "a.version,a.valid_from,a.expires_at,a.revoked_at,"
                    f"{binding_expr} "
                    "FROM management.assignments a "
                    "LEFT JOIN management.principals p ON p.id=a.principal_id "
                    "LEFT JOIN management.role_versions rv ON "
                    "rv.application=a.application AND rv.role_key=a.role_key "
                    "AND rv.version=a.role_version WHERE a.application=%s",
                    (application,),
                )
            ).fetchall()
            snapshot.update({row[0]: dict(zip(columns, row[1:])) for row in rows})
        return snapshot

    async def _management_approval_snapshot(self, c):
        exists = await (
            await c.execute("SELECT to_regclass('management.approval_requests')")
        ).fetchone()
        if exists[0] is None:
            return {}
        columns = (
            "application",
            "operation",
            "school_id",
            "proposer_issuer",
            "proposer_subject",
            "reviewer_issuer",
            "reviewer_subject",
            "expected_policy_version",
            "status",
            "expires_at",
            "decided_at",
        )
        snapshot = {}
        for application in ("oms", "tms"):
            await c.execute("SELECT set_config('app.management_app',%s,true)", (application,))
            rows = await (
                await c.execute(
                    "SELECT id,application,operation,school_id,proposer_issuer,"
                    "proposer_subject,reviewer_issuer,reviewer_subject,"
                    "expected_policy_version,status,expires_at,decided_at "
                    "FROM management.approval_requests WHERE application=%s",
                    (application,),
                )
            ).fetchall()
            snapshot.update({row[0]: dict(zip(columns, row[1:])) for row in rows})
        return snapshot

    async def _management_audit_snapshot(self, c):
        exists = await (await c.execute("SELECT to_regclass('management.audit_events')")).fetchone()
        if exists[0] is None:
            return {}
        columns = (
            "application",
            "school_id",
            "actor_issuer",
            "actor_subject",
            "action_key",
            "target_kind",
            "target_id",
            "request_id",
            "result",
            "reason",
            "before_version",
            "after_version",
            "safe_summary",
        )
        snapshot = {}
        for application in ("oms", "tms"):
            await c.execute("SELECT set_config('app.management_app',%s,true)", (application,))
            rows = await (
                await c.execute(
                    "SELECT id,application,school_id,actor_issuer,actor_subject,"
                    "action_key,target_kind,target_id,request_id,result,reason,"
                    "before_version,after_version,safe_summary "
                    "FROM management.audit_events WHERE application=%s",
                    (application,),
                )
            ).fetchall()
            snapshot.update({row[0]: dict(zip(columns, row[1:])) for row in rows})
        return snapshot

    @staticmethod
    def _validate_management_assignment_snapshot(snapshot, *, before=None):
        from deeptutor_enterprise.management.assignment_rules import validate_assignment_relation
        from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied

        if before is not None and before.keys() - snapshot.keys():
            raise RuntimeError("management assignment transition is invalid")
        for assignment_id, fact in snapshot.items():
            if before is not None:
                previous = before.get(assignment_id)
                if previous is None:
                    if fact["version"] != 1 or fact["status"] != "active":
                        raise RuntimeError("management assignment transition is invalid")
                elif fact != previous:
                    immutable = (
                        "application",
                        "principal_application",
                        "principal_school_id",
                        "role_application",
                        "role_scope_kind",
                        "scope_kind",
                        "school_id",
                        "valid_from",
                    )
                    if (
                        any(fact[key] != previous[key] for key in immutable)
                        or type(previous["version"]) is not int
                        or fact["version"] != previous["version"] + 1
                        or (previous["status"] == "revoked" and fact["status"] != "revoked")
                    ):
                        raise RuntimeError("management assignment transition is invalid")
            valid_from = fact["valid_from"]
            expires_at = fact["expires_at"]
            binding_version = fact["school_binding_version"]
            if (
                not isinstance(assignment_id, UUID)
                or fact["status"] not in {"active", "revoked"}
                or type(fact["version"]) is not int
                or fact["version"] < 1
                or not isinstance(valid_from, datetime)
                or valid_from.tzinfo is None
                or not isinstance(expires_at, datetime)
                or expires_at.tzinfo is None
                or expires_at <= valid_from
                or (fact["status"] == "active") != (fact["revoked_at"] is None)
                or (
                    binding_version is not None
                    and (type(binding_version) is not int or binding_version < 1)
                )
                or (fact["scope_kind"] == "platform" and binding_version is not None)
            ):
                raise RuntimeError("management assignment fact is invalid")
            try:
                validate_assignment_relation(
                    application=fact["application"],
                    principal_application=fact["principal_application"],
                    principal_school_id=fact["principal_school_id"],
                    role_application=fact["role_application"],
                    role_scope_kind=fact["role_scope_kind"],
                    assignment_scope_kind=fact["scope_kind"],
                    assignment_school_id=fact["school_id"],
                )
            except ManagementAuthorizationDenied as exc:
                raise RuntimeError("management assignment relation is invalid") from exc

    @staticmethod
    def _validate_management_delegation_snapshot(snapshot, *, before=None):
        from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied
        from deeptutor_enterprise.management.delegation_rules import validate_delegation_relation

        if before is not None and before.keys() - snapshot.keys():
            raise RuntimeError("management delegation transition is invalid")
        for delegation_id, fact in snapshot.items():
            previous = None if before is None else before.get(delegation_id)
            # 动作目录可单向退役；这不等于委托行被修改。
            changed = previous is None or any(
                fact[key] != previous[key] for key in fact if key != "action_status"
            )
            valid_from = fact["valid_from"]
            expires_at = fact["expires_at"]
            if (
                not isinstance(delegation_id, UUID)
                or fact["status"] not in {"active", "revoked"}
                or type(fact["version"]) is not int
                or fact["version"] < 1
                or not isinstance(valid_from, datetime)
                or valid_from.tzinfo is None
                or not isinstance(expires_at, datetime)
                or expires_at.tzinfo is None
                or expires_at <= valid_from
            ):
                raise RuntimeError("management delegation fact is invalid")
            try:
                validate_delegation_relation(
                    application=fact["application"],
                    principal_application=fact["principal_application"],
                    principal_school_id=fact["principal_school_id"],
                    action_application=fact["action_application"],
                    action_status=fact["action_status"],
                    action_allowed_scope=fact["action_allowed_scope"],
                    delegation_scope_kind=fact["scope_kind"],
                    delegation_school_id=fact["school_id"],
                    for_write=before is not None and changed,
                )
            except ManagementAuthorizationDenied as exc:
                raise RuntimeError("management delegation relation is invalid") from exc

    @staticmethod
    def _validate_management_approval_snapshot(snapshot, *, before=None):
        from deeptutor_enterprise.management.value_validation import (
            ManagementValueError,
            validate_management_approval_row,
        )

        if before is not None and before.keys() - snapshot.keys():
            raise RuntimeError("management approval transition is invalid")
        for approval_id, fact in snapshot.items():
            current = {"id": approval_id, **fact}
            try:
                validate_management_approval_row(current)
            except ManagementValueError as exc:
                raise RuntimeError("management approval fact is invalid") from exc
            if before is not None:
                previous = before.get(approval_id)
                if previous is not None and fact != previous:
                    immutable = (
                        "application",
                        "operation",
                        "school_id",
                        "proposer_issuer",
                        "proposer_subject",
                        "expected_policy_version",
                        "expires_at",
                    )
                    if any(fact[key] != previous[key] for key in immutable):
                        raise RuntimeError("management approval transition is invalid")

    @staticmethod
    def _validate_management_audit_snapshot(snapshot, *, before=None):
        from deeptutor_enterprise.management.value_validation import (
            ManagementValueError,
            validate_management_audit_row,
        )

        if before is not None and before.keys() - snapshot.keys():
            raise RuntimeError("management audit transition is invalid")
        for audit_id, fact in snapshot.items():
            try:
                validate_management_audit_row({"id": audit_id, **fact})
            except ManagementValueError as exc:
                raise RuntimeError("management audit fact is invalid") from exc
            if before is not None and audit_id in before and fact != before[audit_id]:
                raise RuntimeError("management audit transition is invalid")

    @staticmethod
    def _validate_management_role_owner_facts(roles, role_actions):
        for (application, role_key, version), (
            scope,
            is_template,
            owner_school_id,
        ) in roles.items():
            if (
                application not in {"oms", "tms"}
                or not role_key
                or type(version) is not int
                or version < 1
                or scope not in {"platform", "school"}
                or (application == "tms" and scope != "school")
                or type(is_template) is not bool
                or (owner_school_id is not None and not isinstance(owner_school_id, UUID))
                or (application == "oms" and owner_school_id is not None)
                or (application == "tms" and is_template and owner_school_id is not None)
                or (
                    application == "tms"
                    and not is_template
                    and (
                        owner_school_id is None
                        or not role_key.startswith(f"custom_{owner_school_id.hex}_")
                    )
                )
            ):
                raise RuntimeError("management role owner facts are invalid")
        for application, role_key, role_version, action_key, owner_school_id in role_actions:
            role = roles.get((application, role_key, role_version))
            if role is None or role[2] != owner_school_id:
                raise RuntimeError("management role owner facts are invalid")

    @staticmethod
    def _validate_management_role_catalog_transition(before, after, current_actions):
        old_roles, old_role_actions = before
        roles, role_actions = after
        if any(roles.get(key) != value for key, value in old_roles.items()) or not (
            old_role_actions <= role_actions
        ):
            raise RuntimeError("management role catalog transition is invalid")
        try:
            MigrationRunner._validate_management_role_owner_facts(roles, role_actions)
        except RuntimeError as exc:
            raise RuntimeError("management role catalog transition is invalid") from exc
        for application, role_key, role_version, action_key, owner_school_id in (
            role_actions - old_role_actions
        ):
            role = roles.get((application, role_key, role_version))
            action = current_actions.get((application, action_key))
            if (
                (application, role_key, role_version) in old_roles
                or role is None
                or action is None
                or action[2] != "active"
                or action[0] not in {role[0], "both"}
            ):
                raise RuntimeError("management role catalog transition is invalid")

    @staticmethod
    def _validate_management_action_catalog_facts(snapshot):
        for (application, action_key), current in snapshot.items():
            scope, sensitive, status, version = current
            prefix = "ops." if application == "oms" else "tenant."
            if (
                application not in {"oms", "tms"}
                or not action_key.startswith(prefix)
                or scope not in {"platform", "school", "both"}
                or (application == "tms" and scope != "school")
                or type(sensitive) is not bool
                or status not in {"active", "retired"}
                or type(version) is not int
                or version < 1
            ):
                raise RuntimeError("management action catalog fact is invalid")
        required_active = {
            ("oms", "ops.permissions.manage"),
            ("tms", "tenant.permissions.manage"),
        }
        if any(
            snapshot.get(key, (None, None, None, None))[2] != "active" for key in required_active
        ):
            raise RuntimeError("management action catalog fact is invalid")

    @staticmethod
    def _validate_management_action_catalog_transition(before, after):
        for (application, action_key), current in after.items():
            scope, sensitive, status, version = current
            prefix = "ops." if application == "oms" else "tenant."
            if (
                application not in {"oms", "tms"}
                or not action_key.startswith(prefix)
                or scope not in {"platform", "school", "both"}
                or (application == "tms" and scope != "school")
                or type(sensitive) is not bool
                or status not in {"active", "retired"}
                or type(version) is not int
                or version < 1
            ):
                raise RuntimeError("management action catalog transition is invalid")
            old = before.get((application, action_key))
            if old is None:
                if status != "active" or version != 1:
                    raise RuntimeError("management action catalog transition is invalid")
                continue
            if (
                current[:2] != old[:2]
                or version != old[3]
                or (old[2] == "retired" and status != "retired")
                or (
                    old[2] == "active"
                    and status == "retired"
                    and action_key in {"ops.permissions.manage", "tenant.permissions.manage"}
                )
            ):
                raise RuntimeError("management action catalog transition is invalid")
        if before.keys() - after.keys():
            raise RuntimeError("management action catalog transition is invalid")

    async def _verify_management_last_administrators(self, c):
        platform_admin = await (
            await c.execute(
                """
                SELECT 1
                  FROM management.assignments a
                  JOIN management.principals p ON p.id=a.principal_id
                  JOIN management.role_actions ra ON ra.application=a.application
                   AND ra.role_key=a.role_key AND ra.role_version=a.role_version
                  JOIN management.action_catalog ac ON ac.application=ra.application
                   AND ac.action_key=ra.action_key
                 WHERE a.application='oms' AND p.application='oms'
                   AND p.status='active' AND a.status='active'
                   AND a.scope_kind='platform' AND a.school_id IS NULL
                   AND a.valid_from <= now() AND a.expires_at > now()
                   AND ac.action_key='ops.permissions.manage' AND ac.status='active'
                 LIMIT 1
                """
            )
        ).fetchone()
        if platform_admin is None:
            oms_principals = await (
                await c.execute(
                    "SELECT 1 FROM management.principals WHERE application='oms' LIMIT 1"
                )
            ).fetchone()
            if oms_principals is not None:
                raise RuntimeError("management last administrator fact is invalid")
        school_rows = await (
            await c.execute(
                "SELECT DISTINCT school_id FROM management.principals "
                "WHERE application='tms' AND school_id IS NOT NULL"
            )
        ).fetchall()
        for (school_id,) in school_rows:
            school_admin = await (
                await c.execute(
                    """
                    SELECT 1
                      FROM management.assignments a
                      JOIN management.principals p ON p.id=a.principal_id
                      JOIN management.role_actions ra ON ra.application=a.application
                       AND ra.role_key=a.role_key AND ra.role_version=a.role_version
                      JOIN management.action_catalog ac ON ac.application=ra.application
                       AND ac.action_key=ra.action_key
                     WHERE a.application='tms' AND p.application='tms'
                       AND p.status='active' AND a.status='active'
                       AND a.scope_kind='school' AND a.school_id=%s AND p.school_id=%s
                       AND a.valid_from <= now() AND a.expires_at > now()
                       AND ac.action_key='tenant.permissions.manage' AND ac.status='active'
                     LIMIT 1
                    """,
                    (school_id, school_id),
                )
            ).fetchone()
            if school_admin is None:
                raise RuntimeError("management last administrator fact is invalid")

    async def _verify_management_schema(self, c):
        if await self._management_plan(c):
            raise RuntimeError("management schema migration required; run maintenance apply")
        rows = await (
            await c.execute(
                "SELECT r.relname,r.relkind,r.relrowsecurity,r.relforcerowsecurity "
                "FROM pg_class r JOIN pg_namespace n ON n.oid=r.relnamespace "
                "WHERE n.nspname=%s AND r.relkind IN ('r','p','v','m','f')",
                (_MANAGEMENT_SCHEMA,),
            )
        ).fetchall()
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
        expected = {"schema_history": ("r", False, False)}
        expected.update({name: ("r", True, True) for name in scoped})
        if {row[0]: row[1:] for row in rows} != expected:
            raise RuntimeError("management schema drift: table set or RLS flags differ")
        policies = await (
            await c.execute(
                "SELECT r.relname,p.polname,pg_get_expr(p.polqual,p.polrelid),"
                "pg_get_expr(p.polwithcheck,p.polrelid) FROM pg_policy p "
                "JOIN pg_class r ON r.oid=p.polrelid "
                "JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname=%s",
                (_MANAGEMENT_SCHEMA,),
            )
        ).fetchall()
        app_expression = (
            "(application = NULLIF(current_setting('app.management_app'::text, true), ''::text))"
        )
        school_expression = (
            f"({app_expression} AND ((application = 'oms'::text) OR "
            "(school_id = (NULLIF(current_setting('app.tenant_id'::text, "
            "true), ''::text))::uuid)))"
        )
        school_tables = {
            "principals",
            "assignments",
            "delegation_policies",
            "approval_requests",
            "audit_events",
        }
        expected_policies = {
            (
                name,
                "management_scope",
                school_expression if name in school_tables else app_expression,
                school_expression if name in school_tables else app_expression,
            )
            for name in scoped
        }
        if set(map(tuple, policies)) != expected_policies:
            raise RuntimeError("management schema drift: RLS policies differ")
        constraints = await (
            await c.execute(
                "SELECT r.relname,pg_get_constraintdef(k.oid) "
                "FROM pg_constraint k JOIN pg_class r ON r.oid=k.conrelid "
                "JOIN pg_namespace n ON n.oid=r.relnamespace "
                "WHERE n.nspname='management'"
            )
        ).fetchall()
        definitions: dict[str, list[str]] = {}
        for table, definition in constraints:
            definitions.setdefault(table, []).append(definition)
        required_constraint_groups = {
            "role_actions": (
                ("FOREIGN KEY (application, role_key, role_version)",),
                ("FOREIGN KEY (application, action_key)",),
            ),
            "assignments": (
                ("CHECK", "expires_at", "valid_from"),
                ("FOREIGN KEY (principal_id, application)",),
            ),
            "approval_requests": (("FOREIGN KEY (target_principal_id, application)",),),
        }
        if any(
            not any(
                all(fragment in definition for fragment in group)
                for definition in definitions.get(table, [])
            )
            for table, groups in required_constraint_groups.items()
            for group in groups
        ):
            raise RuntimeError("management schema drift: required constraints differ")
        self._validate_management_action_catalog_facts(
            await self._management_action_catalog_snapshot(c)
        )
        await self._verify_management_last_administrators(c)
        # 迁移/运行数据库用户可能是表 owner，但 FORCE RLS 仍要求应用域。
        await c.execute("SELECT set_config('app.management_app','oms',true)")
        skill_actions = await (
            await c.execute(
                "SELECT action_key,allowed_scope,sensitive,status "
                "FROM management.action_catalog WHERE application='oms' "
                "AND action_key LIKE 'ops.skills.%'"
            )
        ).fetchall()
        required_skill_actions = {
            ("ops.skills.read", "platform", False, "active"),
            ("ops.skills.manage", "platform", True, "active"),
            ("ops.skills.review", "platform", True, "active"),
            ("ops.skills.publish", "platform", True, "active"),
            ("ops.skills.grant", "school", True, "active"),
        }
        if set(map(tuple, skill_actions)) != required_skill_actions:
            raise RuntimeError("management schema drift: OMS Skill action catalog differs")
        skill_template_actions = await (
            await c.execute(
                "SELECT ra.role_key,ra.role_version,rv.scope_kind,ra.action_key "
                "FROM management.role_actions ra JOIN management.role_versions rv "
                "ON rv.application=ra.application AND rv.role_key=ra.role_key "
                "AND rv.version=ra.role_version "
                "WHERE ra.application='oms' AND ra.action_key LIKE 'ops.skills.%' "
                "AND rv.is_template"
            )
        ).fetchall()
        required_skill_template_actions = {
            ("platform_security_admin", 2, "platform", "ops.skills.read"),
            ("platform_security_admin", 2, "platform", "ops.skills.review"),
            ("platform_config_admin", 2, "platform", "ops.skills.read"),
            ("platform_config_admin", 2, "platform", "ops.skills.manage"),
            ("platform_config_admin", 2, "platform", "ops.skills.publish"),
            ("platform_operator", 2, "school", "ops.skills.grant"),
        }
        if not required_skill_template_actions.issubset(set(map(tuple, skill_template_actions))):
            raise RuntimeError("management schema drift: OMS Skill templates differ")
        # 模板由受控迁移写入；自定义版本仅由管理服务追加，逐应用核对范围。
        for application in ("oms", "tms"):
            await c.execute("SELECT set_config('app.management_app',%s,true)", (application,))
            bad_scope = await (
                await c.execute(
                    "SELECT 1 FROM management.role_actions ra "
                    "LEFT JOIN management.role_versions rv ON "
                    "(rv.application,rv.role_key,rv.version)="
                    "(ra.application,ra.role_key,ra.role_version) "
                    "LEFT JOIN management.action_catalog ac ON "
                    "(ac.application,ac.action_key)=(ra.application,ra.action_key) "
                    "WHERE ra.application=%s AND "
                    "(rv.scope_kind IS NULL OR ac.allowed_scope IS NULL OR "
                    "(ac.allowed_scope<>'both' AND ac.allowed_scope<>rv.scope_kind)) "
                    "LIMIT 1",
                    (application,),
                )
            ).fetchone()
            if bad_scope:
                raise RuntimeError("management schema drift: role action scope differs")
        owner_columns = await (
            await c.execute(
                "SELECT table_name,data_type,is_nullable FROM information_schema.columns "
                "WHERE table_schema='management' AND table_name IN "
                "('role_versions','role_actions') AND column_name='owner_school_id'"
            )
        ).fetchall()
        if set(map(tuple, owner_columns)) != {
            ("role_versions", "uuid", "YES"),
            ("role_actions", "uuid", "YES"),
        }:
            raise RuntimeError("management schema drift: custom role school owner missing")
        roles, role_actions = await self._management_role_catalog_snapshot(c)
        try:
            self._validate_management_role_owner_facts(roles, role_actions)
        except RuntimeError as exc:
            raise RuntimeError("management schema drift: custom role owner differs") from exc
        self._validate_management_delegation_snapshot(await self._management_delegation_snapshot(c))
        self._validate_management_assignment_snapshot(await self._management_assignment_snapshot(c))
        self._validate_management_approval_snapshot(await self._management_approval_snapshot(c))
        self._validate_management_audit_snapshot(await self._management_audit_snapshot(c))
        binding_version_column = await (
            await c.execute(
                "SELECT data_type,is_nullable FROM information_schema.columns "
                "WHERE table_schema='management' AND table_name='assignments' "
                "AND column_name='school_binding_version'"
            )
        ).fetchone()
        if binding_version_column != ("bigint", "YES"):
            raise RuntimeError("management schema drift: assignment binding version missing")
        indexes = await (
            await c.execute("SELECT indexname FROM pg_indexes WHERE schemaname='management'")
        ).fetchall()
        required_indexes = {
            "principals_oms_identity",
            "principals_tms_identity",
            "assignments_effective",
            "assignments_active_platform_role",
            "assignments_active_school_role",
            "approval_pending_school_activation",
            "audit_events_target_time",
            "role_versions_school_owner",
            "role_actions_school_owner",
        }
        if not required_indexes.issubset({row[0] for row in indexes}):
            raise RuntimeError("management schema drift: required index missing")
        triggers = await (
            await c.execute(
                "SELECT r.relname,t.tgname,t.tgenabled FROM pg_trigger t "
                "JOIN pg_class r ON r.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=r.relnamespace "
                "WHERE n.nspname='management' AND NOT t.tgisinternal"
            )
        ).fetchall()
        expected_triggers = set()
        if set(map(tuple, triggers)) != expected_triggers:
            raise RuntimeError("management schema drift: required triggers differ")
        immutable_function = await (
            await c.execute("SELECT to_regprocedure('management.reject_immutable_fact()')")
        ).fetchone()
        if immutable_function != (None,):
            raise RuntimeError("management schema drift: retired immutable fact function remains")
        role_action_function = await (
            await c.execute("SELECT to_regprocedure('management.validate_role_action()')")
        ).fetchone()
        if role_action_function != (None,):
            raise RuntimeError("management schema drift: retired role action function remains")
        await self._verify_no_database_owned_business_rules(c, _MANAGEMENT_SCHEMA)

    async def plan(self):
        core_pending = await super().plan()
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            extension_pending = [version for version, _ in await self._extension_plan(c)]
            oms_pending = [f"oms/{version}" for version, _ in await self._oms_plan(c)]
            management_pending = [
                f"management/{version}" for version, _ in await self._management_plan(c)
            ]
        return [*core_pending, *extension_pending, *oms_pending, *management_pending]

    async def verify(self):
        await super().verify()
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            for schema in _BUSINESS_RULE_SCHEMAS:
                await self._verify_no_database_owned_business_rules(c, schema)
            await c.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_EXTENSION_LOCK_ID,))
            await self._verify_extension_schema(c)
            await c.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_OMS_LOCK_ID,))
            await self._verify_oms_schema(c)
            await c.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_MANAGEMENT_LOCK_ID,))
            await self._verify_management_schema(c)

    async def apply(self):
        await super().apply()
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            await c.execute("SELECT pg_advisory_xact_lock(%s)", (_EXTENSION_LOCK_ID,))
            pending = await self._extension_plan(c)
            if not pending:
                await self._verify_extension_schema(c)
            else:
                await c.execute(f"CREATE SCHEMA IF NOT EXISTS {_EXTENSION_SCHEMA}")
                await c.execute(
                    f"CREATE TABLE IF NOT EXISTS {_EXTENSION_SCHEMA}.schema_history (version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
                )
                for version, sql in pending:
                    await c.execute(sql, prepare=False)
                    await c.execute(
                        f"INSERT INTO {_EXTENSION_SCHEMA}.schema_history(version,checksum) VALUES(%s,%s)",
                        (version, hashlib.sha256(sql.encode()).hexdigest()),
                    )
                await self._verify_extension_schema(c)
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            await c.execute("SELECT pg_advisory_xact_lock(%s)", (_OMS_LOCK_ID,))
            pending = await self._oms_plan(c)
            if pending:
                previous_bindings = await self._oms_school_binding_snapshot(c)
                await c.execute(f"CREATE SCHEMA IF NOT EXISTS {_OMS_SCHEMA}")
                await c.execute(
                    "CREATE TABLE IF NOT EXISTS oms.schema_history (version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
                )
                for version, sql in pending:
                    await c.execute(sql, prepare=False)
                    current_bindings = await self._oms_school_binding_snapshot(c)
                    self._validate_oms_school_binding_transition(
                        previous_bindings, current_bindings
                    )
                    previous_bindings = current_bindings
                    await c.execute(
                        "INSERT INTO oms.schema_history(version,checksum) VALUES(%s,%s)",
                        (version, hashlib.sha256(sql.encode()).hexdigest()),
                    )
            await self._verify_oms_schema(c)
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            await c.execute("SELECT pg_advisory_xact_lock(%s)", (_MANAGEMENT_LOCK_ID,))
            pending = await self._management_plan(c)
            if pending:
                previous_actions = await self._management_action_catalog_snapshot(c)
                previous_roles = await self._management_role_catalog_snapshot(c)
                previous_delegations = await self._management_delegation_snapshot(c)
                previous_assignments = await self._management_assignment_snapshot(c)
                previous_approvals = await self._management_approval_snapshot(c)
                previous_audits = await self._management_audit_snapshot(c)
                await c.execute(f"CREATE SCHEMA IF NOT EXISTS {_MANAGEMENT_SCHEMA}")
                await c.execute(
                    "CREATE TABLE IF NOT EXISTS management.schema_history "
                    "(version text PRIMARY KEY,checksum text NOT NULL,"
                    "applied_at timestamptz NOT NULL DEFAULT now())"
                )
                for version, sql in pending:
                    await c.execute(sql, prepare=False)
                    current_actions = await self._management_action_catalog_snapshot(c)
                    self._validate_management_action_catalog_transition(
                        previous_actions, current_actions
                    )
                    current_roles = await self._management_role_catalog_snapshot(c)
                    self._validate_management_role_catalog_transition(
                        previous_roles, current_roles, current_actions
                    )
                    current_delegations = await self._management_delegation_snapshot(c)
                    self._validate_management_delegation_snapshot(
                        current_delegations, before=previous_delegations
                    )
                    current_assignments = await self._management_assignment_snapshot(c)
                    self._validate_management_assignment_snapshot(
                        current_assignments, before=previous_assignments
                    )
                    current_approvals = await self._management_approval_snapshot(c)
                    self._validate_management_approval_snapshot(
                        current_approvals, before=previous_approvals
                    )
                    current_audits = await self._management_audit_snapshot(c)
                    self._validate_management_audit_snapshot(current_audits, before=previous_audits)
                    previous_actions = current_actions
                    previous_roles = current_roles
                    previous_delegations = current_delegations
                    previous_assignments = current_assignments
                    previous_approvals = current_approvals
                    previous_audits = current_audits
                    await c.execute(
                        "INSERT INTO management.schema_history(version,checksum) VALUES(%s,%s)",
                        (version, hashlib.sha256(sql.encode()).hexdigest()),
                    )
            await self._verify_management_schema(c)


__all__ = ["MigrationRunner"]
