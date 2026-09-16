"""角色语义辅助函数。

PG 身份中的 ``tenant_admin`` 是租户管理者：可以管理部署级设置、账号、
模型池和默认资源；但它不是旧文件工作区里的 ``admin``，不能因此获得
``data/user`` 本地路径作为权威根。调用方需要显式区分这两种语义。
"""

from __future__ import annotations

from typing import Any


def can_manage_deployment(user: Any) -> bool:
    """Return whether *user* may manage tenant/deployment-level controls."""

    return bool(
        getattr(user, "is_admin", False) or getattr(user, "can_manage_accounts", False)
    )


def is_grant_restricted_user(user: Any) -> bool:
    """Return whether *user* should be constrained by per-user grants."""

    return not can_manage_deployment(user)


__all__ = ["can_manage_deployment", "is_grant_restricted_user"]
