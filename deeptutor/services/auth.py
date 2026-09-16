"""惰性默认 PG 认证适配；import 不解析配置、Secret 或本地身份。"""

from dataclasses import dataclass, field
from typing import Any

# 仅供旧调用者 import 兼容；默认运行时不再支持关闭认证或 PocketBase。
AUTH_ENABLED = True
POCKETBASE_ENABLED = False
TOKEN_EXPIRE_HOURS = 1


@dataclass(frozen=True)
class TokenPayload:
    username: str
    role: str
    user_id: str = ""
    tenant_id: str = ""
    session_id: str = ""
    auth_version: int = 0
    device_credential_id: str = ""
    device_session_nonce: str = ""
    learning_policy: dict | None = None
    token: str = field(default="", repr=False)
    provider: Any = field(default=None, repr=False, compare=False)


def hash_password(plain: str) -> str:
    """离线旧源工具兼容；默认账号写入使用 IdentityService._hash。"""
    import bcrypt

    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    import bcrypt

    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


class PostgresAuthProvider:
    def __init__(self, identity, *, resources, cookie_secure=True):
        self.identity = identity
        self.resources = resources
        self.cookie_secure = bool(cookie_secure)

    async def decode(self, token):
        actor = await self.identity.authenticate(token)
        info = await self.identity.profile(token)
        return TokenPayload(
            username=actor.username,
            role=actor.role,
            user_id=actor.user_id,
            tenant_id=actor.tenant_id,
            session_id=actor.session_id,
            auth_version=actor.auth_version,
            device_credential_id=actor.device_credential_id,
            learning_policy=info["learning_policy"] if actor.role == "user" else None,
            token=token,
            provider=self,
        )

    @staticmethod
    def socket_token(ws):
        from deeptutor.api.routers.auth import _extract_token

        return (
            _extract_token(ws.headers.get("authorization"), ws.cookies.get("dt_token"))
            or ws.query_params.get("token")
            or ""
        )

    async def authenticate(self, ws):
        from deeptutor.multi_user.context import set_current_user, user_from_token_payload

        payload = await self.decode(self.socket_token(ws))
        return set_current_user(user_from_token_payload(payload))

    async def revalidate(self, ws):
        await self.decode(self.socket_token(ws))

    async def record_denial(self):
        await self.identity.record_denial("websocket")

    @staticmethod
    def error_message(error):
        return "Authentication required" if isinstance(error, PermissionError) else "Request failed"


async def decode_token(token):
    from deeptutor.core.providers import get_providers

    providers = get_providers()
    provider = getattr(providers, "auth", None)
    if provider is None:
        raise RuntimeError("explicit PostgreSQL auth provider required")
    try:
        return await provider.decode(token)
    except PermissionError:
        return None
