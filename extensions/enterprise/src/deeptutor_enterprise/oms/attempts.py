"""OMS 内部 provider attempt 总账；外部授权、配置 readiness 和真实证据由调用方负责。

预留提交后才能调用 provider；发送前先记录 dispatch intent。网络调用不在数据库
事务内。发出后结果未知只保留预留，绝不按失败零耗释放。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.scope import TenantScope


class AttemptRejected(ValueError):
    """预留时服务授权、配额、供给或可信主体不满足要求。"""


class QuotaUnavailable(AttemptRejected):
    """目标服务没有足够的有效租户额度。"""


class SettlementRejected(ValueError):
    """结算证据、状态或调用归属不满足要求。"""


class UsageExceedsReservation(SettlementRejected):
    """可信用量超过预留上界，需人工核对而不是静默透支。"""


@dataclass(frozen=True, slots=True)
class AttemptRequest:
    operation_id: UUID
    attempt_id: UUID
    service_id: str
    unit_code: str
    provider_id: str
    provider_account_id: str
    pool_id: str
    model_id: str
    config_version: int
    subject_kind: str
    subject_id: str
    user_id: str
    app_id: str
    reserved_units: Decimal


@dataclass(frozen=True, slots=True)
class AttemptReservation:
    attempt_id: UUID
    status: str
    allocations: tuple[tuple[UUID, UUID, Decimal], ...]


@dataclass(frozen=True, slots=True)
class SettlementResult:
    attempt_id: UUID
    settled_units: Decimal
    status: str


def _units(value: Decimal, *, allow_zero: bool = False) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value.as_tuple().exponent < -6
        or value < 0
        or (value == 0 and not allow_zero)
    ):
        raise ValueError("attempt units must be finite native units with at most six decimals")
    return value


def _safe_ref(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise SettlementRejected("safe evidence reference is required")
    return value


def _fingerprint(scope: TenantScope, request: AttemptRequest) -> str:
    data = {
        "tenant_id": scope.tenant_id,
        "operation_id": str(request.operation_id),
        "attempt_id": str(request.attempt_id),
        "service_id": request.service_id,
        "unit_code": request.unit_code,
        "provider_id": request.provider_id,
        "provider_account_id": request.provider_account_id,
        "pool_id": request.pool_id,
        "model_id": request.model_id,
        "config_version": request.config_version,
        "subject_kind": request.subject_kind,
        "subject_id": request.subject_id,
        "user_id": request.user_id,
        "app_id": request.app_id,
        "reserved_units": str(request.reserved_units.normalize()),
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validate_request(scope: TenantScope, request: AttemptRequest) -> None:
    if not isinstance(scope, TenantScope):
        raise AttemptRejected("trusted tenant scope is required")
    if not isinstance(request.operation_id, UUID) or not isinstance(request.attempt_id, UUID):
        raise AttemptRejected("operation and attempt IDs are required")
    try:
        _units(request.reserved_units)
    except ValueError as error:
        raise AttemptRejected(str(error)) from None
    if not isinstance(request.config_version, int) or request.config_version < 1:
        raise AttemptRejected("confirmed config version is required")
    for name in ("service_id", "unit_code", "provider_id", "pool_id", "subject_id"):
        value = getattr(request, name)
        if not isinstance(value, str) or not value.strip() or len(value) > 255:
            raise AttemptRejected(f"{name} is invalid")
    if request.subject_kind not in {"user", "delegated_user", "app", "service"}:
        raise AttemptRejected("subject kind is invalid")
    if scope.user_id != request.subject_id:
        raise AttemptRejected("trusted subject scope is required")
    if request.subject_kind == "user" and (request.user_id != request.subject_id or request.app_id):
        raise AttemptRejected("user attempt attribution is invalid")
    if request.subject_kind == "delegated_user" and (
        request.user_id != request.subject_id or not request.app_id
    ):
        raise AttemptRejected("delegated user attribution is invalid")
    if request.subject_kind == "app" and (request.app_id != request.subject_id or request.user_id):
        raise AttemptRejected("app attempt attribution is invalid")
    if request.subject_kind == "service" and (request.user_id or request.app_id):
        raise AttemptRejected("service attempt attribution is invalid")


async def _pool_lock(c, service_id, provider_id, account_id, pool_id, unit_code) -> None:
    await c.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"oms-pool:{service_id}:{provider_id}:{account_id}:{pool_id}:{unit_code}",),
    )


async def _event(
    c,
    tenant_id: UUID,
    attempt_id: UUID,
    kind: str,
    reference: str,
    *,
    units: Decimal | None = None,
    provider_request_id: str = "",
) -> None:
    await c.execute(
        "INSERT INTO oms.attempt_evidence_events"
        "(tenant_id,attempt_id,id,event_kind,reference,observed_units,provider_request_id) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (tenant_id, attempt_id, uuid4(), kind, reference, units, provider_request_id),
    )


async def _audit(
    c, tenant_id: UUID, attempt_id: UUID, subject_id: str, action: str, reason: str, summary: dict
) -> None:
    await c.execute(
        "INSERT INTO oms.audit_events"
        "(id,actor_subject,action,target_tenant_id,object_kind,object_id,"
        "request_id,result,reason,safe_summary) "
        "VALUES(%s,%s,%s,%s,'usage_attempt',%s,%s,'success',%s,%s)",
        (
            uuid4(),
            subject_id,
            action,
            tenant_id,
            str(attempt_id),
            str(attempt_id),
            reason,
            Jsonb(summary),
        ),
    )


class OmsAttemptLedger:
    """内部总账事务；不构成可公开的 provider 适配或授权入口。"""

    def __init__(self, db) -> None:
        self.db = db

    @staticmethod
    async def _replay(c, tenant_id: UUID, request: AttemptRequest, fingerprint: str, existing):
        if existing["request_hash"] != fingerprint:
            raise AttemptRejected("attempt id conflicts with prior payload")
        allocations = await (
            await c.execute(
                "SELECT grant_id,lot_id,allocated_units FROM oms.attempt_allocations "
                "WHERE tenant_id=%s AND attempt_id=%s ORDER BY allocation_order",
                (tenant_id, request.attempt_id),
            )
        ).fetchall()
        return AttemptReservation(
            request.attempt_id,
            existing["status"],
            tuple((row["grant_id"], row["lot_id"], row["allocated_units"]) for row in allocations),
        )

    async def _attempt(self, c, scope: TenantScope, attempt_id: UUID):
        row = await (
            await c.execute(
                "SELECT * FROM oms.usage_attempts WHERE tenant_id=%s AND attempt_id=%s FOR UPDATE",
                (UUID(scope.tenant_id), attempt_id),
            )
        ).fetchone()
        if row is None or row["subject_id"] != scope.user_id:
            raise SettlementRejected("attempt is unavailable to this subject")
        return row

    async def _lock_attempt_pool(self, c, scope: TenantScope, attempt_id: UUID):
        """先取不可变池身份再锁池与 attempt，避免和 reserve 重放反序死锁。"""

        pool = await (
            await c.execute(
                "SELECT service_id,provider_id,provider_account_id,pool_id,unit_code,"
                "subject_id FROM oms.usage_attempts "
                "WHERE tenant_id=%s AND attempt_id=%s",
                (UUID(scope.tenant_id), attempt_id),
            )
        ).fetchone()
        if pool is None or pool["subject_id"] != scope.user_id:
            raise SettlementRejected("attempt is unavailable to this subject")
        if pool["pool_id"] is None:
            raise SettlementRejected("legacy attempt requires explicit reconciliation")
        fields = (
            pool["service_id"],
            pool["provider_id"],
            pool["provider_account_id"],
            pool["pool_id"],
            pool["unit_code"],
        )
        await _pool_lock(c, *fields)
        attempt = await self._attempt(c, scope, attempt_id)
        if fields != tuple(
            attempt[field]
            for field in (
                "service_id",
                "provider_id",
                "provider_account_id",
                "pool_id",
                "unit_code",
            )
        ):
            raise SettlementRejected("attempt pool changed during settlement")
        return attempt

    async def reserve(self, scope: TenantScope, request: AttemptRequest) -> AttemptReservation:
        _validate_request(scope, request)
        tenant_id = UUID(scope.tenant_id)
        fingerprint = _fingerprint(scope, request)
        async with self.db.transaction(scope) as c:
            # 已提交的 attempt 重放只读原结果；后来撤销授权不能抹去已发生的预留。
            prior = await (
                await c.execute(
                    "SELECT 1 FROM oms.usage_attempts WHERE tenant_id=%s AND attempt_id=%s",
                    (tenant_id, request.attempt_id),
                )
            ).fetchone()
            if prior is not None:
                try:
                    existing = await self._lock_attempt_pool(c, scope, request.attempt_id)
                except SettlementRejected as error:
                    raise AttemptRejected(str(error)) from None
                return await self._replay(c, tenant_id, request, fingerprint, existing)
            service = await (
                await c.execute(
                    "SELECT unit_code,enabled FROM oms.service_definitions "
                    "WHERE service_id=%s FOR SHARE",
                    (request.service_id,),
                )
            ).fetchone()
            if (
                service is None
                or not service["enabled"]
                or service["unit_code"] != request.unit_code
            ):
                raise AttemptRejected("service is not enabled for the requested unit")
            entitlement = await (
                await c.execute(
                    "SELECT status FROM oms.tenant_service_entitlements "
                    "WHERE tenant_id=%s AND service_id=%s "
                    "AND starts_at<=now() AND expires_at>now() FOR UPDATE",
                    (tenant_id, request.service_id),
                )
            ).fetchone()
            if entitlement is None or entitlement["status"] != "active":
                raise AttemptRejected("tenant service entitlement is unavailable")
            await _pool_lock(
                c,
                request.service_id,
                request.provider_id,
                request.provider_account_id,
                request.pool_id,
                request.unit_code,
            )
            existing = await (
                await c.execute(
                    "SELECT request_hash,status FROM oms.usage_attempts "
                    "WHERE tenant_id=%s AND attempt_id=%s FOR UPDATE",
                    (tenant_id, request.attempt_id),
                )
            ).fetchone()
            if existing is not None:
                return await self._replay(c, tenant_id, request, fingerprint, existing)

            candidates = await (
                await c.execute(
                    "SELECT g.id AS grant_id,g.acquisition_method,g.expires_at,"
                    "g.created_at,g.unit_code,gc.lot_id,gc.unspent,"
                    "sl.expires_at AS lot_expires_at "
                    "FROM oms.quota_grants g "
                    "JOIN oms.grant_commitments gc ON gc.tenant_id=g.tenant_id AND gc.grant_id=g.id "
                    "JOIN oms.supply_lots sl ON sl.id=gc.lot_id "
                    "WHERE g.tenant_id=%s AND g.service_id=%s AND g.unit_code=%s "
                    "AND g.status='active' AND g.starts_at<=now() AND g.expires_at>now() "
                    "AND sl.service_id=%s AND sl.unit_code=%s AND sl.provider_id=%s "
                    "AND sl.provider_account_id=%s AND sl.pool_id=%s AND sl.status='active' "
                    "AND sl.hard_ceiling IS NOT NULL AND sl.starts_at<=now() "
                    "AND sl.expires_at>now() "
                    "ORDER BY CASE WHEN g.acquisition_method='gift' THEN 0 ELSE 1 END,"
                    "g.expires_at,g.created_at,g.id,sl.expires_at,sl.id "
                    "FOR UPDATE OF g,gc,sl",
                    (
                        tenant_id,
                        request.service_id,
                        request.unit_code,
                        request.service_id,
                        request.unit_code,
                        request.provider_id,
                        request.provider_account_id,
                        request.pool_id,
                    ),
                )
            ).fetchall()
            allocations: list[tuple[UUID, UUID, Decimal]] = []
            remaining = request.reserved_units
            for row in candidates:
                take = min(remaining, row["unspent"])
                if take > 0:
                    allocations.append((row["grant_id"], row["lot_id"], take))
                    remaining -= take
                if remaining == 0:
                    break
            if remaining:
                raise QuotaUnavailable("effective tenant quota is insufficient")

            await c.execute(
                "INSERT INTO oms.usage_attempts"
                "(tenant_id,attempt_id,operation_id,service_id,unit_code,provider_id,"
                "provider_account_id,model_id,config_version,subject_kind,subject_id,"
                "user_id,app_id,reserved_units,pool_id,request_hash) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    tenant_id,
                    request.attempt_id,
                    request.operation_id,
                    request.service_id,
                    request.unit_code,
                    request.provider_id,
                    request.provider_account_id,
                    request.model_id,
                    request.config_version,
                    request.subject_kind,
                    request.subject_id,
                    request.user_id,
                    request.app_id,
                    request.reserved_units,
                    request.pool_id,
                    fingerprint,
                ),
            )
            for order, (grant_id, lot_id, take) in enumerate(allocations, start=1):
                updated = await (
                    await c.execute(
                        "UPDATE oms.grant_commitments "
                        "SET unspent=unspent-%s,reserved=reserved+%s "
                        "WHERE tenant_id=%s AND grant_id=%s AND lot_id=%s AND unspent>=%s "
                        "RETURNING lot_id",
                        (take, take, tenant_id, grant_id, lot_id, take),
                    )
                ).fetchone()
                if updated is None:
                    raise QuotaUnavailable("grant balance changed during reservation")
                updated = await (
                    await c.execute(
                        "UPDATE oms.supply_lots "
                        "SET committed_unspent=committed_unspent-%s,"
                        "reserved_inflight=reserved_inflight+%s "
                        "WHERE id=%s AND committed_unspent>=%s RETURNING id",
                        (take, take, lot_id, take),
                    )
                ).fetchone()
                if updated is None:
                    raise QuotaUnavailable("supply commitment changed during reservation")
                await c.execute(
                    "INSERT INTO oms.attempt_allocations"
                    "(tenant_id,attempt_id,grant_id,lot_id,allocated_units,reserved_units,allocation_order) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (tenant_id, request.attempt_id, grant_id, lot_id, take, take, order),
                )
            await _audit(
                c,
                tenant_id,
                request.attempt_id,
                request.subject_id,
                "usage.reserve",
                "upper_bound_reserved",
                {"service_id": request.service_id, "reserved_units": str(request.reserved_units)},
            )
        return AttemptReservation(request.attempt_id, "reserved", tuple(allocations))

    async def mark_dispatched(self, scope: TenantScope, attempt_id: UUID) -> None:
        async with self.db.transaction(scope) as c:
            attempt = await self._attempt(c, scope, attempt_id)
            if attempt["status"] == "dispatched":
                return
            if attempt["status"] != "reserved":
                raise SettlementRejected("attempt cannot be dispatched from current state")
            await c.execute(
                "UPDATE oms.usage_attempts SET status='dispatched',updated_at=now() "
                "WHERE tenant_id=%s AND attempt_id=%s",
                (UUID(scope.tenant_id), attempt_id),
            )
            await _event(c, UUID(scope.tenant_id), attempt_id, "dispatch_intent", str(attempt_id))

    async def mark_remote_unknown(
        self, scope: TenantScope, attempt_id: UUID, *, evidence_ref: str
    ) -> None:
        _safe_ref(evidence_ref)
        async with self.db.transaction(scope) as c:
            attempt = await self._attempt(c, scope, attempt_id)
            if attempt["status"] == "remote_unknown":
                return
            if attempt["status"] != "dispatched":
                raise SettlementRejected("only dispatched attempts can become remote unknown")
            await c.execute(
                "UPDATE oms.usage_attempts SET status='remote_unknown',updated_at=now() "
                "WHERE tenant_id=%s AND attempt_id=%s",
                (UUID(scope.tenant_id), attempt_id),
            )
            await _event(c, UUID(scope.tenant_id), attempt_id, "remote_unknown", evidence_ref)

    async def release_before_dispatch(
        self, scope: TenantScope, attempt_id: UUID, *, evidence_ref: str
    ) -> None:
        _safe_ref(evidence_ref)
        tenant_id = UUID(scope.tenant_id)
        async with self.db.transaction(scope) as c:
            attempt = await self._lock_attempt_pool(c, scope, attempt_id)
            if attempt["status"] != "reserved":
                raise SettlementRejected("dispatched or completed attempt cannot be released")
            rows = await (
                await c.execute(
                    "SELECT aa.grant_id,aa.lot_id,aa.allocated_units,aa.reserved_units,"
                    "aa.allocation_order,"
                    "g.status AS grant_status,g.starts_at AS grant_start,"
                    "g.expires_at AS grant_end,sl.status AS lot_status,"
                    "sl.starts_at AS lot_start,sl.expires_at AS lot_end "
                    "FROM oms.attempt_allocations aa "
                    "JOIN oms.quota_grants g ON g.id=aa.grant_id "
                    "JOIN oms.supply_lots sl ON sl.id=aa.lot_id "
                    "WHERE aa.tenant_id=%s AND aa.attempt_id=%s "
                    "ORDER BY aa.allocation_order FOR UPDATE OF aa,g,sl",
                    (tenant_id, attempt_id),
                )
            ).fetchall()
            if (
                not rows
                or any(
                    row["allocation_order"] is None
                    or row["reserved_units"] != row["allocated_units"]
                    for row in rows
                )
                or sum(row["allocated_units"] for row in rows) != attempt["reserved_units"]
            ):
                raise SettlementRejected("attempt allocations need reconciliation")
            for row in rows:
                reusable = await self._reusable(c, row)
                await self._finish_allocation(
                    c, tenant_id, attempt_id, row, used=Decimal(0), reusable=reusable
                )
            await c.execute(
                "UPDATE oms.usage_attempts SET status='released',updated_at=now() "
                "WHERE tenant_id=%s AND attempt_id=%s",
                (tenant_id, attempt_id),
            )
            await _event(c, tenant_id, attempt_id, "confirmed_not_sent", evidence_ref)
            await _audit(
                c,
                tenant_id,
                attempt_id,
                attempt["subject_id"],
                "usage.release",
                "confirmed_not_sent",
                {},
            )

    async def settle(
        self,
        scope: TenantScope,
        attempt_id: UUID,
        *,
        units: Decimal,
        source: str,
        evidence_ref: str,
        provider_request_id: str = "",
    ) -> SettlementResult:
        try:
            _units(units, allow_zero=True)
        except ValueError as error:
            raise SettlementRejected(str(error)) from None
        if source not in {"provider_usage", "verified_reconciliation"}:
            raise SettlementRejected("only trusted provider or reconciled usage can settle")
        _safe_ref(evidence_ref)
        if not isinstance(provider_request_id, str) or len(provider_request_id) > 255:
            raise SettlementRejected("provider request id is invalid")
        tenant_id = UUID(scope.tenant_id)
        evidence = {
            "source": source,
            "reference": evidence_ref,
            "units": str(units.normalize()),
            "provider_request_id": provider_request_id,
        }
        overage = False
        async with self.db.transaction(scope) as c:
            attempt = await self._lock_attempt_pool(c, scope, attempt_id)
            if attempt["status"] == "settled":
                if attempt["evidence"] != evidence:
                    raise SettlementRejected(
                        "settled attempt evidence conflicts with prior receipt"
                    )
                return SettlementResult(attempt_id, attempt["settled_units"], "settled")
            if attempt["status"] not in {"dispatched", "remote_unknown", "reconcile_required"}:
                raise SettlementRejected("attempt was not dispatched or is already released")
            if attempt["status"] == "reconcile_required" and source != "verified_reconciliation":
                raise SettlementRejected("overage requires verified reconciliation")
            if units > attempt["reserved_units"]:
                overage = True
                if attempt["status"] != "reconcile_required" or attempt["evidence"] != evidence:
                    await c.execute(
                        "UPDATE oms.usage_attempts SET status='reconcile_required',"
                        "provider_request_id=%s,evidence=%s,updated_at=now() "
                        "WHERE tenant_id=%s AND attempt_id=%s",
                        (provider_request_id, Jsonb(evidence), tenant_id, attempt_id),
                    )
                    await _event(
                        c,
                        tenant_id,
                        attempt_id,
                        "overage",
                        evidence_ref,
                        units=units,
                        provider_request_id=provider_request_id,
                    )
            else:
                rows = await (
                    await c.execute(
                        "SELECT aa.grant_id,aa.lot_id,aa.allocated_units,aa.reserved_units,"
                        "aa.allocation_order,"
                        "g.status AS grant_status,g.starts_at AS grant_start,"
                        "g.expires_at AS grant_end,sl.status AS lot_status,"
                        "sl.starts_at AS lot_start,sl.expires_at AS lot_end "
                        "FROM oms.attempt_allocations aa "
                        "JOIN oms.quota_grants g ON g.id=aa.grant_id "
                        "JOIN oms.supply_lots sl ON sl.id=aa.lot_id "
                        "WHERE aa.tenant_id=%s AND aa.attempt_id=%s "
                        "ORDER BY aa.allocation_order FOR UPDATE OF aa,g,sl",
                        (tenant_id, attempt_id),
                    )
                ).fetchall()
                if (
                    not rows
                    or any(
                        row["allocation_order"] is None
                        or row["reserved_units"] != row["allocated_units"]
                        for row in rows
                    )
                    or sum(row["allocated_units"] for row in rows) != attempt["reserved_units"]
                ):
                    raise SettlementRejected("attempt allocations need reconciliation")
                remaining = units
                for row in rows:
                    used = min(remaining, row["allocated_units"])
                    remaining -= used
                    reusable = await self._reusable(c, row)
                    await self._finish_allocation(
                        c, tenant_id, attempt_id, row, used=used, reusable=reusable
                    )
                if remaining:
                    raise SettlementRejected("attempt allocation total is inconsistent")
                await c.execute(
                    "UPDATE oms.usage_attempts SET status='settled',settled_units=%s,"
                    "provider_request_id=%s,evidence=%s,updated_at=now() "
                    "WHERE tenant_id=%s AND attempt_id=%s",
                    (units, provider_request_id, Jsonb(evidence), tenant_id, attempt_id),
                )
                await _event(
                    c,
                    tenant_id,
                    attempt_id,
                    source,
                    evidence_ref,
                    units=units,
                    provider_request_id=provider_request_id,
                )
                await _audit(
                    c,
                    tenant_id,
                    attempt_id,
                    attempt["subject_id"],
                    "usage.settle",
                    source,
                    {"service_id": attempt["service_id"], "settled_units": str(units)},
                )
        if overage:
            raise UsageExceedsReservation("trusted usage exceeds reserved upper bound")
        return SettlementResult(attempt_id, units, "settled")

    @staticmethod
    async def _reusable(c, row) -> bool:
        current = await (await c.execute("SELECT now() AS current_time")).fetchone()
        now = current["current_time"]
        return (
            row["grant_status"] == "active"
            and row["grant_start"] <= now < row["grant_end"]
            and row["lot_status"] == "active"
            and row["lot_start"] <= now < row["lot_end"]
        )

    @staticmethod
    async def _finish_allocation(
        c,
        tenant_id: UUID,
        attempt_id: UUID,
        row,
        *,
        used: Decimal,
        reusable: bool,
    ) -> None:
        allocated = row["allocated_units"]
        unused = allocated - used
        returned = unused if reusable else Decimal(0)
        released = unused - returned
        commitment = await (
            await c.execute(
                "UPDATE oms.grant_commitments "
                "SET reserved=reserved-%s,settled=settled+%s,"
                "unspent=unspent+%s,released=released+%s "
                "WHERE tenant_id=%s AND grant_id=%s AND lot_id=%s AND reserved>=%s "
                "RETURNING grant_id",
                (
                    allocated,
                    used,
                    returned,
                    released,
                    tenant_id,
                    row["grant_id"],
                    row["lot_id"],
                    allocated,
                ),
            )
        ).fetchone()
        if commitment is None:
            raise SettlementRejected("grant commitment needs reconciliation")
        lot = await (
            await c.execute(
                "UPDATE oms.supply_lots "
                "SET reserved_inflight=reserved_inflight-%s,settled_lifetime=settled_lifetime+%s,"
                "committed_unspent=committed_unspent+%s "
                "WHERE id=%s AND reserved_inflight>=%s RETURNING id",
                (allocated, used, returned, row["lot_id"], allocated),
            )
        ).fetchone()
        if lot is None:
            raise SettlementRejected("supply reservation needs reconciliation")
        allocation = await (
            await c.execute(
                "UPDATE oms.attempt_allocations "
                "SET reserved_units=0,settled_units=%s,released_units=%s "
                "WHERE tenant_id=%s AND attempt_id=%s AND grant_id=%s AND lot_id=%s "
                "AND reserved_units=%s RETURNING attempt_id",
                (
                    used,
                    unused,
                    tenant_id,
                    attempt_id,
                    row["grant_id"],
                    row["lot_id"],
                    allocated,
                ),
            )
        ).fetchone()
        if allocation is None:
            raise SettlementRejected("attempt allocation needs reconciliation")
