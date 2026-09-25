"""Shared PostgreSQL-only session test helpers.

These helpers intentionally stand up the real product migrations, restricted
runtime role and trusted identity scope.  They replace the old local SQLite /
PocketBase fixtures for core session tests without adding a mock storage path.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

from deeptutor.persistence.postgres.connection import Database
from deeptutor.persistence.postgres.identity.service import Identity, IdentityService
from deeptutor.persistence.postgres.migrations.runner import MigrationRunner
from deeptutor.persistence.postgres.scope import TenantScope
from deeptutor.persistence.postgres.session import PostgresSessionStore
from tests.fixtures.postgres import single_database_user_dsn

_SIGNING_KEY = "session-pg-helper-signing-key-is-long-enough"
_BOOTSTRAP_SECRET = "session-pg-helper-bootstrap-secret-is-long-enough"


@dataclass(frozen=True, slots=True)
class PgSessionRuntime:
    db: Database
    tenant_id: str
    identity: IdentityService
    admin: Identity
    admin_token: str

    def store(self, actor: Identity | None = None) -> PostgresSessionStore:
        principal = actor or self.admin
        return PostgresSessionStore(self.db, TenantScope(principal.tenant_id, principal.user_id))

    async def create_user(self, username: str, password: str = "long-password-1") -> Identity:
        await self.identity.create_user(self.admin_token, username, password)
        token = await self.identity.login(username, password, client=f"session-test-{username}")
        return await self.identity.authenticate(token)


@asynccontextmanager
async def pg_session_runtime(pg_dsn: str, *, resource: str):
    """Yield an authenticated PG session runtime for one isolated test database."""

    await MigrationRunner(pg_dsn).apply()
    runtime_dsn = single_database_user_dsn(pg_dsn)
    tenant_id = str(uuid4())
    async with Database(runtime_dsn, resource=resource, max_size=4, max_waiting=8) as db:
        identity = IdentityService(
            db,
            tenant_id=tenant_id,
            signing_key=_SIGNING_KEY,
            auth_epoch="session-pg-helper-epoch",
            bootstrap_secret=_BOOTSTRAP_SECRET,
        )
        await identity.bootstrap("admin", "long-password-1", secret=_BOOTSTRAP_SECRET)
        admin_token = await identity.login("admin", "long-password-1", client="session-test-admin")
        admin = await identity.authenticate(admin_token)
        yield PgSessionRuntime(
            db=db,
            tenant_id=tenant_id,
            identity=identity,
            admin=admin,
            admin_token=admin_token,
        )
