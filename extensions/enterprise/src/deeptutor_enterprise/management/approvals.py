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


def _governance_action(application: str) -> str:
    return "ops.permissions.manage" if application == "oms" else "tenant.permissions.manage"


def _validate_text(value: object, *, max_len: int = 1000) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= max_len


def _validate_create_command(command: CreateApprovalRequestCommand) -> None:
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
            "external_qualification_version,status FROM management.approval_requests "
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
        ):
            raise ApprovalConflict("idempotency key was used for another approval")
        return ApprovalRequestResult(_column(existing, "id", 0), _column(existing, "status", 10), True)

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
            "expected_policy_version,status,expires_at,idempotency_key,reason,request_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s)",
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
            "expected_policy_version,status,expires_at,decided_at "
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
