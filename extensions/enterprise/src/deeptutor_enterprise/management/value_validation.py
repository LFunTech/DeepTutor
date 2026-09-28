"""Management 持久事实的应用层值域校验。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID


class ManagementValueError(ValueError):
    """管理授权事实包含未知业务值或条件字段不一致。"""


_APPLICATIONS = {"oms", "tms"}
_PRINCIPAL_STATUSES = {"pending", "active", "disabled"}
_ACTION_SCOPES = {"platform", "school", "both"}
_ACTION_STATUSES = {"active", "retired"}
_SCOPE_KINDS = {"platform", "school"}
_ASSIGNMENT_STATUSES = {"active", "revoked"}
_APPROVAL_OPERATIONS = {"platform_grant", "delegation_expand", "school_activation"}
_APPROVAL_STATUSES = {"pending", "approved", "rejected", "expired", "withdrawn", "failed"}
_AUDIT_RESULTS = {"success", "denied", "conflict", "failed"}


def _optional(row: Mapping[str, object], key: str, default=None):
    return row[key] if key in row else default


def _non_empty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware_datetime(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _non_negative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _valid_action_prefix(application: object, action_key: object) -> bool:
    if not _non_empty(action_key) or len(action_key) > 128:
        return False
    prefix = "ops." if application == "oms" else "tenant."
    return str(action_key).startswith(prefix)


def validate_management_principal_row(row: Mapping[str, object]) -> None:
    """校验 principal 行本身的应用域、状态、版本与学校归属。"""

    application = _optional(row, "application")
    school_id = _optional(row, "school_id")
    if (
        application not in _APPLICATIONS
        or _optional(row, "status") not in _PRINCIPAL_STATUSES
        or ("policy_version" in row and not _positive_int(row["policy_version"]))
        or (application == "oms" and school_id is not None)
        or (application == "tms" and not isinstance(school_id, UUID))
    ):
        raise ManagementValueError("management principal fact is invalid")


def validate_management_action_row(row: Mapping[str, object]) -> None:
    """校验 action_catalog 行的应用域、动作前缀、范围和状态。"""

    application = _optional(row, "application")
    allowed_scope = _optional(row, "allowed_scope")
    if (
        application not in _APPLICATIONS
        or not _valid_action_prefix(application, _optional(row, "action_key"))
        or allowed_scope not in _ACTION_SCOPES
        or (application == "tms" and allowed_scope != "school")
        or _optional(row, "status") not in _ACTION_STATUSES
        or ("sensitive" in row and type(row["sensitive"]) is not bool)
        or ("version" in row and not _positive_int(row["version"]))
    ):
        raise ManagementValueError("management action catalog fact is invalid")


def validate_management_role_version_row(row: Mapping[str, object]) -> None:
    """校验角色版本目录事实，不依赖 role/action 触发器。"""

    application = _optional(row, "application")
    role_key = _optional(row, "role_key")
    scope_kind = _optional(row, "scope_kind")
    is_template = _optional(row, "is_template")
    owner_school_id = _optional(row, "owner_school_id")
    if (
        application not in _APPLICATIONS
        or not _non_empty(role_key)
        or ("version" in row and not _positive_int(row["version"]))
        or scope_kind not in _SCOPE_KINDS
        or (application == "tms" and scope_kind != "school")
        or ("is_template" in row and type(is_template) is not bool)
        or (owner_school_id is not None and not isinstance(owner_school_id, UUID))
        or (application == "oms" and owner_school_id is not None)
        or (application == "tms" and is_template is True and owner_school_id is not None)
        or (
            application == "tms"
            and is_template is False
            and (
                not isinstance(owner_school_id, UUID)
                or not str(role_key).startswith(f"custom_{owner_school_id.hex}_")
            )
        )
    ):
        raise ManagementValueError("management role version fact is invalid")


def validate_management_assignment_row(row: Mapping[str, object]) -> None:
    """校验 assignment 行的值域、有效期、状态与学校绑定版本形状。"""

    scope_kind = _optional(row, "scope_kind")
    school_id = _optional(row, "school_id")
    status = _optional(row, "status")
    valid_from = _optional(row, "valid_from")
    expires_at = _optional(row, "expires_at")
    revoked_at = _optional(row, "revoked_at")
    binding_version = _optional(row, "school_binding_version")
    if (
        _optional(row, "application") not in _APPLICATIONS
        or ("id" in row and not isinstance(row["id"], UUID))
        or not _positive_int(_optional(row, "version"))
        or status not in _ASSIGNMENT_STATUSES
        or scope_kind not in _SCOPE_KINDS
        or not _aware_datetime(valid_from)
        or not _aware_datetime(expires_at)
        or expires_at <= valid_from
        or (status == "active" and revoked_at is not None)
        or (status == "revoked" and not _aware_datetime(revoked_at))
        or (scope_kind == "platform" and (school_id is not None or binding_version is not None))
        or (
            scope_kind == "school"
            and (not isinstance(school_id, UUID) or not _positive_int(binding_version))
        )
    ):
        raise ManagementValueError("management assignment fact is invalid")


def validate_management_delegation_row(row: Mapping[str, object]) -> None:
    """校验 delegation_policies 行的值域、有效期与学校范围形状。"""

    scope_kind = _optional(row, "scope_kind")
    school_id = _optional(row, "school_id")
    valid_from = _optional(row, "valid_from")
    expires_at = _optional(row, "expires_at")
    if (
        _optional(row, "application") not in _APPLICATIONS
        or ("id" in row and not isinstance(row["id"], UUID))
        or not _positive_int(_optional(row, "version"))
        or _optional(row, "status") not in _ASSIGNMENT_STATUSES
        or scope_kind not in _SCOPE_KINDS
        or (scope_kind == "platform" and school_id is not None)
        or (scope_kind == "school" and not isinstance(school_id, UUID))
        or not _aware_datetime(valid_from)
        or not _aware_datetime(expires_at)
        or expires_at <= valid_from
    ):
        raise ManagementValueError("management delegation fact is invalid")


def validate_management_approval_row(row: Mapping[str, object]) -> None:
    """校验审批请求枚举值和双人复核字段条件。"""

    application = _optional(row, "application")
    operation = _optional(row, "operation")
    school_id = _optional(row, "school_id")
    status = _optional(row, "status")
    reviewer_issuer = _optional(row, "reviewer_issuer")
    reviewer_subject = _optional(row, "reviewer_subject")
    proposer_issuer = _optional(row, "proposer_issuer")
    proposer_subject = _optional(row, "proposer_subject")
    decided_at = _optional(row, "decided_at")
    reviewer_empty = reviewer_issuer is None and reviewer_subject is None
    reviewer_complete = _non_empty(reviewer_issuer) and _non_empty(reviewer_subject)
    if (
        ("id" in row and not isinstance(row["id"], UUID))
        or application not in _APPLICATIONS
        or operation not in _APPROVAL_OPERATIONS
        or status not in _APPROVAL_STATUSES
        or not _non_empty(proposer_issuer)
        or not _non_empty(proposer_subject)
        or not _positive_int(_optional(row, "expected_policy_version"))
        or not _aware_datetime(_optional(row, "expires_at"))
        or not (reviewer_empty or reviewer_complete)
        or (
            application == "oms"
            and (operation == "school_activation" or school_id is not None)
        )
        or (
            application == "tms"
            and (operation != "school_activation" or not isinstance(school_id, UUID))
        )
        or (
            status == "approved"
            and (
                not reviewer_complete
                or not _aware_datetime(decided_at)
                or (reviewer_issuer, reviewer_subject) == (proposer_issuer, proposer_subject)
            )
        )
    ):
        raise ManagementValueError("management approval fact is invalid")


def validate_management_audit_row(row: Mapping[str, object]) -> None:
    """校验审计事件的应用域、动作前缀、结果值域与版本形状。"""

    application = _optional(row, "application")
    if (
        ("id" in row and not isinstance(row["id"], UUID))
        or application not in _APPLICATIONS
        or not _valid_action_prefix(application, _optional(row, "action_key"))
        or _optional(row, "result") not in _AUDIT_RESULTS
        or not _non_empty(_optional(row, "actor_issuer"))
        or not _non_empty(_optional(row, "actor_subject"))
        or not _non_empty(_optional(row, "target_kind"))
        or not _non_empty(_optional(row, "target_id"))
        or not _non_empty(_optional(row, "request_id"))
        or not isinstance(_optional(row, "safe_summary", {}), Mapping)
        or (
            "before_version" in row
            and row["before_version"] is not None
            and not _non_negative_int(row["before_version"])
        )
        or (
            "after_version" in row
            and row["after_version"] is not None
            and not _non_negative_int(row["after_version"])
        )
    ):
        raise ManagementValueError("management audit fact is invalid")
