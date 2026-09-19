"""M1/G1 单租户生产基线工具。

本模块只处理脱敏配置、readiness inventory、smoke plan 与 release evidence；
不连接 LightRAG 内部 PG/HugeGraph，也不把 Secret 明文写入证据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .configuration import DeploymentConfig

_SECRET_KEY_RE = re.compile(r"(secret|token|password|api[_-]?key|credential)", re.IGNORECASE)
_DIGEST_RE = re.compile(r"^[^\s]+@sha256:[a-fA-F0-9]{64}$")
_HASH_RE = re.compile(r"^sha256:[a-fA-F0-9]{64}$")
_SHA_RE = re.compile(r"^[a-fA-F0-9]{40}$")
DeploymentReference = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}$")
]


def _secret_env_name(reference: str | None) -> str | None:
    if not reference or not reference.startswith("env:"):
        return None
    return reference[4:]


def _is_set(reference: str | None) -> bool:
    name = _secret_env_name(reference)
    return bool(name and os.environ.get(name))


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


class RegistryContract(BaseModel):
    """镜像仓库契约；只允许记录凭证引用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    repository: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]{2,255}$")
    credentials_ref: DeploymentReference


class WoodpeckerContract(BaseModel):
    """目标 Woodpecker server/agent 与发布边界契约。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    server_url: str
    server_version: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    agent_backend: Literal["kubernetes", "docker", "exec"]
    protected_refs: tuple[str, ...] = Field(min_length=1)
    approval_gate: str = Field(min_length=1)
    secret_boundary: str = Field(min_length=1)
    registry: RegistryContract

    @field_validator("server_url")
    @classmethod
    def secure_server_url(cls, value: str) -> str:
        return _https_origin(value)

    @field_validator("protected_refs")
    @classmethod
    def trusted_refs_only(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not (value.startswith("refs/heads/") or value.startswith("refs/tags/")):
                raise ValueError("protected_refs must be heads/tags refs")
            if "pull" in value.lower() or ".." in value:
                raise ValueError("protected_refs must not include pull or traversal refs")
        return values


class KubernetesContract(BaseModel):
    """目标 Kubernetes runtime 边界契约。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    namespace: str = Field(pattern=r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
    ingress_host: str = Field(pattern=r"^[A-Za-z0-9.-]+$")
    tls_secret_ref: DeploymentReference
    secret_store_ref: DeploymentReference
    service_account: str = Field(pattern=r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
    network_policy: str = Field(min_length=1)
    release_lock_ref: DeploymentReference
    backend_executor_replicas: Literal[1] = 1
    rollout_strategy: Literal["single-executor-drain", "recreate-after-drain"]


class RollbackContract(BaseModel):
    """回退策略契约；不承诺数据库自动降级。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    strategy: Literal["previous-digest-if-compatible", "maintenance-forward-fix"]
    previous_release_ref: DeploymentReference
    requires_smoke_after_rollback: Literal[True] = True


class EvidenceStoreContract(BaseModel):
    """release evidence 存放契约。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["object-store", "ci-artifact", "audit-system"]
    location_ref: DeploymentReference
    retention_days: int = Field(ge=30, le=3650)


class TargetDeploymentContract(BaseModel):
    """A3 前置目标部署契约，避免从租户模式推导 CI/K8s 拓扑。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: str = Field(min_length=1)
    environment: Literal["test", "preprod", "production"]
    tenant_mode: Literal["single-tenant"] = "single-tenant"
    topology_source: Literal["target-environment-contract"] = "target-environment-contract"
    target_base_url: str
    woodpecker: WoodpeckerContract
    kubernetes: KubernetesContract
    rollback: RollbackContract
    evidence_store: EvidenceStoreContract

    @field_validator("target_base_url")
    @classmethod
    def secure_target_base_url(cls, value: str) -> str:
        return _https_origin(value)


def _ref_summary(value: str) -> dict[str, str]:
    kind, _, identifier = value.partition(":")
    return {"kind": kind, "id_hash": _hash_text(identifier)}


def deployment_contract_inventory(
    contract: TargetDeploymentContract | dict[str, Any],
) -> dict[str, Any]:
    """输出可归档、脱敏的目标部署契约摘要。"""

    if not isinstance(contract, TargetDeploymentContract):
        contract = TargetDeploymentContract.model_validate(contract)
    return {
        "ready": True,
        "error_codes": [],
        "contract_version": contract.contract_version,
        "environment": contract.environment,
        "tenant_mode": contract.tenant_mode,
        "topology_source": contract.topology_source,
        "target_base_url": _endpoint_summary(contract.target_base_url),
        "woodpecker": {
            "server": _endpoint_summary(contract.woodpecker.server_url),
            "server_version": contract.woodpecker.server_version,
            "agent_version": contract.woodpecker.agent_version,
            "agent_backend": contract.woodpecker.agent_backend,
            "protected_refs_hash": _hash_text(",".join(sorted(contract.woodpecker.protected_refs))),
            "approval_gate_hash": _hash_text(contract.woodpecker.approval_gate),
            "secret_boundary_hash": _hash_text(contract.woodpecker.secret_boundary),
            "registry_repository_hash": _hash_text(contract.woodpecker.registry.repository),
            "registry_credentials_ref": _ref_summary(contract.woodpecker.registry.credentials_ref),
        },
        "kubernetes": {
            "namespace_hash": _hash_text(contract.kubernetes.namespace),
            "ingress_host_hash": _hash_text(contract.kubernetes.ingress_host),
            "tls_secret_ref": _ref_summary(contract.kubernetes.tls_secret_ref),
            "secret_store_ref": _ref_summary(contract.kubernetes.secret_store_ref),
            "service_account_hash": _hash_text(contract.kubernetes.service_account),
            "network_policy_hash": _hash_text(contract.kubernetes.network_policy),
            "release_lock_ref": _ref_summary(contract.kubernetes.release_lock_ref),
            "backend_executor_replicas": contract.kubernetes.backend_executor_replicas,
            "rollout_strategy": contract.kubernetes.rollout_strategy,
        },
        "rollback": {
            "strategy": contract.rollback.strategy,
            "previous_release_ref": _ref_summary(contract.rollback.previous_release_ref),
            "requires_smoke_after_rollback": contract.rollback.requires_smoke_after_rollback,
        },
        "evidence_store": {
            "kind": contract.evidence_store.kind,
            "location_ref": _ref_summary(contract.evidence_store.location_ref),
            "retention_days": contract.evidence_store.retention_days,
        },
    }


def build_governance_projection(
    *,
    release_evidence: dict[str, Any],
    deployment_contract: dict[str, Any],
    audit_export: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成未来 OMS/C2 可消费的脱敏输入，不提供治理控制面。"""

    safe_evidence = _redact(release_evidence)
    safe_contract = _redact(deployment_contract)
    safe_audit_export = _redact(audit_export or {})
    pipeline = safe_evidence.get("extra", {}).get("pipeline", {})
    evidence_store = safe_contract.get("evidence_store", {})
    fields = [
        "release_id",
        "source_sha",
        "upstream_sha",
        "backend_image_digest",
        "frontend_image_digest",
        "schema_version",
        "runtime_mode",
        "smoke_run_id",
        "approval",
        "unresolved",
        "pipeline_run_id",
        "audit_export",
        "evidence_store",
    ]
    return {
        "future_oms_input": True,
        "online_policy_mutation": "not_available",
        "cross_tenant_governance": "not_available",
        "governance_fields": fields,
        "release": {
            "release_id": safe_evidence.get("release_id"),
            "source_sha": safe_evidence.get("source_sha"),
            "upstream_sha": safe_evidence.get("upstream_sha"),
            "backend_image_digest": safe_evidence.get("backend_image_digest"),
            "frontend_image_digest": safe_evidence.get("frontend_image_digest"),
            "schema_version": safe_evidence.get("schema_version"),
            "runtime_mode": safe_evidence.get("runtime_mode"),
            "smoke_run_id": safe_evidence.get("smoke_run_id"),
            "approval": safe_evidence.get("approval"),
            "unresolved": safe_evidence.get("unresolved", []),
        },
        "pipeline": {
            "run_id": pipeline.get("run_id"),
            "environment": safe_contract.get("environment"),
            "topology_source": safe_contract.get("topology_source"),
        },
        "audit_export": {
            "format": safe_audit_export.get("format"),
            "row_count": safe_audit_export.get("row_count"),
            "file_ref": safe_audit_export.get("file_ref"),
            "preview": safe_audit_export.get("preview"),
        },
        "evidence_store": evidence_store,
        "governance_limitations": [
            "oms_not_delivered",
            "tms_not_delivered",
            "online_policy_mutation_not_available",
            "cross_tenant_governance_not_available",
        ],
    }


def evaluate_governance_gate(
    *,
    usage_accounted: bool,
    lightrag_remote_confirmed: bool,
    revocation_window_implemented: bool,
    policy_source_consistent: bool,
) -> dict[str, Any]:
    """C2 治理输入门禁；缺口以不可用表达而非默认放行。"""

    checks = {
        "usage_missing": usage_accounted,
        "lightrag_remote_unconfirmed": lightrag_remote_confirmed,
        "revocation_window_not_implemented": revocation_window_implemented,
        "policy_source_inconsistent": policy_source_consistent,
    }
    error_codes = sorted(code for code, ok in checks.items() if not ok)
    ready = not error_codes
    return {
        "ready": ready,
        "decision": "available_for_evidence_only" if ready else "unavailable",
        "error_codes": error_codes,
        "online_policy_mutation": "not_available",
        "cross_tenant_governance": "not_available",
    }


def build_resource_binding_evidence(
    config: DeploymentConfig,
    *,
    object_manifest_hash: str,
    lightrag_service_status: str,
    cleanup_result: str,
    lightrag_sample_ready: bool,
) -> dict[str, Any]:
    """生成 A2 ObjectStore/LightRAG binding 切换证据摘要。"""

    error_codes: list[str] = []
    blocking_unverified: list[str] = []
    if not _HASH_RE.match(object_manifest_hash):
        error_codes.append("object_manifest_hash_invalid")
    if config.object_store is None:
        error_codes.append("object_store_binding_missing")
    if config.lightrag is None:
        error_codes.append("lightrag_binding_missing")
    if lightrag_service_status != "ready":
        blocking_unverified.append("lightrag_service_" + lightrag_service_status)
    if not lightrag_sample_ready:
        blocking_unverified.append("lightrag_sample_unavailable")
    object_store = (
        {
            "provider": config.object_store.provider,
            "endpoint": _endpoint_summary(config.object_store.endpoint),
            "bucket_hash": _hash_text(config.object_store.bucket),
            "prefix_hash": _hash_text(config.object_store.prefix),
            "region_hash": _hash_text(config.object_store.region),
            "manifest_hash": object_manifest_hash,
            "cleanup_result": cleanup_result,
        }
        if config.object_store
        else None
    )
    lightrag = (
        {
            "endpoint": _endpoint_summary(config.lightrag.endpoint),
            "workspace_hash": _hash_text(config.lightrag.workspace_binding),
            "index_version": config.lightrag.index_version,
            "contract_version": config.lightrag.contract_version,
            "service_status": lightrag_service_status,
            "sample_ready": lightrag_sample_ready,
        }
        if config.lightrag
        else None
    )
    return {
        "ready": not error_codes and not blocking_unverified,
        "error_codes": sorted(set(error_codes)),
        "blocking_unverified": sorted(set(blocking_unverified)),
        "tenant_id_hash": _hash_text(str(config.tenant_id)),
        "resource": config.resource,
        "object_store": object_store,
        "lightrag": lightrag,
    }


def readiness_inventory(config: DeploymentConfig) -> dict[str, Any]:
    """生成脱敏 production readiness inventory。

    只检查配置形状与 Secret ref 是否可解析；真实 DB/ObjectStore/LightRAG/API
    连通性由迁移 Job 与 smoke harness 执行。
    """

    error_codes: list[str] = []
    secret_refs: dict[str, str] = {
        "database": config.database_secret,
        "migration_database": config.migration_database_secret,
        "signing": config.signing_secret,
        "auth_epoch": config.auth_epoch_secret,
    }
    for model in config.models:
        secret_refs[f"model:{model.profile_id}:{model.model_id}"] = model.secret
    if config.object_store is not None:
        secret_refs["object_store_access_key"] = config.object_store.access_key_secret
        secret_refs["object_store_secret_key"] = config.object_store.secret_key_secret
    if config.lightrag is not None:
        secret_refs["lightrag"] = config.lightrag.api_secret
    if config.eduplus2 is not None:
        secret_refs["eduplus2_client"] = config.eduplus2.client_secret
        if config.eduplus2.allowed_clients_ref:
            secret_refs["eduplus2_allowed_clients"] = config.eduplus2.allowed_clients_ref

    for name, reference in secret_refs.items():
        if not _is_set(reference):
            error_codes.append(name.replace(":", "_") + "_secret_missing")

    if config.production is None:
        error_codes.append("production_baseline_missing")
    else:
        for required in config.production.required_readiness:
            if required == "postgres":
                continue
            if required == "secret_provider":
                target = "secret_provider"
            elif required == "object_store":
                target = "object_store"
            else:
                target = required
            if getattr(config, target, None) is None:
                error_codes.append(f"{required}_binding_missing")

    fallback_disabled = bool(
        config.production
        and not config.production.local_authority_fallback
        and not config.production.sqlite_fallback
        and not config.production.pocketbase_fallback
    )
    if not fallback_disabled:
        error_codes.append("local_authority_fallback_enabled")

    return {
        "ready": not error_codes,
        "error_codes": sorted(set(error_codes)),
        "tenant_id_hash": _hash_text(str(config.tenant_id)),
        "resource": config.resource,
        "runtime_mode": config.production.runtime_mode if config.production else "unconfigured",
        "storage_backend": config.storage_backend,
        "backend_workers": config.backend_workers,
        "local_authority_fallback": "disabled" if fallback_disabled else "blocked",
        "object_store": {
            "provider": config.object_store.provider,
            "endpoint": _endpoint_summary(config.object_store.endpoint),
            "bucket_hash": _hash_text(config.object_store.bucket),
            "prefix_hash": _hash_text(config.object_store.prefix),
        }
        if config.object_store
        else None,
        "lightrag": {
            "endpoint": _endpoint_summary(config.lightrag.endpoint),
            "workspace_hash": _hash_text(config.lightrag.workspace_binding),
            "index_version": config.lightrag.index_version,
            "contract_version": config.lightrag.contract_version,
        }
        if config.lightrag
        else None,
        "eduplus2": {
            "base_url": _endpoint_summary(config.eduplus2.base_url),
            "client_id_hash": _hash_text(config.eduplus2.client_id),
        }
        if config.eduplus2
        else None,
        "secret_refs": sorted(secret_refs.values()),
    }


def _redact(value: Any, *, key: str = "") -> Any:
    if _SECRET_KEY_RE.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, key=str(k)) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return [_redact(v, key=key) for v in value]
    if isinstance(value, str):
        lowered = value.lower()
        if "dt_token" in lowered or "jwt" in lowered or "client-secret" in lowered:
            return "[REDACTED]"
    return value


@dataclass(frozen=True)
class ReleaseEvidence:
    """脱敏 G1 release evidence 最小结构。"""

    release_id: str
    source_sha: str
    upstream_sha: str
    backend_image_digest: str
    frontend_image_digest: str
    schema_version: str
    runtime_mode: str
    secret_refs: list[str]
    smoke_run_id: str
    approval: str
    unresolved: list[str] = field(default_factory=list)

    def __post_init__(self):
        for name in ("source_sha", "upstream_sha"):
            value = getattr(self, name)
            if not _SHA_RE.match(value):
                raise ValueError(f"{name} must be a 40-character SHA")
        for name in ("backend_image_digest", "frontend_image_digest"):
            value = getattr(self, name)
            if not _DIGEST_RE.match(value):
                raise ValueError(f"{name} must use image digest")
        for ref in self.secret_refs:
            # TypeAdapter would be heavier here; reuse pydantic alias in a small model-free path.
            if not isinstance(ref, str) or not ref.startswith("env:"):
                raise ValueError("secret_refs must only contain env: references")

    def to_dict(self, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "release_id": self.release_id,
            "source_sha": self.source_sha,
            "upstream_sha": self.upstream_sha,
            "backend_image_digest": self.backend_image_digest,
            "frontend_image_digest": self.frontend_image_digest,
            "schema_version": self.schema_version,
            "runtime_mode": self.runtime_mode,
            "secret_refs": sorted(self.secret_refs),
            "smoke_run_id": self.smoke_run_id,
            "approval": self.approval,
            "unresolved": list(self.unresolved),
        }
        if extra:
            payload["extra"] = _redact(extra)
        return payload

    def write(self, directory: str | Path, *, extra: dict[str, Any] | None = None) -> Path:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        output = path / "manifest.json"
        output.write_text(
            json.dumps(self.to_dict(extra=extra), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf8",
        )
        return output


def build_smoke_plan(*, base_url: str, lightrag_sample_ready: bool) -> dict[str, Any]:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("smoke base_url must be an HTTPS origin without credentials")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    cases = [
        ("frontend_reachable", "GET /"),
        ("http_status", "GET /api/auth/status"),
        ("eduplus2_exchange", "POST /api/v1/auth/eduplus2/exchange"),
        ("bearer_session_list", "GET /api/sessions"),
        ("ws_start_turn", "WS /api/v1/ws start_turn"),
        ("ws_auth_refresh", "WS /api/v1/ws auth_refresh"),
        ("owner_guard_denied", "cross-owner session denied"),
        ("expired_token_denied", "expired or revoked token denied"),
        ("tenant_spoof_denied", "tenant header/body/query spoof denied"),
        ("object_store", "object write/read/delete or authorized download"),
        ("audit_export", "audit query/export redacted"),
        ("tms_unavailable", "M1 must not expose unapproved /tms"),
        ("oms_unavailable", "M1 must not expose unapproved /oms"),
    ]
    blocking_unverified: list[str] = []
    if lightrag_sample_ready:
        cases.append(("lightrag_kb_retrieval", "KB ready/retrieve/reference authorization"))
    else:
        blocking_unverified.append("lightrag_sample_unavailable")
    return {
        "base_url": origin,
        "cases": [{"id": case_id, "description": description} for case_id, description in cases],
        "blocking_unverified": blocking_unverified,
        "claims_full_production": not blocking_unverified,
        "redaction": ["JWT", "dt_token", "client_secret", "model_key", "user_private_content"],
    }


__all__ = [
    "ReleaseEvidence",
    "TargetDeploymentContract",
    "build_governance_projection",
    "build_resource_binding_evidence",
    "build_smoke_plan",
    "deployment_contract_inventory",
    "evaluate_governance_gate",
    "readiness_inventory",
]
