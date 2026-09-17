"""固定租户 PG 认证与受控账号维护；不读取本地身份或保存明文 token。"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import time
import uuid

import bcrypt
from jose import JWTError, jwt
from psycopg.types.json import Jsonb

from ..scope import TenantScope
from .accounts import AccountOperations, initial_policy


class LoginRateLimited(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class Identity:
    tenant_id: str
    user_id: str
    username: str
    role: str
    session_id: str
    auth_version: int
    device_credential_id: str = ""


class IdentityService(AccountOperations):
    def __init__(
        self,
        db,
        *,
        tenant_id,
        signing_key,
        auth_epoch,
        bootstrap_secret,
        issuer="deeptutor-enterprise",
        audience="deeptutor",
        token_seconds=3600,
    ):
        self.db = db
        self.tenant_id = str(uuid.UUID(tenant_id))
        if (
            len(signing_key) < 32
            or (bootstrap_secret is not None and len(bootstrap_secret) < 32)
            or not auth_epoch
        ):
            raise ValueError("missing or weak identity Secret")
        self._key = signing_key
        self._bootstrap = bootstrap_secret
        self.epoch = auth_epoch
        self.issuer, self.audience = issuer, audience
        if not 60 <= token_seconds <= 86400:
            raise ValueError("invalid token lifetime")
        self.token_seconds = token_seconds
        self._attempts = {}
        self._dummy_hash = None
        self._scope = TenantScope(self.tenant_id, "@identity")

    @staticmethod
    async def _hash(password):
        if not isinstance(password, str) or not 12 <= len(password.encode()) <= 72:
            raise ValueError("password must contain 12 to 72 UTF-8 bytes")
        return (
            await asyncio.to_thread(bcrypt.hashpw, password.encode(), bcrypt.gensalt(rounds=12))
        ).decode()

    @staticmethod
    def _username(username):
        if (
            not isinstance(username, str)
            or not username.strip()
            or len(username) > 128
            or any(ord(c) < 32 for c in username)
        ):
            raise ValueError("invalid username")
        return username.strip()

    async def _audit(self, c, actor, action, target, result):
        await c.execute(
            "INSERT INTO enterprise.audit(tenant_id,actor_id,action,target_id,request_id,result) VALUES(%s,%s,%s,%s,%s,%s)",
            (self.tenant_id, actor, action, target, str(uuid.uuid4()), result),
        )

    async def _denied(self, action, actor="anonymous", target=""):
        async with self.db.transaction(self._scope) as c:
            await self._audit(c, actor, action, target, "denied")

    async def record_denial(self, action, actor="anonymous"):
        await self._denied(action, actor)

    async def bootstrap(self, username, password, *, secret):
        try:
            return await self._bootstrap_user(username, password, secret=secret)
        except ValueError:
            await self._denied("bootstrap_conflict", "@bootstrap")
            raise

    async def _bootstrap_user(self, username, password, *, secret):
        if not self._bootstrap or not hmac.compare_digest(str(secret), self._bootstrap):
            await self._denied("bootstrap")
            raise PermissionError("bootstrap authentication failed")
        username = self._username(username)
        hashed = await self._hash(password)
        async with self.db.transaction(self._scope) as c:
            await c.execute(
                """INSERT INTO enterprise.tenants(id,external_eligibility,local_enabled,provisioning_status,auth_epoch)
                VALUES(%s,'not_required',true,'ready',%s) ON CONFLICT DO NOTHING""",
                (self.tenant_id, self.epoch),
            )
            tenant = await (
                await c.execute(
                    "SELECT * FROM enterprise.tenants WHERE id=%s FOR UPDATE", (self.tenant_id,)
                )
            ).fetchone()
            if tenant["bootstrap_completed"]:
                existing = await (
                    await c.execute(
                        "SELECT id,username,role FROM enterprise.users WHERE tenant_id=%s AND username=%s AND role='tenant_admin'",
                        (self.tenant_id, username),
                    )
                ).fetchone()
                if not existing:
                    raise ValueError("bootstrap already completed; identity conflict")
                await self._audit(c, "@bootstrap", "bootstrap", existing["id"], "replayed")
                return existing
            if await (
                await c.execute(
                    "SELECT 1 FROM enterprise.users WHERE tenant_id=%s LIMIT 1", (self.tenant_id,)
                )
            ).fetchone():
                raise ValueError("bootstrap refuses to promote an existing identity")
            user_id = str(uuid.uuid4())
            await c.execute(
                "INSERT INTO enterprise.users(tenant_id,id,username,role) VALUES(%s,%s,%s,'tenant_admin')",
                (self.tenant_id, user_id, username),
            )
            await c.execute(
                "INSERT INTO enterprise.local_credentials VALUES(%s,%s,%s)",
                (self.tenant_id, user_id, hashed),
            )
            await c.execute(
                "UPDATE enterprise.tenants SET bootstrap_completed=true WHERE id=%s",
                (self.tenant_id,),
            )
            await self._audit(c, "@bootstrap", "bootstrap", user_id, "success")
            return {"id": user_id, "username": username, "role": "tenant_admin"}

    def _limit(self, client):
        now = time.monotonic()
        # 单执行者内有界限流；不使用可伪造的 X-Forwarded-For。
        self._attempts = {k: v for k, v in self._attempts.items() if v[1] > now}
        key = hashlib.sha256(str(client).encode()).hexdigest()
        count, end = self._attempts.get(key, (0, now + 60))
        if count >= 8 or (key not in self._attempts and len(self._attempts) >= 10000):
            raise LoginRateLimited("authentication temporarily limited")
        self._attempts[key] = (count + 1, end)

    async def login(self, username, password, *, client):
        try:
            self._limit(client)
        except LoginRateLimited:
            await self._denied("login_limited")
            raise
        # 缺账号也执行相同 bcrypt；不要把账号名写到错误响应或审计目标。
        if self._dummy_hash is None:
            self._dummy_hash = await self._hash(secrets.token_hex(24))
        async with self.db.transaction(self._scope) as c:
            row = await (
                await c.execute(
                    """SELECT u.*,lc.password_hash,t.local_enabled,t.external_eligibility,
                t.provisioning_status,t.auth_epoch FROM enterprise.users u
                JOIN enterprise.tenants t ON t.id=u.tenant_id
                JOIN enterprise.local_credentials lc ON (lc.tenant_id,lc.user_id)=(u.tenant_id,u.id)
                WHERE u.tenant_id=%s AND u.username=%s FOR UPDATE OF u,t,lc""",
                    (self.tenant_id, str(username)),
                )
            ).fetchone()
            raw = password.encode() if isinstance(password, str) else b""
            valid_length = 0 < len(raw) <= 72
            valid = await asyncio.to_thread(
                bcrypt.checkpw,
                raw if valid_length else b"invalid",
                (row["password_hash"] if row else self._dummy_hash).encode(),
            )
            allowed = bool(
                valid_length
                and valid
                and row
                and not row["disabled"]
                and row["deleted_at"] is None
                and row["local_enabled"]
                and row["external_eligibility"] in ("not_required", "allowed")
                and row["provisioning_status"] == "ready"
                and row["auth_epoch"] == self.epoch
            )
            if allowed:
                token = await self._issue_session(c, row)
                sid = self._claims(token)["sid"]
                await self._audit(c, row["id"], "login", sid, "success")
            else:
                await self._audit(c, "anonymous", "login", "", "denied")
        if not allowed:
            raise PermissionError("invalid credentials")
        return token

    async def _issue_session(
        self,
        c,
        row,
        *,
        device_id=None,
        device_generation=None,
        extra_claims=None,
        token_seconds=None,
    ):
        sid = str(uuid.uuid4())
        now = int(time.time())
        lifetime = self.token_seconds if token_seconds is None else int(token_seconds)
        if not 60 <= lifetime <= self.token_seconds:
            raise ValueError("invalid session token lifetime")
        claims = {
            "tid": self.tenant_id,
            "sub": row["id"],
            "sid": sid,
            "ver": row["auth_version"],
            "epoch": self.epoch,
            "iss": self.issuer,
            "aud": self.audience,
            "iat": now,
            "exp": now + lifetime,
        }
        if extra_claims:
            if any(key in claims for key in extra_claims):
                raise ValueError("extra claims must not override identity claims")
            claims.update(extra_claims)
        token = jwt.encode(claims, self._key, algorithm="HS256")
        await c.execute(
            "INSERT INTO enterprise.auth_sessions(tenant_id,user_id,id,auth_version,auth_epoch,expires_at,device_credential_id,device_generation) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.tenant_id,
                row["id"],
                sid,
                row["auth_version"],
                self.epoch,
                datetime.fromtimestamp(claims["exp"], timezone.utc),
                device_id,
                device_generation,
            ),
        )
        return token

    def _claims(self, token):
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={
                    "require_exp": True,
                    "require_iat": True,
                    "require_sub": True,
                    "require_aud": True,
                    "require_iss": True,
                },
            )
            if (
                claims.get("tid") != self.tenant_id
                or claims.get("epoch") != self.epoch
                or not isinstance(claims.get("ver"), int)
                or claims["iat"] > int(time.time()) + 5
            ):
                raise ValueError
            uuid.UUID(claims["sid"])
            return claims
        except (JWTError, ValueError, KeyError, TypeError):
            raise PermissionError("authentication required") from None

    async def _authenticate(self, c, token, *, lock=False):
        claims = self._claims(token)
        row = await (
            await c.execute(
                """SELECT u.id,u.username,u.role,u.auth_version,s.id AS session_id,s.device_credential_id
            FROM enterprise.auth_sessions s JOIN enterprise.users u ON (u.tenant_id,u.id)=(s.tenant_id,s.user_id)
            JOIN enterprise.tenants t ON t.id=u.tenant_id
            WHERE s.tenant_id=%s AND s.id=%s AND s.user_id=%s AND s.revoked_at IS NULL AND s.expires_at>now()
            AND NOT u.disabled AND u.deleted_at IS NULL AND t.local_enabled AND t.external_eligibility IN ('not_required','allowed') AND t.provisioning_status='ready'
            AND t.auth_epoch=%s AND s.auth_epoch=%s AND s.auth_version=u.auth_version AND u.auth_version=%s
            """
                + (" FOR UPDATE OF u,s,t" if lock else ""),
                (
                    self.tenant_id,
                    claims["sid"],
                    claims["sub"],
                    self.epoch,
                    self.epoch,
                    claims["ver"],
                ),
            )
        ).fetchone()
        if not row:
            raise PermissionError("authentication required")
        await self._validate_device_session(c, str(row["session_id"]))
        return Identity(
            self.tenant_id,
            row["id"],
            row["username"],
            row["role"],
            str(row["session_id"]),
            row["auth_version"],
            row["device_credential_id"] or "",
        )

    async def authenticate(self, token):
        try:
            async with self.db.transaction(self._scope) as c:
                return await self._authenticate(c, token)
        except PermissionError:
            await self._denied("authenticate")
            raise

    async def logout(self, token):
        async with self.db.transaction(self._scope) as c:
            actor = await self._authenticate(c, token, lock=True)
            await c.execute(
                "UPDATE enterprise.auth_sessions SET revoked_at=now() WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, actor.session_id),
            )
            await self._audit(c, actor.user_id, "logout", actor.session_id, "success")

    async def create_user(self, token, username, password, *, preset="standard"):
        try:
            return await self._create_user(token, username, password, preset=preset)
        except (ValueError, LookupError):
            actor = await self.authenticate(token)
            await self._denied("create_user", actor.user_id)
            raise

    async def _create_user(self, token, username, password, *, preset="standard"):
        policy = initial_policy(preset)
        username = self._username(username)
        actor = await self.authenticate(token)
        if actor.role != "tenant_admin":
            await self._denied("create_user", actor.user_id)
            raise PermissionError("tenant administrator required")
        hashed = await self._hash(password)
        async with self.db.transaction(self._scope) as c:
            actor = await self._authenticate(c, token, lock=True)
            if actor.role != "tenant_admin":
                raise PermissionError("tenant administrator required")
            existing = await (
                await c.execute(
                    "SELECT id FROM enterprise.users WHERE tenant_id=%s AND username=%s",
                    (self.tenant_id, username),
                )
            ).fetchone()
            if existing:
                raise ValueError("identity already exists")
            uid = str(uuid.uuid4())
            await c.execute(
                "INSERT INTO enterprise.users(tenant_id,id,username,role,preset,learning_policy) VALUES(%s,%s,%s,'user',%s,%s)",
                (self.tenant_id, uid, username, preset, Jsonb(policy)),
            )
            await c.execute(
                "INSERT INTO enterprise.local_credentials VALUES(%s,%s,%s)",
                (self.tenant_id, uid, hashed),
            )
            await self._audit(c, actor.user_id, "create_user", uid, "success")
        return {"id": uid, "username": username, "role": "user", "preset": preset}

    async def _change(self, token, user_id, action, value=None):
        actor = await self.authenticate(token)
        if actor.role != "tenant_admin" and not (action == "password" and actor.user_id == user_id):
            await self._denied(action, actor.user_id, user_id)
            raise PermissionError("tenant administrator required")
        hashed = await self._hash(value) if action == "password" else None
        async with self.db.transaction(self._scope) as c:
            actor = await self._authenticate(c, token, lock=True)
            if actor.role != "tenant_admin" and not (
                action == "password" and actor.user_id == user_id
            ):
                raise PermissionError("tenant administrator required")
            target = await (
                await c.execute(
                    "SELECT id,disabled FROM enterprise.users WHERE tenant_id=%s AND id=%s AND deleted_at IS NULL FOR UPDATE",
                    (self.tenant_id, user_id),
                )
            ).fetchone()
            if not target:
                raise LookupError("identity not found")
            if action == "password":
                await c.execute(
                    "INSERT INTO enterprise.local_credentials VALUES(%s,%s,%s) ON CONFLICT(tenant_id,user_id) DO UPDATE SET password_hash=EXCLUDED.password_hash",
                    (self.tenant_id, user_id, hashed),
                )
            elif action == "enabled":
                if (
                    value
                    and not await (
                        await c.execute(
                            "SELECT 1 FROM enterprise.local_credentials WHERE tenant_id=%s AND user_id=%s",
                            (self.tenant_id, user_id),
                        )
                    ).fetchone()
                ):
                    raise ValueError("password reset required before enabling")
                if target["disabled"] == (not value):
                    await self._audit(c, actor.user_id, action, user_id, "replayed")
                    return
                await c.execute(
                    "UPDATE enterprise.users SET disabled=%s WHERE tenant_id=%s AND id=%s",
                    (not value, self.tenant_id, user_id),
                )
            await c.execute(
                "UPDATE enterprise.users SET auth_version=auth_version+1 WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, user_id),
            )
            await c.execute(
                "UPDATE enterprise.auth_sessions SET revoked_at=coalesce(revoked_at,now()) WHERE tenant_id=%s AND user_id=%s",
                (self.tenant_id, user_id),
            )
            await self._audit(c, actor.user_id, action, user_id, "success")

    async def change_password(self, token, user_id, password):
        await self._change(token, user_id, "password", password)

    async def set_enabled(self, token, user_id, enabled):
        await self._change(token, user_id, "enabled", bool(enabled))

    async def revoke_sessions(self, token, user_id):
        await self._change(token, user_id, "revoke")
