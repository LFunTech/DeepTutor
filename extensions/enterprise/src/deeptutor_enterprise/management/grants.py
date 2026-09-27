"""管理角色的事务内授予；正式入口须另行接入可信外部身份适配器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from psycopg.errors import CheckViolation
from psycopg.types.json import Jsonb

from deeptutor_enterprise.management.authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
    _identity_is_current,
    require_management_delegation,
    require_management_permission,
)


class ManagementGrantConflict(ValueError):
    """预期版本、幂等命令或现存授权与当前事实冲突。"""


@dataclass(frozen=True, slots=True)
class GrantRoleCommand:
    target_principal_id: UUID
    role_key: str
    role_version: int
    target_school_id: UUID | None
    expected_target_policy_version: int
    expires_at: datetime
    command_id: UUID
    reason: str
    request_id: str


@dataclass(frozen=True, slots=True)
class GrantRoleResult:
    assignment_id: UUID
    target_policy_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class RevokeRoleCommand:
    assignment_id: UUID
    target_school_id: UUID | None
    expected_assignment_version: int
    expected_target_policy_version: int
    command_id: UUID
    reason: str
    request_id: str


@dataclass(frozen=True, slots=True)
class RevokeRoleResult:
    assignment_id: UUID
    assignment_version: int
    target_policy_version: int
    replayed: bool


def _validate_command(command: GrantRoleCommand) -> None:
    if (
        not isinstance(command, GrantRoleCommand)
        or not isinstance(command.target_principal_id, UUID)
        or not isinstance(command.command_id, UUID)
        or not isinstance(command.role_key, str)
        or not command.role_key.strip()
        or len(command.role_key) > 128
        or type(command.role_version) is not int
        or command.role_version < 1
        or (command.target_school_id is not None and not isinstance(command.target_school_id, UUID))
        or type(command.expected_target_policy_version) is not int
        or command.expected_target_policy_version < 1
        or not isinstance(command.expires_at, datetime)
        or command.expires_at.tzinfo is None
        or command.expires_at <= datetime.now(timezone.utc)
        or not isinstance(command.reason, str)
        or not command.reason.strip()
        or len(command.reason) > 1000
        or not isinstance(command.request_id, str)
        or not command.request_id.strip()
        or len(command.request_id) > 128
    ):
        raise ManagementAuthorizationDenied("management grant command is invalid")


async def grant_management_role(
    connection,
    actor: ManagementIdentity,
    target: ManagementIdentity,
    command: GrantRoleCommand,
) -> GrantRoleResult:
    """低风险角色授予；调用方必须保留本事务直到提交或回滚。

    actor 和 target 均须由可信适配器实时核验。本函数不构造身份、不接收
    HTTP header，也不装配 API。首管理员及含敏感动作的角色另走双人审批。
    """

    _validate_command(command)
    if not isinstance(actor, ManagementIdentity) or not isinstance(target, ManagementIdentity):
        raise ManagementAuthorizationDenied("external management identity is unavailable")
    if not _identity_is_current(target, write=True):
        raise ManagementAuthorizationDenied("target external status is not current")
    if actor.application != target.application or (
        actor.issuer == target.issuer and actor.subject == target.subject
    ):
        raise ManagementAuthorizationDenied("cross-application or self grant is forbidden")
    if actor.application == "tms" and (
        actor.school_id != command.target_school_id
        or target.school_id != command.target_school_id
        or target.school_binding_version != actor.school_binding_version
    ):
        raise ManagementAuthorizationDenied("target school differs from trusted identities")
    if actor.application == "oms" and target.school_id is not None:
        raise ManagementAuthorizationDenied("OMS target must be a platform principal")
    governance_action = (
        "ops.permissions.manage" if actor.application == "oms" else "tenant.permissions.manage"
    )
    # 此调用先锁住治理主体和目标学校；后续所有受委托动作仍在同一事务内复核。
    governance = await require_management_permission(
        connection,
        actor,
        governance_action,
        target_school_id=command.target_school_id if actor.application == "tms" else None,
        write=True,
        _lock_school_id=command.target_school_id if actor.application == "oms" else None,
    )
    scope_kind = "platform" if command.target_school_id is None else "school"
    if actor.application == "tms" and scope_kind != "school":
        raise ManagementAuthorizationDenied("TMS grants require a school scope")
    role = await (
        await connection.execute(
            "SELECT scope_kind FROM management.role_versions WHERE application=%s "
            "AND role_key=%s AND version=%s FOR SHARE",
            (actor.application, command.role_key, command.role_version),
        )
    ).fetchone()
    if not role or role[0] != scope_kind:
        raise ManagementAuthorizationDenied("role version or scope is invalid")
    if (actor.application, command.role_key) in {
        ("tms", "school_admin"),
        ("oms", "platform_security_admin"),
    }:
        raise ManagementAuthorizationDenied("administrator grant requires independent approval")
    actions = await (
        await connection.execute(
            "SELECT ra.action_key,ac.status,ac.sensitive FROM management.role_actions ra "
            "JOIN management.action_catalog ac ON ac.application=ra.application "
            "AND ac.action_key=ra.action_key "
            "WHERE ra.application=%s AND ra.role_key=%s AND ra.role_version=%s "
            "ORDER BY ra.action_key FOR SHARE OF ra,ac",
            (actor.application, command.role_key, command.role_version),
        )
    ).fetchall()
    if not actions or any(status != "active" for _, status, _ in actions):
        raise ManagementAuthorizationDenied("role has no active action set")
    if any(sensitive for _, _, sensitive in actions):
        raise ManagementAuthorizationDenied("sensitive role grant requires independent approval")
    for action, _, _ in actions:
        await require_management_delegation(
            connection,
            actor,
            action,
            target_school_id=command.target_school_id,
            grant_expires_at=command.expires_at,
        )

    principal = await (
        await connection.execute(
            "SELECT id,status,policy_version FROM management.principals "
            "WHERE id=%s AND application=%s AND issuer=%s AND subject=%s "
            "AND school_id IS NOT DISTINCT FROM %s FOR UPDATE",
            (
                command.target_principal_id,
                target.application,
                target.issuer,
                target.subject,
                target.school_id,
            ),
        )
    ).fetchone()
    if not principal or principal[1] not in ("pending", "active"):
        raise ManagementAuthorizationDenied("target principal is unavailable")
    if principal[2] != target.policy_version:
        raise ManagementGrantConflict("target identity policy version changed")

    replay = await (
        await connection.execute(
            "SELECT a.id,a.principal_id,a.role_key,a.role_version,a.scope_kind,a.school_id,"
            "a.expires_at,a.created_by,a.status,e.actor_issuer,e.actor_subject,"
            "e.reason,e.request_id,e.before_version,e.after_version "
            "FROM management.assignments a "
            "LEFT JOIN management.audit_events e ON e.application=a.application "
            "AND e.target_kind='assignment' AND e.target_id=a.id::text "
            "AND e.result='success' WHERE a.command_id=%s FOR SHARE OF a",
            (command.command_id,),
        )
    ).fetchone()
    if replay:
        if (
            replay[1:6]
            != (
                command.target_principal_id,
                command.role_key,
                command.role_version,
                scope_kind,
                command.target_school_id,
            )
            or replay[6] != command.expires_at
            or replay[7] != str(governance.principal_id)
            or replay[8] != "active"
            or replay[9:13] != (actor.issuer, actor.subject, command.reason, command.request_id)
            or replay[13] != command.expected_target_policy_version
        ):
            raise ManagementGrantConflict("idempotency key was used for another grant")
        return GrantRoleResult(replay[0], replay[14], True)

    if principal[2] != command.expected_target_policy_version:
        raise ManagementGrantConflict("target policy version changed")
    existing = await (
        await connection.execute(
            "SELECT 1 FROM management.assignments WHERE application=%s "
            "AND principal_id=%s AND role_key=%s AND scope_kind=%s "
            "AND school_id IS NOT DISTINCT FROM %s AND status='active' LIMIT 1",
            (
                actor.application,
                command.target_principal_id,
                command.role_key,
                scope_kind,
                command.target_school_id,
            ),
        )
    ).fetchone()
    if existing:
        raise ManagementGrantConflict("target already has an active role assignment")
    if principal[1] == "pending":
        await connection.execute(
            "UPDATE management.principals SET status='active',updated_at=now() WHERE id=%s",
            (command.target_principal_id,),
        )

    assignment_id = uuid4()
    await connection.execute(
        "INSERT INTO management.assignments"
        "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
        "school_binding_version,valid_from,expires_at,command_id,created_by) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s,%s)",
        (
            assignment_id,
            actor.application,
            command.target_principal_id,
            command.role_key,
            command.role_version,
            scope_kind,
            command.target_school_id,
            governance.school_binding_version,
            command.expires_at,
            command.command_id,
            str(governance.principal_id),
        ),
    )
    version = await (
        await connection.execute(
            "SELECT policy_version FROM management.principals WHERE id=%s",
            (command.target_principal_id,),
        )
    ).fetchone()
    await connection.execute(
        "INSERT INTO management.audit_events"
        "(id,application,school_id,actor_issuer,actor_subject,action_key,target_kind,"
        "target_id,request_id,result,reason,before_version,after_version) "
        "VALUES(%s,%s,%s,%s,%s,%s,'assignment',%s,%s,'success',%s,%s,%s)",
        (
            uuid4(),
            actor.application,
            command.target_school_id,
            actor.issuer,
            actor.subject,
            governance_action,
            str(assignment_id),
            command.request_id,
            command.reason,
            principal[2],
            version[0],
        ),
    )
    return GrantRoleResult(assignment_id, version[0], False)


def _validate_revoke_command(command: RevokeRoleCommand) -> None:
    if (
        not isinstance(command, RevokeRoleCommand)
        or not isinstance(command.assignment_id, UUID)
        or (command.target_school_id is not None and not isinstance(command.target_school_id, UUID))
        or type(command.expected_assignment_version) is not int
        or command.expected_assignment_version < 1
        or type(command.expected_target_policy_version) is not int
        or command.expected_target_policy_version < 1
        or not isinstance(command.command_id, UUID)
        or not isinstance(command.reason, str)
        or not command.reason.strip()
        or len(command.reason) > 1000
        or not isinstance(command.request_id, str)
        or not command.request_id.strip()
        or len(command.request_id) > 128
    ):
        raise ManagementAuthorizationDenied("management revoke command is invalid")


async def revoke_management_role(
    connection,
    actor: ManagementIdentity,
    command: RevokeRoleCommand,
) -> RevokeRoleResult:
    """在同一事务内撤销本产品角色；不会修改外部账号或 OMS 服务权益。"""

    _validate_revoke_command(command)
    if not isinstance(actor, ManagementIdentity):
        raise ManagementAuthorizationDenied("external management identity is unavailable")
    if actor.application == "tms" and actor.school_id != command.target_school_id:
        raise ManagementAuthorizationDenied("target school differs from trusted session")
    governance_action = (
        "ops.permissions.manage" if actor.application == "oms" else "tenant.permissions.manage"
    )
    await require_management_permission(
        connection,
        actor,
        governance_action,
        target_school_id=command.target_school_id if actor.application == "tms" else None,
        write=True,
        _lock_school_id=command.target_school_id if actor.application == "oms" else None,
    )
    scope_kind = "platform" if command.target_school_id is None else "school"
    preliminary = await (
        await connection.execute(
            "SELECT principal_id FROM management.assignments WHERE id=%s AND application=%s "
            "AND scope_kind=%s AND school_id IS NOT DISTINCT FROM %s",
            (command.assignment_id, actor.application, scope_kind, command.target_school_id),
        )
    ).fetchone()
    if not preliminary:
        raise ManagementAuthorizationDenied("target assignment is unavailable")
    target = await (
        await connection.execute(
            "SELECT id,policy_version FROM management.principals WHERE id=%s "
            "AND application=%s FOR UPDATE",
            (preliminary[0], actor.application),
        )
    ).fetchone()
    if not target:
        raise ManagementAuthorizationDenied("target principal is unavailable")
    assignment = await (
        await connection.execute(
            "SELECT principal_id,version,status FROM management.assignments "
            "WHERE id=%s AND application=%s AND scope_kind=%s "
            "AND school_id IS NOT DISTINCT FROM %s FOR UPDATE",
            (command.assignment_id, actor.application, scope_kind, command.target_school_id),
        )
    ).fetchone()
    if not assignment or assignment[0] != target[0]:
        raise ManagementGrantConflict("target assignment changed")
    previous = await (
        await connection.execute(
            "SELECT application,school_id,actor_issuer,actor_subject,action_key,"
            "target_kind,target_id,request_id,result,reason,before_version,after_version,"
            "safe_summary "
            "FROM management.audit_events WHERE id=%s",
            (command.command_id,),
        )
    ).fetchone()
    if previous:
        if (
            previous[:10]
            != (
                actor.application,
                command.target_school_id,
                actor.issuer,
                actor.subject,
                governance_action,
                "assignment_revoke",
                str(command.assignment_id),
                command.request_id,
                "success",
                command.reason,
            )
            or previous[10] != command.expected_target_policy_version
            or previous[12].get("expected_assignment_version")
            != command.expected_assignment_version
            or assignment[2] != "revoked"
        ):
            raise ManagementGrantConflict("idempotency key was used for another revoke")
        return RevokeRoleResult(command.assignment_id, assignment[1], previous[11], True)
    if (
        assignment[2] != "active"
        or assignment[1] != command.expected_assignment_version
        or target[1] != command.expected_target_policy_version
    ):
        raise ManagementGrantConflict("assignment or target policy version changed")
    try:
        async with connection.transaction():
            await connection.execute(
                "UPDATE management.assignments SET status='revoked',revoked_at=now(),"
                "version=version+1 WHERE id=%s",
                (command.assignment_id,),
            )
    except CheckViolation as exc:
        if "last active management administrator" not in str(exc):
            raise
        raise ManagementGrantConflict("last active administrator cannot be revoked") from exc
    after = await (
        await connection.execute(
            "SELECT policy_version FROM management.principals WHERE id=%s", (target[0],)
        )
    ).fetchone()
    await connection.execute(
        "INSERT INTO management.audit_events"
        "(id,application,school_id,actor_issuer,actor_subject,action_key,target_kind,"
        "target_id,request_id,result,reason,before_version,after_version,safe_summary) "
        "VALUES(%s,%s,%s,%s,%s,%s,'assignment_revoke',%s,%s,'success',%s,%s,%s,%s)",
        (
            command.command_id,
            actor.application,
            command.target_school_id,
            actor.issuer,
            actor.subject,
            governance_action,
            str(command.assignment_id),
            command.request_id,
            command.reason,
            target[1],
            after[0],
            Jsonb({"expected_assignment_version": command.expected_assignment_version}),
        ),
    )
    return RevokeRoleResult(command.assignment_id, assignment[1] + 1, after[0], False)
