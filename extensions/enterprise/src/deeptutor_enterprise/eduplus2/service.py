"""EduPlus2 联邦 client 注册、JWT 静默换票与审计。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import time
import uuid

from jose import jwt
from psycopg.types.json import Jsonb

from deeptutor_enterprise.scope import TenantScope

from .client import HmacEduPlus2JwtVerifier, VerifiedEduPlus2Jwt

_REQUIRED_CLAIMS = ("iss", "exp", "iat", "tid", "eui", "sub", "azp")
_ACTIVE_VALUES = {"active", "enabled", "allowed"}
_AUTO_REGISTRATION_SOURCES = {"env_allowlist", "ops_import", "auto_upsert", "test_seed"}
_MANAGEMENT_USAGE_PREFIXES = ("tms.", "tms:", "oms.", "oms:", "ops.", "ops:", "platform.")
_REVOCATION_TARGET_BY_EVENT = {
    "user.disabled": "user",
    "user.deleted": "user",
    "user.revoked": "user",
    "client.revoked": "client",
    "client.disabled": "client",
    "app.inactive": "app",
    "app.revoked": "app",
    "tenant.inactive": "tenant",
    "tenant.revoked": "tenant",
    "subscription.inactive": "subscription",
    "subscription.revoked": "subscription",
    "permission.revoked": "permission",
    "permission.denied": "permission",
}


@dataclass(frozen=True, slots=True)
class ExchangeResult:
    dt_token: str
    token_type: str
    expires_in: int
    expires_at: int
    tenant_id: str
    user_id: str
    client_registration_id: str

    def to_dict(self) -> dict:
        return {
            "dt_token": self.dt_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "expires_at": self.expires_at,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "client_registration_id": self.client_registration_id,
        }


class EduPlus2AccessService:
    """企业扩展内实现 EduPlus2 权威解析、注册和短期 token exchange。"""

    def __init__(
        self,
        db,
        *,
        identity,
        resolver,
        eduplus2_signing_key: str | None = None,
        eduplus2_issuer: str | None = None,
        jwt_verifier=None,
        dt_token_seconds: int = 900,
        allowed_clients: tuple[dict, ...] | list[dict] = (),
        resolve_cache_seconds: int = 60,
        exchange_rate_limit_per_minute: int = 60,
        profile_client=None,
        permission_client=None,
        requested_usages: tuple[str, ...] = ("deeptutor.chat",),
        audit_export_storage_ref: str = "db://eduplus2/audit-export",
        revocation_cache_seconds: int = 30,
    ):
        self.db = db
        self.identity = identity
        self.resolver = resolver
        self.jwt_verifier = jwt_verifier or HmacEduPlus2JwtVerifier(
            signing_key=eduplus2_signing_key or "",
            issuer=eduplus2_issuer or "",
        )
        if not 60 <= int(dt_token_seconds) <= identity.token_seconds:
            raise ValueError("invalid dt_token lifetime")
        self.dt_token_seconds = int(dt_token_seconds)
        self.resolve_cache_seconds = max(0, int(resolve_cache_seconds))
        self.exchange_rate_limit_per_minute = max(1, int(exchange_rate_limit_per_minute))
        self.profile_client = profile_client
        self.permission_client = permission_client
        self.requested_usages = tuple(str(item) for item in requested_usages if str(item).strip())
        self.audit_export_storage_ref = (
            audit_export_storage_ref.rstrip("/")
            if audit_export_storage_ref
            else "db://eduplus2/audit-export"
        )
        self.revocation_cache_seconds = max(0, int(revocation_cache_seconds))
        self.allowed_clients = {
            str(item.get("client_id") or "").strip(): {
                "client_id": str(item.get("client_id") or "").strip(),
                "external_tenant_id": str(
                    item.get("external_tenant_id") or item.get("expected_tenant_id") or ""
                ).strip(),
                "external_app_id": str(
                    item.get("external_app_id") or item.get("expected_app_id") or ""
                ).strip(),
                "internal_tenant_id": str(
                    item.get("internal_tenant_id") or identity.tenant_id
                ).strip(),
                "source": str(item.get("source") or "env_allowlist").strip(),
                "status": str(item.get("status") or "active").strip(),
            }
            for item in allowed_clients
            if str(item.get("client_id") or "").strip()
        }
        self._scope = TenantScope(identity.tenant_id, "@eduplus2")

    async def _enforce_exchange_replay_and_rate_limit(
        self,
        c,
        *,
        request_id: str,
        client_id: str,
        external_tenant_id: str,
        external_user_id: str,
        token_hash: str,
        token_kid: str,
    ) -> None:
        await c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"eduplus2:{token_hash}",))
        replayed = await (
            await c.execute(
                """
                SELECT 1 FROM eduplus2.audit_events
                 WHERE tenant_id=%s AND event_kind='token.exchange' AND result='success'
                   AND summary->>'token_hash'=%s
                   AND created_at > now() - make_interval(secs => %s)
                 LIMIT 1
                """,
                (self.identity.tenant_id, token_hash, self.dt_token_seconds),
            )
        ).fetchone()
        if replayed:
            await self._audit(
                c,
                event_kind="token.exchange",
                result="replayed",
                reason="token_replay",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_user_id=external_user_id,
                summary={"token_hash": token_hash, "kid": token_kid},
            )
            raise PermissionError("token replay detected")
        recent = await (
            await c.execute(
                """
                SELECT count(*) FROM eduplus2.audit_events
                 WHERE tenant_id=%s AND event_kind='token.exchange'
                   AND client_id=%s AND external_tenant_id=%s AND external_user_id=%s
                   AND created_at > now() - interval '1 minute'
                """,
                (self.identity.tenant_id, client_id, external_tenant_id, external_user_id),
            )
        ).fetchone()
        if int(recent["count"]) >= self.exchange_rate_limit_per_minute:
            await self._audit(
                c,
                event_kind="token.exchange",
                result="denied",
                reason="rate_limited",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_user_id=external_user_id,
                summary={"token_hash": token_hash, "kid": token_kid},
            )
            raise PermissionError("exchange rate limited")

    async def _audit(
        self,
        c,
        *,
        event_kind: str,
        result: str,
        reason: str = "",
        request_id: str = "",
        actor_id: str = "",
        client_id: str = "",
        external_tenant_id: str = "",
        external_app_id: str = "",
        external_user_id: str = "",
        internal_user_id: str = "",
        session_id: str = "",
        policy_version: str = "",
        summary: dict | None = None,
    ):
        safe_summary = dict(summary or {})
        for forbidden in ("token", "jwt", "secret", "authorization", "client_secret"):
            safe_summary.pop(forbidden, None)
        await c.execute(
            """
            INSERT INTO eduplus2.audit_events(
              tenant_id,id,request_id,event_kind,actor_id,client_id,external_tenant_id,
              external_app_id,external_user_id,internal_user_id,session_id,result,reason,
              policy_version,summary
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                self.identity.tenant_id,
                str(uuid.uuid4()),
                request_id,
                event_kind,
                actor_id,
                client_id,
                external_tenant_id,
                external_app_id,
                external_user_id,
                internal_user_id,
                session_id,
                result,
                reason,
                policy_version,
                Jsonb(safe_summary),
            ),
        )

    async def _audit_outside_transaction(self, **kwargs) -> None:
        async with self.db.transaction(self._scope) as c:
            await self._audit(c, **kwargs)

    @staticmethod
    def _ordinary_usages(usages) -> list[str]:
        allowed = []
        for usage in usages or ():
            value = str(usage or "").strip()
            lowered = value.lower()
            if value and not lowered.startswith(_MANAGEMENT_USAGE_PREFIXES):
                allowed.append(value)
        return allowed

    async def _fetch_profile(
        self,
        c,
        *,
        claims: dict,
        client_id: str,
        resolved: dict,
        request_id: str,
        token_hash: str,
        token_kid: str,
    ) -> dict | None:
        if self.profile_client is None:
            return None
        external_tenant_id = str(claims["tid"]).strip()
        external_user_id = self._external_user_id(claims)
        external_subject = str(claims.get("sub") or "").strip()
        try:
            profile = await self.profile_client.fetch_profile(
                external_tenant_id=external_tenant_id,
                external_user_id=external_user_id,
                external_subject=external_subject,
                client_id=client_id,
                external_app_id=str(resolved["external_app_id"]),
            )
        except LookupError:
            await self._audit_outside_transaction(
                event_kind="profile.fetch",
                result="failed",
                reason="profile_unavailable",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_app_id=str(resolved.get("external_app_id") or ""),
                external_user_id=external_user_id,
                summary={"token_hash": token_hash, "kid": token_kid},
            )
            raise RuntimeError("profile unavailable") from None
        except RuntimeError:
            await self._audit_outside_transaction(
                event_kind="profile.fetch",
                result="failed",
                reason="profile_unavailable",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_app_id=str(resolved.get("external_app_id") or ""),
                external_user_id=external_user_id,
                summary={"token_hash": token_hash, "kid": token_kid},
            )
            raise
        except PermissionError as exc:
            await self._audit_outside_transaction(
                event_kind="profile.fetch",
                result="denied",
                reason=str(exc) or "profile_denied",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_app_id=str(resolved.get("external_app_id") or ""),
                external_user_id=external_user_id,
                summary={"token_hash": token_hash, "kid": token_kid},
            )
            raise
        if profile["external_tenant_id"] != external_tenant_id:
            raise PermissionError("profile mismatch")
        await self._persist_profile_snapshot(c, profile)
        await self._audit(
            c,
            event_kind="profile.fetch",
            result="success",
            request_id=request_id,
            client_id=client_id,
            external_tenant_id=external_tenant_id,
            external_app_id=str(resolved.get("external_app_id") or ""),
            external_user_id=external_user_id,
            policy_version=str(profile.get("version") or ""),
            summary={
                "token_hash": token_hash,
                "kid": token_kid,
                "status": str(profile.get("status") or ""),
                "profile_version": str(profile.get("version") or ""),
            },
        )
        return profile

    async def _check_permission(
        self,
        c,
        *,
        claims: dict,
        client_id: str,
        registration: dict,
        resolved: dict,
        request_id: str,
        token_hash: str,
        token_kid: str,
    ) -> dict | None:
        if self.permission_client is None:
            return None
        external_tenant_id = str(claims["tid"]).strip()
        external_user_id = self._external_user_id(claims)
        external_subject = str(claims.get("sub") or "").strip()
        try:
            permission = await self.permission_client.check_permission(
                external_tenant_id=external_tenant_id,
                external_user_id=external_user_id,
                external_subject=external_subject,
                client_id=client_id,
                external_app_id=str(resolved["external_app_id"]),
                requested_usages=self.requested_usages,
            )
        except LookupError:
            await self._audit_outside_transaction(
                event_kind="permission.check",
                result="failed",
                reason="permission_unavailable",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_app_id=str(resolved.get("external_app_id") or ""),
                external_user_id=external_user_id,
                summary={"token_hash": token_hash, "kid": token_kid},
            )
            raise RuntimeError("permission unavailable") from None
        except RuntimeError:
            await self._audit_outside_transaction(
                event_kind="permission.check",
                result="failed",
                reason="permission_unavailable",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_app_id=str(resolved.get("external_app_id") or ""),
                external_user_id=external_user_id,
                summary={"token_hash": token_hash, "kid": token_kid},
            )
            raise
        except PermissionError as exc:
            reason = str(exc) or "permission_denied"
            await self._audit_outside_transaction(
                event_kind="permission.check",
                result="denied",
                reason=reason,
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_app_id=str(resolved.get("external_app_id") or ""),
                external_user_id=external_user_id,
                summary={"token_hash": token_hash, "kid": token_kid},
            )
            raise PermissionError("permission denied") from exc
        await self._persist_permission_snapshot(c, permission, registration)
        await self._audit(
            c,
            event_kind="permission.check",
            result="success",
            reason=str(permission.get("reason") or "ok"),
            request_id=request_id,
            client_id=client_id,
            external_tenant_id=external_tenant_id,
            external_app_id=str(resolved.get("external_app_id") or ""),
            external_user_id=external_user_id,
            policy_version=str(permission.get("version") or ""),
            summary={
                "token_hash": token_hash,
                "kid": token_kid,
                "allowed_usages": self._ordinary_usages(permission.get("allowed_usages") or []),
            },
        )
        return permission

    async def _persist_profile_snapshot(self, c, profile: dict) -> None:
        await c.execute(
            """
            INSERT INTO eduplus2.profile_snapshots(
              tenant_id,provider,external_tenant_id,external_user_id,external_subject,
              external_identity_type,display_name,status,profile_version,profile_snapshot,
              fetched_at,updated_at
            ) VALUES(%s,'eduplus2',%s,%s,%s,%s,%s,%s,%s,%s,now(),now())
            ON CONFLICT (tenant_id,provider,external_tenant_id,external_user_id) DO UPDATE
               SET external_subject=EXCLUDED.external_subject,
                   external_identity_type=EXCLUDED.external_identity_type,
                   display_name=EXCLUDED.display_name,
                   status=EXCLUDED.status,
                   profile_version=EXCLUDED.profile_version,
                   profile_snapshot=EXCLUDED.profile_snapshot,
                   fetched_at=now(),
                   updated_at=now()
            """,
            (
                self.identity.tenant_id,
                str(profile["external_tenant_id"]),
                str(profile["external_user_id"]),
                str(profile.get("external_subject") or ""),
                str(profile.get("external_identity_type") or ""),
                str(profile.get("display_name") or ""),
                str(profile.get("status") or ""),
                str(profile.get("version") or ""),
                Jsonb(profile.get("summary") or {}),
            ),
        )

    async def _persist_permission_snapshot(self, c, permission: dict, registration: dict) -> None:
        await c.execute(
            """
            INSERT INTO eduplus2.permission_snapshots(
              tenant_id,provider,client_registration_id,external_tenant_id,external_user_id,
              external_subject,client_id,external_app_id,allowed,reason,allowed_usages,scopes,
              permission_version,permission_snapshot,expires_at,fetched_at,updated_at
            ) VALUES(%s,'eduplus2',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULLIF(%s,'')::timestamptz,now(),now())
            ON CONFLICT (tenant_id,provider,external_tenant_id,external_user_id,client_registration_id)
            DO UPDATE
               SET external_subject=EXCLUDED.external_subject,
                   client_id=EXCLUDED.client_id,
                   external_app_id=EXCLUDED.external_app_id,
                   allowed=EXCLUDED.allowed,
                   reason=EXCLUDED.reason,
                   allowed_usages=EXCLUDED.allowed_usages,
                   scopes=EXCLUDED.scopes,
                   permission_version=EXCLUDED.permission_version,
                   permission_snapshot=EXCLUDED.permission_snapshot,
                   expires_at=EXCLUDED.expires_at,
                   fetched_at=now(),
                   updated_at=now()
            """,
            (
                self.identity.tenant_id,
                registration["id"],
                str(permission["external_tenant_id"]),
                str(permission["external_user_id"]),
                str(permission.get("external_subject") or ""),
                str(permission["client_id"]),
                str(permission["external_app_id"]),
                bool(permission.get("allowed", False)),
                str(permission.get("reason") or ""),
                list(permission.get("allowed_usages") or []),
                list(permission.get("scopes") or []),
                str(permission.get("version") or ""),
                Jsonb(permission.get("summary") or {}),
                str(permission.get("expires_at") or ""),
            ),
        )

    @staticmethod
    def _revocation_target_kind(event_type: str) -> str:
        event_type = str(event_type or "").strip().lower()
        if event_type in _REVOCATION_TARGET_BY_EVENT:
            return _REVOCATION_TARGET_BY_EVENT[event_type]
        prefix = event_type.split(".", 1)[0]
        if prefix in {"user", "client", "app", "tenant", "permission", "subscription"}:
            return prefix
        raise ValueError("unsupported revocation event type")

    async def _ensure_not_revoked(
        self,
        c,
        *,
        external_tenant_id: str,
        external_user_id: str = "",
        client_id: str = "",
        external_app_id: str = "",
    ) -> None:
        row = await (
            await c.execute(
                """
                SELECT target_kind,reason FROM eduplus2.revocation_state
                 WHERE tenant_id=%s AND active AND (
                   (target_kind='tenant' AND external_tenant_id=%s)
                   OR (target_kind='user' AND external_tenant_id=%s AND external_user_id=%s)
                   OR (target_kind='client' AND client_id=%s)
                   OR (target_kind='app' AND external_app_id=%s)
                   OR (
                     target_kind='permission'
                     AND external_tenant_id=%s AND external_user_id=%s AND client_id=%s
                     AND (external_app_id='' OR external_app_id=%s)
                   )
                   OR (
                     target_kind='subscription'
                     AND external_tenant_id=%s
                     AND (client_id='' OR client_id=%s)
                     AND (external_app_id='' OR external_app_id=%s)
                   )
                 )
                 ORDER BY updated_at DESC
                 LIMIT 1
                """,
                (
                    self.identity.tenant_id,
                    external_tenant_id,
                    external_tenant_id,
                    external_user_id,
                    client_id,
                    external_app_id,
                    external_tenant_id,
                    external_user_id,
                    client_id,
                    external_app_id,
                    external_tenant_id,
                    client_id,
                    external_app_id,
                ),
            )
        ).fetchone()
        if row:
            raise PermissionError("access revoked")

    async def ensure_token_allowed(
        self,
        token: str,
        *,
        required_usage: str = "deeptutor.chat",
    ) -> None:
        claims = jwt.get_unverified_claims(token)
        eduplus2 = claims.get("eduplus2")
        if not isinstance(eduplus2, dict):
            return
        async with self.db.transaction(self._scope) as c:
            await self._ensure_not_revoked(
                c,
                external_tenant_id=str(eduplus2.get("external_tenant_id") or ""),
                external_user_id=str(eduplus2.get("external_user_id") or ""),
                client_id=str(eduplus2.get("azp") or ""),
                external_app_id=str(eduplus2.get("external_app_id") or ""),
            )
            if eduplus2.get("permission_version"):
                row = await (
                    await c.execute(
                        """
                        SELECT allowed,reason,allowed_usages,expires_at,updated_at
                          FROM eduplus2.permission_snapshots
                         WHERE tenant_id=%s AND provider='eduplus2'
                           AND external_tenant_id=%s AND external_user_id=%s
                           AND client_registration_id=%s
                         ORDER BY updated_at DESC
                         LIMIT 1
                        """,
                        (
                            self.identity.tenant_id,
                            str(eduplus2.get("external_tenant_id") or ""),
                            str(eduplus2.get("external_user_id") or ""),
                            str(eduplus2.get("client_registration_id") or ""),
                        ),
                    )
                ).fetchone()
                if self._snapshot_recheck_due(row["updated_at"] if row else None):
                    await self._revalidate_external_authorization_snapshot(
                        c,
                        eduplus2=eduplus2,
                        required_usage=required_usage,
                        token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    )
                    row = await (
                        await c.execute(
                            """
                            SELECT allowed,reason,allowed_usages,expires_at,updated_at
                              FROM eduplus2.permission_snapshots
                             WHERE tenant_id=%s AND provider='eduplus2'
                               AND external_tenant_id=%s AND external_user_id=%s
                               AND client_registration_id=%s
                             ORDER BY updated_at DESC
                             LIMIT 1
                            """,
                            (
                                self.identity.tenant_id,
                                str(eduplus2.get("external_tenant_id") or ""),
                                str(eduplus2.get("external_user_id") or ""),
                                str(eduplus2.get("client_registration_id") or ""),
                            ),
                        )
                    ).fetchone()
                if not row or not row["allowed"]:
                    raise PermissionError("permission revoked")
                if row["expires_at"] is not None and row["expires_at"] <= datetime.now(
                    timezone.utc
                ):
                    raise PermissionError("permission revoked")
                usages = [str(item) for item in row["allowed_usages"] or []]
                if usages and required_usage not in usages:
                    raise PermissionError("permission revoked")

    def _snapshot_recheck_due(self, updated_at) -> bool:
        if updated_at is None:
            return True
        if self.revocation_cache_seconds == 0:
            return True
        return updated_at <= datetime.now(timezone.utc) - timedelta(
            seconds=self.revocation_cache_seconds
        )

    async def _revalidate_external_authorization_snapshot(
        self,
        c,
        *,
        eduplus2: dict,
        required_usage: str,
        token_hash: str,
    ) -> None:
        if self.permission_client is None:
            raise PermissionError("permission recheck unavailable")
        client_registration_id = str(eduplus2.get("client_registration_id") or "")
        external_tenant_id = str(eduplus2.get("external_tenant_id") or "")
        external_user_id = str(eduplus2.get("external_user_id") or "")
        client_id = str(eduplus2.get("azp") or "")
        registration = await (
            await c.execute(
                """
                SELECT *
                  FROM eduplus2.external_client_registrations
                 WHERE tenant_id=%s AND provider='eduplus2' AND id=%s AND client_id=%s
                """,
                (self.identity.tenant_id, client_registration_id, client_id),
            )
        ).fetchone()
        if not registration or registration["status"] != "active":
            raise PermissionError("registration revoked")
        resolved = await self._resolve(
            client_id,
            c=c,
            request_id="token-recheck",
            external_user_id=external_user_id,
        )
        if (
            external_tenant_id != registration["external_tenant_id"]
            or external_tenant_id != resolved["external_tenant_id"]
            or registration["external_app_id"] != resolved["external_app_id"]
        ):
            raise PermissionError("tenant mismatch")
        binding = await (
            await c.execute(
                """
                SELECT external_subject
                  FROM eduplus2.identity_bindings
                 WHERE tenant_id=%s AND provider='eduplus2'
                   AND external_tenant_id=%s AND external_user_id=%s
                """,
                (self.identity.tenant_id, external_tenant_id, external_user_id),
            )
        ).fetchone()
        claims = {
            "tid": external_tenant_id,
            "eui": external_user_id,
            "sub": str(binding["external_subject"] if binding else ""),
            "azp": client_id,
        }
        if self.profile_client is not None:
            profile = await self._fetch_profile(
                c,
                claims=claims,
                client_id=client_id,
                resolved=resolved,
                request_id="token-recheck",
                token_hash=token_hash,
                token_kid="",
            )
            claims["sub"] = str((profile or {}).get("external_subject") or claims["sub"])
        permission = await self._check_permission(
            c,
            claims=claims,
            client_id=client_id,
            registration=dict(registration),
            resolved=resolved,
            request_id="token-recheck",
            token_hash=token_hash,
            token_kid="",
        )
        usages = self._ordinary_usages((permission or {}).get("allowed_usages") or [])
        if usages and required_usage not in usages:
            raise PermissionError("permission revoked")

    async def apply_revocation_event(self, event: dict, *, request_id: str = "") -> dict:
        event_id = str(event.get("event_id") or event.get("id") or "").strip()
        event_type = str(event.get("event_type") or event.get("type") or "").strip()
        if not event_id or not event_type:
            raise ValueError("revocation event id and type are required")
        target_kind = self._revocation_target_kind(event_type)
        external_tenant_id = str(event.get("external_tenant_id") or event.get("tenant_id") or "")
        external_user_id = str(event.get("external_user_id") or event.get("user_id") or "")
        client_id = str(event.get("client_id") or "")
        external_app_id = str(event.get("external_app_id") or event.get("app_id") or "")
        reason = str(event.get("reason") or event_type)
        event_version = str(event.get("version") or event.get("event_version") or "")
        occurred_at = str(event.get("occurred_at") or "")
        summary = {
            "event_type": event_type,
            "target_kind": target_kind,
            "external_tenant_id": external_tenant_id,
            "external_user_id": external_user_id,
            "client_id": client_id,
            "external_app_id": external_app_id,
            "reason": reason,
            "event_version": event_version,
        }
        async with self.db.transaction(self._scope) as c:
            duplicate = await (
                await c.execute(
                    "SELECT processing_status FROM eduplus2.revocation_events WHERE tenant_id=%s AND event_id=%s",
                    (self.identity.tenant_id, event_id),
                )
            ).fetchone()
            if duplicate:
                return {"status": "duplicate", "event_id": event_id}
            await c.execute(
                """
                INSERT INTO eduplus2.revocation_events(
                  tenant_id,event_id,event_type,target_kind,external_tenant_id,
                  external_user_id,client_id,external_app_id,reason,event_version,
                  payload_summary,processing_status,occurred_at,processed_at
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'applied',NULLIF(%s,'')::timestamptz,now())
                """,
                (
                    self.identity.tenant_id,
                    event_id,
                    event_type,
                    target_kind,
                    external_tenant_id,
                    external_user_id,
                    client_id,
                    external_app_id,
                    reason,
                    event_version,
                    Jsonb(summary),
                    occurred_at,
                ),
            )
            await c.execute(
                """
                INSERT INTO eduplus2.revocation_state(
                  tenant_id,target_kind,external_tenant_id,external_user_id,
                  client_id,external_app_id,event_id,reason,event_version,active,updated_at
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,true,now())
                ON CONFLICT (tenant_id,target_kind,external_tenant_id,external_user_id,client_id,external_app_id)
                DO UPDATE SET event_id=EXCLUDED.event_id,
                              reason=EXCLUDED.reason,
                              event_version=EXCLUDED.event_version,
                              active=true,
                              updated_at=now()
                """,
                (
                    self.identity.tenant_id,
                    target_kind,
                    external_tenant_id,
                    external_user_id,
                    client_id,
                    external_app_id,
                    event_id,
                    reason,
                    event_version,
                ),
            )
            if client_id:
                await c.execute(
                    "DELETE FROM eduplus2.resolve_cache WHERE tenant_id=%s AND client_id=%s",
                    (self.identity.tenant_id, client_id),
                )
            if target_kind in {"permission", "user", "client", "app", "tenant", "subscription"}:
                await c.execute(
                    """
                    UPDATE eduplus2.permission_snapshots
                       SET allowed=false, reason=%s, updated_at=now()
                     WHERE tenant_id=%s
                       AND (%s='' OR external_tenant_id=%s)
                       AND (%s='' OR external_user_id=%s)
                       AND (%s='' OR client_id=%s)
                       AND (%s='' OR external_app_id=%s)
                    """,
                    (
                        reason,
                        self.identity.tenant_id,
                        external_tenant_id,
                        external_tenant_id,
                        external_user_id,
                        external_user_id,
                        client_id,
                        client_id,
                        external_app_id,
                        external_app_id,
                    ),
                )
            await self._audit(
                c,
                event_kind="revocation.apply",
                result="success",
                reason=reason,
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_app_id=external_app_id,
                external_user_id=external_user_id,
                policy_version=event_version,
                summary=summary,
            )
        return {"status": "applied", "event_id": event_id, "target_kind": target_kind}

    @staticmethod
    def _audit_filters(filters: dict) -> tuple[str, list]:
        clauses = []
        values = []
        for column in (
            "event_kind",
            "client_id",
            "external_tenant_id",
            "external_app_id",
            "external_user_id",
            "internal_user_id",
            "result",
            "request_id",
        ):
            value = str(filters.get(column) or "").strip()
            if value:
                clauses.append(f"{column}=%s")
                values.append(value)
        return (" AND ".join(clauses), values)

    @staticmethod
    def _audit_row(row) -> dict:
        summary = row["summary"]
        if not isinstance(summary, dict):
            summary = dict(summary or {})
        return {
            "id": str(row["id"]),
            "request_id": row["request_id"],
            "event_kind": row["event_kind"],
            "actor_id": row["actor_id"],
            "client_id": row["client_id"],
            "external_tenant_id": row["external_tenant_id"],
            "external_app_id": row["external_app_id"],
            "external_user_id": row["external_user_id"],
            "internal_user_id": row["internal_user_id"],
            "session_id": row["session_id"],
            "turn_id": row["turn_id"],
            "result": row["result"],
            "reason": row["reason"],
            "policy_version": row["policy_version"],
            "summary": summary,
            "created_at": row["created_at"].isoformat(),
        }

    async def query_audit_events(self, filters: dict, *, limit: int = 100) -> dict:
        limit = max(1, min(int(limit or 100), 500))
        where, values = self._audit_filters(filters)
        sql = "SELECT * FROM eduplus2.audit_events WHERE tenant_id=%s"
        params = [self.identity.tenant_id]
        if where:
            sql += " AND " + where
            params.extend(values)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        async with self.db.transaction(self._scope) as c:
            rows = await (await c.execute(sql, tuple(params))).fetchall()
        return {"items": [self._audit_row(row) for row in rows], "limit": limit}

    @staticmethod
    def _render_audit_export(items: list[dict], export_format: str) -> str:
        if export_format == "jsonl":
            return "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items)
        output = io.StringIO()
        fieldnames = [
            "created_at",
            "event_kind",
            "request_id",
            "client_id",
            "external_tenant_id",
            "external_app_id",
            "external_user_id",
            "internal_user_id",
            "session_id",
            "result",
            "reason",
            "policy_version",
            "summary",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            row = dict(item)
            row["summary"] = json.dumps(row.get("summary") or {}, ensure_ascii=False, sort_keys=True)
            writer.writerow(row)
        return output.getvalue()

    async def create_audit_export(
        self,
        filters: dict,
        *,
        export_format: str,
        actor_id: str,
    ) -> dict:
        export_format = str(export_format or "jsonl").lower()
        if export_format not in {"jsonl", "csv"}:
            raise ValueError("unsupported audit export format")
        result = await self.query_audit_events(filters, limit=int(filters.get("limit") or 1000))
        items = result["items"]
        content = self._render_audit_export(items, export_format)
        job_id = str(uuid.uuid4())
        file_ref = f"{self.audit_export_storage_ref}/{job_id}.{export_format}"
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        async with self.db.transaction(self._scope) as c:
            await c.execute(
                """
                INSERT INTO eduplus2.audit_export_jobs(
                  tenant_id,id,requested_by,format,status,filter_snapshot,row_count,
                  file_ref,export_content,completed_at,expires_at
                ) VALUES(%s,%s,%s,%s,'completed',%s,%s,%s,%s,now(),%s)
                """,
                (
                    self.identity.tenant_id,
                    job_id,
                    actor_id,
                    export_format,
                    Jsonb(filters),
                    len(items),
                    file_ref,
                    content,
                    expires_at,
                ),
            )
            await self._audit(
                c,
                event_kind="audit.export",
                result="success",
                reason="completed",
                actor_id=actor_id,
                summary={
                    "format": export_format,
                    "row_count": len(items),
                    "file_ref": file_ref,
                    "filters": filters,
                },
            )
        return {
            "id": job_id,
            "status": "completed",
            "format": export_format,
            "row_count": len(items),
            "file_ref": file_ref,
            "expires_at": expires_at.isoformat(),
            "preview": content[:1000],
        }

    async def record_refresh_audit(
        self,
        token: str,
        *,
        request_id: str,
        reason: str,
        result: str = "success",
    ) -> None:
        claims = jwt.get_unverified_claims(token)
        eduplus2 = claims.get("eduplus2")
        if not isinstance(eduplus2, dict):
            return
        async with self.db.transaction(self._scope) as c:
            await self._audit(
                c,
                event_kind="token.refresh",
                result=result,
                reason=reason,
                request_id=request_id,
                client_id=str(eduplus2.get("azp") or ""),
                external_tenant_id=str(eduplus2.get("external_tenant_id") or ""),
                external_app_id=str(eduplus2.get("external_app_id") or ""),
                external_user_id=str(eduplus2.get("external_user_id") or ""),
                internal_user_id=str(claims.get("sub") or ""),
                session_id=str(claims.get("sid") or ""),
                policy_version=str(eduplus2.get("permission_version") or ""),
                summary={
                    "expires_at": int(claims.get("exp") or 0),
                    "proof": reason,
                },
            )

    @staticmethod
    def _normalized_resolve(client_id: str, resolved: dict) -> dict:
        value = dict(resolved)
        value.setdefault("client_id", client_id)
        value.setdefault("external_tenant_name", "")
        value.setdefault("external_app_name", "")
        value.setdefault("policy", {})
        value.setdefault("version", "")
        missing = [
            key
            for key in ("client_id", "external_tenant_id", "external_app_id", "status")
            if not value.get(key)
        ]
        if missing:
            raise ValueError("resolve response missing required fields")
        if value["client_id"] != client_id:
            raise PermissionError("resolved client id mismatch")
        return value

    @staticmethod
    def _is_active(resolved: dict) -> bool:
        status = str(resolved.get("status") or "").lower()
        subscription = str(resolved.get("subscription_status") or "active").lower()
        tenant_status = str(resolved.get("tenant_status") or "active").lower()
        app_status = str(resolved.get("app_status") or "active").lower()
        return all(
            value in _ACTIVE_VALUES for value in (status, subscription, tenant_status, app_status)
        )

    async def _resolve(
        self,
        client_id: str,
        c=None,
        *,
        request_id: str = "",
        external_user_id: str = "",
    ) -> dict:
        if c is not None and self.resolve_cache_seconds > 0:
            cached = await (
                await c.execute(
                    """
                    SELECT resolved FROM eduplus2.resolve_cache
                     WHERE tenant_id=%s AND client_id=%s AND expires_at>now()
                    """,
                    (self.identity.tenant_id, client_id),
                )
            ).fetchone()
            if cached:
                return self._normalized_resolve(client_id, dict(cached["resolved"]))
        try:
            raw = await self.resolver.resolve_client(client_id)
        except LookupError as exc:
            if c is not None:
                await self._audit(
                    c,
                    event_kind="resolve",
                    result="denied",
                    reason="client_not_found",
                    request_id=request_id,
                    client_id=client_id,
                    external_user_id=external_user_id,
                )
            raise PermissionError("azp is not registered") from exc
        resolved = self._normalized_resolve(client_id, raw)
        if not self._is_active(resolved):
            if c is not None:
                await self._audit(
                    c,
                    event_kind="resolve",
                    result="denied",
                    reason="client_or_tenant_inactive",
                    request_id=request_id,
                    client_id=client_id,
                    external_tenant_id=str(resolved.get("external_tenant_id") or ""),
                    external_app_id=str(resolved.get("external_app_id") or ""),
                    external_user_id=external_user_id,
                    policy_version=str(resolved.get("version") or ""),
                )
            raise PermissionError("client/app/tenant is inactive")
        if c is not None and self.resolve_cache_seconds > 0:
            await c.execute(
                """
                INSERT INTO eduplus2.resolve_cache(
                  tenant_id,client_id,resolved,resolve_version,expires_at,updated_at
                ) VALUES(%s,%s,%s,%s,%s,now())
                ON CONFLICT (tenant_id,client_id) DO UPDATE
                   SET resolved=EXCLUDED.resolved,
                       resolve_version=EXCLUDED.resolve_version,
                       expires_at=EXCLUDED.expires_at,
                       updated_at=now()
                """,
                (
                    self.identity.tenant_id,
                    client_id,
                    Jsonb(resolved),
                    str(resolved.get("version") or ""),
                    datetime.now(timezone.utc) + timedelta(seconds=self.resolve_cache_seconds),
                ),
            )
        if c is not None:
            await self._audit(
                c,
                event_kind="resolve",
                result="success",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=str(resolved.get("external_tenant_id") or ""),
                external_app_id=str(resolved.get("external_app_id") or ""),
                external_user_id=external_user_id,
                policy_version=str(resolved.get("version") or ""),
                summary={
                    "reason": str(resolved.get("reason") or "ok"),
                    "tenant_status": str(resolved.get("tenant_status") or ""),
                    "app_status": str(resolved.get("app_status") or ""),
                    "subscription_status": str(resolved.get("subscription_status") or ""),
                },
            )
        return resolved

    async def _find_registration(self, c, client_id: str):
        return await (
            await c.execute(
                """
                SELECT * FROM eduplus2.external_client_registrations
                 WHERE tenant_id=%s AND client_id=%s
                 ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, updated_at DESC
                 LIMIT 1
                """,
                (self.identity.tenant_id, client_id),
            )
        ).fetchone()

    def _allowed_client(self, client_id: str) -> dict:
        allowed = self.allowed_clients.get(client_id)
        if not allowed or allowed.get("status") != "active":
            raise PermissionError("azp is not registered")
        if allowed.get("internal_tenant_id") != self.identity.tenant_id:
            raise PermissionError("azp is not registered")
        if allowed.get("source") not in _AUTO_REGISTRATION_SOURCES:
            raise PermissionError("azp is not registered")
        if not allowed.get("external_tenant_id"):
            raise PermissionError("azp is not registered")
        return allowed

    async def _ensure_registration(
        self,
        c,
        *,
        client_id: str,
        external_tenant_id: str,
        external_user_id: str,
        request_id: str,
        token_hash: str,
        token_kid: str,
    ) -> tuple[dict, dict]:
        registration = await self._find_registration(c, client_id)
        if registration and registration["status"] != "active":
            await self._audit(
                c,
                event_kind="token.exchange",
                result="denied",
                reason="registration_inactive",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_user_id=external_user_id,
                summary={"token_hash": token_hash, "kid": token_kid},
            )
            raise PermissionError("azp is not registered")
        if registration:
            resolved = await self._resolve(
                client_id,
                c,
                request_id=request_id,
                external_user_id=external_user_id,
            )
            return dict(registration), resolved
        try:
            allowed = self._allowed_client(client_id)
        except PermissionError:
            await self._audit(
                c,
                event_kind="token.exchange",
                result="denied",
                reason="azp_unregistered",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_user_id=external_user_id,
                summary={"token_hash": token_hash, "kid": token_kid},
            )
            raise
        await c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"eduplus2:{client_id}",))
        registration = await self._find_registration(c, client_id)
        if registration and registration["status"] != "active":
            raise PermissionError("azp is not registered")
        if registration:
            resolved = await self._resolve(
                client_id,
                c,
                request_id=request_id,
                external_user_id=external_user_id,
            )
            return dict(registration), resolved
        resolved = await self._resolve(
            client_id,
            c,
            request_id=request_id,
            external_user_id=external_user_id,
        )
        expected_app_id = allowed.get("external_app_id") or ""
        if (
            external_tenant_id != allowed["external_tenant_id"]
            or external_tenant_id != resolved["external_tenant_id"]
            or (expected_app_id and expected_app_id != resolved["external_app_id"])
        ):
            await self._audit(
                c,
                event_kind="registration.upsert",
                result="denied",
                reason="tenant_or_app_mismatch",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_app_id=str(resolved.get("external_app_id") or ""),
                external_user_id=external_user_id,
                policy_version=str(resolved.get("version") or ""),
                summary={
                    "expected_tenant_id": allowed["external_tenant_id"],
                    "expected_app_id": expected_app_id,
                    "token_hash": token_hash,
                    "kid": token_kid,
                },
            )
            raise PermissionError("tenant mismatch")
        existing = await (
            await c.execute(
                """
                SELECT client_id FROM eduplus2.external_client_registrations
                 WHERE status='active' AND provider='eduplus2'
                   AND external_tenant_id=%s AND external_app_id=%s
                 LIMIT 1
                """,
                (resolved["external_tenant_id"], resolved["external_app_id"]),
            )
        ).fetchone()
        if existing:
            await self._audit(
                c,
                event_kind="registration.upsert",
                result="denied",
                reason="active_registration_exists",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=resolved["external_tenant_id"],
                external_app_id=resolved["external_app_id"],
                external_user_id=external_user_id,
                policy_version=str(resolved.get("version") or ""),
            )
            raise ValueError("active registration already exists")
        registration_id = str(uuid.uuid4())
        await c.execute(
            """
            INSERT INTO eduplus2.external_client_registrations(
              tenant_id,id,client_id,external_tenant_id,external_tenant_name,
              external_app_id,external_app_name,internal_tenant_id,registered_by_surface,
              status,resolve_version,policy_snapshot,created_by,updated_by
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s)
            """,
            (
                self.identity.tenant_id,
                registration_id,
                client_id,
                resolved["external_tenant_id"],
                resolved.get("external_tenant_name", ""),
                resolved["external_app_id"],
                resolved.get("external_app_name", ""),
                self.identity.tenant_id,
                allowed["source"],
                str(resolved.get("version") or ""),
                Jsonb(resolved.get("policy") or {}),
                allowed["source"],
                allowed["source"],
            ),
        )
        await self._audit(
            c,
            event_kind="registration.upsert",
            result="success",
            reason="allowlist",
            request_id=request_id,
            client_id=client_id,
            external_tenant_id=resolved["external_tenant_id"],
            external_app_id=resolved["external_app_id"],
            external_user_id=external_user_id,
            policy_version=str(resolved.get("version") or ""),
            summary={"source": allowed["source"], "token_hash": token_hash, "kid": token_kid},
        )
        registration = await self._find_registration(c, client_id)
        return dict(registration), resolved

    async def register_client(
        self,
        token: str,
        client_id: str,
        *,
        surface: str,
        expected_tenant_id: str | None = None,
    ) -> dict:
        actor = await self.identity.authenticate(token)
        if surface == "tms":
            if actor.role != "tenant_admin":
                async with self.db.transaction(self._scope) as c:
                    await self._audit(
                        c,
                        event_kind="client.register",
                        result="denied",
                        reason="role",
                        actor_id=actor.user_id,
                        client_id=client_id,
                    )
                raise PermissionError("tenant administrator required")
        elif surface == "oms":
            # 当前 core role model 尚未交付 platform_operator/auditor；fail closed。
            async with self.db.transaction(self._scope) as c:
                await self._audit(
                    c,
                    event_kind="client.register",
                    result="denied",
                    reason="oms_not_configured",
                    actor_id=actor.user_id,
                    client_id=client_id,
                )
            raise PermissionError("OMS platform capability is not configured")
        else:
            raise ValueError("unsupported registration surface")
        resolved = await self._resolve(str(client_id).strip())
        if expected_tenant_id and resolved["external_tenant_id"] != expected_tenant_id:
            async with self.db.transaction(self._scope) as c:
                await self._audit(
                    c,
                    event_kind="client.register",
                    result="denied",
                    reason="tenant_mismatch",
                    actor_id=actor.user_id,
                    client_id=client_id,
                    external_tenant_id=resolved.get("external_tenant_id", ""),
                    external_app_id=resolved.get("external_app_id", ""),
                    policy_version=str(resolved.get("version") or ""),
                )
            raise PermissionError("tenant mismatch")
        registration_id = str(uuid.uuid4())
        async with self.db.transaction(self._scope) as c:
            existing = await (
                await c.execute(
                    """
                    SELECT client_id FROM eduplus2.external_client_registrations
                     WHERE status='active' AND (
                       client_id=%s OR (provider='eduplus2' AND external_tenant_id=%s AND external_app_id=%s)
                     )
                     LIMIT 1
                    """,
                    (client_id, resolved["external_tenant_id"], resolved["external_app_id"]),
                )
            ).fetchone()
            if existing:
                await self._audit(
                    c,
                    event_kind="client.register",
                    result="denied",
                    reason="active_registration_exists",
                    actor_id=actor.user_id,
                    client_id=client_id,
                    external_tenant_id=resolved["external_tenant_id"],
                    external_app_id=resolved["external_app_id"],
                    policy_version=str(resolved.get("version") or ""),
                )
                raise ValueError("active registration already exists")
            await c.execute(
                """
                INSERT INTO eduplus2.external_client_registrations(
                  tenant_id,id,client_id,external_tenant_id,external_tenant_name,
                  external_app_id,external_app_name,internal_tenant_id,registered_by_surface,
                  status,resolve_version,policy_snapshot,created_by,updated_by
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s)
                """,
                (
                    self.identity.tenant_id,
                    registration_id,
                    client_id,
                    resolved["external_tenant_id"],
                    resolved.get("external_tenant_name", ""),
                    resolved["external_app_id"],
                    resolved.get("external_app_name", ""),
                    self.identity.tenant_id,
                    surface,
                    str(resolved.get("version") or ""),
                    Jsonb(resolved.get("policy") or {}),
                    actor.user_id,
                    actor.user_id,
                ),
            )
            await self._audit(
                c,
                event_kind="client.register",
                result="success",
                actor_id=actor.user_id,
                client_id=client_id,
                external_tenant_id=resolved["external_tenant_id"],
                external_app_id=resolved["external_app_id"],
                policy_version=str(resolved.get("version") or ""),
                summary={"surface": surface},
            )
        return {
            "id": registration_id,
            "client_id": client_id,
            "external_tenant_id": resolved["external_tenant_id"],
            "external_app_id": resolved["external_app_id"],
            "status": "active",
        }

    async def _verified_claims(self, token: str) -> VerifiedEduPlus2Jwt:
        return await self.jwt_verifier.verify(token)

    @staticmethod
    def _external_user_id(claims: dict) -> str:
        return str(claims["eui"]).strip()

    @staticmethod
    def _internal_user_id(external_tenant_id: str, external_user_id: str) -> str:
        digest = hashlib.sha256(
            f"eduplus2:{external_tenant_id}:{external_user_id}".encode()
        ).hexdigest()
        return "eduplus2:" + digest[:48]

    async def exchange_user_jwt(self, token: str, *, request_id: str = "") -> dict:
        verified = await self._verified_claims(token)
        claims = verified.claims
        client_id = str(claims["azp"]).strip()
        external_tenant_id = str(claims["tid"]).strip()
        external_user_id = self._external_user_id(claims)
        token_hash = verified.token_hash
        token_kid = str(verified.header.get("kid") or "")
        async with self.db.transaction(self._scope) as c:
            await self._enforce_exchange_replay_and_rate_limit(
                c,
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_user_id=external_user_id,
                token_hash=token_hash,
                token_kid=token_kid,
            )
            registration, resolved = await self._ensure_registration(
                c,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_user_id=external_user_id,
                request_id=request_id,
                token_hash=token_hash,
                token_kid=token_kid,
            )
            if (
                external_tenant_id != registration["external_tenant_id"]
                or external_tenant_id != resolved["external_tenant_id"]
                or registration["external_app_id"] != resolved["external_app_id"]
            ):
                await self._audit(
                    c,
                    event_kind="token.exchange",
                    result="denied",
                    reason="tenant_mismatch",
                    request_id=request_id,
                    client_id=client_id,
                    external_tenant_id=external_tenant_id,
                    external_app_id=registration["external_app_id"],
                    external_user_id=external_user_id,
                    policy_version=registration["resolve_version"],
                    summary={"token_hash": token_hash, "kid": token_kid},
                )
                raise PermissionError("tenant mismatch")
            await self._ensure_not_revoked(
                c,
                external_tenant_id=external_tenant_id,
                external_user_id=external_user_id,
                client_id=client_id,
                external_app_id=str(resolved.get("external_app_id") or ""),
            )
            profile = await self._fetch_profile(
                c,
                claims=claims,
                client_id=client_id,
                resolved=resolved,
                request_id=request_id,
                token_hash=token_hash,
                token_kid=token_kid,
            )
            permission = await self._check_permission(
                c,
                claims=claims,
                client_id=client_id,
                registration=registration,
                resolved=resolved,
                request_id=request_id,
                token_hash=token_hash,
                token_kid=token_kid,
            )
            binding = await (
                await c.execute(
                    """
                    SELECT * FROM eduplus2.identity_bindings
                     WHERE tenant_id=%s AND provider='eduplus2' AND external_tenant_id=%s AND external_user_id=%s
                    """,
                    (self.identity.tenant_id, external_tenant_id, external_user_id),
                )
            ).fetchone()
            if binding and binding["status"] != "active":
                await self._audit(
                    c,
                    event_kind="token.exchange",
                    result="denied",
                    reason="binding_inactive",
                    request_id=request_id,
                    client_id=client_id,
                    external_tenant_id=external_tenant_id,
                    external_app_id=registration["external_app_id"],
                    external_user_id=external_user_id,
                )
                raise PermissionError("identity binding is inactive")
            internal_user_id = (
                binding["internal_user_id"]
                if binding
                else self._internal_user_id(external_tenant_id, external_user_id)
            )
            external_subject = str(
                (profile or {}).get("external_subject") or claims.get("sub") or ""
            )
            external_identity_type = str(
                (profile or {}).get("external_identity_type") or claims.get("eit") or ""
            )
            if not binding:
                username = external_user_id[:128]
                if await (
                    await c.execute(
                        "SELECT 1 FROM enterprise.users WHERE tenant_id=%s AND username=%s",
                        (self.identity.tenant_id, username),
                    )
                ).fetchone():
                    username = (external_user_id[:118] + "#" + internal_user_id[-8:])[:128]
                await c.execute(
                    """
                    INSERT INTO enterprise.users(tenant_id,id,username,role,preset)
                    VALUES(%s,%s,%s,'user','standard')
                    """,
                    (self.identity.tenant_id, internal_user_id, username),
                )
                await c.execute(
                    """
                    INSERT INTO eduplus2.identity_bindings(
                      tenant_id,external_tenant_id,external_user_id,external_subject,
                      external_identity_type,internal_user_id,last_client_registration_id
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        self.identity.tenant_id,
                        external_tenant_id,
                        external_user_id,
                        external_subject,
                        external_identity_type,
                        internal_user_id,
                        registration["id"],
                    ),
                )
            else:
                await c.execute(
                    """
                    UPDATE eduplus2.identity_bindings
                       SET external_subject=%s, external_identity_type=%s,
                           last_client_registration_id=%s, updated_at=now()
                     WHERE tenant_id=%s AND provider='eduplus2' AND external_tenant_id=%s AND external_user_id=%s
                    """,
                    (
                        external_subject,
                        external_identity_type,
                        registration["id"],
                        self.identity.tenant_id,
                        external_tenant_id,
                        external_user_id,
                    ),
                )
            row = await (
                await c.execute(
                    """
                    SELECT u.* FROM enterprise.users u JOIN enterprise.tenants t ON t.id=u.tenant_id
                     WHERE u.tenant_id=%s AND u.id=%s AND NOT u.disabled AND u.deleted_at IS NULL
                       AND t.local_enabled AND t.external_eligibility IN ('not_required','allowed')
                       AND t.provisioning_status='ready' AND t.auth_epoch=%s
                     FOR UPDATE OF u,t
                    """,
                    (self.identity.tenant_id, internal_user_id, self.identity.epoch),
                )
            ).fetchone()
            if not row:
                await self._audit(
                    c,
                    event_kind="token.exchange",
                    result="denied",
                    reason="user_or_tenant_inactive",
                    request_id=request_id,
                    client_id=client_id,
                    external_tenant_id=external_tenant_id,
                    external_app_id=registration["external_app_id"],
                    external_user_id=external_user_id,
                    internal_user_id=internal_user_id,
                )
                raise PermissionError("user or tenant is inactive")
            token_extra = {
                "eduplus2": {
                    "client_registration_id": str(registration["id"]),
                    "external_tenant_id": external_tenant_id,
                    "external_app_id": registration["external_app_id"],
                    "external_user_id": external_user_id,
                    "azp": client_id,
                }
            }
            if permission is not None:
                token_extra["eduplus2"]["allowed_usages"] = self._ordinary_usages(
                    permission.get("allowed_usages") or []
                )
                token_extra["eduplus2"]["permission_version"] = str(
                    permission.get("version") or ""
                )
            dt_token = await self.identity._issue_session(  # core seam: extra claims + shorter TTL
                c,
                row,
                extra_claims=token_extra,
                token_seconds=self.dt_token_seconds,
            )
            session_id = jwt.get_unverified_claims(dt_token)["sid"]
            await self._audit(
                c,
                event_kind="token.exchange",
                result="success",
                request_id=request_id,
                client_id=client_id,
                external_tenant_id=external_tenant_id,
                external_app_id=registration["external_app_id"],
                external_user_id=external_user_id,
                internal_user_id=internal_user_id,
                session_id=session_id,
                policy_version=registration["resolve_version"],
                summary={"token_hash": token_hash, "kid": token_kid},
            )
        now = int(time.time())
        return ExchangeResult(
            dt_token=dt_token,
            token_type="Bearer",
            expires_in=self.dt_token_seconds,
            expires_at=now + self.dt_token_seconds,
            tenant_id=self.identity.tenant_id,
            user_id=internal_user_id,
            client_registration_id=str(registration["id"]),
        ).to_dict()
