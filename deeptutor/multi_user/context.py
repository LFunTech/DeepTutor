"""Request-local current user context."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from .models import CurrentUser

_current_user: ContextVar[CurrentUser | None] = ContextVar("deeptutor_current_user", default=None)


def set_current_user(user: CurrentUser) -> Token[CurrentUser | None]:
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    _current_user.reset(token)


def get_current_user() -> CurrentUser:
    user = _current_user.get()
    if user is not None:
        return user
    raise PermissionError("authenticated identity is required")


def get_current_user_or_none() -> CurrentUser | None:
    return _current_user.get()


def user_from_token_payload(payload: Any | None) -> CurrentUser:
    from .models import UserScope

    if payload is None:
        raise PermissionError("authenticated identity is required")
    tenant_id = str(getattr(payload, "tenant_id", "") or "")
    user_id = str(getattr(payload, "user_id", "") or "")
    role = str(getattr(payload, "role", "") or "")
    if not tenant_id or not user_id or role not in {"user", "tenant_admin"}:
        raise PermissionError("PostgreSQL identity is required")
    return CurrentUser(
        id=user_id,
        username=payload.username,
        role=role,
        scope=UserScope(kind="tenant", tenant_id=tenant_id, user_id=user_id, root=None),
        learning_policy=getattr(payload, "learning_policy", None),
    )
