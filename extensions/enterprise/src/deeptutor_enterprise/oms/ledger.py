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

from .value_validation import (
    OmsValueError,
    validate_entitlement_row,
    validate_grant_command_row,
    validate_oms_audit_result,
    validate_quota_grant_row,
    validate_service_definition_row,
    validate_supply_lot_row,
)


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


@dataclass(frozen=True, slots=True)
class ExpireRequest:
    grant_id: UUID
    expected_version: int
    actor_subject: str
    request_id: str
    idempotency_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class ExpireResult:
    grant_id: UUID
    version: int
    released_units: Decimal


@dataclass(frozen=True, slots=True)
class AdjustRequest:
    grant_id: UUID
    expected_version: int
    new_quantity: Decimal
    actor_subject: str
    request_id: str
    idempotency_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class AdjustResult:
    grant_id: UUID
    version: int
    previous_quantity: Decimal
    quantity: Decimal


def _validate_revoke(scope: TenantScope, request: RevokeRequest | ExpireRequest) -> None:
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


def _revoke_fingerprint(scope: TenantScope, request: RevokeRequest | ExpireRequest) -> str:
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

    @staticmethod
    def _reject_value_error(error: OmsValueError) -> None:
        raise GrantRejected(str(error)) from None

    @staticmethod
    async def _require_quota_management(c, management_identity, tenant_id: UUID) -> None:
        if management_identity is None:
            return
        from ..management.authorization import require_management_permission

        await require_management_permission(
            c,
            management_identity,
            "ops.quotas.manage",
            target_school_id=tenant_id,
            write=True,
            _lock_school_id=tenant_id,
        )

    async def adjust(
        self,
        scope: TenantScope,
        request: AdjustRequest,
        *,
        management_identity=None,
    ) -> AdjustResult:
        """按版本调整当前额度，只在供给池中转移未使用承诺。"""

        _validate_revoke(scope, request)
        quantity = request.new_quantity
        if (
            not isinstance(quantity, Decimal)
            or not quantity.is_finite()
            or quantity <= 0
            or quantity.as_tuple().exponent < -6
        ):
            raise GrantRejected("adjusted grant quantity is invalid")
        tenant_id = UUID(scope.tenant_id)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "tenant_id": scope.tenant_id,
                    "grant_id": str(request.grant_id),
                    "expected_version": request.expected_version,
                    "new_quantity": str(quantity.normalize()),
                    "reason": request.reason,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        rejected: InsufficientSupply | None = None
        result: AdjustResult | None = None
        async with self.db.transaction(scope) as c:
            await self._require_quota_management(c, management_identity, tenant_id)
            claimed = await (
                await c.execute(
                    "INSERT INTO oms.grant_commands"
                    "(actor_subject,action,idempotency_key,target_tenant_id,payload_hash,grant_id) "
                    "VALUES(%s,'quota.adjust',%s,%s,%s,%s) "
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
                        "AND action='quota.adjust' AND idempotency_key=%s FOR UPDATE",
                        (request.actor_subject, request.idempotency_key),
                    )
                ).fetchone()
                if (
                    prior is None
                    or prior["target_tenant_id"] != tenant_id
                    or prior["payload_hash"] != fingerprint
                    or prior["grant_id"] != request.grant_id
                ):
                    raise GrantRejected("adjust idempotency key conflicts with prior payload")
                try:
                    validate_grant_command_row(prior)
                except OmsValueError as error:
                    self._reject_value_error(error)
                if prior["result"] == "denied":
                    raise InsufficientSupply("compatible finite supply is insufficient")
                if prior["result"] != "success":
                    raise GrantRejected("adjust idempotency result is incomplete")
                summary = prior["result_summary"]
                return AdjustResult(
                    request.grant_id,
                    int(summary["version"]),
                    Decimal(summary["previous_quantity"]),
                    Decimal(summary["quantity"]),
                )

            identity = await (
                await c.execute(
                    "SELECT service_id FROM oms.quota_grants WHERE tenant_id=%s AND id=%s",
                    (tenant_id, request.grant_id),
                )
            ).fetchone()
            if identity is None:
                raise GrantRejected("grant is unavailable")
            entitlement = await (
                await c.execute(
                    "SELECT status,starts_at,expires_at,version "
                    "FROM oms.tenant_service_entitlements "
                    "WHERE tenant_id=%s AND service_id=%s FOR UPDATE",
                    (tenant_id, identity["service_id"]),
                )
            ).fetchone()
            if entitlement is None:
                raise GrantRejected("grant entitlement is unavailable")
            try:
                validate_entitlement_row(entitlement)
            except OmsValueError as error:
                self._reject_value_error(error)
            pools = await (
                await c.execute(
                    "SELECT DISTINCT sl.service_id,sl.provider_id,sl.provider_account_id,"
                    "sl.pool_id,sl.unit_code FROM oms.grant_commitments gc "
                    "JOIN oms.supply_lots sl ON sl.id=gc.lot_id "
                    "WHERE gc.tenant_id=%s AND gc.grant_id=%s",
                    (tenant_id, request.grant_id),
                )
            ).fetchall()
            if len(pools) != 1:
                raise GrantRejected("grant pool needs reconciliation")
            pool = pools[0]
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
                    "SELECT status,version,quantity,adjustment_released,service_id,starts_at,"
                    "expires_at,acquisition_method "
                    "FROM oms.quota_grants WHERE tenant_id=%s AND id=%s FOR UPDATE",
                    (tenant_id, request.grant_id),
                )
            ).fetchone()
            if grant is not None:
                try:
                    validate_quota_grant_row(grant)
                except OmsValueError as error:
                    self._reject_value_error(error)
            if (
                grant is None
                or grant["status"] != "active"
                or grant["version"] != request.expected_version
            ):
                raise GrantRejected("grant version is stale or inactive")
            now = (await (await c.execute("SELECT now() AS current_time")).fetchone())[
                "current_time"
            ]
            if grant["expires_at"] <= now:
                raise GrantRejected("expired grant cannot be adjusted")
            previous_quantity = grant["quantity"] - grant["adjustment_released"]
            delta = quantity - previous_quantity
            if delta == 0:
                raise GrantRejected("adjustment must change quantity")
            rows = await (
                await c.execute(
                    "SELECT gc.lot_id,gc.committed_total,gc.unspent,gc.reserved,gc.settled,"
                    "gc.released,sl.expires_at "
                    "FROM oms.grant_commitments gc "
                    "JOIN oms.supply_lots sl ON sl.id=gc.lot_id "
                    "WHERE gc.tenant_id=%s AND gc.grant_id=%s "
                    "ORDER BY sl.id FOR UPDATE OF gc,sl",
                    (tenant_id, request.grant_id),
                )
            ).fetchall()
            if sum(row["committed_total"] for row in rows) != grant["quantity"]:
                raise GrantRejected("grant commitments need reconciliation")
            if delta < 0:
                remaining = -delta
                for row in sorted(
                    rows, key=lambda row: (row["expires_at"], row["lot_id"]), reverse=True
                ):
                    take = min(remaining, row["unspent"])
                    if take <= 0:
                        continue
                    updated = await (
                        await c.execute(
                            "UPDATE oms.grant_commitments "
                            "SET unspent=unspent-%s,released=released+%s "
                            "WHERE tenant_id=%s AND grant_id=%s AND lot_id=%s "
                            "AND unspent>=%s RETURNING lot_id",
                            (take, take, tenant_id, request.grant_id, row["lot_id"], take),
                        )
                    ).fetchone()
                    if updated is None:
                        raise GrantRejected("grant commitment changed during adjustment")
                    updated = await (
                        await c.execute(
                            "UPDATE oms.supply_lots SET committed_unspent=committed_unspent-%s "
                            "WHERE id=%s AND committed_unspent>=%s RETURNING id",
                            (take, row["lot_id"], take),
                        )
                    ).fetchone()
                    if updated is None:
                        raise GrantRejected("supply commitment changed during adjustment")
                    remaining -= take
                    if remaining == 0:
                        break
                if remaining:
                    raise GrantRejected("adjustment exceeds unspent commitment")
            else:
                if (
                    entitlement["status"] != "active"
                    or entitlement["starts_at"] > now
                    or entitlement["expires_at"] < grant["expires_at"]
                ):
                    raise GrantRejected("tenant service entitlement is unavailable")
                lots = await (
                    await c.execute(
                        "SELECT id,hard_ceiling,settled_lifetime,committed_unspent,"
                        "reserved_inflight,status,supply_basis,verified_at,created_by,version "
                        "FROM oms.supply_lots WHERE service_id=%s AND provider_id=%s "
                        "AND provider_account_id=%s AND pool_id=%s AND unit_code=%s "
                        "AND status='active' AND hard_ceiling IS NOT NULL "
                        "AND supply_basis='native_units' AND verified_at IS NOT NULL "
                        "AND starts_at<=now() AND expires_at>now() AND expires_at>=%s "
                        "ORDER BY expires_at,id FOR UPDATE",
                        (
                            pool["service_id"],
                            pool["provider_id"],
                            pool["provider_account_id"],
                            pool["pool_id"],
                            pool["unit_code"],
                            grant["expires_at"],
                        ),
                    )
                ).fetchall()
                remaining = delta
                allocations: list[tuple[UUID, Decimal]] = []
                for lot in lots:
                    try:
                        validate_supply_lot_row(lot)
                    except OmsValueError as error:
                        self._reject_value_error(error)
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
                    for lot_id, take in allocations:
                        updated = await (
                            await c.execute(
                                "UPDATE oms.supply_lots SET committed_unspent=committed_unspent+%s "
                                "WHERE id=%s AND status='active' AND hard_ceiling IS NOT NULL "
                                "AND supply_basis='native_units' AND verified_at IS NOT NULL "
                                "AND hard_ceiling-settled_lifetime-committed_unspent-reserved_inflight>=%s "
                                "RETURNING id",
                                (take, lot_id, take),
                            )
                        ).fetchone()
                        if updated is None:
                            raise GrantRejected("supply changed during adjustment")
                        await c.execute(
                            "INSERT INTO oms.grant_commitments"
                            "(tenant_id,grant_id,lot_id,committed_total,unspent) "
                            "VALUES(%s,%s,%s,%s,%s) "
                            "ON CONFLICT (tenant_id,grant_id,lot_id) DO UPDATE "
                            "SET committed_total=oms.grant_commitments.committed_total+EXCLUDED.committed_total,"
                            "unspent=oms.grant_commitments.unspent+EXCLUDED.unspent",
                            (tenant_id, request.grant_id, lot_id, take, take),
                        )
            if rejected is None:
                updated = await (
                    await c.execute(
                        "UPDATE oms.quota_grants SET "
                        "quantity=quantity+%s,adjustment_released=adjustment_released+%s,"
                        "version=version+1 "
                        "WHERE tenant_id=%s AND id=%s AND version=%s RETURNING version",
                        (
                            delta if delta > 0 else Decimal(0),
                            -delta if delta < 0 else Decimal(0),
                            tenant_id,
                            request.grant_id,
                            request.expected_version,
                        ),
                    )
                ).fetchone()
                if updated is None:
                    raise GrantRejected("grant version changed during adjustment")
                result = AdjustResult(
                    request.grant_id, updated["version"], previous_quantity, quantity
                )
            validate_oms_audit_result("denied" if rejected else "success")
            await c.execute(
                "INSERT INTO oms.audit_events"
                "(id,actor_subject,action,target_tenant_id,object_kind,object_id,"
                "request_id,result,reason,safe_summary) "
                "VALUES(%s,%s,'quota.adjust',%s,'quota_grant',%s,%s,%s,%s,%s)",
                (
                    uuid4(),
                    request.actor_subject,
                    tenant_id,
                    str(request.grant_id),
                    request.request_id,
                    "denied" if rejected else "success",
                    request.reason,
                    Jsonb(
                        {
                            "previous_quantity": str(previous_quantity),
                            "quantity": str(quantity),
                            "delta": str(delta),
                        }
                    ),
                ),
            )
            await c.execute(
                "UPDATE oms.grant_commands SET result=%s,completed_at=now(),result_summary=%s "
                "WHERE actor_subject=%s AND action='quota.adjust' AND idempotency_key=%s",
                (
                    "denied" if rejected else "success",
                    Jsonb(
                        {}
                        if rejected
                        else {
                            "version": result.version,
                            "previous_quantity": str(result.previous_quantity),
                            "quantity": str(result.quantity),
                        }
                    ),
                    request.actor_subject,
                    request.idempotency_key,
                ),
            )
        if rejected:
            raise rejected
        assert result is not None
        return result

    async def revoke(
        self,
        scope: TenantScope,
        request: RevokeRequest,
        *,
        management_identity=None,
    ) -> RevokeResult:
        """只释放未使用承诺；在途预留及历史结算由原 attempt 继续核对。"""

        version, released = await self._close_grant(
            scope,
            request,
            action="quota.revoke",
            terminal_status="revoked",
            require_due=False,
            management_identity=management_identity,
        )
        return RevokeResult(request.grant_id, version, released)

    async def expire(
        self,
        scope: TenantScope,
        request: ExpireRequest,
        *,
        management_identity=None,
    ) -> ExpireResult:
        """到期后释放未使用承诺，远端未知 attempt 的预留继续留账。"""

        version, released = await self._close_grant(
            scope,
            request,
            action="quota.expire",
            terminal_status="expired",
            require_due=True,
            management_identity=management_identity,
        )
        return ExpireResult(request.grant_id, version, released)

    async def _close_grant(
        self,
        scope: TenantScope,
        request: RevokeRequest | ExpireRequest,
        *,
        action: str,
        terminal_status: str,
        require_due: bool,
        management_identity=None,
    ) -> tuple[int, Decimal]:

        _validate_revoke(scope, request)
        tenant_id = UUID(scope.tenant_id)
        fingerprint = _revoke_fingerprint(scope, request)
        async with self.db.transaction(scope) as c:
            await self._require_quota_management(c, management_identity, tenant_id)
            claimed = await (
                await c.execute(
                    "INSERT INTO oms.grant_commands"
                    "(actor_subject,action,idempotency_key,target_tenant_id,payload_hash,grant_id) "
                    "VALUES(%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING RETURNING grant_id",
                    (
                        request.actor_subject,
                        action,
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
                        "AND action=%s AND idempotency_key=%s FOR UPDATE",
                        (request.actor_subject, action, request.idempotency_key),
                    )
                ).fetchone()
                if (
                    prior is None
                    or prior["target_tenant_id"] != tenant_id
                    or prior["payload_hash"] != fingerprint
                    or prior["grant_id"] != request.grant_id
                ):
                    raise GrantRejected("revoke idempotency key conflicts with prior payload")
                try:
                    validate_grant_command_row(prior)
                except OmsValueError as error:
                    self._reject_value_error(error)
                if prior["result"] != "success":
                    raise GrantRejected("revoke idempotency result is incomplete")
                summary = prior["result_summary"]
                return int(summary["version"]), Decimal(summary["released_units"])

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
                    "SELECT service_id,status,version FROM oms.tenant_service_entitlements "
                    "WHERE tenant_id=%s AND service_id=%s FOR UPDATE",
                    (tenant_id, identity["service_id"]),
                )
            ).fetchone()
            if entitlement is None:
                raise GrantRejected("grant entitlement is unavailable")
            try:
                validate_entitlement_row(entitlement)
            except OmsValueError as error:
                self._reject_value_error(error)
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
                    "SELECT status,version,quantity,service_id,expires_at,acquisition_method "
                    "FROM oms.quota_grants "
                    "WHERE tenant_id=%s AND id=%s FOR UPDATE",
                    (tenant_id, request.grant_id),
                )
            ).fetchone()
            if grant is not None:
                try:
                    validate_quota_grant_row(grant)
                except OmsValueError as error:
                    self._reject_value_error(error)
            if (
                grant is None
                or grant["status"] != "active"
                or grant["version"] != request.expected_version
            ):
                raise GrantRejected("grant is revoked or version is stale")
            if require_due:
                due = await (await c.execute("SELECT now() AS current_time")).fetchone()
                if grant["expires_at"] > due["current_time"]:
                    raise GrantRejected("grant is not expired")
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
                    "UPDATE oms.quota_grants SET status=%s,version=version+1 "
                    "WHERE tenant_id=%s AND id=%s AND version=%s RETURNING version",
                    (terminal_status, tenant_id, request.grant_id, request.expected_version),
                )
            ).fetchone()
            if updated is None:
                raise GrantRejected("grant version changed during revocation")
            validate_oms_audit_result("success")
            await c.execute(
                "INSERT INTO oms.audit_events"
                "(id,actor_subject,action,target_tenant_id,object_kind,object_id,"
                "request_id,result,reason,safe_summary) "
                "VALUES(%s,%s,%s,%s,'quota_grant',%s,%s,'success',%s,%s)",
                (
                    uuid4(),
                    request.actor_subject,
                    action,
                    tenant_id,
                    str(request.grant_id),
                    request.request_id,
                    request.reason,
                    Jsonb({"service_id": grant["service_id"], "released_units": str(released)}),
                ),
            )
            await c.execute(
                "UPDATE oms.grant_commands SET result='success',completed_at=now(),"
                "result_summary=%s WHERE actor_subject=%s AND action=%s "
                "AND idempotency_key=%s",
                (
                    Jsonb({"version": updated["version"], "released_units": str(released)}),
                    request.actor_subject,
                    action,
                    request.idempotency_key,
                ),
            )
            return updated["version"], released

    async def grant(
        self,
        scope: TenantScope,
        request: GrantRequest,
        *,
        management_identity=None,
    ) -> GrantResult:
        _validate(scope, request)
        tenant_id = UUID(scope.tenant_id)
        fingerprint = _fingerprint(scope, request)
        rejected: InsufficientSupply | None = None
        allocations: list[tuple[UUID, Decimal]] = []
        async with self.db.transaction(scope) as c:
            await self._require_quota_management(c, management_identity, tenant_id)
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
                try:
                    validate_grant_command_row(prior)
                except OmsValueError as error:
                    self._reject_value_error(error)
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
                    "SELECT unit_code,enabled,resource_category FROM oms.service_definitions "
                    "WHERE service_id=%s FOR SHARE",
                    (request.service_id,),
                )
            ).fetchone()
            if service:
                try:
                    validate_service_definition_row(service)
                except OmsValueError as error:
                    self._reject_value_error(error)
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
            if entitlement:
                try:
                    validate_entitlement_row(entitlement)
                except OmsValueError as error:
                    self._reject_value_error(error)
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
                    "SELECT id,hard_ceiling,settled_lifetime,committed_unspent,"
                    "reserved_inflight,status,supply_basis,verified_at,created_by,version "
                    "FROM oms.supply_lots WHERE service_id=%s AND provider_id=%s "
                    "AND provider_account_id=%s AND pool_id=%s AND unit_code=%s "
                    "AND status='active' AND hard_ceiling IS NOT NULL "
                    "AND supply_basis='native_units' AND verified_at IS NOT NULL "
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
                try:
                    validate_supply_lot_row(lot)
                except OmsValueError as error:
                    self._reject_value_error(error)
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
                            "AND supply_basis='native_units' AND verified_at IS NOT NULL "
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

            validate_oms_audit_result("denied" if rejected else "success")
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
