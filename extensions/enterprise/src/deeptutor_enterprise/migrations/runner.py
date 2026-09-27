"""企业扩展迁移：core schema + 独立 EduPlus2 extension schema。"""

from __future__ import annotations

import hashlib
from importlib.resources import files

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
        if actual != expected_policies:
            raise RuntimeError("eduplus2 schema drift: tenant RLS policies differ")
        indexes = await (
            await c.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname='eduplus2' "
                "AND tablename IN ('lifecycle_inbox','lifecycle_targets',"
                "'lifecycle_actor_candidates')"
            )
        ).fetchall()
        required_lifecycle_indexes = {
            "eduplus2_lifecycle_inbox_target_pending",
            "eduplus2_lifecycle_targets_retry",
            "eduplus2_lifecycle_targets_expiry",
            "eduplus2_lifecycle_actor_candidates_school",
        }
        if not required_lifecycle_indexes.issubset({row[0] for row in indexes}):
            raise RuntimeError("eduplus2 schema drift: lifecycle indexes missing")

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
        }
        expected_tables = {
            name: ("r", name in tenant_tables, name in tenant_tables)
            for name in {
                "schema_history",
                "service_definitions",
                "supply_lots",
                "school_bindings",
                "grant_commands",
                *tenant_tables,
                "audit_events",
            }
        }
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
            if name != "entitlement_commands"
        }
        expected_policies.add(("entitlement_commands", "tenant_scope", command_expr, command_expr))
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
        }
        if not required_indexes.issubset({row[0] for row in indexes}):
            raise RuntimeError("oms schema drift: required index missing")
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
        if (
            not any(
                "UNIQUE (eduplus_tenant_id)" in definition
                for definition in binding_constraints.values()
            )
            or not any(
                "eduplus_tenant_id > 0" in definition for definition in binding_constraints.values()
            )
            or not any(
                "verified_at" in definition and "verified_by" in definition
                for definition in binding_constraints.values()
            )
        ):
            raise RuntimeError("oms schema drift: school binding constraints missing")
        binding_guard = await (
            await c.execute(
                "SELECT t.tgname,t.tgenabled,fn.nspname,p.proname "
                "FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid "
                "JOIN pg_proc p ON p.oid=t.tgfoid "
                "JOIN pg_namespace fn ON fn.oid=p.pronamespace "
                "WHERE r.oid='oms.school_bindings'::regclass AND NOT t.tgisinternal"
            )
        ).fetchall()
        if set(map(tuple, binding_guard)) != {
            ("guard_school_binding_version", "O", "oms", "guard_school_binding_version")
        }:
            raise RuntimeError("oms schema drift: school binding version guard missing")
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
        supply_constraint = await (
            await c.execute(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "WHERE c.conrelid='oms.supply_lots'::regclass "
                "AND c.conname='supply_lots_verified_native'"
            )
        ).fetchone()
        if not supply_constraint or not all(
            term in supply_constraint[0]
            for term in (
                "legacy_unverified",
                "native_units",
                "money",
                "credits",
                "paygo",
                "verified_at",
                "hard_ceiling",
            )
        ):
            raise RuntimeError("oms schema drift: supply verification constraint missing")
        quota_status = await (
            await c.execute(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "WHERE c.conrelid='oms.quota_grants'::regclass "
                "AND c.conname='quota_grants_status_check'"
            )
        ).fetchone()
        if not quota_status or not all(
            term in quota_status[0] for term in ("active", "revoked", "expired")
        ):
            raise RuntimeError("oms schema drift: quota expiry status constraint missing")
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
                "('usage_attempts_status_check','usage_attempts_request_hash_valid',"
                "'attempt_allocations_order_positive','grant_commands_result_summary_object')"
            )
        ).fetchall()
        constraints = dict(lifecycle_constraints)
        if set(constraints) != {
            "usage_attempts_status_check",
            "usage_attempts_request_hash_valid",
            "attempt_allocations_order_positive",
            "grant_commands_result_summary_object",
        } or any(
            value not in constraints["usage_attempts_status_check"]
            for value in (
                "reserved",
                "dispatched",
                "remote_unknown",
                "reconcile_required",
                "settled",
                "released",
            )
        ):
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
        if set(map(tuple, fact_triggers)) != {
            (
                "attempt_evidence_events",
                "attempt_evidence_append_only",
                "O",
                "oms",
                "reject_fact_mutation",
            ),
            ("audit_events", "audit_events_append_only", "O", "oms", "reject_fact_mutation"),
        }:
            raise RuntimeError("oms schema drift: append-only fact triggers differ")

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
            "principals": (("CHECK", "application", "school_id"),),
            "action_catalog": (("CHECK", "ops.%", "tenant.%"), ("CHECK", "allowed_scope")),
            "role_actions": (
                ("FOREIGN KEY (application, role_key, role_version)",),
                ("FOREIGN KEY (application, action_key)",),
            ),
            "assignments": (
                ("CHECK", "expires_at", "valid_from"),
                ("CHECK", "scope_kind", "school_id"),
                ("CHECK", "school_binding_version", "scope_kind"),
                ("FOREIGN KEY (principal_id, application)",),
            ),
            "approval_requests": (
                ("CHECK", "reviewer_subject", "proposer_subject"),
                ("CHECK", "reviewer_issuer IS NULL", "reviewer_subject IS NULL"),
                ("CHECK", "status", "approved", "decided_at"),
                ("FOREIGN KEY (target_principal_id, application)",),
            ),
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
        expected_triggers = {
            ("role_versions", "role_versions_append_only", "O"),
            ("role_actions", "role_actions_append_only", "O"),
            ("audit_events", "audit_events_append_only", "O"),
            ("action_catalog", "validate_action_catalog_change", "O"),
            ("assignments", "validate_assignment", "O"),
            ("assignments", "protect_last_administrator", "O"),
            ("principals", "protect_last_administrator_principal", "O"),
            ("role_actions", "validate_role_action", "O"),
            ("assignments", "assignment_policy_version", "O"),
            ("delegation_policies", "delegation_policy_version", "O"),
            ("delegation_policies", "validate_delegation_policy", "O"),
        }
        if set(map(tuple, triggers)) != expected_triggers:
            raise RuntimeError("management schema drift: required triggers differ")

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
                await c.execute(f"CREATE SCHEMA IF NOT EXISTS {_OMS_SCHEMA}")
                await c.execute(
                    "CREATE TABLE IF NOT EXISTS oms.schema_history (version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
                )
                for version, sql in pending:
                    await c.execute(sql, prepare=False)
                    await c.execute(
                        "INSERT INTO oms.schema_history(version,checksum) VALUES(%s,%s)",
                        (version, hashlib.sha256(sql.encode()).hexdigest()),
                    )
            await self._verify_oms_schema(c)
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            await c.execute("SELECT pg_advisory_xact_lock(%s)", (_MANAGEMENT_LOCK_ID,))
            pending = await self._management_plan(c)
            if pending:
                await c.execute(f"CREATE SCHEMA IF NOT EXISTS {_MANAGEMENT_SCHEMA}")
                await c.execute(
                    "CREATE TABLE IF NOT EXISTS management.schema_history "
                    "(version text PRIMARY KEY,checksum text NOT NULL,"
                    "applied_at timestamptz NOT NULL DEFAULT now())"
                )
                for version, sql in pending:
                    await c.execute(sql, prepare=False)
                    await c.execute(
                        "INSERT INTO management.schema_history(version,checksum) VALUES(%s,%s)",
                        (version, hashlib.sha256(sql.encode()).hexdigest()),
                    )
            await self._verify_management_schema(c)


__all__ = ["MigrationRunner"]
