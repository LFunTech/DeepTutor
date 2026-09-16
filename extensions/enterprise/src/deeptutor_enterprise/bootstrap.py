"""企业显式组合根：运行只 verify，不读取 local app、不自动迁移。"""

import asyncio
from contextlib import asynccontextmanager, suppress
from importlib.metadata import version

from packaging.specifiers import SpecifierSet

from deeptutor.persistence.postgres.executor import ExecutorLease
from deeptutor.persistence.postgres.identity.service import IdentityService
from deeptutor.persistence.postgres.session import PostgresSessionStore

from . import CORE_COMPATIBILITY
from .configuration import (
    Configuration,
    DeploymentConfig,
    postgres_configuration,
    resolve_secret,
)
from .context import current_token, identity_context
from .migrations.runner import MigrationRunner
from .scope import TenantScope
from .stores.postgres.connection import Database


class _ControlledBootstrapIdentity(IdentityService):
    """日常实例不持有 bootstrap 明文；显式调用时使用短期 core service。"""

    def __init__(self, *args, bootstrap_resolver, **kwargs):
        super().__init__(*args, bootstrap_secret=None, **kwargs)
        self._bootstrap_resolver = bootstrap_resolver

    async def bootstrap(self, username, password, *, secret):
        controlled = IdentityService(
            self.db,
            tenant_id=self.tenant_id,
            signing_key=self._key,
            auth_epoch=self.epoch,
            bootstrap_secret=self._bootstrap_resolver(),
            issuer=self.issuer,
            audience=self.audience,
            token_seconds=self.token_seconds,
        )
        return await controlled.bootstrap(username, password, secret=secret)


class Enterprise:
    def __init__(self, deployment):
        if version("deeptutor") not in SpecifierSet(CORE_COMPATIBILITY):
            raise RuntimeError("incompatible DeepTutor core version")
        try:
            from deeptutor.core import providers

            if getattr(providers, "APPLICATION_HOOK_VERSION", None) != 1:
                raise ImportError
        except ImportError:
            raise RuntimeError("incompatible or missing application hook") from None
        self.configuration = Configuration(deployment)
        for model in deployment.models:
            resolve_secret(model.secret)
        self.deployment = deployment
        self.postgres = postgres_configuration(deployment)
        dsn = self.postgres.resolve_runtime().reveal()
        identity_secrets = self.postgres.resolve_identity()
        self.db = Database(dsn, **self.postgres.connection_kwargs())
        self.migrations = MigrationRunner(dsn)
        self.lease = ExecutorLease(dsn, resource=deployment.resource)
        self.identity = _ControlledBootstrapIdentity(
            self.db,
            tenant_id=str(deployment.tenant_id),
            signing_key=identity_secrets.signing_key.reveal(),
            auth_epoch=identity_secrets.auth_epoch.reveal(),
            bootstrap_resolver=lambda: self.postgres.resolve_bootstrap().reveal(),
            token_seconds=deployment.token_seconds,
        )
        self.container = None
        self._monitor = None

    async def start(self):
        from deeptutor.app.container import ApplicationContainer
        from deeptutor.core.providers import ApplicationProviders, provider_context
        from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_SPECS
        from deeptutor.runtime.capability_catalog import CapabilityCatalog
        from deeptutor.runtime.coordination import CoordinationSettings, MemoryCoordinator
        from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
        from deeptutor.runtime.request_contracts import CAPABILITY_CONFIG_MODELS

        from .runtime import GuardedTurns, StoreProvider, TurnEnvironment

        if self.deployment.maintenance:
            raise RuntimeError("maintenance mode does not accept application traffic")
        await self.migrations.verify()
        await self.db.__aenter__()
        try:
            async with self.db.transaction(
                TenantScope(str(self.deployment.tenant_id), "@preflight")
            ) as c:
                tenant = await (
                    await c.execute(
                        "SELECT 1 FROM enterprise.tenants WHERE id=%s AND bootstrap_completed AND local_enabled AND provisioning_status='ready' AND recovery_state='normal' AND external_eligibility IN ('allowed','not_required') AND auth_epoch=%s",
                        (str(self.deployment.tenant_id), self.identity.epoch),
                    )
                ).fetchone()
                if not tenant:
                    raise RuntimeError("fixed tenant is not initialized or available")
            await self.lease.acquire()
            self.db.execution_guard = self.lease.check
            self.store_provider = StoreProvider(self)
            self.providers = ApplicationProviders(
                store=self.store_provider, configuration=self.configuration
            )
            with provider_context(self.providers):
                registry = CapabilityRegistry(CapabilityCatalog())
                spec = BUILTIN_CAPABILITY_SPECS["chat"]

                def chat_factory():
                    import importlib

                    module, name = spec.class_path.split(":")
                    return getattr(importlib.import_module(module), name)()

                registry.catalog.register(
                    name="chat",
                    kind="turn",
                    manifest=spec.manifest,
                    factory=chat_factory,
                    config_model=CAPABILITY_CONFIG_MODELS["chat"],
                )
                self.container = ApplicationContainer(
                    settings=CoordinationSettings(),
                    coordinator=MemoryCoordinator(),
                    worker_id=self.lease.execution_id,
                    store_provider=self.store_provider,
                    turn_environment=TurnEnvironment(self),
                    capability_registry=registry,
                    load_plugins=False,
                    coordinator_factory=MemoryCoordinator,
                    turn_service_factory=lambda *args: GuardedTurns(self, *args),
                )
                self.providers = ApplicationProviders(
                    store=self.store_provider,
                    container=self.container,
                    configuration=self.configuration,
                )
                await self.container.start()
                await self.recover()
            self._monitor = asyncio.create_task(self._watch_executor())
        except BaseException:
            await self.lease.close()
            await self.db.__aexit__()
            raise

    async def _watch_executor(self):
        while True:
            await asyncio.sleep(1)
            try:
                await self.lease.check()
            except RuntimeError:
                await self.container.runtime_registry.close(drain_timeout_seconds=0)
                return

    async def authorize(self):
        await self.lease.check()
        return await self.identity.authenticate(current_token())

    async def recover(self):
        # 仅在已取得锁且旧进程确认停止后清理；不派发任何模型/工具。
        async with self.db.transaction(
            TenantScope(str(self.deployment.tenant_id), "@recovery")
        ) as c:
            users = await (
                await c.execute(
                    "SELECT id FROM enterprise.users WHERE tenant_id=%s",
                    (str(self.deployment.tenant_id),),
                )
            ).fetchall()
        for user in users:
            store = PostgresSessionStore(
                self.db, TenantScope(str(self.deployment.tenant_id), user["id"])
            )
            for turn in await store.list_nonterminal_turns():
                await store.finalize_turn(
                    turn["id"],
                    status="failed",
                    failure_code="worker_lost",
                    retryable=True,
                    error="Previous executor stopped; start a new operation to retry",
                )

    async def close(self):
        if self._monitor:
            self._monitor.cancel()
            with suppress(asyncio.CancelledError):
                await self._monitor
        if self.container:
            await self.container.runtime_registry.close(drain_timeout_seconds=0)
            await self.container.close()
        await self.lease.close()
        await self.db.__aexit__()

    @asynccontextmanager
    async def sdk(self, token):
        from deeptutor.app.facade import DeepTutorApp
        from deeptutor.core.providers import provider_context

        identity = await self.identity.authenticate(token)
        with provider_context(self.providers), identity_context(identity, token):
            yield DeepTutorApp(container=self.container)


def create_application(deployment: DeploymentConfig):
    from .api.application import create_application as assemble

    return assemble(Enterprise(deployment))
