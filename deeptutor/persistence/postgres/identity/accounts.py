"""唯一 PG 身份服务的账号附属操作；不另建用户或 token 权威。"""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid

import bcrypt
from psycopg.types.json import Jsonb

LEARNER_POLICY = {
    "age_band": "9-12",
    "locked_persona": "teacher",
    "allowed_capabilities": ["chat", "immersive_reading"],
    "default_capability": "immersive_reading",
    "allowed_surfaces": ["chat", "reading"],
    "reading": {"allow_upload": False, "material_ids": [], "extensions": []},
}


def initial_policy(preset):
    if preset not in ("standard", "custom", "learner"):
        raise ValueError("invalid account preset")
    return deepcopy(LEARNER_POLICY) if preset == "learner" else None


def public_account(row):
    result = {
        k: row[k]
        for k in (
            "id",
            "username",
            "role",
            "created_at",
            "disabled",
            "avatar",
            "preset",
            "learner_profile",
            "learning_policy",
        )
    }
    result["created_at"] = result["created_at"].isoformat()
    return result


def public_device(row):
    keys = (
        "id",
        "user_id",
        "device_name",
        "created_at",
        "expires_at",
        "daily_limit_minutes",
        "last_login_at",
        "last_heartbeat_at",
        "usage_day",
        "used_seconds",
        "revoked_at",
        "revoked_by",
    )
    return {k: row[k].isoformat() if hasattr(row[k], "isoformat") else row[k] for k in keys}


def accrued_device_usage(row, now):
    """按微秒累计当前 UTC 日的有效 lease，刷新频率不能丢弃小数余量。"""
    same_day = row["usage_day"] == now.date()
    used_us = (row["used_seconds"] * 1_000_000 + row["usage_remainder_us"]) if same_day else 0
    last = row["last_heartbeat_at"]
    if last:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = max(last, midnight)
        end = min(now, last + timedelta(seconds=300))
        used_us += max((end - start) // timedelta(microseconds=1), 0)
    used_us = min(used_us, row["daily_limit_minutes"] * 60 * 1_000_000)
    return divmod(used_us, 1_000_000)


class AccountOperations:
    """由 IdentityService 继承，所有操作使用其连接、tenant、认证和审计。"""

    async def _admin(self, c, token):
        actor = await self._authenticate(c, token, lock=True)
        if actor.role != "tenant_admin":
            raise PermissionError("tenant administrator required")
        return actor

    async def list_users(self, token):
        async with self.db.transaction(self._scope) as c:
            await self._admin(c, token)
            rows = await (
                await c.execute(
                    "SELECT * FROM enterprise.users WHERE tenant_id=%s AND deleted_at IS NULL ORDER BY created_at,id",
                    (self.tenant_id,),
                )
            ).fetchall()
            return [public_account(row) for row in rows]

    async def _profile_row(self, c, token, username=None):
        actor = await self._authenticate(c, token, lock=True)
        if username and username != actor.username and actor.role != "tenant_admin":
            raise PermissionError("own profile or tenant administrator required")
        row = await (
            await c.execute(
                "SELECT * FROM enterprise.users WHERE tenant_id=%s AND username=%s AND deleted_at IS NULL FOR UPDATE",
                (self.tenant_id, username or actor.username),
            )
        ).fetchone()
        if not row:
            raise LookupError("identity not found")
        return actor, row

    async def profile(self, token, *, username=None):
        async with self.db.transaction(self._scope) as c:
            _, row = await self._profile_row(c, token, username)
            return public_account(row)

    async def update_learner_profile(self, token, profile, *, username=None):
        from deeptutor.multi_user.learner_profile import normalize_profile

        normalized = normalize_profile(profile)
        async with self.db.transaction(self._scope) as c:
            actor, row = await self._profile_row(c, token, username)
            if row["role"] != "user" or row["preset"] != "learner":
                raise LookupError("learner profile required")
            await c.execute(
                "UPDATE enterprise.users SET learner_profile=%s WHERE tenant_id=%s AND id=%s",
                (Jsonb(normalized), self.tenant_id, row["id"]),
            )
            await self._audit(c, actor.user_id, "learner_profile", row["id"], "success")
        return normalized

    async def set_role(self, token, username, role):
        if role not in ("tenant_admin", "user"):
            raise ValueError("invalid tenant role")
        async with self.db.transaction(self._scope) as c:
            actor = await self._admin(c, token)
            if username == actor.username:
                raise ValueError("cannot change own role")
            _, row = await self._profile_row(c, token, username)
            if row["role"] == role:
                return
            await c.execute(
                "UPDATE enterprise.users SET role=%s,auth_version=auth_version+1 WHERE tenant_id=%s AND id=%s",
                (role, self.tenant_id, row["id"]),
            )
            await self._revoke_account(c, actor, row["id"], "role")

    async def _revoke_account(self, c, actor, user_id, action):
        await c.execute(
            "UPDATE enterprise.auth_sessions SET revoked_at=coalesce(revoked_at,now()) WHERE tenant_id=%s AND user_id=%s",
            (self.tenant_id, user_id),
        )
        await c.execute(
            "UPDATE enterprise.device_credentials SET revoked_at=coalesce(revoked_at,now()),revoked_by=%s WHERE tenant_id=%s AND user_id=%s",
            (actor.user_id, self.tenant_id, user_id),
        )
        await self._audit(c, actor.user_id, action, user_id, "success")

    async def delete_user(self, token, username):
        async with self.db.transaction(self._scope) as c:
            actor = await self._admin(c, token)
            if username == actor.username:
                raise ValueError("cannot delete own account")
            _, row = await self._profile_row(c, token, username)
            # 保留复合 FK/正文历史，释放用户名；删除身份永不恢复。
            await c.execute(
                "UPDATE enterprise.users SET username=%s,disabled=true,deleted_at=now(),auth_version=auth_version+1,avatar='',avatar_object='',learner_profile=NULL,learning_policy=NULL WHERE tenant_id=%s AND id=%s",
                ("@deleted:" + uuid.uuid4().hex, self.tenant_id, row["id"]),
            )
            await c.execute(
                "DELETE FROM enterprise.local_credentials WHERE tenant_id=%s AND user_id=%s",
                (self.tenant_id, row["id"]),
            )
            await self._revoke_account(c, actor, row["id"], "delete_user")
            return row

    async def avatar_record(self, token, user_id):
        async with self.db.transaction(self._scope) as c:
            await self._authenticate(c, token)
            row = await (
                await c.execute(
                    "SELECT id,avatar,avatar_object FROM enterprise.users WHERE tenant_id=%s AND id=%s AND deleted_at IS NULL",
                    (self.tenant_id, user_id),
                )
            ).fetchone()
            if not row:
                raise LookupError("avatar not found")
            return row

    async def set_avatar(self, token, marker, object_id=""):
        async with self.db.transaction(self._scope) as c:
            actor, row = await self._profile_row(c, token)
            if object_id:
                previous_version = (
                    row["avatar"].split(":", 1)[-1] if row["avatar"].startswith("img:") else "0"
                )
                marker = "img:" + str(
                    int(previous_version) + 1 if previous_version.isdecimal() else 1
                )
            await c.execute(
                "UPDATE enterprise.users SET avatar=%s,avatar_object=%s WHERE tenant_id=%s AND id=%s",
                (marker, object_id, self.tenant_id, actor.user_id),
            )
            await self._audit(c, actor.user_id, "avatar", actor.user_id, "success")
            return {"previous": row["avatar_object"], "marker": marker}

    async def issue_device(self, token, user_id, device_name, expires_in_days, daily_limit_minutes):
        if (
            not 1 <= expires_in_days <= 365
            or not 5 <= daily_limit_minutes <= 1440
            or not 1 <= len(device_name.strip()) <= 80
        ):
            raise ValueError("invalid device limits")
        code, pin = "dc_" + secrets.token_urlsafe(24), f"{secrets.randbelow(1000000):06d}"
        hashed = (
            await asyncio.to_thread(bcrypt.hashpw, pin.encode(), bcrypt.gensalt(rounds=12))
        ).decode()
        async with self.db.transaction(self._scope) as c:
            actor = await self._admin(c, token)
            row = await (
                await c.execute(
                    "SELECT * FROM enterprise.users WHERE tenant_id=%s AND id=%s AND deleted_at IS NULL FOR UPDATE",
                    (self.tenant_id, user_id),
                )
            ).fetchone()
            if not row:
                raise LookupError("identity not found")
            if row["role"] != "user" or row["preset"] != "learner" or row["disabled"]:
                raise ValueError("device credentials require an active learner account")
            record = await (
                await c.execute(
                    "INSERT INTO enterprise.device_credentials(tenant_id,user_id,id,device_name,pairing_code_hash,pin_hash,auth_version,auth_epoch,expires_at,daily_limit_minutes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    (
                        self.tenant_id,
                        user_id,
                        "dc_" + uuid.uuid4().hex,
                        device_name.strip(),
                        hashlib.sha256(code.encode()).hexdigest(),
                        hashed,
                        row["auth_version"],
                        self.epoch,
                        datetime.now(timezone.utc) + timedelta(days=expires_in_days),
                        daily_limit_minutes,
                    ),
                )
            ).fetchone()
            await self._audit(c, actor.user_id, "device_issue", record["id"], "success")
            return public_device(record), code, pin

    async def list_devices(self, token, *, user_id=None, include_revoked=False):
        async with self.db.transaction(self._scope) as c:
            await self._admin(c, token)
            rows = await (
                await c.execute(
                    "SELECT d.*,u.username FROM enterprise.device_credentials d JOIN enterprise.users u ON (u.tenant_id,u.id)=(d.tenant_id,d.user_id) WHERE d.tenant_id=%s AND u.deleted_at IS NULL AND (%s OR d.revoked_at IS NULL) AND (%s::text IS NULL OR d.user_id=%s) ORDER BY d.created_at,d.id",
                    (self.tenant_id, include_revoked, user_id, user_id),
                )
            ).fetchall()
            return [{**public_device(row), "username": row["username"]} for row in rows]

    async def revoke_device(self, token, credential_id):
        async with self.db.transaction(self._scope) as c:
            actor = await self._admin(c, token)
            row = await (
                await c.execute(
                    "UPDATE enterprise.device_credentials SET revoked_at=coalesce(revoked_at,now()),revoked_by=%s WHERE tenant_id=%s AND id=%s RETURNING *",
                    (actor.user_id, self.tenant_id, credential_id),
                )
            ).fetchone()
            if not row:
                raise LookupError("device credential not found")
            await self._audit(c, actor.user_id, "device_revoke", credential_id, "success")
            return public_device(row)

    async def device_login(self, pairing_code, pin, *, client):
        self._limit(client)
        now = datetime.now(timezone.utc)
        token = None
        async with self.db.transaction(self._scope) as c:
            row = await (
                await c.execute(
                    "SELECT d.*,u.username,u.role,u.preset,u.disabled,u.deleted_at,u.auth_version AS current_version,t.local_enabled,t.external_eligibility,t.provisioning_status,t.auth_epoch AS current_epoch FROM enterprise.device_credentials d JOIN enterprise.users u ON (u.tenant_id,u.id)=(d.tenant_id,d.user_id) JOIN enterprise.tenants t ON t.id=u.tenant_id WHERE d.tenant_id=%s AND d.pairing_code_hash=%s FOR UPDATE OF u,t,d",
                    (self.tenant_id, hashlib.sha256(pairing_code.encode()).hexdigest()),
                )
            ).fetchone()
            if (
                row
                and not row["revoked_at"]
                and row["expires_at"] > now
                and row["role"] == "user"
                and row["preset"] == "learner"
                and not row["disabled"]
                and row["deleted_at"] is None
                and row["auth_version"] == row["current_version"]
                and row["auth_epoch"] == self.epoch == row["current_epoch"]
                and row["local_enabled"]
                and row["external_eligibility"] in ("allowed", "not_required")
                and row["provisioning_status"] == "ready"
                and (not row["pin_locked_until"] or row["pin_locked_until"] <= now)
            ):
                valid = (
                    len(pin) == 6
                    and pin.isascii()
                    and pin.isdigit()
                    and await asyncio.to_thread(
                        bcrypt.checkpw, pin.encode(), row["pin_hash"].encode()
                    )
                )
                if not valid:
                    attempts = row["failed_pin_attempts"] + 1
                    await c.execute(
                        "UPDATE enterprise.device_credentials SET failed_pin_attempts=%s,pin_locked_until=%s WHERE tenant_id=%s AND id=%s",
                        (
                            attempts,
                            now + timedelta(minutes=15) if attempts >= 5 else None,
                            self.tenant_id,
                            row["id"],
                        ),
                    )
                else:
                    used, remainder = accrued_device_usage(row, now)
                    generation = row["generation"] + 1
                    await c.execute(
                        "UPDATE enterprise.device_credentials SET used_seconds=%s,usage_remainder_us=%s,usage_day=%s,failed_pin_attempts=0,pin_locked_until=NULL,generation=%s,last_login_at=%s,last_heartbeat_at=%s WHERE tenant_id=%s AND id=%s",
                        (
                            used,
                            remainder,
                            now.date(),
                            generation,
                            now,
                            now,
                            self.tenant_id,
                            row["id"],
                        ),
                    )
                    if used < row["daily_limit_minutes"] * 60:
                        token = await self._issue_session(
                            c,
                            {"id": row["user_id"], "auth_version": row["auth_version"]},
                            device_id=row["id"],
                            device_generation=generation,
                        )
            await self._audit(
                c,
                row["user_id"] if token else "anonymous",
                "device_login",
                row["id"] if token else "",
                "success" if token else "denied",
            )
        if not token:
            raise PermissionError("invalid credentials")
        return token

    async def _validate_device_session(self, c, session_id):
        row = await (
            await c.execute(
                "SELECT d.*,s.device_generation,u.role,u.preset FROM enterprise.auth_sessions s JOIN enterprise.device_credentials d ON (d.tenant_id,d.user_id,d.id)=(s.tenant_id,s.user_id,s.device_credential_id) JOIN enterprise.users u ON (u.tenant_id,u.id)=(s.tenant_id,s.user_id) WHERE s.tenant_id=%s AND s.id=%s",
                (self.tenant_id, session_id),
            )
        ).fetchone()
        if not row:
            return None
        now = datetime.now(timezone.utc)
        used = row["used_seconds"] if row["usage_day"] == now.date() else 0
        last = row["last_heartbeat_at"]
        if (
            row["revoked_at"]
            or row["expires_at"] <= now
            or row["generation"] != row["device_generation"]
            or row["role"] != "user"
            or row["preset"] != "learner"
            or used >= row["daily_limit_minutes"] * 60
            or not last
            or not 0 <= (now - last).total_seconds() <= 300
        ):
            raise PermissionError("authentication required")
        return row

    async def device_heartbeat(self, token):
        async with self.db.transaction(self._scope) as c:
            actor = await self._authenticate(c, token, lock=True)
            row = await self._validate_device_session(c, actor.session_id)
            if row is None:
                return None
            await c.execute(
                "SELECT id FROM enterprise.device_credentials WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, row["id"]),
            )
            row = await self._validate_device_session(c, actor.session_id)
            now = datetime.now(timezone.utc)
            used, remainder = accrued_device_usage(row, now)
            updated = await (
                await c.execute(
                    "UPDATE enterprise.device_credentials SET used_seconds=%s,usage_remainder_us=%s,usage_day=%s,last_heartbeat_at=%s WHERE tenant_id=%s AND id=%s RETURNING *",
                    (used, remainder, now.date(), now, self.tenant_id, row["id"]),
                )
            ).fetchone()
            return {
                **public_device(updated),
                "remaining_seconds": row["daily_limit_minutes"] * 60 - used,
                "limit_reached": used >= row["daily_limit_minutes"] * 60,
            }
