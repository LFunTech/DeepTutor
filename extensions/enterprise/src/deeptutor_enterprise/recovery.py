"""受控恢复门禁；在停机维护和外置新世代下撤销快照身份，未知账号保持禁用。"""

from contextlib import asynccontextmanager
import uuid

from deeptutor.persistence.postgres.executor import lock_key
from deeptutor.persistence.postgres.identity.service import IdentityService

from .scope import TenantScope


class RecoveryOperations:
    def __init__(self, db, *, tenant_id, resource, auth_epoch, maintenance):
        if not maintenance or not auth_epoch:
            raise ValueError("explicit maintenance mode and external auth epoch required")
        self.db = db
        self.scope = TenantScope(tenant_id, "@recovery")
        self.resource = resource
        self.epoch = auth_epoch

    @asynccontextmanager
    async def _transaction(self):
        async with self.db.transaction(self.scope) as c:
            row = await (
                await c.execute(
                    "SELECT pg_try_advisory_xact_lock(%s) AS acquired", (lock_key(self.resource),)
                )
            ).fetchone()
            if not row["acquired"]:
                raise RuntimeError("application executor must be stopped")
            yield c

    async def _audit(self, c, action, target):
        await c.execute(
            "INSERT INTO enterprise.audit(tenant_id,actor_id,action,target_id,request_id,result) VALUES(%s,%s,%s,%s,%s,%s)",
            (self.scope.tenant_id, "@recovery", action, target, str(uuid.uuid4()), "success"),
        )

    async def quarantine(self, *, old_process_confirmed_stopped):
        if not old_process_confirmed_stopped:
            raise ValueError("old process must be confirmed stopped")
        async with self._transaction() as c:
            tenant = await (
                await c.execute(
                    "SELECT * FROM enterprise.tenants WHERE id=%s FOR UPDATE",
                    (self.scope.tenant_id,),
                )
            ).fetchone()
            if not tenant:
                raise LookupError("tenant not found")
            if tenant["auth_epoch"] == self.epoch:
                if tenant["recovery_state"] == "quarantined":
                    return
                raise ValueError("restore requires a new external authentication epoch")
            await c.execute(
                "UPDATE enterprise.tenants SET local_enabled=false,local_version=local_version+1,auth_epoch=%s,recovery_state='quarantined' WHERE id=%s",
                (self.epoch, self.scope.tenant_id),
            )
            await c.execute(
                "UPDATE enterprise.users SET disabled=true,auth_version=auth_version+1 WHERE tenant_id=%s",
                (self.scope.tenant_id,),
            )
            await c.execute(
                "UPDATE enterprise.auth_sessions SET revoked_at=coalesce(revoked_at,now()) WHERE tenant_id=%s",
                (self.scope.tenant_id,),
            )
            # 不可能用旧快照的 hash 登录；只有受控 reset_account 重建的凭证可重新启用。
            await c.execute(
                "DELETE FROM enterprise.local_credentials WHERE tenant_id=%s",
                (self.scope.tenant_id,),
            )
            await c.execute(
                "UPDATE enterprise.executor_state SET status='stopped',updated_at=now() WHERE status='active'"
            )
            await self._audit(c, "restore_quarantine", self.scope.tenant_id)

    async def _quarantined(self, c):
        row = await (
            await c.execute(
                "SELECT 1 FROM enterprise.tenants WHERE id=%s AND auth_epoch=%s AND recovery_state='quarantined' AND NOT local_enabled FOR UPDATE",
                (self.scope.tenant_id, self.epoch),
            )
        ).fetchone()
        if not row:
            raise ValueError("identity quarantine is required")

    async def reset_account(self, user_id, password, *, enabled=False):
        hashed = await IdentityService._hash(password)
        async with self._transaction() as c:
            await self._quarantined(c)
            row = await (
                await c.execute(
                    "SELECT id FROM enterprise.users WHERE tenant_id=%s AND id=%s FOR UPDATE",
                    (self.scope.tenant_id, user_id),
                )
            ).fetchone()
            if not row:
                raise LookupError("identity not found")
            await c.execute(
                "INSERT INTO enterprise.local_credentials VALUES(%s,%s,%s) ON CONFLICT(tenant_id,user_id) DO UPDATE SET password_hash=EXCLUDED.password_hash",
                (self.scope.tenant_id, user_id, hashed),
            )
            await c.execute(
                "UPDATE enterprise.users SET disabled=%s,auth_version=auth_version+1 WHERE tenant_id=%s AND id=%s",
                (not enabled, self.scope.tenant_id, user_id),
            )
            await self._audit(c, "restore_reset_account", user_id)

    async def release(self):
        async with self._transaction() as c:
            await self._quarantined(c)
            admin = await (
                await c.execute(
                    "SELECT 1 FROM enterprise.users u JOIN enterprise.local_credentials lc ON (lc.tenant_id,lc.user_id)=(u.tenant_id,u.id) WHERE u.tenant_id=%s AND u.role='tenant_admin' AND NOT u.disabled LIMIT 1",
                    (self.scope.tenant_id,),
                )
            ).fetchone()
            if not admin:
                raise ValueError("a verified reset administrator is required")
            await c.execute(
                "UPDATE enterprise.tenants SET local_enabled=true,local_version=local_version+1,recovery_state='normal' WHERE id=%s",
                (self.scope.tenant_id,),
            )
            await self._audit(c, "restore_release", self.scope.tenant_id)
