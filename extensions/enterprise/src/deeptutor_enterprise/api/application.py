"""原通用会话路由 + 企业认证：无旧 admin/plugin/文件管理入口。"""

from contextlib import asynccontextmanager, nullcontext
from datetime import datetime
from decimal import Decimal
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from typing import Literal
import uuid
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from jose import JWTError, jwt
import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import Headers, UploadFile
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse

from deeptutor.core.providers import provider_context

from ..configuration import ModelDeployment
from ..context import bind_identity_reference, current_token, identity_context
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
        oms_path = scope["type"] == "http" and path.startswith("/api/v1/oms/")
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
            "/api/v1/eduplus2/webhooks",
            "/api/v1/tms/school-bootstrap/status",
            "/api/v1/tms/school-bootstrap/activate",
            "/api/v1/tms/quotas",
            "/api/v1/auth/eduplus2/demo/start",
            "/api/v1/auth/eduplus2/demo/callback",
            "/api/v1/auth/eduplus2/demo/result",
            "/api/v1/auth/eduplus2/demo/refresh",
            "/api/settings/ui",
            "/health/live",
            "/health/ready",
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
            if oms_path and (not token or not uses_bearer):
                status = 401
                raise PermissionError
            identity = (
                None
                if anonymous or oms_path
                else await enterprise.identity.authenticate(token or "")
            )
            if not anonymous and not oms_path:
                await enforce_eduplus2_token_allowed()
                await enterprise.lease.check()
            elif oms_path:
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


class OmsModelDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)
    models: tuple[ModelDeployment, ...] = Field(min_length=1, max_length=32)


class OmsModelPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class OmsModelRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class OmsSkillReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=1000)
    code_review_evidence: str = Field(default="", max_length=2000)


class OmsSkillPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)


class OmsSkillGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_grant_version: int = Field(ge=0)
    expires_at: datetime
    reason: str = Field(min_length=1, max_length=1000)


class OmsSkillRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_grant_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class OmsEntitlementCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "revoked"]
    starts_at: datetime
    expires_at: datetime
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)


class OmsQuotaGrantCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grant_id: UUID
    service_id: str = Field(min_length=1, max_length=255)
    unit_code: str = Field(min_length=1, max_length=255)
    acquisition_method: Literal["gift", "recharge"]
    quantity: Decimal = Field(gt=0)
    starts_at: datetime
    expires_at: datetime
    provider_id: str = Field(min_length=1, max_length=255)
    provider_account_id: str = Field(default="", max_length=255)
    pool_id: str = Field(min_length=1, max_length=255)
    source_ref: str = Field(min_length=1, max_length=255)
    expected_entitlement_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)


class OmsQuotaAdjustCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    new_quantity: Decimal = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)


class OmsQuotaCloseCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)


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
        token = current_token()
        identity = await self.enterprise.authorize()
        claims = jwt.get_unverified_claims(token)
        ws.state.enterprise_auth_context = bind_identity_reference(identity, token)
        ws.state.enterprise_token = token
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
        auth_context = getattr(ws.state, "enterprise_auth_context", None)
        if auth_context is not None:
            auth_context.update(identity, token)

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
        auth_context = getattr(ws.state, "enterprise_auth_context", None)
        if auth_context is not None:
            auth_context.update(new_identity, new_token)
        return {
            "expires_at": expires_at,
            "refresh_deadline": max(
                0,
                expires_at
                - int(getattr(self.enterprise, "eduplus2_refresh_deadline_leeway_seconds", 30)),
            ),
            "session_id": str(new_claims.get("sid") or ""),
        }

    async def validate_start_turn(self, ws, payload):
        if self.enterprise.deployment.production is None:
            return
        if any(field in payload for field in ("tenant", "tenant_id", "tenantId")):
            raise ValueError("tenant override is not allowed")
        if payload.get("attachments"):
            raise ValueError(
                "production websocket input accepts DeepTutor resource references only"
            )
        resource_ids = [str(item or "").strip() for item in payload.get("resource_ids") or []]
        if not resource_ids:
            return
        from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore

        store = self.enterprise.store_provider.get()
        resources = PostgresObjectResourceStore(store, self.enterprise.object_store)
        for resource_id in resource_ids:
            try:
                await resources.verify_ready_reference(
                    resource_id=resource_id,
                    session_id=str(payload.get("session_id") or ""),
                    purpose="chat_turn",
                )
            except (FileNotFoundError, PermissionError, RuntimeError, ValueError, OSError) as exc:
                raise ValueError("invalid resource reference") from exc

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
    from deeptutor.api.routers import resources, sessions, settings, unified_ws, voice

    from ..eduplus2 import fronting_demo

    auth = APIRouter()
    attrs = {"httponly": True, "secure": True, "samesite": "lax", "path": "/"}

    eduplus2_auth = APIRouter()
    eduplus2_audit = APIRouter()
    tms_bootstrap = APIRouter()
    oms = APIRouter()
    conversation_test = APIRouter()
    health = APIRouter()

    async def _authorize_oms_request(
        request: Request, action: str, *, target_school_id: UUID | None = None
    ):
        """每个正式 OMS 请求都重新验身份及本产品动作权限。"""
        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..oms.identity import PlatformAccountInactive, trusted_oms_identity_from_token

        bearer = request.headers.get("authorization", "")
        if not bearer.lower().startswith("bearer "):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        try:
            actor = await trusted_oms_identity_from_token(enterprise, bearer[7:])
        except PlatformAccountInactive:
            return JSONResponse({"detail": "Account unavailable"}, status_code=403)
        except PermissionError:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Identity unavailable"}, status_code=503)
        try:
            scope = (
                GlobalScope("@oms-access")
                if target_school_id is None
                else TenantScope(str(target_school_id), "@oms-access")
            )
            async with enterprise.db.transaction(scope) as c:
                await require_management_permission(
                    c,
                    actor,
                    "ops.oms.access",
                    target_school_id=target_school_id,
                    write=False,
                )
                decision = await require_management_permission(
                    c,
                    actor,
                    action,
                    target_school_id=target_school_id,
                    write=False,
                )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Permission unavailable"}, status_code=503)
        return actor, decision

    def _decimal_text(value) -> str:
        text = format(Decimal(value).normalize(), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return "0" if text in {"", "-0"} else text

    def _request_id(request: Request) -> str:
        return request.headers.get("x-request-id") or str(uuid.uuid4())

    @oms.get("/me")
    async def oms_me(request: Request):
        """独立 OMS 平台主体入口；不复用租户会话或 JWT 中的角色。"""

        authorized = await _authorize_oms_request(request, "ops.oms.access")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, decision = authorized
        return {
            "application": "oms",
            "subject": actor.subject,
            "policy_version": decision.policy_version,
        }

    @oms.get("/models")
    async def oms_models(request: Request):
        """展示当前 active 模型；未发布时只展示部署基线且不冒充 OMS 托管。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..oms.model_drafts import redacted_model_items

        authorized = await _authorize_oms_request(request, "ops.providers.read")
        if isinstance(authorized, JSONResponse):
            return authorized
        try:
            async with enterprise.db.transaction(GlobalScope("@oms-model-inventory")) as c:
                row = await (
                    await c.execute(
                        "SELECT active,status FROM oms.model_catalog_config WHERE id='global'"
                    )
                ).fetchone()
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Model configuration unavailable"}, status_code=503)
        if row and isinstance(row["active"], dict) and row["active"]:
            models = redacted_model_items(row["active"], source="oms_active", status="active")
            if models:
                return {"models": models}
        return {
            "models": [
                {
                    "profile_id": model.profile_id,
                    "model_id": model.model_id,
                    "model": model.model,
                    "provider": model.provider,
                    "source": "deployment",
                    "managed": False,
                    "status": "readiness_unverified",
                }
                for model in enterprise.deployment.models
            ]
        }

    @oms.get("/resources/status")
    async def oms_resources_status(request: Request):
        """五类平台资源的安全状态投影；不暴露 Secret、endpoint 或租户正文。"""

        from ..oms.resource_status import build_resource_status

        authorized = await _authorize_oms_request(request, "ops.providers.read")
        if isinstance(authorized, JSONResponse):
            return authorized
        try:
            return await build_resource_status(enterprise)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Resource status unavailable"}, status_code=503)

    @oms.post("/models/draft")
    async def oms_model_draft(request: Request, command: OmsModelDraftRequest):
        """保存全局草稿；执行者确认与发布尚未装配，绝不激活此版本。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.model_drafts import ModelDraftConflict, save_global_model_draft

        authorized = await _authorize_oms_request(request, "ops.providers.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            version = await save_global_model_draft(
                enterprise,
                actor,
                models=command.models,
                expected_version=command.expected_version,
                reason=command.reason,
                request_id=request.headers.get("x-request-id") or str(uuid.uuid4()),
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except ModelDraftConflict:
            return JSONResponse({"detail": "Version conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid model draft"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Model configuration unavailable"}, status_code=503)
        return {"version": version, "status": "saved"}

    @oms.post("/models/publish")
    async def oms_model_publish(request: Request, command: OmsModelPublishRequest):
        """发布已保存草稿；当前 backend 执行者装载确认成功后才写 active。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.model_drafts import (
            ModelDraftConflict,
            ModelPublishUnavailable,
            publish_global_model_catalog,
        )

        authorized = await _authorize_oms_request(request, "ops.providers.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            return await publish_global_model_catalog(
                enterprise,
                actor,
                expected_version=command.expected_version,
                reason=command.reason,
                request_id=request.headers.get("x-request-id") or str(uuid.uuid4()),
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except ModelDraftConflict:
            return JSONResponse({"detail": "Version conflict"}, status_code=409)
        except ModelPublishUnavailable:
            return JSONResponse({"detail": "Model configuration unavailable"}, status_code=503)
        except ValueError:
            return JSONResponse({"detail": "Invalid model publish"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Model configuration unavailable"}, status_code=503)

    @oms.post("/models/test")
    async def oms_model_test(request: Request, command: OmsModelPublishRequest):
        """测试已保存草稿；目标执行者确认成功也不写 active。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.model_drafts import (
            ModelDraftConflict,
            ModelPublishUnavailable,
            test_global_model_catalog,
        )

        authorized = await _authorize_oms_request(request, "ops.providers.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            return await test_global_model_catalog(
                enterprise,
                actor,
                expected_version=command.expected_version,
                reason=command.reason,
                request_id=request.headers.get("x-request-id") or str(uuid.uuid4()),
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except ModelDraftConflict:
            return JSONResponse({"detail": "Version conflict"}, status_code=409)
        except ModelPublishUnavailable:
            return JSONResponse({"detail": "Model configuration unavailable"}, status_code=503)
        except ValueError:
            return JSONResponse({"detail": "Invalid model test"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Model configuration unavailable"}, status_code=503)

    @oms.post("/models/rollback")
    async def oms_model_rollback(request: Request, command: OmsModelRollbackRequest):
        """丢弃未生效草稿或失败状态，继续使用当前 active。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.model_drafts import ModelDraftConflict, rollback_global_model_catalog

        authorized = await _authorize_oms_request(request, "ops.providers.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            return await rollback_global_model_catalog(
                enterprise,
                actor,
                expected_version=command.expected_version,
                reason=command.reason,
                request_id=request.headers.get("x-request-id") or str(uuid.uuid4()),
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except ModelDraftConflict:
            return JSONResponse({"detail": "Version conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid model rollback"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Model configuration unavailable"}, status_code=503)

    @oms.get("/models/draft")
    async def oms_model_draft_read(request: Request):
        """只读脱敏草稿；目标执行者未确认前不显示为可用模型。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..oms.model_drafts import redacted_model_items

        authorized = await _authorize_oms_request(request, "ops.providers.read")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            async with enterprise.db.transaction(GlobalScope("@oms-model-draft-read")) as c:
                await require_management_permission(c, actor, "ops.providers.read", write=False)
                row = await (
                    await c.execute(
                        "SELECT version,status,desired FROM oms.model_catalog_config "
                        "WHERE id='global'"
                    )
                ).fetchone()
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Model configuration unavailable"}, status_code=503)
        if row is None:
            return {"version": 0, "status": "unconfigured", "models": []}
        models = row["desired"].get("models")
        if not isinstance(models, list):
            return JSONResponse({"detail": "Model configuration unavailable"}, status_code=503)
        return {
            "version": row["version"],
            "status": row["status"],
            "models": redacted_model_items(row["desired"], source="oms_draft", status="not_active"),
        }

    @oms.post("/skills/draft")
    async def oms_skill_draft(request: Request):
        """仅接受完整 ZIP；无权者在解析 multipart 前即被拒绝。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.skill_package import SkillPackageRejected
        from ..oms.skill_store import SkillDraftConflict, upload_global_skill

        authorized = await _authorize_oms_request(request, "ops.skills.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        length = request.headers.get("content-length")
        if length and (not length.isdecimal() or int(length) > 20_100_000):
            return JSONResponse({"detail": "Skill package too large"}, status_code=413)
        try:
            async with request.form(max_files=1, max_fields=2, max_part_size=4096) as form:
                upload = form.get("file")
                raw_version = form.get("expected_version")
                reason = form.get("reason")
                if (
                    not isinstance(upload, UploadFile)
                    or upload.content_type != "application/zip"
                    or not isinstance(raw_version, str)
                    or not raw_version.isascii()
                    or not raw_version.isdecimal()
                    or not isinstance(reason, str)
                ):
                    return JSONResponse({"detail": "Invalid Skill package"}, status_code=422)
                payload = bytearray()
                while chunk := await upload.read(64 * 1024):
                    if len(payload) + len(chunk) > 20_000_000:
                        return JSONResponse({"detail": "Skill package too large"}, status_code=413)
                    payload.extend(chunk)
                result = await upload_global_skill(
                    enterprise,
                    actor,
                    bytes(payload),
                    expected_version=int(raw_version),
                    reason=reason,
                    request_id=request.headers.get("x-request-id") or str(uuid.uuid4()),
                )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except SkillDraftConflict:
            return JSONResponse({"detail": "Version conflict"}, status_code=409)
        except (SkillPackageRejected, ValueError):
            return JSONResponse({"detail": "Invalid Skill package"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Skill storage unavailable"}, status_code=503)
        return {
            "revision_id": str(result.revision_id),
            "name": result.name,
            "version": result.version,
            "sha256": result.sha256,
            "status": result.status,
        }

    @oms.post("/skills/revisions/{revision_id}/review")
    async def oms_skill_review(request: Request, revision_id: UUID, command: OmsSkillReviewRequest):
        """只允许独立审查人；服务端复读不可变 ZIP，不能由按钮伪造审查。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.skill_package import SkillPackageRejected
        from ..oms.skill_store import SkillReviewConflict, review_global_skill

        authorized = await _authorize_oms_request(request, "ops.skills.review")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await review_global_skill(
                enterprise,
                actor,
                revision_id,
                expected_sha256=command.expected_sha256,
                approved=command.approved,
                reason=command.reason,
                request_id=request.headers.get("x-request-id") or str(uuid.uuid4()),
                code_review_evidence=command.code_review_evidence,
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except SkillReviewConflict:
            return JSONResponse({"detail": "Skill review conflict"}, status_code=409)
        except (SkillPackageRejected, ValueError):
            return JSONResponse({"detail": "Invalid Skill review"}, status_code=422)
        except (RuntimeError, psycopg.Error, OSError):
            return JSONResponse({"detail": "Skill review unavailable"}, status_code=503)
        return {
            "review_id": str(result.review_id),
            "revision_id": str(result.revision_id),
            "approved": result.approved,
            "code_file_count": result.code_file_count,
            "replayed": result.replayed,
        }

    @oms.post("/skills/revisions/{revision_id}/publish")
    async def oms_skill_publish(
        request: Request, revision_id: UUID, command: OmsSkillPublishRequest
    ):
        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.skill_store import SkillReviewConflict, publish_global_skill

        authorized = await _authorize_oms_request(request, "ops.skills.publish")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await publish_global_skill(
                enterprise,
                actor,
                revision_id,
                expected_version=command.expected_version,
                reason=command.reason,
                request_id=request.headers.get("x-request-id") or str(uuid.uuid4()),
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except SkillReviewConflict:
            return JSONResponse({"detail": "Skill publication conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid Skill publication"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Skill publication unavailable"}, status_code=503)
        return {
            "publication_id": str(result.publication_id),
            "revision_id": str(result.revision_id),
            "review_id": str(result.review_id),
            "version": result.version,
        }

    @oms.post("/skills/{name}/schools/{school_id}/grant")
    async def oms_skill_grant(
        request: Request, name: str, school_id: UUID, command: OmsSkillGrantRequest
    ):
        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.skill_store import SkillReviewConflict, grant_global_skill

        authorized = await _authorize_oms_request(
            request, "ops.skills.grant", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await grant_global_skill(
                enterprise,
                actor,
                school_id,
                name,
                expected_grant_version=command.expected_grant_version,
                expires_at=command.expires_at,
                reason=command.reason,
                request_id=request.headers.get("x-request-id") or str(uuid.uuid4()),
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except SkillReviewConflict:
            return JSONResponse({"detail": "Skill grant conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid Skill grant"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Skill grant unavailable"}, status_code=503)
        return {
            "school_id": str(result.school_id),
            "name": result.name,
            "revision_id": str(result.revision_id),
            "grant_version": result.grant_version,
            "publication_version": result.publication_version,
            "status": result.status,
        }

    @oms.delete("/skills/{name}/schools/{school_id}/grant")
    async def oms_skill_revoke(
        request: Request, name: str, school_id: UUID, command: OmsSkillRevokeRequest
    ):
        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.skill_store import SkillReviewConflict, revoke_global_skill

        authorized = await _authorize_oms_request(
            request, "ops.skills.grant", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await revoke_global_skill(
                enterprise,
                actor,
                school_id,
                name,
                expected_grant_version=command.expected_grant_version,
                reason=command.reason,
                request_id=request.headers.get("x-request-id") or str(uuid.uuid4()),
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except SkillReviewConflict:
            return JSONResponse({"detail": "Skill grant conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid Skill grant"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Skill grant unavailable"}, status_code=503)
        return {
            "school_id": str(result.school_id),
            "name": result.name,
            "revision_id": str(result.revision_id),
            "grant_version": result.grant_version,
            "publication_version": result.publication_version,
            "status": result.status,
        }

    @oms.get("/schools/{school_id}/quota")
    async def oms_school_quota_summary(request: Request, school_id: UUID):
        """OMS 同一学校服务授权与赠送/充值额度列表；不回显采购凭据。"""

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )

        authorized = await _authorize_oms_request(
            request, "ops.quotas.read", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            async with enterprise.db.transaction(TenantScope(str(school_id), actor.subject)) as c:
                await require_management_permission(
                    c,
                    actor,
                    "ops.entitlements.read",
                    target_school_id=school_id,
                    write=False,
                )
                entitlements = await (
                    await c.execute(
                        "SELECT service_id,status,starts_at,expires_at,version "
                        "FROM oms.tenant_service_entitlements "
                        "WHERE tenant_id=%s ORDER BY service_id",
                        (school_id,),
                    )
                ).fetchall()
                grants = await (
                    await c.execute(
                        "SELECT id,service_id,unit_code,acquisition_method,quantity,"
                        "adjustment_released,status,version,starts_at,expires_at,source_ref "
                        "FROM oms.quota_grants WHERE tenant_id=%s "
                        "ORDER BY created_at DESC,id",
                        (school_id,),
                    )
                ).fetchall()
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Quota summary unavailable"}, status_code=503)
        return {
            "school_id": str(school_id),
            "entitlements": [
                {
                    "service_id": row["service_id"],
                    "status": row["status"],
                    "starts_at": row["starts_at"].isoformat(),
                    "expires_at": row["expires_at"].isoformat(),
                    "version": row["version"],
                }
                for row in entitlements
            ],
            "grants": [
                {
                    "grant_id": str(row["id"]),
                    "service_id": row["service_id"],
                    "unit_code": row["unit_code"],
                    "acquisition_method": row["acquisition_method"],
                    "quantity": _decimal_text(row["quantity"]),
                    "adjustment_released": _decimal_text(row["adjustment_released"]),
                    "status": row["status"],
                    "version": row["version"],
                    "starts_at": row["starts_at"].isoformat(),
                    "expires_at": row["expires_at"].isoformat(),
                    "source_ref_hash": hashlib.sha256(row["source_ref"].encode()).hexdigest(),
                }
                for row in grants
            ],
        }

    @oms.post("/schools/{school_id}/entitlements/{service_id}")
    async def oms_school_entitlement_set(
        request: Request,
        school_id: UUID,
        service_id: str,
        command: OmsEntitlementCommandRequest,
    ):
        from ..oms.entitlements import (
            EntitlementRejected,
            EntitlementRequest,
            OmsEntitlementLedger,
        )

        authorized = await _authorize_oms_request(
            request, "ops.entitlements.manage", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await OmsEntitlementLedger(enterprise.db).set(
                TenantScope(str(school_id), actor.subject),
                EntitlementRequest(
                    service_id=service_id,
                    status=command.status,
                    starts_at=command.starts_at,
                    expires_at=command.expires_at,
                    expected_version=command.expected_version,
                    actor_subject=actor.subject,
                    request_id=_request_id(request),
                    idempotency_key=command.idempotency_key,
                    reason=command.reason,
                ),
                management_identity=actor,
            )
        except EntitlementRejected:
            return JSONResponse({"detail": "Entitlement conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid entitlement command"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Entitlement unavailable"}, status_code=503)
        return {
            "service_id": result.service_id,
            "status": result.status,
            "version": result.version,
        }

    @oms.post("/schools/{school_id}/quota-grants")
    async def oms_school_quota_grant(
        request: Request,
        school_id: UUID,
        command: OmsQuotaGrantCommandRequest,
    ):
        from ..oms.ledger import GrantRejected, GrantRequest, InsufficientSupply, OmsGrantLedger

        authorized = await _authorize_oms_request(
            request, "ops.quotas.manage", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await OmsGrantLedger(enterprise.db).grant(
                TenantScope(str(school_id), actor.subject),
                GrantRequest(
                    grant_id=command.grant_id,
                    service_id=command.service_id,
                    unit_code=command.unit_code,
                    acquisition_method=command.acquisition_method,
                    quantity=command.quantity,
                    starts_at=command.starts_at,
                    expires_at=command.expires_at,
                    provider_id=command.provider_id,
                    provider_account_id=command.provider_account_id,
                    pool_id=command.pool_id,
                    source_ref=command.source_ref,
                    actor_subject=actor.subject,
                    request_id=_request_id(request),
                    idempotency_key=command.idempotency_key,
                    reason=command.reason,
                    expected_entitlement_version=command.expected_entitlement_version,
                ),
                management_identity=actor,
            )
        except InsufficientSupply:
            return JSONResponse({"detail": "Insufficient supply"}, status_code=409)
        except GrantRejected:
            return JSONResponse({"detail": "Quota grant conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid quota grant"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Quota grant unavailable"}, status_code=503)
        return {
            "grant_id": str(result.grant_id),
            "allocations": [
                {"lot_id": str(lot_id), "quantity": _decimal_text(quantity)}
                for lot_id, quantity in result.allocations
            ],
        }

    @oms.patch("/schools/{school_id}/quota-grants/{grant_id}")
    async def oms_school_quota_adjust(
        request: Request,
        school_id: UUID,
        grant_id: UUID,
        command: OmsQuotaAdjustCommandRequest,
    ):
        from ..oms.ledger import AdjustRequest, GrantRejected, InsufficientSupply, OmsGrantLedger

        authorized = await _authorize_oms_request(
            request, "ops.quotas.manage", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await OmsGrantLedger(enterprise.db).adjust(
                TenantScope(str(school_id), actor.subject),
                AdjustRequest(
                    grant_id=grant_id,
                    expected_version=command.expected_version,
                    new_quantity=command.new_quantity,
                    actor_subject=actor.subject,
                    request_id=_request_id(request),
                    idempotency_key=command.idempotency_key,
                    reason=command.reason,
                ),
                management_identity=actor,
            )
        except InsufficientSupply:
            return JSONResponse({"detail": "Insufficient supply"}, status_code=409)
        except GrantRejected:
            return JSONResponse({"detail": "Quota adjustment conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid quota adjustment"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Quota adjustment unavailable"}, status_code=503)
        return {
            "grant_id": str(result.grant_id),
            "version": result.version,
            "previous_quantity": _decimal_text(result.previous_quantity),
            "quantity": _decimal_text(result.quantity),
        }

    @oms.post("/schools/{school_id}/quota-grants/{grant_id}/revoke")
    async def oms_school_quota_revoke(
        request: Request,
        school_id: UUID,
        grant_id: UUID,
        command: OmsQuotaCloseCommandRequest,
    ):
        from ..oms.ledger import GrantRejected, OmsGrantLedger, RevokeRequest

        authorized = await _authorize_oms_request(
            request, "ops.quotas.manage", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await OmsGrantLedger(enterprise.db).revoke(
                TenantScope(str(school_id), actor.subject),
                RevokeRequest(
                    grant_id=grant_id,
                    expected_version=command.expected_version,
                    actor_subject=actor.subject,
                    request_id=_request_id(request),
                    idempotency_key=command.idempotency_key,
                    reason=command.reason,
                ),
                management_identity=actor,
            )
        except GrantRejected:
            return JSONResponse({"detail": "Quota revoke conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid quota revoke"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Quota revoke unavailable"}, status_code=503)
        return {
            "grant_id": str(result.grant_id),
            "version": result.version,
            "released_units": _decimal_text(result.released_units),
        }

    @oms.post("/schools/{school_id}/quota-grants/{grant_id}/expire")
    async def oms_school_quota_expire(
        request: Request,
        school_id: UUID,
        grant_id: UUID,
        command: OmsQuotaCloseCommandRequest,
    ):
        from ..oms.ledger import ExpireRequest, GrantRejected, OmsGrantLedger

        authorized = await _authorize_oms_request(
            request, "ops.quotas.manage", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await OmsGrantLedger(enterprise.db).expire(
                TenantScope(str(school_id), actor.subject),
                ExpireRequest(
                    grant_id=grant_id,
                    expected_version=command.expected_version,
                    actor_subject=actor.subject,
                    request_id=_request_id(request),
                    idempotency_key=command.idempotency_key,
                    reason=command.reason,
                ),
                management_identity=actor,
            )
        except GrantRejected:
            return JSONResponse({"detail": "Quota expire conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid quota expire"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Quota expire unavailable"}, status_code=503)
        return {
            "grant_id": str(result.grant_id),
            "version": result.version,
            "released_units": _decimal_text(result.released_units),
        }

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
                return JSONResponse(
                    {"detail": "Authentication temporarily limited"}, status_code=429
                )
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

    @eduplus2_auth.post("/eduplus2/webhooks")
    async def eduplus2_webhook(request: Request):
        """验签后隔离 mock；正式事件须显式开启并事务持久入队。"""

        secret = str(getattr(enterprise, "eduplus2_webhook_secret", "") or "")
        if not secret:
            return JSONResponse({"detail": "Service unavailable"}, status_code=503)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 128 * 1024:
                return JSONResponse({"detail": "Payload too large"}, status_code=413)
        timestamp = request.headers.get("x-eduplus-timestamp", "")
        event_type = request.headers.get("x-eduplus-event", "")
        signature = request.headers.get("x-eduplus-signature", "")
        if not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp) > 12:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        if abs(int(time.time()) - int(timestamp)) > 300:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,100}", event_type):
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        if not re.fullmatch(r"sha256=[0-9a-f]{64}", signature):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        signed_bytes = timestamp.encode("ascii") + b"." + event_type.encode("ascii") + b"." + raw
        expected = hmac.new(secret.encode("utf-8"), signed_bytes, hashlib.sha256).hexdigest()
        current_matches = hmac.compare_digest(expected, signature[7:])
        previous_secret = str(getattr(enterprise, "eduplus2_webhook_previous_secret", "") or "")
        previous_until = int(getattr(enterprise, "eduplus2_webhook_previous_until", 0) or 0)
        previous_matches = False
        if previous_secret and int(time.time()) <= previous_until:
            previous_expected = hmac.new(
                previous_secret.encode("utf-8"), signed_bytes, hashlib.sha256
            ).hexdigest()
            previous_matches = hmac.compare_digest(previous_expected, signature[7:])
        if not (current_matches or previous_matches):
            enterprise.webhook_metrics["signature_rejections"] += 1
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        if not isinstance(payload, dict) or payload.get("event") != event_type:
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        event_id = payload.get("event_id")
        if (
            request.headers.get("x-eduplus-mock", "").lower() == "true"
            and isinstance(event_id, str)
            and event_id.startswith("mock_")
            and len(event_id) <= 128
        ):
            return Response(status_code=204)
        if not getattr(enterprise, "eduplus2_lifecycle_receiver_enabled", False):
            return JSONResponse({"detail": "Lifecycle receiver unavailable"}, status_code=503)
        from ..eduplus2.lifecycle import (
            LifecycleConflict,
            LifecycleInvalid,
            parse_lifecycle_event,
        )
        from ..eduplus2.webhook_authority import ingest_authoritative_webhook

        try:
            event = parse_lifecycle_event(
                payload,
                event_type,
                digest_key=getattr(enterprise, "eduplus2_webhook_inbox_digest_key", ""),
            )
            await ingest_authoritative_webhook(enterprise, event, delivery_timestamp=int(timestamp))
        except LifecycleConflict:
            enterprise.webhook_metrics["delivery_conflicts"] += 1
            logging.getLogger(__name__).warning(
                "lifecycle webhook conflict; no business state changed"
            )
            return JSONResponse({"detail": "Event conflict"}, status_code=409)
        except LifecycleInvalid:
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        except (RuntimeError, TimeoutError, psycopg.Error):
            enterprise.webhook_metrics["delivery_failures"] += 1
            logging.getLogger(__name__).warning(
                "lifecycle webhook transaction failed; sender must retry"
            )
            return JSONResponse({"detail": "Lifecycle receiver unavailable"}, status_code=503)
        return Response(status_code=204)

    async def _tms_bootstrap_identity(request: Request):
        from ..management.tms_identity import (
            TmsAuthenticationDenied,
            trusted_tms_identity_from_token,
        )

        bearer = request.headers.get("authorization", "")
        if not bearer.lower().startswith("bearer "):
            raise TmsAuthenticationDenied("TMS bearer token is missing")
        return await trusted_tms_identity_from_token(enterprise, bearer[7:])

    @tms_bootstrap.get("/quotas")
    async def tms_quota_summary(request: Request):
        """TMS 当前学校配额只读安全视图；不暴露供给、成本或 Secret 关联字段。"""

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-quota-summary")
            ) as c:
                await require_management_permission(
                    c,
                    identity,
                    "tenant.tms.access",
                    target_school_id=identity.school_id,
                    write=False,
                )
                await require_management_permission(
                    c,
                    identity,
                    "tenant.quotas.read",
                    target_school_id=identity.school_id,
                    write=False,
                )
                await require_management_permission(
                    c,
                    identity,
                    "tenant.usage.read",
                    target_school_id=identity.school_id,
                    write=False,
                )
                entitlements = await (
                    await c.execute(
                        "SELECT service_id,status,starts_at,expires_at,version "
                        "FROM oms.tenant_service_entitlements "
                        "WHERE tenant_id=%s ORDER BY service_id",
                        (identity.school_id,),
                    )
                ).fetchall()
                grants = await (
                    await c.execute(
                        "SELECT id,service_id,unit_code,acquisition_method,quantity,"
                        "adjustment_released,status,version,starts_at,expires_at "
                        "FROM oms.quota_grants WHERE tenant_id=%s "
                        "ORDER BY created_at DESC,id",
                        (identity.school_id,),
                    )
                ).fetchall()
                usage = await (
                    await c.execute(
                        "SELECT service_id,unit_code,status,count(*) AS attempts,"
                        "COALESCE(sum(reserved_units),0) AS reserved_units,"
                        "COALESCE(sum(settled_units),0) AS settled_units "
                        "FROM oms.usage_attempts WHERE tenant_id=%s "
                        "GROUP BY service_id,unit_code,status ORDER BY service_id,status",
                        (identity.school_id,),
                    )
                ).fetchall()
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Quota summary unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "school_id": str(identity.school_id),
                "entitlements": [
                    {
                        "service_id": row["service_id"],
                        "status": row["status"],
                        "starts_at": row["starts_at"].isoformat(),
                        "expires_at": row["expires_at"].isoformat(),
                        "version": row["version"],
                    }
                    for row in entitlements
                ],
                "grants": [
                    {
                        "grant_id": str(row["id"]),
                        "service_id": row["service_id"],
                        "unit_code": row["unit_code"],
                        "acquisition_method": row["acquisition_method"],
                        "quantity": _decimal_text(row["quantity"]),
                        "adjustment_released": _decimal_text(row["adjustment_released"]),
                        "status": row["status"],
                        "version": row["version"],
                        "starts_at": row["starts_at"].isoformat(),
                        "expires_at": row["expires_at"].isoformat(),
                    }
                    for row in grants
                ],
                "usage": [
                    {
                        "service_id": row["service_id"],
                        "unit_code": row["unit_code"],
                        "status": row["status"],
                        "attempts": row["attempts"],
                        "reserved_units": _decimal_text(row["reserved_units"]),
                        "settled_units": _decimal_text(row["settled_units"]),
                    }
                    for row in usage
                ],
            },
            headers=headers,
        )

    @tms_bootstrap.get("/school-bootstrap/status")
    async def tms_bootstrap_status(request: Request):
        from ..management.actor_handoff import find_pending_actor_candidates
        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            candidates = await find_pending_actor_candidates(enterprise, identity)
            if candidates:
                return JSONResponse({"status": "ready_to_activate"}, headers=headers)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-bootstrap-status")
            ) as c:
                try:
                    await require_management_permission(
                        c, identity, "tenant.tms.access", target_school_id=identity.school_id
                    )
                except ManagementAuthorizationDenied:
                    return JSONResponse({"status": "awaiting_actor"}, headers=headers)
            return JSONResponse({"status": "active"}, headers=headers)
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except TmsSchoolDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse({"detail": "Service unavailable"}, status_code=503, headers=headers)

    @tms_bootstrap.post("/school-bootstrap/activate")
    async def tms_bootstrap_activate(request: Request):
        from ..management.actor_activation import activate_first_school_administrator
        from ..management.actor_handoff import find_pending_actor_candidates
        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            candidates = await find_pending_actor_candidates(enterprise, identity)
            if not candidates:
                # 本人重试已提交的激活时保持幂等，但不为其他学校成员返回成功。
                async with enterprise.db.transaction(
                    TenantScope(str(identity.school_id), "@tms-bootstrap-replay")
                ) as c:
                    try:
                        await require_management_permission(
                            c, identity, "tenant.tms.access", target_school_id=identity.school_id
                        )
                    except ManagementAuthorizationDenied:
                        return JSONResponse(
                            {"detail": "Activation unavailable"}, status_code=409, headers=headers
                        )
                return JSONResponse(
                    {"status": "active", "policy_version": identity.policy_version},
                    headers=headers,
                )
            request_id = request.headers.get("x-request-id", "").strip() or str(uuid.uuid4())
            result = await activate_first_school_administrator(
                enterprise, identity, event_id=candidates[0].event_id, request_id=request_id
            )
            return JSONResponse(
                {"status": "active", "policy_version": result.policy_version}, headers=headers
            )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except TmsSchoolDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ManagementAuthorizationDenied:
            return JSONResponse(
                {"detail": "Activation unavailable"}, status_code=409, headers=headers
            )
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse({"detail": "Service unavailable"}, status_code=503, headers=headers)

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

    @conversation_test.get("/options")
    async def conversation_test_options():
        """普通对话测试页的可选能力清单；只返回逻辑名和安全展示文案。"""

        await enterprise.authorize()
        try:
            from deeptutor_enterprise.knowledge_bases import list_externalized_knowledge_bases

            from deeptutor.api.utils.tool_options import build_tool_options
            from deeptutor.services.skill.runtime import (
                call_skill_service,
                get_runtime_skill_service,
            )
        except Exception:
            return {"knowledge_bases": [], "skills": [], "mcp_tools": []}

        def safe_description(value: object) -> str:
            text = str(value or "").strip()
            for word in ("api_secret", "secret", "endpoint"):
                text = text.replace(word, "redacted").replace(word.upper(), "REDACTED")
            return text

        rag_enabled = "rag" in set(getattr(enterprise.deployment, "allowed_tools", ()))
        lightrag_bound = getattr(enterprise.deployment, "lightrag", None) is not None
        store = enterprise.store_provider.get()
        knowledge_bases = []
        for item in await list_externalized_knowledge_bases(store):
            status = item.status
            description = safe_description(item.description)
            if not rag_enabled:
                status = "unavailable"
                description = "当前部署未启用知识库检索"
            elif not lightrag_bound:
                status = "unavailable"
                description = "当前部署未绑定知识库检索服务"
            knowledge_bases.append(
                {
                    "id": item.id,
                    "label": item.label,
                    "description": description,
                    "status": status,
                    "disabled": status != "ready",
                }
            )

        try:
            skill_service = get_runtime_skill_service()
            skill_entries = await call_skill_service(skill_service, "summary_entries")
        except Exception:
            skill_entries = []
        skills = [
            {
                "id": entry.name,
                "label": entry.name,
                "description": safe_description(entry.description),
                "status": "ready" if entry.available else "unavailable",
                "disabled": not entry.available,
            }
            for entry in skill_entries
        ]

        try:
            tool_options = await build_tool_options()
        except Exception:
            tool_options = {"mcp_tools": []}

        def friendly_mcp_label(name: str, description: str) -> str:
            lowered = f"{name} {description}".lower()
            if "lightrag" in lowered or "rag" in lowered:
                return "外部检索工具"
            return "外部工具"

        mcp_tools = []
        for item in tool_options.get("mcp_tools") or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            description = safe_description(item.get("description"))
            mcp_tools.append(
                {
                    "id": name,
                    "label": friendly_mcp_label(name, description),
                    "description": description[:240],
                    "status": "ready",
                    "disabled": False,
                }
            )

        return {
            "knowledge_bases": knowledge_bases,
            "skills": skills,
            "mcp_tools": mcp_tools,
        }

    @health.get("/live")
    async def health_live():
        return {"status": "alive"}

    @health.get("/ready")
    async def health_ready():
        return {"status": "ready"}

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
            (tms_bootstrap, "/api/v1/tms"),
            (oms, "/api/v1/oms"),
            (eduplus2_audit, "/api/v1/enterprise/audit/eduplus2"),
            (conversation_test, "/api/v1/enterprise/conversation-test"),
            # Next/AppShell 在登录前会读取界面语言和主题。只挂载核心的
            # public_router，避免把完整 settings/admin 配置面暴露到企业最小 API。
            (settings.public_router, "/api/settings"),
            (session_routes, "/api/sessions"),
            (resources.api_router, "/api/v1/resources"),
            (resources.router, "/files/resources"),
            (voice.router, "/api/voice"),
            (unified_ws.router, "/api/v1"),
            (health, "/health"),
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
