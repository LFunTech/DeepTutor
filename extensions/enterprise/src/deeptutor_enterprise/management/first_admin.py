"""OMS 首位平台管理员的受控本地初始化。

此模块只消费已经由 OMS OIDC 适配器验真的 ``ManagementIdentity``，不从
EduPlus2 读取或推断任何 DeepTutor ``ops.*`` 权限。正常授权仍走
``management.grants``/``management.approvals``；这里仅解决零本地管理员的
首次启动闭环。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from psycopg.types.json import Jsonb

from .authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
    _identity_is_current,
)
from .policy_version import advance_principal_policy_version
from .value_validation import (
    ManagementValueError,
    validate_management_assignment_row,
    validate_management_principal_row,
    validate_management_role_version_row,
)

_BOOTSTRAP_ROLE_VERSION = 2
_BOOTSTRAP_ROLES = ("platform_config_admin", "platform_security_admin")


class FirstOmsAdministratorConflict(RuntimeError):
    """首位 OMS 管理员已由其他主体初始化。"""


@dataclass(frozen=True, slots=True)
class BootstrapFirstOmsAdministratorCommand:
    command_id: UUID
    reason: str
    request_id: str


@dataclass(frozen=True, slots=True)
class BootstrapFirstOmsAdministratorResult:
    principal_id: UUID
    assignment_ids: tuple[UUID, ...]
    role_keys: tuple[str, ...]
    target_policy_version: int
    replayed: bool


def _validate_command(command: BootstrapFirstOmsAdministratorCommand) -> None:
    if (
        not isinstance(command, BootstrapFirstOmsAdministratorCommand)
        or not isinstance(command.command_id, UUID)
        or not isinstance(command.reason, str)
        or not command.reason.strip()
        or len(command.reason) > 1000
        or not isinstance(command.request_id, str)
        or not command.request_id.strip()
        or len(command.request_id) > 128
    ):
        raise ManagementAuthorizationDenied("OMS first administrator command is invalid")


def _assignment_command_id(command_id: UUID, role_key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"deeptutor:oms:first-admin:{command_id}:{role_key}")


async def _active_security_administrators(connection) -> list[dict[str, object]]:
    rows = await (
        await connection.execute(
            "SELECT DISTINCT p.id,p.issuer,p.subject "
            "FROM management.assignments a "
            "JOIN management.principals p ON p.application=a.application "
            "AND p.id=a.principal_id "
            "JOIN management.role_actions ra ON ra.application=a.application "
            "AND ra.role_key=a.role_key AND ra.role_version=a.role_version "
            "JOIN management.action_catalog ac ON ac.application=ra.application "
            "AND ac.action_key=ra.action_key "
            "WHERE a.application='oms' AND a.role_key='platform_security_admin' "
            "AND a.scope_kind='platform' AND a.school_id IS NULL "
            "AND a.status='active' AND a.valid_from<=now() AND a.expires_at>now() "
            "AND p.status='active' AND ra.action_key='ops.permissions.manage' "
            "AND ac.status='active' "
            "ORDER BY p.subject,p.id"
        )
    ).fetchall()
    return [dict(row) if isinstance(row, dict) else {"id": row[0], "issuer": row[1], "subject": row[2]} for row in rows]


async def _ensure_bootstrap_roles_exist(connection) -> None:
    for role_key in _BOOTSTRAP_ROLES:
        row = await (
            await connection.execute(
                "SELECT application,role_key,version,scope_kind,is_template,owner_school_id "
                "FROM management.role_versions "
                "WHERE application='oms' AND role_key=%s AND version=%s FOR SHARE",
                (role_key, _BOOTSTRAP_ROLE_VERSION),
            )
        ).fetchone()
        if row is None:
            raise ManagementAuthorizationDenied("OMS bootstrap role is unavailable")
        try:
            validate_management_role_version_row(
                {
                    "application": row["application"],
                    "role_key": row["role_key"],
                    "version": row["version"],
                    "scope_kind": row["scope_kind"],
                    "is_template": row["is_template"],
                    "owner_school_id": row["owner_school_id"],
                }
            )
        except ManagementValueError:
            raise ManagementAuthorizationDenied("OMS bootstrap role fact is invalid") from None
        if row["scope_kind"] != "platform" or row["is_template"] is not True:
            raise ManagementAuthorizationDenied("OMS bootstrap role scope is invalid")


async def _ensure_principal(connection, actor: ManagementIdentity) -> tuple[UUID, int]:
    row = await (
        await connection.execute(
            "SELECT id,application,school_id,status,policy_version "
            "FROM management.principals "
            "WHERE application='oms' AND issuer=%s AND subject=%s "
            "AND school_id IS NULL FOR UPDATE",
            (actor.issuer, actor.subject),
        )
    ).fetchone()
    if row is None:
        principal_id = uuid4()
        await connection.execute(
            "INSERT INTO management.principals"
            "(id,application,issuer,subject,school_id,status,external_evidence_ref) "
            "VALUES(%s,'oms',%s,%s,NULL,'active','oms:first-admin-bootstrap')",
            (principal_id, actor.issuer, actor.subject),
        )
        return principal_id, 1

    try:
        validate_management_principal_row(
            {
                "application": row["application"],
                "school_id": row["school_id"],
                "status": row["status"],
                "policy_version": row["policy_version"],
            }
        )
    except ManagementValueError:
        raise ManagementAuthorizationDenied("management principal fact is invalid") from None
    if row["status"] == "disabled":
        raise ManagementAuthorizationDenied("OMS principal is disabled")
    if row["status"] == "pending":
        await connection.execute(
            "UPDATE management.principals SET status='active',updated_at=clock_timestamp() "
            "WHERE id=%s",
            (row["id"],),
        )
    return row["id"], row["policy_version"]


async def _assignment_for_role(connection, principal_id: UUID, role_key: str):
    return await (
        await connection.execute(
            "SELECT id,version,status,valid_from,expires_at,revoked_at,"
            "scope_kind,school_id,school_binding_version "
            "FROM management.assignments "
            "WHERE application='oms' AND principal_id=%s AND role_key=%s "
            "AND role_version=%s AND scope_kind='platform' AND school_id IS NULL "
            "AND status='active' AND valid_from<=now() AND expires_at>now() "
            "ORDER BY created_at DESC,id LIMIT 1 FOR SHARE",
            (principal_id, role_key, _BOOTSTRAP_ROLE_VERSION),
        )
    ).fetchone()


async def _insert_assignment(
    connection,
    *,
    actor: ManagementIdentity,
    principal_id: UUID,
    role_key: str,
    command: BootstrapFirstOmsAdministratorCommand,
    expected_policy_version: int,
) -> tuple[UUID, int]:
    assignment_id = uuid4()
    expires_at = datetime(9998, 1, 1, tzinfo=timezone.utc)
    await connection.execute(
        "INSERT INTO management.assignments"
        "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
        "school_binding_version,valid_from,expires_at,command_id,created_by) "
        "VALUES(%s,'oms',%s,%s,%s,'platform',NULL,NULL,clock_timestamp(),%s,%s,%s)",
        (
            assignment_id,
            principal_id,
            role_key,
            _BOOTSTRAP_ROLE_VERSION,
            expires_at,
            _assignment_command_id(command.command_id, role_key),
            "oms:first-admin-bootstrap",
        ),
    )
    try:
        validate_management_assignment_row(
            {
                "id": assignment_id,
                "application": "oms",
                "version": 1,
                "scope_kind": "platform",
                "school_id": None,
                "status": "active",
                "valid_from": datetime.now(timezone.utc),
                "expires_at": expires_at,
                "revoked_at": None,
                "school_binding_version": None,
            }
        )
    except ManagementValueError:
        raise ManagementAuthorizationDenied("OMS bootstrap assignment fact is invalid") from None
    next_policy_version = await advance_principal_policy_version(
        connection, principal_id, expected_before=expected_policy_version
    )
    await connection.execute(
        "INSERT INTO management.audit_events"
        "(id,application,school_id,actor_issuer,actor_subject,action_key,target_kind,"
        "target_id,request_id,result,reason,before_version,after_version,safe_summary) "
        "VALUES(%s,'oms',NULL,%s,%s,'ops.permissions.manage','assignment',%s,%s,"
        "'success',%s,%s,%s,%s)",
        (
            uuid4(),
            actor.issuer,
            actor.subject,
            str(assignment_id),
            command.request_id,
            command.reason,
            expected_policy_version,
            next_policy_version,
            Jsonb(
                {
                    "bootstrap": "first_oms_administrator",
                    "role_key": role_key,
                    "role_version": _BOOTSTRAP_ROLE_VERSION,
                }
            ),
        ),
    )
    return assignment_id, next_policy_version


async def bootstrap_first_oms_administrator(
    connection,
    actor: ManagementIdentity,
    command: BootstrapFirstOmsAdministratorCommand,
) -> BootstrapFirstOmsAdministratorResult:
    """将当前已认证平台主体初始化为首位本产品 OMS 管理员。

    只允许在没有其他活跃 ``platform_security_admin`` 时执行；同一主体重复
    请求幂等返回，不会给第二个主体打开旁路。
    """

    _validate_command(command)
    if not isinstance(actor, ManagementIdentity) or actor.application != "oms":
        raise ManagementAuthorizationDenied("OMS platform identity is required")
    if not _identity_is_current(actor, write=True):
        raise ManagementAuthorizationDenied("OMS platform identity is not current")
    await connection.execute("SELECT set_config('app.management_app','oms',true)")
    # 使用应用显式表锁串行化零管理员检查与首次插入；业务规则仍在 Python 中判断。
    await connection.execute("LOCK TABLE management.principals, management.assignments IN SHARE ROW EXCLUSIVE MODE")
    active_admins = await _active_security_administrators(connection)
    active_for_actor = [
        row
        for row in active_admins
        if row["issuer"] == actor.issuer and row["subject"] == actor.subject
    ]
    if active_admins and len(active_for_actor) != len(active_admins):
        raise FirstOmsAdministratorConflict("OMS first administrator is already initialized")

    await _ensure_bootstrap_roles_exist(connection)
    principal_id, policy_version = await _ensure_principal(connection, actor)
    assignment_ids: list[UUID] = []
    inserted = False
    current_policy = policy_version
    for role_key in _BOOTSTRAP_ROLES:
        existing = await _assignment_for_role(connection, principal_id, role_key)
        if existing is not None:
            assignment_ids.append(existing["id"])
            continue
        assignment_id, current_policy = await _insert_assignment(
            connection,
            actor=actor,
            principal_id=principal_id,
            role_key=role_key,
            command=command,
            expected_policy_version=current_policy,
        )
        assignment_ids.append(assignment_id)
        inserted = True

    return BootstrapFirstOmsAdministratorResult(
        principal_id=principal_id,
        assignment_ids=tuple(assignment_ids),
        role_keys=_BOOTSTRAP_ROLES,
        target_policy_version=current_policy,
        replayed=not inserted,
    )


__all__ = [
    "BootstrapFirstOmsAdministratorCommand",
    "BootstrapFirstOmsAdministratorResult",
    "FirstOmsAdministratorConflict",
    "bootstrap_first_oms_administrator",
]
