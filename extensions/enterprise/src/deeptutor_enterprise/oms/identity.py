"""EduPlus2 OIDC 平台身份验证；本产品动作权限另由 Enterprise 程序判定。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import time
from urllib.parse import urlsplit

import httpx
from jose import JWTError, jwt

from deeptutor.persistence.postgres.scope import GlobalScope
from deeptutor_enterprise.eduplus2.client import EduPlus2OidcJwtVerifier
from deeptutor_enterprise.management.authorization import ManagementIdentity


def _https_origin(url: str) -> tuple[str, str, int]:
    """仅接受无凭据的 HTTPS URL，返回可比较的来源。"""

    try:
        parts = urlsplit(url)
        if (
            parts.scheme.lower() != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError
        return ("https", parts.hostname.lower(), parts.port or 443)
    except ValueError:
        raise ValueError("OMS OIDC endpoints must use trusted HTTPS URLs") from None


@dataclass(frozen=True, slots=True)
class PlatformIdentity:
    """仅持有已验证的身份断言，不携带 JWT role 或租户 scope。"""

    issuer: str
    subject: str
    client_id: str
    token_hash: str
    issued_at: int
    expires_at: int


class PlatformOidcJwtVerifier:
    """验证专用 OMS audience/client 的 EduPlus2 access token。

    该类不授予任何 `ops.*` 权限，也不把它转换为租户会话；权限
    本产品动作授权与目标学校绑定未验收前，调用方必须保持跨学校写路由未装配。
    """

    def __init__(
        self,
        *,
        discovery_url: str,
        issuer: str,
        audience: str,
        client_id: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not all((discovery_url, issuer, audience, client_id)):
            raise ValueError("OMS OIDC identity contract is incomplete")
        issuer_origin = _https_origin(issuer)
        if _https_origin(discovery_url) != issuer_origin:
            raise ValueError("OMS OIDC discovery must share the issuer HTTPS origin")
        self._issuer_origin = issuer_origin
        self.issuer = issuer
        self.audience = audience
        self.client_id = client_id
        self._oidc = EduPlus2OidcJwtVerifier(
            discovery_url=discovery_url,
            issuer=issuer,
            http_client=http_client,
            algorithms=("RS256",),
        )

    async def verify(self, token: str) -> PlatformIdentity:
        try:
            header = jwt.get_unverified_header(token)
        except JWTError:
            raise PermissionError("OMS platform token is invalid") from None
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise PermissionError("OMS platform token algorithm is not allowed")
        discovery = await self._oidc._load_discovery()
        try:
            if _https_origin(discovery["jwks_uri"]) != self._issuer_origin:
                raise ValueError
        except (KeyError, ValueError):
            raise PermissionError("OMS JWKS origin is not trusted") from None
        key = await self._oidc._key_for(str(header["kid"]))
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=discovery["issuer"],
                audience=self.audience,
                options={
                    "verify_at_hash": False,
                    "require_exp": True,
                    "require_iat": True,
                    "require_iss": True,
                    "require_aud": True,
                },
            )
        except JWTError:
            raise PermissionError("OMS platform token verification failed") from None
        if (
            not isinstance(claims.get("sub"), str)
            or not claims["sub"].strip()
            or claims.get("azp") != self.client_id
            or claims.get("typ") != "Bearer"
        ):
            raise PermissionError("OMS platform token identity is invalid")
        try:
            issued_at = int(claims["iat"])
            expires_at = int(claims["exp"])
        except (TypeError, ValueError):
            raise PermissionError("OMS platform token timestamps are invalid") from None
        if issued_at > int(time.time()) + 5:
            raise PermissionError("OMS platform token iat is in the future")
        return PlatformIdentity(
            issuer=self.issuer,
            subject=claims["sub"],
            client_id=self.client_id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            issued_at=issued_at,
            expires_at=expires_at,
        )


class PlatformAccountInactive(PermissionError):
    """外部在线检查确认平台账号不可用。"""


async def trusted_oms_identity_from_token(enterprise, token: str) -> ManagementIdentity:
    """合成 OMS 本产品身份；外部只确认身份和账号状态，不授予动作。"""

    verifier = getattr(enterprise, "oms_platform_verifier", None)
    status = getattr(enterprise, "oms_account_status", None)
    if verifier is None or status is None:
        raise RuntimeError("OMS identity contract is unavailable")
    if not isinstance(token, str) or not token or len(token) > 16_384:
        raise PermissionError("OMS bearer token is invalid")
    verified = await verifier.verify(token)
    if not isinstance(verified, PlatformIdentity) or not verified.issuer or not verified.subject:
        raise PermissionError("OMS identity verification is invalid")
    try:
        active = await status.check(token, issuer=verified.issuer, subject=verified.subject)
    except Exception as error:
        raise RuntimeError("OMS online account status is unavailable") from error
    if active is not True:
        raise PlatformAccountInactive("OMS platform account is inactive")
    now = datetime.now(timezone.utc)
    verified_until = min(
        datetime.fromtimestamp(verified.expires_at, timezone.utc), now + timedelta(seconds=5)
    )
    if verified_until <= now:
        raise PermissionError("OMS bearer token is expired")
    async with enterprise.db.transaction(GlobalScope("@oms-identity")) as c:
        await c.execute("SELECT set_config('app.management_app','oms',true)")
        row = await (
            await c.execute(
                "SELECT policy_version FROM management.principals "
                "WHERE application='oms' AND issuer=%s AND subject=%s AND status='active'",
                (verified.issuer, verified.subject),
            )
        ).fetchone()
    return ManagementIdentity(
        application="oms",
        issuer=verified.issuer,
        subject=verified.subject,
        school_id=None,
        policy_version=row["policy_version"] if row else 1,
        school_binding_version=None,
        external_active=True,
        external_checked_at=now,
        external_verified_until=verified_until,
    )
