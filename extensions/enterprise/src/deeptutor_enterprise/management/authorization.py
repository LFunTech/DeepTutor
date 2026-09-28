"""DeepTutor Enterprise 应用层管理授权；PG 仅保存事实并保障事务一致性。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from psycopg.pq import TransactionStatus

from deeptutor.persistence.postgres.tenant_state import validate_tenant_business_values
from deeptutor_enterprise.oms.value_validation import (
    OmsValueError,
    validate_school_binding_row,
)

from .value_validation import (
    ManagementValueError,
    validate_management_action_row,
    validate_management_assignment_row,
    validate_management_delegation_row,
    validate_management_principal_row,
    validate_management_role_version_row,
)


class ManagementAuthorizationDenied(PermissionError):
    """身份、应用域、学校、动作或版本不满足当前授权。"""


@dataclass(frozen=True, slots=True)
class ManagementIdentity:
    """已认证的外部身份与本产品会话版本，不接受请求体构造。

    ``policy_version`` 是 DeepTutor Enterprise 本地权限版本，不来自
    EduPlus2 token/role；``external_active`` 只表达身份有效性，不是动作授权。
    """

    application: Literal["oms", "tms"]
    issuer: str
    subject: str
    school_id: UUID | None
    policy_version: int
    school_binding_version: int | None
    external_active: bool
    external_checked_at: datetime
    external_verified_until: datetime
    webhook_app_id: int | None = None


@dataclass(frozen=True, slots=True)
class ManagementDecision:
    application: Literal["oms", "tms"]
    principal_id: UUID
    action: str
    school_id: UUID | None
    policy_version: int
    assignment_id: UUID
    assignment_version: int
    school_binding_version: int | None


@dataclass(frozen=True, slots=True)
class ManagementDelegationDecision:
    governance: ManagementDecision
    delegated_action: str
    school_id: UUID | None
    delegation_id: UUID
    delegation_version: int
    school_binding_version: int | None


def _column(row, key: str, index: int):
    """同时兼容企业连接的 dict_row 与独立权限测试的 tuple row。"""

    return row[key] if isinstance(row, dict) else row[index]


def _optional_column(row, key: str, index: int, default):
    """兼容旧单元测试 fake row；真实 SQL 已选择该列。"""

    if isinstance(row, dict):
        return row.get(key, default)
    return row[index] if len(row) > index else default


def _identity_is_current(identity: ManagementIdentity, *, write: bool) -> bool:
    if identity.application not in {"oms", "tms"}:
        return False
    if not identity.issuer or not identity.subject or identity.policy_version < 1:
        return False
    if (
        identity.external_verified_until.tzinfo is None
        or identity.external_checked_at.tzinfo is None
    ):
        return False
    now = datetime.now(timezone.utc)
    max_age = timedelta(seconds=5 if write else 30)
    if (
        not identity.external_active
        or identity.external_checked_at > now + timedelta(seconds=5)
        or identity.external_checked_at < now - max_age
        or identity.external_verified_until <= now
    ):
        return False
    if identity.application == "oms":
        return identity.school_id is None and identity.school_binding_version is None
    return (
        isinstance(identity.school_id, UUID)
        and type(identity.school_binding_version) is int
        and identity.school_binding_version > 0
    )


async def require_management_permission(
    connection,
    identity: ManagementIdentity,
    action: str,
    *,
    target_school_id: UUID | None = None,
    write: bool = False,
    _lock_school_id: UUID | None = None,
) -> ManagementDecision:
    """在调用方现有事务中决策；写事务须持有锁直至业务写入提交。

    此函数是应用层 PEP 决策，不靠 PG role、GRANT 或 RLS 行可见性放行。
    它不负责外部身份验签；学校侧引导资格由本产品独立管理。
    它也不会从 JWT role/`eit`/header 提权。
    """

    if not isinstance(identity, ManagementIdentity) or not _identity_is_current(
        identity, write=write
    ):
        raise ManagementAuthorizationDenied("external management identity is unavailable")
    if (
        write
        and connection.autocommit
        and connection.info.transaction_status != TransactionStatus.INTRANS
    ):
        raise ManagementAuthorizationDenied("management write requires a transaction")
    if not isinstance(action, str) or not action or len(action) > 128:
        raise ManagementAuthorizationDenied("management action is invalid")
    prefix = "ops." if identity.application == "oms" else "tenant."
    if not action.startswith(prefix):
        raise ManagementAuthorizationDenied("management application and action differ")
    if target_school_id is not None and not isinstance(target_school_id, UUID):
        raise ManagementAuthorizationDenied("target school is invalid")
    if _lock_school_id is not None and not isinstance(_lock_school_id, UUID):
        raise ManagementAuthorizationDenied("locked school is invalid")
    if (
        _lock_school_id is not None
        and target_school_id is not None
        and _lock_school_id != target_school_id
    ):
        raise ManagementAuthorizationDenied("locked school differs from target")
    if identity.application == "tms" and target_school_id != identity.school_id:
        raise ManagementAuthorizationDenied("target school differs from trusted session")
    if identity.application == "tms":
        tenant_setting = await (
            await connection.execute("SELECT current_setting('app.tenant_id',true)")
        ).fetchone()
        if not tenant_setting or _column(tenant_setting, "current_setting", 0) != str(
            identity.school_id
        ):
            raise ManagementAuthorizationDenied("transaction school scope is not trusted")

    await connection.execute(
        "SELECT set_config('app.management_app',%s,true)", (identity.application,)
    )
    scope_kind = "platform" if target_school_id is None else "school"
    lock = " FOR UPDATE" if write else ""
    principal = await (
        await connection.execute(
            "SELECT id,school_id,status,policy_version,application "
            "FROM management.principals "
            "WHERE application=%s AND issuer=%s AND subject=%s "
            "AND school_id IS NOT DISTINCT FROM %s" + lock,
            (identity.application, identity.issuer, identity.subject, identity.school_id),
        )
    ).fetchone()
    if principal:
        try:
            validate_management_principal_row(
                {
                    "application": _optional_column(
                        principal, "application", 4, identity.application
                    ),
                    "school_id": _column(principal, "school_id", 1),
                    "status": _column(principal, "status", 2),
                    "policy_version": _column(principal, "policy_version", 3),
                }
            )
        except ManagementValueError:
            raise ManagementAuthorizationDenied("management principal fact is invalid") from None
    if (
        not principal
        or _column(principal, "status", 2) != "active"
        or _column(principal, "policy_version", 3) != identity.policy_version
    ):
        raise ManagementAuthorizationDenied("management principal or policy version is invalid")

    binding_version = None
    binding_school_id = _lock_school_id or target_school_id
    if binding_school_id is not None:
        lifecycle_governance = (
            identity.application == "oms" and action == "ops.reconciliation.manage"
        )
        binding_lock = " FOR SHARE OF b,t" if write else ""
        binding = await (
            await connection.execute(
                "SELECT b.version,t.bootstrap_completed,t.local_enabled,"
                "t.provisioning_status,t.recovery_state,b.eduplus_tenant_id,t.external_tid,"
                "t.external_eligibility,b.status,b.verified_at,b.verified_by,b.source_ref "
                "FROM oms.school_bindings b "
                "JOIN enterprise.tenants t ON t.id=b.tenant_id "
                "WHERE b.tenant_id=%s "
                + (
                    ""
                    if lifecycle_governance
                    else "AND (t.external_tid IS NOT NULL OR t.external_eligibility='allowed') "
                )
                + binding_lock,
                (binding_school_id,),
            )
        ).fetchone()
        if not binding:
            raise ManagementAuthorizationDenied("target school binding is not verified")
        try:
            validate_school_binding_row(
                {
                    "version": _column(binding, "version", 0),
                    "status": _optional_column(binding, "status", 8, "verified"),
                    "verified_at": _optional_column(
                        binding, "verified_at", 9, datetime.now(timezone.utc)
                    ),
                    "verified_by": _optional_column(binding, "verified_by", 10, "test"),
                    "source_ref": _optional_column(binding, "source_ref", 11, "test"),
                }
            )
        except OmsValueError:
            raise ManagementAuthorizationDenied("target school binding fact is invalid") from None
        if _optional_column(binding, "status", 8, "verified") != "verified":
            raise ManagementAuthorizationDenied("target school binding is not verified")
        try:
            validate_tenant_business_values(
                {
                    "external_eligibility": _column(binding, "external_eligibility", 7),
                    "provisioning_status": _column(binding, "provisioning_status", 3),
                    "recovery_state": _column(binding, "recovery_state", 4),
                }
            )
        except ValueError:
            raise ManagementAuthorizationDenied("target school business state is invalid") from None
        binding_version = _column(binding, "version", 0)
        availability = tuple(
            _column(binding, key, index)
            for index, key in enumerate(
                ("bootstrap_completed", "local_enabled", "provisioning_status", "recovery_state"),
                start=1,
            )
        )
        external_tid = _column(binding, "external_tid", 6)
        if external_tid is not None:
            external_school_id = _column(binding, "eduplus_tenant_id", 5)
            if (
                external_tid != str(external_school_id)
                or type(identity.webhook_app_id) is not int
                or identity.webhook_app_id <= 0
            ):
                raise ManagementAuthorizationDenied("school identity binding is inconsistent")
            projection_lock = " FOR SHARE" if write else ""
            projected = await (
                await connection.execute(
                    "SELECT 1 FROM eduplus2.webhook_school_state p "
                    "JOIN eduplus2.webhook_school_controls k "
                    "ON (k.tenant_id,k.school_id,k.external_app_id)="
                    "(p.tenant_id,p.school_id,p.external_app_id) "
                    "WHERE p.school_id=%s AND p.external_tenant_id=%s "
                    "AND p.external_app_id=%s AND p.binding_version=%s "
                    "AND p.onboarding_event_id IS NOT NULL "
                    "AND p.onboarding_completed_at IS NOT NULL "
                    + (
                        ""
                        if lifecycle_governance
                        else "AND p.eligibility='allowed' AND NOT k.frozen "
                    )
                    + projection_lock,
                    (
                        binding_school_id,
                        external_school_id,
                        identity.webhook_app_id,
                        binding_version,
                    ),
                )
            ).fetchone()
            if (
                not projected
                or (not lifecycle_governance and availability[3] != "normal")
                or (identity.application == "tms" and not availability[0])
            ):
                raise ManagementAuthorizationDenied("target school management is unavailable")
        elif (identity.application == "tms" or write) and availability != (
            True,
            True,
            "ready",
            "normal",
        ):
            raise ManagementAuthorizationDenied("target school is not available")
        if identity.application == "tms" and binding_version != identity.school_binding_version:
            raise ManagementAuthorizationDenied("school binding version changed")

    lock_assignment = " FOR SHARE OF a,rv,ra,ac" if write else ""
    assignments = await (
        await connection.execute(
            "SELECT a.id,a.version,rv.is_template,rv.owner_school_id,a.role_key,"
            "ra.owner_school_id AS action_owner_school_id,a.status,a.valid_from,"
            "a.expires_at,a.school_binding_version,ac.status AS action_status,"
            "ac.allowed_scope,a.scope_kind,a.school_id,a.revoked_at,a.application,"
            "rv.scope_kind AS role_scope_kind "
            "FROM management.assignments a "
            "JOIN management.role_actions ra ON ra.application=a.application "
            "AND ra.role_key=a.role_key AND ra.role_version=a.role_version "
            "JOIN management.role_versions rv ON rv.application=a.application "
            "AND rv.role_key=a.role_key AND rv.version=a.role_version "
            "JOIN management.action_catalog ac ON ac.application=ra.application "
            "AND ac.action_key=ra.action_key "
            "WHERE a.application=%s AND a.principal_id=%s AND ra.action_key=%s "
            "ORDER BY a.id" + lock_assignment,
            (
                identity.application,
                _column(principal, "id", 0),
                action,
            ),
        )
    ).fetchall()
    now = datetime.now(timezone.utc)
    selected = None
    for assignment in assignments:
        is_template = _column(assignment, "is_template", 2)
        owner_school_id = _column(assignment, "owner_school_id", 3)
        role_key = _column(assignment, "role_key", 4)
        action_owner_school_id = _column(assignment, "action_owner_school_id", 5)
        status = _column(assignment, "status", 6)
        valid_from = _column(assignment, "valid_from", 7)
        expires_at = _column(assignment, "expires_at", 8)
        assignment_binding_version = _column(assignment, "school_binding_version", 9)
        action_status = _column(assignment, "action_status", 10)
        allowed_scope = _column(assignment, "allowed_scope", 11)
        row_scope = _column(assignment, "scope_kind", 12)
        row_school_id = _column(assignment, "school_id", 13)
        revoked_at = _column(assignment, "revoked_at", 14)
        row_application = _column(assignment, "application", 15)
        role_scope = _column(assignment, "role_scope_kind", 16)
        try:
            validate_management_action_row(
                {
                    "application": row_application,
                    "action_key": action,
                    "allowed_scope": allowed_scope,
                    "status": action_status,
                }
            )
        except ManagementValueError:
            raise ManagementAuthorizationDenied(
                "management assignment fact is invalid: action catalog fact is invalid"
            ) from None
        try:
            validate_management_role_version_row(
                {
                    "application": row_application,
                    "role_key": role_key,
                    "scope_kind": role_scope,
                    "is_template": is_template,
                    "owner_school_id": owner_school_id,
                }
            )
        except ManagementValueError:
            raise ManagementAuthorizationDenied(
                "management assignment fact is invalid: role version fact is invalid"
            ) from None
        try:
            validate_management_assignment_row(
                {
                    "id": _column(assignment, "id", 0),
                    "application": row_application,
                    "version": _column(assignment, "version", 1),
                    "scope_kind": row_scope,
                    "school_id": row_school_id,
                    "status": status,
                    "valid_from": valid_from,
                    "expires_at": expires_at,
                    "revoked_at": revoked_at,
                    "school_binding_version": assignment_binding_version,
                }
            )
        except ManagementValueError:
            raise ManagementAuthorizationDenied("management assignment fact is invalid") from None
        if (
            not isinstance(_column(assignment, "id", 0), UUID)
            or type(_column(assignment, "version", 1)) is not int
            or _column(assignment, "version", 1) < 1
            or row_application != identity.application
            or not isinstance(role_key, str)
            or not role_key.strip()
            or status not in {"active", "revoked"}
            or row_scope not in {"platform", "school"}
            or role_scope != row_scope
            or (
                row_scope == "platform"
                and (row_school_id is not None or assignment_binding_version is not None)
            )
            or (
                row_scope == "school"
                and (
                    not isinstance(row_school_id, UUID)
                    or type(assignment_binding_version) is not int
                    or assignment_binding_version < 1
                )
            )
            or (identity.application == "tms" and row_school_id != identity.school_id)
            or not isinstance(valid_from, datetime)
            or valid_from.tzinfo is None
            or not isinstance(expires_at, datetime)
            or expires_at.tzinfo is None
            or expires_at <= valid_from
            or (status == "active" and revoked_at is not None)
            or (
                status == "revoked"
                and (not isinstance(revoked_at, datetime) or revoked_at.tzinfo is None)
            )
            or action_status not in {"active", "retired"}
            or allowed_scope not in {"platform", "school", "both"}
            or allowed_scope not in {row_scope, "both"}
            or (
                identity.application == "tms"
                and (row_scope != "school" or allowed_scope != "school")
            )
        ):
            raise ManagementAuthorizationDenied("management assignment fact is invalid")
        if type(is_template) is not bool or action_owner_school_id != owner_school_id:
            raise ManagementAuthorizationDenied("management role owner is inconsistent")
        if identity.application == "oms" and owner_school_id is not None:
            raise ManagementAuthorizationDenied("management role owner is inconsistent")
        if identity.application == "tms" and is_template and owner_school_id is not None:
            raise ManagementAuthorizationDenied("management role owner is inconsistent")
        if (
            identity.application == "tms"
            and not is_template
            and (
                not isinstance(row_school_id, UUID)
                or owner_school_id != row_school_id
                or not role_key.startswith(f"custom_{row_school_id.hex}_")
            )
        ):
            raise ManagementAuthorizationDenied("management role owner is inconsistent")
        if (
            status == "active"
            and valid_from <= now < expires_at
            and action_status == "active"
            and row_scope == scope_kind
            and row_school_id == target_school_id
            and (row_scope == "platform" or assignment_binding_version == binding_version)
            and selected is None
        ):
            selected = assignment
    if selected is None:
        raise ManagementAuthorizationDenied("management action or scope is not granted")
    return ManagementDecision(
        application=identity.application,
        principal_id=_column(principal, "id", 0),
        action=action,
        school_id=target_school_id,
        policy_version=_column(principal, "policy_version", 3),
        assignment_id=_column(selected, "id", 0),
        assignment_version=_column(selected, "version", 1),
        school_binding_version=binding_version,
    )


async def require_management_delegation(
    connection,
    identity: ManagementIdentity,
    action: str,
    *,
    target_school_id: UUID | None,
    grant_expires_at: datetime,
) -> ManagementDelegationDecision:
    """核验治理动作及独立委托上界；不代替目标主体或写命令复核。"""

    from .delegation_rules import validate_delegation_relation

    if (
        not isinstance(grant_expires_at, datetime)
        or grant_expires_at.tzinfo is None
        or grant_expires_at <= datetime.now(timezone.utc)
    ):
        raise ManagementAuthorizationDenied("delegation expiry is invalid")
    if not isinstance(identity, ManagementIdentity):
        raise ManagementAuthorizationDenied("external management identity is unavailable")
    if not isinstance(action, str) or len(action) > 128:
        raise ManagementAuthorizationDenied("delegated action is invalid")
    prefix = "ops." if identity.application == "oms" else "tenant."
    if (
        not action.startswith(prefix)
        or target_school_id is not None
        and not isinstance(target_school_id, UUID)
    ):
        raise ManagementAuthorizationDenied("delegated action or scope is invalid")
    if identity.application == "tms" and target_school_id != identity.school_id:
        raise ManagementAuthorizationDenied("delegation school differs from trusted session")

    governance_action = (
        "ops.permissions.manage" if identity.application == "oms" else "tenant.permissions.manage"
    )
    governance = await require_management_permission(
        connection,
        identity,
        governance_action,
        target_school_id=identity.school_id if identity.application == "tms" else None,
        write=True,
        _lock_school_id=target_school_id if identity.application == "oms" else None,
    )
    scope_kind = "platform" if target_school_id is None else "school"
    rows = await (
        await connection.execute(
            "SELECT d.id,d.version,d.status,d.valid_from,d.expires_at,"
            "d.scope_kind,d.school_id,ac.status AS action_status,ac.allowed_scope "
            "FROM management.delegation_policies d "
            "JOIN management.action_catalog ac ON ac.application=d.application "
            "AND ac.action_key=d.action_key "
            "WHERE d.application=%s AND d.principal_id=%s AND d.action_key=%s "
            "ORDER BY d.id FOR SHARE OF d,ac",
            (
                identity.application,
                governance.principal_id,
                action,
            ),
        )
    ).fetchall()
    now = datetime.now(timezone.utc)
    selected = None
    for row in rows:
        status = _column(row, "status", 2)
        valid_from = _column(row, "valid_from", 3)
        expires_at = _column(row, "expires_at", 4)
        row_scope = _column(row, "scope_kind", 5)
        school_id = _column(row, "school_id", 6)
        action_status = _column(row, "action_status", 7)
        allowed_scope = _column(row, "allowed_scope", 8)
        try:
            validate_management_action_row(
                {
                    "application": identity.application,
                    "action_key": action,
                    "allowed_scope": allowed_scope,
                    "status": action_status,
                }
            )
        except ManagementValueError:
            raise ManagementAuthorizationDenied("management delegation fact is invalid") from None
        try:
            validate_management_delegation_row(
                {
                    "id": _column(row, "id", 0),
                    "application": identity.application,
                    "version": _column(row, "version", 1),
                    "status": status,
                    "valid_from": valid_from,
                    "expires_at": expires_at,
                    "scope_kind": row_scope,
                    "school_id": school_id,
                }
            )
        except ManagementValueError:
            raise ManagementAuthorizationDenied("management delegation fact is invalid") from None
        if (
            not isinstance(_column(row, "id", 0), UUID)
            or type(_column(row, "version", 1)) is not int
            or _column(row, "version", 1) < 1
            or status not in {"active", "revoked"}
            or not isinstance(valid_from, datetime)
            or valid_from.tzinfo is None
            or not isinstance(expires_at, datetime)
            or expires_at.tzinfo is None
            or expires_at <= valid_from
        ):
            raise ManagementAuthorizationDenied("management delegation fact is invalid")
        try:
            validate_delegation_relation(
                application=identity.application,
                principal_application=identity.application,
                principal_school_id=identity.school_id,
                action_application=identity.application,
                action_status=action_status,
                action_allowed_scope=allowed_scope,
                delegation_scope_kind=row_scope,
                delegation_school_id=school_id,
                for_write=False,
            )
        except ManagementAuthorizationDenied as exc:
            raise ManagementAuthorizationDenied("management delegation fact is invalid") from exc
        if (
            row_scope == scope_kind
            and school_id == target_school_id
            and status == "active"
            and valid_from <= now
            and expires_at >= grant_expires_at
            and action_status == "active"
            and allowed_scope in {scope_kind, "both"}
        ):
            selected = row
    if selected is None:
        raise ManagementAuthorizationDenied("management delegation is not granted")
    return ManagementDelegationDecision(
        governance=governance,
        delegated_action=action,
        school_id=target_school_id,
        delegation_id=_column(selected, "id", 0),
        delegation_version=_column(selected, "version", 1),
        school_binding_version=governance.school_binding_version,
    )
