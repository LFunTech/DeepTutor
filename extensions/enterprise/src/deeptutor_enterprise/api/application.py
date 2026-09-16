"""原通用会话路由 + 企业认证：无旧 admin/plugin/文件管理入口。"""

from contextlib import asynccontextmanager, nullcontext
import hmac
import secrets

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
import psycopg
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse

from deeptutor.core.providers import provider_context

from ..context import current_token, identity_context
from ..identity.service import LoginRateLimited


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
        bearer = headers.get("authorization", "")
        uses_bearer = bearer.lower().startswith("bearer ")
        token = bearer[7:] if uses_bearer else connection.cookies.get("dt_token")
        anonymous = scope["type"] == "http" and path in ("/api/auth/login", "/api/auth/status")
        status = None
        identity = None

        async def record_denial(code):
            await enterprise.identity.record_denial(
                f"http.{code}" if scope["type"] == "http" else "ws.rejected",
                identity.user_id if identity is not None else "anonymous",
            )

        async def audited_send(message):
            if message["type"] == "http.response.start" and message["status"] >= 400:
                await record_denial(message["status"])
            await send(message)

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


class SocketAuthentication:
    def __init__(self, enterprise):
        self.enterprise = enterprise

    async def authenticate(self, ws):
        # ASGI 中间件已绑定/清理 ContextVar，此处不再次覆盖用户。
        await self.enterprise.authorize()
        return None

    async def revalidate(self, ws):
        await self.enterprise.authorize()

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

    auth = APIRouter()
    attrs = {"httponly": True, "secure": True, "samesite": "lax", "path": "/"}

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
