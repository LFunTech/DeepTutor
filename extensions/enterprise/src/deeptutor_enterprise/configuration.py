"""只读、版本化部署配置。Secret 只在执行者内存解析，不提供保存接口。"""

import copy
import json
import os
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from deeptutor.persistence.postgres.configuration import (
    CANONICAL_MIGRATION_DATABASE_SECRET,
    PostgresConfigurationError,
    PostgresDeploymentConfig,
)

SecretReference = Annotated[str, StringConstraints(pattern=r"^env:[A-Za-z_][A-Za-z0-9_]*$")]
EnterpriseAllowedTool = Literal["ask_user", "rag"]


class ModelDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    profile_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str
    secret: SecretReference
    provider: Literal["openai", "anthropic"] = "openai"
    allowed_roles: tuple[Literal["user", "tenant_admin"], ...] = ()
    allowed_user_ids: tuple[str, ...] = ()
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    context_window: int = Field(default=32768, ge=4096)
    request_timeout_seconds: float = Field(default=90, gt=0, le=600, allow_inf_nan=False)
    connect_timeout_seconds: float = Field(default=10, gt=0, le=600, allow_inf_nan=False)
    max_retries: int = Field(default=0, ge=0, le=2)

    @field_validator("base_url")
    @classmethod
    def secure_endpoint(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("model endpoint must be HTTPS without credentials/query")
        return value.rstrip("/")


class _HttpsEndpointMixin(BaseModel):
    @field_validator("endpoint", "base_url", check_fields=False)
    @classmethod
    def https_endpoint(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("endpoint must be HTTPS without credentials/query")
        return value.rstrip("/")


class ObjectStoreBinding(_HttpsEndpointMixin):
    """DeepTutor 业务对象存储绑定；只保存 Secret 引用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Literal["s3-compatible"]
    endpoint: str
    bucket: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
    region: str = Field(min_length=1)
    access_key_secret: SecretReference
    secret_key_secret: SecretReference
    prefix: str = Field(default="deeptutor", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,127}$")
    path_style: bool = True


class SettingsProviderBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["postgres"]


class SecretProviderBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["external-secret", "kubernetes-secret", "env"]
    name: str | None = Field(default=None, min_length=1)


class LightRAGBinding(BaseModel):
    """LightRAG Server API 绑定；DeepTutor 不保存图/检索库凭证。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    endpoint: str
    api_secret: SecretReference
    workspace_binding: str = Field(min_length=1)
    index_version: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)

    @field_validator("endpoint")
    @classmethod
    def endpoint_allows_loopback_for_local_debug(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
        ):
            raise ValueError("endpoint must be an http(s) origin without credentials/query")
        if parsed.scheme == "https":
            return value.rstrip("/")
        if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
            return value.rstrip("/")
        raise ValueError("endpoint must be HTTPS, except loopback HTTP for local debug")


class EduPlus2Binding(_HttpsEndpointMixin):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str
    client_id: str = Field(min_length=1)
    client_secret: SecretReference
    allowed_clients_ref: SecretReference | None = None


class ProductionBaselineConfig(BaseModel):
    """M1/G1 生产门禁；任何 local/SQLite/PocketBase fallback 都拒绝。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    runtime_mode: Literal["production"]
    local_authority_fallback: Literal[False] = False
    sqlite_fallback: Literal[False] = False
    pocketbase_fallback: Literal[False] = False
    required_readiness: tuple[
        Literal["postgres", "object_store", "secret_provider", "lightrag", "eduplus2"], ...
    ] = ("postgres", "object_store", "secret_provider", "lightrag", "eduplus2")

    @model_validator(mode="after")
    def require_fail_closed_values(self):
        if self.local_authority_fallback or self.sqlite_fallback or self.pocketbase_fallback:
            raise ValueError("production fallback must be disabled")
        return self


class DeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1]
    tenant_id: UUID
    resource: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    database_secret: SecretReference
    migration_database_secret: SecretReference = "env:" + CANONICAL_MIGRATION_DATABASE_SECRET
    signing_secret: SecretReference
    auth_epoch_secret: SecretReference
    bootstrap_secret: SecretReference | None = None
    origins: tuple[str, ...] = Field(min_length=1)
    models: tuple[ModelDeployment, ...] = Field(min_length=1)
    allowed_tools: tuple[EnterpriseAllowedTool, ...] = ("ask_user",)
    token_seconds: int = Field(default=3600, ge=60, le=86400)
    storage_backend: Literal["postgres"] = "postgres"
    max_size: int = Field(default=8, ge=1)
    max_waiting: int = Field(default=16, ge=1)
    timeout: float = Field(default=10, gt=0, le=3600, allow_inf_nan=False)
    statement_timeout_ms: int = Field(default=15_000, ge=1, le=3_600_000)
    transaction_timeout_ms: int = Field(default=30_000, ge=1, le=3_600_000)
    backend_workers: Literal[1] = 1
    language: Literal["en", "zh"] = "zh"
    max_rounds: int = Field(default=8, ge=1, le=16)
    maintenance: bool = False
    object_store: ObjectStoreBinding | None = None
    settings_provider: SettingsProviderBinding | None = None
    secret_provider: SecretProviderBinding | None = None
    lightrag: LightRAGBinding | None = None
    eduplus2: EduPlus2Binding | None = None
    production: ProductionBaselineConfig | None = None

    @field_validator("origins")
    @classmethod
    def secure_origins(cls, values):
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("origins must be exact HTTPS origins")
        return tuple(v.rstrip("/") for v in values)

    @field_validator("models")
    @classmethod
    def unique_models(cls, values):
        keys = [(m.profile_id, m.model_id) for m in values]
        if len(set(keys)) != len(keys) or any(
            not (m.allowed_roles or m.allowed_user_ids) for m in values
        ):
            raise ValueError("models require unique selections and explicit authorized principals")
        return values

    @model_validator(mode="after")
    def production_requires_bindings(self):
        if self.production is None:
            return self
        if self.lightrag is not None and urlsplit(self.lightrag.endpoint).scheme != "https":
            raise ValueError("production baseline requires HTTPS LightRAG endpoint")
        missing = [
            name
            for name in (
                "object_store",
                "settings_provider",
                "secret_provider",
                "lightrag",
                "eduplus2",
            )
            if getattr(self, name) is None
        ]
        if missing:
            raise ValueError("production baseline requires bindings: " + ",".join(missing))
        return self

    @classmethod
    def from_file(cls, path):
        try:
            return cls.model_validate(json.loads(Path(path).read_text(encoding="utf8")))
        except PostgresConfigurationError:
            raise
        except Exception:
            # Pydantic 会把 extra field 的原值放进 ValidationError，统一改为安全错误。
            raise PostgresConfigurationError("postgres_config_invalid") from None


def postgres_configuration(deployment: DeploymentConfig) -> PostgresDeploymentConfig:
    """把企业部署字段显式适配到 core 配置合同。"""

    return PostgresDeploymentConfig.from_deployment(deployment)


def resolve_secret(reference):
    if not reference or not reference.startswith("env:"):
        raise RuntimeError("Secret reference is not configured")
    value = os.environ.get(reference[4:])
    if not value:
        raise RuntimeError("required Secret is unavailable")
    return value


class Configuration:
    def __init__(self, deployment: DeploymentConfig):
        self.deployment = deployment.model_copy(deep=True)
        for model in self.deployment.models:
            self.model_transport(model).validate_environment(
                backend="anthropic" if model.provider == "anthropic" else "openai_compat"
            )

    @staticmethod
    def model_transport(model):
        from deeptutor.services.llm.transport import LLMTransportConfig

        return LLMTransportConfig(
            request_timeout_seconds=model.request_timeout_seconds,
            connect_timeout_seconds=model.connect_timeout_seconds,
            max_retries=model.max_retries,
        )

    def validate_session_update(self, values):
        if "course_id" in values or values.get("session_kind", "chat") not in (None, "chat"):
            raise ValueError("requested session resource is not available")

    def agent_params(self, module):
        # 摘要与标题复用同一获准模型，额度仍受部署上限约束。
        return {"temperature": 0.2, "max_tokens": min(m.max_tokens for m in self.deployment.models)}

    def chat_params(self):
        return copy.deepcopy(
            {
                "temperature": 0.2,
                "max_rounds": self.deployment.max_rounds,
                "exploring": {"max_tokens": 1600},
                "responding": {"max_tokens": min(m.max_tokens for m in self.deployment.models)},
            }
        )

    def select_model(self, selection, *, role, user_id, models=None):
        candidates = tuple(models or self.deployment.models)
        allowed = [
            m
            for m in candidates
            if role in m.allowed_roles or user_id in m.allowed_user_ids
        ]
        if selection:
            allowed = [
                m
                for m in allowed
                if (m.profile_id, m.model_id)
                == (selection.get("profile_id"), selection.get("model_id"))
            ]
        if not allowed:
            raise PermissionError("model is not authorized")
        return allowed[0]

    def resolve_model_deployment(self, model):
        from deeptutor.services.llm.config import LLMConfig

        transport = self.model_transport(model)
        api_key = resolve_secret(model.secret)
        transport.validate_provider(
            backend="anthropic" if model.provider == "anthropic" else "openai_compat",
            api_key=api_key,
            base_url=model.base_url,
        )
        return LLMConfig(
            model=model.model,
            api_key=api_key,
            base_url=model.base_url,
            binding=model.provider,
            provider_name=model.provider,
            max_tokens=model.max_tokens,
            context_window=model.context_window,
            temperature=0.2,
            transport=transport,
        )

    def resolve_model(self, selection, *, role, user_id, models=None):
        model = self.select_model(selection, role=role, user_id=user_id, models=models)
        return self.resolve_model_deployment(model)
