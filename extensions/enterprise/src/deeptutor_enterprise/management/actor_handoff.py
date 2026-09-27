"""已验证 Webhook actor 向 TMS 授权服务的只读候选交接。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..scope import TenantScope
from .authorization import ManagementIdentity, _identity_is_current


@dataclass(frozen=True, slots=True)
class PendingActorCandidate:
    event_id: str
    subscription_id: int
    school_id: UUID
    binding_version: int


async def find_pending_actor_candidates(
    enterprise, identity: ManagementIdentity
) -> tuple[PendingActorCandidate, ...]:
    """只向受信 TMS 本人身份交接候选；不授予角色、不消费引导。

    调用方必须通过可信 TMS 身份适配器构造 ``identity``，不可直接从请求体实例化。
    后续激活服务须在同一写事务内重验全部条件和一次性消费栅栏。
    """

    if (
        not isinstance(identity, ManagementIdentity)
        or identity.application != "tms"
        or not _identity_is_current(identity, write=False)
        or not getattr(enterprise, "eduplus2_lifecycle_receiver_enabled", False)
    ):
        return ()
    app_id = identity.webhook_app_id
    current_issuer = str(getattr(enterprise, "eduplus2_issuer", "") or "").strip()
    if type(app_id) is not int or app_id <= 0 or not current_issuer or identity.issuer != current_issuer:
        return ()
    owner_id = enterprise.deployment.tenant_id
    scope = TenantScope(str(owner_id), "@eduplus2-actor-handoff")
    async with enterprise.db.transaction(scope) as c:
        rows = await (
            await c.execute(
                "SELECT a.event_id,a.external_subscription_id,a.school_id,a.binding_version "
                "FROM eduplus2.lifecycle_actor_candidates a "
                "JOIN oms.school_bindings b ON b.tenant_id=a.school_id "
                "AND b.eduplus_tenant_id=a.external_tenant_id "
                "JOIN enterprise.tenants t ON t.id=a.school_id "
                "AND t.external_tid=a.external_tenant_id::text "
                "JOIN eduplus2.webhook_school_state p ON p.tenant_id=a.tenant_id "
                "AND p.external_tenant_id=a.external_tenant_id "
                "AND p.external_app_id=a.external_app_id "
                "WHERE a.tenant_id=%s AND a.school_id=%s "
                "AND a.external_app_id=%s AND a.actor_issuer=%s "
                "AND a.actor_subject=%s AND a.status='pending_verification' "
                "AND a.binding_version=%s AND b.version=a.binding_version "
                "AND b.status='verified' "
                "AND NOT t.bootstrap_completed "
                "AND t.recovery_state='normal' "
                "AND p.school_id=a.school_id AND p.eligibility='allowed' "
                "AND p.binding_version=b.version "
                "AND p.onboarding_event_id IS NOT NULL "
                "AND p.onboarding_completed_at IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM eduplus2.webhook_school_controls k "
                "WHERE (k.tenant_id,k.school_id,k.external_app_id)="
                "(p.tenant_id,p.school_id,p.external_app_id) AND NOT k.frozen) "
                "ORDER BY a.received_at,a.event_id",
                (
                    owner_id,
                    identity.school_id,
                    app_id,
                    identity.issuer,
                    identity.subject,
                    identity.school_binding_version,
                ),
            )
        ).fetchall()
    return tuple(
        PendingActorCandidate(
            event_id=row["event_id"],
            subscription_id=row["external_subscription_id"],
            school_id=row["school_id"],
            binding_version=row["binding_version"],
        )
        for row in rows
    )
