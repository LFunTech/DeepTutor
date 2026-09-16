"""PostgreSQL-only 部署配置与 Secret 引用解析。

模块只处理显式传入的值或文件，不加载 ``.env``、用户 settings，也不建立
目录、数据库或连接池。数据库凭证以不透明值返回，避免进入配置 dump、repr
或校验异常。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from psycopg.conninfo import conninfo_to_dict

CANONICAL_DATABASE_SECRET = "DEEPTUTOR_DATABASE_URL"
CANONICAL_MIGRATION_DATABASE_SECRET = "DEEPTUTOR_MIGRATION_DATABASE_URL"

_SECRET_REFERENCE = re.compile(r"env:[A-Za-z_][A-Za-z0-9_]*\Z")
_RESOURCE = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_URI_PREFIX = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_SAFE_MESSAGES = {
    "postgres_backend_required": (
        "PostgreSQL is required; export legacy SQLite/PocketBase data and configure PostgreSQL"
    ),
    "postgres_bootstrap_secret_missing": "bootstrap Secret is unavailable",
    "postgres_config_missing": "default PostgreSQL deployment configuration is unavailable",
    "postgres_config_conflict": "conflicting PostgreSQL Secret values are configured",
    "postgres_config_invalid": "PostgreSQL deployment configuration is invalid",
    "postgres_dsn_invalid": (
        "PostgreSQL DSN must explicitly identify a database and database user"
    ),
    "postgres_identity_secret_invalid": "identity Secret configuration is invalid",
    "postgres_identity_secret_missing": "required identity Secret is unavailable",
    "postgres_migration_secret_missing": "migration PostgreSQL Secret is unavailable",
    "postgres_migration_not_separate": (
        "migration PostgreSQL credentials must be separate from runtime credentials"
    ),
    "postgres_secret_missing": "runtime PostgreSQL Secret is unavailable",
    "postgres_tenant_unavailable": "configured PostgreSQL tenant is unavailable",
    "production_data_provider_required": (
        "production runtime requires external data providers; local data authority is disabled"
    ),
}


class PostgresConfigurationError(ValueError):
    """仅暴露稳定 code 与安全说明，不保留原输入或驱动异常。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"{code}: {_SAFE_MESSAGES[code]}")


@dataclass(frozen=True, slots=True)
class SecretReference:
    """环境变量 Secret 引用；对象本身不包含 Secret 值。"""

    name: str

    @classmethod
    def parse(cls, value: object) -> SecretReference:
        if not isinstance(value, str) or not _SECRET_REFERENCE.fullmatch(value):
            raise PostgresConfigurationError("postgres_config_invalid")
        return cls(value[4:])

    @classmethod
    def environment(cls, name: object) -> SecretReference:
        return cls.parse("env:" + name if isinstance(name, str) else name)

    def as_config_value(self) -> str:
        return "env:" + self.name


class SecretValue:
    """显式使用 ``reveal`` 才能取得内存中的 Secret。"""

    __slots__ = ("__value",)

    def __init__(self, value: str):
        object.__setattr__(self, "_SecretValue__value", value)

    def __setattr__(self, name, value):
        raise AttributeError("SecretValue is immutable")

    def reveal(self) -> str:
        return self.__value

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    __str__ = __repr__

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


@dataclass(frozen=True, slots=True)
class IdentitySecretValues:
    signing_key: SecretValue
    auth_epoch: SecretValue
    bootstrap_secret: SecretValue | None = None


@dataclass(frozen=True, slots=True)
class PostgresDeploymentConfig:
    """默认发行与企业 adapter 共用的不可变 PostgreSQL 配置值对象。"""

    version: int
    tenant_id: UUID
    resource: str
    signing_secret: SecretReference
    auth_epoch_secret: SecretReference
    bootstrap_secret: SecretReference | None
    database_secret: SecretReference
    migration_database_secret: SecretReference
    storage_backend: str
    max_size: int
    max_waiting: int
    timeout: float
    statement_timeout_ms: int
    transaction_timeout_ms: int
    token_seconds: int
    backend_workers: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PostgresDeploymentConfig:
        return cls._from_mapping(raw, enterprise_adapter=False)

    @classmethod
    def from_deployment(cls, deployment: object) -> PostgresDeploymentConfig:
        """按字段协议适配外部部署对象，core 不导入企业包。"""

        keys = (
            "version",
            "tenant_id",
            "resource",
            "signing_secret",
            "auth_epoch_secret",
            "bootstrap_secret",
            "database_secret",
            "migration_database_secret",
            "storage_backend",
            "max_size",
            "max_waiting",
            "timeout",
            "statement_timeout_ms",
            "transaction_timeout_ms",
            "token_seconds",
            "backend_workers",
        )
        try:
            raw = {key: getattr(deployment, key) for key in keys if hasattr(deployment, key)}
        except Exception:
            raise PostgresConfigurationError("postgres_config_invalid") from None
        return cls._from_mapping(raw, enterprise_adapter=True)

    @classmethod
    def _from_mapping(
        cls, raw: Mapping[str, Any], *, enterprise_adapter: bool
    ) -> PostgresDeploymentConfig:
        if not isinstance(raw, Mapping):
            raise PostgresConfigurationError("postgres_config_invalid")
        legacy_fields = {
            "database_path",
            "db_path",
            "pocketbase_url",
            "pocketbase_backend",
            "sqlite_path",
        }
        if legacy_fields.intersection(raw):
            raise PostgresConfigurationError("postgres_backend_required")
        allowed = {
            "version",
            "tenant_id",
            "resource",
            "signing_secret",
            "auth_epoch_secret",
            "bootstrap_secret",
            "database_secret",
            "migration_database_secret",
            "storage_backend",
            "max_size",
            "max_waiting",
            "timeout",
            "statement_timeout_ms",
            "transaction_timeout_ms",
            "token_seconds",
            "backend_workers",
        }
        if set(raw) - allowed:
            raise PostgresConfigurationError("postgres_config_invalid")
        if raw.get("storage_backend", "postgres") != "postgres":
            raise PostgresConfigurationError("postgres_backend_required")
        try:
            version = raw["version"]
            tenant_id = UUID(str(raw["tenant_id"]))
            resource = raw["resource"]
            signing_secret = SecretReference.parse(raw["signing_secret"])
            auth_epoch_secret = SecretReference.parse(raw["auth_epoch_secret"])
            bootstrap_raw = raw.get("bootstrap_secret")
            bootstrap_secret = (
                SecretReference.parse(bootstrap_raw) if bootstrap_raw is not None else None
            )
            database_secret = SecretReference.parse(
                raw.get("database_secret", "env:" + CANONICAL_DATABASE_SECRET)
            )
            migration_database_secret = SecretReference.parse(
                raw.get(
                    "migration_database_secret",
                    "env:" + CANONICAL_MIGRATION_DATABASE_SECRET,
                )
            )
            max_size = raw.get("max_size", 8)
            max_waiting = raw.get("max_waiting", 16)
            timeout = raw.get("timeout", 10.0)
            statement_timeout_ms = raw.get("statement_timeout_ms", 15_000)
            transaction_timeout_ms = raw.get("transaction_timeout_ms", 30_000)
            token_seconds = raw.get("token_seconds", 3600)
            backend_workers = raw.get("backend_workers", 1)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise PostgresConfigurationError("postgres_config_invalid") from None
        if version != 1 or isinstance(version, bool):
            raise PostgresConfigurationError("postgres_config_invalid")
        if not isinstance(resource, str) or not _RESOURCE.fullmatch(resource):
            raise PostgresConfigurationError("postgres_config_invalid")
        if not enterprise_adapter and database_secret.name == "DT_DATABASE_DSN":
            raise PostgresConfigurationError("postgres_config_invalid")
        if not enterprise_adapter and migration_database_secret.name == "DT_MIGRATION_DSN":
            raise PostgresConfigurationError("postgres_config_invalid")
        if database_secret.name == migration_database_secret.name:
            raise PostgresConfigurationError("postgres_config_invalid")
        for value in (max_size, max_waiting):
            if type(value) is not int or value < 1:
                raise PostgresConfigurationError("postgres_config_invalid")
        for value in (statement_timeout_ms, transaction_timeout_ms):
            if type(value) is not int or not 1 <= value <= 3_600_000:
                raise PostgresConfigurationError("postgres_config_invalid")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 3600
        ):
            raise PostgresConfigurationError("postgres_config_invalid")
        if type(token_seconds) is not int or not 60 <= token_seconds <= 86400:
            raise PostgresConfigurationError("postgres_config_invalid")
        if type(backend_workers) is not int or backend_workers != 1:
            raise PostgresConfigurationError("postgres_config_invalid")
        return cls(
            version=version,
            tenant_id=tenant_id,
            resource=resource,
            signing_secret=signing_secret,
            auth_epoch_secret=auth_epoch_secret,
            bootstrap_secret=bootstrap_secret,
            database_secret=database_secret,
            migration_database_secret=migration_database_secret,
            storage_backend="postgres",
            max_size=max_size,
            max_waiting=max_waiting,
            timeout=float(timeout),
            statement_timeout_ms=statement_timeout_ms,
            transaction_timeout_ms=transaction_timeout_ms,
            token_seconds=token_seconds,
            backend_workers=backend_workers,
        )

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> PostgresDeploymentConfig:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf8"))
            return cls.from_mapping(raw)
        except PostgresConfigurationError:
            raise
        except Exception:
            raise PostgresConfigurationError("postgres_config_invalid") from None

    def connection_kwargs(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "resource": self.resource,
                "max_size": self.max_size,
                "max_waiting": self.max_waiting,
                "timeout": self.timeout,
                "statement_timeout_ms": self.statement_timeout_ms,
                "transaction_timeout_ms": self.transaction_timeout_ms,
            }
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "tenant_id": str(self.tenant_id),
            "resource": self.resource,
            "database_secret": self.database_secret.as_config_value(),
            "migration_database_secret": self.migration_database_secret.as_config_value(),
            "signing_secret": self.signing_secret.as_config_value(),
            "auth_epoch_secret": self.auth_epoch_secret.as_config_value(),
            "bootstrap_secret": (
                self.bootstrap_secret.as_config_value() if self.bootstrap_secret else None
            ),
            "storage_backend": self.storage_backend,
            "max_size": self.max_size,
            "max_waiting": self.max_waiting,
            "timeout": self.timeout,
            "statement_timeout_ms": self.statement_timeout_ms,
            "transaction_timeout_ms": self.transaction_timeout_ms,
            "token_seconds": self.token_seconds,
            "backend_workers": self.backend_workers,
        }

    def _resolve_database(
        self,
        reference: SecretReference,
        *,
        canonical_name: str,
        missing_code: str,
        environ: Mapping[str, str] | None,
    ) -> SecretValue:
        source = os.environ if environ is None else environ
        value = source.get(reference.name)
        if not isinstance(value, str) or not value:
            raise PostgresConfigurationError(missing_code)
        canonical = source.get(canonical_name)
        if (
            reference.name != canonical_name
            and isinstance(canonical, str)
            and canonical
            and canonical != value
        ):
            raise PostgresConfigurationError("postgres_config_conflict")
        _validate_postgres_dsn(value)
        return SecretValue(value)

    def resolve_runtime(self, *, environ: Mapping[str, str] | None = None) -> SecretValue:
        return self._resolve_database(
            self.database_secret,
            canonical_name=CANONICAL_DATABASE_SECRET,
            missing_code="postgres_secret_missing",
            environ=environ,
        )

    def resolve_migration(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        secret_reference: SecretReference | None = None,
    ) -> SecretValue:
        reference = secret_reference or self.migration_database_secret
        if reference.name in (self.database_secret.name, CANONICAL_DATABASE_SECRET):
            raise PostgresConfigurationError("postgres_migration_not_separate")
        resolved = self._resolve_database(
            reference,
            canonical_name=CANONICAL_MIGRATION_DATABASE_SECRET,
            missing_code="postgres_migration_secret_missing",
            environ=environ,
        )
        source = os.environ if environ is None else environ
        runtime_values = {
            value
            for name in (self.database_secret.name, CANONICAL_DATABASE_SECRET)
            if isinstance((value := source.get(name)), str) and value
        }
        if resolved.reveal() in runtime_values:
            raise PostgresConfigurationError("postgres_migration_not_separate")
        return resolved

    def resolve_identity(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        include_bootstrap: bool = False,
    ) -> IdentitySecretValues:
        source = os.environ if environ is None else environ
        signing = _identity_secret(source, self.signing_secret)
        epoch = _identity_secret(source, self.auth_epoch_secret)
        if len(signing) < 32 or not epoch:
            raise PostgresConfigurationError("postgres_identity_secret_invalid")
        bootstrap = None
        if include_bootstrap:
            bootstrap = self.resolve_bootstrap(environ=source)
        return IdentitySecretValues(SecretValue(signing), SecretValue(epoch), bootstrap)

    def resolve_bootstrap(self, *, environ: Mapping[str, str] | None = None) -> SecretValue:
        source = os.environ if environ is None else environ
        if self.bootstrap_secret is None:
            raise PostgresConfigurationError("postgres_bootstrap_secret_missing")
        value = source.get(self.bootstrap_secret.name)
        if not isinstance(value, str) or not value:
            raise PostgresConfigurationError("postgres_bootstrap_secret_missing")
        if len(value) < 32:
            raise PostgresConfigurationError("postgres_identity_secret_invalid")
        return SecretValue(value)


def _identity_secret(source: Mapping[str, str], reference: SecretReference) -> str:
    if reference.name not in source:
        raise PostgresConfigurationError("postgres_identity_secret_missing")
    value = source.get(reference.name)
    if not isinstance(value, str) or not value:
        raise PostgresConfigurationError("postgres_identity_secret_invalid")
    return value


def _validate_postgres_dsn(value: str) -> None:
    try:
        candidate = value.lstrip()
        if _URI_PREFIX.match(candidate):
            parsed = urlsplit(candidate)
            if parsed.scheme not in ("postgres", "postgresql"):
                raise ValueError
        parsed_dsn = conninfo_to_dict(value)
        if not parsed_dsn.get("user") or not parsed_dsn.get("dbname"):
            raise ValueError
    except Exception:
        # psycopg 的解析错误可能包含完整 conninfo，绝不链接原异常。
        raise PostgresConfigurationError("postgres_dsn_invalid") from None
