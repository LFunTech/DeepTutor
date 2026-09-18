"""原通用会话路由 + 企业认证：无旧 admin/plugin/文件管理入口。"""

from contextlib import asynccontextmanager, nullcontext
import hashlib
import hmac
import json
import secrets
import time
import uuid

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from jose import JWTError, jwt
import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse

from deeptutor.core.providers import provider_context

from ..context import current_token, identity_context
from ..identity.service import LoginRateLimited
from ..scope import TenantScope


def bearer_from_headers_or_cookie(
    headers,
    *,
    cookies,
    scope_type: str,
    query=None,
) -> tuple[str, bool]:
    """从安全载体提取 bearer token；禁止 query token。

    浏览器 WebSocket 不能设置 Authorization header。demo 页面使用
    ``Sec-WebSocket-Protocol: deeptutor-token, <jwt>`` 传入内存态 token；
    token 不进入 URL/query/hash，也不写 cookie/localStorage。
    """

    bearer = headers.get("authorization", "")
    if bearer.lower().startswith("bearer "):
        return bearer[7:], True
    if scope_type == "websocket":
        raw_protocols = str(headers.get("sec-websocket-protocol", "") or "")
        protocols = [item.strip() for item in raw_protocols.split(",") if item.strip()]
        for index, item in enumerate(protocols[:-1]):
            if item == "deeptutor-token":
                return protocols[index + 1], True
    return cookies.get("dt_token", ""), False


class AuthenticationMiddleware:
    def __init__(self, app, *, enterprise):
        self.app = app
        self.enterprise = enterprise

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        enterprise = self.enterprise
        connection = HTTPConnection(scope)
        headers = Headers(scope=scope)
        path = scope.get("path", "")
        origin = headers.get("origin")
        token, uses_bearer = bearer_from_headers_or_cookie(
            headers,
            cookies=connection.cookies,
            scope_type=scope["type"],
            query=connection.query_params,
        )
        anonymous = scope["type"] == "http" and path in (
            "/api/auth/login",
            "/api/auth/status",
            "/api/v1/auth/eduplus2/exchange",
            "/api/v1/auth/eduplus2/revocations",
            "/api/v1/auth/eduplus2/demo/start",
            "/api/v1/auth/eduplus2/demo/callback",
            "/api/v1/auth/eduplus2/demo/result",
            "/api/v1/auth/eduplus2/demo/refresh",
        )
        status = None
        identity = None

        async def record_denial(code):
            await enterprise.identity.record_denial(
                f"http.{code}" if scope["type"] == "http" else "ws.rejected",
                identity.user_id if identity is not None else "anonymous",
            )

        async def record_eduplus2_authz_denied(code):
            if identity is None or not token or scope["type"] != "http":
                return
            try:
                claims = jwt.get_unverified_claims(token)
            except JWTError:
                return
            eduplus2 = claims.get("eduplus2")
            if not isinstance(eduplus2, dict):
                return
            async with enterprise.db.transaction(
                TenantScope(identity.tenant_id, identity.user_id)
            ) as c:
                await c.execute(
                    """
                    INSERT INTO eduplus2.audit_events(
                      tenant_id,id,request_id,event_kind,client_id,external_tenant_id,
                      external_app_id,external_user_id,internal_user_id,session_id,
                      result,reason,policy_version,summary
                    ) VALUES(%s,%s,%s,'authz.denied',%s,%s,%s,%s,%s,%s,'denied',%s,'',%s)
                    """,
                    (
                        identity.tenant_id,
                        str(uuid.uuid4()),
                        headers.get("x-request-id", ""),
                        str(eduplus2.get("azp") or ""),
                        str(eduplus2.get("external_tenant_id") or ""),
                        str(eduplus2.get("external_app_id") or ""),
                        str(eduplus2.get("external_user_id") or ""),
                        identity.user_id,
                        str(claims.get("sid") or ""),
                        f"http.{code}",
                        Jsonb({"path": path, "status": int(code)}),
                    ),
                )

        async def audited_send(message):
            if message["type"] == "http.response.start" and message["status"] >= 400:
                await record_denial(message["status"])
                await record_eduplus2_authz_denied(message["status"])
            await send(message)

        async def enforce_eduplus2_token_allowed():
            if identity is None or not token:
                return
            try:
                claims = jwt.get_unverified_claims(token)
            except JWTError:
                return
            if isinstance(claims.get("eduplus2"), dict):
                await enterprise.eduplus2.ensure_token_allowed(token)

        try:
            if any(
                headers.get(name) is not None for name in ("x-tenant-id", "x-deeptutor-tenant-id")
            ) or any(
                name in connection.query_params for name in ("tenant", "tenant_id", "tenantId")
            ):
                status = 403
                raise PermissionError
            if origin and origin not in enterprise.deployment.origins:
                status = 403
                raise PermissionError
            if scope["type"] == "websocket" and origin not in enterprise.deployment.origins:
                status = 403
                raise PermissionError
            if scope["type"] == "http" and scope.get("method") not in ("GET", "HEAD", "OPTIONS"):
                if not uses_bearer and (
                    path == "/api/auth/login" or connection.cookies.get("dt_token")
                ):
                    if origin not in enterprise.deployment.origins:
                        status = 403
                        raise PermissionError
                    if path != "/api/auth/login":
                        csrf = headers.get("x-csrf-token", "")
                        cookie = connection.cookies.get("dt_csrf", "")
                        if not csrf or not cookie or not hmac.compare_digest(csrf, cookie):
                            status = 403
                            raise PermissionError
            identity = None if anonymous else await enterprise.identity.authenticate(token or "")
            if not anonymous:
                await enforce_eduplus2_token_allowed()
                await enterprise.lease.check()
            with provider_context(enterprise.providers):
                with identity_context(identity, token) if identity is not None else nullcontext():
                    return await self.app(scope, receive, audited_send)
        except LoginRateLimited:
            status = 429
        except PermissionError:
            status = status or 401
        except LookupError:
            status = 404
        except ValueError:
            status = 409
        except (RuntimeError, psycopg.Error):
            status = 503
        if status != 503:
            try:
                await record_denial(status)
            except (RuntimeError, psycopg.Error):
                status = 503
        if scope["type"] == "websocket":
            await send(
                {
                    "type": "websocket.close",
                    "code": 1008,
                    "reason": "Authentication or operation rejected",
                }
            )
        else:
            await JSONResponse(
                {
                    "detail": {
                        401: "Authentication required",
                        403: "Origin or CSRF rejected",
                        404: "Resource not found",
                        409: "Operation conflict",
                        429: "Authentication temporarily limited",
                        503: "Service unavailable",
                    }[status]
                },
                status_code=status,
            )(scope, receive, send)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class AuditExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: str = Field(default="jsonl", pattern="^(jsonl|csv)$")
    event_kind: str = Field(default="", max_length=128)
    client_id: str = Field(default="", max_length=256)
    external_tenant_id: str = Field(default="", max_length=256)
    external_app_id: str = Field(default="", max_length=256)
    external_user_id: str = Field(default="", max_length=256)
    internal_user_id: str = Field(default="", max_length=256)
    result: str = Field(default="", max_length=32)
    request_id: str = Field(default="", max_length=256)
    limit: int = Field(default=1000, ge=1, le=5000)

    def filters(self) -> dict:
        return {
            "event_kind": self.event_kind,
            "client_id": self.client_id,
            "external_tenant_id": self.external_tenant_id,
            "external_app_id": self.external_app_id,
            "external_user_id": self.external_user_id,
            "internal_user_id": self.internal_user_id,
            "result": self.result,
            "request_id": self.request_id,
            "limit": self.limit,
        }


class SocketAuthentication:
    def __init__(self, enterprise):
        self.enterprise = enterprise

    async def _ensure_eduplus2_token_allowed(self, token: str) -> None:
        try:
            claims = jwt.get_unverified_claims(token)
        except JWTError:
            return
        if isinstance(claims.get("eduplus2"), dict):
            await self.enterprise.eduplus2.ensure_token_allowed(token)

    async def authenticate(self, ws):
        # ASGI 中间件已绑定/清理 ContextVar；WS 自身保存可 refresh 的当前 token。
        identity = await self.enterprise.authorize()
        claims = jwt.get_unverified_claims(current_token())
        ws.state.enterprise_token = current_token()
        ws.state.enterprise_identity = identity
        ws.state.enterprise_expires_at = int(claims.get("exp") or 0)
        return None

    async def revalidate(self, ws):
        token = str(getattr(ws.state, "enterprise_token", "") or "")
        if not token:
            await self.enterprise.authorize()
            return
        identity = await self.enterprise.identity.authenticate(token)
        await self._ensure_eduplus2_token_allowed(token)
        await self.enterprise.lease.check()
        ws.state.enterprise_identity = identity

    async def refresh(self, ws, payload):
        old_token = str(getattr(ws.state, "enterprise_token", "") or "")
        old_identity = getattr(ws.state, "enterprise_identity", None)
        if not old_token or old_identity is None:
            old_token = current_token()
            old_identity = await self.enterprise.identity.authenticate(old_token)
        new_token = str(payload.get("dt_token") or "").strip()
        proof_kind = "dt_token"
        if not new_token and payload.get("external_token"):
            proof_kind = "external_token"
            exchanged = await self.enterprise.eduplus2.exchange_user_jwt(
                str(payload["external_token"]), request_id=str(payload.get("command_id") or "")
            )
            new_token = str(exchanged["dt_token"])
        if not new_token:
            raise PermissionError("refresh proof required")
        new_identity = await self.enterprise.identity.authenticate(new_token)
        await self._ensure_eduplus2_token_allowed(new_token)
        if (
            new_identity.tenant_id != old_identity.tenant_id
            or new_identity.user_id != old_identity.user_id
            or new_identity.role != old_identity.role
        ):
            raise PermissionError("identity mismatch")
        old_claims = jwt.get_unverified_claims(old_token)
        new_claims = jwt.get_unverified_claims(new_token)
        old_eduplus2 = old_claims.get("eduplus2")
        new_eduplus2 = new_claims.get("eduplus2")
        if isinstance(old_eduplus2, dict):
            if not isinstance(new_eduplus2, dict):
                raise PermissionError("identity mismatch")
            for key in (
                "client_registration_id",
                "external_tenant_id",
                "external_app_id",
                "external_user_id",
                "azp",
            ):
                if str(old_eduplus2.get(key) or "") != str(new_eduplus2.get(key) or ""):
                    raise PermissionError("identity mismatch")
        await self.enterprise.lease.check()
        await self.enterprise.eduplus2.record_refresh_audit(
            new_token,
            request_id=str(payload.get("command_id") or ""),
            reason=proof_kind,
        )
        expires_at = int(new_claims.get("exp") or 0)
        ws.state.enterprise_token = new_token
        ws.state.enterprise_identity = new_identity
        ws.state.enterprise_expires_at = expires_at
        return {
            "expires_at": expires_at,
            "refresh_deadline": max(
                0,
                expires_at
                - int(getattr(self.enterprise, "eduplus2_refresh_deadline_leeway_seconds", 30)),
            ),
            "session_id": str(new_claims.get("sid") or ""),
        }

    @staticmethod
    def error_message(error):
        if isinstance(error, LookupError):
            return "Resource not found"
        if isinstance(error, ValueError):
            return "Requested operation is unavailable or invalid"
        return "Service unavailable"

    async def record_denial(self):
        identity = await self.enterprise.authorize()
        await self.enterprise.identity.record_denial("ws.command_rejected", identity.user_id)


def create_application(enterprise):
    from deeptutor.api.application import create_api_application
    from deeptutor.api.routers import sessions, unified_ws

    from ..eduplus2 import fronting_demo

    auth = APIRouter()
    attrs = {"httponly": True, "secure": True, "samesite": "lax", "path": "/"}

    eduplus2_auth = APIRouter()
    eduplus2_audit = APIRouter()

    async def require_audit_admin():
        identity = await enterprise.identity.authenticate(current_token())
        if identity.role != "tenant_admin":
            raise PermissionError("tenant administrator required")
        return identity

    @eduplus2_auth.post("/auth/eduplus2/exchange")
    async def eduplus2_exchange(request: Request):
        bearer = request.headers.get("authorization", "")
        if not bearer.lower().startswith("bearer "):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        try:
            result = await enterprise.eduplus2.exchange_user_jwt(
                bearer[7:], request_id=request.headers.get("x-request-id", "")
            )
            return result
        except PermissionError as exc:
            reason = str(exc)
            if "rate limited" in reason:
                return JSONResponse({"detail": "Authentication temporarily limited"}, status_code=429)
            if "tenant mismatch" in reason:
                return JSONResponse({"detail": "Operation conflict"}, status_code=409)
            if "azp is not registered" in reason or "inactive" in reason:
                return JSONResponse({"detail": "Forbidden"}, status_code=403)
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        except ValueError:
            return JSONResponse({"detail": "Operation conflict"}, status_code=409)
        except RuntimeError:
            return JSONResponse({"detail": "Service unavailable"}, status_code=503)

    @eduplus2_auth.post("/auth/eduplus2/revocations")
    async def eduplus2_revocations(request: Request):
        secret = str(getattr(enterprise, "eduplus2_revocation_webhook_secret", "") or "")
        if not secret:
            return JSONResponse({"detail": "Service unavailable"}, status_code=503)
        raw = await request.body()
        timestamp = request.headers.get("x-eduplus2-timestamp", "")
        signature = request.headers.get("x-eduplus2-signature", "")
        try:
            ts = int(timestamp)
        except ValueError:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        if abs(int(time.time()) - ts) > 300:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        expected = hmac.new(
            secret.encode(),
            timestamp.encode() + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        provided = signature.removeprefix("sha256=")
        if not hmac.compare_digest(expected, provided):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        try:
            payload = json.loads(raw.decode("utf8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        try:
            return await enterprise.eduplus2.apply_revocation_event(
                payload,
                request_id=request.headers.get("x-request-id", ""),
            )
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        except RuntimeError:
            return JSONResponse({"detail": "Service unavailable"}, status_code=503)

    @eduplus2_auth.get("/auth/eduplus2/demo/start", name="eduplus2_demo_start")
    async def eduplus2_demo_start(request: Request):
        try:
            return fronting_demo.create_authorization_redirect(request)
        except fronting_demo.FrontingDemoConfigurationError as exc:
            return fronting_demo.configuration_error_response(exc)
        except RuntimeError:
            return JSONResponse({"detail": "EduPlus2 demo is not configured"}, status_code=503)

    @eduplus2_auth.get("/auth/eduplus2/demo/callback", name="eduplus2_demo_callback")
    async def eduplus2_demo_callback(request: Request):
        return await fronting_demo.handle_callback(request, enterprise)

    @eduplus2_auth.get("/auth/eduplus2/demo/result")
    async def eduplus2_demo_result(request: Request):
        return fronting_demo.result_response(request)

    @eduplus2_auth.post("/auth/eduplus2/demo/refresh")
    async def eduplus2_demo_refresh(request: Request):
        return await fronting_demo.refresh_response(request, enterprise)

    @eduplus2_audit.get("/events")
    async def eduplus2_audit_events(request: Request):
        try:
            await require_audit_admin()
        except PermissionError:
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        filters = {
            key: request.query_params.get(key, "")
            for key in (
                "event_kind",
                "client_id",
                "external_tenant_id",
                "external_app_id",
                "external_user_id",
                "internal_user_id",
                "result",
                "request_id",
            )
        }
        try:
            limit = int(request.query_params.get("limit", "100"))
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        try:
            return await enterprise.eduplus2.query_audit_events(filters, limit=limit)
        except RuntimeError:
            return JSONResponse({"detail": "Service unavailable"}, status_code=503)

    @eduplus2_audit.post("/exports")
    async def eduplus2_audit_exports(payload: AuditExportRequest):
        try:
            identity = await require_audit_admin()
        except PermissionError:
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        try:
            return await enterprise.eduplus2.create_audit_export(
                payload.filters(),
                export_format=payload.format,
                actor_id=identity.user_id,
            )
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        except RuntimeError:
            return JSONResponse({"detail": "Service unavailable"}, status_code=503)

    @auth.post("/login")
    async def login(payload: LoginRequest, request: Request, response: Response):
        token = await enterprise.identity.login(
            payload.username,
            payload.password,
            client=request.client.host if request.client else "unknown",
        )
        identity = await enterprise.identity.authenticate(token)
        response.set_cookie("dt_token", token, max_age=enterprise.identity.token_seconds, **attrs)
        response.set_cookie(
            "dt_csrf",
            secrets.token_urlsafe(32),
            max_age=enterprise.identity.token_seconds,
            secure=True,
            samesite="lax",
            path="/",
        )
        return {
            "success": True,
            "username": identity.username,
            "user_id": identity.user_id,
            "role": identity.role,
        }

    @auth.get("/status")
    async def status(request: Request):
        token = request.headers.get("authorization", "")
        token = (
            token[7:]
            if token.lower().startswith("bearer ")
            else request.cookies.get("dt_token", "")
        )
        try:
            identity = await enterprise.identity.authenticate(token)
            return {
                "enabled": True,
                "authenticated": True,
                "user_id": identity.user_id,
                "username": identity.username,
                "role": identity.role,
                "is_admin": False,
            }
        except PermissionError:
            return {"enabled": True, "authenticated": False, "is_admin": False}

    @auth.post("/logout")
    async def logout(response: Response):
        await enterprise.identity.logout(current_token())
        response.delete_cookie("dt_token", **attrs)
        response.delete_cookie("dt_csrf", secure=True, samesite="lax", path="/")
        return {"success": True}

    # 复用原 endpoint/协议；明确白名单，不复制 handler 或靠注册顺序覆盖。
    session_routes = APIRouter()
    allowed = {
        ("", "GET"),
        ("/{session_id}", "GET"),
        ("/{session_id}", "PATCH"),
        ("/{session_id}", "DELETE"),
        ("/{session_id}/messages/{message_id}/events", "GET"),
        ("/{session_id}/organization", "PATCH"),
        ("/{session_id}/branch-selection", "PUT"),
        ("/{session_id}/messages/{message_id}", "DELETE"),
    }
    for route in sessions.router.routes:
        if any((route.path, method) in allowed for method in route.methods):
            session_routes.routes.append(route)

    @asynccontextmanager
    async def lifespan(app):
        await enterprise.start()
        app.state.application_container = enterprise.container
        try:
            yield
        finally:
            await enterprise.close()

    app = create_api_application(
        routers=(
            (auth, "/api/auth"),
            (eduplus2_auth, "/api/v1"),
            (eduplus2_audit, "/api/v1/enterprise/audit/eduplus2"),
            (session_routes, "/api/sessions"),
            (unified_ws.router, "/api/v1"),
        ),
        lifespan=lifespan,
        middleware=(
            Middleware(
                CORSMiddleware,
                allow_origins=list(enterprise.deployment.origins),
                allow_credentials=True,
                allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "If-Match"],
            ),
            Middleware(AuthenticationMiddleware, enterprise=enterprise),
        ),
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # FastAPI 默认 validation detail 含原始 input，登录错误不能回显密码/token。
        return JSONResponse({"detail": "Invalid request"}, status_code=422)

    app.state.enterprise = enterprise
    app.state.auth_provider = SocketAuthentication(enterprise)
    return app
