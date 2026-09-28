"""自定义管理角色的应用层、只追加版本发布服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from uuid import UUID

from psycopg.types.json import Jsonb

from .authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
    _column,
    _identity_is_current,
    require_management_delegation,
    require_management_permission,
)
from .value_validation import (
    ManagementValueError,
    validate_management_action_row,
    validate_management_audit_row,
)

_CUSTOM_ROLE_KEY = re.compile(r"^custom_[a-z0-9][a-z0-9_]{0,63}$")


class CustomRoleConflict(ValueError):
    """角色版本、不可变模板或幂等命令与当前事实冲突。"""


@dataclass(frozen=True, slots=True)
class PublishCustomRoleCommand:
    role_key: str
    scope_kind: str
    target_school_id: UUID | None
    action_keys: tuple[str, ...]
    expected_version: int
    command_id: UUID
    reason: str
    request_id: str


@dataclass(frozen=True, slots=True)
class PublishedCustomRole:
    role_key: str
    version: int
    scope_kind: str
    action_keys: tuple[str, ...]
    replayed: bool


def _validate_command(actor: ManagementIdentity, command: PublishCustomRoleCommand) -> None:
    if not isinstance(actor, ManagementIdentity) or not _identity_is_current(actor, write=True):
        raise ManagementAuthorizationDenied("external management identity is unavailable")
    if (
        not isinstance(command, PublishCustomRoleCommand)
        or not isinstance(command.role_key, str)
        or not _CUSTOM_ROLE_KEY.fullmatch(command.role_key)
        or command.scope_kind not in {"platform", "school"}
        or (command.target_school_id is not None and not isinstance(command.target_school_id, UUID))
        or not isinstance(command.action_keys, tuple)
        or not 1 <= len(command.action_keys) <= 64
        or any(not isinstance(key, str) or not 1 <= len(key) <= 128 for key in command.action_keys)
        or len(command.action_keys) != len(set(command.action_keys))
        or type(command.expected_version) is not int
        or command.expected_version < 0
        or not isinstance(command.command_id, UUID)
        or not isinstance(command.reason, str)
        or not 1 <= len(command.reason.strip()) <= 1000
        or not isinstance(command.request_id, str)
        or not 1 <= len(command.request_id.strip()) <= 128
    ):
        raise ManagementAuthorizationDenied("custom role command is invalid")
    if (command.scope_kind == "platform") != (command.target_school_id is None):
        raise ManagementAuthorizationDenied("custom role scope and school differ")
    if actor.application == "tms" and (
        command.scope_kind != "school" or actor.school_id != command.target_school_id
    ):
        raise ManagementAuthorizationDenied("custom role school differs from trusted session")
    prefix = "ops." if actor.application == "oms" else "tenant."
    if any(not key.startswith(prefix) for key in command.action_keys):
        raise ManagementAuthorizationDenied("custom role application action differs")


async def publish_custom_role(
    connection, actor: ManagementIdentity, command: PublishCustomRoleCommand
) -> PublishedCustomRole:
    """在调用方写事务中 CAS 追加角色版本；不自动迁移既有 assignment。"""

    _validate_command(actor, command)
    owner_school_id = command.target_school_id if actor.application == "tms" else None
    role_key = (
        f"custom_{owner_school_id.hex}_{command.role_key.removeprefix('custom_')}"
        if owner_school_id is not None
        else command.role_key
    )
    action_keys = tuple(sorted(command.action_keys))
    governance_action = (
        "ops.permissions.manage" if actor.application == "oms" else "tenant.permissions.manage"
    )
    governance = await require_management_permission(
        connection,
        actor,
        governance_action,
        target_school_id=command.target_school_id if actor.application == "tms" else None,
        write=True,
        _lock_school_id=command.target_school_id if actor.application == "oms" else None,
    )
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"management-custom-role:{actor.application}:{role_key}",),
    )
    previous = await (
        await connection.execute(
            "SELECT application,school_id,actor_issuer,actor_subject,action_key,"
            "target_kind,target_id,request_id,result,reason,before_version,after_version,"
            "safe_summary FROM management.audit_events WHERE id=%s",
            (command.command_id,),
        )
    ).fetchone()
    if previous:
        try:
            validate_management_audit_row(
                {
                    "application": _column(previous, "application", 0),
                    "school_id": _column(previous, "school_id", 1),
                    "actor_issuer": _column(previous, "actor_issuer", 2),
                    "actor_subject": _column(previous, "actor_subject", 3),
                    "action_key": _column(previous, "action_key", 4),
                    "target_kind": _column(previous, "target_kind", 5),
                    "target_id": _column(previous, "target_id", 6),
                    "request_id": _column(previous, "request_id", 7),
                    "result": _column(previous, "result", 8),
                    "reason": _column(previous, "reason", 9),
                    "before_version": _column(previous, "before_version", 10),
                    "after_version": _column(previous, "after_version", 11),
                    "safe_summary": _column(previous, "safe_summary", 12),
                }
            )
        except ManagementValueError:
            raise CustomRoleConflict("custom role audit fact is invalid") from None
        expected = (
            actor.application,
            command.target_school_id,
            actor.issuer,
            actor.subject,
            governance_action,
            "role_version",
            f"{role_key}:{command.expected_version + 1}",
            command.request_id,
            "success",
            command.reason,
            command.expected_version,
            command.expected_version + 1,
        )
        actual = tuple(
            _column(previous, key, index)
            for index, key in enumerate(
                (
                    "application",
                    "school_id",
                    "actor_issuer",
                    "actor_subject",
                    "action_key",
                    "target_kind",
                    "target_id",
                    "request_id",
                    "result",
                    "reason",
                    "before_version",
                    "after_version",
                )
            )
        )
        summary = _column(previous, "safe_summary", 12)
        if actual != expected or summary != {
            "role_key": command.role_key,
            "physical_role_key": role_key,
            "owner_school_id": str(owner_school_id) if owner_school_id else None,
            "scope_kind": command.scope_kind,
            "action_keys": list(action_keys),
        }:
            raise CustomRoleConflict("custom role idempotency key has different facts")
        stored = await (
            await connection.execute(
                "SELECT version,scope_kind,is_template,owner_school_id "
                "FROM management.role_versions "
                "WHERE application=%s AND role_key=%s AND version=%s",
                (actor.application, role_key, command.expected_version + 1),
            )
        ).fetchone()
        actions = await (
            await connection.execute(
                "SELECT action_key,owner_school_id FROM management.role_actions WHERE application=%s "
                "AND role_key=%s AND role_version=%s ORDER BY action_key",
                (actor.application, role_key, command.expected_version + 1),
            )
        ).fetchall()
        if (
            not stored
            or _column(stored, "scope_kind", 1) != command.scope_kind
            or _column(stored, "is_template", 2)
            or _column(stored, "owner_school_id", 3) != owner_school_id
            or tuple(_column(row, "action_key", 0) for row in actions) != action_keys
            or any(_column(row, "owner_school_id", 1) != owner_school_id for row in actions)
        ):
            raise CustomRoleConflict("custom role replay facts have drifted")
        return PublishedCustomRole(
            role_key, command.expected_version + 1, command.scope_kind, action_keys, True
        )

    latest = await (
        await connection.execute(
            "SELECT version,scope_kind,is_template,owner_school_id "
            "FROM management.role_versions "
            "WHERE application=%s AND role_key=%s ORDER BY version DESC LIMIT 1 FOR SHARE",
            (actor.application, role_key),
        )
    ).fetchone()
    if latest and _column(latest, "is_template", 2):
        raise CustomRoleConflict("template roles cannot be changed online")
    if (latest is None and command.expected_version != 0) or (
        latest is not None and _column(latest, "version", 0) != command.expected_version
    ):
        raise CustomRoleConflict("custom role expected version changed")
    if latest and _column(latest, "scope_kind", 1) != command.scope_kind:
        raise CustomRoleConflict("custom role scope cannot change")
    if latest and _column(latest, "owner_school_id", 3) != owner_school_id:
        raise CustomRoleConflict("custom role school owner cannot change")

    for action_key in action_keys:
        row = await (
            await connection.execute(
                "SELECT allowed_scope,status,sensitive FROM management.action_catalog "
                "WHERE application=%s AND action_key=%s FOR SHARE",
                (actor.application, action_key),
            )
        ).fetchone()
        if not row:
            raise ManagementAuthorizationDenied("custom role action is unregistered or retired")
        allowed_scope = _column(row, "allowed_scope", 0)
        try:
            validate_management_action_row(
                {
                    "application": actor.application,
                    "action_key": action_key,
                    "allowed_scope": allowed_scope,
                    "status": _column(row, "status", 1),
                    "sensitive": _column(row, "sensitive", 2),
                }
            )
        except ManagementValueError:
            raise ManagementAuthorizationDenied("custom role action catalog fact is invalid") from None
        if _column(row, "status", 1) != "active":
            raise ManagementAuthorizationDenied("custom role action is unregistered or retired")
        if allowed_scope not in {command.scope_kind, "both"}:
            raise ManagementAuthorizationDenied("custom role action scope is invalid")
        if _column(row, "sensitive", 2):
            raise ManagementAuthorizationDenied(
                "sensitive custom role requires independent approval"
            )
        # 创建角色不会授予动作，但创建者仍须具备当前可委托上界。
        # 敏感动作在后续 assignment 授予时仍须独立审批，不能借角色发布绕过。
        await require_management_delegation(
            connection,
            actor,
            action_key,
            target_school_id=command.target_school_id,
            grant_expires_at=datetime.now(timezone.utc) + timedelta(seconds=1),
        )

    next_version = command.expected_version + 1
    await connection.execute(
        "INSERT INTO management.role_versions"
        "(application,role_key,version,scope_kind,is_template,owner_school_id) "
        "VALUES(%s,%s,%s,%s,false,%s)",
        (actor.application, role_key, next_version, command.scope_kind, owner_school_id),
    )
    for action_key in action_keys:
        await connection.execute(
            "INSERT INTO management.role_actions"
            "(application,role_key,role_version,action_key,owner_school_id) "
            "VALUES(%s,%s,%s,%s,%s)",
            (actor.application, role_key, next_version, action_key, owner_school_id),
        )
    await connection.execute(
        "INSERT INTO management.audit_events"
        "(id,application,school_id,actor_issuer,actor_subject,action_key,target_kind,"
        "target_id,request_id,result,reason,before_version,after_version,safe_summary) "
        "VALUES(%s,%s,%s,%s,%s,%s,'role_version',%s,%s,'success',%s,%s,%s,%s)",
        (
            command.command_id,
            actor.application,
            command.target_school_id,
            actor.issuer,
            actor.subject,
            governance_action,
            f"{role_key}:{next_version}",
            command.request_id,
            command.reason,
            command.expected_version,
            next_version,
            Jsonb(
                {
                    "role_key": command.role_key,
                    "physical_role_key": role_key,
                    "owner_school_id": str(owner_school_id) if owner_school_id else None,
                    "scope_kind": command.scope_kind,
                    "action_keys": list(action_keys),
                }
            ),
        ),
    )
    return PublishedCustomRole(role_key, next_version, command.scope_kind, action_keys, False)
