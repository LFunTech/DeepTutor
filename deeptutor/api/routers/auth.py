"""默认 PG 身份入口，保留原 DTO/路由；无 JSON/PocketBase/无认证管理员。"""

import asyncio
from contextlib import asynccontextmanager
import re

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
)
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from starlette.requests import HTTPConnection

from deeptutor.multi_user.context import set_current_user, user_from_token_payload
from deeptutor.multi_user.models import AccountPreset
from deeptutor.services.auth import TokenPayload

router = APIRouter()
_COOKIE_NAME = "dt_token"
_AVATAR_MAX_BYTES = 1024 * 1024
_AVATAR_MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def _provider(connection: HTTPConnection):
    provider = getattr(connection.app.state, "auth_provider", None)
    if provider is None:
        from deeptutor.core.providers import get_providers

        provider = getattr(get_providers(), "auth", None)
    if provider is None:
        raise HTTPException(503, "PostgreSQL authentication provider is not configured")
    return provider


def _cookie_attrs(provider):
    return {
        "key": _COOKIE_NAME,
        "httponly": True,
        "samesite": "none" if provider.cookie_secure else "lax",
        "secure": provider.cookie_secure,
        "path": "/",
    }


@asynccontextmanager
async def _errors():
    try:
        yield
    except HTTPException:
        raise
    except PermissionError:
        raise HTTPException(403, "Permission denied") from None
    except LookupError:
        raise HTTPException(404, "User or resource not found") from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    except Exception:
        raise HTTPException(503, "Account service unavailable") from None


class LoginRequest(BaseModel):
    """Payload for the POST /login endpoint."""

    username: str
    password: str


class DeviceLoginRequest(BaseModel):
    """Payload for the built-in device-credential login endpoint."""

    pairing_code: str = Field(min_length=8, max_length=128)
    pin: str = Field(min_length=6, max_length=6)


class DeviceCredentialCreateRequest(BaseModel):
    """Admin payload for issuing a local ordinary-user device credential."""

    user_id: str = Field(min_length=1, max_length=64)
    device_name: str = Field(min_length=1, max_length=80)
    expires_in_days: int = Field(ge=1, le=365)
    daily_limit_minutes: int = Field(ge=5, le=1440)


class RegisterRequest(BaseModel):
    """Payload for the POST /register endpoint."""

    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        import re

        v = v.strip()
        if not v:
            raise ValueError("Email cannot be empty")
        # 保留 email/普通用户名输入兼容；两种形式都由同一 PG 身份权威处理。
        email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        plain_re = re.compile(r"^[A-Za-z0-9_\-.]{3,64}$")
        if not email_re.match(v) and not plain_re.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        if not 12 <= len(v.encode("utf-8")) <= 72:
            raise ValueError("Password must contain 12 to 72 UTF-8 bytes")
        return v


class SetRoleRequest(BaseModel):
    """Payload for the PUT /users/{username}/role endpoint."""

    role: str

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        if v not in ("admin", "tenant_admin", "user"):
            raise ValueError("Role must be 'admin' or 'user'")
        return "tenant_admin" if v == "admin" else v


class AdminCreateUserRequest(RegisterRequest):
    """Admin user-creation payload.

    A preset configures an ordinary account; it never becomes a third role.
    """

    preset: AccountPreset = "standard"


class AuthStatusResponse(BaseModel):
    """Response body for the GET /status endpoint."""

    enabled: bool
    authenticated: bool
    user_id: str | None = None
    username: str | None = None
    role: str | None = None
    is_admin: bool = False
    avatar: str = ""
    preset: AccountPreset | None = None
    learning_policy: dict | None = None


class UserInfo(BaseModel):
    """Single user record returned by the GET /users and /profile endpoints."""

    id: str = ""
    username: str
    role: str
    created_at: str
    disabled: bool = False
    avatar: str = ""
    preset: AccountPreset = "standard"


class LearnerProfileRequest(BaseModel):
    age: int | None = Field(default=None, ge=3, le=120)
    grade_level: str | None = Field(default=None, max_length=80)
    curriculum: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=80)
    reading_level: str | None = Field(default=None, max_length=80)
    explanation_style: str | None = Field(default=None, max_length=80)

    @field_validator("grade_level", "curriculum", "language", "reading_level", "explanation_style")
    @classmethod
    def profile_text_valid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        from deeptutor.multi_user.learner_profile import normalize_profile

        normalize_profile({"language": value})
        return value.strip()


# Markers settable through PUT /profile. Image markers ("img:<version>") are
# managed exclusively by the upload endpoint so users cannot point their
# avatar at a file that was never validated.
_ICON_MARKER_RE = re.compile(r"^icon:[a-z0-9-]{1,32}:[a-z0-9-]{1,32}$")

# User ids are generated as "u_<uuid hex>" (plus the "local-admin" /
# "env-admin" sentinels); reject anything else before it reaches the
# filesystem layer.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class UpdateProfileRequest(BaseModel):
    """Payload for the PUT /profile endpoint."""

    avatar: str

    @field_validator("avatar")
    @classmethod
    def avatar_valid(cls, v: str) -> str:
        v = v.strip()
        if v and not _ICON_MARKER_RE.match(v):
            raise ValueError("Avatar must be empty or 'icon:<name>:<color>'")
        return v


def _bearer_token_from_header(authorization: str | None) -> str | None:
    """Parse ``Authorization: Bearer <token>`` without using ``HTTPBearer``.

    ``HTTPBearer`` is a class-based dependency whose ``__call__`` is annotated
    ``request: Request``. FastAPI doesn't inject a Request into WebSocket
    dependency resolution, which makes ``HTTPBearer`` raise ``TypeError`` the
    moment a router with this dep mounts a WS endpoint. Doing the parse by
    hand keeps ``require_auth`` HTTP/WS-symmetric.
    """
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1].strip()
        return token or None
    return None


def _extract_token(authorization: str | None, dt_token: str | None) -> str | None:
    return _bearer_token_from_header(authorization) or dt_token


def _install_current_user(payload):
    return set_current_user(user_from_token_payload(payload))


async def require_auth(
    connection: HTTPConnection,
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
) -> TokenPayload:
    token = _extract_token(authorization, dt_token)
    if not token:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    provider = _provider(connection)
    try:
        payload = await provider.decode(token)
    except PermissionError:
        raise HTTPException(
            401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
        ) from None
    except Exception:
        raise HTTPException(503, "Account service unavailable") from None
    _install_current_user(payload)
    return payload


class _WsAuthFailed:
    pass


ws_auth_failed = _WsAuthFailed()


async def ws_require_auth(ws: WebSocket):
    try:
        return await _provider(ws).authenticate(ws)
    except (PermissionError, HTTPException):
        await ws.close(code=4001)
        return ws_auth_failed


async def require_admin(payload: TokenPayload = Depends(require_auth)):
    if payload.role != "tenant_admin":
        raise HTTPException(403, "Tenant account management required")
    return payload


def _learning_surface_for_path(path: str) -> str:
    normalized = "/" + str(path or "").lstrip("/")
    for root, surface in (
        ("/api/reading", "reading"),
        ("/api/courses", "reading"),
        ("/api/chat", "chat"),
        ("/api/question", "chat"),
        ("/api/question-notebook", "chat"),
        ("/api/sessions", "chat"),
    ):
        if normalized == root or normalized.startswith(f"{root}/"):
            return surface
    return ""


async def require_learning_surface(request: Request, payload: TokenPayload = Depends(require_auth)):
    policy = payload.learning_policy
    if policy is not None and _learning_surface_for_path(request.url.path) not in set(
        policy.get("allowed_surfaces") or ["chat", "reading"]
    ):
        raise HTTPException(403, "This learning account cannot use the requested server surface.")


@router.get("/openai-codex/callback")
async def receive_codex_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    headers = {"Cache-Control": "no-store"}
    from deeptutor.services.codex_auth.contracts import CodexAuthError
    from deeptutor.services.codex_auth.service import deliver_codex_oauth_callback

    try:
        callback_state = state if len(request.query_params.getlist("state")) == 1 else None
        await deliver_codex_oauth_callback(code, callback_state, error)
    except CodexAuthError as exc:
        return HTMLResponse(
            (
                "<!doctype html><title>DeepTutor Codex</title>"
                "<p>Authentication could not be received. Return to DeepTutor and try again.</p>"
            ),
            status_code=exc.http_status,
            headers=headers,
        )
    return HTMLResponse(
        (
            "<!doctype html><title>DeepTutor Codex</title>"
            "<p>Authentication received. You can return to DeepTutor.</p>"
        ),
        headers=headers,
    )


def _sniff_image(data: bytes) -> str | None:
    """Detect a supported raster image format from its magic bytes.

    The uploaded filename and Content-Type are attacker-controlled, so the
    stored extension (and the media type served back) is derived from the
    bytes alone. SVG is deliberately unsupported — serving user-supplied SVG
    is a stored-XSS vector.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(
    connection: HTTPConnection,
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None),
):
    token = _extract_token(authorization, dt_token)
    provider = _provider(connection)
    if not token:
        return AuthStatusResponse(enabled=True, authenticated=False)
    try:
        payload = await provider.decode(token)
        info = await provider.identity.profile(token)
    except PermissionError:
        return AuthStatusResponse(enabled=True, authenticated=False)
    except Exception:
        raise HTTPException(503, "Account service unavailable") from None
    return AuthStatusResponse(
        enabled=True,
        authenticated=True,
        user_id=payload.user_id,
        username=payload.username,
        role=payload.role,
        is_admin=payload.role == "tenant_admin",
        avatar=info["avatar"],
        preset=info["preset"],
        learning_policy=payload.learning_policy,
    )


async def _logged_in(provider, token, response):
    actor = await provider.decode(token)
    response.set_cookie(
        value=token, max_age=provider.identity.token_seconds, **_cookie_attrs(provider)
    )
    return {
        "ok": True,
        "user_id": actor.user_id,
        "username": actor.username,
        "role": actor.role,
        "is_admin": actor.role == "tenant_admin",
    }


@router.post("/login")
async def login(body: LoginRequest, response: Response, request: Request):
    provider = _provider(request)
    from deeptutor.persistence.postgres.identity.service import LoginRateLimited

    try:
        token = await provider.identity.login(
            body.username,
            body.password,
            client=request.client.host if request.client else "unknown",
        )
        return await _logged_in(provider, token, response)
    except LoginRateLimited:
        raise HTTPException(429, "Authentication temporarily limited") from None
    except PermissionError:
        raise HTTPException(401, "Incorrect username or password") from None
    except Exception:
        raise HTTPException(503, "Account service unavailable") from None


@router.post("/logout")
async def logout(
    response: Response,
    connection: HTTPConnection,
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None),
):
    provider = _provider(connection)
    token = _extract_token(authorization, dt_token)
    if token:
        try:
            await provider.identity.logout(token)
        except PermissionError:
            pass  # 已撤销/无效 token 的退出幂等；数据库故障不伪报成功。
        except Exception:
            raise HTTPException(503, "Account service unavailable") from None
    response.delete_cookie(**_cookie_attrs(provider))
    return {"ok": True}


@router.post("/register", status_code=201)
async def register(body: RegisterRequest):
    raise HTTPException(403, "Public registration is disabled; use controlled account provisioning")


@router.get("/is_first_user")
async def check_is_first_user():
    return {"is_first_user": False}


@router.get("/profile", response_model=UserInfo)
async def get_profile(current: TokenPayload = Depends(require_auth)):
    async with _errors():
        return UserInfo(**await current.provider.identity.profile(current.token))


async def _replace_avatar(current, marker, object_id=""):
    provider = current.provider
    try:
        result = await provider.identity.set_avatar(current.token, marker, object_id)
        previous, marker = result["previous"], result["marker"]
    except (PermissionError, LookupError, ValueError):
        # 仅已知拒绝可立即删候选对象；提交/取消结果不确定时保留，不能破坏已提交引用。
        if object_id:
            await asyncio.to_thread(
                provider.resources.delete_avatar, current.tenant_id, current.user_id, object_id
            )
        raise
    if previous and previous != object_id:
        await asyncio.to_thread(
            provider.resources.delete_avatar, current.tenant_id, current.user_id, previous
        )
    return {"ok": True, "avatar": marker}


@router.put("/profile")
async def update_profile(body: UpdateProfileRequest, current: TokenPayload = Depends(require_auth)):
    async with _errors():
        return await _replace_avatar(current, body.avatar)


@router.put("/profile/avatar")
async def upload_avatar(
    file: UploadFile = File(...), current: TokenPayload = Depends(require_auth)
):
    data = await file.read(_AVATAR_MAX_BYTES + 1)
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(413, "Avatar image is too large (max 1 MB).")
    extension = _sniff_image(data)
    if extension is None:
        raise HTTPException(415, "Avatar must be a PNG, JPEG or WebP image.")
    async with _errors():
        object_id = await asyncio.to_thread(
            current.provider.resources.write_avatar,
            current.tenant_id,
            current.user_id,
            data,
            extension,
        )
        # 数字版本在 PG 行锁内递增；对象名保持不可变。
        marker = "img:1"
        return await _replace_avatar(current, marker, object_id)


@router.delete("/profile/avatar")
async def remove_avatar(current: TokenPayload = Depends(require_auth)):
    async with _errors():
        return await _replace_avatar(current, "")


@router.get("/avatar/{user_id}")
async def get_avatar_image(user_id: str, current: TokenPayload = Depends(require_auth)):
    async with _errors():
        record = await current.provider.identity.avatar_record(current.token, user_id)
        if not record["avatar_object"]:
            raise HTTPException(404, "Avatar not found")
        try:
            data = await asyncio.to_thread(
                current.provider.resources.read_avatar,
                current.tenant_id,
                user_id,
                record["avatar_object"],
            )
        except FileNotFoundError:
            raise HTTPException(404, "Avatar not found") from None
        return Response(
            data,
            media_type=_AVATAR_MEDIA_TYPES[record["avatar_object"].split(".")[-1]],
            headers={
                "Cache-Control": "private, max-age=86400",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "inline",
            },
        )


@router.get("/users", response_model=list[UserInfo])
async def get_users(current: TokenPayload = Depends(require_admin)):
    async with _errors():
        return [
            UserInfo(**row) for row in await current.provider.identity.list_users(current.token)
        ]


@router.post("/users", status_code=201)
async def admin_create_user(
    body: AdminCreateUserRequest, current: TokenPayload = Depends(require_admin)
):
    async with _errors():
        try:
            user = await current.provider.identity.create_user(
                current.token, body.username, body.password, preset=body.preset
            )
        except ValueError:
            raise HTTPException(409, "Username already taken") from None
        return {
            "ok": True,
            "user_id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "is_admin": False,
            "preset": body.preset,
        }


@router.delete("/users/{username}")
async def remove_user(username: str, current: TokenPayload = Depends(require_admin)):
    async with _errors():
        old = await current.provider.identity.delete_user(current.token, username)
        if old["avatar_object"]:
            await asyncio.to_thread(
                current.provider.resources.delete_avatar,
                current.tenant_id,
                old["id"],
                old["avatar_object"],
            )
        return {"ok": True}


@router.put("/users/{username}/role")
async def update_user_role(
    username: str, body: SetRoleRequest, current: TokenPayload = Depends(require_admin)
):
    async with _errors():
        await current.provider.identity.set_role(current.token, username, body.role)
        return {"ok": True, "username": username, "role": body.role}


async def _learner(current, username=None):
    row = await current.provider.identity.profile(current.token, username=username)
    if row["role"] != "user" or row["preset"] != "learner":
        raise HTTPException(404 if username else 403, "Learner profile required")
    return {"learner_profile": row["learner_profile"]}


@router.get("/profile/learner-profile")
async def get_current_learner_profile(current: TokenPayload = Depends(require_auth)):
    async with _errors():
        return await _learner(current)


@router.put("/profile/learner-profile")
async def put_current_learner_profile(
    body: LearnerProfileRequest, current: TokenPayload = Depends(require_auth)
):
    async with _errors():
        await _learner(current)
        return {
            "learner_profile": await current.provider.identity.update_learner_profile(
                current.token, body.model_dump(exclude_none=True)
            )
        }


@router.get("/users/{username}/learner-profile")
async def get_learner_profile(username: str, current: TokenPayload = Depends(require_admin)):
    async with _errors():
        return await _learner(current, username)


@router.put("/users/{username}/learner-profile")
async def put_learner_profile(
    username: str, body: LearnerProfileRequest, current: TokenPayload = Depends(require_admin)
):
    async with _errors():
        await _learner(current, username)
        return {
            "learner_profile": await current.provider.identity.update_learner_profile(
                current.token, body.model_dump(exclude_none=True), username=username
            )
        }


@router.post("/device-login")
async def device_login(body: DeviceLoginRequest, response: Response, request: Request):
    provider = _provider(request)
    from deeptutor.persistence.postgres.identity.service import LoginRateLimited

    try:
        token = await provider.identity.device_login(
            body.pairing_code, body.pin, client=request.client.host if request.client else "unknown"
        )
        result = await _logged_in(provider, token, response)
        actor = await provider.decode(token)
        return {**result, "device_credential_id": actor.device_credential_id}
    except LoginRateLimited:
        raise HTTPException(429, "Authentication temporarily limited") from None
    except PermissionError:
        raise HTTPException(401, "Invalid device credentials") from None
    except Exception:
        raise HTTPException(503, "Account service unavailable") from None


@router.post("/device/heartbeat")
async def device_heartbeat(current: TokenPayload = Depends(require_auth)):
    async with _errors():
        device = await current.provider.identity.device_heartbeat(current.token)
        if device is None:
            raise HTTPException(400, "This session does not use a device credential.")
        return {"ok": not device.pop("limit_reached"), **device}


@router.get("/devices")
async def list_devices(
    user_id: str | None = None,
    include_revoked: bool = False,
    current: TokenPayload = Depends(require_admin),
):
    async with _errors():
        return {
            "devices": await current.provider.identity.list_devices(
                current.token, user_id=user_id, include_revoked=include_revoked
            )
        }


@router.post("/devices", status_code=201)
async def issue_device(
    body: DeviceCredentialCreateRequest, current: TokenPayload = Depends(require_admin)
):
    async with _errors():
        device, code, pin = await current.provider.identity.issue_device(
            current.token,
            body.user_id,
            body.device_name,
            body.expires_in_days,
            body.daily_limit_minutes,
        )
        return {"device": device, "pairing_code": code, "pin": pin}


@router.delete("/devices/{device_credential_id}")
async def revoke_device(device_credential_id: str, current: TokenPayload = Depends(require_admin)):
    async with _errors():
        return {
            "ok": True,
            "device": await current.provider.identity.revoke_device(
                current.token, device_credential_id
            ),
        }
