"""企业显式组合根：运行只 verify，不读取 local app、不自动迁移。"""

import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
from importlib.metadata import PackageNotFoundError, version
import logging
import os

from jose import JWTError, jwt
from packaging.specifiers import SpecifierSet

from deeptutor.persistence.postgres.executor import ExecutorLease
from deeptutor.persistence.postgres.identity.service import IdentityService
from deeptutor.persistence.postgres.session import PostgresSessionStore
from deeptutor.persistence.postgres.tenant_state import validate_tenant_business_values

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

    def __init__(self, *args, bootstrap_resolver, lifecycle_gate=None, **kwargs):
        super().__init__(*args, bootstrap_secret=None, **kwargs)
        self._bootstrap_resolver = bootstrap_resolver
        self._lifecycle_gate = lifecycle_gate

    async def _authenticate(self, c, token, *, lock=False):
        identity = await super()._authenticate(c, token, lock=lock)
        if self._lifecycle_gate is not None:
            await self._lifecycle_gate(c)
        return identity

    async def _issue_session(self, c, row, **kwargs):
        if self._lifecycle_gate is not None:
            await self._lifecycle_gate(c)
        return await super()._issue_session(c, row, **kwargs)

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
            lifecycle_gate=self._require_current_lifecycle_proof,
            token_seconds=deployment.token_seconds,
        )
        self.container = None
        self._monitor = None
        self._webhook_monitor_task = None
        self.webhook_metrics = {
            "monitor_failures": 0,
            "delivery_conflicts": 0,
            "delivery_failures": 0,
            "signature_rejections": 0,
        }
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
        self.eduplus2_webhook_secret = ""
        self.eduplus2_webhook_previous_secret = ""
        self.eduplus2_webhook_previous_until = 0
        self.eduplus2_webhook_inbox_digest_key = ""
        self.eduplus2_lifecycle_receiver_enabled = False
        self.eduplus2_lifecycle_proof_ttl_seconds = 30
        self.eduplus2_signing_key = ""
        self.eduplus2_issuer = ""
        # OMS 身份服务必须由已核实的外部合同显式装配；缺配置时正式入口失败关闭。
        self.oms_platform_verifier = None
        self.oms_account_status = None
        self._configure_eduplus2_from_env()

    async def _require_current_lifecycle_proof(self, c):
        """企业入口在签发/复验会话时核对本地 Webhook 投影。"""

        tenant = await (
            await c.execute(
                "SELECT external_eligibility,external_tid,provisioning_status,recovery_state "
                "FROM enterprise.tenants WHERE id=%s",
                (self.deployment.tenant_id,),
            )
        ).fetchone()
        if not tenant:
            raise PermissionError("school lifecycle unavailable")
        validate_tenant_business_values(tenant)
        if not self.eduplus2_lifecycle_receiver_enabled and tenant["external_tid"] is None:
            return
        if tenant["external_eligibility"] == "not_required" and tenant["external_tid"] is None:
            return
        if tenant["external_eligibility"] != "allowed" or not tenant["external_tid"]:
            raise PermissionError("school lifecycle unavailable")
        states = await (
            await c.execute(
                "SELECT p.eligibility,p.binding_version,p.onboarding_event_id,"
                "p.onboarding_completed_at,k.frozen,k.version AS control_version,b.version "
                "FROM oms.school_bindings b "
                "JOIN eduplus2.webhook_school_state p "
                "ON p.external_tenant_id=b.eduplus_tenant_id "
                "AND p.school_id=b.tenant_id "
                "LEFT JOIN eduplus2.webhook_school_controls k "
                "ON (k.tenant_id,k.school_id,k.external_app_id)="
                "(p.tenant_id,p.school_id,p.external_app_id) "
                "WHERE b.tenant_id=%s AND b.status='verified' "
                "AND b.eduplus_tenant_id::text=%s "
                "AND p.tenant_id=%s LIMIT 2",
                (
                    self.deployment.tenant_id,
                    tenant["external_tid"],
                    self.deployment.tenant_id,
                ),
            )
        ).fetchall()
        # 此固定租户旧会话没有目标应用身份，多个应用时不能任选一个放行。
        if len(states) != 1 or not (
            states[0]["eligibility"] == "allowed"
            and states[0]["binding_version"] == states[0]["version"]
            and states[0]["onboarding_event_id"] is not None
            and states[0]["onboarding_completed_at"] is not None
            and states[0]["control_version"] is not None
            and not states[0]["frozen"]
        ):
            raise PermissionError("school lifecycle unavailable")

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
        self.eduplus2_issuer = issuer
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
        webhook_secret_ref = os.environ.get("DT_EDUPLUS2_WEBHOOK_SECRET_REF", "").strip()
        if not webhook_secret_ref and os.environ.get("DT_EDUPLUS2_WEBHOOK_SECRET"):
            webhook_secret_ref = "env:DT_EDUPLUS2_WEBHOOK_SECRET"
        if webhook_secret_ref:
            self.eduplus2_webhook_secret = resolve_secret(webhook_secret_ref)
        previous_webhook_ref = os.environ.get("DT_EDUPLUS2_WEBHOOK_PREVIOUS_SECRET_REF", "").strip()
        if previous_webhook_ref:
            self.eduplus2_webhook_previous_secret = resolve_secret(previous_webhook_ref)
        previous_until = os.environ.get("DT_EDUPLUS2_WEBHOOK_PREVIOUS_UNTIL", "").strip()
        if previous_until.isascii() and previous_until.isdecimal():
            self.eduplus2_webhook_previous_until = int(previous_until)
        inbox_digest_ref = os.environ.get("DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY_REF", "").strip()
        if not inbox_digest_ref and os.environ.get("DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY"):
            inbox_digest_ref = "env:DT_EDUPLUS2_WEBHOOK_INBOX_DIGEST_KEY"
        if inbox_digest_ref:
            self.eduplus2_webhook_inbox_digest_key = resolve_secret(inbox_digest_ref)
        self.eduplus2_lifecycle_receiver_enabled = (
            os.environ.get("DT_EDUPLUS2_LIFECYCLE_RECEIVER_ENABLED", "").strip().lower() == "true"
        )
        try:
            proof_ttl = int(
                os.environ.get(
                    "DT_EDUPLUS2_LIFECYCLE_PROOF_TTL_SECONDS",
                    str(self.eduplus2_lifecycle_proof_ttl_seconds),
                )
            )
        except ValueError:
            proof_ttl = self.eduplus2_lifecycle_proof_ttl_seconds
        self.eduplus2_lifecycle_proof_ttl_seconds = max(1, min(proof_ttl, 60))
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
        oms_requested = (
            os.environ.get("DT_EDUPLUS2_OMS_ENABLED", "").strip().lower() == "true"
            or any(
                os.environ.get(name)
                for name in (
                    "DT_EDUPLUS2_OMS_DISCOVERY_URL",
                    "DT_EDUPLUS2_OMS_OIDC_ISSUER",
                    "DT_EDUPLUS2_OMS_AUDIENCE",
                    "DT_EDUPLUS2_OMS_CLIENT_ID",
                    "DT_EDUPLUS2_OMS_ACCOUNT_STATUS_URL",
                )
            )
        )
        if oms_requested:
            from .oms.identity import (
                BearerAccountStatusClient,
                PlatformOidcJwtVerifier,
                TokenOnlyAccountStatusClient,
            )

            oms_discovery_url = os.environ.get("DT_EDUPLUS2_OMS_DISCOVERY_URL", "").strip() or discovery_url
            oms_issuer = os.environ.get("DT_EDUPLUS2_OMS_OIDC_ISSUER", "").strip() or issuer
            oms_client_id = (
                os.environ.get("DT_EDUPLUS2_OMS_CLIENT_ID", "").strip()
                or "eduplus-platform-admin"
            )
            oms_audience = (
                os.environ.get("DT_EDUPLUS2_OMS_AUDIENCE", "").strip() or oms_client_id
            )
            oms_status_url, oms_status_disabled = _optional_url_env(
                "DT_EDUPLUS2_OMS_ACCOUNT_STATUS_URL"
            )
            if not oms_status_url and base_url and not oms_status_disabled:
                oms_status_url = base_url + "/api/v1/me/profile"
            if not (
                oms_discovery_url
                and oms_issuer
                and oms_audience
                and oms_client_id
                and (oms_status_url or oms_status_disabled)
            ):
                raise RuntimeError("OMS identity configuration is incomplete")
            self.oms_platform_verifier = PlatformOidcJwtVerifier(
                discovery_url=oms_discovery_url,
                issuer=oms_issuer,
                audience=oms_audience,
                client_id=oms_client_id,
            )
            self.oms_account_status = (
                TokenOnlyAccountStatusClient()
                if oms_status_disabled
                else BearerAccountStatusClient(profile_url=oms_status_url)
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
        if self.eduplus2_lifecycle_receiver_enabled and (
            not self.eduplus2_webhook_secret
            or len(self.eduplus2_webhook_inbox_digest_key) < 32
            or not self.eduplus2_issuer
            or hmac.compare_digest(
                self.eduplus2_webhook_inbox_digest_key, self.eduplus2_webhook_secret
            )
            or (
                self.eduplus2_webhook_previous_secret
                and hmac.compare_digest(
                    self.eduplus2_webhook_inbox_digest_key,
                    self.eduplus2_webhook_previous_secret,
                )
            )
        ):
            raise RuntimeError("lifecycle receiver configuration is incomplete or unsafe")

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

        from .oms.runtime_skills import enterprise_skill_service_factory
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
                        "SELECT bootstrap_completed,auth_epoch,external_tid,local_enabled,"
                        "external_eligibility,provisioning_status,recovery_state "
                        "FROM enterprise.tenants WHERE id=%s",
                        (str(self.deployment.tenant_id),),
                    )
                ).fetchone()
                if tenant:
                    validate_tenant_business_values(tenant)
                if not tenant or not (
                    tenant["bootstrap_completed"]
                    and tenant["auth_epoch"] == self.identity.epoch
                    and (
                        self.eduplus2_lifecycle_receiver_enabled
                        or tenant["external_tid"] is not None
                        or (
                            tenant["local_enabled"]
                            and tenant["provisioning_status"] == "ready"
                            and tenant["recovery_state"] == "normal"
                            and tenant["external_eligibility"] in {"allowed", "not_required"}
                        )
                    )
                ):
                    raise RuntimeError("fixed tenant is not initialized or available")
            self.store_provider = StoreProvider(self)
            skill_service_factory = enterprise_skill_service_factory(self)
            self.providers = ApplicationProviders(
                store=self.store_provider,
                configuration=self.configuration,
                object_store=self.object_store,
                skill_service_factory=skill_service_factory,
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
                requires_singleton_lease = _requires_singleton_executor_lease(coordination_settings)
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
                    skill_service_factory=skill_service_factory,
                )
                await self.container.start()
                await self.recover()
            # 生命周期由已验签 Webhook 同事务投影；仅启动只读聚合监测。
            if self.eduplus2_lifecycle_receiver_enabled:
                self._webhook_monitor_task = asyncio.create_task(self._webhook_monitor_loop())
            if requires_singleton_lease:
                self._monitor = asyncio.create_task(self._watch_executor())
        except BaseException:
            await self.lease.close()
            await self.db.__aexit__()
            raise

    async def _runtime_coordination_guard(self):
        if self.container is not None and not await self.container.coordinator.health():
            raise RuntimeError("turn coordination backend is unavailable")

    async def _webhook_monitor_loop(self):
        from .eduplus2.webhook_authority import snapshot_webhook_authority_metrics

        while True:
            try:
                self.webhook_metrics.update(await snapshot_webhook_authority_metrics(self))
                if self.webhook_metrics.get("legacy_pending_events", 0):
                    logging.getLogger(__name__).warning(
                        "EduPlus2 historical webhook inbox has pending rows"
                    )
                if self.webhook_metrics.get("quiet_schools", 0):
                    logging.getLogger(__name__).warning(
                        "EduPlus2 schools have no recent subscription delivery; "
                        "external state cannot be inferred"
                    )
                if self.webhook_metrics.get("stored_events", 0) >= 1_000_000:
                    logging.getLogger(__name__).warning(
                        "EduPlus2 webhook inbox capacity review is required; "
                        "idempotency facts must not be deleted automatically"
                    )
            except Exception:
                self.webhook_metrics["monitor_failures"] += 1
                logging.getLogger(__name__).warning("EduPlus2 webhook aggregate monitoring failed")
            await asyncio.sleep(60)

    async def _watch_executor(self):
        while True:
            await asyncio.sleep(1)
            try:
                await self.lease.check()
            except RuntimeError:
                await self.container.runtime_registry.close(drain_timeout_seconds=0)
                return

    async def authorize(self):
        if self.container is None or _requires_singleton_executor_lease(self.container.settings):
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
        if self._webhook_monitor_task:
            self._webhook_monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._webhook_monitor_task
            self._webhook_monitor_task = None
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
