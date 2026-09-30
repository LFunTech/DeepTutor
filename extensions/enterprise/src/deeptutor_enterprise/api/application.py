"""原通用会话路由 + 企业认证：无旧 admin/plugin/文件管理入口。"""

from contextlib import asynccontextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import logging
import os
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
        oms_auth_path = scope["type"] == "http" and path.startswith("/api/v1/oms/auth/")
        oms_path = (
            scope["type"] == "http"
            and path.startswith("/api/v1/oms/")
            and not oms_auth_path
        )
        origin = headers.get("origin")
        token, uses_bearer = bearer_from_headers_or_cookie(
            headers,
            cookies=connection.cookies,
            scope_type=scope["type"],
            query=connection.query_params,
        )
        uses_oms_cookie = False
        if oms_path and not uses_bearer:
            token = connection.cookies.get("dt_oms_token", "")
            uses_oms_cookie = bool(token)
        anonymous = scope["type"] == "http" and (
            path
            in (
                "/api/auth/login",
                "/api/auth/status",
                "/api/v1/auth/eduplus2/exchange",
                "/api/v1/auth/eduplus2/revocations",
                "/api/v1/eduplus2/webhooks",
                "/api/v1/tms/school-bootstrap/status",
                "/api/v1/tms/school-bootstrap/activate",
                "/api/v1/tms/quotas",
                "/api/v1/tms/me/permissions",
                "/api/v1/tms/me/register",
                "/api/v1/tms/skills",
                "/api/v1/tms/roles/custom",
                "/api/v1/tms/authz-audit",
                "/api/v1/tms/members",
                "/api/v1/tms/approvals",
                "/api/v1/tms/directory/users",
                "/api/v1/auth/eduplus2/demo/start",
                "/api/v1/auth/eduplus2/demo/callback",
                "/api/v1/auth/eduplus2/demo/result",
                "/api/v1/auth/eduplus2/demo/refresh",
                "/api/v1/oms/auth/start",
                "/api/v1/oms/auth/callback",
                "/api/v1/oms/auth/refresh",
                "/api/v1/oms/auth/status",
                "/api/v1/oms/auth/logout",
                "/api/settings/ui",
                "/health/live",
                "/health/ready",
            )
            or path.startswith("/api/v1/tms/service-access")
            or path == "/api/v1/tms/permissions"
            or path.startswith("/api/v1/tms/permissions/")
            or path.startswith("/api/v1/tms/assignments/")
            or path.startswith("/api/v1/tms/members/")
            or path.startswith("/api/v1/tms/approvals/")
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
                if oms_path and uses_oms_cookie:
                    if origin not in enterprise.deployment.origins:
                        status = 403
                        raise PermissionError
                    csrf = headers.get("x-csrf-token", "")
                    cookie = connection.cookies.get("dt_oms_csrf", "")
                    if not csrf or not cookie or not hmac.compare_digest(csrf, cookie):
                        status = 403
                        raise PermissionError
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
            if oms_path and not token:
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


class OmsProviderSettingsDryRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: str = Field(min_length=1, max_length=64)
    settings: dict[str, object]


class OmsProviderSettingsDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)
    settings: dict[str, object]


class OmsProviderSettingsCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class OmsFirstAdminBootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
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


class OmsPrincipalRoleGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_key: str = Field(min_length=1, max_length=128)
    role_version: int = Field(ge=1)
    target_school_id: UUID
    expected_target_policy_version: int = Field(ge=1)
    expires_at: datetime
    command_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class OmsPrincipalDisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_target_policy_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class OmsAssignmentRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_school_id: UUID | None = None
    expected_assignment_version: int = Field(ge=1)
    expected_target_policy_version: int = Field(ge=1)
    command_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class OmsApprovalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["platform_grant", "delegation_expand"]
    target_principal_id: UUID
    expected_target_policy_version: int = Field(ge=1)
    expires_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    external_qualification_ref: str = Field(min_length=1, max_length=1000)
    external_qualification_version: str = Field(min_length=1, max_length=256)
    target_role_key: str | None = Field(default=None, min_length=1, max_length=128)
    target_role_version: int | None = Field(default=None, ge=1)
    confirmed_role_version: int | None = Field(default=None, ge=1)
    target_action_keys: tuple[str, ...] = Field(default=(), max_length=64)
    target_expires_at: datetime | None = None


class OmsApprovalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    expected_target_policy_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class OmsApprovalWithdrawRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)


class OmsApprovalApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_target_policy_version: int = Field(ge=1)
    command_id: UUID
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


class OmsSupplyRegisterCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lot_id: UUID
    service_id: str = Field(min_length=1, max_length=255)
    unit_code: str = Field(min_length=1, max_length=255)
    provider_id: str = Field(min_length=1, max_length=255)
    provider_account_id: str = Field(default="", max_length=255)
    pool_id: str = Field(min_length=1, max_length=255)
    basis: Literal["legacy_unverified", "native_units", "money", "credits", "paygo"]
    hard_ceiling: Decimal | None = Field(default=None, gt=0)
    starts_at: datetime
    expires_at: datetime
    evidence_ref: str = Field(min_length=1, max_length=255)
    verified_native: bool
    reason: str = Field(min_length=1, max_length=1000)


class OmsSupplyRevokeCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class OmsAttemptSettleCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    units: Decimal = Field(ge=0)
    source: Literal["provider_usage", "verified_reconciliation"]
    evidence_ref: str = Field(min_length=1, max_length=255)
    provider_request_id: str = Field(default="", max_length=255)
    reason: str = Field(min_length=1, max_length=1000)


class OmsProviderReceiptSettleCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1, max_length=255)
    provider_account_id: str = Field(default="", max_length=255)
    provider_request_id: str = Field(min_length=1, max_length=255)
    units: Decimal = Field(ge=0)
    evidence_ref: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)


class OmsAttemptReleaseCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_ref: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)


class TmsServiceAccessGrantCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grant_id: UUID
    service_id: str = Field(min_length=1, max_length=128)
    subject_kind: Literal["member", "application", "service_principal"]
    subject_id: str = Field(min_length=1, max_length=255)
    starts_at: datetime
    expires_at: datetime
    expected_entitlement_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class TmsServiceAccessRevokeCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class TmsCustomRolePublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_key: str = Field(pattern=r"^custom_[a-z0-9][a-z0-9_]{0,63}$")
    action_keys: tuple[str, ...] = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=0)
    command_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class TmsAssignmentRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_assignment_version: int = Field(ge=1)
    expected_target_policy_version: int = Field(ge=1)
    command_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class TmsMemberRoleGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_key: str = Field(min_length=1, max_length=128)
    role_version: int = Field(ge=1)
    expected_target_policy_version: int = Field(ge=1)
    expires_at: datetime
    command_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class TmsApprovalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["school_activation"]
    target_principal_id: UUID
    expected_target_policy_version: int = Field(ge=1)
    expires_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    external_qualification_ref: str = Field(min_length=1, max_length=1000)
    external_qualification_version: str = Field(min_length=1, max_length=256)


class TmsApprovalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected"]
    expected_target_policy_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class TmsApprovalWithdrawRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)


class TmsApprovalApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_target_policy_version: int = Field(ge=1)
    command_id: UUID
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
    from ..oms import oauth as oms_oauth

    auth = APIRouter()
    attrs = {"httponly": True, "secure": True, "samesite": "lax", "path": "/"}

    eduplus2_auth = APIRouter()
    eduplus2_audit = APIRouter()
    tms_bootstrap = APIRouter()
    oms = APIRouter()
    conversation_test = APIRouter()
    health = APIRouter()

    async def _authorize_oms_request(
        request: Request,
        action: str,
        *,
        target_school_id: UUID | None = None,
        allow_school_scope_access: bool = False,
    ):
        """每个正式 OMS 请求都重新验身份及本产品动作权限。"""
        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..management.authorization import (
            ManagementAuthorizationDenied,
        )
        from ..oms.governance import authorized_oms_school_ids, require_platform_permission
        from ..oms.identity import PlatformAccountInactive, trusted_oms_identity_from_token

        bearer = request.headers.get("authorization", "")
        if bearer.lower().startswith("bearer "):
            token = bearer[7:]
        else:
            token = str(request.cookies.get(oms_oauth.OMS_TOKEN_COOKIE) or "")
        if not token:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        try:
            actor = await trusted_oms_identity_from_token(enterprise, token)
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
                try:
                    await require_platform_permission(
                        c,
                        actor,
                        "ops.oms.access",
                        target_school_id=target_school_id,
                        write=False,
                    )
                except ManagementAuthorizationDenied:
                    if (
                        action == "ops.oms.access"
                        and target_school_id is None
                        and allow_school_scope_access
                    ):
                        school_ids = await authorized_oms_school_ids(
                            enterprise, actor, "ops.oms.access"
                        )
                        if school_ids:
                            async with enterprise.db.transaction(
                                TenantScope(str(school_ids[0]), "@oms-access")
                            ) as scoped_c:
                                decision = await require_platform_permission(
                                    scoped_c,
                                    actor,
                                    action,
                                    target_school_id=school_ids[0],
                                    write=False,
                                )
                            return actor, decision
                    raise
                decision = await require_platform_permission(
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

    @oms.get("/auth/start", name="oms_auth_start")
    async def oms_auth_start(request: Request):
        try:
            return oms_oauth.create_authorization_redirect(request)
        except oms_oauth.OmsLoginConfigurationError:
            return JSONResponse({"detail": "OMS login is not configured"}, status_code=503)
        except RuntimeError:
            return JSONResponse({"detail": "OMS login is not configured"}, status_code=503)

    @oms.post("/auth/callback", name="oms_auth_callback")
    async def oms_auth_callback(request: Request):
        return await oms_oauth.handle_frontend_callback(request, enterprise)

    @oms.post("/auth/refresh")
    async def oms_auth_refresh(request: Request):
        return await oms_oauth.refresh_session(request, enterprise)

    @oms.get("/auth/status")
    async def oms_auth_status(request: Request):
        return await oms_oauth.status_response(request, enterprise)

    @oms.post("/auth/logout")
    async def oms_auth_logout():
        return oms_oauth.logout_response()

    @oms.post("/bootstrap/first-admin")
    async def oms_first_admin_bootstrap(
        request: Request, command: OmsFirstAdminBootstrapRequest
    ):
        """零本地管理员时，将当前已认证 OMS 平台主体初始化为首位管理员。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..management.authorization import ManagementAuthorizationDenied
        from ..management.first_admin import (
            BootstrapFirstOmsAdministratorCommand,
            FirstOmsAdministratorConflict,
            bootstrap_first_oms_administrator,
        )
        from ..oms.identity import PlatformAccountInactive, trusted_oms_identity_from_token

        headers = {"Cache-Control": "no-store"}
        enabled = os.environ.get(
            "DT_EDUPLUS2_OMS_FIRST_ADMIN_BOOTSTRAP_ENABLED", "true"
        ).strip().lower()
        if enabled in {"0", "false", "no", "off", "disabled"}:
            return JSONResponse({"detail": "First administrator bootstrap disabled"}, status_code=403, headers=headers)
        bearer = request.headers.get("authorization", "")
        if bearer.lower().startswith("bearer "):
            token = bearer[7:]
        else:
            token = str(request.cookies.get(oms_oauth.OMS_TOKEN_COOKIE) or "")
        if not token:
            return JSONResponse({"detail": "Authentication required"}, status_code=401, headers=headers)
        try:
            actor = await trusted_oms_identity_from_token(enterprise, token)
            async with enterprise.db.transaction(GlobalScope("@oms-first-admin-bootstrap")) as c:
                result = await bootstrap_first_oms_administrator(
                    c,
                    actor,
                    BootstrapFirstOmsAdministratorCommand(
                        command_id=command.command_id,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except PlatformAccountInactive:
            return JSONResponse({"detail": "Account unavailable"}, status_code=403, headers=headers)
        except PermissionError:
            return JSONResponse({"detail": "Authentication required"}, status_code=401, headers=headers)
        except FirstOmsAdministratorConflict:
            return JSONResponse(
                {"detail": "First administrator already initialized"},
                status_code=409,
                headers=headers,
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "First administrator bootstrap unavailable"},
                status_code=503,
                headers=headers,
            )
        return JSONResponse(
            {
                "application": "oms",
                "principal_id": str(result.principal_id),
                "assignment_ids": [str(item) for item in result.assignment_ids],
                "roles": list(result.role_keys),
                "target_policy_version": result.target_policy_version,
                "subject_hash": hashlib.sha256(actor.subject.encode()).hexdigest()[:16],
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @oms.get("/permissions")
    async def oms_permissions_catalog(request: Request):
        """OMS 平台权限管理只读 DTO；写入仍须独立命令/审批 API。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        authorized = await _authorize_oms_request(request, "ops.permissions.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        headers = {"Cache-Control": "no-store"}
        try:
            async with enterprise.db.transaction(GlobalScope("@oms-permissions-catalog")) as c:
                await c.execute("SELECT set_config('app.management_app','oms',true)")
                actions = await (
                    await c.execute(
                        "SELECT action_key,allowed_scope,sensitive,status,version "
                        "FROM management.action_catalog WHERE application='oms' "
                        "ORDER BY action_key"
                    )
                ).fetchall()
                role_rows = await (
                    await c.execute(
                        "SELECT rv.role_key,rv.version,rv.scope_kind,rv.is_template,"
                        "rv.owner_school_id,ra.action_key "
                        "FROM management.role_versions rv "
                        "LEFT JOIN management.role_actions ra ON ra.application=rv.application "
                        "AND ra.role_key=rv.role_key AND ra.role_version=rv.version "
                        "WHERE rv.application='oms' "
                        "ORDER BY rv.scope_kind,rv.role_key,rv.version,ra.action_key"
                    )
                ).fetchall()
                principals = await (
                    await c.execute(
                        "SELECT id,issuer,subject,status,policy_version,created_at,updated_at "
                        "FROM management.principals WHERE application='oms' "
                        "ORDER BY subject,id LIMIT 500"
                    )
                ).fetchall()
                assignments = await (
                    await c.execute(
                        "SELECT a.id,a.principal_id,p.subject,a.role_key,a.role_version,"
                        "a.scope_kind,a.school_id,a.status,a.version,a.valid_from,a.expires_at,"
                        "a.revoked_at,a.school_binding_version "
                        "FROM management.assignments a "
                        "JOIN management.principals p ON p.application=a.application "
                        "AND p.id=a.principal_id "
                        "WHERE a.application='oms' "
                        "ORDER BY a.created_at DESC,a.id LIMIT 500"
                    )
                ).fetchall()
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Permission catalog unavailable"}, status_code=503, headers=headers
            )

        roles_by_id: dict[tuple[str, int], dict[str, object]] = {}
        for row in role_rows:
            key = (row["role_key"], row["version"])
            role = roles_by_id.setdefault(
                key,
                {
                    "role_key": row["role_key"],
                    "version": row["version"],
                    "scope_kind": row["scope_kind"],
                    "is_template": row["is_template"],
                    "owner_school_id": "" if row["owner_school_id"] is None else str(row["owner_school_id"]),
                    "actions": [],
                },
            )
            if row["action_key"]:
                actions_list = role["actions"]
                if isinstance(actions_list, list):
                    actions_list.append(row["action_key"])
        return JSONResponse(
            {
                "application": "oms",
                "actions": [
                    {
                        "action_key": row["action_key"],
                        "allowed_scope": row["allowed_scope"],
                        "sensitive": row["sensitive"],
                        "status": row["status"],
                        "version": row["version"],
                    }
                    for row in actions
                    if isinstance(row["action_key"], str) and row["action_key"].startswith("ops.")
                ],
                "roles": list(roles_by_id.values()),
                "principals": [
                    {
                        "principal_id": str(row["id"]),
                        "issuer": row["issuer"],
                        "subject": row["subject"],
                        "status": row["status"],
                        "policy_version": row["policy_version"],
                        "created_at": row["created_at"].isoformat(),
                        "updated_at": row["updated_at"].isoformat(),
                    }
                    for row in principals
                ],
                "assignments": [
                    {
                        "assignment_id": str(row["id"]),
                        "principal_id": str(row["principal_id"]),
                        "subject": row["subject"],
                        "role_key": row["role_key"],
                        "role_version": row["role_version"],
                        "scope_kind": row["scope_kind"],
                        "school_id": "" if row["school_id"] is None else str(row["school_id"]),
                        "school_binding_version": row["school_binding_version"],
                        "status": row["status"],
                        "version": row["version"],
                        "valid_from": row["valid_from"].isoformat(),
                        "expires_at": row["expires_at"].isoformat(),
                        "revoked_at": "" if row["revoked_at"] is None else row["revoked_at"].isoformat(),
                    }
                    for row in assignments
                ],
            },
            headers=headers,
        )

    @oms.get("/approvals")
    async def oms_approvals_list(request: Request):
        """OMS 平台敏感授权审批列表；只读本产品本地审批事实。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        authorized = await _authorize_oms_request(request, "ops.permissions.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        headers = {"Cache-Control": "no-store"}
        try:
            limit = min(max(int(request.query_params.get("limit", "50")), 1), 200)
            offset = min(max(int(request.query_params.get("offset", "0")), 0), 10_000)
            status = request.query_params.get("status", "").strip()
            filters = []
            params: list[object] = []
            if status:
                if len(status) > 64:
                    raise ValueError("approval status filter is too long")
                filters.append("status=%s")
                params.append(status)
            where = " AND " + " AND ".join(filters) if filters else ""
            async with enterprise.db.transaction(GlobalScope("@oms-approvals-list")) as c:
                await c.execute("SELECT set_config('app.management_app','oms',true)")
                rows = await (
                    await c.execute(
                        "SELECT id,operation,target_principal_id,expected_policy_version,"
                        "status,expires_at,decided_at,proposer_subject,reviewer_subject,"
                        "reason,request_id,external_qualification_ref,"
                        "external_qualification_version,target_role_key,target_role_version,"
                        "target_action_keys,target_expires_at,confirmed_role_version "
                        "FROM management.approval_requests WHERE application='oms' "
                        + where
                        + " ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s",
                        (*params, limit, offset),
                    )
                ).fetchall()
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Approvals unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "oms",
                "page": {"limit": limit, "offset": offset, "count": len(rows)},
                "approvals": [
                    {
                        "approval_id": str(row["id"]),
                        "operation": row["operation"],
                        "target_principal_id": str(row["target_principal_id"]),
                        "expected_target_policy_version": row["expected_policy_version"],
                        "status": row["status"],
                        "expires_at": row["expires_at"].isoformat(),
                        "decided_at": ""
                        if row["decided_at"] is None
                        else row["decided_at"].isoformat(),
                        "proposer_subject": row["proposer_subject"],
                        "reviewer_subject": row["reviewer_subject"] or "",
                        "reason": row["reason"],
                        "request_id": row["request_id"],
                        "external_qualification_ref": row["external_qualification_ref"],
                        "external_qualification_version": row[
                            "external_qualification_version"
                        ],
                        "target_role_key": row["target_role_key"] or "",
                        "target_role_version": row["target_role_version"] or 0,
                        "confirmed_role_version": row["confirmed_role_version"] or 0,
                        "target_action_keys": list(row["target_action_keys"] or []),
                        "target_expires_at": ""
                        if row["target_expires_at"] is None
                        else row["target_expires_at"].isoformat(),
                    }
                    for row in rows
                ],
            },
            headers=headers,
        )

    @oms.post("/approvals")
    async def oms_approval_create(request: Request, command: OmsApprovalCreateRequest):
        """创建 OMS 平台敏感授权审批；不直接授予角色或委托。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..management.approvals import (
            ApprovalConflict,
            CreateApprovalRequestCommand,
            create_management_approval_request,
        )
        from ..management.authorization import ManagementAuthorizationDenied

        headers = {"Cache-Control": "no-store"}
        if command.operation == "platform_grant":
            if (
                command.target_role_key is None
                or command.target_role_version is None
                or command.confirmed_role_version != command.target_role_version
                or command.target_expires_at is None
                or command.target_action_keys
            ):
                return JSONResponse({"detail": "Invalid request"}, status_code=422, headers=headers)
        if command.operation == "delegation_expand":
            if (
                not command.target_action_keys
                or command.target_role_key is not None
                or command.target_role_version is not None
                or command.confirmed_role_version is not None
                or command.target_expires_at is None
            ):
                return JSONResponse({"detail": "Invalid request"}, status_code=422, headers=headers)
        authorized = await _authorize_oms_request(request, "ops.permissions.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            async with enterprise.db.transaction(GlobalScope("@oms-approval-create")) as c:
                result = await create_management_approval_request(
                    c,
                    actor,
                    CreateApprovalRequestCommand(
                        operation=command.operation,
                        target_principal_id=command.target_principal_id,
                        target_school_id=None,
                        expected_target_policy_version=command.expected_target_policy_version,
                        expires_at=command.expires_at,
                        idempotency_key=command.idempotency_key,
                        reason=command.reason,
                        request_id=_request_id(request),
                        external_qualification_ref=command.external_qualification_ref,
                        external_qualification_version=command.external_qualification_version,
                        target_role_key=command.target_role_key,
                        target_role_version=command.target_role_version,
                        target_action_keys=tuple(command.target_action_keys),
                        target_expires_at=command.target_expires_at,
                        confirmed_role_version=command.confirmed_role_version,
                    ),
                )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ApprovalConflict:
            return JSONResponse({"detail": "Approval conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Approval unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "oms",
                "approval_id": str(result.approval_id),
                "status": result.status,
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @oms.post("/approvals/{approval_id}/review")
    async def oms_approval_review(
        request: Request, approval_id: UUID, command: OmsApprovalReviewRequest
    ):
        """独立平台安全管理员复核 OMS 授权审批；提议人不可自批。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..management.approvals import (
            ApprovalConflict,
            ReviewApprovalCommand,
            review_management_approval,
        )
        from ..management.authorization import ManagementAuthorizationDenied

        headers = {"Cache-Control": "no-store"}
        authorized = await _authorize_oms_request(request, "ops.permissions.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            async with enterprise.db.transaction(GlobalScope("@oms-approval-review")) as c:
                result = await review_management_approval(
                    c,
                    actor,
                    ReviewApprovalCommand(
                        approval_id=approval_id,
                        decision=command.decision,
                        expected_target_policy_version=command.expected_target_policy_version,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ApprovalConflict:
            return JSONResponse({"detail": "Approval conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Approval unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "oms",
                "approval_id": str(result.approval_id),
                "status": result.status,
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @oms.post("/approvals/{approval_id}/withdraw")
    async def oms_approval_withdraw(
        request: Request, approval_id: UUID, command: OmsApprovalWithdrawRequest
    ):
        """提议人撤回仍处于 pending 的 OMS 审批。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..management.approvals import (
            ApprovalConflict,
            WithdrawApprovalCommand,
            withdraw_management_approval,
        )
        from ..management.authorization import ManagementAuthorizationDenied

        headers = {"Cache-Control": "no-store"}
        authorized = await _authorize_oms_request(request, "ops.permissions.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            async with enterprise.db.transaction(GlobalScope("@oms-approval-withdraw")) as c:
                result = await withdraw_management_approval(
                    c,
                    actor,
                    WithdrawApprovalCommand(
                        approval_id=approval_id,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ApprovalConflict:
            return JSONResponse({"detail": "Approval conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Approval unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "oms",
                "approval_id": str(result.approval_id),
                "status": result.status,
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @oms.post("/approvals/{approval_id}/apply")
    async def oms_approval_apply(
        request: Request, approval_id: UUID, command: OmsApprovalApplyRequest
    ):
        """应用已批准的 OMS 敏感授权审批；不绕过审批终态。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..management.approvals import (
            ApplyApprovalCommand,
            ApprovalConflict,
            apply_approved_management_approval,
        )
        from ..management.authorization import ManagementAuthorizationDenied

        headers = {"Cache-Control": "no-store"}
        authorized = await _authorize_oms_request(request, "ops.permissions.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            async with enterprise.db.transaction(GlobalScope("@oms-approval-apply")) as c:
                result = await apply_approved_management_approval(
                    c,
                    actor,
                    ApplyApprovalCommand(
                        approval_id=approval_id,
                        expected_target_policy_version=command.expected_target_policy_version,
                        command_id=command.command_id,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ApprovalConflict:
            return JSONResponse({"detail": "Approval conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Approval unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "oms",
                "approval_id": str(result.approval_id),
                "assignment_id": "" if result.assignment_id is None else str(result.assignment_id),
                "role_key": result.role_key,
                "target_policy_version": result.target_policy_version,
                "replayed": result.replayed,
                "applied_kind": result.applied_kind,
                "delegation_ids": [str(item) for item in result.delegation_ids],
            },
            headers=headers,
        )

    @oms.post("/principals/{principal_id}/roles")
    async def oms_principal_role_grant(
        request: Request, principal_id: UUID, command: OmsPrincipalRoleGrantRequest
    ):
        """给已登记平台主体授予低风险学校范围 OMS 角色；敏感角色必须走审批。"""

        from ..management.authorization import ManagementAuthorizationDenied, ManagementIdentity
        from ..management.grants import (
            GrantRoleCommand,
            ManagementGrantConflict,
            grant_management_role,
        )

        headers = {"Cache-Control": "no-store"}
        authorized = await _authorize_oms_request(request, "ops.permissions.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        now = datetime.now(timezone.utc)
        try:
            async with enterprise.db.transaction(
                TenantScope(str(command.target_school_id), "@oms-principal-role-grant")
            ) as c:
                await c.execute("SELECT set_config('app.management_app','oms',true)")
                target_row = await (
                    await c.execute(
                        "SELECT id,issuer,subject,status,policy_version "
                        "FROM management.principals WHERE id=%s AND application='oms' "
                        "AND school_id IS NULL FOR UPDATE",
                        (principal_id,),
                    )
                ).fetchone()
                if target_row is None:
                    return JSONResponse(
                        {"detail": "Target principal not found"}, status_code=404, headers=headers
                    )
                if target_row["status"] not in {"pending", "active"}:
                    return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
                target = ManagementIdentity(
                    application="oms",
                    issuer=target_row["issuer"],
                    subject=target_row["subject"],
                    school_id=None,
                    policy_version=target_row["policy_version"],
                    school_binding_version=None,
                    external_active=True,
                    external_checked_at=now,
                    external_verified_until=now + timedelta(seconds=30),
                )
                result = await grant_management_role(
                    c,
                    actor,
                    target,
                    GrantRoleCommand(
                        target_principal_id=principal_id,
                        role_key=command.role_key,
                        role_version=command.role_version,
                        target_school_id=command.target_school_id,
                        expected_target_policy_version=command.expected_target_policy_version,
                        expires_at=command.expires_at,
                        command_id=command.command_id,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ManagementGrantConflict:
            return JSONResponse({"detail": "Grant conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse({"detail": "Grant unavailable"}, status_code=503, headers=headers)
        return JSONResponse(
            {
                "application": "oms",
                "principal_id": str(principal_id),
                "school_id": str(command.target_school_id),
                "assignment_id": str(result.assignment_id),
                "role_key": command.role_key,
                "role_version": command.role_version,
                "target_policy_version": result.target_policy_version,
                "status": "active",
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @oms.post("/assignments/{assignment_id}/revoke")
    async def oms_assignment_revoke(
        request: Request, assignment_id: UUID, command: OmsAssignmentRevokeRequest
    ):
        """撤销 OMS 平台或学校范围角色 assignment；撤权立即影响本地 PEP。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..management.authorization import ManagementAuthorizationDenied
        from ..management.grants import (
            ManagementGrantConflict,
            RevokeRoleCommand,
            revoke_management_role,
        )

        headers = {"Cache-Control": "no-store"}
        authorized = await _authorize_oms_request(request, "ops.permissions.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        scope = (
            GlobalScope("@oms-assignment-revoke")
            if command.target_school_id is None
            else TenantScope(str(command.target_school_id), "@oms-assignment-revoke")
        )
        try:
            async with enterprise.db.transaction(scope) as c:
                result = await revoke_management_role(
                    c,
                    actor,
                    RevokeRoleCommand(
                        assignment_id=assignment_id,
                        target_school_id=command.target_school_id,
                        expected_assignment_version=command.expected_assignment_version,
                        expected_target_policy_version=command.expected_target_policy_version,
                        command_id=command.command_id,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ManagementGrantConflict:
            return JSONResponse({"detail": "Revoke conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse({"detail": "Revoke unavailable"}, status_code=503, headers=headers)
        return JSONResponse(
            {
                "application": "oms",
                "assignment_id": str(result.assignment_id),
                "assignment_version": result.assignment_version,
                "target_policy_version": result.target_policy_version,
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @oms.post("/principals/{principal_id}/disable")
    async def oms_principal_disable(
        request: Request, principal_id: UUID, command: OmsPrincipalDisableRequest
    ):
        """停用 DeepTutor 本地 OMS 主体；不修改 EduPlus2 账号。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..management.authorization import ManagementAuthorizationDenied
        from ..management.principals import (
            DisablePrincipalCommand,
            disable_management_principal,
        )

        headers = {"Cache-Control": "no-store"}
        authorized = await _authorize_oms_request(request, "ops.permissions.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            async with enterprise.db.transaction(GlobalScope("@oms-principal-disable")) as c:
                result = await disable_management_principal(
                    c,
                    actor,
                    DisablePrincipalCommand(
                        target_principal_id=principal_id,
                        target_school_id=None,
                        expected_policy_version=command.expected_target_policy_version,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse({"detail": "Principal unavailable"}, status_code=503, headers=headers)
        return JSONResponse(
            {
                "application": "oms",
                "principal_id": str(result.target_principal_id),
                "target_policy_version": result.target_policy_version,
                "status": "disabled",
            },
            headers=headers,
        )

    @oms.get("/me")
    async def oms_me(request: Request):
        """独立 OMS 平台主体入口；不复用租户会话或 JWT 中的角色。"""

        authorized = await _authorize_oms_request(
            request, "ops.oms.access", allow_school_scope_access=True
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, decision = authorized
        return {
            "application": "oms",
            "subject": actor.subject,
            "policy_version": decision.policy_version,
        }

    @oms.get("/me/permissions")
    async def oms_me_permissions(request: Request):
        """正式 OMS 前端同源权限摘要；真实 API 仍逐次鉴权。"""

        from ..oms.governance import oms_permission_summary

        authorized = await _authorize_oms_request(
            request, "ops.oms.access", allow_school_scope_access=True
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            return await oms_permission_summary(enterprise, actor)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Permission unavailable"}, status_code=503)

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

    @oms.get("/status/catalog")
    async def oms_status_catalog(request: Request):
        """后端拥有的治理状态展示目录；前端不得硬编码 raw code 语义。"""

        from ..oms.governance import status_catalog

        authorized = await _authorize_oms_request(
            request, "ops.oms.access", allow_school_scope_access=True
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        return status_catalog()

    @oms.get("/summary")
    async def oms_summary(request: Request):
        """OMS 总览只聚合当前平台主体已获授权的学校与脱敏资源状态。"""

        from ..oms.governance import build_oms_summary

        authorized = await _authorize_oms_request(
            request, "ops.oms.access", allow_school_scope_access=True
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            return await build_oms_summary(enterprise, actor)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "OMS summary unavailable"}, status_code=503)

    @oms.get("/tenants")
    async def oms_tenants(request: Request):
        """只列出当前主体通过本产品 school-scope ops 授权可见的学校。"""

        from ..oms.governance import list_tenants_for_oms

        authorized = await _authorize_oms_request(
            request, "ops.oms.access", allow_school_scope_access=True
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            return await list_tenants_for_oms(enterprise, actor)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Tenant governance unavailable"}, status_code=503)

    @oms.get("/tenants/{school_id}")
    async def oms_tenant_detail(request: Request, school_id: UUID):
        from ..oms.governance import tenant_projection

        authorized = await _authorize_oms_request(
            request, "ops.tenants.read", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        try:
            return await tenant_projection(enterprise, school_id)
        except LookupError:
            return JSONResponse({"detail": "Resource not found"}, status_code=404)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Tenant governance unavailable"}, status_code=503)

    @oms.get("/supply")
    async def oms_supply(request: Request):
        from ..oms.governance import supply_projection

        authorized = await _authorize_oms_request(request, "ops.supply.read")
        if isinstance(authorized, JSONResponse):
            return authorized
        try:
            return await supply_projection(enterprise)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Supply governance unavailable"}, status_code=503)

    @oms.post("/supply/lots")
    async def oms_supply_lot_register(
        request: Request,
        command: OmsSupplyRegisterCommandRequest,
    ):
        """OMS 平台供给补充；证据引用只入账，不回显给浏览器。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..oms.supply import OmsSupplyLedger, SupplyRejected, SupplyRequest

        authorized = await _authorize_oms_request(request, "ops.supply.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            lot_id = await OmsSupplyLedger(enterprise.db).register(
                GlobalScope(actor.subject),
                SupplyRequest(
                    lot_id=command.lot_id,
                    service_id=command.service_id,
                    unit_code=command.unit_code,
                    provider_id=command.provider_id,
                    provider_account_id=command.provider_account_id,
                    pool_id=command.pool_id,
                    basis=command.basis,
                    hard_ceiling=command.hard_ceiling,
                    starts_at=command.starts_at,
                    expires_at=command.expires_at,
                    evidence_ref=command.evidence_ref,
                    verified_native=command.verified_native,
                    actor_subject=actor.subject,
                    request_id=_request_id(request),
                    reason=command.reason,
                ),
            )
        except SupplyRejected:
            return JSONResponse({"detail": "Supply command conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid supply command"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Supply command unavailable"}, status_code=503)
        return {"lot_id": str(lot_id), "service_id": command.service_id, "version": 1}

    @oms.post("/supply/lots/{lot_id}/revoke")
    async def oms_supply_lot_revoke(
        request: Request,
        lot_id: UUID,
        command: OmsSupplyRevokeCommandRequest,
    ):
        """OMS 平台供给批次撤销；由后端复核 supply manage 权限与版本。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        from ..oms.supply import OmsSupplyLedger, SupplyRejected, SupplyRevokeRequest

        authorized = await _authorize_oms_request(request, "ops.supply.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            version = await OmsSupplyLedger(enterprise.db).revoke(
                GlobalScope(actor.subject),
                SupplyRevokeRequest(
                    lot_id=lot_id,
                    expected_version=command.expected_version,
                    actor_subject=actor.subject,
                    request_id=_request_id(request),
                    reason=command.reason,
                ),
            )
        except SupplyRejected:
            return JSONResponse({"detail": "Supply revoke conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid supply revoke"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Supply revoke unavailable"}, status_code=503)
        return {"lot_id": str(lot_id), "version": version}

    @oms.get("/schools/{school_id}/usage")
    async def oms_school_usage(request: Request, school_id: UUID):
        from ..oms.governance import usage_projection

        authorized = await _authorize_oms_request(
            request, "ops.usage.read", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        try:
            return await usage_projection(
                enterprise,
                school_id,
                service_id=request.query_params.get("service_id", ""),
                provider_id=request.query_params.get("provider_id", ""),
                model_id=request.query_params.get("model_id", ""),
                unit_code=request.query_params.get("unit_code", ""),
                status=request.query_params.get("status", ""),
                subject_id=request.query_params.get("subject_id", ""),
                limit=int(request.query_params.get("limit", "50")),
                offset=int(request.query_params.get("offset", "0")),
            )
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Usage governance unavailable"}, status_code=503)

    @oms.get("/schools/{school_id}/usage/export")
    async def oms_school_usage_export(request: Request, school_id: UUID):
        from ..oms.governance import usage_export_projection

        authorized = await _authorize_oms_request(
            request, "ops.audit.export", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            return await usage_export_projection(
                enterprise,
                school_id,
                actor_subject=actor.subject,
                request_id=_request_id(request),
                limit=int(request.query_params.get("limit", "500")),
            )
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Usage export unavailable"}, status_code=503)

    @oms.get("/schools/{school_id}/jobs")
    async def oms_school_jobs(request: Request, school_id: UUID):
        from ..oms.governance import jobs_projection

        authorized = await _authorize_oms_request(
            request, "ops.jobs.read", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        try:
            return await jobs_projection(enterprise, school_id)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Job governance unavailable"}, status_code=503)

    @oms.post("/schools/{school_id}/usage/provider-receipts")
    async def oms_provider_receipt_settle(
        request: Request,
        school_id: UUID,
        command: OmsProviderReceiptSettleCommandRequest,
    ):
        """OMS/受控对账按 provider request/task ID 回填原 attempt；不回显 receipt。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.attempts import (
            OmsAttemptLedger,
            SettlementRejected,
            UsageExceedsReservation,
        )

        authorized = await _authorize_oms_request(
            request, "ops.reconciliation.manage", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await OmsAttemptLedger(
                enterprise.db
            ).settle_provider_receipt_as_reconciler(
                TenantScope(str(school_id), actor.subject),
                actor,
                provider_id=command.provider_id,
                provider_account_id=command.provider_account_id,
                provider_request_id=command.provider_request_id,
                units=command.units,
                evidence_ref=command.evidence_ref,
                reason=command.reason,
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except UsageExceedsReservation:
            return JSONResponse({"detail": "Reconciliation required"}, status_code=409)
        except SettlementRejected:
            return JSONResponse({"detail": "Settlement conflict"}, status_code=409)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Settlement unavailable"}, status_code=503)
        return {
            "attempt_id": str(result.attempt_id),
            "status": result.status,
            "settled_units": _decimal_text(result.settled_units),
        }

    @oms.post("/schools/{school_id}/attempts/{attempt_id}/settle")
    async def oms_attempt_settle(
        request: Request,
        school_id: UUID,
        attempt_id: UUID,
        command: OmsAttemptSettleCommandRequest,
    ):
        """OMS 人工核对/更正 attempt；原始 evidence 入账但不回显。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.attempts import (
            OmsAttemptLedger,
            SettlementRejected,
            UsageExceedsReservation,
        )

        authorized = await _authorize_oms_request(
            request, "ops.reconciliation.manage", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await OmsAttemptLedger(enterprise.db).settle_as_reconciler(
                TenantScope(str(school_id), actor.subject),
                actor,
                attempt_id,
                units=command.units,
                source=command.source,
                evidence_ref=command.evidence_ref,
                provider_request_id=command.provider_request_id,
                reason=command.reason,
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except UsageExceedsReservation:
            return JSONResponse({"detail": "Reconciliation required"}, status_code=409)
        except SettlementRejected:
            return JSONResponse({"detail": "Settlement conflict"}, status_code=409)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Settlement unavailable"}, status_code=503)
        return {
            "attempt_id": str(result.attempt_id),
            "status": result.status,
            "settled_units": _decimal_text(result.settled_units),
        }

    @oms.post("/schools/{school_id}/attempts/{attempt_id}/release")
    async def oms_attempt_release(
        request: Request,
        school_id: UUID,
        attempt_id: UUID,
        command: OmsAttemptReleaseCommandRequest,
    ):
        """OMS 核对确认未发出后释放预留；原始 evidence 入账但不回显。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.attempts import OmsAttemptLedger, SettlementRejected

        authorized = await _authorize_oms_request(
            request, "ops.reconciliation.manage", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await OmsAttemptLedger(enterprise.db).release_as_reconciler(
                TenantScope(str(school_id), actor.subject),
                actor,
                attempt_id,
                evidence_ref=command.evidence_ref,
                reason=command.reason,
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except SettlementRejected:
            return JSONResponse({"detail": "Release conflict"}, status_code=409)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Release unavailable"}, status_code=503)
        return {"attempt_id": str(result.attempt_id), "status": result.status}

    @oms.get("/audit")
    async def oms_audit(request: Request):
        from ..oms.governance import audit_projection

        raw_school_id = request.query_params.get("school_id", "").strip()
        try:
            school_id = UUID(raw_school_id) if raw_school_id else None
            limit = int(request.query_params.get("limit", "50"))
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        authorized = await _authorize_oms_request(
            request, "ops.audit.read", target_school_id=school_id
        )
        if isinstance(authorized, JSONResponse):
            return authorized
        try:
            return await audit_projection(enterprise, application="oms", school_id=school_id, limit=limit)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Audit governance unavailable"}, status_code=503)

    @oms.get("/cost")
    async def oms_cost(request: Request):
        """成本为 OMS-only 敏感读取；没有可信成本源时返回未配置状态而不是伪造金额。"""

        from ..oms.governance import cost_projection

        authorized = await _authorize_oms_request(request, "ops.cost.read")
        if isinstance(authorized, JSONResponse):
            return authorized
        try:
            return await cost_projection(enterprise)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Cost governance unavailable"}, status_code=503)

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

    @oms.get("/provider-settings")
    async def oms_provider_settings_read(request: Request):
        """全服务 Provider 设置的脱敏读模型；不输出 endpoint Secret 或明文凭据。"""

        from ..oms.provider_settings import read_provider_settings

        authorized = await _authorize_oms_request(request, "ops.providers.read")
        if isinstance(authorized, JSONResponse):
            return authorized
        try:
            return await read_provider_settings(enterprise)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Provider settings unavailable"}, status_code=503)

    @oms.post("/provider-settings/dry-run")
    async def oms_provider_settings_dry_run(
        request: Request, command: OmsProviderSettingsDryRunRequest
    ):
        """旧 JSON 导入 dry-run：只保存 hash 与脱敏预览，不写 active。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.provider_settings import record_provider_settings_dry_run

        authorized = await _authorize_oms_request(request, "ops.providers.read")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            result = await record_provider_settings_dry_run(
                enterprise, actor, source_kind=command.source_kind, raw_settings=command.settings
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except ValueError:
            return JSONResponse({"detail": "Invalid provider settings"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Provider settings unavailable"}, status_code=503)
        return {
            "id": str(result.id),
            "source_hash": result.source_hash,
            "recognized_sections": list(result.recognized_sections),
            "unsupported_sections": list(result.unsupported_sections),
            "secret_paths": list(result.secret_paths),
            "result": result.result,
        }

    @oms.post("/provider-settings/draft")
    async def oms_provider_settings_draft(
        request: Request, command: OmsProviderSettingsDraftRequest
    ):
        """保存全服务配置草稿；Secret 必须是引用，绝不接受明文。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.provider_settings import ProviderSettingsConflict, save_provider_settings_draft

        authorized = await _authorize_oms_request(request, "ops.providers.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            return await save_provider_settings_draft(
                enterprise,
                actor,
                settings=command.settings,
                expected_version=command.expected_version,
                reason=command.reason,
                request_id=_request_id(request),
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except ProviderSettingsConflict:
            return JSONResponse({"detail": "Version conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid provider settings"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Provider settings unavailable"}, status_code=503)

    @oms.post("/provider-settings/test")
    async def oms_provider_settings_test(
        request: Request, command: OmsProviderSettingsCommandRequest
    ):
        """逐执行者确认草稿可装载；失败时 active 保持旧版本。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.provider_settings import (
            ProviderSettingsConflict,
            ProviderSettingsUnavailable,
            test_provider_settings,
        )

        authorized = await _authorize_oms_request(request, "ops.providers.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            return await test_provider_settings(
                enterprise,
                actor,
                expected_version=command.expected_version,
                reason=command.reason,
                request_id=_request_id(request),
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except ProviderSettingsConflict:
            return JSONResponse({"detail": "Version conflict"}, status_code=409)
        except ProviderSettingsUnavailable:
            return JSONResponse({"detail": "Provider settings unavailable"}, status_code=503)
        except ValueError:
            return JSONResponse({"detail": "Invalid provider settings"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Provider settings unavailable"}, status_code=503)

    @oms.post("/provider-settings/publish")
    async def oms_provider_settings_publish(
        request: Request, command: OmsProviderSettingsCommandRequest
    ):
        """确认后发布 active 配置；失败时只记录 failed，不污染运行态。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.provider_settings import (
            ProviderSettingsConflict,
            ProviderSettingsUnavailable,
            publish_provider_settings,
        )

        authorized = await _authorize_oms_request(request, "ops.providers.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            return await publish_provider_settings(
                enterprise,
                actor,
                expected_version=command.expected_version,
                reason=command.reason,
                request_id=_request_id(request),
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except ProviderSettingsConflict:
            return JSONResponse({"detail": "Version conflict"}, status_code=409)
        except ProviderSettingsUnavailable:
            return JSONResponse({"detail": "Provider settings unavailable"}, status_code=503)
        except ValueError:
            return JSONResponse({"detail": "Invalid provider settings"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Provider settings unavailable"}, status_code=503)

    @oms.post("/provider-settings/rollback")
    async def oms_provider_settings_rollback(
        request: Request, command: OmsProviderSettingsCommandRequest
    ):
        """丢弃未生效草稿，恢复 desired 到当前 active。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..oms.provider_settings import ProviderSettingsConflict, rollback_provider_settings

        authorized = await _authorize_oms_request(request, "ops.providers.manage")
        if isinstance(authorized, JSONResponse):
            return authorized
        actor, _ = authorized
        try:
            return await rollback_provider_settings(
                enterprise,
                actor,
                expected_version=command.expected_version,
                reason=command.reason,
                request_id=_request_id(request),
            )
        except ManagementAuthorizationDenied:
            return JSONResponse({"detail": "Permission denied"}, status_code=403)
        except ProviderSettingsConflict:
            return JSONResponse({"detail": "Version conflict"}, status_code=409)
        except ValueError:
            return JSONResponse({"detail": "Invalid provider settings"}, status_code=422)
        except (RuntimeError, psycopg.Error):
            return JSONResponse({"detail": "Provider settings unavailable"}, status_code=503)

    @oms.get("/skills")
    async def oms_skills_list(request: Request):
        """OMS global Skill 只读列表；不返回 ObjectStore key 或包内正文。"""

        from deeptutor.persistence.postgres.scope import GlobalScope

        authorized = await _authorize_oms_request(request, "ops.skills.read")
        if isinstance(authorized, JSONResponse):
            return authorized
        headers = {"Cache-Control": "no-store"}
        try:
            async with enterprise.db.transaction(GlobalScope("@oms-skills-list")) as c:
                await c.execute("SELECT set_config('app.management_app','oms',true)")
                rows = await (
                    await c.execute(
                        "WITH latest AS ("
                        "  SELECT DISTINCT ON (name) id,name,version,content_sha256,metadata,created_at "
                        "  FROM oms.skill_revisions "
                        "  WHERE owner_kind='global' AND owner_school_id IS NULL "
                        "  ORDER BY name,version DESC,created_at DESC"
                        "), review_state AS ("
                        "  SELECT DISTINCT ON (revision_id) revision_id,approved,reviewed_at "
                        "  FROM oms.skill_reviews ORDER BY revision_id,reviewed_at DESC,id DESC"
                        ") "
                        "SELECT l.id,l.name,l.version,l.content_sha256,l.metadata,"
                        "p.revision_id AS published_revision_id,p.version AS published_version,"
                        "rs.approved "
                        "FROM latest l "
                        "LEFT JOIN oms.skill_publications p ON p.owner_kind='global' "
                        "AND p.owner_school_id IS NULL AND p.name=l.name "
                        "LEFT JOIN review_state rs ON rs.revision_id=l.id "
                        "ORDER BY l.name"
                    )
                ).fetchall()
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse({"detail": "Skill catalog unavailable"}, status_code=503)

        def _metadata_value(row, key: str, default):
            metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
            value = metadata.get(key, default)
            return value if isinstance(value, type(default)) else default

        skills = []
        for row in rows:
            published_revision_id = row["published_revision_id"]
            if published_revision_id == row["id"]:
                status = "published"
            elif row["approved"] is True:
                status = "approved"
            elif row["approved"] is False:
                status = "rejected"
            else:
                status = "draft"
            skills.append(
                {
                    "name": row["name"],
                    "status": status,
                    "latest_version": row["version"],
                    "published_version": 0 if row["published_version"] is None else row["published_version"],
                    "published_revision_id": "" if published_revision_id is None else str(published_revision_id),
                    "sha256": row["content_sha256"],
                    "description": _metadata_value(row, "description", ""),
                    "tags": _metadata_value(row, "tags", []),
                    "grant_count": 0,
                }
            )
        return JSONResponse({"application": "oms", "skills": skills}, headers=headers)

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

    @tms_bootstrap.get("/skills")
    async def tms_skills_list(request: Request):
        """当前学校已授权 global Skill 只读列表；不泄露平台存储路径。"""

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-skills-list")
            ) as c:
                await require_management_permission(
                    c,
                    identity,
                    "tenant.tms.access",
                    target_school_id=identity.school_id,
                    write=False,
                )
                rows = await (
                    await c.execute(
                        "SELECT g.name,g.revision_id,g.publication_version,g.version AS grant_version,"
                        "g.status,r.content_sha256,r.metadata "
                        "FROM oms.skill_grants g "
                        "JOIN oms.skill_publications p ON p.owner_kind='global' "
                        "AND p.owner_school_id IS NULL AND p.name=g.name "
                        "AND p.revision_id=g.revision_id AND p.version=g.publication_version "
                        "JOIN oms.skill_revisions r ON r.id=g.revision_id "
                        "AND r.owner_kind='global' AND r.owner_school_id IS NULL "
                        "WHERE g.tenant_id=%s AND g.status='active' AND g.expires_at>now() "
                        "ORDER BY g.name",
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
            return JSONResponse({"detail": "Skill catalog unavailable"}, status_code=503)

        def _metadata_value(row, key: str, default):
            metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
            value = metadata.get(key, default)
            return value if isinstance(value, type(default)) else default

        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "skills": [
                    {
                        "name": row["name"],
                        "revision_id": str(row["revision_id"]),
                        "publication_version": row["publication_version"],
                        "grant_version": row["grant_version"],
                        "status": row["status"],
                        "sha256": row["content_sha256"],
                        "description": _metadata_value(row, "description", ""),
                        "tags": _metadata_value(row, "tags", []),
                    }
                    for row in rows
                ],
            },
            headers=headers,
        )

    @tms_bootstrap.get("/permissions")
    async def tms_permissions_catalog(request: Request):
        """当前学校 TMS 权限管理只读 DTO；写入仍须独立审批/命令 API。"""

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-permissions-catalog")
            ) as c:
                await require_management_permission(
                    c,
                    identity,
                    "tenant.permissions.manage",
                    target_school_id=identity.school_id,
                    write=False,
                )
                actions = await (
                    await c.execute(
                        "SELECT action_key,allowed_scope,sensitive,status,version "
                        "FROM management.action_catalog WHERE application='tms' "
                        "ORDER BY action_key"
                    )
                ).fetchall()
                role_rows = await (
                    await c.execute(
                        "SELECT rv.role_key,rv.version,rv.scope_kind,rv.is_template,"
                        "rv.owner_school_id,ra.action_key "
                        "FROM management.role_versions rv "
                        "LEFT JOIN management.role_actions ra ON ra.application=rv.application "
                        "AND ra.role_key=rv.role_key AND ra.role_version=rv.version "
                        "WHERE rv.application='tms' AND rv.scope_kind='school' "
                        "AND (rv.is_template OR rv.owner_school_id=%s) "
                        "ORDER BY rv.role_key,rv.version,ra.action_key",
                        (identity.school_id,),
                    )
                ).fetchall()
                principals = await (
                    await c.execute(
                        "SELECT id,issuer,subject,status,policy_version,created_at,updated_at "
                        "FROM management.principals WHERE application='tms' AND school_id=%s "
                        "ORDER BY subject,id LIMIT 500",
                        (identity.school_id,),
                    )
                ).fetchall()
                assignments = await (
                    await c.execute(
                        "SELECT a.id,a.principal_id,p.subject,a.role_key,a.role_version,"
                        "a.scope_kind,a.school_id,a.status,a.version,a.valid_from,a.expires_at,"
                        "a.revoked_at,a.school_binding_version "
                        "FROM management.assignments a "
                        "JOIN management.principals p ON p.application=a.application "
                        "AND p.id=a.principal_id "
                        "WHERE a.application='tms' AND a.school_id=%s "
                        "ORDER BY a.created_at DESC,a.id LIMIT 500",
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
                {"detail": "Permission catalog unavailable"}, status_code=503, headers=headers
            )

        roles_by_id: dict[tuple[str, int], dict[str, object]] = {}
        for row in role_rows:
            key = (row["role_key"], row["version"])
            role = roles_by_id.setdefault(
                key,
                {
                    "role_key": row["role_key"],
                    "version": row["version"],
                    "scope_kind": row["scope_kind"],
                    "is_template": row["is_template"],
                    "owner_school_id": "" if row["owner_school_id"] is None else str(row["owner_school_id"]),
                    "actions": [],
                },
            )
            if row["action_key"]:
                actions_list = role["actions"]
                if isinstance(actions_list, list):
                    actions_list.append(row["action_key"])
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "actions": [
                    {
                        "action_key": row["action_key"],
                        "allowed_scope": row["allowed_scope"],
                        "sensitive": row["sensitive"],
                        "status": row["status"],
                        "version": row["version"],
                    }
                    for row in actions
                    if isinstance(row["action_key"], str) and row["action_key"].startswith("tenant.")
                ],
                "roles": list(roles_by_id.values()),
                "principals": [
                    {
                        "principal_id": str(row["id"]),
                        "issuer": row["issuer"],
                        "subject": row["subject"],
                        "status": row["status"],
                        "policy_version": row["policy_version"],
                        "created_at": row["created_at"].isoformat(),
                        "updated_at": row["updated_at"].isoformat(),
                    }
                    for row in principals
                ],
                "assignments": [
                    {
                        "assignment_id": str(row["id"]),
                        "principal_id": str(row["principal_id"]),
                        "subject": row["subject"],
                        "role_key": row["role_key"],
                        "role_version": row["role_version"],
                        "scope_kind": row["scope_kind"],
                        "school_id": str(row["school_id"]),
                        "school_binding_version": row["school_binding_version"],
                        "status": row["status"],
                        "version": row["version"],
                        "valid_from": row["valid_from"].isoformat(),
                        "expires_at": row["expires_at"].isoformat(),
                        "revoked_at": "" if row["revoked_at"] is None else row["revoked_at"].isoformat(),
                    }
                    for row in assignments
                ],
            },
            headers=headers,
        )

    @tms_bootstrap.get("/authz-audit")
    async def tms_authz_audit(request: Request):
        """当前学校授权审计安全 DTO；不包含 OMS、Secret、token 或私有正文。"""

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        def _page_number(name: str, default: int, *, minimum: int, maximum: int) -> int:
            raw = request.query_params.get(name, str(default)).strip()
            if not raw.isdecimal():
                raise ValueError("invalid audit page")
            return min(max(int(raw), minimum), maximum)

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            limit = _page_number("limit", 50, minimum=1, maximum=200)
            offset = _page_number("offset", 0, minimum=0, maximum=10_000)
            filters = []
            params: list[object] = [identity.school_id]
            for column, key in (
                ("action_key", "action_key"),
                ("target_kind", "target_kind"),
                ("result", "result"),
                ("request_id", "request_id"),
            ):
                value = request.query_params.get(key, "").strip()
                if not value:
                    continue
                if len(value) > 128:
                    raise ValueError("audit filter is too long")
                filters.append(f"{column}=%s")
                params.append(value)
            where = " AND " + " AND ".join(filters) if filters else ""
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-authz-audit")
            ) as c:
                await require_management_permission(
                    c,
                    identity,
                    "tenant.permissions.manage",
                    target_school_id=identity.school_id,
                    write=False,
                )
                rows = await (
                    await c.execute(
                        "SELECT id,actor_subject,action_key,target_kind,target_id,"
                        "request_id,result,reason,before_version,after_version,"
                        "approval_id,safe_summary,created_at "
                        "FROM management.audit_events "
                        "WHERE application='tms' AND school_id=%s "
                        + where
                        + " ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s",
                        (*params, limit, offset),
                    )
                ).fetchall()
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Authorization audit unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "page": {"limit": limit, "offset": offset, "count": len(rows)},
                "events": [
                    {
                        "event_id": str(row["id"]),
                        "actor_subject": row["actor_subject"],
                        "action_key": row["action_key"],
                        "target_kind": row["target_kind"],
                        "target_id": row["target_id"],
                        "request_id": row["request_id"],
                        "result": row["result"],
                        "reason": row["reason"],
                        "before_version": row["before_version"],
                        "after_version": row["after_version"],
                        "approval_id": ""
                        if row["approval_id"] is None
                        else str(row["approval_id"]),
                        "safe_summary": row["safe_summary"]
                        if isinstance(row["safe_summary"], dict)
                        else {},
                        "created_at": row["created_at"].isoformat(),
                    }
                    for row in rows
                    if isinstance(row["action_key"], str)
                    and row["action_key"].startswith("tenant.")
                ],
            },
            headers=headers,
        )

    @tms_bootstrap.get("/members")
    async def tms_members_list(request: Request):
        """当前学校本产品成员主体只读列表；不查询或创建外部账号。"""

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
            raw = request.query_params.get(name, str(default)).strip()
            if not raw.isdecimal():
                raise ValueError("invalid members page")
            return min(max(int(raw), minimum), maximum)

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            limit = _bounded_int("limit", 50, minimum=1, maximum=200)
            offset = _bounded_int("offset", 0, minimum=0, maximum=10_000)
            filters = []
            params: list[object] = [identity.school_id]
            subject_filter = request.query_params.get("subject", "").strip()
            if subject_filter:
                if len(subject_filter) > 255:
                    raise ValueError("member filter is too long")
                filters.append("subject=%s")
                params.append(subject_filter)
            status_filter = request.query_params.get("status", "").strip()
            if status_filter:
                if len(status_filter) > 64:
                    raise ValueError("member status filter is too long")
                filters.append("status=%s")
                params.append(status_filter)
            where = " AND " + " AND ".join(filters) if filters else ""
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-members-list")
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
                    "tenant.members.read",
                    target_school_id=identity.school_id,
                    write=False,
                )
                principals = await (
                    await c.execute(
                        "SELECT id,subject,status,policy_version,created_at,updated_at "
                        "FROM management.principals "
                        "WHERE application='tms' AND school_id=%s "
                        + where
                        + " ORDER BY updated_at DESC,id LIMIT %s OFFSET %s",
                        (*params, limit, offset),
                    )
                ).fetchall()
                principal_ids = [row["id"] for row in principals]
                assignments = (
                    []
                    if not principal_ids
                    else await (
                        await c.execute(
                            "SELECT id,principal_id,role_key,role_version,status,version,"
                            "expires_at,revoked_at "
                            "FROM management.assignments "
                            "WHERE application='tms' AND school_id=%s "
                            "AND principal_id=ANY(%s::uuid[]) "
                            "ORDER BY created_at DESC,id",
                            (identity.school_id, principal_ids),
                        )
                    ).fetchall()
                )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse({"detail": "Members unavailable"}, status_code=503, headers=headers)

        roles_by_principal: dict[UUID, list[dict[str, object]]] = {}
        for row in assignments:
            roles_by_principal.setdefault(row["principal_id"], []).append(
                {
                    "assignment_id": str(row["id"]),
                    "role_key": row["role_key"],
                    "role_version": row["role_version"],
                    "status": row["status"],
                    "version": row["version"],
                    "expires_at": row["expires_at"].isoformat(),
                    "revoked_at": ""
                    if row["revoked_at"] is None
                    else row["revoked_at"].isoformat(),
                }
            )
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "page": {"limit": limit, "offset": offset, "count": len(principals)},
                "members": [
                    {
                        "principal_id": str(row["id"]),
                        "subject": row["subject"],
                        "status": row["status"],
                        "policy_version": row["policy_version"],
                        "roles": roles_by_principal.get(row["id"], []),
                        "created_at": row["created_at"].isoformat(),
                        "updated_at": row["updated_at"].isoformat(),
                    }
                    for row in principals
                ],
            },
            headers=headers,
        )

    @tms_bootstrap.get("/directory/users")
    async def tms_directory_users(request: Request):
        """外部学校目录未核实时失败关闭；不返回合成用户。"""

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        query = request.query_params.get("q", "").strip()
        try:
            if len(query) > 128:
                raise ValueError("directory query is too long")
            identity = await _tms_bootstrap_identity(request)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-directory-users")
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
                    "tenant.members.read",
                    target_school_id=identity.school_id,
                    write=False,
                )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse({"detail": "Directory unavailable"}, status_code=503, headers=headers)
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "status": "not_enabled",
                "reason_code": "external_directory_contract_missing",
                "message": "学校成员目录尚未核实第三方应用授权码用户令牌与策略范围，当前仅支持本人登录登记。",
                "query": query,
                "users": [],
            },
            headers=headers,
        )

    @tms_bootstrap.get("/approvals")
    async def tms_approvals_list(request: Request):
        """当前学校高风险授权审批请求列表；只读本地事实。"""

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
            raw = request.query_params.get(name, str(default)).strip()
            if not raw.isdecimal():
                raise ValueError("invalid approvals page")
            return min(max(int(raw), minimum), maximum)

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            limit = _bounded_int("limit", 50, minimum=1, maximum=200)
            offset = _bounded_int("offset", 0, minimum=0, maximum=10_000)
            status = request.query_params.get("status", "").strip()
            filters = []
            params: list[object] = [identity.school_id]
            if status:
                if len(status) > 64:
                    raise ValueError("approval status filter is too long")
                filters.append("status=%s")
                params.append(status)
            where = " AND " + " AND ".join(filters) if filters else ""
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-approvals-list")
            ) as c:
                await require_management_permission(
                    c,
                    identity,
                    "tenant.permissions.manage",
                    target_school_id=identity.school_id,
                    write=False,
                )
                rows = await (
                    await c.execute(
                        "SELECT id,operation,target_principal_id,expected_policy_version,"
                        "status,expires_at,decided_at,proposer_subject,reviewer_subject,"
                        "reason,request_id,external_qualification_ref,"
                        "external_qualification_version "
                        "FROM management.approval_requests "
                        "WHERE application='tms' AND school_id=%s "
                        + where
                        + " ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s",
                        (*params, limit, offset),
                    )
                ).fetchall()
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Approvals unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "page": {"limit": limit, "offset": offset, "count": len(rows)},
                "approvals": [
                    {
                        "approval_id": str(row["id"]),
                        "operation": row["operation"],
                        "target_principal_id": str(row["target_principal_id"]),
                        "expected_target_policy_version": row["expected_policy_version"],
                        "status": row["status"],
                        "expires_at": row["expires_at"].isoformat(),
                        "decided_at": ""
                        if row["decided_at"] is None
                        else row["decided_at"].isoformat(),
                        "proposer_subject": row["proposer_subject"],
                        "reviewer_subject": row["reviewer_subject"] or "",
                        "reason": row["reason"],
                        "request_id": row["request_id"],
                        "external_qualification_ref": row["external_qualification_ref"],
                        "external_qualification_version": row[
                            "external_qualification_version"
                        ],
                    }
                    for row in rows
                ],
            },
            headers=headers,
        )

    @tms_bootstrap.post("/approvals")
    async def tms_approval_create(request: Request, command: TmsApprovalCreateRequest):
        """创建当前学校高风险授权审批请求；不直接授予角色。"""

        from ..management.approvals import (
            ApprovalConflict,
            CreateApprovalRequestCommand,
            create_management_approval_request,
        )
        from ..management.authorization import ManagementAuthorizationDenied
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-approval-create")
            ) as c:
                result = await create_management_approval_request(
                    c,
                    identity,
                    CreateApprovalRequestCommand(
                        operation=command.operation,
                        target_principal_id=command.target_principal_id,
                        target_school_id=identity.school_id,
                        expected_target_policy_version=command.expected_target_policy_version,
                        expires_at=command.expires_at,
                        idempotency_key=command.idempotency_key,
                        reason=command.reason,
                        request_id=_request_id(request),
                        external_qualification_ref=command.external_qualification_ref,
                        external_qualification_version=command.external_qualification_version,
                    ),
                )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ApprovalConflict:
            return JSONResponse({"detail": "Approval conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Approval unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "approval_id": str(result.approval_id),
                "status": result.status,
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @tms_bootstrap.post("/approvals/{approval_id}/review")
    async def tms_approval_review(
        request: Request, approval_id: UUID, command: TmsApprovalReviewRequest
    ):
        """同校独立管理员复核审批请求；被授权人或提议人不可自批。"""

        from ..management.approvals import (
            ApprovalConflict,
            ReviewApprovalCommand,
            review_management_approval,
        )
        from ..management.authorization import ManagementAuthorizationDenied
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-approval-review")
            ) as c:
                result = await review_management_approval(
                    c,
                    identity,
                    ReviewApprovalCommand(
                        approval_id=approval_id,
                        decision=command.decision,
                        expected_target_policy_version=command.expected_target_policy_version,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ApprovalConflict:
            return JSONResponse({"detail": "Approval conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Approval unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "approval_id": str(result.approval_id),
                "status": result.status,
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @tms_bootstrap.post("/approvals/{approval_id}/withdraw")
    async def tms_approval_withdraw(
        request: Request, approval_id: UUID, command: TmsApprovalWithdrawRequest
    ):
        """提议人撤回仍处于 pending 的当前学校审批请求。"""

        from ..management.approvals import (
            ApprovalConflict,
            WithdrawApprovalCommand,
            withdraw_management_approval,
        )
        from ..management.authorization import ManagementAuthorizationDenied
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-approval-withdraw")
            ) as c:
                result = await withdraw_management_approval(
                    c,
                    identity,
                    WithdrawApprovalCommand(
                        approval_id=approval_id,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ApprovalConflict:
            return JSONResponse({"detail": "Approval conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Approval unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "approval_id": str(result.approval_id),
                "status": result.status,
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @tms_bootstrap.post("/approvals/{approval_id}/apply")
    async def tms_approval_apply(
        request: Request, approval_id: UUID, command: TmsApprovalApplyRequest
    ):
        """应用已批准的当前学校高风险授权请求；不绕过审批结果。"""

        from ..management.approvals import (
            ApplyApprovalCommand,
            ApprovalConflict,
            apply_approved_management_approval,
        )
        from ..management.authorization import ManagementAuthorizationDenied
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-approval-apply")
            ) as c:
                result = await apply_approved_management_approval(
                    c,
                    identity,
                    ApplyApprovalCommand(
                        approval_id=approval_id,
                        expected_target_policy_version=command.expected_target_policy_version,
                        command_id=command.command_id,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ApprovalConflict:
            return JSONResponse({"detail": "Approval conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Approval unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "approval_id": str(result.approval_id),
                "assignment_id": str(result.assignment_id),
                "role_key": result.role_key,
                "target_policy_version": result.target_policy_version,
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @tms_bootstrap.get("/me/permissions")
    async def tms_me_permissions(request: Request):
        """正式 TMS 前端同源权限摘要；真实 API 仍逐次鉴权。"""

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            tms_permission_summary,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            return JSONResponse(
                await tms_permission_summary(enterprise, identity),
                headers=headers,
            )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Permission unavailable"}, status_code=503, headers=headers
            )

    @tms_bootstrap.post("/me/register")
    async def tms_me_register(request: Request):
        """当前学校成员本人登录后登记本产品零权主体；不授予角色。"""

        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            principal_id = uuid.uuid4()
            evidence = "tms-self-register:" + _request_id(request)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-self-register")
            ) as c:
                await c.execute("SELECT set_config('app.management_app','tms',true)")
                row = await (
                    await c.execute(
                        "INSERT INTO management.principals"
                        "(id,application,issuer,subject,school_id,status,external_evidence_ref) "
                        "VALUES(%s,'tms',%s,%s,%s,'pending',%s) "
                        "ON CONFLICT (issuer,subject,school_id) WHERE application='tms' "
                        "DO UPDATE SET external_evidence_ref=EXCLUDED.external_evidence_ref,"
                        "updated_at=clock_timestamp() "
                        "WHERE management.principals.status<>'disabled' "
                        "RETURNING id,status,policy_version,created_at,updated_at",
                        (
                            principal_id,
                            identity.issuer,
                            identity.subject,
                            identity.school_id,
                            evidence,
                        ),
                    )
                ).fetchone()
                if row is None:
                    return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except TmsSchoolDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse({"detail": "Registration unavailable"}, status_code=503)
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "principal_id": str(row["id"]),
                "issuer": identity.issuer,
                "subject": identity.subject,
                "status": row["status"],
                "policy_version": row["policy_version"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
            },
            headers=headers,
        )

    @tms_bootstrap.post("/members/{principal_id}/roles")
    async def tms_member_role_grant(
        request: Request, principal_id: UUID, command: TmsMemberRoleGrantRequest
    ):
        """给已本人登录登记的当前学校主体授予低风险 TMS 角色。"""

        from ..management.authorization import ManagementAuthorizationDenied, ManagementIdentity
        from ..management.grants import (
            GrantRoleCommand,
            ManagementGrantConflict,
            grant_management_role,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            actor = await _tms_bootstrap_identity(request)
            now = datetime.now(timezone.utc)
            async with enterprise.db.transaction(
                TenantScope(str(actor.school_id), "@tms-member-role-grant")
            ) as c:
                await c.execute("SELECT set_config('app.management_app','tms',true)")
                await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(actor.school_id),))
                target_row = await (
                    await c.execute(
                        "SELECT id,issuer,subject,status,policy_version,school_id "
                        "FROM management.principals WHERE id=%s AND application='tms' "
                        "AND school_id=%s FOR UPDATE",
                        (principal_id, actor.school_id),
                    )
                ).fetchone()
                if target_row is None:
                    return JSONResponse(
                        {"detail": "Target principal not found"},
                        status_code=404,
                        headers=headers,
                    )
                if target_row["status"] not in {"pending", "active"}:
                    return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
                target = ManagementIdentity(
                    application="tms",
                    issuer=target_row["issuer"],
                    subject=target_row["subject"],
                    school_id=actor.school_id,
                    policy_version=target_row["policy_version"],
                    school_binding_version=actor.school_binding_version,
                    external_active=True,
                    external_checked_at=now,
                    external_verified_until=now + timedelta(seconds=30),
                    webhook_app_id=actor.webhook_app_id,
                )
                result = await grant_management_role(
                    c,
                    actor,
                    target,
                    GrantRoleCommand(
                        target_principal_id=principal_id,
                        role_key=command.role_key,
                        role_version=command.role_version,
                        target_school_id=actor.school_id,
                        expected_target_policy_version=command.expected_target_policy_version,
                        expires_at=command.expires_at,
                        command_id=command.command_id,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ManagementGrantConflict:
            return JSONResponse({"detail": "Grant conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse({"detail": "Grant unavailable"}, status_code=503)
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(actor.school_id),
                "principal_id": str(principal_id),
                "assignment_id": str(result.assignment_id),
                "role_key": command.role_key,
                "role_version": command.role_version,
                "target_policy_version": result.target_policy_version,
                "status": "active",
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @tms_bootstrap.post("/roles/custom")
    async def tms_custom_role_publish(
        request: Request, command: TmsCustomRolePublishRequest
    ):
        """发布当前学校自定义角色版本；不创建外部用户或跨校/OMS 权限。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..management.roles import (
            CustomRoleConflict,
            PublishCustomRoleCommand,
            publish_custom_role,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-custom-role-publish")
            ) as c:
                result = await publish_custom_role(
                    c,
                    identity,
                    PublishCustomRoleCommand(
                        role_key=command.role_key,
                        scope_kind="school",
                        target_school_id=identity.school_id,
                        action_keys=tuple(command.action_keys),
                        expected_version=command.expected_version,
                        command_id=command.command_id,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except CustomRoleConflict:
            return JSONResponse({"detail": "Role conflict"}, status_code=409, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse({"detail": "Role unavailable"}, status_code=503, headers=headers)
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "role_key": result.role_key,
                "version": result.version,
                "scope_kind": result.scope_kind,
                "action_keys": list(result.action_keys),
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @tms_bootstrap.post("/assignments/{assignment_id}/revoke")
    async def tms_assignment_revoke(
        request: Request, assignment_id: UUID, command: TmsAssignmentRevokeRequest
    ):
        """撤销当前学校角色 assignment；不修改 EduPlus2 用户或 OMS 服务授权。"""

        from ..management.authorization import ManagementAuthorizationDenied
        from ..management.grants import (
            ManagementGrantConflict,
            RevokeRoleCommand,
            revoke_management_role,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-assignment-revoke")
            ) as c:
                result = await revoke_management_role(
                    c,
                    identity,
                    RevokeRoleCommand(
                        assignment_id=assignment_id,
                        target_school_id=identity.school_id,
                        expected_assignment_version=command.expected_assignment_version,
                        expected_target_policy_version=command.expected_target_policy_version,
                        command_id=command.command_id,
                        reason=command.reason,
                        request_id=_request_id(request),
                    ),
                )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ManagementGrantConflict:
            return JSONResponse(
                {"detail": "Assignment conflict"}, status_code=409, headers=headers
            )
        except (RuntimeError, TimeoutError, psycopg.Error):
            logging.getLogger(__name__).exception("tms assignment revoke failed")
            return JSONResponse(
                {"detail": "Assignment unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "application": "tms",
                "school_id": str(identity.school_id),
                "assignment_id": str(result.assignment_id),
                "assignment_version": result.assignment_version,
                "target_policy_version": result.target_policy_version,
                "status": "revoked",
                "replayed": result.replayed,
            },
            headers=headers,
        )

    @tms_bootstrap.get("/quotas")
    async def tms_quota_summary(request: Request):
        """TMS 当前学校配额只读安全视图；不暴露供给、成本或 Secret 关联字段。"""

        def _tms_usage_filter():
            clauses = []
            params = []
            for column, key in (
                ("service_id", "service_id"),
                ("unit_code", "unit_code"),
                ("status", "status"),
                ("subject_id", "subject_id"),
            ):
                text = request.query_params.get(key, "").strip()
                if not text:
                    continue
                if len(text) > 255:
                    raise ValueError("usage filter is too long")
                clauses.append(f"{column}=%s")
                params.append(text)
            return (" AND " + " AND ".join(clauses) if clauses else ""), tuple(params)

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            extra_usage_filter, extra_usage_params = _tms_usage_filter()
            usage_limit = min(max(int(request.query_params.get("limit", "50")), 1), 200)
            usage_offset = min(max(int(request.query_params.get("offset", "0")), 0), 10_000)
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
                usage_details = await (
                    await c.execute(
                        "SELECT attempt_id,operation_id,service_id,unit_code,subject_kind,"
                        "subject_id,user_id,app_id,status,reserved_units,settled_units,"
                        "started_at,updated_at "
                        "FROM oms.usage_attempts WHERE tenant_id=%s "
                        + extra_usage_filter
                        + " ORDER BY started_at DESC,attempt_id LIMIT %s OFFSET %s",
                        (identity.school_id, *extra_usage_params, usage_limit, usage_offset),
                    )
                ).fetchall()
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422, headers=headers)
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
                "usage_page": {
                    "limit": usage_limit,
                    "offset": usage_offset,
                    "count": len(usage_details),
                },
                "usage_details": [
                    {
                        "attempt_id": str(row["attempt_id"]),
                        "operation_id": str(row["operation_id"]),
                        "service_id": row["service_id"],
                        "unit_code": row["unit_code"],
                        "subject_kind": row["subject_kind"],
                        "subject_id": row["subject_id"],
                        "user_id": row["user_id"],
                        "app_id": row["app_id"],
                        "status": row["status"],
                        "reserved_units": _decimal_text(row["reserved_units"]),
                        "settled_units": _decimal_text(row["settled_units"]),
                        "started_at": row["started_at"].isoformat(),
                        "updated_at": row["updated_at"].isoformat(),
                    }
                    for row in usage_details
                ],
            },
            headers=headers,
        )

    @tms_bootstrap.get("/service-access")
    async def tms_service_access_list(request: Request):
        """当前学校服务访问资格列表；不返回额度、成本、Provider 或跨学校字段。"""

        from ..management.authorization import (
            ManagementAuthorizationDenied,
            require_management_permission,
        )
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            filters = []
            params: list[object] = [identity.school_id]
            for column, key in (
                ("service_id", "service_id"),
                ("subject_kind", "subject_kind"),
                ("subject_id", "subject_id"),
                ("status", "status"),
            ):
                value = request.query_params.get(key, "").strip()
                if not value:
                    continue
                if len(value) > 255:
                    raise ValueError("service access filter is too long")
                filters.append(f"{column}=%s")
                params.append(value)
            limit = min(max(int(request.query_params.get("limit", "50")), 1), 200)
            offset = min(max(int(request.query_params.get("offset", "0")), 0), 10_000)
            async with enterprise.db.transaction(
                TenantScope(str(identity.school_id), "@tms-service-access-list")
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
                    "tenant.access.manage",
                    target_school_id=identity.school_id,
                    write=False,
                )
                where = " AND " + " AND ".join(filters) if filters else ""
                rows = await (
                    await c.execute(
                        "SELECT id,service_id,subject_kind,subject_id,entitlement_version,"
                        "starts_at,expires_at,status,sync_status,version,revoked_at,"
                        "created_at,updated_at "
                        "FROM oms.tenant_service_access_grants WHERE tenant_id=%s "
                        + where
                        + " ORDER BY updated_at DESC,id LIMIT %s OFFSET %s",
                        (*params, limit, offset),
                    )
                ).fetchall()
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except (TmsSchoolDenied, ManagementAuthorizationDenied):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ValueError:
            return JSONResponse({"detail": "Invalid request"}, status_code=422, headers=headers)
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Service access unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "school_id": str(identity.school_id),
                "page": {"limit": limit, "offset": offset, "count": len(rows)},
                "service_access_grants": [
                    {
                        "grant_id": str(row["id"]),
                        "service_id": row["service_id"],
                        "subject_kind": row["subject_kind"],
                        "subject_id": row["subject_id"],
                        "entitlement_version": row["entitlement_version"],
                        "starts_at": row["starts_at"].isoformat(),
                        "expires_at": row["expires_at"].isoformat(),
                        "status": row["status"],
                        "sync_status": row["sync_status"],
                        "version": row["version"],
                        "revoked_at": ""
                        if row["revoked_at"] is None
                        else row["revoked_at"].isoformat(),
                        "created_at": row["created_at"].isoformat(),
                        "updated_at": row["updated_at"].isoformat(),
                    }
                    for row in rows
                ],
            },
            headers=headers,
        )

    @tms_bootstrap.post("/service-access")
    async def tms_service_access_grant(
        request: Request, command: TmsServiceAccessGrantCommandRequest
    ):
        """授予当前学校成员/应用/服务主体访问资格；不创建配额或 usage。"""

        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied
        from ..oms.service_access import (
            ServiceAccessGrantRequest,
            ServiceAccessLedger,
            ServiceAccessRejected,
        )

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            result = await ServiceAccessLedger(enterprise.db).grant(
                TenantScope(str(identity.school_id), identity.subject),
                identity,
                ServiceAccessGrantRequest(
                    grant_id=command.grant_id,
                    service_id=command.service_id,
                    subject_kind=command.subject_kind,
                    subject_id=command.subject_id,
                    starts_at=command.starts_at,
                    expires_at=command.expires_at,
                    expected_entitlement_version=command.expected_entitlement_version,
                    reason=command.reason,
                ),
            )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except TmsSchoolDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ServiceAccessRejected as exc:
            status_code = 403 if str(exc) == "Permission denied" else 409
            return JSONResponse(
                {"detail": "Service access conflict"}, status_code=status_code, headers=headers
            )
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Service access unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "grant_id": str(result.grant_id),
                "service_id": result.service_id,
                "subject_kind": result.subject_kind,
                "subject_id": result.subject_id,
                "status": result.status,
                "sync_status": result.sync_status,
                "version": result.version,
            },
            headers=headers,
        )

    @tms_bootstrap.post("/service-access/{grant_id}/revoke")
    async def tms_service_access_revoke(
        request: Request, grant_id: UUID, command: TmsServiceAccessRevokeCommandRequest
    ):
        from ..management.tms_identity import TmsAuthenticationDenied, TmsSchoolDenied
        from ..oms.service_access import (
            ServiceAccessLedger,
            ServiceAccessRejected,
            ServiceAccessRevokeRequest,
        )

        headers = {"Cache-Control": "no-store"}
        try:
            identity = await _tms_bootstrap_identity(request)
            result = await ServiceAccessLedger(enterprise.db).revoke(
                TenantScope(str(identity.school_id), identity.subject),
                identity,
                ServiceAccessRevokeRequest(
                    grant_id=grant_id,
                    expected_version=command.expected_version,
                    reason=command.reason,
                ),
            )
        except TmsAuthenticationDenied:
            return JSONResponse(
                {"detail": "Authentication required"}, status_code=401, headers=headers
            )
        except TmsSchoolDenied:
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers=headers)
        except ServiceAccessRejected as exc:
            status_code = 403 if str(exc) == "Permission denied" else 409
            return JSONResponse(
                {"detail": "Service access conflict"}, status_code=status_code, headers=headers
            )
        except (RuntimeError, TimeoutError, psycopg.Error):
            return JSONResponse(
                {"detail": "Service access unavailable"}, status_code=503, headers=headers
            )
        return JSONResponse(
            {
                "grant_id": str(result.grant_id),
                "service_id": result.service_id,
                "subject_kind": result.subject_kind,
                "subject_id": result.subject_id,
                "status": result.status,
                "sync_status": result.sync_status,
                "version": result.version,
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
