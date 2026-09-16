"""同步 HTTP/WS 测试桥接：真实隔离 PG、真实 bearer，绝无认证 mock。"""

from contextlib import asynccontextmanager, contextmanager
from functools import partial
from pathlib import Path
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.persistence.postgres.connection import Database
from deeptutor.persistence.postgres.identity.service import IdentityService
from deeptutor.persistence.postgres.migrations.runner import MigrationRunner
from deeptutor.persistence.resources import OwnerResourceProvider
from deeptutor.services.auth import PostgresAuthProvider


class AccountClient(TestClient):
    def request(self, *args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        value = headers.get("Authorization", "")
        if value.startswith("Bearer "):
            alias = value.split(" ", 1)[1]
            headers["Authorization"] = "Bearer " + self.app.state.tokens.get(alias, alias)
        kwargs["headers"] = headers
        return super().request(*args, **kwargs)

    @property
    def identity(self):
        return self.app.state.auth_provider.identity

    def call(self, method, *args, **kwargs):
        return self.portal.call(partial(getattr(self.identity, method), *args, **kwargs))

    def users(self):
        return {
            row["username"]: row
            for row in self.call("list_users", self.app.state.tokens["admin-token"])
        }

    def avatar_file(self, uid):
        try:
            row = self.call("avatar_record", self.app.state.tokens["admin-token"], uid)
        except LookupError:
            return None
        if not row["avatar_object"]:
            return None
        resources = self.app.state.auth_provider.resources
        return Path("/").joinpath(
            *resources._segments(self.identity.tenant_id, uid, "avatars"), row["avatar_object"]
        )


@contextmanager
def pg_auth_client(dsn, root, *, admin="alice", learner="bob", ordinary="sam"):
    @asynccontextmanager
    async def lifespan(app):
        await MigrationRunner(dsn).apply()
        async with Database(
            dsn.replace("user=postgres", "user=dt_enterprise_app"), resource="test-default-auth"
        ) as db:
            service = IdentityService(
                db,
                tenant_id=str(uuid.uuid4()),
                signing_key="s" * 48,
                auth_epoch="epoch1",
                bootstrap_secret="b" * 48,
            )
            await service.bootstrap(admin, "administrator-123", secret="b" * 48)
            admin_token = await service.login(admin, "administrator-123", client="setup")
            await service.create_user(admin_token, learner, "learner-password", preset="learner")
            await service.create_user(admin_token, ordinary, "ordinary-password")
            app.state.tokens = {
                "admin-token": admin_token,
                "user-token": await service.login(learner, "learner-password", client="learner"),
                "standard-token": await service.login(
                    ordinary, "ordinary-password", client="ordinary"
                ),
            }
            app.state.auth_provider = PostgresAuthProvider(
                service, resources=OwnerResourceProvider(root.resolve()), cookie_secure=False
            )
            yield

    from deeptutor.api.routers.auth import router

    app = FastAPI(lifespan=lifespan)
    app.include_router(router, prefix="/api/auth")
    with AccountClient(app) as client:
        yield client
