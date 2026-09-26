"""OMS 内部额度授予事务；调用方必须先完成平台动作与目标租户授权。

这里不暴露 HTTP/SDK 入口，不把租户会话或 JWT role 当平台授权。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.scope import TenantScope


class GrantRejected(ValueError):
    """服务、租户授权或输入不满足授予契约。"""


class InsufficientSupply(GrantRejected):
    """兼容的有效供给不足。"""


@dataclass(frozen=True, slots=True)
class GrantRequest:
    grant_id: UUID
    service_id: str
    unit_code: str
    acquisition_method: str
    quantity: Decimal
    starts_at: datetime
    expires_at: datetime
    provider_id: str
    provider_account_id: str
    pool_id: str
    source_ref: str
    actor_subject: str
    request_id: str
    idempotency_key: str
    reason: str
    expected_entitlement_version: int


@dataclass(frozen=True, slots=True)
class GrantResult:
    grant_id: UUID
    allocations: tuple[tuple[UUID, Decimal], ...]


@dataclass(frozen=True, slots=True)
class RevokeRequest:
    grant_id: UUID
    expected_version: int
    actor_subject: str
    request_id: str
    idempotency_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class RevokeResult:
    grant_id: UUID
    version: int
    released_units: Decimal


def _validate_revoke(scope: TenantScope, request: RevokeRequest) -> None:
    if not isinstance(scope, TenantScope) or scope.user_id != request.actor_subject:
        raise GrantRejected("trusted actor scope is required")
    if not isinstance(request.grant_id, UUID) or type(request.expected_version) is not int:
        raise GrantRejected("grant id or version is invalid")
    if request.expected_version < 1:
        raise GrantRejected("grant version is invalid")
    for name in ("actor_subject", "request_id", "idempotency_key", "reason"):
        value = getattr(request, name)
        if not isinstance(value, str) or not value.strip() or len(value) > 255:
            raise GrantRejected(f"{name} is invalid")


def _revoke_fingerprint(scope: TenantScope, request: RevokeRequest) -> str:
    data = {
        "tenant_id": scope.tenant_id,
        "grant_id": str(request.grant_id),
        "expected_version": request.expected_version,
        "reason": request.reason,
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validate(scope: TenantScope, request: GrantRequest) -> None:
    if not isinstance(scope, TenantScope) or scope.user_id != request.actor_subject:
        raise GrantRejected("trusted actor scope is required")
    if not isinstance(request.grant_id, UUID):
        raise GrantRejected("grant id is invalid")
    if request.acquisition_method not in {"gift", "recharge"}:
        raise GrantRejected("grant acquisition method is invalid")
    if not isinstance(request.quantity, Decimal) or not request.quantity.is_finite():
        raise GrantRejected("grant quantity is invalid")
    if request.quantity <= 0 or request.quantity.as_tuple().exponent < -6:
        raise GrantRejected("grant quantity must be positive with at most six decimals")
    if (
        request.starts_at.tzinfo is None
        or request.expires_at.tzinfo is None
        or request.expires_at <= request.starts_at
        or request.expires_at <= datetime.now(timezone.utc)
    ):
        raise GrantRejected("grant validity is invalid")
    if request.expected_entitlement_version < 1:
        raise GrantRejected("entitlement version is invalid")
    for name in (
        "service_id",
        "unit_code",
        "provider_id",
        "pool_id",
        "source_ref",
        "actor_subject",
        "request_id",
        "idempotency_key",
        "reason",
    ):
        value = getattr(request, name)
        if not isinstance(value, str) or not value.strip() or len(value) > 255:
            raise GrantRejected(f"{name} is invalid")


def _fingerprint(scope: TenantScope, request: GrantRequest) -> str:
    """关联 ID 不参与去重；同一业务键改变任何账务字段均冲突。"""

    data = {
        "tenant_id": scope.tenant_id,
        "grant_id": str(request.grant_id),
        "service_id": request.service_id,
        "unit_code": request.unit_code,
        "acquisition_method": request.acquisition_method,
        "quantity": str(request.quantity.normalize()),
        "starts_at": request.starts_at.astimezone(timezone.utc).isoformat(),
        "expires_at": request.expires_at.astimezone(timezone.utc).isoformat(),
        "provider_id": request.provider_id,
        "provider_account_id": request.provider_account_id,
        "pool_id": request.pool_id,
        "source_ref": request.source_ref,
        "reason": request.reason,
        "expected_entitlement_version": request.expected_entitlement_version,
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class OmsGrantLedger:
    """只负责一笔授予的业务原子性；不代替 API 层平台授权。"""

    def __init__(self, db) -> None:
        self.db = db

    async def revoke(self, scope: TenantScope, request: RevokeRequest) -> RevokeResult:
        """只释放未使用承诺；在途预留及历史结算由原 attempt 继续核对。"""

        _validate_revoke(scope, request)
        tenant_id = UUID(scope.tenant_id)
        fingerprint = _revoke_fingerprint(scope, request)
        async with self.db.transaction(scope) as c:
            claimed = await (
                await c.execute(
                    "INSERT INTO oms.grant_commands"
                    "(actor_subject,action,idempotency_key,target_tenant_id,payload_hash,grant_id) "
                    "VALUES(%s,'quota.revoke',%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING RETURNING grant_id",
                    (
                        request.actor_subject,
                        request.idempotency_key,
                        tenant_id,
                        fingerprint,
                        request.grant_id,
                    ),
                )
            ).fetchone()
            if claimed is None:
                prior = await (
                    await c.execute(
                        "SELECT target_tenant_id,payload_hash,grant_id,result,result_summary "
                        "FROM oms.grant_commands WHERE actor_subject=%s "
                        "AND action='quota.revoke' AND idempotency_key=%s FOR UPDATE",
                        (request.actor_subject, request.idempotency_key),
                    )
                ).fetchone()
                if (
                    prior is None
                    or prior["target_tenant_id"] != tenant_id
                    or prior["payload_hash"] != fingerprint
                    or prior["grant_id"] != request.grant_id
                ):
                    raise GrantRejected("revoke idempotency key conflicts with prior payload")
                if prior["result"] != "success":
                    raise GrantRejected("revoke idempotency result is incomplete")
                summary = prior["result_summary"]
                return RevokeResult(
                    request.grant_id,
                    int(summary["version"]),
                    Decimal(summary["released_units"]),
                )

            identity = await (
                await c.execute(
                    "SELECT service_id FROM oms.quota_grants WHERE tenant_id=%s AND id=%s",
                    (tenant_id, request.grant_id),
                )
            ).fetchone()
            if identity is None:
                raise GrantRejected("grant is unavailable")
            # 与授予/预留统一：租户权益锁 → 池 advisory 锁 → grant/lot 行锁。
            entitlement = await (
                await c.execute(
                    "SELECT service_id FROM oms.tenant_service_entitlements "
                    "WHERE tenant_id=%s AND service_id=%s FOR UPDATE",
                    (tenant_id, identity["service_id"]),
                )
            ).fetchone()
            if entitlement is None:
                raise GrantRejected("grant entitlement is unavailable")
            pools = await (
                await c.execute(
                    "SELECT DISTINCT sl.service_id,sl.provider_id,sl.provider_account_id,"
                    "sl.pool_id,sl.unit_code FROM oms.grant_commitments gc "
                    "JOIN oms.supply_lots sl ON sl.id=gc.lot_id "
                    "WHERE gc.tenant_id=%s AND gc.grant_id=%s",
                    (tenant_id, request.grant_id),
                )
            ).fetchall()
            if not pools:
                raise GrantRejected("grant commitments need reconciliation")
            for pool in sorted(
                pools,
                key=lambda row: (
                    row["service_id"],
                    row["provider_id"],
                    row["provider_account_id"],
                    row["pool_id"],
                    row["unit_code"],
                ),
            ):
                await c.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    (
                        "oms-pool:"
                        f"{pool['service_id']}:{pool['provider_id']}:"
                        f"{pool['provider_account_id']}:{pool['pool_id']}:{pool['unit_code']}",
                    ),
                )
            grant = await (
                await c.execute(
                    "SELECT status,version,quantity,service_id FROM oms.quota_grants "
                    "WHERE tenant_id=%s AND id=%s FOR UPDATE",
                    (tenant_id, request.grant_id),
                )
            ).fetchone()
            if (
                grant is None
                or grant["status"] != "active"
                or grant["version"] != request.expected_version
            ):
                raise GrantRejected("grant is revoked or version is stale")
            rows = await (
                await c.execute(
                    "SELECT gc.lot_id,gc.committed_total,gc.unspent "
                    "FROM oms.grant_commitments gc "
                    "JOIN oms.supply_lots sl ON sl.id=gc.lot_id "
                    "WHERE gc.tenant_id=%s AND gc.grant_id=%s "
                    "ORDER BY sl.id FOR UPDATE OF gc,sl",
                    (tenant_id, request.grant_id),
                )
            ).fetchall()
            if sum(row["committed_total"] for row in rows) != grant["quantity"]:
                raise GrantRejected("grant commitments need reconciliation")
            released = Decimal(0)
            for row in rows:
                amount = row["unspent"]
                if amount == 0:
                    continue
                commitment = await (
                    await c.execute(
                        "UPDATE oms.grant_commitments "
                        "SET unspent=0,released=released+%s "
                        "WHERE tenant_id=%s AND grant_id=%s AND lot_id=%s "
                        "AND unspent=%s RETURNING lot_id",
                        (amount, tenant_id, request.grant_id, row["lot_id"], amount),
                    )
                ).fetchone()
                if commitment is None:
                    raise GrantRejected("grant commitment changed during revocation")
                lot = await (
                    await c.execute(
                        "UPDATE oms.supply_lots "
                        "SET committed_unspent=committed_unspent-%s "
                        "WHERE id=%s AND committed_unspent>=%s RETURNING id",
                        (amount, row["lot_id"], amount),
                    )
                ).fetchone()
                if lot is None:
                    raise GrantRejected("supply commitment changed during revocation")
                released += amount
            updated = await (
                await c.execute(
                    "UPDATE oms.quota_grants SET status='revoked',version=version+1 "
                    "WHERE tenant_id=%s AND id=%s AND version=%s RETURNING version",
                    (tenant_id, request.grant_id, request.expected_version),
                )
            ).fetchone()
            if updated is None:
                raise GrantRejected("grant version changed during revocation")
            result = RevokeResult(request.grant_id, updated["version"], released)
            await c.execute(
                "INSERT INTO oms.audit_events"
                "(id,actor_subject,action,target_tenant_id,object_kind,object_id,"
                "request_id,result,reason,safe_summary) "
                "VALUES(%s,%s,'quota.revoke',%s,'quota_grant',%s,%s,'success',%s,%s)",
                (
                    uuid4(),
                    request.actor_subject,
                    tenant_id,
                    str(request.grant_id),
                    request.request_id,
                    request.reason,
                    Jsonb({"service_id": grant["service_id"], "released_units": str(released)}),
                ),
            )
            await c.execute(
                "UPDATE oms.grant_commands SET result='success',completed_at=now(),"
                "result_summary=%s WHERE actor_subject=%s AND action='quota.revoke' "
                "AND idempotency_key=%s",
                (
                    Jsonb({"version": result.version, "released_units": str(released)}),
                    request.actor_subject,
                    request.idempotency_key,
                ),
            )
            return result

    async def grant(self, scope: TenantScope, request: GrantRequest) -> GrantResult:
        _validate(scope, request)
        tenant_id = UUID(scope.tenant_id)
        fingerprint = _fingerprint(scope, request)
        rejected: InsufficientSupply | None = None
        allocations: list[tuple[UUID, Decimal]] = []
        async with self.db.transaction(scope) as c:
            claimed = await (
                await c.execute(
                    "INSERT INTO oms.grant_commands"
                    "(actor_subject,action,idempotency_key,target_tenant_id,payload_hash,grant_id) "
                    "VALUES(%s,'quota.grant',%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING RETURNING grant_id",
                    (
                        request.actor_subject,
                        request.idempotency_key,
                        tenant_id,
                        fingerprint,
                        request.grant_id,
                    ),
                )
            ).fetchone()
            if claimed is None:
                prior = await (
                    await c.execute(
                        "SELECT target_tenant_id,payload_hash,grant_id,result "
                        "FROM oms.grant_commands "
                        "WHERE actor_subject=%s AND action='quota.grant' "
                        "AND idempotency_key=%s FOR UPDATE",
                        (request.actor_subject, request.idempotency_key),
                    )
                ).fetchone()
                if (
                    prior is None
                    or prior["target_tenant_id"] != tenant_id
                    or prior["payload_hash"] != fingerprint
                    or prior["grant_id"] != request.grant_id
                ):
                    raise GrantRejected("grant idempotency key conflicts with prior payload")
                if prior["result"] == "denied":
                    raise InsufficientSupply("compatible finite supply is insufficient")
                if prior["result"] != "success":
                    raise GrantRejected("grant idempotency result is incomplete")
                rows = await (
                    await c.execute(
                        "SELECT gc.lot_id,gc.committed_total "
                        "FROM oms.grant_commitments gc "
                        "JOIN oms.supply_lots sl ON sl.id=gc.lot_id "
                        "WHERE gc.tenant_id=%s AND gc.grant_id=%s "
                        "ORDER BY sl.expires_at,sl.id",
                        (tenant_id, request.grant_id),
                    )
                ).fetchall()
                return GrantResult(
                    request.grant_id,
                    tuple((row["lot_id"], row["committed_total"]) for row in rows),
                )

            service = await (
                await c.execute(
                    "SELECT unit_code,enabled FROM oms.service_definitions "
                    "WHERE service_id=%s FOR SHARE",
                    (request.service_id,),
                )
            ).fetchone()
            if not service or not service["enabled"] or service["unit_code"] != request.unit_code:
                raise GrantRejected("service is not enabled for the requested unit")

            entitlement = await (
                await c.execute(
                    "SELECT status,starts_at,expires_at,version "
                    "FROM oms.tenant_service_entitlements "
                    "WHERE tenant_id=%s AND service_id=%s FOR UPDATE",
                    (tenant_id, request.service_id),
                )
            ).fetchone()
            if (
                not entitlement
                or entitlement["status"] != "active"
                or entitlement["version"] != request.expected_entitlement_version
                or entitlement["starts_at"] > request.starts_at
                or entitlement["expires_at"] < request.expires_at
            ):
                raise GrantRejected("tenant service entitlement is unavailable or stale")

            await c.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (
                    "oms-pool:"
                    f"{request.service_id}:{request.provider_id}:"
                    f"{request.provider_account_id}:{request.pool_id}:{request.unit_code}",
                ),
            )

            lots = await (
                await c.execute(
                    "SELECT id,hard_ceiling,settled_lifetime,committed_unspent,reserved_inflight "
                    "FROM oms.supply_lots WHERE service_id=%s AND provider_id=%s "
                    "AND provider_account_id=%s AND pool_id=%s AND unit_code=%s "
                    "AND status='active' AND hard_ceiling IS NOT NULL "
                    "AND starts_at<=now() AND starts_at<=%s "
                    "AND expires_at>now() AND expires_at>=%s "
                    "ORDER BY expires_at,id FOR UPDATE",
                    (
                        request.service_id,
                        request.provider_id,
                        request.provider_account_id,
                        request.pool_id,
                        request.unit_code,
                        request.starts_at,
                        request.expires_at,
                    ),
                )
            ).fetchall()
            remaining = request.quantity
            for lot in lots:
                available = (
                    lot["hard_ceiling"]
                    - lot["settled_lifetime"]
                    - lot["committed_unspent"]
                    - lot["reserved_inflight"]
                )
                take = min(remaining, available)
                if take > 0:
                    allocations.append((lot["id"], take))
                    remaining -= take
                if remaining == 0:
                    break

            if remaining:
                rejected = InsufficientSupply("compatible finite supply is insufficient")
            else:
                await c.execute(
                    "INSERT INTO oms.quota_grants"
                    "(id,tenant_id,service_id,unit_code,acquisition_method,quantity,"
                    "starts_at,expires_at,created_by,source_ref) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        request.grant_id,
                        tenant_id,
                        request.service_id,
                        request.unit_code,
                        request.acquisition_method,
                        request.quantity,
                        request.starts_at,
                        request.expires_at,
                        request.actor_subject,
                        request.source_ref,
                    ),
                )
                for lot_id, quantity in allocations:
                    updated = await (
                        await c.execute(
                            "UPDATE oms.supply_lots "
                            "SET committed_unspent=committed_unspent+%s "
                            "WHERE id=%s AND status='active' AND hard_ceiling IS NOT NULL "
                            "AND hard_ceiling-settled_lifetime-committed_unspent-reserved_inflight>=%s "
                            "RETURNING id",
                            (quantity, lot_id, quantity),
                        )
                    ).fetchone()
                    if updated is None:
                        raise GrantRejected("supply changed during grant")
                    await c.execute(
                        "INSERT INTO oms.grant_commitments"
                        "(tenant_id,grant_id,lot_id,committed_total,unspent) "
                        "VALUES(%s,%s,%s,%s,%s)",
                        (tenant_id, request.grant_id, lot_id, quantity, quantity),
                    )

            await c.execute(
                "INSERT INTO oms.audit_events"
                "(id,actor_subject,action,target_tenant_id,object_kind,object_id,"
                "request_id,result,reason,safe_summary) "
                "VALUES(%s,%s,'quota.grant',%s,'quota_grant',%s,%s,%s,%s,%s)",
                (
                    uuid4(),
                    request.actor_subject,
                    tenant_id,
                    str(request.grant_id),
                    request.request_id,
                    "denied" if rejected else "success",
                    "insufficient_supply" if rejected else request.reason,
                    Jsonb(
                        {
                            "service_id": request.service_id,
                            "unit_code": request.unit_code,
                            "acquisition_method": request.acquisition_method,
                            "quantity": str(request.quantity),
                            "source_ref_hash": hashlib.sha256(
                                request.source_ref.encode()
                            ).hexdigest(),
                        }
                    ),
                ),
            )
            await c.execute(
                "UPDATE oms.grant_commands SET result=%s,completed_at=now() "
                "WHERE actor_subject=%s AND action='quota.grant' AND idempotency_key=%s",
                (
                    "denied" if rejected else "success",
                    request.actor_subject,
                    request.idempotency_key,
                ),
            )
        if rejected:
            raise rejected
        return GrantResult(request.grant_id, tuple(allocations))
