"""TMS 服务访问资格：不发放额度、不预留、不结算用量。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.scope import TenantScope


class ServiceAccessRejected(ValueError):
    """服务访问资格命令不满足权限、版本或业务契约。"""


@dataclass(frozen=True, slots=True)
class ServiceAccessGrantRequest:
    grant_id: UUID
    service_id: str
    subject_kind: str
    subject_id: str
    starts_at: datetime
    expires_at: datetime
    expected_entitlement_version: int
    reason: str


@dataclass(frozen=True, slots=True)
class ServiceAccessRevokeRequest:
    grant_id: UUID
    expected_version: int
    reason: str


@dataclass(frozen=True, slots=True)
class ServiceAccessResult:
    grant_id: UUID
    service_id: str
    subject_kind: str
    subject_id: str
    status: str
    sync_status: str
    version: int


def _validate_window(starts_at: datetime, expires_at: datetime) -> None:
    if not isinstance(starts_at, datetime) or not isinstance(expires_at, datetime):
        raise ServiceAccessRejected("service access validity is invalid")
    if starts_at.tzinfo is None or expires_at.tzinfo is None or expires_at <= starts_at:
        raise ServiceAccessRejected("service access validity is invalid")
    if expires_at <= datetime.now(timezone.utc):
        raise ServiceAccessRejected("service access validity is invalid")


def _validate_text(name: str, value: str, *, max_length: int = 255) -> str:
    if not isinstance(value, str):
        raise ServiceAccessRejected(f"{name} is invalid")
    text = value.strip()
    if not text or len(text) > max_length:
        raise ServiceAccessRejected(f"{name} is invalid")
    return text


def _validate_grant_request(scope: TenantScope, request: ServiceAccessGrantRequest) -> None:
    if not isinstance(scope, TenantScope):
        raise ServiceAccessRejected("trusted school scope is required")
    if not isinstance(request.grant_id, UUID):
        raise ServiceAccessRejected("service access grant id is invalid")
    _validate_text("service_id", request.service_id, max_length=128)
    if request.subject_kind not in {"member", "application", "service_principal"}:
        raise ServiceAccessRejected("service access subject kind is invalid")
    _validate_text("subject_id", request.subject_id)
    _validate_text("reason", request.reason, max_length=1024)
    _validate_window(request.starts_at, request.expires_at)
    if (
        type(request.expected_entitlement_version) is not int
        or request.expected_entitlement_version < 1
    ):
        raise ServiceAccessRejected("entitlement version is invalid")


def _validate_revoke_request(scope: TenantScope, request: ServiceAccessRevokeRequest) -> None:
    if not isinstance(scope, TenantScope):
        raise ServiceAccessRejected("trusted school scope is required")
    if not isinstance(request.grant_id, UUID):
        raise ServiceAccessRejected("service access grant id is invalid")
    if type(request.expected_version) is not int or request.expected_version < 1:
        raise ServiceAccessRejected("service access grant version is invalid")
    _validate_text("reason", request.reason, max_length=1024)


def _tenant_id(scope: TenantScope) -> UUID:
    try:
        return UUID(str(scope.tenant_id))
    except (TypeError, ValueError):
        raise ServiceAccessRejected("trusted school scope is required") from None


async def _require_tms_access(connection, identity, school_id: UUID) -> None:
    from ..management.authorization import (
        ManagementAuthorizationDenied,
        require_management_permission,
    )

    try:
        await require_management_permission(
            connection,
            identity,
            "tenant.access.manage",
            target_school_id=school_id,
            write=True,
            _lock_school_id=school_id,
        )
    except ManagementAuthorizationDenied:
        raise ServiceAccessRejected("Permission denied") from None


async def _audit(
    connection,
    *,
    school_id: UUID,
    actor_subject: str,
    action: str,
    grant_id: UUID,
    result: str,
    reason: str,
    summary: dict,
) -> None:
    await connection.execute(
        "INSERT INTO oms.audit_events"
        "(id,actor_subject,action,target_tenant_id,object_kind,object_id,"
        "request_id,result,reason,safe_summary) "
        "VALUES(%s,%s,%s,%s,'tenant_service_access_grant',%s,%s,%s,%s,%s)",
        (
            uuid4(),
            actor_subject,
            action,
            school_id,
            str(grant_id),
            str(grant_id),
            result,
            reason,
            Jsonb(summary),
        ),
    )


class ServiceAccessLedger:
    """TMS 当前学校服务访问资格账本。

    它只记录成员/应用/服务主体是否具备某服务的调用资格；真实执行仍必须
    经过 OMS 服务授权、配置 readiness、供给和额度准入。这里绝不写
    ``oms.quota_grants``、``oms.grant_commitments``、``oms.usage_attempts`` 或
    ``oms.attempt_allocations``。
    """

    def __init__(self, db) -> None:
        self.db = db

    async def grant(self, scope: TenantScope, identity, request: ServiceAccessGrantRequest):
        _validate_grant_request(scope, request)
        school_id = _tenant_id(scope)
        async with self.db.transaction(scope) as connection:
            await _require_tms_access(connection, identity, school_id)
            entitlement = await (
                await connection.execute(
                    "SELECT status,version,starts_at,expires_at "
                    "FROM oms.tenant_service_entitlements "
                    "WHERE tenant_id=%s AND service_id=%s FOR SHARE",
                    (school_id, request.service_id),
                )
            ).fetchone()
            if (
                entitlement is None
                or entitlement["status"] != "active"
                or entitlement["version"] != request.expected_entitlement_version
                or entitlement["starts_at"] > request.starts_at
                or entitlement["expires_at"] < request.expires_at
            ):
                raise ServiceAccessRejected("service entitlement is unavailable")
            duplicate = await (
                await connection.execute(
                    "SELECT id FROM oms.tenant_service_access_grants "
                    "WHERE tenant_id=%s AND service_id=%s AND subject_kind=%s "
                    "AND subject_id=%s AND status='active' AND revoked_at IS NULL "
                    "AND expires_at>clock_timestamp() FOR UPDATE",
                    (
                        school_id,
                        request.service_id,
                        request.subject_kind,
                        request.subject_id,
                    ),
                )
            ).fetchone()
            if duplicate is not None:
                raise ServiceAccessRejected("active service access grant exists")
            row = await (
                await connection.execute(
                    "INSERT INTO oms.tenant_service_access_grants"
                    "(tenant_id,id,service_id,subject_kind,subject_id,entitlement_version,"
                    "starts_at,expires_at,status,sync_status,version,command_id,created_by,reason) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'active','local_ready',1,%s,%s,%s) "
                    "RETURNING id,service_id,subject_kind,subject_id,status,sync_status,version",
                    (
                        school_id,
                        request.grant_id,
                        request.service_id,
                        request.subject_kind,
                        request.subject_id,
                        request.expected_entitlement_version,
                        request.starts_at,
                        request.expires_at,
                        uuid4(),
                        identity.subject,
                        request.reason,
                    ),
                )
            ).fetchone()
            if row is None:
                raise ServiceAccessRejected("service access grant was not recorded")
            result = ServiceAccessResult(
                grant_id=row["id"],
                service_id=row["service_id"],
                subject_kind=row["subject_kind"],
                subject_id=row["subject_id"],
                status=row["status"],
                sync_status=row["sync_status"],
                version=row["version"],
            )
            await _audit(
                connection,
                school_id=school_id,
                actor_subject=identity.subject,
                action="tenant_service_access.grant",
                grant_id=result.grant_id,
                result="success",
                reason=request.reason,
                summary={
                    "service_id": result.service_id,
                    "subject_kind": result.subject_kind,
                    "status": result.status,
                    "version": result.version,
                },
            )
            return result

    async def revoke(self, scope: TenantScope, identity, request: ServiceAccessRevokeRequest):
        _validate_revoke_request(scope, request)
        school_id = _tenant_id(scope)
        async with self.db.transaction(scope) as connection:
            await _require_tms_access(connection, identity, school_id)
            row = await (
                await connection.execute(
                    "SELECT id,service_id,subject_kind,subject_id,status,sync_status,version "
                    "FROM oms.tenant_service_access_grants "
                    "WHERE tenant_id=%s AND id=%s FOR UPDATE",
                    (school_id, request.grant_id),
                )
            ).fetchone()
            if (
                row is None
                or row["status"] != "active"
                or row["version"] != request.expected_version
            ):
                raise ServiceAccessRejected("service access grant version is stale")
            updated = await (
                await connection.execute(
                    "UPDATE oms.tenant_service_access_grants "
                    "SET status='revoked',version=version+1,revoked_at=clock_timestamp(),"
                    "updated_at=clock_timestamp() "
                    "WHERE tenant_id=%s AND id=%s AND version=%s "
                    "RETURNING id,service_id,subject_kind,subject_id,status,sync_status,version",
                    (school_id, request.grant_id, request.expected_version),
                )
            ).fetchone()
            if updated is None:
                raise ServiceAccessRejected("service access grant version changed")
            result = ServiceAccessResult(
                grant_id=updated["id"],
                service_id=updated["service_id"],
                subject_kind=updated["subject_kind"],
                subject_id=updated["subject_id"],
                status=updated["status"],
                sync_status=updated["sync_status"],
                version=updated["version"],
            )
            await _audit(
                connection,
                school_id=school_id,
                actor_subject=identity.subject,
                action="tenant_service_access.revoke",
                grant_id=result.grant_id,
                result="success",
                reason=request.reason,
                summary={
                    "service_id": result.service_id,
                    "subject_kind": result.subject_kind,
                    "status": result.status,
                    "version": result.version,
                },
            )
            return result


__all__ = [
    "ServiceAccessGrantRequest",
    "ServiceAccessLedger",
    "ServiceAccessRejected",
    "ServiceAccessResult",
    "ServiceAccessRevokeRequest",
]
