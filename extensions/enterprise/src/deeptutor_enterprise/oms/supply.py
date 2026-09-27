"""OMS 内部供给批次登记与有效可授予量；平台权限必须由未来入口先行校验。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.scope import GlobalScope


class SupplyRejected(ValueError):
    """供给来源、单位或批次状态不满足准入规则。"""


@dataclass(frozen=True, slots=True)
class SupplyRequest:
    lot_id: UUID
    service_id: str
    unit_code: str
    provider_id: str
    provider_account_id: str
    pool_id: str
    basis: str
    hard_ceiling: Decimal | None
    starts_at: datetime
    expires_at: datetime
    evidence_ref: str
    verified_native: bool
    actor_subject: str
    request_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class SupplyRevokeRequest:
    lot_id: UUID
    expected_version: int
    actor_subject: str
    request_id: str
    reason: str


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 255 or "\x00" in value:
        raise SupplyRejected(f"{name} is invalid")


def _validate(scope: GlobalScope, request: SupplyRequest) -> None:
    if not isinstance(scope, GlobalScope) or scope.user_id != request.actor_subject:
        raise SupplyRejected("trusted global actor scope is required")
    if not isinstance(request.lot_id, UUID):
        raise SupplyRejected("lot id is invalid")
    for name in (
        "service_id",
        "unit_code",
        "provider_id",
        "pool_id",
        "evidence_ref",
        "actor_subject",
        "request_id",
        "reason",
    ):
        _nonempty(getattr(request, name), name)
    if (
        not isinstance(request.provider_account_id, str)
        or len(request.provider_account_id) > 255
        or "\x00" in request.provider_account_id
    ):
        raise SupplyRejected("provider_account_id is invalid")
    if request.basis not in {"native_units", "money", "credits", "paygo"}:
        raise SupplyRejected("supply basis is invalid")
    if type(request.verified_native) is not bool:
        raise SupplyRejected("native verification flag is invalid")
    if (
        not isinstance(request.starts_at, datetime)
        or not isinstance(request.expires_at, datetime)
        or request.starts_at.tzinfo is None
        or request.expires_at.tzinfo is None
        or request.expires_at <= request.starts_at
    ):
        raise SupplyRejected("supply validity is invalid")
    if request.verified_native and (
        request.basis != "native_units" or request.hard_ceiling is None
    ):
        raise SupplyRejected("verified native ceiling is required")
    if request.basis != "native_units" and request.hard_ceiling is not None:
        raise SupplyRejected("money, credits and paygo have no verified native ceiling")
    if request.hard_ceiling is not None and (
        not isinstance(request.hard_ceiling, Decimal)
        or not request.hard_ceiling.is_finite()
        or request.hard_ceiling <= 0
        or request.hard_ceiling.as_tuple().exponent < -6
        or request.hard_ceiling >= Decimal("1000000000000000000000000")
    ):
        raise SupplyRejected("native ceiling is invalid")


def _matches_existing(prior, request: SupplyRequest) -> bool:
    return prior is not None and (
        prior["service_id"],
        prior["provider_id"],
        prior["provider_account_id"],
        prior["pool_id"],
        prior["unit_code"],
        prior["evidence_ref"],
        prior["hard_ceiling"],
        prior["starts_at"],
        prior["expires_at"],
        prior["supply_basis"],
        prior["verified_at"] is not None,
        prior["created_by"],
    ) == (
        request.service_id,
        request.provider_id,
        request.provider_account_id,
        request.pool_id,
        request.unit_code,
        request.evidence_ref,
        request.hard_ceiling,
        request.starts_at,
        request.expires_at,
        request.basis,
        request.verified_native,
        request.actor_subject,
    )


_LOT_IDENTITY_SQL = (
    "SELECT service_id,provider_id,provider_account_id,pool_id,unit_code,"
    "evidence_ref,hard_ceiling,starts_at,expires_at,supply_basis,"
    "verified_at,created_by FROM oms.supply_lots WHERE id=%s FOR UPDATE"
)


class OmsSupplyLedger:
    """只操作全局供给账；GlobalScope 是隔离范围，不是平台权限证明。"""

    def __init__(self, db) -> None:
        self.db = db

    async def revoke(self, scope: GlobalScope, request: SupplyRevokeRequest) -> int:
        if not isinstance(scope, GlobalScope) or scope.user_id != request.actor_subject:
            raise SupplyRejected("trusted global actor scope is required")
        if not isinstance(request.lot_id, UUID) or type(request.expected_version) is not int:
            raise SupplyRejected("supply lot id or version is invalid")
        if request.expected_version < 1:
            raise SupplyRejected("supply version is invalid")
        for name in ("actor_subject", "request_id", "reason"):
            _nonempty(getattr(request, name), name)
        async with self.db.transaction(scope) as c:
            pool = await (
                await c.execute(
                    "SELECT service_id,provider_id,provider_account_id,pool_id,unit_code "
                    "FROM oms.supply_lots WHERE id=%s",
                    (request.lot_id,),
                )
            ).fetchone()
            if pool is None:
                raise SupplyRejected("supply lot is unavailable")
            await c.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (
                    "oms-pool:"
                    f"{pool['service_id']}:{pool['provider_id']}:"
                    f"{pool['provider_account_id']}:{pool['pool_id']}:{pool['unit_code']}",
                ),
            )
            updated = await (
                await c.execute(
                    "UPDATE oms.supply_lots SET status='revoked',version=version+1 "
                    "WHERE id=%s AND status='active' AND version=%s RETURNING version",
                    (request.lot_id, request.expected_version),
                )
            ).fetchone()
            if updated is None:
                raise SupplyRejected("supply version is stale or lot is revoked")
            await c.execute(
                "INSERT INTO oms.audit_events"
                "(id,actor_subject,action,object_kind,object_id,request_id,result,reason,safe_summary) "
                "VALUES(%s,%s,'supply.revoke','supply_lot',%s,%s,'success',%s,%s)",
                (
                    uuid4(),
                    request.actor_subject,
                    str(request.lot_id),
                    request.request_id,
                    request.reason,
                    Jsonb({"service_id": pool["service_id"], "version": updated["version"]}),
                ),
            )
            return updated["version"]

    async def register(self, scope: GlobalScope, request: SupplyRequest) -> UUID:
        _validate(scope, request)
        async with self.db.transaction(scope) as c:
            prior = await (await c.execute(_LOT_IDENTITY_SQL, (request.lot_id,))).fetchone()
            if prior is not None:
                if not _matches_existing(prior, request):
                    raise SupplyRejected("supply lot id conflicts with prior payload")
                return request.lot_id
            service = await (
                await c.execute(
                    "SELECT unit_code,enabled FROM oms.service_definitions "
                    "WHERE service_id=%s FOR SHARE",
                    (request.service_id,),
                )
            ).fetchone()
            if not service or not service["enabled"] or service["unit_code"] != request.unit_code:
                raise SupplyRejected("service is not enabled for the requested native unit")
            row = await (
                await c.execute(
                    "INSERT INTO oms.supply_lots"
                    "(id,service_id,provider_id,provider_account_id,pool_id,unit_code,"
                    "evidence_ref,hard_ceiling,starts_at,expires_at,supply_basis,verified_at,created_by) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                    "CASE WHEN %s THEN now() ELSE NULL END,%s) "
                    "ON CONFLICT (id) DO NOTHING RETURNING id",
                    (
                        request.lot_id,
                        request.service_id,
                        request.provider_id,
                        request.provider_account_id,
                        request.pool_id,
                        request.unit_code,
                        request.evidence_ref,
                        request.hard_ceiling,
                        request.starts_at,
                        request.expires_at,
                        request.basis,
                        request.verified_native,
                        request.actor_subject,
                    ),
                )
            ).fetchone()
            if row is None:
                prior = await (await c.execute(_LOT_IDENTITY_SQL, (request.lot_id,))).fetchone()
                if not _matches_existing(prior, request):
                    raise SupplyRejected("supply lot id conflicts with prior payload")
                return request.lot_id
            await c.execute(
                "INSERT INTO oms.audit_events"
                "(id,actor_subject,action,object_kind,object_id,request_id,result,reason,safe_summary) "
                "VALUES(%s,%s,'supply.register','supply_lot',%s,%s,'success',%s,%s)",
                (
                    uuid4(),
                    request.actor_subject,
                    str(request.lot_id),
                    request.request_id,
                    request.reason,
                    Jsonb(
                        {
                            "service_id": request.service_id,
                            "unit_code": request.unit_code,
                            "supply_basis": request.basis,
                            "verified_native": request.verified_native,
                        }
                    ),
                ),
            )
        return request.lot_id

    async def available(
        self,
        scope: GlobalScope,
        service_id: str,
        provider_id: str,
        provider_account_id: str,
        pool_id: str,
        unit_code: str,
    ) -> Decimal:
        if not isinstance(scope, GlobalScope):
            raise SupplyRejected("trusted global actor scope is required")
        for name, value in (
            ("service_id", service_id),
            ("provider_id", provider_id),
            ("pool_id", pool_id),
            ("unit_code", unit_code),
        ):
            _nonempty(value, name)
        if not isinstance(provider_account_id, str) or len(provider_account_id) > 255:
            raise SupplyRejected("provider_account_id is invalid")
        async with self.db.transaction(scope) as c:
            row = await (
                await c.execute(
                    "SELECT COALESCE(SUM(hard_ceiling-settled_lifetime-committed_unspent-"
                    "reserved_inflight),0) AS available "
                    "FROM oms.supply_lots WHERE service_id=%s AND provider_id=%s "
                    "AND provider_account_id=%s AND pool_id=%s AND unit_code=%s "
                    "AND status='active' AND supply_basis='native_units' "
                    "AND verified_at IS NOT NULL AND hard_ceiling IS NOT NULL "
                    "AND starts_at<=now() AND expires_at>now()",
                    (service_id, provider_id, provider_account_id, pool_id, unit_code),
                )
            ).fetchone()
            return row["available"]
