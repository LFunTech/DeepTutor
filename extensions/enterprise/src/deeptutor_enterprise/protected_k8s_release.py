"""Protected K8s release pipeline gates.

本模块只处理发布契约、deployment tag、Secret preflight、digest 清单、
rollback 决策和脱敏 evidence。它不连接真实 Woodpecker/K8s/SecretStore，
也不保存任何 Secret 明文；真实执行由目标环境 pipeline/Job 调用这些门禁。
"""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import hashlib
import json
from pathlib import Path
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

_ENV_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
_CANONICAL_TAG_RE = re.compile(
    r"^deploy/(?P<env_id>[a-z][a-z0-9-]{1,40})/"
    r"(?P<version>v[0-9]+\.[0-9]+\.[0-9]+(-(rc|hotfix)\.[0-9]+)?)$"
)
_DIGEST_RE = re.compile(r"^[^\s:@]+(?:[./:@-][^\s:@]+)*@sha256:[a-fA-F0-9]{64}$")
_SHA_RE = re.compile(r"^[a-fA-F0-9]{40}$")
_SECRET_REF_RE = re.compile(r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}$")
_LEAK_PATTERNS: dict[str, re.Pattern[str]] = {
    "dot_secrets": re.compile(r"\.secrets"),
    "jwt": re.compile(r"\b(jwt|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.)", re.IGNORECASE),
    "dt_token": re.compile(r"\bdt_token\b|\bdt_[A-Za-z0-9_-]{12,}", re.IGNORECASE),
    "client_secret": re.compile(r"[\"']?client[_-]?secret[\"']?\s*[:=]", re.IGNORECASE),
    "model_key": re.compile(
        r"[\"']?(model|openai|dashscope|bailian)[_-]?api[_-]?key[\"']?\s*[:=]",
        re.IGNORECASE,
    ),
    "kubeconfig": re.compile(r"\b(apiVersion:\s*v1\s+clusters:|KUBECONFIG=)", re.IGNORECASE),
    "private_key": re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    "woodpecker_secret": re.compile(r"WOODPECKER[_-]?SECRET\s*[:=]", re.IGNORECASE),
}
_SENSITIVE_JSON_KEY_RE = re.compile(
    r"(^|_)(client_secret|api_key|password|authorization|bearer|kubeconfig|secret_value)$",
    re.IGNORECASE,
)

SecretRef = Annotated[str, StringConstraints(pattern=_SECRET_REF_RE.pattern)]
EnvId = Annotated[str, StringConstraints(pattern=_ENV_ID_RE.pattern)]
ImageDigest = Annotated[str, StringConstraints(pattern=_DIGEST_RE.pattern)]
GitSha = Annotated[str, StringConstraints(pattern=_SHA_RE.pattern)]


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf8")).hexdigest()[:12]


def _endpoint_summary(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    parsed = urlsplit(value)
    return {
        "scheme": parsed.scheme,
        "host_hash": _hash_text(parsed.hostname or ""),
        "port": parsed.port,
    }


def _https_origin(value: str) -> str:
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
        raise ValueError("endpoint must be an HTTPS origin without credentials/query/path")
    return value.rstrip("/")


def _ref_summary(value: str) -> dict[str, str]:
    kind, _, identifier = value.partition(":")
    return {"kind": kind, "id_hash": _hash_text(identifier)}


def _require_env_marker(value: str, env_id: str, field: str) -> None:
    if env_id not in value:
        raise ValueError(f"{field} must be scoped to {env_id}")


def _image_digest_prefix(repository: str, component: str) -> str:
    return f"{repository.rstrip('/')}/{component}@sha256:"


def _require_env_scoped_digest(
    value: str,
    *,
    repository: str,
    component: str,
    label: str,
) -> str:
    if not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"image_digest_required:{label}")
    if not value.startswith(_image_digest_prefix(repository, component)):
        raise ValueError(f"image_digest_registry_mismatch:{label}")
    return value


def _redact(value: Any, *, key: str = "") -> Any:
    key_lower = key.lower()
    if key_lower in {"token", "password", "credential", "client_secret", "secret_value"}:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, key=str(k)) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return [_redact(v, key=key) for v in value]
    if isinstance(value, str):
        lowered = value.lower()
        if "dt_token" in lowered or "client-secret" in lowered or "jwt=" in lowered:
            return "[REDACTED]"
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_redact(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf8",
    )


@dataclass(frozen=True, slots=True)
class DeploymentTag:
    env_id: str
    version: str
    raw: str


def parse_deployment_tag(tag: str) -> DeploymentTag:
    """Parse the canonical deployment tag.

    Raises ``ValueError('deployment_tag_invalid')`` for all non-canonical inputs.
    """

    if not isinstance(tag, str):
        raise ValueError("deployment_tag_invalid")
    match = _CANONICAL_TAG_RE.fullmatch(tag.strip())
    if not match:
        raise ValueError("deployment_tag_invalid")
    return DeploymentTag(env_id=match.group("env_id"), version=match.group("version"), raw=tag)


class ApprovalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    required: bool = False
    approvers: tuple[str, ...] = ()
    window: str = "not-required"


class WoodpeckerSecret(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    logical_name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,80}$")
    ref: SecretRef
    purpose: Literal[
        "registry_push",
        "k8s_deploy",
        "secret_store",
        "pg_migrator",
        "runtime_secret_ref",
        "runtime_secret_sync",
        "smoke_credentials",
        "evidence_store",
        "tag_approval_verify",
        "image_signing",
        "scanner",
        "notification",
        "registry_read",
    ]
    scope_env_id: EnvId
    permission_summary: str = Field(min_length=1)
    rotation_state: Literal["current", "stale", "unknown"] = "unknown"
    least_privilege: bool = False
    required: bool = True

    def redacted_summary(self) -> dict[str, Any]:
        return {
            "logical_name": self.logical_name,
            "purpose": self.purpose,
            "scope_env_id": self.scope_env_id,
            "ref": _ref_summary(self.ref),
            "permission_hash": _hash_text(self.permission_summary),
            "rotation_state": self.rotation_state,
            "least_privilege": self.least_privilege,
            "required": self.required,
        }


class WoodpeckerEnvironmentContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    server_url: str
    server_version: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    agent_backend: Literal["kubernetes", "docker", "exec"]
    protected_refs: tuple[str, ...] = Field(min_length=1)
    approval_policy: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    secret_resolution_mode: Literal["secret-extension", "configuration-extension", "native-static"]
    secrets: tuple[WoodpeckerSecret, ...] = Field(min_length=1)

    @field_validator("server_url")
    @classmethod
    def secure_server_url(cls, value: str) -> str:
        return _https_origin(value)

    @field_validator("protected_refs")
    @classmethod
    def protected_refs_are_tags_or_heads(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not (value.startswith("refs/tags/") or value.startswith("refs/heads/")):
                raise ValueError("protected_refs must be Git refs")
            if "pull" in value.lower() or ".." in value:
                raise ValueError("protected_refs must not include pull/traversal refs")
        return values


class RegistryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    repository: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]{2,255}$")
    credentials_ref: SecretRef
    immutable_tags: bool = True


class RuntimeCoordinationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    backend: Literal["memory", "redis"] = "memory"
    redis_secret_ref: SecretRef | None = None
    shared_turn_leases: bool = False
    shared_event_stream: bool = False
    fencing_tokens: bool = True
    worker_recovery: bool = False
    consistency_evidence_ref: str = Field(
        default="",
        pattern=r"^[A-Za-z0-9._:/-]*$",
    )

    @model_validator(mode="after")
    def _validate_coordination(self):
        if self.backend == "redis":
            if self.redis_secret_ref is None:
                raise ValueError("redis_coordination_requires_secret_ref")
            if not (
                self.shared_turn_leases
                and self.shared_event_stream
                and self.fencing_tokens
                and self.worker_recovery
            ):
                raise ValueError("redis_coordination_requires_consistency_controls")
        elif self.redis_secret_ref is not None:
            raise ValueError("memory_coordination_must_not_declare_redis_secret_ref")
        return self

    def redacted_summary(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "redis_secret_ref": (
                _ref_summary(self.redis_secret_ref) if self.redis_secret_ref is not None else None
            ),
            "shared_turn_leases": self.shared_turn_leases,
            "shared_event_stream": self.shared_event_stream,
            "fencing_tokens": self.fencing_tokens,
            "worker_recovery": self.worker_recovery,
            "consistency_evidence_ref": self.consistency_evidence_ref,
        }


class AutoscalingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = False
    min_replicas: int = Field(default=1, ge=1, le=100)
    max_replicas: int = Field(default=1, ge=1, le=100)
    target_cpu_utilization_percentage: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def _validate_autoscaling(self):
        if self.max_replicas < self.min_replicas:
            raise ValueError("autoscaling_max_replicas_lt_min")
        if self.enabled and self.target_cpu_utilization_percentage is None:
            raise ValueError("autoscaling_requires_cpu_target")
        return self

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "min_replicas": self.min_replicas,
            "max_replicas": self.max_replicas,
            "target_cpu_utilization_percentage": self.target_cpu_utilization_percentage,
        }


class KubernetesContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    cluster_ref: SecretRef
    namespace: str = Field(pattern=r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
    ingress_host: str = Field(pattern=r"^[A-Za-z0-9.-]+$")
    tls_secret_ref: SecretRef
    secret_store_ref: SecretRef
    rbac_ref: SecretRef
    network_policy_ref: SecretRef
    service_account: str = Field(pattern=r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
    backend_executor_replicas: int = Field(default=1, ge=1, le=100)
    rollout_strategy: Literal[
        "single-executor-drain",
        "recreate-after-drain",
        "rolling-replicated-agent",
    ]
    runtime_coordination: RuntimeCoordinationContract = Field(
        default_factory=RuntimeCoordinationContract
    )
    autoscaling: AutoscalingContract = Field(default_factory=AutoscalingContract)

    @model_validator(mode="after")
    def _validate_replicated_runtime(self):
        replicated = self.backend_executor_replicas > 1 or self.autoscaling.enabled
        if not replicated:
            return self
        if self.rollout_strategy != "rolling-replicated-agent":
            raise ValueError("multi_replica_requires_replicated_rollout_strategy")
        if self.runtime_coordination.backend != "redis":
            raise ValueError("multi_replica_requires_redis_coordination")
        if (
            self.autoscaling.enabled
            and self.autoscaling.min_replicas != self.backend_executor_replicas
        ):
            raise ValueError("autoscaling_min_must_match_backend_executor_replicas")
        return self


class DataPlaneBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    pg_secret_ref: SecretRef
    object_store_ref: SecretRef
    lightrag_ref: SecretRef
    eduplus2_smoke_ref: SecretRef


class ReleaseControl(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    release_lock_ref: SecretRef
    migration_lock_ref: SecretRef
    maintenance_mode_ref: SecretRef


class RollbackPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    compatible_strategy: Literal["previous-digest-if-compatible"]
    incompatible_strategy: Literal["maintenance-forward-fix"]
    previous_release_ref: SecretRef
    requires_smoke_after_rollback: Literal[True] = True


class EvidenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    store_ref: SecretRef
    prefix: str = Field(pattern=r"^[A-Za-z0-9._/-]+$")
    retention_days: int = Field(ge=30, le=3650)
    write_scope: str = Field(min_length=1)
    read_scope: str = Field(min_length=1)


_REQUIRED_SECRET_PURPOSES = {
    "registry_push",
    "k8s_deploy",
    "secret_store",
    "pg_migrator",
    "runtime_secret_ref",
    "smoke_credentials",
    "evidence_store",
    "tag_approval_verify",
}


class DeploymentEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    env_id: EnvId
    env_class: Literal["local", "test", "pre", "staging", "prod"]
    prod_group: str | None = None
    verification_status: Literal["verified", "unverified", "blocked"] = "unverified"
    tag_pattern: str
    allowed_ref: str
    woodpecker: WoodpeckerEnvironmentContract
    registry: RegistryContract
    kubernetes: KubernetesContract
    data_plane: DataPlaneBinding
    release_control: ReleaseControl
    rollback_policy: RollbackPolicy
    evidence: EvidenceContract

    @model_validator(mode="after")
    def _validate_environment_boundaries(self):
        if self.env_id not in self.tag_pattern or self.env_id not in self.allowed_ref:
            raise ValueError("environment tag/ref patterns must include env_id")
        if self.env_id not in self.evidence.prefix:
            raise ValueError("evidence prefix must include env_id")
        _require_env_marker(self.registry.repository, self.env_id, "registry.repository")
        _require_env_marker(
            self.registry.credentials_ref,
            self.env_id.replace("-", "_").upper(),
            "registry.credentials_ref",
        )
        _require_env_marker(self.kubernetes.cluster_ref, self.env_id, "cluster_ref")
        _require_env_marker(self.kubernetes.namespace, self.env_id, "namespace")
        # Ingress host can be a business-owned DNS name (for example an llm-agent
        # vanity domain) that does not include the internal target env id. The
        # env isolation boundary is enforced by namespace, cluster/ref bindings,
        # Secret refs, locks, registry path and evidence prefixes below.
        _require_env_marker(self.kubernetes.tls_secret_ref, self.env_id, "tls_secret_ref")
        _require_env_marker(self.kubernetes.secret_store_ref, self.env_id, "secret_store_ref")
        _require_env_marker(self.kubernetes.rbac_ref, self.env_id, "rbac_ref")
        _require_env_marker(self.kubernetes.network_policy_ref, self.env_id, "network_policy_ref")
        if self.kubernetes.runtime_coordination.redis_secret_ref is not None:
            _require_env_marker(
                self.kubernetes.runtime_coordination.redis_secret_ref,
                self.env_id,
                "runtime_coordination.redis_secret_ref",
            )
        if self.kubernetes.runtime_coordination.consistency_evidence_ref:
            _require_env_marker(
                self.kubernetes.runtime_coordination.consistency_evidence_ref,
                self.env_id,
                "runtime_coordination.consistency_evidence_ref",
            )
        _require_env_marker(self.data_plane.pg_secret_ref, self.env_id, "pg_secret_ref")
        _require_env_marker(self.data_plane.object_store_ref, self.env_id, "object_store_ref")
        _require_env_marker(self.data_plane.lightrag_ref, self.env_id, "lightrag_ref")
        _require_env_marker(self.data_plane.eduplus2_smoke_ref, self.env_id, "eduplus2_smoke_ref")
        _require_env_marker(self.release_control.release_lock_ref, self.env_id, "release_lock_ref")
        _require_env_marker(
            self.release_control.migration_lock_ref,
            self.env_id,
            "migration_lock_ref",
        )
        _require_env_marker(
            self.release_control.maintenance_mode_ref,
            self.env_id,
            "maintenance_mode_ref",
        )
        _require_env_marker(
            self.rollback_policy.previous_release_ref,
            self.env_id,
            "previous_release_ref",
        )
        _require_env_marker(self.evidence.write_scope, self.env_id, "evidence.write_scope")
        _require_env_marker(self.evidence.read_scope, self.env_id, "evidence.read_scope")
        if self.env_class == "prod" and not self.woodpecker.approval_policy.required:
            raise ValueError("prod environment requires approval policy")
        purposes = {secret.purpose for secret in self.woodpecker.secrets if secret.required}
        missing = _REQUIRED_SECRET_PURPOSES - purposes
        if missing:
            raise ValueError(
                "required Woodpecker secret purposes missing: " + ",".join(sorted(missing))
            )
        logical_names: set[str] = set()
        for secret in self.woodpecker.secrets:
            if secret.logical_name in logical_names:
                raise ValueError("duplicate Woodpecker secret logical_name")
            logical_names.add(secret.logical_name)
            if secret.scope_env_id != self.env_id:
                raise ValueError("Woodpecker secret scope must match env_id")
        return self

    def redacted_summary(self) -> dict[str, Any]:
        return {
            "env_id": self.env_id,
            "env_class": self.env_class,
            "prod_group": self.prod_group,
            "verification_status": self.verification_status,
            "tag_pattern": self.tag_pattern,
            "allowed_ref": self.allowed_ref,
            "woodpecker": {
                "server": _endpoint_summary(self.woodpecker.server_url),
                "server_version": self.woodpecker.server_version,
                "agent_version": self.woodpecker.agent_version,
                "agent_backend": self.woodpecker.agent_backend,
                "protected_refs": list(self.woodpecker.protected_refs),
                "approval_required": self.woodpecker.approval_policy.required,
                "approval_window": self.woodpecker.approval_policy.window,
                "secret_resolution_mode": self.woodpecker.secret_resolution_mode,
                "secrets": [secret.redacted_summary() for secret in self.woodpecker.secrets],
            },
            "registry": {
                "repository_hash": _hash_text(self.registry.repository),
                "credentials_ref": _ref_summary(self.registry.credentials_ref),
                "immutable_tags": self.registry.immutable_tags,
            },
            "kubernetes": {
                "cluster_ref": _ref_summary(self.kubernetes.cluster_ref),
                "namespace_hash": _hash_text(self.kubernetes.namespace),
                "ingress": {"host_hash": _hash_text(self.kubernetes.ingress_host)},
                "tls_secret_ref": _ref_summary(self.kubernetes.tls_secret_ref),
                "secret_store_ref": _ref_summary(self.kubernetes.secret_store_ref),
                "rbac_ref": _ref_summary(self.kubernetes.rbac_ref),
                "network_policy_ref": _ref_summary(self.kubernetes.network_policy_ref),
                "service_account_hash": _hash_text(self.kubernetes.service_account),
                "backend_executor_replicas": self.kubernetes.backend_executor_replicas,
                "rollout_strategy": self.kubernetes.rollout_strategy,
                "runtime_coordination": self.kubernetes.runtime_coordination.redacted_summary(),
                "autoscaling": self.kubernetes.autoscaling.summary(),
            },
            "data_plane": {
                "pg_secret_ref": _ref_summary(self.data_plane.pg_secret_ref),
                "object_store_ref": _ref_summary(self.data_plane.object_store_ref),
                "lightrag_ref": _ref_summary(self.data_plane.lightrag_ref),
                "eduplus2_smoke_ref": _ref_summary(self.data_plane.eduplus2_smoke_ref),
            },
            "release_control": {
                "release_lock_ref": _ref_summary(self.release_control.release_lock_ref),
                "migration_lock_ref": _ref_summary(self.release_control.migration_lock_ref),
                "maintenance_mode_ref": _ref_summary(self.release_control.maintenance_mode_ref),
            },
            "rollback_policy": {
                "compatible_strategy": self.rollback_policy.compatible_strategy,
                "incompatible_strategy": self.rollback_policy.incompatible_strategy,
                "previous_release_ref": _ref_summary(self.rollback_policy.previous_release_ref),
                "requires_smoke_after_rollback": self.rollback_policy.requires_smoke_after_rollback,
            },
            "evidence": {
                "store_ref": _ref_summary(self.evidence.store_ref),
                "prefix": self.evidence.prefix,
                "retention_days": self.evidence.retention_days,
                "write_scope_hash": _hash_text(self.evidence.write_scope),
                "read_scope_hash": _hash_text(self.evidence.read_scope),
            },
            "evidence_prefix": self.evidence.prefix,
        }


class EnvironmentRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    registry_version: str = Field(min_length=1)
    canonical_tag_regex: str = _CANONICAL_TAG_RE.pattern
    environments: tuple[DeploymentEnvironment, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_registry(self):
        seen: set[str] = set()
        classes: set[str] = set()
        for env in self.environments:
            if env.env_id in seen:
                raise ValueError("duplicate env_id")
            seen.add(env.env_id)
            classes.add(env.env_class)
        if "test" not in classes or "pre" not in classes:
            raise ValueError("registry must include test and pre environments")
        return self

    @property
    def production_env_ids(self) -> tuple[str, ...]:
        return tuple(env.env_id for env in self.environments if env.env_class == "prod")

    def find_env(self, env_id: str) -> DeploymentEnvironment | None:
        for env in self.environments:
            if env.env_id == env_id:
                return env
        return None

    def redacted_matrix(self) -> dict[str, Any]:
        return {
            "registry_version": self.registry_version,
            "canonical_tag_regex": self.canonical_tag_regex,
            "production_env_ids": list(self.production_env_ids),
            "environments": {env.env_id: env.redacted_summary() for env in self.environments},
            "promotion_path": [
                env.env_id
                for env in self.environments
                if env.env_class in {"test", "pre", "staging", "prod"}
            ],
            "multi_prod_rule": (
                "each production env requires its own deployment tag, approval, "
                "smoke and evidence"
            ),
        }


def _ref_matches(pattern: str, ref: str) -> bool:
    glob = pattern.replace("**", "*")
    return fnmatch.fnmatch(ref, glob)


def validate_release_trigger(
    registry: EnvironmentRegistry,
    *,
    event: str,
    ref: str,
    tag: str,
    protected_ref: bool,
    approved: bool,
    approval_id: str,
    actor: str,
    tag_object_sha: str,
    commit_sha: str,
    previous_evidence: dict[str, Any] | None = None,
    manual_target_env_id: str | None = None,
    trust_source: str | None = None,
) -> dict[str, Any]:
    """Fail-closed release trigger gate, safe to run before reading env secrets."""

    error_codes: list[str] = []
    parsed: DeploymentTag | None = None
    if event != "tag":
        error_codes.append("event_not_tag")
    try:
        parsed = parse_deployment_tag(tag)
    except ValueError:
        error_codes.append("deployment_tag_invalid")
    if manual_target_env_id:
        error_codes.append("manual_environment_override_forbidden")

    env = registry.find_env(parsed.env_id) if parsed else None
    if parsed and env is None:
        error_codes.append("environment_not_registered")
    if parsed and parsed.env_id in {"prod", "production", "latest", "stable"}:
        error_codes.append("ambiguous_environment_alias")
    if parsed and env is not None and not _ref_matches(env.allowed_ref, ref):
        error_codes.append("ref_environment_mismatch")
    if not protected_ref:
        error_codes.append("tag_not_protected")
    if env and env.env_class == "prod" and env.woodpecker.approval_policy.required:
        if not approved or not approval_id:
            error_codes.append("prod_approval_missing")
        if (
            env.woodpecker.approval_policy.approvers
            and actor not in env.woodpecker.approval_policy.approvers
        ):
            error_codes.append("prod_approval_actor_unauthorized")

    if previous_evidence and parsed:
        historical = {
            "target_env_id": previous_evidence.get("target_env_id"),
            "version": previous_evidence.get("version"),
            "tag_object_sha": previous_evidence.get("tag_object_sha"),
            "commit_sha": previous_evidence.get("commit_sha"),
        }
        current = {
            "target_env_id": parsed.env_id,
            "version": parsed.version,
            "tag_object_sha": tag_object_sha,
            "commit_sha": commit_sha,
        }
        if historical != current:
            error_codes.append("deployment_tag_reused_or_moved")

    for name, value in {"tag_object_sha": tag_object_sha, "commit_sha": commit_sha}.items():
        if not _SHA_RE.fullmatch(str(value or "")):
            error_codes.append(name + "_invalid")

    return {
        "ready": not error_codes,
        "error_codes": sorted(set(error_codes)),
        "event": event,
        "ref_hash": _hash_text(ref),
        "tag": parsed.raw if parsed else tag,
        "target_env_id": parsed.env_id if parsed else None,
        "version": parsed.version if parsed else None,
        "tag_object_sha": tag_object_sha,
        "commit_sha": commit_sha,
        "approval": {
            "approved": approved,
            "approval_id_hash": _hash_text(approval_id) if approval_id else None,
        },
        "actor_hash": _hash_text(actor),
        "trust_source": trust_source or "caller-supplied",
    }


def secret_preflight(
    registry: EnvironmentRegistry,
    target_env_id: str,
    available_secrets: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    env = registry.find_env(target_env_id)
    if env is None:
        return {
            "ready": False,
            "target_env_id": target_env_id,
            "error_codes": ["environment_not_registered"],
        }
    error_codes: list[str] = []
    summaries: list[dict[str, Any]] = []
    for secret in env.woodpecker.secrets:
        if not secret.required:
            continue
        observed = available_secrets.get(secret.logical_name)
        if not observed or observed.get("present") is False:
            error_codes.append("secret_missing:" + secret.logical_name)
            summaries.append({**secret.redacted_summary(), "status": "missing"})
            continue
        scope = str(observed.get("scope_env_id") or "")
        least_privilege = bool(observed.get("least_privilege"))
        rotation_state = str(observed.get("rotation_state") or "unknown")
        permission_summary = str(observed.get("permission_summary") or "")
        if scope != target_env_id:
            error_codes.append("secret_scope_mismatch:" + secret.logical_name)
        lowered_permission = permission_summary.lower()
        if (
            not least_privilege
            or "superuser" in lowered_permission
            or "root" in lowered_permission
            or lowered_permission.endswith(":*")
        ):
            error_codes.append("secret_over_privileged:" + secret.logical_name)
        if rotation_state != "current":
            error_codes.append("secret_rotation_not_current:" + secret.logical_name)
        summaries.append(
            {
                **secret.redacted_summary(),
                "status": "available",
                "observed_scope_env_id": scope,
                "observed_permission_hash": _hash_text(permission_summary),
                "observed_rotation_state": rotation_state,
                "observed_least_privilege": least_privilege,
            }
        )
    return {
        "ready": not error_codes,
        "target_env_id": target_env_id,
        "secret_resolution_mode": env.woodpecker.secret_resolution_mode,
        "error_codes": sorted(set(error_codes)),
        "secrets": summaries,
    }


def build_release_manifest(
    registry: EnvironmentRegistry,
    *,
    target_env_id: str,
    version: str,
    tag: str,
    tag_object_sha: GitSha,
    tag_creator: str,
    source_sha: GitSha,
    upstream_sha: GitSha,
    enterprise_package_version: str,
    backend_image_digest: str,
    frontend_image_digest: str,
    build_run_id: str,
    scan_summary: dict[str, Any],
) -> dict[str, Any]:
    env = registry.find_env(target_env_id)
    if env is None:
        raise ValueError("environment_not_registered")
    parsed = parse_deployment_tag(tag)
    if parsed.env_id != target_env_id or parsed.version != version:
        raise ValueError("tag_environment_or_version_mismatch")
    backend = _require_env_scoped_digest(
        backend_image_digest,
        repository=env.registry.repository,
        component="backend",
        label="backend",
    )
    frontend = _require_env_scoped_digest(
        frontend_image_digest,
        repository=env.registry.repository,
        component="frontend",
        label="frontend",
    )
    if not _SHA_RE.fullmatch(source_sha) or not _SHA_RE.fullmatch(upstream_sha):
        raise ValueError("source_or_upstream_sha_invalid")
    return {
        "schema": "deeptutor.protected-k8s-release-manifest.v1",
        "target_env_id": target_env_id,
        "env_class": env.env_class,
        "prod_group": env.prod_group,
        "version": version,
        "tag": tag,
        "tag_object_sha": tag_object_sha,
        "tag_creator_hash": _hash_text(tag_creator),
        "source_sha": source_sha,
        "upstream_sha": upstream_sha,
        "enterprise_package_version": enterprise_package_version,
        "images": {"backend": backend, "frontend": frontend},
        "build": {"run_id": build_run_id, "scan_summary": _redact(scan_summary)},
        "registry": {
            "repository_hash": _hash_text(env.registry.repository),
            "immutable_tags": env.registry.immutable_tags,
        },
        "kubernetes": {
            "cluster_ref": _ref_summary(env.kubernetes.cluster_ref),
            "namespace_hash": _hash_text(env.kubernetes.namespace),
            "backend_executor_replicas": env.kubernetes.backend_executor_replicas,
            "rollout_strategy": env.kubernetes.rollout_strategy,
            "runtime_coordination": env.kubernetes.runtime_coordination.redacted_summary(),
            "autoscaling": env.kubernetes.autoscaling.summary(),
        },
        "release_control": {
            "release_lock_ref": _ref_summary(env.release_control.release_lock_ref),
            "migration_lock_ref": _ref_summary(env.release_control.migration_lock_ref),
        },
        "evidence_prefix": str(Path(env.evidence.prefix) / version),
    }


def decide_rollback(
    registry: EnvironmentRegistry,
    target_env_id: str,
    *,
    failure_code: str,
    previous_release_compatible: bool,
    previous_digest: str | None,
    approval_id: str,
) -> dict[str, Any]:
    env = registry.find_env(target_env_id)
    if env is None:
        raise ValueError("environment_not_registered")
    if previous_release_compatible and previous_digest:
        previous_digest = _require_env_scoped_digest(
            previous_digest,
            repository=env.registry.repository,
            component="backend",
            label="rollback",
        )
        return {
            "target_env_id": target_env_id,
            "failure_code": failure_code,
            "action": "rollback_previous_digest",
            "previous_digest": previous_digest,
            "rollback_policy": env.rollback_policy.compatible_strategy,
            "approval_id_hash": _hash_text(approval_id),
            "requires_smoke_after_rollback": env.rollback_policy.requires_smoke_after_rollback,
            "write_state": "resume_after_smoke",
        }
    return {
        "target_env_id": target_env_id,
        "failure_code": failure_code,
        "action": "maintenance_forward_fix",
        "rollback_policy": env.rollback_policy.incompatible_strategy,
        "approval_id_hash": _hash_text(approval_id),
        "requires_smoke_after_rollback": False,
        "write_state": "stopped",
    }


def write_release_evidence(
    base_dir: str | Path,
    registry: EnvironmentRegistry,
    manifest: dict[str, Any],
    *,
    deployment_contract: dict[str, Any],
    migration: dict[str, Any],
    deploy: dict[str, Any],
    smoke: dict[str, Any],
    rollback: dict[str, Any],
    upstream_compat: dict[str, Any],
    unresolved: list[str],
) -> Path:
    target_env_id = str(manifest["target_env_id"])
    version = str(manifest["version"])
    env = registry.find_env(target_env_id)
    if env is None:
        raise ValueError("environment_not_registered")
    root = Path(base_dir) / target_env_id / version
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "deployment-contract.json", deployment_contract)
    _write_json(root / "manifest.json", manifest)
    _write_json(root / "migration.json", migration)
    _write_json(root / "deploy.json", deploy)
    _write_json(root / "smoke.json", smoke)
    _write_json(root / "rollback.json", rollback)
    upstream_md = ["# Upstream compatibility review", ""]
    for key, value in sorted(_redact(upstream_compat).items()):
        upstream_md.append(f"- {key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
    (root / "upstream-compat.md").write_text("\n".join(upstream_md) + "\n", encoding="utf8")
    unresolved_lines = ["# Unresolved / unverified", ""] + [f"- {item}" for item in unresolved]
    (root / "unresolved.md").write_text("\n".join(unresolved_lines) + "\n", encoding="utf8")
    return root


def _json_secret_key_leaks(value: Any, *, path: str = "") -> list[str]:
    leaks: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _SENSITIVE_JSON_KEY_RE.search(key_text) and item not in (None, "", "[REDACTED]"):
                leaks.append("json_sensitive_key:" + key_text)
            leaks.extend(_json_secret_key_leaks(item, path=child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            leaks.extend(_json_secret_key_leaks(item, path=f"{path}[{index}]"))
    return leaks


def scan_secret_leakage(path: str | Path) -> dict[str, Any]:
    root = Path(path)
    leaks: list[dict[str, str]] = []
    files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf8")
        except UnicodeDecodeError:
            continue
        relative = str(file_path.relative_to(root if root.is_dir() else root.parent))
        for code, pattern in _LEAK_PATTERNS.items():
            if pattern.search(text):
                leaks.append({"file": relative, "code": code})
        if file_path.suffix.lower() in {".json", ".jsonl"}:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                for code in _json_secret_key_leaks(parsed):
                    leaks.append({"file": relative, "code": code})
    return {
        "ready": not leaks,
        "error_codes": [] if not leaks else ["secret_leak_detected"],
        "leaks": leaks,
    }


def load_registry(path: str | Path) -> EnvironmentRegistry:
    return EnvironmentRegistry.model_validate(json.loads(Path(path).read_text(encoding="utf8")))


__all__ = [
    "DeploymentEnvironment",
    "DeploymentTag",
    "EnvironmentRegistry",
    "build_release_manifest",
    "decide_rollback",
    "load_registry",
    "parse_deployment_tag",
    "scan_secret_leakage",
    "secret_preflight",
    "validate_release_trigger",
    "write_release_evidence",
]
