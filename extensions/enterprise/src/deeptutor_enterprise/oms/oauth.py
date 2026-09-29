"""OMS 专用 EduPlus2 授权码登录会话。

本模块只负责把已由 EduPlus2 OIDC/JWKS 验签且在线状态有效的平台
身份保存为受限 OMS 浏览器会话；它不授予任何 ``ops.*`` 权限，后续
每个 OMS API 仍由 DeepTutor Enterprise 本地授权服务判定。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from jose import JWTError, jwt
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from ..configuration import resolve_secret
from .identity import trusted_oms_identity_from_token

logger = logging.getLogger(__name__)

OMS_TOKEN_COOKIE = "dt_oms_token"
OMS_REFRESH_COOKIE = "dt_oms_refresh"
OMS_CSRF_COOKIE = "dt_oms_csrf"
OMS_COOKIE_PATH = "/api/v1/oms"
OMS_CSRF_COOKIE_PATH = "/"
_STATE_TTL_SECONDS = 5 * 60
_DEFAULT_REFRESH_MAX_AGE_SECONDS = 14 * 24 * 60 * 60
_DEFAULT_SCOPE = "openid profile"
_DISABLED_FLAGS = {"0", "false", "off", "no"}
_ENABLED_FLAGS = {"1", "true", "on", "yes"}
_STATE_STORE: dict[str, "OmsLoginState"] = {}


class OmsLoginConfigurationError(RuntimeError):
    """OMS 登录配置缺失或显式关闭。"""


class OmsLoginStateError(RuntimeError):
    """授权码 state 不存在或已过期。"""


@dataclass(frozen=True, slots=True)
class OmsOauthConfig:
    authorization_endpoint: str
    token_endpoint: str
    client_id: str
    client_secret: str
    redirect_uri: str
    return_url: str
    scope: str = _DEFAULT_SCOPE


@dataclass(slots=True)
class OmsLoginState:
    state: str
    code_verifier: str
    redirect_uri: str
    return_url: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + _STATE_TTL_SECONDS)


def _cleanup_expired() -> None:
    now = time.time()
    for key, value in list(_STATE_STORE.items()):
        if value.expires_at <= now:
            _STATE_STORE.pop(key, None)


def _append_query(url: str, values: dict[str, str]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: value for key, value in values.items() if value})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _safe_url(value: str, *, allow_relative: bool = False) -> str:
    text = str(value or "").strip()
    if allow_relative and text.startswith("/"):
        return text
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OmsLoginConfigurationError("OMS login is not configured")
    if parsed.username or parsed.password:
        raise OmsLoginConfigurationError("OMS login is not configured")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _url_origin(value: str) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.username or parsed.password:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def _default_frontend_callback_url(request: Request) -> str:
    return f"{_request_origin(request)}/oms/auth/callback"


def _allowed_return_url(value: str, request: Request) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False
    request_origin = _request_origin(request)
    return_origin = f"{parsed.scheme}://{parsed.netloc}"
    if hmac.compare_digest(return_origin, request_origin):
        return True
    configured = _url_origin(os.environ.get("DT_EDUPLUS2_OMS_RETURN_URL", ""))
    return bool(configured and hmac.compare_digest(return_origin, configured))


def _resolve_return_url(request: Request) -> str:
    requested = str(request.query_params.get("return_to") or "").strip()
    if requested and _allowed_return_url(requested, request):
        return _safe_url(requested)
    configured = os.environ.get("DT_EDUPLUS2_OMS_RETURN_URL", "").strip()
    if configured:
        return _safe_url(configured, allow_relative=True)
    return f"{_request_origin(request)}/oms"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _login_enabled() -> bool:
    flag = os.environ.get("DT_EDUPLUS2_OMS_LOGIN_ENABLED", "").strip().lower()
    if flag in _DISABLED_FLAGS:
        return False
    if flag in _ENABLED_FLAGS:
        return True
    return True


def _secret_ref_for_client(client_id: str) -> str:
    explicit = os.environ.get("DT_EDUPLUS2_OMS_CLIENT_SECRET_REF", "").strip()
    if explicit:
        return explicit
    if os.environ.get("DT_EDUPLUS2_OMS_CLIENT_SECRET"):
        return "env:DT_EDUPLUS2_OMS_CLIENT_SECRET"
    # 只有通用前置应用 client 与 OMS client 确认为同一个时，才复用其 secret。
    if os.environ.get("DT_EDUPLUS2_CLIENT_ID", "").strip() == client_id:
        ref = os.environ.get("DT_EDUPLUS2_CLIENT_SECRET_REF", "").strip()
        if ref:
            return ref
        if os.environ.get("DT_EDUPLUS2_CLIENT_SECRET"):
            return "env:DT_EDUPLUS2_CLIENT_SECRET"
    return ""


def load_config(request: Request) -> OmsOauthConfig:
    if not _login_enabled():
        raise OmsLoginConfigurationError("OMS login is disabled")
    authorization_endpoint = _safe_url(
        os.environ.get("DT_EDUPLUS2_OMS_AUTHORIZATION_ENDPOINT", "").strip()
        or os.environ.get("DT_EDUPLUS2_AUTHORIZATION_ENDPOINT", "")
    )
    token_endpoint = _safe_url(
        os.environ.get("DT_EDUPLUS2_OMS_TOKEN_ENDPOINT", "").strip()
        or os.environ.get("DT_EDUPLUS2_TOKEN_ENDPOINT", "")
    )
    client_id = (
        os.environ.get("DT_EDUPLUS2_OMS_CLIENT_ID", "").strip()
        or "eduplus-platform-admin"
    )
    redirect_uri = os.environ.get("DT_EDUPLUS2_OMS_REDIRECT_URI", "").strip()
    redirect_uri = _safe_url(redirect_uri) if redirect_uri else _default_frontend_callback_url(request)
    secret_ref = _secret_ref_for_client(client_id)
    scope = os.environ.get("DT_EDUPLUS2_OMS_SCOPES", _DEFAULT_SCOPE).strip() or _DEFAULT_SCOPE
    return OmsOauthConfig(
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        client_id=client_id,
        client_secret=resolve_secret(secret_ref) if secret_ref else "",
        redirect_uri=redirect_uri,
        return_url=_resolve_return_url(request),
        scope=scope,
    )


def create_authorization_redirect(request: Request) -> RedirectResponse:
    _cleanup_expired()
    config = load_config(request)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    _STATE_STORE[state] = OmsLoginState(
        state=state,
        code_verifier=verifier,
        redirect_uri=config.redirect_uri,
        return_url=config.return_url,
    )
    redirect_url = _append_query(
        config.authorization_endpoint,
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": config.scope,
            "state": state,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        },
    )
    return RedirectResponse(redirect_url, status_code=303)


async def _exchange_code(config: OmsOauthConfig, state: OmsLoginState, code: str) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": state.redirect_uri,
        "client_id": config.client_id,
        "code_verifier": state.code_verifier,
    }
    auth = httpx.BasicAuth(config.client_id, config.client_secret) if config.client_secret else None
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                config.token_endpoint,
                timeout=10.0,
                data=data,
                auth=auth,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError:
            raise RuntimeError("OMS token endpoint is unavailable") from None
    if response.status_code >= 400:
        raise RuntimeError("OMS authorization code exchange failed")
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("OMS token response is invalid") from None
    if not isinstance(payload, dict):
        raise RuntimeError("OMS token response is invalid")
    return payload


async def _refresh_access_token(config: OmsOauthConfig, refresh_token: str) -> dict[str, Any]:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": config.client_id,
    }
    auth = httpx.BasicAuth(config.client_id, config.client_secret) if config.client_secret else None
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                config.token_endpoint,
                timeout=10.0,
                data=data,
                auth=auth,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError:
            raise RuntimeError("OMS token endpoint is unavailable") from None
    if response.status_code >= 400:
        raise RuntimeError("OMS refresh token exchange failed")
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("OMS token response is invalid") from None
    if not isinstance(payload, dict):
        raise RuntimeError("OMS token response is invalid")
    return payload


def _token_candidates(payload: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for name in ("access_token", "id_token"):
        value = str(payload.get(name) or "").strip()
        if value and value.count(".") == 2 and value not in result:
            result.append(value)
    return result


def _safe_claim_summary(token: str) -> dict[str, Any]:
    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError:
        return {"jwt": "unreadable"}
    subject = str(claims.get("sub") or "").strip()
    audience = claims.get("aud")
    if isinstance(audience, str):
        audience_summary: str | list[str] = audience
    elif isinstance(audience, list):
        audience_summary = sorted(str(item) for item in audience if item is not None)
    else:
        audience_summary = []
    return {
        "iss": str(claims.get("iss") or ""),
        "aud": audience_summary,
        "azp": str(claims.get("azp") or ""),
        "typ": str(claims.get("typ") or ""),
        "subject_hash": hashlib.sha256(subject.encode()).hexdigest()[:16] if subject else "",
        "has_iat": claims.get("iat") is not None,
        "has_exp": claims.get("exp") is not None,
    }


def _max_age_from_token(token: str) -> int:
    try:
        claims = jwt.get_unverified_claims(token)
        exp = int(claims.get("exp") or 0)
    except (JWTError, TypeError, ValueError):
        exp = 0
    now = int(time.time())
    if exp <= now:
        return 60
    return max(60, min(exp - now, 3600))


def _refresh_max_age_seconds() -> int:
    raw = os.environ.get("DT_EDUPLUS2_OMS_REFRESH_MAX_AGE_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_REFRESH_MAX_AGE_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_REFRESH_MAX_AGE_SECONDS
    return max(300, min(value, 30 * 24 * 60 * 60))


async def _select_verified_token(enterprise, payload: dict[str, Any]) -> str:
    last_error: Exception | None = None
    for index, token in enumerate(_token_candidates(payload)):
        try:
            await trusted_oms_identity_from_token(enterprise, token)
            return token
        except Exception as exc:  # noqa: BLE001 - 只保存分类，不能回显 token/响应。
            last_error = exc
            logger.warning(
                "OMS OAuth token candidate rejected index=%s claims=%s failure_type=%s "
                "failure_reason=%s",
                index,
                _safe_claim_summary(token),
                type(exc).__name__,
                str(exc),
            )
    if last_error is not None:
        raise RuntimeError("OMS platform token verification failed") from last_error
    raise RuntimeError("OMS token response missing platform JWT")


def _classify_error(exc: Exception) -> str:
    text = str(exc)
    if isinstance(exc, OmsLoginConfigurationError):
        return "not_configured"
    if isinstance(exc, PermissionError):
        return "identity_denied"
    if "exchange failed" in text:
        return "code_exchange_failed"
    if "token response" in text:
        return "token_response_invalid"
    if "verification failed" in text:
        return "identity_verification_failed"
    if "unavailable" in text:
        return "external_unavailable"
    return "service_unavailable"


def _json_error(reason: str, status_code: int) -> JSONResponse:
    return JSONResponse({"detail": reason}, status_code=status_code)


def _callback_payload_value(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    return str(value or "").strip() if value is not None else ""


def _set_oms_session_cookies(
    response: JSONResponse | RedirectResponse,
    *,
    access_token: str,
    refresh_token: str,
) -> None:
    access_max_age = _max_age_from_token(access_token)
    refresh_max_age = _refresh_max_age_seconds()
    response.set_cookie(
        OMS_TOKEN_COOKIE,
        access_token,
        max_age=access_max_age,
        httponly=True,
        secure=True,
        samesite="lax",
        path=OMS_COOKIE_PATH,
    )
    response.set_cookie(
        OMS_REFRESH_COOKIE,
        refresh_token,
        max_age=refresh_max_age,
        httponly=True,
        secure=True,
        samesite="lax",
        path=OMS_COOKIE_PATH,
    )
    response.set_cookie(
        OMS_CSRF_COOKIE,
        secrets.token_urlsafe(32),
        max_age=refresh_max_age,
        secure=True,
        samesite="lax",
        path=OMS_CSRF_COOKIE_PATH,
    )
    response.delete_cookie(OMS_CSRF_COOKIE, path=OMS_COOKIE_PATH, secure=True, samesite="lax")


def _oms_csrf_valid(request: Request) -> bool:
    csrf = str(request.headers.get("x-csrf-token") or "").strip()
    cookie = str(request.cookies.get(OMS_CSRF_COOKIE) or "").strip()
    return bool(csrf and cookie and hmac.compare_digest(csrf, cookie))


async def handle_frontend_callback(request: Request, enterprise) -> JSONResponse:
    """Exchange frontend-received authorization code inside the BFF boundary."""

    _cleanup_expired()
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - 只返回通用错误，不暴露请求内容。
        return _json_error("Invalid request", 422)
    if not isinstance(payload, dict):
        return _json_error("Invalid request", 422)
    state_value = _callback_payload_value(payload, "state")
    state = _STATE_STORE.pop(state_value, None) if state_value else None
    if state is None or state.expires_at <= time.time():
        return _json_error("state_invalid", 400)
    provider_error = _callback_payload_value(payload, "error")
    if provider_error:
        return _json_error("authorization_denied", 400)
    code = _callback_payload_value(payload, "code")
    if not code:
        return _json_error("code_missing", 400)
    try:
        config = load_config(request)
        token_payload = await _exchange_code(config, state, code)
        refresh_token = str(token_payload.get("refresh_token") or "").strip()
        if not refresh_token:
            raise RuntimeError("OMS token response missing refresh token")
        platform_token = await _select_verified_token(enterprise, token_payload)
    except Exception as exc:  # noqa: BLE001 - 只回传诊断码，不暴露 secret/token。
        return _json_error(_classify_error(exc), 400)
    response = JSONResponse({"authenticated": True, "return_url": state.return_url})
    _set_oms_session_cookies(
        response,
        access_token=platform_token,
        refresh_token=refresh_token,
    )
    return response


async def refresh_session(request: Request, enterprise) -> JSONResponse:
    refresh_token = str(request.cookies.get(OMS_REFRESH_COOKIE) or "").strip()
    if not refresh_token:
        return JSONResponse({"authenticated": False}, status_code=401)
    if not _oms_csrf_valid(request):
        return _json_error("csrf_invalid", 403)
    try:
        config = load_config(request)
        token_payload = await _refresh_access_token(config, refresh_token)
        next_refresh_token = str(token_payload.get("refresh_token") or "").strip() or refresh_token
        platform_token = await _select_verified_token(enterprise, token_payload)
    except Exception as exc:  # noqa: BLE001 - 不回显 token/secret。
        response = _json_error(_classify_error(exc), 401)
        response.delete_cookie(OMS_TOKEN_COOKIE, path=OMS_COOKIE_PATH, secure=True, samesite="lax")
        response.delete_cookie(OMS_REFRESH_COOKIE, path=OMS_COOKIE_PATH, secure=True, samesite="lax")
        response.delete_cookie(
            OMS_CSRF_COOKIE,
            path=OMS_CSRF_COOKIE_PATH,
            secure=True,
            samesite="lax",
        )
        response.delete_cookie(OMS_CSRF_COOKIE, path=OMS_COOKIE_PATH, secure=True, samesite="lax")
        return response
    response = JSONResponse({"authenticated": True})
    _set_oms_session_cookies(
        response,
        access_token=platform_token,
        refresh_token=next_refresh_token,
    )
    return response


async def status_response(request: Request, enterprise) -> JSONResponse:
    token = str(request.cookies.get(OMS_TOKEN_COOKIE) or "")
    if not token:
        return JSONResponse({"authenticated": False}, status_code=401)
    try:
        actor = await trusted_oms_identity_from_token(enterprise, token)
    except PermissionError:
        return JSONResponse({"authenticated": False}, status_code=401)
    except RuntimeError:
        return JSONResponse({"authenticated": False}, status_code=503)
    return JSONResponse(
        {
            "authenticated": True,
            "application": actor.application,
            "issuer": actor.issuer,
            "subject_hash": hashlib.sha256(actor.subject.encode()).hexdigest()[:16],
            "external_active": actor.external_active,
        }
    )


def logout_response() -> JSONResponse:
    response = JSONResponse({"success": True})
    response.delete_cookie(OMS_TOKEN_COOKIE, path=OMS_COOKIE_PATH, secure=True, samesite="lax")
    response.delete_cookie(OMS_REFRESH_COOKIE, path=OMS_COOKIE_PATH, secure=True, samesite="lax")
    response.delete_cookie(
        OMS_CSRF_COOKIE,
        path=OMS_CSRF_COOKIE_PATH,
        secure=True,
        samesite="lax",
    )
    response.delete_cookie(OMS_CSRF_COOKIE, path=OMS_COOKIE_PATH, secure=True, samesite="lax")
    return response
