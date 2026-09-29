"""管理主体本地停用的事务规则；外部账号状态仍由身份适配器判定。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from psycopg.pq import TransactionStatus

from .authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
    _column,
    _identity_is_current,
    require_management_permission,
)


@dataclass(frozen=True, slots=True)
class DisablePrincipalCommand:
    target_principal_id: UUID
    target_school_id: UUID | None
    expected_policy_version: int
    reason: str
    request_id: str


@dataclass(frozen=True, slots=True)
class DisablePrincipalResult:
    target_principal_id: UUID
    target_policy_version: int


async def disable_management_principal(
    connection,
    actor: ManagementIdentity,
    command: DisablePrincipalCommand,
) -> DisablePrincipalResult:
    """停用本产品主体，不修改 EduPlus2 账号；调用方持有同一写事务直至提交。"""

    if (
        not isinstance(actor, ManagementIdentity)
        or not _identity_is_current(actor, write=True)
        or not isinstance(command, DisablePrincipalCommand)
        or not isinstance(command.target_principal_id, UUID)
        or (command.target_school_id is not None and not isinstance(command.target_school_id, UUID))
        or type(command.expected_policy_version) is not int
        or command.expected_policy_version < 1
        or not isinstance(command.reason, str)
        or not 1 <= len(command.reason.strip()) <= 1000
        or not isinstance(command.request_id, str)
        or not 1 <= len(command.request_id.strip()) <= 128
        or (actor.application == "oms" and command.target_school_id is not None)
        or (actor.application == "tms" and command.target_school_id != actor.school_id)
    ):
        raise ManagementAuthorizationDenied("management principal disable command is invalid")
    if connection.autocommit and connection.info.transaction_status != TransactionStatus.INTRANS:
        raise ManagementAuthorizationDenied("management write requires a transaction")
    # 撤销 assignment 和停用 principal 必须按同一学校/平台锁串行化。
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (
            str(command.target_school_id)
            if command.target_school_id is not None
            else "oms-platform-security",
        ),
    )
    action = "ops.permissions.manage" if actor.application == "oms" else "tenant.permissions.manage"
    await require_management_permission(
        connection,
        actor,
        action,
        target_school_id=command.target_school_id if actor.application == "tms" else None,
        _lock_school_id=command.target_school_id if actor.application == "oms" else None,
        write=True,
    )
    target = await (
        await connection.execute(
            "SELECT id,status,policy_version FROM management.principals "
            "WHERE id=%s AND application=%s AND school_id IS NOT DISTINCT FROM %s FOR UPDATE",
            (command.target_principal_id, actor.application, command.target_school_id),
        )
    ).fetchone()
    if target is None or _column(target, "status", 1) != "active":
        raise ManagementAuthorizationDenied("management principal is not active")
    if _column(target, "policy_version", 2) != command.expected_policy_version:
        raise ManagementAuthorizationDenied("management principal policy version changed")

    admin_role = "platform_security_admin" if actor.application == "oms" else "school_admin"
    target_is_admin = await (
        await connection.execute(
            "SELECT 1 FROM management.assignments a "
            "JOIN management.role_actions ra ON ra.application=a.application "
            "AND ra.role_key=a.role_key AND ra.role_version=a.role_version "
            "JOIN management.action_catalog ac ON ac.application=ra.application "
            "AND ac.action_key=ra.action_key "
            "WHERE a.application=%s AND a.principal_id=%s AND a.role_key=%s "
            "AND a.school_id IS NOT DISTINCT FROM %s "
            "AND a.status='active' AND a.valid_from<=clock_timestamp() "
            "AND a.expires_at>clock_timestamp() AND ra.action_key=%s "
            "AND ac.status='active' LIMIT 1",
            (
                actor.application,
                command.target_principal_id,
                admin_role,
                command.target_school_id,
                action,
            ),
        )
    ).fetchone()
    if target_is_admin:
        replacement = await (
            await connection.execute(
                "SELECT 1 FROM management.assignments a "
                "JOIN management.principals p ON p.id=a.principal_id "
                "AND p.application=a.application "
                "JOIN management.role_actions ra ON ra.application=a.application "
                "AND ra.role_key=a.role_key AND ra.role_version=a.role_version "
                "JOIN management.action_catalog ac ON ac.application=ra.application "
                "AND ac.action_key=ra.action_key "
                "WHERE a.application=%s AND a.principal_id<>%s AND a.role_key=%s "
                "AND a.school_id IS NOT DISTINCT FROM %s "
                "AND a.status='active' AND a.valid_from<=clock_timestamp() "
                "AND a.expires_at>clock_timestamp() AND p.status='active' "
                "AND ra.action_key=%s AND ac.status='active' LIMIT 1",
                (
                    actor.application,
                    command.target_principal_id,
                    admin_role,
                    command.target_school_id,
                    action,
                ),
            )
        ).fetchone()
        if replacement is None:
            raise ManagementAuthorizationDenied("last active management administrator cannot be disabled")

    updated = await (
        await connection.execute(
            "UPDATE management.principals SET status='disabled',"
            "policy_version=policy_version+1,updated_at=clock_timestamp() "
            "WHERE id=%s AND application=%s AND status='active' AND policy_version=%s "
            "RETURNING policy_version",
            (command.target_principal_id, actor.application, command.expected_policy_version),
        )
    ).fetchone()
    if updated is None or _column(updated, "policy_version", 0) != command.expected_policy_version + 1:
        raise ManagementAuthorizationDenied("management principal changed during disable")
    await connection.execute(
        "INSERT INTO management.audit_events"
        "(id,application,school_id,actor_issuer,actor_subject,action_key,target_kind,"
        "target_id,request_id,result,reason,before_version,after_version) "
        "VALUES(%s,%s,%s,%s,%s,%s,'principal',%s,%s,'success',%s,%s,%s)",
        (
            uuid4(), actor.application, command.target_school_id, actor.issuer,
            actor.subject, action, str(command.target_principal_id), command.request_id.strip(),
            command.reason.strip(), command.expected_policy_version, _column(updated, "policy_version", 0),
        ),
    )
    return DisablePrincipalResult(command.target_principal_id, _column(updated, "policy_version", 0))
