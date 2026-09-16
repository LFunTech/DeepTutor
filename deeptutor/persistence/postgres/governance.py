"""PG-backed runtime governance primitives for TMS/OMS contracts.

此模块只保存配置 desired/active 状态、Secret 引用和脱敏审计摘要。
Secret 明文必须由 Secret provider 注入；不能进入 PG、日志或 report。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

_SENSITIVE_KEYS = {
    "api_key",
    "auth_epoch",
    "cookie_secret",
    "dsn",
    "password",
    "private_key",
    "secret",
    "secret_key",
    "signing_key",
    "token",
}


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            lowered = text_key.lower()
            if lowered in _SENSITIVE_KEYS or any(
                token in lowered for token in ("api_key", "password", "secret", "token", "dsn")
            ):
                redacted[text_key] = "<secret-ref-required>"
            else:
                redacted[text_key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _scope(scope_kind: str, scope_id: str) -> tuple[str, str]:
    if scope_kind not in {"platform", "tenant", "owner", "resource"}:
        raise ValueError("unsupported governance scope")
    if scope_kind in {"platform", "tenant"}:
        return scope_kind, ""
    if not scope_id:
        raise ValueError("scoped governance writes require a scope id")
    return scope_kind, scope_id


def _row_dict(row) -> dict[str, Any]:
    return dict(getattr(row, "_mapping", row))


class RuntimeGovernanceStore:
    """Settings/Secret/audit/usage store scoped by the current PG tenant."""

    def __init__(self, store) -> None:
        self.store = store

    @property
    def _tenant_id(self) -> str:
        return self.store.scope.tenant_id

    @property
    def _actor_owner_id(self) -> str:
        return self.store.scope.user_id

    async def _audit(
        self,
        c,
        event_kind: str,
        *,
        actor_id: str,
        scope_kind: str = "tenant",
        scope_id: str = "",
        resource_kind: str = "",
        resource_id: str = "",
        summary: Mapping[str, Any] | None = None,
    ) -> None:
        kind, sid = _scope(scope_kind, scope_id) if scope_kind == "resource" else (scope_kind, scope_id)
        await c.execute(
            "INSERT INTO enterprise.runtime_audit_events"
            "(tenant_id,id,event_kind,actor_id,scope_kind,scope_id,resource_kind,resource_id,summary) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self._tenant_id,
                uuid4(),
                event_kind,
                actor_id,
                kind,
                sid,
                resource_kind,
                resource_id,
                Jsonb(_redact(dict(summary or {}))),
            ),
        )

    async def record_event(
        self,
        event_kind: str,
        *,
        actor_id: str,
        scope_kind: str = "tenant",
        scope_id: str = "",
        resource_kind: str = "",
        resource_id: str = "",
        summary: Mapping[str, Any] | None = None,
    ) -> None:
        """Append a redacted audit event in its own transaction."""

        async with self.store.db.transaction(self.store.scope) as c:
            await self._audit(
                c,
                event_kind,
                actor_id=actor_id,
                scope_kind=scope_kind,
                scope_id=scope_id,
                resource_kind=resource_kind,
                resource_id=resource_id,
                summary=summary,
            )

    async def save_setting(
        self,
        *,
        key: str,
        desired: Mapping[str, Any],
        actor_id: str,
        scope_kind: str = "tenant",
        scope_id: str = "",
    ) -> dict[str, Any]:
        if not key:
            raise ValueError("settings key is required")
        if actor_id != self._actor_owner_id:
            raise PermissionError("actor does not match authenticated scope")
        kind, sid = _scope(scope_kind, scope_id)
        redacted = _redact(dict(desired))
        async with self.store.db.transaction(self.store.scope) as c:
            row = await (
                await c.execute(
                    "INSERT INTO enterprise.runtime_settings"
                    "(tenant_id,scope_kind,scope_id,key,version,desired,active,status,updated_by) "
                    "VALUES(%s,%s,%s,%s,1,%s,'{}'::jsonb,'saved',%s) "
                    "ON CONFLICT (tenant_id,scope_kind,scope_id,key) DO UPDATE "
                    "SET desired=EXCLUDED.desired,status='saved',version=enterprise.runtime_settings.version+1,"
                    "updated_by=EXCLUDED.updated_by,updated_at=now() "
                    "RETURNING tenant_id,scope_kind,scope_id,key,version,desired,active,status,updated_by",
                    (self._tenant_id, kind, sid, key, Jsonb(redacted), actor_id),
                )
            ).fetchone()
            await self._audit(
                c,
                "settings.saved",
                actor_id=actor_id,
                scope_kind=kind,
                scope_id=sid,
                resource_kind="runtime_setting",
                resource_id=key,
                summary={"key": key, "desired": redacted, "status": "saved"},
            )
        return _row_dict(row)

    async def mark_active(
        self,
        key: str,
        *,
        actor_id: str,
        scope_kind: str = "tenant",
        scope_id: str = "",
    ) -> dict[str, Any]:
        if actor_id != self._actor_owner_id:
            raise PermissionError("actor does not match authenticated scope")
        kind, sid = _scope(scope_kind, scope_id)
        async with self.store.db.transaction(self.store.scope) as c:
            row = await (
                await c.execute(
                    "UPDATE enterprise.runtime_settings "
                    "SET active=desired,status='active',version=version+1,updated_by=%s,updated_at=now() "
                    "WHERE tenant_id=%s AND scope_kind=%s AND scope_id=%s AND key=%s "
                    "RETURNING tenant_id,scope_kind,scope_id,key,version,desired,active,status,updated_by",
                    (actor_id, self._tenant_id, kind, sid, key),
                )
            ).fetchone()
            if row is None:
                raise KeyError(key)
            await self._audit(
                c,
                "settings.active",
                actor_id=actor_id,
                scope_kind=kind,
                scope_id=sid,
                resource_kind="runtime_setting",
                resource_id=key,
                summary={"key": key, "version": _row_dict(row)["version"], "status": "active"},
            )
        return _row_dict(row)

    async def upsert_secret_reference(
        self,
        *,
        name: str,
        provider: str,
        reference: str,
        actor_id: str,
        status: str = "saved",
        scope_kind: str = "tenant",
        scope_id: str = "",
    ) -> dict[str, Any]:
        if actor_id != self._actor_owner_id:
            raise PermissionError("actor does not match authenticated scope")
        kind, sid = _scope(scope_kind, scope_id)
        redacted_summary = f"{provider}:{reference}:{status}"
        async with self.store.db.transaction(self.store.scope) as c:
            row = await (
                await c.execute(
                    "INSERT INTO enterprise.secret_references"
                    "(tenant_id,scope_kind,scope_id,name,provider,reference,version,status,redacted_summary,updated_by) "
                    "VALUES(%s,%s,%s,%s,%s,%s,1,%s,%s,%s) "
                    "ON CONFLICT (tenant_id,scope_kind,scope_id,name) DO UPDATE "
                    "SET provider=EXCLUDED.provider,reference=EXCLUDED.reference,status=EXCLUDED.status,"
                    "redacted_summary=EXCLUDED.redacted_summary,updated_by=EXCLUDED.updated_by,"
                    "version=enterprise.secret_references.version+1,updated_at=now() "
                    "RETURNING tenant_id,scope_kind,scope_id,name,provider,version,status,redacted_summary,updated_by",
                    (
                        self._tenant_id,
                        kind,
                        sid,
                        name,
                        provider,
                        reference,
                        status,
                        redacted_summary,
                        actor_id,
                    ),
                )
            ).fetchone()
            await self._audit(
                c,
                "secret_ref.saved",
                actor_id=actor_id,
                scope_kind=kind,
                scope_id=sid,
                resource_kind="secret_reference",
                resource_id=name,
                summary={
                    "name": name,
                    "provider": provider,
                    "redacted_summary": redacted_summary,
                    "status": status,
                },
            )
        return _row_dict(row)

    async def list_audit(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 500))
        async with self.store.db.transaction(self.store.scope) as c:
            rows = await (
                await c.execute(
                    "SELECT id,event_kind,actor_id,scope_kind,scope_id,resource_kind,resource_id,summary,created_at "
                    "FROM enterprise.runtime_audit_events "
                    "WHERE tenant_id=%s ORDER BY created_at ASC,id ASC LIMIT %s",
                    (self._tenant_id, bounded),
                )
            ).fetchall()
        return [_row_dict(row) for row in rows]

    async def usage_summary(self) -> dict[str, Any]:
        async with self.store.db.transaction(self.store.scope) as c:
            object_rows = await (
                await c.execute(
                    "SELECT resource_kind,state,count(*)::bigint AS count,coalesce(sum(size_bytes),0)::bigint AS size_bytes "
                    "FROM enterprise.resource_objects WHERE tenant_id=%s "
                    "GROUP BY resource_kind,state ORDER BY resource_kind,state",
                    (self._tenant_id,),
                )
            ).fetchall()
            cleanup_rows = await (
                await c.execute(
                    "SELECT state,count(*)::bigint AS count "
                    "FROM enterprise.resource_cleanup_jobs WHERE tenant_id=%s "
                    "GROUP BY state ORDER BY state",
                    (self._tenant_id,),
                )
            ).fetchall()
        return {
            "tenant_id": self._tenant_id,
            "objects": [_row_dict(row) for row in object_rows],
            "cleanup": [_row_dict(row) for row in cleanup_rows],
        }
