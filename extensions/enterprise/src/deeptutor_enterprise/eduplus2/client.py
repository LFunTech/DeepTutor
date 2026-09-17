"""EduPlus2 OIDC/JWKS verifier 与 OAuth client resolve 客户端。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any

import httpx
from jose import JWTError, jwt

_REQUIRED_CLAIMS = ("iss", "exp", "iat", "tid", "eui", "sub", "azp")
_DEFAULT_INCLUDE = ("app", "tenant", "oauth", "policy")
_ALLOWED_ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"})
_ACTIVE_PROFILE_STATUSES = frozenset({"active", "enabled", "allowed"})


@dataclass(frozen=True, slots=True)
class VerifiedEduPlus2Jwt:
    """已校验 EduPlus2 user JWT 的脱敏结果。"""

    claims: dict[str, Any]
    header: dict[str, Any]
    token_hash: str


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _require_claims(claims: dict[str, Any]) -> None:
    missing = [key for key in _REQUIRED_CLAIMS if not claims.get(key)]
    if missing:
        raise PermissionError("required EduPlus2 JWT claims are missing")
    if int(claims["iat"]) > int(time.time()) + 5:
        raise PermissionError("EduPlus2 JWT iat is in the future")


class HmacEduPlus2JwtVerifier:
    """本地测试/受控环境用的对称 key verifier；生产默认使用 OIDC/JWKS。"""

    def __init__(self, *, signing_key: str, issuer: str):
        if len(signing_key or "") < 32:
            raise ValueError("missing or weak EduPlus2 verifier key")
        if not (issuer or "").strip():
            raise ValueError("EduPlus2 issuer is required")
        self.signing_key = signing_key
        self.issuer = issuer.rstrip("/")

    async def verify(self, token: str) -> VerifiedEduPlus2Jwt:
        try:
            header = jwt.get_unverified_header(token)
            claims = jwt.decode(
                token,
                self.signing_key,
                algorithms=["HS256"],
                issuer=self.issuer,
                options={
                    "verify_aud": False,
                    "require_exp": True,
                    "require_iat": True,
                    "require_iss": True,
                },
            )
        except JWTError:
            raise PermissionError("EduPlus2 JWT verification failed") from None
        _require_claims(claims)
        return VerifiedEduPlus2Jwt(claims=claims, header=header, token_hash=_token_hash(token))


class EduPlus2OidcJwtVerifier:
    """通过 OIDC discovery/JWKS 验证 EduPlus2 user JWT。"""

    def __init__(
        self,
        *,
        discovery_url: str,
        issuer: str | None = None,
        jwks_uri: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        jwks_ttl_seconds: int = 300,
        timeout_seconds: float = 5.0,
        algorithms: tuple[str, ...] | None = None,
    ):
        if not discovery_url:
            raise ValueError("EduPlus2 discovery url is required")
        self.discovery_url = discovery_url
        self.expected_issuer = issuer.rstrip("/") if issuer else ""
        self.configured_jwks_uri = jwks_uri
        self.jwks_ttl_seconds = int(jwks_ttl_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self.algorithms = tuple(algorithms or ())
        self._http_client = http_client
        self._discovery: dict[str, Any] | None = None
        self._jwks_by_kid: dict[str, dict[str, Any]] = {}
        self._jwks_expires_at = 0.0

    async def _get_json(self, url: str) -> dict[str, Any]:
        client = self._http_client or httpx.AsyncClient()
        close = self._http_client is None
        try:
            response = await client.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            raise RuntimeError("EduPlus2 OIDC endpoint is unavailable") from None
        finally:
            if close:
                await client.aclose()

    async def _load_discovery(self) -> dict[str, Any]:
        if self._discovery is not None:
            return self._discovery
        discovery = await self._get_json(self.discovery_url)
        issuer = str(discovery.get("issuer") or "").rstrip("/")
        if not issuer:
            raise RuntimeError("EduPlus2 discovery response missing issuer")
        if self.expected_issuer and issuer != self.expected_issuer:
            raise PermissionError("EduPlus2 issuer mismatch")
        jwks_uri = self.configured_jwks_uri or str(discovery.get("jwks_uri") or "")
        if not jwks_uri:
            raise RuntimeError("EduPlus2 discovery response missing jwks_uri")
        algorithms = self.algorithms or tuple(
            alg
            for alg in discovery.get("id_token_signing_alg_values_supported", [])
            if alg in _ALLOWED_ASYMMETRIC_ALGORITHMS
        )
        if not algorithms:
            algorithms = ("RS256",)
        if any(alg not in _ALLOWED_ASYMMETRIC_ALGORITHMS for alg in algorithms):
            raise PermissionError("EduPlus2 JWT algorithm is not allowed")
        self._discovery = {"issuer": issuer, "jwks_uri": jwks_uri, "algorithms": algorithms}
        return self._discovery

    async def _load_jwks(self, *, force: bool = False) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        if not force and self._jwks_by_kid and now < self._jwks_expires_at:
            return self._jwks_by_kid
        discovery = await self._load_discovery()
        jwks = await self._get_json(discovery["jwks_uri"])
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            raise RuntimeError("EduPlus2 JWKS response missing keys")
        self._jwks_by_kid = {
            str(key.get("kid")): key
            for key in keys
            if isinstance(key, dict) and key.get("kid") and key.get("kty")
        }
        self._jwks_expires_at = now + max(1, self.jwks_ttl_seconds)
        return self._jwks_by_kid

    async def _key_for(self, kid: str) -> dict[str, Any]:
        keys = await self._load_jwks()
        key = keys.get(kid)
        if key is None:
            key = (await self._load_jwks(force=True)).get(kid)
        if key is None:
            raise PermissionError("EduPlus2 JWKS kid is not trusted")
        return key

    async def warmup(self) -> None:
        """预加载 discovery/JWKS；用于启动检查和 gated smoke。"""

        await self._load_jwks()

    async def verify(self, token: str) -> VerifiedEduPlus2Jwt:
        try:
            header = jwt.get_unverified_header(token)
        except JWTError:
            raise PermissionError("EduPlus2 JWT verification failed") from None
        kid = str(header.get("kid") or "")
        alg = str(header.get("alg") or "")
        discovery = await self._load_discovery()
        if not kid or alg not in discovery["algorithms"]:
            raise PermissionError("EduPlus2 JWT algorithm is not allowed")
        key = await self._key_for(kid)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[alg],
                issuer=discovery["issuer"],
                options={
                    "verify_aud": False,
                    "require_exp": True,
                    "require_iat": True,
                    "require_iss": True,
                },
            )
        except JWTError:
            # kid 轮换期间刷新一次 JWKS；仍失败则 fail closed。
            key = (await self._load_jwks(force=True)).get(kid) or key
            try:
                claims = jwt.decode(
                    token,
                    key,
                    algorithms=[alg],
                    issuer=discovery["issuer"],
                    options={
                        "verify_aud": False,
                        "require_exp": True,
                        "require_iat": True,
                        "require_iss": True,
                    },
                )
            except JWTError:
                raise PermissionError("EduPlus2 JWT verification failed") from None
        _require_claims(claims)
        return VerifiedEduPlus2Jwt(claims=claims, header=header, token_hash=_token_hash(token))


def _pick(value: dict[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        found = value.get(name)
        if found is not None:
            return str(found)
    return default


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple | set):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RuntimeError("EduPlus2 permission response is invalid") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _data_payload(payload: dict[str, Any], *, endpoint: str) -> dict[str, Any]:
    code = payload.get("code")
    if code not in (None, 0, "0"):
        raise PermissionError(f"EduPlus2 {endpoint} rejected request")
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise RuntimeError(f"EduPlus2 {endpoint} response is invalid")
    return data


def normalize_resolve_response(client_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """把 EduPlus2 resolve 响应规范化成 exchange service 使用的扁平结构。"""

    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise RuntimeError("EduPlus2 resolve response is invalid")
    verified = bool(data.get("verified", payload.get("verified", False)))
    reason = str(data.get("reason", payload.get("reason", "")) or "")
    if not verified:
        raise PermissionError(reason or "resolve_unverified")
    client = data.get("client") if isinstance(data.get("client"), dict) else data
    tenant = data.get("tenant") if isinstance(data.get("tenant"), dict) else data
    app = data.get("app") if isinstance(data.get("app"), dict) else data
    policy = data.get("policy") if isinstance(data.get("policy"), dict) else {}
    resolved = {
        "client_id": _pick(client, "client_id", "id"),
        "external_tenant_id": _pick(tenant, "id", "tenant_id", "external_tenant_id"),
        "external_tenant_name": _pick(tenant, "name", "tenant_name", "external_tenant_name"),
        "external_app_id": _pick(app, "id", "app_id", "external_app_id"),
        "external_app_name": _pick(app, "name", "app_name", "external_app_name"),
        "status": _pick(client, "status", default=""),
        "tenant_status": _pick(tenant, "status", default="active"),
        "app_status": _pick(app, "status", default="active"),
        "subscription_status": _pick(policy, "subscription_status", "status", default="active"),
        "oauth": data.get("oauth") if isinstance(data.get("oauth"), dict) else {},
        "policy": policy,
        "version": _pick(data, "version", "etag", default=""),
        "reason": reason,
    }
    missing = [
        key
        for key in ("client_id", "external_tenant_id", "external_app_id", "status")
        if not resolved.get(key)
    ]
    if missing:
        raise RuntimeError("EduPlus2 resolve response missing required fields")
    if resolved["client_id"] != client_id:
        raise PermissionError("resolved client id mismatch")
    return resolved


def normalize_profile_response(
    *,
    external_tenant_id: str,
    external_user_id: str,
    external_subject: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """把 EduPlus2 profile 响应收敛为最小、可持久化、脱敏快照。"""

    data = _data_payload(payload, endpoint="profile")
    verified = bool(data.get("verified", payload.get("verified", True)))
    if not verified:
        raise PermissionError("profile is not verified")
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else data
    normalized = {
        "external_tenant_id": _pick(profile, "tenant_id", "tid", "external_tenant_id"),
        "external_user_id": _pick(profile, "user_id", "eui", "external_user_id"),
        "external_subject": _pick(profile, "subject", "sub", "external_subject"),
        "external_identity_type": _pick(
            profile,
            "identity_type",
            "identityType",
            "eit",
            "external_identity_type",
        ),
        "display_name": _pick(profile, "display_name", "displayName", "name", default=""),
        "status": _pick(profile, "status", default=""),
        "version": _pick(profile, "version", "profile_version", "etag", default=""),
    }
    missing = [
        key
        for key in ("external_tenant_id", "external_user_id", "external_subject", "status")
        if not normalized.get(key)
    ]
    if missing:
        raise RuntimeError("EduPlus2 profile response missing required fields")
    if (
        normalized["external_tenant_id"] != external_tenant_id
        or normalized["external_user_id"] != external_user_id
        or normalized["external_subject"] != external_subject
    ):
        raise PermissionError("profile mismatch")
    if normalized["status"].lower() not in _ACTIVE_PROFILE_STATUSES:
        raise PermissionError("profile is inactive")
    normalized["summary"] = dict(normalized)
    return normalized


def normalize_permission_response(
    *,
    external_tenant_id: str,
    external_user_id: str,
    external_subject: str,
    client_id: str,
    external_app_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """把 EduPlus2 permission 响应规范化为本地授权边界快照。"""

    data = _data_payload(payload, endpoint="permission")
    permission = data.get("permission") if isinstance(data.get("permission"), dict) else data
    tenant = data.get("tenant") if isinstance(data.get("tenant"), dict) else data
    user = data.get("user") if isinstance(data.get("user"), dict) else data
    client = data.get("client") if isinstance(data.get("client"), dict) else data
    app = data.get("app") if isinstance(data.get("app"), dict) else data
    normalized = {
        "allowed": bool(data.get("allowed", permission.get("allowed", False))),
        "reason": str(data.get("reason", permission.get("reason", "")) or ""),
        "external_tenant_id": _pick(tenant, "id", "tenant_id", "external_tenant_id"),
        "external_user_id": _pick(user, "id", "user_id", "eui", "external_user_id"),
        "external_subject": _pick(user, "subject", "sub", "external_subject", default=""),
        "client_id": _pick(client, "client_id", "id"),
        "external_app_id": _pick(app, "id", "app_id", "external_app_id"),
        "allowed_usages": _as_str_list(
            permission.get("allowed_usages", data.get("allowed_usages", []))
        ),
        "scopes": _as_str_list(permission.get("scopes", data.get("scopes", []))),
        "version": _pick(permission, "version", "permission_version", "etag", default=""),
        "expires_at": _pick(permission, "expires_at", "expiresAt", default=""),
    }
    missing = [
        key
        for key in ("external_tenant_id", "external_user_id", "client_id", "external_app_id")
        if not normalized.get(key)
    ]
    if missing:
        raise RuntimeError("EduPlus2 permission response missing required fields")
    if (
        normalized["external_tenant_id"] != external_tenant_id
        or normalized["external_user_id"] != external_user_id
        or normalized["client_id"] != client_id
        or normalized["external_app_id"] != external_app_id
    ):
        raise PermissionError("permission mismatch")
    if normalized["external_subject"] and normalized["external_subject"] != external_subject:
        raise PermissionError("permission mismatch")
    expires_at = _parse_timestamp(str(normalized["expires_at"] or ""))
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        raise PermissionError("permission expired")
    if not normalized["allowed"]:
        raise PermissionError(normalized["reason"] or "permission denied")
    normalized["summary"] = {
        "allowed": normalized["allowed"],
        "reason": normalized["reason"],
        "external_tenant_id": normalized["external_tenant_id"],
        "external_user_id": normalized["external_user_id"],
        "external_subject": normalized["external_subject"],
        "client_id": normalized["client_id"],
        "external_app_id": normalized["external_app_id"],
        "allowed_usages": list(normalized["allowed_usages"]),
        "scopes": list(normalized["scopes"]),
        "version": normalized["version"],
        "expires_at": normalized["expires_at"],
    }
    return normalized


class EduPlus2ResolveClient:
    """调用 EduPlus2 M2M token endpoint 与 OAuth client resolve API。"""

    def __init__(
        self,
        *,
        token_url: str,
        resolve_url: str,
        client_id: str,
        client_secret: str,
        http_client: httpx.AsyncClient | None = None,
        include: tuple[str, ...] = _DEFAULT_INCLUDE,
        timeout_seconds: float = 5.0,
        token_refresh_leeway_seconds: int = 30,
    ):
        if not token_url or not resolve_url or not client_id or not client_secret:
            raise ValueError("EduPlus2 resolve client configuration is incomplete")
        self.token_url = token_url
        self.resolve_url = resolve_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.include = tuple(include)
        self.timeout_seconds = float(timeout_seconds)
        self.token_refresh_leeway_seconds = int(token_refresh_leeway_seconds)
        self._http_client = http_client
        self._access_token = ""
        self._access_token_expires_at = 0.0

    async def _post_token(self) -> httpx.Response:
        client = self._http_client or httpx.AsyncClient()
        close = self._http_client is None
        try:
            response = await client.post(
                self.token_url,
                timeout=self.timeout_seconds,
                data={"grant_type": "client_credentials"},
                auth=httpx.BasicAuth(self.client_id, self.client_secret),
                headers={"Accept": "application/json"},
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"EduPlus2 token endpoint rejected request: {response.status_code}"
                )
            return response
        except httpx.HTTPError:
            raise RuntimeError("EduPlus2 token endpoint is unavailable") from None
        finally:
            if close:
                await client.aclose()

    async def _post_resolve(self, payload: dict[str, Any]) -> httpx.Response:
        access_token = await self._m2m_token()
        client = self._http_client or httpx.AsyncClient()
        close = self._http_client is None
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + access_token,
        }
        try:
            response = await client.post(
                self.resolve_url,
                timeout=self.timeout_seconds,
                json=payload,
                headers=headers,
            )
            if response.status_code >= 400:
                status = response.status_code
                payload = {"client_id": "<redacted>", "include": list(payload.get("include", []))}
                raise RuntimeError(
                    f"EduPlus2 resolve endpoint rejected request: {status}"
                )
            return response
        except httpx.HTTPError:
            raise RuntimeError("EduPlus2 resolve endpoint is unavailable") from None
        finally:
            access_token = "<redacted>"
            headers = {"Authorization": "<redacted>"}
            if close:
                await client.aclose()

    async def _m2m_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._access_token_expires_at:
            return self._access_token
        response = await self._post_token()
        try:
            payload = response.json()
        except json.JSONDecodeError:
            raise RuntimeError("EduPlus2 token response is invalid") from None
        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise RuntimeError("EduPlus2 token response is invalid")
        expires_in = int(payload.get("expires_in") or 60)
        self._access_token = access_token
        self._access_token_expires_at = now + max(1, expires_in - self.token_refresh_leeway_seconds)
        return access_token

    async def resolve_client(
        self, client_id: str, *, expected_tenant_id: Any | None = None
    ) -> dict[str, Any]:
        payload = {"client_id": client_id, "include": list(self.include)}
        if expected_tenant_id:
            payload["expected_tenant_id"] = expected_tenant_id
        response = await self._post_resolve(payload)
        try:
            payload = response.json()
        except json.JSONDecodeError:
            raise RuntimeError("EduPlus2 resolve response is invalid") from None
        code = payload.get("code")
        if code not in (None, 0, "0"):
            raise PermissionError(str(payload.get("message") or "resolve_rejected"))
        return normalize_resolve_response(client_id, payload)


class _EduPlus2AuthorizedJsonClient:
    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 5.0,
        token_refresh_leeway_seconds: int = 30,
    ):
        if not token_url or not client_id or not client_secret:
            raise ValueError("EduPlus2 client configuration is incomplete")
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout_seconds = float(timeout_seconds)
        self.token_refresh_leeway_seconds = int(token_refresh_leeway_seconds)
        self._http_client = http_client
        self._access_token = ""
        self._access_token_expires_at = 0.0

    async def _post_token(self) -> httpx.Response:
        client = self._http_client or httpx.AsyncClient()
        close = self._http_client is None
        try:
            response = await client.post(
                self.token_url,
                timeout=self.timeout_seconds,
                data={"grant_type": "client_credentials"},
                auth=httpx.BasicAuth(self.client_id, self.client_secret),
                headers={"Accept": "application/json"},
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"EduPlus2 token endpoint rejected request: {response.status_code}"
                )
            return response
        except httpx.HTTPError:
            raise RuntimeError("EduPlus2 token endpoint is unavailable") from None
        finally:
            if close:
                await client.aclose()

    async def _m2m_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._access_token_expires_at:
            return self._access_token
        response = await self._post_token()
        try:
            payload = response.json()
        except json.JSONDecodeError:
            raise RuntimeError("EduPlus2 token response is invalid") from None
        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise RuntimeError("EduPlus2 token response is invalid")
        expires_in = int(payload.get("expires_in") or 60)
        self._access_token = access_token
        self._access_token_expires_at = now + max(1, expires_in - self.token_refresh_leeway_seconds)
        return access_token

    async def _post_json(self, url: str, payload: dict[str, Any], *, endpoint: str) -> dict[str, Any]:
        access_token = await self._m2m_token()
        client = self._http_client or httpx.AsyncClient()
        close = self._http_client is None
        headers = {"Accept": "application/json", "Authorization": "Bearer " + access_token}
        try:
            response = await client.post(
                url,
                timeout=self.timeout_seconds,
                json=payload,
                headers=headers,
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"EduPlus2 {endpoint} endpoint rejected request: {response.status_code}"
                )
            try:
                data = response.json()
            except json.JSONDecodeError:
                raise RuntimeError(f"EduPlus2 {endpoint} response is invalid") from None
            if not isinstance(data, dict):
                raise RuntimeError(f"EduPlus2 {endpoint} response is invalid")
            return data
        except httpx.HTTPError:
            raise RuntimeError(f"EduPlus2 {endpoint} endpoint is unavailable") from None
        finally:
            access_token = "<redacted>"
            headers = {"Authorization": "<redacted>"}
            if close:
                await client.aclose()


class EduPlus2ProfileClient(_EduPlus2AuthorizedJsonClient):
    """调用 EduPlus2 profile API，并只返回最小可审计快照。"""

    def __init__(self, *, profile_url: str, **kwargs):
        if not profile_url:
            raise ValueError("EduPlus2 profile url is required")
        super().__init__(**kwargs)
        self.profile_url = profile_url

    async def fetch_profile(
        self,
        *,
        external_tenant_id: str,
        external_user_id: str,
        external_subject: str,
        client_id: str,
        external_app_id: str,
    ) -> dict[str, Any]:
        payload = {
            "tenant_id": external_tenant_id,
            "user_id": external_user_id,
            "subject": external_subject,
            "client_id": client_id,
            "app_id": external_app_id,
        }
        response = await self._post_json(self.profile_url, payload, endpoint="profile")
        return normalize_profile_response(
            external_tenant_id=external_tenant_id,
            external_user_id=external_user_id,
            external_subject=external_subject,
            payload=response,
        )


class EduPlus2PermissionClient(_EduPlus2AuthorizedJsonClient):
    """调用 EduPlus2 permission API，并规范化普通 DeepTutor 能力边界。"""

    def __init__(self, *, permission_url: str, **kwargs):
        if not permission_url:
            raise ValueError("EduPlus2 permission url is required")
        super().__init__(**kwargs)
        self.permission_url = permission_url

    async def check_permission(
        self,
        *,
        external_tenant_id: str,
        external_user_id: str,
        external_subject: str,
        client_id: str,
        external_app_id: str,
        requested_usages: tuple[str, ...] = ("deeptutor.chat",),
    ) -> dict[str, Any]:
        payload = {
            "tenant_id": external_tenant_id,
            "user_id": external_user_id,
            "subject": external_subject,
            "client_id": client_id,
            "app_id": external_app_id,
            "requested_usages": list(requested_usages),
        }
        response = await self._post_json(self.permission_url, payload, endpoint="permission")
        return normalize_permission_response(
            external_tenant_id=external_tenant_id,
            external_user_id=external_user_id,
            external_subject=external_subject,
            client_id=client_id,
            external_app_id=external_app_id,
            payload=response,
        )


def secret_fingerprint(value: str) -> str:
    """返回仅用于审计/排错的 secret 指纹，绝不返回 secret 本身。"""

    digest = hashlib.sha256(value.encode()).digest()
    return base64.urlsafe_b64encode(digest[:9]).rstrip(b"=").decode("ascii")


def parse_allowed_clients(
    raw: str | None, *, default_internal_tenant_id: str
) -> tuple[dict[str, str], ...]:
    """解析 `DT_EDUPLUS2_ALLOWED_CLIENTS`。

    推荐 JSON：
    `[{"client_id":"...","external_tenant_id":"...","external_app_id":"..."}]`
    也兼容 `client_id:tenant[:app]` 的分号/逗号分隔格式，便于本地 smoke。
    """

    if not raw:
        return ()
    value = raw.strip()
    records: list[dict[str, Any]]
    try:
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            records = [dict({"client_id": key}, **val) for key, val in decoded.items()]
        elif isinstance(decoded, list):
            records = [dict(item) for item in decoded if isinstance(item, dict)]
        else:
            raise ValueError
    except (json.JSONDecodeError, TypeError, ValueError):
        records = []
        for item in value.replace(";", ",").split(","):
            item = item.strip()
            if not item:
                continue
            parts = item.split(":")
            if len(parts) < 2:
                raise ValueError("invalid EduPlus2 allowed client entry")
            records.append(
                {
                    "client_id": parts[0],
                    "external_tenant_id": parts[1],
                    "external_app_id": parts[2] if len(parts) > 2 else "",
                    "internal_tenant_id": parts[3] if len(parts) > 3 else default_internal_tenant_id,
                }
            )
    parsed = []
    for record in records:
        client_id = str(record.get("client_id") or "").strip()
        tenant_id = str(
            record.get("external_tenant_id") or record.get("expected_tenant_id") or ""
        ).strip()
        if not client_id or not tenant_id:
            raise ValueError("invalid EduPlus2 allowed client entry")
        parsed.append(
            {
                "client_id": client_id,
                "external_tenant_id": tenant_id,
                "external_app_id": str(
                    record.get("external_app_id") or record.get("expected_app_id") or ""
                ).strip(),
                "internal_tenant_id": str(
                    record.get("internal_tenant_id") or default_internal_tenant_id
                ).strip(),
                "source": str(record.get("source") or "env_allowlist").strip(),
                "status": str(record.get("status") or "active").strip(),
            }
        )
    return tuple(parsed)
