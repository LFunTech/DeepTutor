"""委托策略的程序关系校验；不通过数据库函数决定动作范围。"""

from __future__ import annotations

from uuid import UUID

from .authorization import ManagementAuthorizationDenied


def validate_delegation_relation(
    *,
    application: str,
    principal_application: str | None,
    principal_school_id: UUID | None,
    action_application: str | None,
    action_status: str | None,
    action_allowed_scope: str | None,
    delegation_scope_kind: str,
    delegation_school_id: UUID | None,
    for_write: bool = True,
) -> None:
    """旧触发器的学校/动作范围语义及缺失事实由 Python 统一拒绝。"""

    if (
        application not in {"oms", "tms"}
        or principal_application != application
        or action_application != application
        or (action_status != "active" if for_write else action_status not in {"active", "retired"})
        or action_allowed_scope not in {"platform", "school", "both"}
        or delegation_scope_kind not in {"platform", "school"}
        or action_allowed_scope not in {delegation_scope_kind, "both"}
        or (application == "tms" and action_allowed_scope != "school")
        or (delegation_scope_kind == "platform") != (delegation_school_id is None)
        or (application == "oms" and principal_school_id is not None)
        or (
            application == "tms"
            and (
                delegation_scope_kind != "school"
                or not isinstance(delegation_school_id, UUID)
                or principal_school_id != delegation_school_id
            )
        )
    ):
        raise ManagementAuthorizationDenied("delegation relation is invalid")
