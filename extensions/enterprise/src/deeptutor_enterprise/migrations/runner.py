"""企业扩展迁移：core schema + 独立 EduPlus2 extension schema。"""

from __future__ import annotations

import hashlib
from importlib.resources import files

import psycopg

from deeptutor.persistence.postgres.migrations.runner import MigrationRunner as CoreMigrationRunner

_EXTENSION_SCHEMA = "eduplus2"
_EXTENSION_PACKAGE = "deeptutor_enterprise.eduplus2.migrations"
_EXTENSION_LOCK_ID = 0x44544544555032


class MigrationRunner(CoreMigrationRunner):
    """保留 core runner 语义，并追加企业扩展自有 schema 迁移。"""

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
        if any(
            version not in expected or expected[version] != digest
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
            "provider_clients": ("r", True, True),
            "external_client_registrations": ("r", True, True),
            "identity_bindings": ("r", True, True),
            "resolve_cache": ("r", True, True),
            "profile_snapshots": ("r", True, True),
            "permission_snapshots": ("r", True, True),
            "revocation_events": ("r", True, True),
            "revocation_state": ("r", True, True),
            "audit_export_jobs": ("r", True, True),
            "audit_events": ("r", True, True),
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

    async def plan(self):
        core_pending = await super().plan()
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            extension_pending = [version for version, _ in await self._extension_plan(c)]
        return [*core_pending, *extension_pending]

    async def verify(self):
        await super().verify()
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            await c.execute("SELECT pg_advisory_xact_lock_shared(%s)", (_EXTENSION_LOCK_ID,))
            await self._verify_extension_schema(c)

    async def apply(self):
        await super().apply()
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            await c.execute("SELECT pg_advisory_xact_lock(%s)", (_EXTENSION_LOCK_ID,))
            pending = await self._extension_plan(c)
            if not pending:
                await self._verify_extension_schema(c)
                return
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


__all__ = ["MigrationRunner"]
