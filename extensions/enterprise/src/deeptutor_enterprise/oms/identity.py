"""EduPlus2 OIDC 平台身份验证；本产品动作权限另由 Enterprise 程序判定。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import time
from urllib.parse import urlsplit

import httpx
from jose import JWTError, jwt

_ACTIVE_ACCOUNT_STATUSES = frozenset({"active", "enabled", "allowed", "normal", "available"})
_INACTIVE_ACCOUNT_STATUSES = frozenset({"inactive", "disabled", "locked", "suspended", "deleted", "revoked"})
logger = logging.getLogger(__name__)

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




class BearerAccountStatusClient:
    """用同一个 OMS Bearer token 对既存用户状态端点做在线复核。

    该客户端只确认外部平台账号仍可用；不读取或映射任何 EduPlus2 业务权限，
    也不会把响应中的角色、部门或学校字段转成本产品 `ops.*` 授权。
    """

    def __init__(
        self,
        *,
        profile_url: str,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not profile_url:
            raise ValueError("OMS account status URL is required")
        _https_origin(profile_url)
        self.profile_url = profile_url
        self.timeout_seconds = float(timeout_seconds)
        self._http_client = http_client

    async def check(self, token: str, *, issuer: str, subject: str) -> bool:
        if not isinstance(token, str) or not token or len(token) > 16_384:
            raise PermissionError("OMS bearer token is invalid")
        if not subject:
            raise PermissionError("OMS subject is invalid")
        client = self._http_client or httpx.AsyncClient()
        close = self._http_client is None
        try:
            response = await client.get(
                self.profile_url,
                timeout=self.timeout_seconds,
                headers={"Accept": "application/json", "Authorization": "Bearer " + token},
            )
            if response.status_code in (401, 403):
                logger.warning(
                    "OMS account status endpoint denied bearer status_code=%s",
                    response.status_code,
                )
                return False
            if response.status_code >= 400:
                raise RuntimeError("OMS account status endpoint rejected request")
            try:
                payload = response.json()
            except ValueError:
                raise RuntimeError("OMS account status response is invalid") from None
            if not isinstance(payload, dict):
                raise RuntimeError("OMS account status response is invalid")
            return _normalize_account_status(payload, issuer=issuer, subject=subject)
        except httpx.HTTPError:
            raise RuntimeError("OMS account status endpoint is unavailable") from None
        finally:
            if close:
                await client.aclose()


class TokenOnlyAccountStatusClient:
    """仅以已验签 OIDC token 的有效期作为外部账号状态复核。

    该策略用于 EduPlus2 只提供认证与身份识别、未向 OMS client 开放独立 profile
    状态端点的部署。它不会授予任何 DeepTutor `ops.*` 权限，也不会读取 JWT 角色；
    业务动作仍由本地 Enterprise 授权事实判定。
    """

    async def check(self, token: str, *, issuer: str, subject: str) -> bool:
        if not isinstance(token, str) or not token or len(token) > 16_384:
            raise PermissionError("OMS bearer token is invalid")
        if not issuer or not subject:
            raise PermissionError("OMS subject is invalid")
        return True


def _walk_dicts(value: object):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _first_text(mapping: dict, *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int):
            return str(value)
    return ""


def _normalize_account_status(payload: dict, *, issuer: str, subject: str) -> bool:
    code = payload.get("code")
    if code not in (None, 0, "0"):
        logger.warning(
            "OMS account status response rejected by envelope code=%s keys=%s data_keys=%s",
            code,
            sorted(str(key) for key in payload.keys()),
            sorted(str(key) for key in payload.get("data", {}).keys())
            if isinstance(payload.get("data"), dict)
            else [],
        )
        return False
    subject_seen = False
    status_values: list[str] = []
    enabled_values: list[bool] = []
    for mapping in _walk_dicts(payload.get("data", payload)):
        found_subject = _first_text(
            mapping,
            "sub",
            "subject",
            "k_user_id",
            "keycloak_user_id",
            "keycloakUserId",
        )
        if found_subject:
            if found_subject != subject:
                raise PermissionError("OMS account status subject mismatch")
            subject_seen = True
        found_issuer = _first_text(mapping, "iss", "issuer")
        if found_issuer and issuer and found_issuer.rstrip("/") != issuer.rstrip("/"):
            raise PermissionError("OMS account status issuer mismatch")
        for key in (
            "status",
            "account_status",
            "accountStatus",
            "user_status",
            "userStatus",
            "state",
        ):
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                status_values.append(value.strip().lower())
        for key in ("active", "enabled", "available"):
            value = mapping.get(key)
            if type(value) is bool:
                enabled_values.append(value)
    if not subject_seen:
        raise RuntimeError("OMS account status response missing subject")
    if any(value in _INACTIVE_ACCOUNT_STATUSES for value in status_values):
        logger.warning(
            "OMS account status inactive by status_values=%s enabled_values=%s",
            status_values,
            enabled_values,
        )
        return False
    if any(value in _ACTIVE_ACCOUNT_STATUSES for value in status_values):
        return True
    if enabled_values:
        if not all(enabled_values):
            logger.warning(
                "OMS account status inactive by enabled_values=%s status_values=%s",
                enabled_values,
                status_values,
            )
        return all(enabled_values)
    raise RuntimeError("OMS account status response missing status")


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
