"""管理敏感操作的双人审批服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from deeptutor_enterprise.management.authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
    _column,
    _identity_is_current,
    require_management_permission,
)
from deeptutor_enterprise.management.value_validation import (
    ManagementValueError,
    validate_management_approval_row,
)


class ApprovalConflict(ValueError):
    """审批请求的幂等、版本或终态冲突。"""


@dataclass(frozen=True)
class CreateApprovalRequestCommand:
    operation: str
    target_principal_id: UUID
    target_school_id: UUID | None
    expected_target_policy_version: int
    expires_at: datetime
    idempotency_key: str
    reason: str
    request_id: str
    external_qualification_ref: str
    external_qualification_version: str
    target_role_key: str | None = None
    target_role_version: int | None = None
    target_action_keys: tuple[str, ...] = ()
    target_expires_at: datetime | None = None
    confirmed_role_version: int | None = None


@dataclass(frozen=True)
class ApprovalRequestResult:
    approval_id: UUID
    status: str
    replayed: bool


@dataclass(frozen=True)
class ReviewApprovalCommand:
    approval_id: UUID
    decision: str
    expected_target_policy_version: int
    reason: str
    request_id: str


@dataclass(frozen=True)
class ApprovalReviewResult:
    approval_id: UUID
    status: str
    replayed: bool


@dataclass(frozen=True)
class WithdrawApprovalCommand:
    approval_id: UUID
    reason: str
    request_id: str


@dataclass(frozen=True)
class ApprovalWithdrawResult:
    approval_id: UUID
    status: str
    replayed: bool


@dataclass(frozen=True)
class ApplyApprovalCommand:
    approval_id: UUID
    expected_target_policy_version: int
    command_id: UUID
    reason: str
    request_id: str


@dataclass(frozen=True)
class ApprovalApplyResult:
    approval_id: UUID
    assignment_id: UUID | None
    role_key: str
    target_policy_version: int
    replayed: bool
    applied_kind: str = "assignment"
    delegation_ids: tuple[UUID, ...] = ()


def _governance_action(application: str) -> str:
    return "ops.permissions.manage" if application == "oms" else "tenant.permissions.manage"


def _validate_text(value: object, *, max_len: int = 1000) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= max_len


def _validate_create_command(command: CreateApprovalRequestCommand) -> None:
    role_payload_empty = (
        command.target_role_key is None
        and command.target_role_version is None
        and command.confirmed_role_version is None
    )
    action_payload_empty = not command.target_action_keys
    if (
        not isinstance(command, CreateApprovalRequestCommand)
        or command.operation not in {"platform_grant", "delegation_expand", "school_activation"}
        or not isinstance(command.target_principal_id, UUID)
        or (
            command.target_school_id is not None
            and not isinstance(command.target_school_id, UUID)
        )
        or type(command.expected_target_policy_version) is not int
        or command.expected_target_policy_version < 1
        or not isinstance(command.expires_at, datetime)
        or command.expires_at.tzinfo is None
        or command.expires_at <= datetime.now(timezone.utc)
        or not _validate_text(command.idempotency_key, max_len=128)
        or not _validate_text(command.reason)
        or not _validate_text(command.request_id, max_len=128)
        or not _validate_text(command.external_qualification_ref)
        or not _validate_text(command.external_qualification_version, max_len=256)
        or (
            command.target_role_key is not None
            and (
                not _validate_text(command.target_role_key, max_len=128)
                or command.target_role_key.startswith(("ops.", "tenant."))
            )
        )
        or (
            command.target_role_version is not None
            and (type(command.target_role_version) is not int or command.target_role_version < 1)
        )
        or (
            command.confirmed_role_version is not None
            and (
                type(command.confirmed_role_version) is not int
                or command.confirmed_role_version < 1
                or command.confirmed_role_version != command.target_role_version
            )
        )
        or not isinstance(command.target_action_keys, tuple)
        or len(command.target_action_keys) != len(set(command.target_action_keys))
        or any(not _validate_text(key, max_len=128) for key in command.target_action_keys)
        or (
            command.target_expires_at is not None
            and (
                not isinstance(command.target_expires_at, datetime)
                or command.target_expires_at.tzinfo is None
                or command.target_expires_at <= datetime.now(timezone.utc)
                or command.target_expires_at > command.expires_at
            )
        )
        or (
            command.operation == "platform_grant"
            and (
                action_payload_empty is False
                or (
                    not role_payload_empty
                    and (
                        command.target_role_key is None
                        or command.target_role_version is None
                        or command.confirmed_role_version is None
                        or command.target_expires_at is None
                    )
                )
            )
        )
        or (
            command.operation == "delegation_expand"
            and (
                role_payload_empty is False
                or (
                    not action_payload_empty
                    and (
                        command.target_expires_at is None
                        or any(not key.startswith("ops.") for key in command.target_action_keys)
                    )
                )
            )
        )
        or (
            command.operation == "school_activation"
            and (
                not action_payload_empty
                or (
                    not role_payload_empty
                    and (
                        command.target_role_key != "school_admin"
                        or command.target_role_version != 1
                        or command.confirmed_role_version != 1
                    )
                )
            )
        )
    ):
        raise ManagementAuthorizationDenied("approval command is invalid")


def _validate_review_command(command: ReviewApprovalCommand) -> None:
    if (
        not isinstance(command, ReviewApprovalCommand)
        or not isinstance(command.approval_id, UUID)
        or command.decision not in {"approved", "rejected"}
        or type(command.expected_target_policy_version) is not int
        or command.expected_target_policy_version < 1
        or not _validate_text(command.reason)
        or not _validate_text(command.request_id, max_len=128)
    ):
        raise ManagementAuthorizationDenied("approval review command is invalid")


def _validate_withdraw_command(command: WithdrawApprovalCommand) -> None:
    if (
        not isinstance(command, WithdrawApprovalCommand)
        or not isinstance(command.approval_id, UUID)
        or not _validate_text(command.reason)
        or not _validate_text(command.request_id, max_len=128)
    ):
        raise ManagementAuthorizationDenied("approval withdraw command is invalid")


def _validate_apply_command(command: ApplyApprovalCommand) -> None:
    if (
        not isinstance(command, ApplyApprovalCommand)
        or not isinstance(command.approval_id, UUID)
        or type(command.expected_target_policy_version) is not int
        or command.expected_target_policy_version < 1
        or not isinstance(command.command_id, UUID)
        or not _validate_text(command.reason)
        or not _validate_text(command.request_id, max_len=128)
    ):
        raise ManagementAuthorizationDenied("approval apply command is invalid")


def _assert_identity(identity: ManagementIdentity, *, write: bool = True) -> None:
    if not isinstance(identity, ManagementIdentity) or not _identity_is_current(identity, write=write):
        raise ManagementAuthorizationDenied("external management identity is unavailable")


def _assert_operation_scope(identity: ManagementIdentity, operation: str, school_id: UUID | None) -> None:
    if identity.application == "oms":
        if operation == "school_activation" or school_id is not None:
            raise ManagementAuthorizationDenied("approval operation differs from application")
    elif identity.application == "tms":
        if operation != "school_activation" or school_id != identity.school_id:
            raise ManagementAuthorizationDenied("approval school differs from trusted session")
    else:
        raise ManagementAuthorizationDenied("approval application is invalid")


async def _lock_target_principal(
    connection,
    *,
    application: str,
    principal_id: UUID,
    school_id: UUID | None,
):
    row = await (
        await connection.execute(
            "SELECT id,status,policy_version,school_id FROM management.principals "
            "WHERE id=%s AND application=%s AND school_id IS NOT DISTINCT FROM %s "
            "FOR UPDATE",
            (principal_id, application, school_id),
        )
    ).fetchone()
    if row is None:
        raise ManagementAuthorizationDenied("approval target principal is unavailable")
    status = _column(row, "status", 1)
    if status not in {"pending", "active"}:
        raise ManagementAuthorizationDenied("approval target principal is unavailable")
    return row


async def _audit(
    connection,
    *,
    application: str,
    school_id: UUID | None,
    actor: ManagementIdentity,
    target_id: UUID,
    request_id: str,
    result: str,
    reason: str,
    before_version: int | None = None,
    after_version: int | None = None,
    safe_summary: dict[str, object] | None = None,
) -> None:
    await connection.execute(
        "INSERT INTO management.audit_events"
        "(id,application,school_id,actor_issuer,actor_subject,action_key,target_kind,"
        "target_id,request_id,result,reason,before_version,after_version,approval_id,safe_summary) "
        "VALUES(%s,%s,%s,%s,%s,%s,'approval_request',%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            uuid4(),
            application,
            school_id,
            actor.issuer,
            actor.subject,
            _governance_action(application),
            str(target_id),
            request_id,
            result,
            reason,
            before_version,
            after_version,
            target_id,
            Jsonb(safe_summary or {}),
        ),
    )


def _approval_fact_from_create(
    *,
    approval_id: UUID,
    identity: ManagementIdentity,
    command: CreateApprovalRequestCommand,
    status: str,
    reviewer_issuer: str | None = None,
    reviewer_subject: str | None = None,
    decided_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "id": approval_id,
        "application": identity.application,
        "operation": command.operation,
        "target_principal_id": command.target_principal_id,
        "school_id": command.target_school_id,
        "proposer_issuer": identity.issuer,
        "proposer_subject": identity.subject,
        "reviewer_issuer": reviewer_issuer,
        "reviewer_subject": reviewer_subject,
        "expected_policy_version": command.expected_target_policy_version,
        "status": status,
        "expires_at": command.expires_at,
        "decided_at": decided_at,
    }


async def create_management_approval_request(
    connection,
    actor: ManagementIdentity,
    command: CreateApprovalRequestCommand,
) -> ApprovalRequestResult:
    """创建敏感操作审批请求；同一 proposer/idempotency_key 精确幂等。"""

    _assert_identity(actor)
    _validate_create_command(command)
    _assert_operation_scope(actor, command.operation, command.target_school_id)
    await require_management_permission(
        connection,
        actor,
        _governance_action(actor.application),
        target_school_id=actor.school_id if actor.application == "tms" else None,
        write=True,
    )
    principal = await _lock_target_principal(
        connection,
        application=actor.application,
        principal_id=command.target_principal_id,
        school_id=command.target_school_id if actor.application == "tms" else None,
    )
    if _column(principal, "policy_version", 2) != command.expected_target_policy_version:
        raise ApprovalConflict("target policy version changed")

    existing = await (
        await connection.execute(
            "SELECT id,operation,target_principal_id,school_id,expected_policy_version,"
            "expires_at,reason,request_id,external_qualification_ref,"
            "external_qualification_version,target_role_key,target_role_version,"
            "target_action_keys,target_expires_at,confirmed_role_version,status "
            "FROM management.approval_requests "
            "WHERE application=%s AND proposer_issuer=%s AND proposer_subject=%s "
            "AND idempotency_key=%s FOR SHARE",
            (actor.application, actor.issuer, actor.subject, command.idempotency_key),
        )
    ).fetchone()
    if existing is not None:
        if (
            _column(existing, "operation", 1),
            _column(existing, "target_principal_id", 2),
            _column(existing, "school_id", 3),
            _column(existing, "expected_policy_version", 4),
            _column(existing, "expires_at", 5),
            _column(existing, "reason", 6),
            _column(existing, "request_id", 7),
            _column(existing, "external_qualification_ref", 8),
            _column(existing, "external_qualification_version", 9),
            _column(existing, "target_role_key", 10),
            _column(existing, "target_role_version", 11),
            tuple(_column(existing, "target_action_keys", 12) or ()),
            _column(existing, "target_expires_at", 13),
            _column(existing, "confirmed_role_version", 14),
        ) != (
            command.operation,
            command.target_principal_id,
            command.target_school_id,
            command.expected_target_policy_version,
            command.expires_at,
            command.reason,
            command.request_id,
            command.external_qualification_ref,
            command.external_qualification_version,
            command.target_role_key,
            command.target_role_version,
            command.target_action_keys,
            command.target_expires_at,
            command.confirmed_role_version,
        ):
            raise ApprovalConflict("idempotency key was used for another approval")
        return ApprovalRequestResult(_column(existing, "id", 0), _column(existing, "status", 15), True)

    approval_id = uuid4()
    fact = _approval_fact_from_create(
        approval_id=approval_id, identity=actor, command=command, status="pending"
    )
    try:
        validate_management_approval_row(fact)
    except ManagementValueError as exc:
        raise ManagementAuthorizationDenied("approval fact is invalid") from exc
    try:
        await connection.execute(
            "INSERT INTO management.approval_requests"
            "(id,application,operation,target_principal_id,school_id,proposer_issuer,"
            "proposer_subject,external_qualification_ref,external_qualification_version,"
            "expected_policy_version,status,expires_at,idempotency_key,reason,request_id,"
            "target_role_key,target_role_version,target_action_keys,target_expires_at,"
            "confirmed_role_version) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                approval_id,
                actor.application,
                command.operation,
                command.target_principal_id,
                command.target_school_id,
                actor.issuer,
                actor.subject,
                command.external_qualification_ref,
                command.external_qualification_version,
                command.expected_target_policy_version,
                command.expires_at,
                command.idempotency_key,
                command.reason,
                command.request_id,
                command.target_role_key,
                command.target_role_version,
                list(command.target_action_keys),
                command.target_expires_at,
                command.confirmed_role_version,
            ),
        )
    except UniqueViolation as exc:
        raise ApprovalConflict("approval request conflicts with an existing pending request") from exc
    await _audit(
        connection,
        application=actor.application,
        school_id=command.target_school_id,
        actor=actor,
        target_id=approval_id,
        request_id=command.request_id,
        result="success",
        reason=command.reason,
        before_version=command.expected_target_policy_version,
        after_version=command.expected_target_policy_version,
        safe_summary={"operation": command.operation, "status": "pending"},
    )
    return ApprovalRequestResult(approval_id, "pending", False)


async def _load_approval_for_update(connection, approval_id: UUID):
    row = await (
        await connection.execute(
            "SELECT id,application,operation,target_principal_id,school_id,"
            "proposer_issuer,proposer_subject,reviewer_issuer,reviewer_subject,"
            "expected_policy_version,status,expires_at,decided_at,"
            "target_role_key,target_role_version,target_action_keys,target_expires_at,"
            "confirmed_role_version "
            "FROM management.approval_requests WHERE id=%s FOR UPDATE",
            (approval_id,),
        )
    ).fetchone()
    if row is None:
        raise ApprovalConflict("approval request is unavailable")
    return row


def _validate_loaded_approval(row) -> None:
    try:
        validate_management_approval_row(
            {
                "id": _column(row, "id", 0),
                "application": _column(row, "application", 1),
                "operation": _column(row, "operation", 2),
                "target_principal_id": _column(row, "target_principal_id", 3),
                "school_id": _column(row, "school_id", 4),
                "proposer_issuer": _column(row, "proposer_issuer", 5),
                "proposer_subject": _column(row, "proposer_subject", 6),
                "reviewer_issuer": _column(row, "reviewer_issuer", 7),
                "reviewer_subject": _column(row, "reviewer_subject", 8),
                "expected_policy_version": _column(row, "expected_policy_version", 9),
                "status": _column(row, "status", 10),
                "expires_at": _column(row, "expires_at", 11),
                "decided_at": _column(row, "decided_at", 12),
            }
        )
    except ManagementValueError as exc:
        raise ApprovalConflict("approval fact is invalid") from exc


async def review_management_approval(
    connection,
    reviewer: ManagementIdentity,
    command: ReviewApprovalCommand,
) -> ApprovalReviewResult:
    """独立复核人批准或拒绝审批请求，目标版本漂移时失败关闭。"""

    _assert_identity(reviewer)
    _validate_review_command(command)
    await connection.execute(
        "SELECT set_config('app.management_app',%s,true)", (reviewer.application,)
    )
    row = await _load_approval_for_update(connection, command.approval_id)
    _validate_loaded_approval(row)
    application = _column(row, "application", 1)
    operation = _column(row, "operation", 2)
    school_id = _column(row, "school_id", 4)
    if reviewer.application != application:
        raise ManagementAuthorizationDenied("approval application differs from reviewer")
    _assert_operation_scope(reviewer, operation, school_id)
    await require_management_permission(
        connection,
        reviewer,
        _governance_action(application),
        target_school_id=reviewer.school_id if application == "tms" else None,
        write=True,
    )
    status = _column(row, "status", 10)
    existing_reviewer = (_column(row, "reviewer_issuer", 7), _column(row, "reviewer_subject", 8))
    if status in {"approved", "rejected"}:
        if status == command.decision and existing_reviewer == (reviewer.issuer, reviewer.subject):
            return ApprovalReviewResult(command.approval_id, status, True)
        raise ApprovalConflict("approval request is already terminal")
    if status in {"withdrawn", "expired", "failed"}:
        raise ApprovalConflict("approval request is already terminal")
    if datetime.now(timezone.utc) >= _column(row, "expires_at", 11):
        await connection.execute(
            "UPDATE management.approval_requests SET status='expired',decided_at=now() WHERE id=%s",
            (command.approval_id,),
        )
        raise ApprovalConflict("approval request expired")
    if (reviewer.issuer, reviewer.subject) == (
        _column(row, "proposer_issuer", 5),
        _column(row, "proposer_subject", 6),
    ):
        raise ApprovalConflict("approval requires an independent reviewer")
    expected = _column(row, "expected_policy_version", 9)
    if command.expected_target_policy_version != expected:
        raise ApprovalConflict("target policy version changed")
    target = await _lock_target_principal(
        connection,
        application=application,
        principal_id=_column(row, "target_principal_id", 3),
        school_id=school_id if application == "tms" else None,
    )
    if _column(target, "policy_version", 2) != expected:
        raise ApprovalConflict("target policy version changed")
    decided_at = datetime.now(timezone.utc)
    fact = {
        "id": command.approval_id,
        "application": application,
        "operation": operation,
        "target_principal_id": _column(row, "target_principal_id", 3),
        "school_id": school_id,
        "proposer_issuer": _column(row, "proposer_issuer", 5),
        "proposer_subject": _column(row, "proposer_subject", 6),
        "reviewer_issuer": reviewer.issuer,
        "reviewer_subject": reviewer.subject,
        "expected_policy_version": expected,
        "status": command.decision,
        "expires_at": _column(row, "expires_at", 11),
        "decided_at": decided_at,
    }
    try:
        validate_management_approval_row(fact)
    except ManagementValueError as exc:
        raise ApprovalConflict("approval fact is invalid") from exc
    await connection.execute(
        "UPDATE management.approval_requests SET status=%s,reviewer_issuer=%s,"
        "reviewer_subject=%s,decided_at=%s WHERE id=%s AND status='pending'",
        (command.decision, reviewer.issuer, reviewer.subject, decided_at, command.approval_id),
    )
    await _audit(
        connection,
        application=application,
        school_id=school_id,
        actor=reviewer,
        target_id=command.approval_id,
        request_id=command.request_id,
        result="success",
        reason=command.reason,
        before_version=expected,
        after_version=expected,
        safe_summary={"operation": operation, "status": command.decision},
    )
    return ApprovalReviewResult(command.approval_id, command.decision, False)


async def withdraw_management_approval(
    connection,
    actor: ManagementIdentity,
    command: WithdrawApprovalCommand,
) -> ApprovalWithdrawResult:
    """提议人撤回仍处于 pending 的审批请求。"""

    _assert_identity(actor)
    _validate_withdraw_command(command)
    await connection.execute(
        "SELECT set_config('app.management_app',%s,true)", (actor.application,)
    )
    row = await _load_approval_for_update(connection, command.approval_id)
    _validate_loaded_approval(row)
    application = _column(row, "application", 1)
    operation = _column(row, "operation", 2)
    school_id = _column(row, "school_id", 4)
    if actor.application != application or (actor.issuer, actor.subject) != (
        _column(row, "proposer_issuer", 5),
        _column(row, "proposer_subject", 6),
    ):
        raise ManagementAuthorizationDenied("only the proposer can withdraw approval")
    _assert_operation_scope(actor, operation, school_id)
    await require_management_permission(
        connection,
        actor,
        _governance_action(application),
        target_school_id=actor.school_id if application == "tms" else None,
        write=True,
    )
    status = _column(row, "status", 10)
    if status == "withdrawn":
        return ApprovalWithdrawResult(command.approval_id, "withdrawn", True)
    if status != "pending":
        raise ApprovalConflict("approval request is already terminal")
    await connection.execute(
        "UPDATE management.approval_requests SET status='withdrawn',decided_at=now() WHERE id=%s",
        (command.approval_id,),
    )
    expected = _column(row, "expected_policy_version", 9)
    await _audit(
        connection,
        application=application,
        school_id=school_id,
        actor=actor,
        target_id=command.approval_id,
        request_id=command.request_id,
        result="success",
        reason=command.reason,
        before_version=expected,
        after_version=expected,
        safe_summary={"operation": operation, "status": "withdrawn"},
    )
    return ApprovalWithdrawResult(command.approval_id, "withdrawn", False)


def _approval_payload(row) -> dict[str, object]:
    return {
        "target_role_key": _column(row, "target_role_key", 13),
        "target_role_version": _column(row, "target_role_version", 14),
        "target_action_keys": tuple(_column(row, "target_action_keys", 15) or ()),
        "target_expires_at": _column(row, "target_expires_at", 16),
        "confirmed_role_version": _column(row, "confirmed_role_version", 17),
    }


def _assert_approved_for_apply(
    row, actor: ManagementIdentity, command: ApplyApprovalCommand
) -> tuple[str, str, UUID | None, UUID, int]:
    application = _column(row, "application", 1)
    operation = _column(row, "operation", 2)
    school_id = _column(row, "school_id", 4)
    target_principal_id = _column(row, "target_principal_id", 3)
    if actor.application != application:
        raise ManagementAuthorizationDenied("approval application differs from actor")
    _assert_operation_scope(actor, operation, school_id)
    status = _column(row, "status", 10)
    if status != "approved":
        raise ApprovalConflict("approval request is not approved")
    expected = _column(row, "expected_policy_version", 9)
    if command.expected_target_policy_version != expected:
        raise ApprovalConflict("target policy version changed")
    return application, operation, school_id, target_principal_id, expected


async def _insert_apply_audit(
    connection,
    *,
    audit_id: UUID,
    application: str,
    school_id: UUID | None,
    actor: ManagementIdentity,
    action_key: str,
    target_kind: str,
    target_id: str,
    request_id: str,
    reason: str,
    before_version: int,
    after_version: int,
    approval_id: UUID,
    safe_summary: dict[str, object],
) -> None:
    await connection.execute(
        "INSERT INTO management.audit_events"
        "(id,application,school_id,actor_issuer,actor_subject,action_key,target_kind,"
        "target_id,request_id,result,reason,before_version,after_version,approval_id,safe_summary) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'success',%s,%s,%s,%s,%s)",
        (
            audit_id,
            application,
            school_id,
            actor.issuer,
            actor.subject,
            action_key,
            target_kind,
            target_id,
            request_id,
            reason,
            before_version,
            after_version,
            approval_id,
            Jsonb(safe_summary),
        ),
    )


async def _apply_approved_platform_grant(
    connection,
    actor: ManagementIdentity,
    command: ApplyApprovalCommand,
    row,
) -> ApprovalApplyResult:
    from .assignment_rules import validate_assignment_relation
    from .grants import validate_role_action_owner_for_grant, validate_role_owner_for_grant
    from .policy_version import advance_principal_policy_version
    from .authorization import require_management_delegation

    application, operation, school_id, target_principal_id, expected = _assert_approved_for_apply(
        row, actor, command
    )
    if application != "oms" or operation != "platform_grant" or school_id is not None:
        raise ManagementAuthorizationDenied("approval operation is not applicable")
    payload = _approval_payload(row)
    role_key = payload["target_role_key"]
    role_version = payload["target_role_version"]
    target_expires_at = payload["target_expires_at"]
    confirmed_role_version = payload["confirmed_role_version"]
    if (
        not isinstance(role_key, str)
        or type(role_version) is not int
        or confirmed_role_version != role_version
        or not isinstance(target_expires_at, datetime)
        or target_expires_at.tzinfo is None
        or target_expires_at <= datetime.now(timezone.utc)
    ):
        raise ApprovalConflict("approval apply payload is unavailable")
    governance = await require_management_permission(
        connection, actor, _governance_action(application), write=True
    )
    replay = await (
        await connection.execute(
            "SELECT id,principal_id,role_key,role_version,scope_kind,school_id,status "
            "FROM management.assignments WHERE application='oms' AND command_id=%s "
            "FOR SHARE",
            (command.command_id,),
        )
    ).fetchone()
    if replay is not None:
        if (
            _column(replay, "principal_id", 1) != target_principal_id
            or _column(replay, "role_key", 2) != role_key
            or _column(replay, "role_version", 3) != role_version
            or _column(replay, "scope_kind", 4) != "platform"
            or _column(replay, "school_id", 5) is not None
            or _column(replay, "status", 6) != "active"
        ):
            raise ApprovalConflict("idempotency key was used for another assignment")
        target = await _lock_target_principal(
            connection,
            application="oms",
            principal_id=target_principal_id,
            school_id=None,
        )
        return ApprovalApplyResult(
            command.approval_id,
            _column(replay, "id", 0),
            role_key,
            _column(target, "policy_version", 2),
            True,
        )

    target = await _lock_target_principal(
        connection,
        application="oms",
        principal_id=target_principal_id,
        school_id=None,
    )
    if _column(target, "policy_version", 2) != expected:
        raise ApprovalConflict("target policy version changed")
    role = await (
        await connection.execute(
            "SELECT scope_kind,is_template,owner_school_id FROM management.role_versions "
            "WHERE application='oms' AND role_key=%s AND version=%s FOR SHARE",
            (role_key, role_version),
        )
    ).fetchone()
    validate_role_owner_for_grant(role, application="oms", target_school_id=None)
    if _column(role, "is_template", 1) is True and confirmed_role_version != role_version:
        raise ManagementAuthorizationDenied("role template version confirmation is required")
    actions = await (
        await connection.execute(
            "SELECT ra.action_key,ac.status,ac.sensitive,ra.owner_school_id "
            "FROM management.role_actions ra "
            "JOIN management.action_catalog ac ON ac.application=ra.application "
            "AND ac.action_key=ra.action_key "
            "WHERE ra.application='oms' AND ra.role_key=%s AND ra.role_version=%s "
            "ORDER BY ra.action_key FOR SHARE OF ra,ac",
            (role_key, role_version),
        )
    ).fetchall()
    validate_role_action_owner_for_grant(actions, owner_school_id=_column(role, "owner_school_id", 2))
    if not actions or any(_column(action, "status", 1) != "active" for action in actions):
        raise ManagementAuthorizationDenied("role has no active action set")
    for action in actions:
        action_key = _column(action, "action_key", 0)
        await require_management_delegation(
            connection,
            actor,
            action_key,
            target_school_id=None,
            grant_expires_at=target_expires_at,
        )
    validate_assignment_relation(
        application="oms",
        principal_application="oms",
        principal_school_id=_column(target, "school_id", 3),
        role_application="oms",
        role_scope_kind=_column(role, "scope_kind", 0),
        assignment_scope_kind="platform",
        assignment_school_id=None,
    )
    existing = await (
        await connection.execute(
            "SELECT 1 FROM management.assignments WHERE application='oms' "
            "AND principal_id=%s AND role_key=%s AND scope_kind='platform' "
            "AND status='active' LIMIT 1",
            (target_principal_id, role_key),
        )
    ).fetchone()
    if existing:
        raise ApprovalConflict("target already has an active role assignment")
    if _column(target, "status", 1) == "pending":
        await connection.execute(
            "UPDATE management.principals SET status='active',updated_at=clock_timestamp() "
            "WHERE id=%s AND application='oms'",
            (target_principal_id,),
        )
    assignment_id = uuid4()
    await connection.execute(
        "INSERT INTO management.assignments(id,application,principal_id,role_key,"
        "role_version,scope_kind,school_id,school_binding_version,valid_from,expires_at,"
        "command_id,created_by) VALUES(%s,'oms',%s,%s,%s,'platform',NULL,NULL,"
        "clock_timestamp()-interval '1 second',%s,%s,%s)",
        (
            assignment_id,
            target_principal_id,
            role_key,
            role_version,
            target_expires_at,
            command.command_id,
            str(governance.principal_id),
        ),
    )
    next_policy_version = await advance_principal_policy_version(
        connection, target_principal_id, expected_before=expected
    )
    await _insert_apply_audit(
        connection,
        audit_id=uuid4(),
        application="oms",
        school_id=None,
        actor=actor,
        action_key=_governance_action(application),
        target_kind="approval_apply_assignment",
        target_id=str(assignment_id),
        request_id=command.request_id,
        reason=command.reason,
        before_version=expected,
        after_version=next_policy_version,
        approval_id=command.approval_id,
        safe_summary={
            "approval_id": str(command.approval_id),
            "operation": operation,
            "role_key": role_key,
            "role_version": role_version,
        },
    )
    return ApprovalApplyResult(
        command.approval_id, assignment_id, role_key, next_policy_version, False
    )


async def _apply_approved_delegation_expand(
    connection,
    actor: ManagementIdentity,
    command: ApplyApprovalCommand,
    row,
) -> ApprovalApplyResult:
    from .authorization import require_management_delegation
    from .delegation_rules import validate_delegation_relation
    from .policy_version import advance_principal_policy_version

    application, operation, school_id, target_principal_id, expected = _assert_approved_for_apply(
        row, actor, command
    )
    if application != "oms" or operation != "delegation_expand" or school_id is not None:
        raise ManagementAuthorizationDenied("approval operation is not applicable")
    payload = _approval_payload(row)
    action_keys = tuple(payload["target_action_keys"] or ())
    target_expires_at = payload["target_expires_at"]
    if (
        not action_keys
        or any(not isinstance(action, str) or not action.startswith("ops.") for action in action_keys)
        or not isinstance(target_expires_at, datetime)
        or target_expires_at.tzinfo is None
        or target_expires_at <= datetime.now(timezone.utc)
    ):
        raise ApprovalConflict("approval apply payload is unavailable")
    await require_management_permission(
        connection, actor, _governance_action(application), write=True
    )
    replay = await (
        await connection.execute(
            "SELECT id,target_id,after_version,safe_summary FROM management.audit_events "
            "WHERE id=%s AND application='oms' AND target_kind='approval_apply_delegation' "
            "FOR SHARE",
            (command.command_id,),
        )
    ).fetchone()
    if replay is not None:
        summary = _column(replay, "safe_summary", 3)
        ids = tuple(UUID(value) for value in summary.get("delegation_ids", ()))
        return ApprovalApplyResult(
            command.approval_id,
            None,
            "",
            _column(replay, "after_version", 2),
            True,
            "delegation",
            ids,
        )
    target = await _lock_target_principal(
        connection,
        application="oms",
        principal_id=target_principal_id,
        school_id=None,
    )
    if _column(target, "policy_version", 2) != expected:
        raise ApprovalConflict("target policy version changed")
    delegation_ids: list[UUID] = []
    for action_key in action_keys:
        await require_management_delegation(
            connection,
            actor,
            action_key,
            target_school_id=None,
            grant_expires_at=target_expires_at,
        )
        action = await (
            await connection.execute(
                "SELECT status,allowed_scope FROM management.action_catalog "
                "WHERE application='oms' AND action_key=%s FOR SHARE",
                (action_key,),
            )
        ).fetchone()
        try:
            validate_delegation_relation(
                application="oms",
                principal_application="oms",
                principal_school_id=None,
                action_application="oms" if action else None,
                action_status=_column(action, "status", 0) if action else None,
                action_allowed_scope=_column(action, "allowed_scope", 1) if action else None,
                delegation_scope_kind="platform",
                delegation_school_id=None,
            )
        except ManagementAuthorizationDenied as exc:
            raise ManagementAuthorizationDenied("delegation expansion target is invalid") from exc
        existing = await (
            await connection.execute(
                "SELECT id FROM management.delegation_policies WHERE application='oms' "
                "AND principal_id=%s AND action_key=%s AND scope_kind='platform' "
                "AND school_id IS NULL AND status='active' AND expires_at>now() LIMIT 1",
                (target_principal_id, action_key),
            )
        ).fetchone()
        if existing:
            raise ApprovalConflict("target already has an active delegation policy")
        delegation_id = uuid4()
        await connection.execute(
            "INSERT INTO management.delegation_policies"
            "(id,application,principal_id,action_key,scope_kind,school_id,valid_from,expires_at) "
            "VALUES(%s,'oms',%s,%s,'platform',NULL,clock_timestamp()-interval '1 second',%s)",
            (delegation_id, target_principal_id, action_key, target_expires_at),
        )
        delegation_ids.append(delegation_id)
    next_policy_version = await advance_principal_policy_version(
        connection, target_principal_id, expected_before=expected
    )
    await _insert_apply_audit(
        connection,
        audit_id=command.command_id,
        application="oms",
        school_id=None,
        actor=actor,
        action_key=_governance_action(application),
        target_kind="approval_apply_delegation",
        target_id=str(target_principal_id),
        request_id=command.request_id,
        reason=command.reason,
        before_version=expected,
        after_version=next_policy_version,
        approval_id=command.approval_id,
        safe_summary={
            "approval_id": str(command.approval_id),
            "operation": operation,
            "action_keys": list(action_keys),
            "delegation_ids": [str(item) for item in delegation_ids],
        },
    )
    return ApprovalApplyResult(
        command.approval_id,
        None,
        "",
        next_policy_version,
        False,
        "delegation",
        tuple(delegation_ids),
    )


async def apply_approved_management_approval(
    connection,
    actor: ManagementIdentity,
    command: ApplyApprovalCommand,
) -> ApprovalApplyResult:
    """应用已批准的管理审批请求。

    学校首管激活、平台敏感角色授予和委托上界扩展共用同一审批终态、
    目标 policy version、显式模板版本与命令幂等校验。
    """

    _assert_identity(actor)
    _validate_apply_command(command)
    await connection.execute(
        "SELECT set_config('app.management_app',%s,true)", (actor.application,)
    )
    row = await _load_approval_for_update(connection, command.approval_id)
    _validate_loaded_approval(row)
    operation = _column(row, "operation", 2)
    if operation == "school_activation":
        return await apply_approved_school_activation(connection, actor, command)
    if operation == "platform_grant":
        return await _apply_approved_platform_grant(connection, actor, command, row)
    if operation == "delegation_expand":
        return await _apply_approved_delegation_expand(connection, actor, command, row)
    raise ManagementAuthorizationDenied("approval operation is not applicable")


async def apply_approved_school_activation(
    connection,
    actor: ManagementIdentity,
    command: ApplyApprovalCommand,
) -> ApprovalApplyResult:
    """将已批准的学校高风险授权请求应用为 school_admin assignment。

    此函数只处理 DeepTutor 本地授权事实；不创建或修改外部账号。调用方
    必须在当前学校事务中执行并保持事务到提交。
    """

    from .assignment_rules import validate_assignment_relation
    from .policy_version import advance_principal_policy_version

    _assert_identity(actor)
    _validate_apply_command(command)
    await connection.execute("SELECT set_config('app.management_app','tms',true)")
    row = await _load_approval_for_update(connection, command.approval_id)
    _validate_loaded_approval(row)
    application = _column(row, "application", 1)
    operation = _column(row, "operation", 2)
    school_id = _column(row, "school_id", 4)
    target_principal_id = _column(row, "target_principal_id", 3)
    if application != "tms" or actor.application != "tms" or operation != "school_activation":
        raise ManagementAuthorizationDenied("approval operation is not applicable")
    _assert_operation_scope(actor, operation, school_id)
    await require_management_permission(
        connection,
        actor,
        _governance_action(application),
        target_school_id=actor.school_id,
        write=True,
    )
    status = _column(row, "status", 10)
    if status != "approved":
        raise ApprovalConflict("approval request is not approved")
    expected = _column(row, "expected_policy_version", 9)
    if command.expected_target_policy_version != expected:
        raise ApprovalConflict("target policy version changed")

    replay = await (
        await connection.execute(
            "SELECT id,principal_id,role_key,role_version,school_id,status "
            "FROM management.assignments WHERE application='tms' AND command_id=%s "
            "FOR SHARE",
            (command.command_id,),
        )
    ).fetchone()
    if replay is not None:
        if (
            _column(replay, "principal_id", 1) != target_principal_id
            or _column(replay, "role_key", 2) != "school_admin"
            or _column(replay, "role_version", 3) != 1
            or _column(replay, "school_id", 4) != school_id
            or _column(replay, "status", 5) != "active"
        ):
            raise ApprovalConflict("idempotency key was used for another assignment")
        target = await _lock_target_principal(
            connection,
            application="tms",
            principal_id=target_principal_id,
            school_id=school_id,
        )
        return ApprovalApplyResult(
            command.approval_id,
            _column(replay, "id", 0),
            "school_admin",
            _column(target, "policy_version", 2),
            True,
        )

    target = await _lock_target_principal(
        connection,
        application="tms",
        principal_id=target_principal_id,
        school_id=school_id,
    )
    if _column(target, "policy_version", 2) != expected:
        raise ApprovalConflict("target policy version changed")
    existing_admin = await (
        await connection.execute(
            "SELECT 1 FROM management.assignments WHERE application='tms' "
            "AND principal_id=%s AND role_key='school_admin' AND school_id=%s "
            "AND status='active' AND valid_from<=now() AND expires_at>now()",
            (target_principal_id, school_id),
        )
    ).fetchone()
    if existing_admin is not None:
        raise ApprovalConflict("target already has an active school administrator role")
    role = await (
        await connection.execute(
            "SELECT scope_kind FROM management.role_versions "
            "WHERE application='tms' AND role_key='school_admin' AND version=1 FOR SHARE"
        )
    ).fetchone()
    validate_assignment_relation(
        application="tms",
        principal_application="tms",
        principal_school_id=_column(target, "school_id", 3),
        role_application="tms" if role else None,
        role_scope_kind=_column(role, "scope_kind", 0) if role else None,
        assignment_scope_kind="school",
        assignment_school_id=school_id,
    )
    assignment_id = uuid4()
    expires_at = datetime(9998, 1, 1, tzinfo=timezone.utc)
    await connection.execute(
        "UPDATE management.principals SET status='active',updated_at=clock_timestamp() "
        "WHERE id=%s AND application='tms'",
        (target_principal_id,),
    )
    await connection.execute(
        "INSERT INTO management.assignments(id,application,principal_id,role_key,"
        "role_version,scope_kind,school_id,school_binding_version,valid_from,expires_at,"
        "command_id,created_by) VALUES(%s,'tms',%s,'school_admin',1,'school',%s,%s,"
        "clock_timestamp()-interval '1 second',%s,%s,%s)",
        (
            assignment_id,
            target_principal_id,
            school_id,
            actor.school_binding_version,
            expires_at,
            command.command_id,
            actor.subject,
        ),
    )
    delegation_actions = await (
        await connection.execute(
            "SELECT ra.action_key FROM management.role_actions ra "
            "JOIN management.action_catalog ac ON ac.application=ra.application "
            "AND ac.action_key=ra.action_key "
            "WHERE ra.application='tms' AND ra.role_key='school_admin' "
            "AND ra.role_version=1 AND ac.status='active' "
            "AND ac.allowed_scope='school' AND NOT ac.sensitive "
            "ORDER BY ra.action_key"
        )
    ).fetchall()
    for action in delegation_actions:
        await connection.execute(
            "INSERT INTO management.delegation_policies"
            "(id,application,principal_id,action_key,scope_kind,school_id,valid_from,expires_at) "
            "VALUES(%s,'tms',%s,%s,'school',%s,clock_timestamp()-interval '1 second',%s)",
            (
                uuid4(),
                target_principal_id,
                _column(action, "action_key", 0),
                school_id,
                expires_at,
            ),
        )
    next_policy_version = await advance_principal_policy_version(
        connection, target_principal_id, expected_before=expected
    )
    await _audit(
        connection,
        application="tms",
        school_id=school_id,
        actor=actor,
        target_id=assignment_id,
        request_id=command.request_id,
        result="success",
        reason=command.reason,
        before_version=expected,
        after_version=next_policy_version,
        safe_summary={"approval_id": str(command.approval_id), "role_key": "school_admin"},
    )
    return ApprovalApplyResult(
        command.approval_id, assignment_id, "school_admin", next_policy_version, False
    )
