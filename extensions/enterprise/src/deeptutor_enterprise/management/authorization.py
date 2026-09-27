"""DeepTutor Enterprise 应用层管理授权；PG 仅保存事实并保障事务一致性。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID


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
    if write and connection.autocommit:
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
        if not tenant_setting or tenant_setting[0] != str(identity.school_id):
            raise ManagementAuthorizationDenied("transaction school scope is not trusted")

    await connection.execute(
        "SELECT set_config('app.management_app',%s,true)", (identity.application,)
    )
    scope_kind = "platform" if target_school_id is None else "school"
    lock = " FOR UPDATE" if write else ""
    principal = await (
        await connection.execute(
            "SELECT id,school_id,status,policy_version FROM management.principals "
            "WHERE application=%s AND issuer=%s AND subject=%s "
            "AND school_id IS NOT DISTINCT FROM %s" + lock,
            (identity.application, identity.issuer, identity.subject, identity.school_id),
        )
    ).fetchone()
    if not principal or principal[2] != "active" or principal[3] != identity.policy_version:
        raise ManagementAuthorizationDenied("management principal or policy version is invalid")

    binding_version = None
    binding_school_id = _lock_school_id or target_school_id
    if binding_school_id is not None:
        binding_lock = " FOR SHARE OF b,t" if write else ""
        binding = await (
            await connection.execute(
                "SELECT b.version,t.bootstrap_completed,t.local_enabled,"
                "t.provisioning_status,t.recovery_state FROM oms.school_bindings b "
                "JOIN enterprise.tenants t ON t.id=b.tenant_id "
                "WHERE b.tenant_id=%s AND b.status='verified' "
                "AND t.external_eligibility='allowed'" + binding_lock,
                (binding_school_id,),
            )
        ).fetchone()
        if not binding:
            raise ManagementAuthorizationDenied("target school binding is not verified")
        binding_version = binding[0]
        if (identity.application == "tms" or write) and binding[1:] != (
            True,
            True,
            "ready",
            "normal",
        ):
            raise ManagementAuthorizationDenied("target school is not available")
        if identity.application == "tms" and binding_version != identity.school_binding_version:
            raise ManagementAuthorizationDenied("school binding version changed")

    lock_assignment = " FOR SHARE OF a" if write else ""
    assignment = await (
        await connection.execute(
            "SELECT a.id,a.version FROM management.assignments a "
            "JOIN management.role_actions ra ON ra.application=a.application "
            "AND ra.role_key=a.role_key AND ra.role_version=a.role_version "
            "JOIN management.action_catalog ac ON ac.application=ra.application "
            "AND ac.action_key=ra.action_key "
            "WHERE a.application=%s AND a.principal_id=%s "
            "AND a.scope_kind=%s AND a.school_id IS NOT DISTINCT FROM %s "
            "AND a.status='active' AND a.valid_from<=now() AND a.expires_at>now() "
            "AND ra.action_key=%s AND ac.status='active' "
            "AND ac.allowed_scope IN (%s,'both') "
            "AND (a.scope_kind='platform' OR a.school_binding_version=%s) "
            "ORDER BY a.id LIMIT 1" + lock_assignment,
            (
                identity.application,
                principal[0],
                scope_kind,
                target_school_id,
                action,
                scope_kind,
                binding_version,
            ),
        )
    ).fetchone()
    if not assignment:
        raise ManagementAuthorizationDenied("management action or scope is not granted")
    return ManagementDecision(
        application=identity.application,
        principal_id=principal[0],
        action=action,
        school_id=target_school_id,
        policy_version=principal[3],
        assignment_id=assignment[0],
        assignment_version=assignment[1],
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
    row = await (
        await connection.execute(
            "SELECT d.id,d.version FROM management.delegation_policies d "
            "JOIN management.action_catalog ac ON ac.application=d.application "
            "AND ac.action_key=d.action_key "
            "WHERE d.application=%s AND d.principal_id=%s AND d.action_key=%s "
            "AND d.scope_kind=%s AND d.school_id IS NOT DISTINCT FROM %s "
            "AND d.status='active' AND d.valid_from<=now() "
            "AND d.expires_at>=%s AND ac.status='active' "
            "AND ac.allowed_scope IN (%s,'both') "
            "ORDER BY d.id LIMIT 1 FOR SHARE OF d,ac",
            (
                identity.application,
                governance.principal_id,
                action,
                scope_kind,
                target_school_id,
                grant_expires_at,
                scope_kind,
            ),
        )
    ).fetchone()
    if not row:
        raise ManagementAuthorizationDenied("management delegation is not granted")
    return ManagementDelegationDecision(
        governance=governance,
        delegated_action=action,
        school_id=target_school_id,
        delegation_id=row[0],
        delegation_version=row[1],
        school_binding_version=governance.school_binding_version,
    )
