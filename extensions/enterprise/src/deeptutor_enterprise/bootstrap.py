"""企业显式组合根：运行只 verify，不读取 local app、不自动迁移。"""

import asyncio
from contextlib import asynccontextmanager, suppress
from importlib.metadata import PackageNotFoundError, version
import os

from jose import JWTError, jwt
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

_DISABLED_OPTIONAL_URL_VALUES = {"0", "false", "off", "no", "none", "disabled"}


def _optional_url_env(name: str) -> tuple[str, bool]:
    value = os.environ.get(name, "").strip()
    disabled = value.lower() in _DISABLED_OPTIONAL_URL_VALUES
    return ("" if disabled else value), disabled


def _build_enterprise_runtime_coordination():
    """按部署环境变量构建企业组合根的 turn coordination。

    单副本默认继续使用 memory coordination，且每个 scope 保持独立 coordinator；
    多副本/HPA 场景由发布契约注入 Redis 配置，让所有 Pod 共享 turn lease、
    fencing token、事件流和命令流。企业入口不能读取本地 runtime settings 文件，
    否则会重新引入本地 `data/` 权威。
    """

    from deeptutor.runtime.coordination import (
        CoordinationSettings,
        MemoryCoordinator,
        RedisCoordinator,
    )

    settings = CoordinationSettings.from_runtime_settings(
        {
            "backend_workers": (
                os.environ.get("DEEPTUTOR_BACKEND_WORKERS")
                or os.environ.get("BACKEND_WORKERS")
                or 1
            )
        },
        {
            "turn_coordination": {
                "backend": os.environ.get("DEEPTUTOR_TURN_COORDINATION_BACKEND", "memory"),
                "redis_url": os.environ.get("DEEPTUTOR_REDIS_URL", ""),
                "key_prefix": os.environ.get("DEEPTUTOR_REDIS_KEY_PREFIX", "deeptutor"),
            }
        },
    )
    if settings.backend == "redis":
        return (
            settings,
            RedisCoordinator(
                settings.redis_url,
                key_prefix=settings.key_prefix,
                lease_ttl_seconds=settings.lease_ttl_seconds,
                stream_retention_seconds=settings.stream_retention_seconds,
            ),
            None,
        )

    def memory_factory():
        return MemoryCoordinator(lease_ttl_seconds=settings.lease_ttl_seconds)

    return settings, memory_factory(), memory_factory


def _requires_singleton_executor_lease(coordination_settings) -> bool:
    """是否需要沿用单执行者 PG advisory lock。

    Redis coordination 表示 backend Pod 之间通过共享 turn lease、fencing token、
    事件流和命令流协同；继续持有全局 `ExecutorLease` 会把多副本退化成单副本。
    """

    return getattr(coordination_settings, "backend", "memory") != "redis"


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


def _core_version() -> str:
    try:
        return version("deeptutor")
    except PackageNotFoundError:
        from deeptutor.__version__ import __version__

        return __version__


class Enterprise:
    def __init__(self, deployment):
        if _core_version() not in SpecifierSet(CORE_COMPATIBILITY):
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
        self.object_store = self._object_store_from_deployment(deployment)
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
        self.eduplus2_resolver = None
        self.eduplus2_verifier = None
        self.eduplus2_profile_client = None
        self.eduplus2_permission_client = None
        self.eduplus2_allowed_clients = ()
        self.eduplus2_dt_token_seconds = min(1800, self.identity.token_seconds)
        self.eduplus2_refresh_deadline_leeway_seconds = 30
        self.eduplus2_revocation_cache_ttl_seconds = 30
        self.eduplus2_audit_export_storage_ref = "db://eduplus2/audit-export"
        self.eduplus2_revocation_webhook_secret = ""
        self.eduplus2_signing_key = ""
        self.eduplus2_issuer = ""
        self._configure_eduplus2_from_env()

    @staticmethod
    def _object_store_from_deployment(deployment):
        binding = getattr(deployment, "object_store", None)
        if binding is None:
            return None
        from deeptutor.runtime.externalized_providers import (
            EnvSecretResolver,
            S3CompatibleObjectStore,
            S3ObjectStoreConfig,
            SecretRef,
        )

        return S3CompatibleObjectStore(
            S3ObjectStoreConfig(
                endpoint=binding.endpoint,
                region=binding.region,
                bucket=binding.bucket,
                access_key_ref=SecretRef.parse(binding.access_key_secret),
                secret_key_ref=SecretRef.parse(binding.secret_key_secret),
                path_style=binding.path_style,
            ),
            secret_resolver=EnvSecretResolver(),
        )

    def _configure_eduplus2_from_env(self):
        """从运行时环境装配 B1-lite provider；缺项时保持未配置并 fail closed。"""

        from .eduplus2.client import (
            EduPlus2OidcJwtVerifier,
            EduPlus2PermissionClient,
            EduPlus2ProfileClient,
            EduPlus2ResolveClient,
            parse_allowed_clients,
        )

        base_url = os.environ.get("DT_EDUPLUS2_BASE_URL", "").rstrip("/")
        discovery_url = os.environ.get("DT_EDUPLUS2_DISCOVERY_URL", "").strip()
        issuer = os.environ.get("DT_EDUPLUS2_OIDC_ISSUER", "").strip()
        jwks_uri = os.environ.get("DT_EDUPLUS2_JWKS_URI", "").strip()
        token_url = os.environ.get("DT_EDUPLUS2_TOKEN_ENDPOINT", "").strip()
        resolve_url = os.environ.get("DT_EDUPLUS2_RESOLVE_URL", "").strip()
        profile_url, profile_disabled = _optional_url_env("DT_EDUPLUS2_PROFILE_URL")
        permission_url, permission_disabled = _optional_url_env("DT_EDUPLUS2_PERMISSION_URL")
        if not resolve_url and base_url:
            resolve_url = base_url + "/api/v1/open/oauth-clients/resolve"
        if not profile_url and base_url and not profile_disabled:
            profile_url = base_url + "/api/v1/open/profile"
        if not permission_url and base_url and not permission_disabled:
            permission_url = base_url + "/api/v1/open/permissions/check"
        client_id = os.environ.get("DT_EDUPLUS2_CLIENT_ID", "").strip()
        secret_ref = os.environ.get("DT_EDUPLUS2_CLIENT_SECRET_REF", "").strip()
        if not secret_ref and os.environ.get("DT_EDUPLUS2_CLIENT_SECRET"):
            secret_ref = "env:DT_EDUPLUS2_CLIENT_SECRET"
        revocation_secret_ref = os.environ.get(
            "DT_EDUPLUS2_REVOCATION_WEBHOOK_SECRET_REF", ""
        ).strip()
        if not revocation_secret_ref and os.environ.get("DT_EDUPLUS2_REVOCATION_WEBHOOK_SECRET"):
            revocation_secret_ref = "env:DT_EDUPLUS2_REVOCATION_WEBHOOK_SECRET"
        if revocation_secret_ref:
            self.eduplus2_revocation_webhook_secret = resolve_secret(revocation_secret_ref)
        try:
            ttl = int(
                os.environ.get(
                    "DT_EDUPLUS2_DT_TOKEN_TTL_SECONDS", str(self.eduplus2_dt_token_seconds)
                )
            )
        except ValueError:
            ttl = self.eduplus2_dt_token_seconds
        self.eduplus2_dt_token_seconds = max(60, min(ttl, self.identity.token_seconds))
        try:
            refresh_deadline = int(
                os.environ.get(
                    "DT_EDUPLUS2_REFRESH_DEADLINE_LEEWAY_SECONDS",
                    str(self.eduplus2_refresh_deadline_leeway_seconds),
                )
            )
        except ValueError:
            refresh_deadline = self.eduplus2_refresh_deadline_leeway_seconds
        self.eduplus2_refresh_deadline_leeway_seconds = max(0, min(refresh_deadline, 3600))
        try:
            revocation_ttl = int(
                os.environ.get(
                    "DT_EDUPLUS2_REVOCATION_CACHE_TTL_SECONDS",
                    str(self.eduplus2_revocation_cache_ttl_seconds),
                )
            )
        except ValueError:
            revocation_ttl = self.eduplus2_revocation_cache_ttl_seconds
        self.eduplus2_revocation_cache_ttl_seconds = max(0, min(revocation_ttl, 3600))
        self.eduplus2_audit_export_storage_ref = (
            os.environ.get(
                "DT_EDUPLUS2_AUDIT_EXPORT_STORAGE_REF",
                self.eduplus2_audit_export_storage_ref,
            )
            .strip()
            .rstrip("/")
            or "db://eduplus2/audit-export"
        )
        self.eduplus2_allowed_clients = parse_allowed_clients(
            os.environ.get("DT_EDUPLUS2_ALLOWED_CLIENTS"),
            default_internal_tenant_id=str(self.deployment.tenant_id),
        )
        if discovery_url:
            self.eduplus2_verifier = EduPlus2OidcJwtVerifier(
                discovery_url=discovery_url,
                issuer=issuer or None,
                jwks_uri=jwks_uri or None,
            )
        if token_url and resolve_url and client_id and secret_ref:
            self.eduplus2_resolver = EduPlus2ResolveClient(
                token_url=token_url,
                resolve_url=resolve_url,
                client_id=client_id,
                client_secret=resolve_secret(secret_ref),
            )
        if token_url and profile_url and client_id and secret_ref:
            self.eduplus2_profile_client = EduPlus2ProfileClient(
                token_url=token_url,
                profile_url=profile_url,
                client_id=client_id,
                client_secret=resolve_secret(secret_ref),
            )
        if token_url and permission_url and client_id and secret_ref:
            self.eduplus2_permission_client = EduPlus2PermissionClient(
                token_url=token_url,
                permission_url=permission_url,
                client_id=client_id,
                client_secret=resolve_secret(secret_ref),
            )

    @property
    def eduplus2(self):
        from .eduplus2.service import EduPlus2AccessService

        resolver = getattr(self, "eduplus2_resolver", None)
        verifier = getattr(self, "eduplus2_verifier", None)
        signing_key = getattr(self, "eduplus2_signing_key", "")
        issuer = getattr(self, "eduplus2_issuer", "")
        if signing_key and issuer:
            from .eduplus2.client import HmacEduPlus2JwtVerifier

            verifier = HmacEduPlus2JwtVerifier(signing_key=signing_key, issuer=issuer)
        if resolver is None or verifier is None:
            raise RuntimeError("EduPlus2 provider is not configured")
        return EduPlus2AccessService(
            self.db,
            identity=self.identity,
            resolver=resolver,
            jwt_verifier=verifier,
            dt_token_seconds=self.eduplus2_dt_token_seconds,
            allowed_clients=self.eduplus2_allowed_clients,
            profile_client=getattr(self, "eduplus2_profile_client", None),
            permission_client=getattr(self, "eduplus2_permission_client", None),
            audit_export_storage_ref=self.eduplus2_audit_export_storage_ref,
            revocation_cache_seconds=self.eduplus2_revocation_cache_ttl_seconds,
        )

    async def start(self):
        from deeptutor.app.container import ApplicationContainer
        from deeptutor.core.providers import ApplicationProviders, provider_context
        from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_SPECS
        from deeptutor.runtime.capability_catalog import CapabilityCatalog
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
            self.store_provider = StoreProvider(self)
            self.providers = ApplicationProviders(
                store=self.store_provider,
                configuration=self.configuration,
                object_store=self.object_store,
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
                (
                    coordination_settings,
                    coordinator,
                    coordinator_factory,
                ) = _build_enterprise_runtime_coordination()
                requires_singleton_lease = _requires_singleton_executor_lease(
                    coordination_settings
                )
                if requires_singleton_lease:
                    await self.lease.acquire()
                    self.db.execution_guard = self.lease.check
                else:
                    self.db.execution_guard = self._runtime_coordination_guard
                self.container = ApplicationContainer(
                    settings=coordination_settings,
                    coordinator=coordinator,
                    worker_id=self.lease.execution_id,
                    store_provider=self.store_provider,
                    turn_environment=TurnEnvironment(self),
                    capability_registry=registry,
                    load_plugins=False,
                    coordinator_factory=coordinator_factory,
                    turn_service_factory=lambda *args: GuardedTurns(self, *args),
                    object_store_provider=self.object_store,
                )
                self.providers = ApplicationProviders(
                    store=self.store_provider,
                    container=self.container,
                    configuration=self.configuration,
                    object_store=self.object_store,
                )
                await self.container.start()
                await self.recover()
            if requires_singleton_lease:
                self._monitor = asyncio.create_task(self._watch_executor())
        except BaseException:
            await self.lease.close()
            await self.db.__aexit__()
            raise

    async def _runtime_coordination_guard(self):
        if self.container is not None and not await self.container.coordinator.health():
            raise RuntimeError("turn coordination backend is unavailable")

    async def _watch_executor(self):
        while True:
            await asyncio.sleep(1)
            try:
                await self.lease.check()
            except RuntimeError:
                await self.container.runtime_registry.close(drain_timeout_seconds=0)
                return

    async def authorize(self):
        if self.container is None or _requires_singleton_executor_lease(
            self.container.settings
        ):
            await self.lease.check()
        else:
            await self._runtime_coordination_guard()
        token = current_token()
        identity = await self.identity.authenticate(token)
        try:
            claims = jwt.get_unverified_claims(token)
        except JWTError:
            claims = {}
        if isinstance(claims.get("eduplus2"), dict):
            await self.eduplus2.ensure_token_allowed(token)
        return identity

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
        if self.container is not None and not _requires_singleton_executor_lease(
            self.container.settings
        ):
            from deeptutor.runtime.coordination import TurnRecoveryService

            for user in users:
                store = PostgresSessionStore(
                    self.db, TenantScope(str(self.deployment.tenant_id), user["id"])
                )
                await TurnRecoveryService(self.container.coordinator, store).recover_once()
            return
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
        try:
            claims = jwt.get_unverified_claims(token)
        except JWTError:
            claims = {}
        if isinstance(claims.get("eduplus2"), dict):
            await self.eduplus2.ensure_token_allowed(token)
        with provider_context(self.providers), identity_context(identity, token):
            yield DeepTutorApp(container=self.container)


def create_application(deployment: DeploymentConfig):
    from .api.application import create_application as assemble

    return assemble(Enterprise(deployment))
