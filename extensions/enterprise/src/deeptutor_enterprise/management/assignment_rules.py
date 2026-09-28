"""授权 assignment 的程序关联校验；替代原行级触发器的语义。"""

from __future__ import annotations

from uuid import UUID

from .authorization import ManagementAuthorizationDenied


def validate_assignment_relation(
    *,
    application: str,
    principal_application: str | None,
    principal_school_id: UUID | None,
    role_application: str | None,
    role_scope_kind: str | None,
    assignment_scope_kind: str,
    assignment_school_id: UUID | None,
) -> None:
    """程序核对角色范围和 TMS 主体学校；缺失/未知旧事实拒绝。"""

    if (
        application not in {"oms", "tms"}
        or principal_application != application
        or role_application != application
        or role_scope_kind not in {"platform", "school"}
        or assignment_scope_kind != role_scope_kind
        or (assignment_scope_kind == "platform") != (assignment_school_id is None)
        or (application == "oms" and principal_school_id is not None)
        or (
            application == "tms"
            and (
                assignment_scope_kind != "school"
                or not isinstance(assignment_school_id, UUID)
                or principal_school_id != assignment_school_id
            )
        )
    ):
        raise ManagementAuthorizationDenied("assignment relation is invalid")
