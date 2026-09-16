"""认证凭证仅驻留请求/执行任务上下文，不能由客户端注入 tenant。"""

from contextlib import contextmanager
from contextvars import ContextVar

_token = ContextVar("enterprise_token", default=None)
_identity = ContextVar("enterprise_identity", default=None)


def current_token():
    token = _token.get()
    if not token:
        raise PermissionError("authentication required")
    return token


def current_identity():
    identity = _identity.get()
    if identity is None:
        raise PermissionError("authentication required")
    return identity


@contextmanager
def identity_context(identity, token):
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    t = _token.set(token)
    i = _identity.set(identity)
    u = set_current_user(
        CurrentUser(
            id=identity.user_id,
            username=identity.username,
            role=identity.role,
            scope=UserScope(
                kind="tenant", user_id=identity.user_id, root=None, tenant_id=identity.tenant_id
            ),
        )
    )
    try:
        yield identity
    finally:
        reset_current_user(u)
        _identity.reset(i)
        _token.reset(t)
