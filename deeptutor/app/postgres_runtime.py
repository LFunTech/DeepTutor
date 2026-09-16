"""默认 PostgreSQL-only 应用组合。

这里是默认 Web/API/CLI/SDK 的进程级 PG 装配边界：读取显式部署配置，
解析 Secret 引用，启动时校验 schema/受限角色/执行权，并按当前认证身份
派生 tenant/owner 作用域。模块 import 本身不连接数据库、不读取 Secret。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path

from deeptutor.persistence.postgres.configuration import (
    IdentitySecretValues,
    PostgresConfigurationError,
    PostgresDeploymentConfig,
)
from deeptutor.persistence.postgres.connection import Database, SyncDatabase
from deeptutor.persistence.postgres.executor import ExecutorLease
from deeptutor.persistence.postgres.identity.service import IdentityService
from deeptutor.persistence.postgres.learning import ExecutionAuthority
from deeptutor.persistence.postgres.migrations.runner import MigrationRunner
from deeptutor.persistence.postgres.offline_import.maintenance import install_maintenance_guards
from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore
from deeptutor.persistence.postgres.scope import TenantScope
from deeptutor.persistence.postgres.session import PostgresSessionStore
from deeptutor.persistence.resources import OwnerResourceProvider
from deeptutor.runtime.home import get_runtime_data_root, get_runtime_home
from deeptutor.services.auth import PostgresAuthProvider

DEFAULT_POSTGRES_CONFIG_ENV = "DEEPTUTOR_POSTGRES_CONFIG"
DEFAULT_POSTGRES_CONFIG_RELATIVE = Path("config") / "postgres.json"
DEFAULT_RESOURCE_ROOT_RELATIVE = Path("data") / "postgres-resources"


def default_postgres_config_path(
    *, environ: Mapping[str, str] | None = None, home: str | Path | None = None
) -> Path:
    """返回默认部署配置路径；不创建文件或目录。"""

    source = os.environ if environ is None else environ
    configured = str(source.get(DEFAULT_POSTGRES_CONFIG_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (get_runtime_home(home) / DEFAULT_POSTGRES_CONFIG_RELATIVE).resolve()


def load_default_postgres_config(
    *, environ: Mapping[str, str] | None = None, home: str | Path | None = None
) -> PostgresDeploymentConfig:
    path = default_postgres_config_path(environ=environ, home=home)
    if not path.is_file():
        raise PostgresConfigurationError("postgres_config_missing")
    return PostgresDeploymentConfig.from_file(path)


class _ScopedProvider:
    def __init__(self, runtime: "DefaultPostgresRuntime") -> None:
        self.runtime = runtime


class DefaultPostgresStoreProvider(_ScopedProvider):
    def get(self) -> PostgresSessionStore:
        return self.runtime.session_store_for_current_user()


class DefaultPostgresLearningProvider(_ScopedProvider):
    def get(self):
        return self.runtime.learning_runtime_for_current_user()


class DefaultPostgresReadingProvider(_ScopedProvider):
    def get(self) -> AsyncReadingCatalogStore:
        return self.runtime.reading_store_for_current_user()


class DefaultPostgresMarginNoteProvider(_ScopedProvider):
    def get(self, kb_id: str):
        return self.runtime.marginnote_store_for_current_user(kb_id)


@dataclass(slots=True)
class DefaultPostgresRuntime:
    """一个进程级 PG runtime；每个请求再由当前 token 派生 owner scope。"""

    config: PostgresDeploymentConfig
    runtime_dsn: str = field(repr=False)
    identity_values: IdentitySecretValues = field(repr=False)
    cookie_secure: bool
    resource_root: Path | None
    object_store: object | None = None
    db: Database = field(init=False, repr=False)
    sync_db: SyncDatabase = field(init=False, repr=False)
    executor: ExecutorLease = field(init=False, repr=False)
    resources: OwnerResourceProvider | None = field(init=False)
    identity: IdentityService = field(init=False, repr=False)
    auth_provider: PostgresAuthProvider = field(init=False)
    store_provider: DefaultPostgresStoreProvider = field(init=False)
    learning_provider: DefaultPostgresLearningProvider = field(init=False)
    reading_provider: DefaultPostgresReadingProvider = field(init=False)
    marginnote_provider: DefaultPostgresMarginNoteProvider = field(init=False)
    _started: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        kwargs = dict(self.config.connection_kwargs())
        self.db = Database(self.runtime_dsn, **kwargs)
        self.sync_db = SyncDatabase(self.runtime_dsn, **kwargs)
        install_maintenance_guards(self.db, tenant_id=str(self.config.tenant_id))
        install_maintenance_guards(self.sync_db, tenant_id=str(self.config.tenant_id))
        self.executor = ExecutorLease(self.runtime_dsn, resource=self.config.resource)
        self.resources = (
            None
            if self.object_store is not None
            else OwnerResourceProvider(self.resource_root)
        )
        self.identity = IdentityService(
            self.db,
            tenant_id=str(self.config.tenant_id),
            signing_key=self.identity_values.signing_key.reveal(),
            auth_epoch=self.identity_values.auth_epoch.reveal(),
            # 默认业务启动不创建首位管理员；bootstrap 只能走受控 CLI。
            bootstrap_secret=None,
            token_seconds=self.config.token_seconds,
        )
        self.auth_provider = PostgresAuthProvider(
            self.identity,
            resources=self.resources,
            cookie_secure=self.cookie_secure,
        )
        self.store_provider = DefaultPostgresStoreProvider(self)
        self.learning_provider = DefaultPostgresLearningProvider(self)
        self.reading_provider = DefaultPostgresReadingProvider(self)
        self.marginnote_provider = DefaultPostgresMarginNoteProvider(self)

    @classmethod
    def from_environment(
        cls,
        *,
        cookie_secure: bool = True,
        environ: Mapping[str, str] | None = None,
        home: str | Path | None = None,
    ) -> "DefaultPostgresRuntime":
        source = os.environ if environ is None else environ
        config = load_default_postgres_config(environ=source, home=home)
        data_root = get_runtime_data_root(home)
        object_store = cls._object_store_from_environment(source)
        cls._verify_runtime_data_authority(
            source,
            data_root,
            owner_resources="objectstore" if object_store is not None else "local",
        )
        return cls(
            config=config,
            runtime_dsn=config.resolve_runtime(environ=source).reveal(),
            identity_values=config.resolve_identity(environ=source),
            cookie_secure=cookie_secure,
            resource_root=(
                None
                if object_store is not None
                else (data_root / DEFAULT_RESOURCE_ROOT_RELATIVE.name).resolve()
            ),
            object_store=object_store,
        )

    @staticmethod
    def _object_store_from_environment(environ: Mapping[str, str]) -> object | None:
        configured = any(
            str(environ.get(name) or "").strip()
            for name in (
                "DEEPTUTOR_OBJECTSTORE_ENDPOINT",
                "DEEPTUTOR_OBJECTSTORE_REGION",
                "DEEPTUTOR_OBJECTSTORE_BUCKET",
                "DEEPTUTOR_OBJECTSTORE_ACCESS_KEY_REF",
                "DEEPTUTOR_OBJECTSTORE_SECRET_KEY_REF",
                "DEEPTUTOR_OBJECTSTORE_SESSION_TOKEN_REF",
            )
        )
        if not configured:
            return None
        try:
            from deeptutor.runtime.externalized_providers import (
                EnvSecretResolver,
                S3CompatibleObjectStore,
                S3ObjectStoreConfig,
            )

            return S3CompatibleObjectStore(
                S3ObjectStoreConfig.from_environment(environ),
                secret_resolver=EnvSecretResolver(),
            )
        except ValueError:
            raise PostgresConfigurationError("production_data_provider_required") from None

    @staticmethod
    def _verify_runtime_data_authority(
        environ: Mapping[str, str], data_root: Path, *, owner_resources: str
    ) -> None:
        from deeptutor.runtime.data_gate import RuntimeDataGate, RuntimeMode

        report = RuntimeDataGate(data_root, mode=RuntimeMode.from_environ(environ)).evaluate(
            active_authorities={"owner_resources": owner_resources}
        )
        if not report.ready:
            raise PostgresConfigurationError("production_data_provider_required")

    def _verify_object_store_ready(self) -> None:
        if self.object_store is None:
            return
        check_bucket = getattr(self.object_store, "check_bucket", None)
        if not callable(check_bucket):
            raise PostgresConfigurationError("production_data_provider_required")
        status = check_bucket()
        if not getattr(status, "available", False):
            raise PostgresConfigurationError("production_data_provider_required")

    async def start(self) -> None:
        if self._started:
            return
        self._verify_object_store_ready()
        opened_db = False
        opened_sync = False
        acquired_executor = False
        try:
            # 启动只 verify；schema apply/import 必须由维护命令显式执行。
            await MigrationRunner(self.runtime_dsn).verify()
            await self.db.__aenter__()
            opened_db = True
            await self.sync_db.__aenter__()
            opened_sync = True
            await self.executor.acquire()
            acquired_executor = True
            await self._verify_tenant_ready()
        except BaseException:
            if acquired_executor:
                await self.executor.close()
            if opened_sync:
                await self.sync_db.__aexit__(None, None, None)
            if opened_db:
                await self.db.__aexit__(None, None, None)
            raise
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
        try:
            await self.executor.close()
        finally:
            try:
                await self.sync_db.__aexit__(None, None, None)
            finally:
                await self.db.__aexit__(None, None, None)
                self._started = False

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("PostgreSQL runtime has not started")

    async def _verify_tenant_ready(self) -> None:
        scope = TenantScope(str(self.config.tenant_id), "@identity")
        async with self.db.transaction(scope) as c:
            row = await (
                await c.execute(
                    """SELECT bootstrap_completed,local_enabled,external_eligibility,
                              provisioning_status,auth_epoch,recovery_state
                         FROM enterprise.tenants
                        WHERE id=%s""",
                    (str(self.config.tenant_id),),
                )
            ).fetchone()
        if (
            row is None
            or not row["bootstrap_completed"]
            or not row["local_enabled"]
            or row["external_eligibility"] not in ("not_required", "allowed")
            or row["provisioning_status"] != "ready"
            or row["auth_epoch"] != self.identity.epoch
            or row["recovery_state"] != "normal"
        ):
            raise PostgresConfigurationError("postgres_tenant_unavailable")

    def scope_for_current_user(self) -> TenantScope:
        self._require_started()
        from deeptutor.multi_user.context import get_current_user

        user = get_current_user()
        expected_tenant = str(self.config.tenant_id)
        if (
            user.scope.kind != "tenant"
            or user.scope.tenant_id != expected_tenant
            or user.id != user.scope.user_id
            or user.role not in ("tenant_admin", "user")
        ):
            raise PermissionError("PostgreSQL tenant identity is required")
        return TenantScope(expected_tenant, user.id)

    async def authorize_current_user(self) -> None:
        self.scope_for_current_user()
        await self.executor.check()

    def _sync_executor_guard(self) -> None:
        # SyncDatabase 的 guard 必须同步；完整执行权由 LearningRuntime 的
        # authorize/ExecutionAuthority 在异步边界和事务内共同验证。
        if not self.executor.active:
            raise RuntimeError("executor authority unavailable")

    def session_store_for_current_user(self) -> PostgresSessionStore:
        scope = self.scope_for_current_user()
        return PostgresSessionStore(self.db, scope)

    def learning_runtime_for_current_user(self):
        from deeptutor.learning.runtime import LearningRuntime

        scope = self.scope_for_current_user()
        return LearningRuntime(
            self.sync_db,
            scope,
            executor=self.executor,
            session_store=PostgresSessionStore(self.db, scope),
            authorize=self.authorize_current_user,
            authority=ExecutionAuthority(self.executor),
        )

    def reading_store_for_current_user(self) -> AsyncReadingCatalogStore:
        return AsyncReadingCatalogStore(self.sync_db, self.scope_for_current_user())

    def marginnote_store_for_current_user(self, kb_id: str):
        return self.marginnote_store_for_scope(self.scope_for_current_user(), kb_id)

    def marginnote_store_for_scope(self, scope: TenantScope, kb_id: str):
        self._require_started()
        from deeptutor.persistence.postgres.marginnote import PostgresMarginNoteStore

        return PostgresMarginNoteStore(self.sync_db, scope, kb_id=kb_id)

    async def recover_once(self) -> int:
        """恢复 PG learning 租约；不扫描本地用户目录、不触发模型。"""

        self._require_started()
        # 1.17 会补全跨用户恢复矩阵；当前至少保证默认后台不再扫描旧 local 目录。
        return 0


__all__ = [
    "DEFAULT_POSTGRES_CONFIG_ENV",
    "DEFAULT_POSTGRES_CONFIG_RELATIVE",
    "DEFAULT_RESOURCE_ROOT_RELATIVE",
    "DefaultPostgresLearningProvider",
    "DefaultPostgresMarginNoteProvider",
    "DefaultPostgresReadingProvider",
    "DefaultPostgresRuntime",
    "DefaultPostgresStoreProvider",
    "default_postgres_config_path",
    "load_default_postgres_config",
]
