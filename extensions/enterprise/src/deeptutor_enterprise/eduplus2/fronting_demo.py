"""Local/test EduPlus2 统一认证前置应用 demo。

该模块只服务 `/auth/eduplus2/demo/*` 路由：它生成 OIDC state/PKCE，
接收 authorization-code callback，并复用现有 ``exchange_user_jwt`` 换取
DeepTutor 短期 token。所有持久化生产登录能力均不在这里实现。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

import httpx
from jose import JWTError, jwt
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from ..configuration import resolve_secret

_DEFAULT_SCOPES = "openid profile offline_access"
_STATE_TTL_SECONDS = 5 * 60
_RESULT_TTL_SECONDS = 5 * 60
_DISABLED_FLAGS = {"0", "false", "off", "no"}
_ENABLED_FLAGS = {"1", "true", "on", "yes"}
_STATE_STORE: dict[str, "DemoState"] = {}
_RESULT_STORE: dict[str, "DemoResult"] = {}
_EXCHANGE_REQUIRED_CLAIMS = ("iss", "exp", "iat", "tid", "eui", "sub", "azp")


class FrontingDemoConfigurationError(RuntimeError):
    """Demo 启动配置缺失或被禁用；错误文本必须可公开展示。"""


class FrontingDemoStateError(RuntimeError):
    """state/session 不存在或已过期。"""


@dataclass(frozen=True, slots=True)
class FrontingDemoConfig:
    authorization_endpoint: str
    token_endpoint: str
    client_id: str
    client_secret: str
    redirect_uri: str
    return_url: str
    scopes: str = _DEFAULT_SCOPES


@dataclass(slots=True)
class DemoState:
    state: str
    code_verifier: str
    redirect_uri: str
    return_url: str
    request_id: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + _STATE_TTL_SECONDS)


@dataclass(slots=True)
class DemoResult:
    ok: bool
    request_id: str
    token_type: str
    dt_token: str
    summary: dict[str, Any]
    steps: list[dict[str, Any]]
    refresh_token: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + _RESULT_TTL_SECONDS)

    def to_response(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "request_id": self.request_id,
            "token_type": self.token_type,
            # 仅供 demo 页面内存态 API probe 使用；页面不得渲染或持久化。
            "dt_token": self.dt_token,
            "summary": self.summary,
            "steps": self.steps,
            "created_at": int(self.created_at),
            "expires_at": int(self.expires_at),
        }


def _cleanup_expired() -> None:
    now = time.time()
    for key, state in list(_STATE_STORE.items()):
        if state.expires_at <= now:
            _STATE_STORE.pop(key, None)
    for key, result in list(_RESULT_STORE.items()):
        if result.expires_at <= now:
            _RESULT_STORE.pop(key, None)


def _append_query(url: str, values: dict[str, str]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: value for key, value in values.items() if value})
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            "",
        )
    )


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _hash_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:16]


def _looks_like_jwt(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 3 and all(parts)


def _unverified_jwt_claims(value: str) -> dict[str, Any]:
    if not _looks_like_jwt(value):
        return {}
    try:
        claims = jwt.get_unverified_claims(value)
    except JWTError:
        return {}
    return claims if isinstance(claims, dict) else {}


def _missing_exchange_claims(value: str) -> list[str]:
    claims = _unverified_jwt_claims(value)
    if not claims:
        return list(_EXCHANGE_REQUIRED_CLAIMS)
    return [claim for claim in _EXCHANGE_REQUIRED_CLAIMS if not claims.get(claim)]


def _jwt_public_diagnostics(value: str) -> dict[str, Any]:
    if not _looks_like_jwt(value):
        return {}
    try:
        header = jwt.get_unverified_header(value)
    except JWTError:
        header = {}
    claims = _unverified_jwt_claims(value)
    audience = claims.get("aud")
    if isinstance(audience, list):
        safe_audience: Any = [str(item) for item in audience if item]
    else:
        safe_audience = str(audience or "")
    now = int(time.time())

    def _delta_seconds(name: str) -> int | None:
        raw = claims.get(name)
        try:
            return int(raw) - now
        except (TypeError, ValueError):
            return None

    return {
        "header_alg": str(header.get("alg") or ""),
        "header_kid_hash": _hash_identifier(header.get("kid")),
        "claim_issuer": str(claims.get("iss") or ""),
        "claim_audience": safe_audience,
        "claim_azp": str(claims.get("azp") or ""),
        "claim_tid_hash": _hash_identifier(claims.get("tid")),
        "claim_eui_hash": _hash_identifier(claims.get("eui")),
        "claim_sub_hash": _hash_identifier(claims.get("sub")),
        "claim_iat_delta_seconds": _delta_seconds("iat"),
        "claim_nbf_delta_seconds": _delta_seconds("nbf"),
        "claim_exp_delta_seconds": _delta_seconds("exp"),
    }


def _token_diagnostics(payload: dict[str, Any], *, selected_token_name: str = "") -> dict[str, Any]:
    diagnostics: dict[str, Any] = {"selected_token": selected_token_name}
    for name in ("id_token", "access_token"):
        token = str(payload.get(name) or "").strip()
        missing = _missing_exchange_claims(token) if _looks_like_jwt(token) else []
        diagnostics[name] = {
            "present": bool(token),
            "jwt": _looks_like_jwt(token),
            "has_exchange_claims": bool(token) and _looks_like_jwt(token) and not missing,
            "missing_exchange_claims": missing,
            **_jwt_public_diagnostics(token),
        }
    selected = diagnostics.get(selected_token_name)
    if isinstance(selected, dict):
        diagnostics.update(
            {
                "selected_header_alg": selected.get("header_alg", ""),
                "selected_header_kid_hash": selected.get("header_kid_hash", ""),
                "selected_claim_issuer": selected.get("claim_issuer", ""),
                "selected_claim_audience": selected.get("claim_audience", ""),
                "selected_claim_azp": selected.get("claim_azp", ""),
                "selected_claim_iat_delta_seconds": selected.get("claim_iat_delta_seconds"),
                "selected_claim_nbf_delta_seconds": selected.get("claim_nbf_delta_seconds"),
                "selected_claim_exp_delta_seconds": selected.get("claim_exp_delta_seconds"),
            }
        )
    return diagnostics


def _select_user_jwt_entry(payload: dict[str, Any]) -> tuple[str, str]:
    jwt_candidates = [
        (name, str(payload.get(name) or "").strip())
        for name in ("id_token", "access_token")
        if _looks_like_jwt(str(payload.get(name) or "").strip())
    ]
    for name, token in jwt_candidates:
        if not _missing_exchange_claims(token):
            return name, token
    if jwt_candidates:
        return jwt_candidates[0]
    return "", ""


def _safe_url(value: str, *, allow_relative: bool = False) -> str:
    text = str(value or "").strip()
    if allow_relative and text.startswith("/"):
        return text
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise FrontingDemoConfigurationError("EduPlus2 demo is not configured")
    if parsed.username or parsed.password:
        raise FrontingDemoConfigurationError("EduPlus2 demo is not configured")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _is_loopback_host(hostname: str | None) -> bool:
    return hostname in {"127.0.0.1", "localhost", "::1"}


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


def _allowed_return_url(value: str, request: Request) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False
    request_origin = f"{request.url.scheme}://{request.url.netloc}"
    return_origin = f"{parsed.scheme}://{parsed.netloc}"
    if return_origin == request_origin:
        return True
    configured_return_origin = _url_origin(os.environ.get("DT_EDUPLUS2_FRONTING_DEMO_RETURN_URL", ""))
    if configured_return_origin and return_origin == configured_return_origin:
        return True
    # 本地 demo 常见形态：Next dev 和 API server 不同 loopback 端口。
    return _is_loopback_host(parsed.hostname) and parsed.scheme == "http"


def _resolve_return_url(request: Request) -> str:
    requested = str(request.query_params.get("return_to") or "").strip()
    if requested and _allowed_return_url(requested, request):
        return _safe_url(requested)
    configured = os.environ.get("DT_EDUPLUS2_FRONTING_DEMO_RETURN_URL", "").strip()
    if configured:
        return _safe_url(configured, allow_relative=True)
    return f"{request.url.scheme}://{request.url.netloc}/enterprise/eduplus2/fronting-demo"


def _demo_enabled() -> bool:
    flag = os.environ.get("DT_EDUPLUS2_FRONTING_DEMO_ENABLED", "").strip().lower()
    if flag in _DISABLED_FLAGS:
        return False
    if flag in _ENABLED_FLAGS:
        return True
    # 未设置时由配置完整性决定；该路由仍然是 demo-only，且缺项 fail closed。
    return True


def load_config(request: Request) -> FrontingDemoConfig:
    if not _demo_enabled():
        raise FrontingDemoConfigurationError("EduPlus2 demo is disabled")
    authorization_endpoint = _safe_url(os.environ.get("DT_EDUPLUS2_AUTHORIZATION_ENDPOINT", ""))
    token_endpoint = _safe_url(os.environ.get("DT_EDUPLUS2_TOKEN_ENDPOINT", ""))
    client_id = os.environ.get("DT_EDUPLUS2_CLIENT_ID", "").strip()
    secret_ref = os.environ.get("DT_EDUPLUS2_CLIENT_SECRET_REF", "").strip()
    if not secret_ref and os.environ.get("DT_EDUPLUS2_CLIENT_SECRET"):
        secret_ref = "env:DT_EDUPLUS2_CLIENT_SECRET"
    if not client_id or not secret_ref:
        raise FrontingDemoConfigurationError("EduPlus2 demo is not configured")
    client_secret = resolve_secret(secret_ref)
    redirect_uri = os.environ.get("DT_EDUPLUS2_FRONTING_DEMO_REDIRECT_URI", "").strip()
    if redirect_uri:
        redirect_uri = _safe_url(redirect_uri)
    else:
        redirect_uri = str(request.url_for("eduplus2_demo_callback"))
    scopes = os.environ.get("DT_EDUPLUS2_FRONTING_DEMO_SCOPES", _DEFAULT_SCOPES).strip()
    return FrontingDemoConfig(
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        return_url=_resolve_return_url(request),
        scopes=scopes or _DEFAULT_SCOPES,
    )


def create_authorization_redirect(request: Request) -> RedirectResponse:
    _cleanup_expired()
    config = load_config(request)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    request_id = request.headers.get("x-request-id") or f"demo-{uuid.uuid4().hex}"
    _STATE_STORE[state] = DemoState(
        state=state,
        code_verifier=verifier,
        redirect_uri=config.redirect_uri,
        return_url=config.return_url,
        request_id=request_id,
    )
    redirect_url = _append_query(
        config.authorization_endpoint,
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": config.scopes,
            "state": state,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        },
    )
    return RedirectResponse(redirect_url, status_code=303)


async def exchange_authorization_code(
    config: FrontingDemoConfig,
    state: DemoState,
    code: str,
) -> dict[str, Any]:
    client = httpx.AsyncClient()
    try:
        response = await client.post(
            config.token_endpoint,
            timeout=10.0,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": state.redirect_uri,
                "client_id": config.client_id,
                "code_verifier": state.code_verifier,
            },
            auth=httpx.BasicAuth(config.client_id, config.client_secret),
            headers={"Accept": "application/json"},
        )
        if response.status_code >= 400:
            raise RuntimeError("EduPlus2 authorization code exchange failed")
        try:
            payload = response.json()
        except json.JSONDecodeError:
            raise RuntimeError("EduPlus2 token response is invalid") from None
        if not isinstance(payload, dict):
            raise RuntimeError("EduPlus2 token response is invalid")
        return payload
    except httpx.HTTPError:
        raise RuntimeError("EduPlus2 token endpoint is unavailable") from None
    finally:
        await client.aclose()


async def refresh_user_token(config: FrontingDemoConfig, refresh_token: str) -> dict[str, Any]:
    if not refresh_token:
        raise RuntimeError("EduPlus2 refresh token is unavailable")
    client = httpx.AsyncClient()
    try:
        response = await client.post(
            config.token_endpoint,
            timeout=10.0,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": config.client_id,
            },
            auth=httpx.BasicAuth(config.client_id, config.client_secret),
            headers={"Accept": "application/json"},
        )
        if response.status_code >= 400:
            raise RuntimeError("EduPlus2 refresh grant failed")
        try:
            payload = response.json()
        except json.JSONDecodeError:
            raise RuntimeError("EduPlus2 refresh response is invalid") from None
        if not isinstance(payload, dict):
            raise RuntimeError("EduPlus2 refresh response is invalid")
        return payload
    except httpx.HTTPError:
        raise RuntimeError("EduPlus2 token endpoint is unavailable") from None
    finally:
        await client.aclose()


def select_user_jwt(payload: dict[str, Any]) -> str:
    _name, token = _select_user_jwt_entry(payload)
    if token:
        return token
    raise RuntimeError("EduPlus2 token response missing user JWT")


def _failure_steps(reason: str) -> list[dict[str, Any]]:
    return [
        {"id": "redirect", "status": "done", "label": "EduPlus2 Redirect"},
        {
            "id": "code_exchange",
            "status": "failed",
            "label": "Authorization Code Token Exchange",
            "reason": reason,
        },
        {"id": "deeptutor_exchange", "status": "skipped", "label": "DeepTutor Token Exchange"},
        {"id": "api_probe", "status": "skipped", "label": "DeepTutor API Probe"},
        {"id": "ws_chat", "status": "skipped", "label": "DeepTutor WebSocket Chat"},
        {"id": "token_refresh", "status": "skipped", "label": "Token Refresh"},
    ]


def _success_steps() -> list[dict[str, Any]]:
    return [
        {"id": "redirect", "status": "done", "label": "EduPlus2 Redirect"},
        {"id": "code_exchange", "status": "done", "label": "Authorization Code Token Exchange"},
        {"id": "deeptutor_exchange", "status": "done", "label": "DeepTutor Token Exchange"},
        {"id": "api_probe", "status": "pending", "label": "DeepTutor API Probe"},
        {"id": "ws_chat", "status": "idle", "label": "DeepTutor WebSocket Chat"},
        {"id": "token_refresh", "status": "idle", "label": "Token Refresh"},
    ]


def _store_result(result: DemoResult) -> str:
    _cleanup_expired()
    session_id = secrets.token_urlsafe(32)
    _RESULT_STORE[session_id] = result
    return session_id


def _claims_summary(user_token: str, exchange: dict[str, Any], request_id: str) -> dict[str, Any]:
    try:
        claims = jwt.get_unverified_claims(user_token)
    except JWTError:
        claims = {}
    return {
        "request_id": request_id,
        "client_id": str(claims.get("azp") or ""),
        "external_tenant_hash": _hash_identifier(claims.get("tid")),
        "external_user_hash": _hash_identifier(claims.get("eui") or claims.get("sub")),
        "internal_tenant_hash": _hash_identifier(exchange.get("tenant_id")),
        "internal_user_hash": _hash_identifier(exchange.get("user_id")),
        "client_registration_hash": _hash_identifier(exchange.get("client_registration_id")),
        "expires_at": int(exchange.get("expires_at") or 0),
    }


def _safe_error_redirect(return_url: str, *, error: str, request_id: str = "") -> RedirectResponse:
    return RedirectResponse(
        _append_query(return_url, {"demo_error": error, "request_id": request_id}),
        status_code=303,
    )


def _error_code(exc: Exception) -> str:
    if isinstance(exc, PermissionError):
        reason = str(exc)
        if "rate limited" in reason:
            return "deeptutor_rate_limited"
        if "tenant mismatch" in reason:
            return "deeptutor_tenant_mismatch"
        if "inactive" in reason or "registered" in reason:
            return "deeptutor_forbidden"
        return "deeptutor_unauthorized"
    if isinstance(exc, ValueError):
        return "deeptutor_conflict"
    return "service_unavailable"


def _safe_permission_detail(exc: Exception) -> str:
    reason = str(exc)
    if "required EduPlus2 JWT claims are missing" in reason:
        return "exchange_jwt_missing_required_claims"
    if "JWT verification failed" in reason:
        return "exchange_jwt_verification_failed"
    if "JWT expired" in reason:
        return "exchange_jwt_expired"
    if "JWT not yet valid" in reason:
        return "exchange_jwt_not_yet_valid"
    if "signature verification failed" in reason:
        return "exchange_jwt_signature_verification_failed"
    if "audience rejected" in reason:
        return "exchange_jwt_audience_rejected"
    if "token issuer mismatch" in reason:
        return "exchange_jwt_token_issuer_mismatch"
    if "issuer mismatch" in reason:
        return "exchange_jwt_issuer_mismatch"
    if "algorithm is not allowed" in reason:
        return "exchange_jwt_algorithm_not_allowed"
    if "JWKS kid is not trusted" in reason:
        return "exchange_jwt_kid_not_trusted"
    if "iat is in the future" in reason:
        return "exchange_jwt_iat_in_future"
    if "tenant mismatch" in reason:
        return "tenant_mismatch"
    if "rate limited" in reason:
        return "rate_limited"
    if "inactive" in reason:
        return "inactive"
    if "registered" in reason:
        return "registration_not_active"
    return "permission_denied"


def _safe_error_detail(exc: Exception) -> str:
    """把内部异常归类为可展示诊断码，避免把 secret/token/响应正文带到页面。"""

    if isinstance(exc, PermissionError):
        return _safe_permission_detail(exc)
    reason = str(exc)
    checks = (
        ("EduPlus2 token endpoint rejected request", "eduplus2_token_endpoint_rejected"),
        ("EduPlus2 token endpoint is unavailable", "eduplus2_token_endpoint_unavailable"),
        ("EduPlus2 token response is invalid", "eduplus2_token_response_invalid"),
        ("EduPlus2 resolve endpoint rejected request", "eduplus2_resolve_endpoint_rejected"),
        ("EduPlus2 resolve endpoint is unavailable", "eduplus2_resolve_endpoint_unavailable"),
        ("EduPlus2 resolve response is invalid", "eduplus2_resolve_response_invalid"),
        ("EduPlus2 profile endpoint rejected request", "eduplus2_profile_endpoint_rejected"),
        ("EduPlus2 profile endpoint is unavailable", "eduplus2_profile_endpoint_unavailable"),
        ("EduPlus2 profile response is invalid", "eduplus2_profile_response_invalid"),
        ("profile unavailable", "eduplus2_profile_unavailable"),
        (
            "EduPlus2 permission endpoint rejected request",
            "eduplus2_permission_endpoint_rejected",
        ),
        (
            "EduPlus2 permission endpoint is unavailable",
            "eduplus2_permission_endpoint_unavailable",
        ),
        ("EduPlus2 permission response is invalid", "eduplus2_permission_response_invalid"),
        ("permission unavailable", "eduplus2_permission_unavailable"),
        ("EduPlus2 token response missing user JWT", "eduplus2_user_jwt_missing"),
    )
    for needle, code in checks:
        if needle in reason:
            return code
    return _error_code(exc)


async def handle_callback(request: Request, enterprise) -> RedirectResponse:
    _cleanup_expired()
    state_value = str(request.query_params.get("state") or "").strip()
    state = _STATE_STORE.pop(state_value, None) if state_value else None
    if state is None or state.expires_at <= time.time():
        fallback = os.environ.get(
            "DT_EDUPLUS2_FRONTING_DEMO_RETURN_URL",
            f"{request.url.scheme}://{request.url.netloc}/enterprise/eduplus2/fronting-demo",
        )
        return _safe_error_redirect(fallback, error="state_invalid")

    provider_error = str(request.query_params.get("error") or "").strip()
    if provider_error:
        session_id = _store_result(
            DemoResult(
                ok=False,
                request_id=state.request_id,
                token_type="",
                dt_token="",
                summary={"request_id": state.request_id, "reason": "authorization_denied"},
                steps=_failure_steps("authorization_denied"),
            )
        )
        return RedirectResponse(
            _append_query(state.return_url, {"demo_session": session_id, "request_id": state.request_id}),
            status_code=303,
        )

    code = str(request.query_params.get("code") or "").strip()
    if not code:
        session_id = _store_result(
            DemoResult(
                ok=False,
                request_id=state.request_id,
                token_type="",
                dt_token="",
                summary={"request_id": state.request_id, "reason": "code_missing"},
                steps=_failure_steps("code_missing"),
            )
        )
        return RedirectResponse(
            _append_query(state.return_url, {"demo_session": session_id, "request_id": state.request_id}),
            status_code=303,
        )

    token_payload: dict[str, Any] = {}
    user_token_name = ""
    try:
        config = load_config(request)
        token_payload = await exchange_authorization_code(config, state, code)
        user_token_name, user_token = _select_user_jwt_entry(token_payload)
        if not user_token:
            raise RuntimeError("EduPlus2 token response missing user JWT")
        exchange = await enterprise.eduplus2.exchange_user_jwt(
            user_token,
            request_id=state.request_id,
        )
        refresh_token = str(token_payload.get("refresh_token") or "").strip()
        session_id = _store_result(
            DemoResult(
                ok=True,
                request_id=state.request_id,
                token_type=str(exchange.get("token_type") or "Bearer"),
                dt_token=str(exchange["dt_token"]),
                summary={
                    **_claims_summary(user_token, exchange, state.request_id),
                    "selected_token": user_token_name,
                },
                steps=_success_steps(),
                refresh_token=refresh_token,
            )
        )
        return RedirectResponse(
            _append_query(state.return_url, {"demo_session": session_id, "request_id": state.request_id}),
            status_code=303,
        )
    except Exception as exc:
        reason = _error_code(exc)
        detail = _safe_error_detail(exc)
        session_id = _store_result(
            DemoResult(
                ok=False,
                request_id=state.request_id,
                token_type="",
                dt_token="",
                summary={
                    "request_id": state.request_id,
                    "reason": reason,
                    "detail": detail,
                    **_token_diagnostics(
                        token_payload if isinstance(token_payload, dict) else {},
                        selected_token_name=user_token_name,
                    ),
                },
                steps=_failure_steps(reason),
            )
        )
        return RedirectResponse(
            _append_query(state.return_url, {"demo_session": session_id, "request_id": state.request_id}),
            status_code=303,
        )


def result_response(request: Request) -> JSONResponse:
    _cleanup_expired()
    session_id = str(request.query_params.get("demo_session") or "").strip()
    result = _RESULT_STORE.get(session_id)
    if result is None:
        return JSONResponse({"detail": "Demo session not found"}, status_code=404)
    return JSONResponse(result.to_response())


async def refresh_response(request: Request, enterprise) -> JSONResponse:
    _cleanup_expired()
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"detail": "Invalid request"}, status_code=422)
    if not isinstance(payload, dict):
        return JSONResponse({"detail": "Invalid request"}, status_code=422)
    session_id = str(payload.get("demo_session") or "").strip()
    result = _RESULT_STORE.get(session_id)
    if result is None:
        return JSONResponse({"detail": "Demo session not found"}, status_code=404)
    if not result.refresh_token:
        return JSONResponse({"detail": "EduPlus2 refresh token is unavailable"}, status_code=428)
    try:
        config = load_config(request)
        token_payload = await refresh_user_token(config, result.refresh_token)
        user_token = select_user_jwt(token_payload)
        exchange = await enterprise.eduplus2.exchange_user_jwt(
            user_token,
            request_id=result.request_id,
        )
    except PermissionError:
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    except ValueError:
        return JSONResponse({"detail": "Operation conflict"}, status_code=409)
    except FrontingDemoConfigurationError as exc:
        return configuration_error_response(exc)
    except RuntimeError:
        return JSONResponse({"detail": "Service unavailable"}, status_code=503)
    refreshed = DemoResult(
        ok=True,
        request_id=result.request_id,
        token_type=str(exchange.get("token_type") or "Bearer"),
        dt_token=str(exchange["dt_token"]),
        summary={
            **_claims_summary(user_token, exchange, result.request_id),
            "refreshed": True,
        },
        steps=[
            *(step for step in result.steps if step.get("id") != "token_refresh"),
            {"id": "token_refresh", "status": "done", "label": "Token Refresh"},
        ],
        refresh_token=str(token_payload.get("refresh_token") or result.refresh_token),
    )
    _RESULT_STORE[session_id] = refreshed
    return JSONResponse(refreshed.to_response())


def configuration_error_response(error: FrontingDemoConfigurationError) -> JSONResponse:
    detail = str(error)
    if detail not in {"EduPlus2 demo is disabled", "EduPlus2 demo is not configured"}:
        detail = "EduPlus2 demo is not configured"
    return JSONResponse({"detail": detail}, status_code=503)
