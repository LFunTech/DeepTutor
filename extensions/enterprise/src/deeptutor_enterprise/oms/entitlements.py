"""OMS 服务授权的内部版本化事务；平台动作与目标学校权限须由调用方先核验。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.scope import TenantScope


class EntitlementRejected(ValueError):
    """服务授权命令不满足版本、状态或幂等契约。"""


@dataclass(frozen=True, slots=True)
class EntitlementRequest:
    service_id: str
    status: str
    starts_at: datetime
    expires_at: datetime
    expected_version: int
    actor_subject: str
    request_id: str
    idempotency_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class EntitlementResult:
    service_id: str
    status: str
    version: int


def _validate(scope: TenantScope, request: EntitlementRequest) -> None:
    if not isinstance(scope, TenantScope) or scope.user_id != request.actor_subject:
        raise EntitlementRejected("trusted actor scope is required")
    if request.status not in {"active", "revoked"}:
        raise EntitlementRejected("entitlement status is invalid")
    if type(request.expected_version) is not int or request.expected_version < 0:
        raise EntitlementRejected("entitlement version is invalid")
    if not isinstance(request.starts_at, datetime) or not isinstance(request.expires_at, datetime):
        raise EntitlementRejected("entitlement validity is invalid")
    if (
        request.starts_at.tzinfo is None
        or request.expires_at.tzinfo is None
        or request.expires_at <= request.starts_at
        or (request.status == "active" and request.expires_at <= datetime.now(timezone.utc))
    ):
        raise EntitlementRejected("entitlement validity is invalid")
    for name in ("service_id", "actor_subject", "request_id", "idempotency_key", "reason"):
        value = getattr(request, name)
        if not isinstance(value, str) or not value.strip() or len(value) > 255:
            raise EntitlementRejected(f"{name} is invalid")


def _fingerprint(scope: TenantScope, request: EntitlementRequest) -> str:
    payload = {
        "tenant_id": scope.tenant_id,
        "service_id": request.service_id,
        "status": request.status,
        "starts_at": request.starts_at.astimezone(timezone.utc).isoformat(),
        "expires_at": request.expires_at.astimezone(timezone.utc).isoformat(),
        "expected_version": request.expected_version,
        "reason": request.reason,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class OmsEntitlementLedger:
    """仅写入经外部平台授权后的学校服务状态，不生成额度或消耗。"""

    def __init__(self, db) -> None:
        self.db = db

    async def set(self, scope: TenantScope, request: EntitlementRequest) -> EntitlementResult:
        _validate(scope, request)
        tenant_id = UUID(scope.tenant_id)
        fingerprint = _fingerprint(scope, request)
        action = "service_entitlement.set"
        async with self.db.transaction(scope) as c:
            claimed = await (
                await c.execute(
                    "INSERT INTO oms.entitlement_commands"
                    "(actor_subject,action,idempotency_key,target_tenant_id,service_id,payload_hash) "
                    "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING "
                    "RETURNING idempotency_key",
                    (
                        request.actor_subject,
                        action,
                        request.idempotency_key,
                        tenant_id,
                        request.service_id,
                        fingerprint,
                    ),
                )
            ).fetchone()
            if claimed is None:
                prior = await (
                    await c.execute(
                        "SELECT target_tenant_id,service_id,payload_hash,result_summary "
                        "FROM oms.entitlement_commands WHERE actor_subject=%s "
                        "AND action=%s AND idempotency_key=%s FOR UPDATE",
                        (request.actor_subject, action, request.idempotency_key),
                    )
                ).fetchone()
                if (
                    prior is None
                    or prior["target_tenant_id"] != tenant_id
                    or prior["service_id"] != request.service_id
                    or prior["payload_hash"] != fingerprint
                ):
                    raise EntitlementRejected("entitlement idempotency key conflicts with payload")
                summary = prior["result_summary"]
                if not summary or summary.get("status") not in {"active", "revoked"}:
                    raise EntitlementRejected("entitlement idempotency result is incomplete")
                return EntitlementResult(
                    request.service_id, summary["status"], int(summary["version"])
                )

            current = await (
                await c.execute(
                    "SELECT status,version,starts_at,expires_at "
                    "FROM oms.tenant_service_entitlements "
                    "WHERE tenant_id=%s AND service_id=%s FOR UPDATE",
                    (tenant_id, request.service_id),
                )
            ).fetchone()
            if current is None:
                if request.expected_version != 0 or request.status != "active":
                    raise EntitlementRejected("entitlement version is stale")
                service = await (
                    await c.execute(
                        "SELECT enabled FROM oms.service_definitions WHERE service_id=%s FOR SHARE",
                        (request.service_id,),
                    )
                ).fetchone()
                if service is None or not service["enabled"]:
                    raise EntitlementRejected("service is not enabled")
                await c.execute(
                    "INSERT INTO oms.tenant_service_entitlements"
                    "(tenant_id,service_id,status,starts_at,expires_at,created_by) "
                    "VALUES(%s,%s,'active',%s,%s,%s)",
                    (
                        tenant_id,
                        request.service_id,
                        request.starts_at,
                        request.expires_at,
                        request.actor_subject,
                    ),
                )
                version = 1
            else:
                if current["version"] != request.expected_version:
                    raise EntitlementRejected("entitlement version is stale")
                if current["status"] == "revoked" and request.status == "revoked":
                    raise EntitlementRejected("entitlement is already revoked")
                if request.status == "revoked" and (
                    current["starts_at"] != request.starts_at
                    or current["expires_at"] != request.expires_at
                ):
                    raise EntitlementRejected("revocation cannot change entitlement validity")
                if request.status == "active":
                    service = await (
                        await c.execute(
                            "SELECT enabled FROM oms.service_definitions "
                            "WHERE service_id=%s FOR SHARE",
                            (request.service_id,),
                        )
                    ).fetchone()
                    if service is None or not service["enabled"]:
                        raise EntitlementRejected("service is not enabled")
                    if current["status"] == "revoked":
                        old_grant = await (
                            await c.execute(
                                "SELECT 1 FROM oms.quota_grants WHERE tenant_id=%s "
                                "AND service_id=%s AND status='active' "
                                "AND expires_at>now() LIMIT 1",
                                (tenant_id, request.service_id),
                            )
                        ).fetchone()
                        if old_grant is not None:
                            raise EntitlementRejected("old active grant blocks reactivation")
                updated = await (
                    await c.execute(
                        "UPDATE oms.tenant_service_entitlements "
                        "SET status=%s,starts_at=%s,expires_at=%s,version=version+1 "
                        "WHERE tenant_id=%s AND service_id=%s AND version=%s "
                        "RETURNING version",
                        (
                            request.status,
                            request.starts_at,
                            request.expires_at,
                            tenant_id,
                            request.service_id,
                            request.expected_version,
                        ),
                    )
                ).fetchone()
                if updated is None:
                    raise EntitlementRejected("entitlement version changed")
                version = updated["version"]

            result = EntitlementResult(request.service_id, request.status, version)
            await c.execute(
                "INSERT INTO oms.audit_events"
                "(id,actor_subject,action,target_tenant_id,object_kind,object_id,"
                "request_id,result,reason,safe_summary) "
                "VALUES(%s,%s,%s,%s,'tenant_service_entitlement',%s,%s,'success',%s,%s)",
                (
                    uuid4(),
                    request.actor_subject,
                    action,
                    tenant_id,
                    request.service_id,
                    request.request_id,
                    request.reason,
                    Jsonb({"status": result.status, "version": result.version}),
                ),
            )
            await c.execute(
                "UPDATE oms.entitlement_commands "
                "SET result_summary=%s,completed_at=now() "
                "WHERE actor_subject=%s AND action=%s AND idempotency_key=%s",
                (
                    Jsonb({"status": result.status, "version": result.version}),
                    request.actor_subject,
                    action,
                    request.idempotency_key,
                ),
            )
            return result
