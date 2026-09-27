"""已验签 EduPlus2 事件的学校与生命周期事务投影。"""

from __future__ import annotations

import hmac
from uuid import uuid4

from ..scope import TenantScope
from .lifecycle import LifecycleConflict, LifecycleEvent, LifecycleInvalid

_ACTIVE = frozenset({"active", "subscribed"})
_INACTIVE = frozenset({"suspended", "terminated", "expired", "inactive", "cancelled"})


async def snapshot_webhook_authority_metrics(enterprise) -> dict[str, int]:
    """只返回聚合量；久未投递是诊断信号，不能证明外部状态已改变。"""

    owner = enterprise.deployment.tenant_id
    app_id = int(getattr(enterprise, "eduplus2_webhook_app_id", 0) or 0)
    async with enterprise.db.transaction(TenantScope(str(owner), "@webhook-metrics")) as c:
        inbox = await (
            await c.execute(
                "SELECT count(*) AS stored_events,"
                "count(*) FILTER (WHERE processed_at IS NOT NULL) AS accepted_events,"
                "count(*) FILTER (WHERE processing_status IN "
                "('pending_binding','pending_reconcile','reconciling','retry')) "
                "AS legacy_pending_events,"
                "count(*) FILTER (WHERE last_error_code='school_not_bound') "
                "AS unbound_events FROM eduplus2.lifecycle_inbox "
                "WHERE tenant_id=%s AND external_app_id=%s",
                (owner, app_id),
            )
        ).fetchone()
        schools = await (
            await c.execute(
                "SELECT count(*) FILTER (WHERE p.eligibility='allowed') AS allowed_schools,"
                "count(*) FILTER (WHERE p.eligibility='denied') AS denied_schools,"
                "count(*) FILTER (WHERE p.eligibility='unknown') AS unknown_schools,"
                "count(*) FILTER (WHERE p.onboarding_completed_at IS NOT NULL) "
                "AS onboarded_schools,"
                "count(*) FILTER (WHERE k.frozen) AS frozen_schools,"
                "count(*) FILTER (WHERE p.updated_at<clock_timestamp()-interval '30 days') "
                "AS quiet_schools FROM eduplus2.webhook_school_state p "
                "LEFT JOIN eduplus2.webhook_school_controls k "
                "ON (k.tenant_id,k.school_id,k.external_app_id)="
                "(p.tenant_id,p.school_id,p.external_app_id) "
                "WHERE p.tenant_id=%s AND p.external_app_id=%s",
                (owner, app_id),
            )
        ).fetchone()
        actors = await (
            await c.execute(
                "SELECT count(*) AS pending_actors FROM eduplus2.lifecycle_actor_candidates "
                "WHERE tenant_id=%s AND external_app_id=%s AND status='pending_verification'",
                (owner, app_id),
            )
        ).fetchone()
    return {key: int(value) for row in (inbox, schools, actors) for key, value in row.items()}


def _eligibility(event: LifecycleEvent) -> str:
    status = event.subscription_status.lower()
    if event.event_type in {
        "subscription.suspended",
        "subscription.terminated",
        "subscription.expired",
    }:
        return "denied" if status in _INACTIVE else "unknown"
    if status in _ACTIVE:
        return "allowed"
    if status in _INACTIVE:
        return "denied"
    return "unknown"


async def ingest_authoritative_webhook(
    enterprise, event: LifecycleEvent, *, delivery_timestamp: int
):
    """事务内按接收顺序建校、投影和交接 actor；不调用 online resolve。"""

    digest_key = str(getattr(enterprise, "eduplus2_webhook_inbox_digest_key", "") or "")
    signing_secrets = (
        str(getattr(enterprise, "eduplus2_webhook_secret", "") or ""),
        str(getattr(enterprise, "eduplus2_webhook_previous_secret", "") or ""),
    )
    if digest_key and any(
        secret and hmac.compare_digest(digest_key, secret) for secret in signing_secrets
    ):
        raise RuntimeError("inbox integrity key must be independent")
    if event.event_type == "subscription.created" and not event.client_id:
        raise LifecycleInvalid("created event has no application client")
    owner = enterprise.deployment.tenant_id
    scope = TenantScope(str(owner), "@eduplus2-webhook")
    target_key = f"deeptutor-webhook:{event.external_tenant_id}:{event.external_app_id}"
    async with enterprise.db.transaction(scope) as c:
        await c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (target_key,))
        if event.client_id:
            # 先锁 client 再核对历史归属，避免并发的两个学校抢占同一 OAuth client。
            await c.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("deeptutor-webhook-client:" + event.client_id,),
            )
            conflicting_client = await (
                await c.execute(
                    "SELECT 1 FROM eduplus2.external_client_registrations "
                    "WHERE client_id=%s AND (external_tenant_id<>%s OR external_app_id<>%s) "
                    "LIMIT 1",
                    (event.client_id, str(event.external_tenant_id), str(event.external_app_id)),
                )
            ).fetchone()
            if conflicting_client:
                raise LifecycleConflict("client belongs to another school target")
        inserted = await (
            await c.execute(
                "INSERT INTO eduplus2.lifecycle_inbox(tenant_id,event_id,semantic_digest,"
                "event_type,external_tenant_id,external_app_id,external_subscription_id,"
                "subscription_status,client_id,actor_subject,actor_type,delivery_timestamp) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id,event_id) DO NOTHING RETURNING event_id",
                (
                    owner,
                    event.event_id,
                    event.semantic_digest,
                    event.event_type,
                    event.external_tenant_id,
                    event.external_app_id,
                    event.external_subscription_id,
                    event.subscription_status,
                    event.client_id,
                    event.actor_subject,
                    event.actor_type,
                    delivery_timestamp,
                ),
            )
        ).fetchone()
        if not inserted:
            previous = await (
                await c.execute(
                    "SELECT semantic_digest FROM eduplus2.lifecycle_inbox "
                    "WHERE tenant_id=%s AND event_id=%s",
                    (owner, event.event_id),
                )
            ).fetchone()
            if not previous or not hmac.compare_digest(
                previous["semantic_digest"], event.semantic_digest
            ):
                raise LifecycleConflict("event id carries different business facts")
            return "duplicate"

        binding = await (
            await c.execute(
                "SELECT b.tenant_id,b.status,b.version,t.external_tid "
                "FROM oms.school_bindings b JOIN enterprise.tenants t ON t.id=b.tenant_id "
                "WHERE b.eduplus_tenant_id=%s FOR UPDATE OF b,t",
                (event.external_tenant_id,),
            )
        ).fetchone()
        if binding is None and event.event_type == "subscription.created":
            legacy_school = await (
                await c.execute(
                    "SELECT id FROM enterprise.tenants WHERE external_tid=%s FOR UPDATE",
                    (str(event.external_tenant_id),),
                )
            ).fetchone()
            if legacy_school:
                raise LifecycleConflict("external school already exists without signed binding")
            school_id = uuid4()
            # 新学校仍是待初始化状态；不能因 Webhook 2xx 获得业务或管理权限。
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_id),))
            await c.execute(
                "INSERT INTO enterprise.tenants(id,external_tid,external_eligibility,"
                "local_enabled,provisioning_status,auth_epoch) "
                "VALUES(%s,%s,'denied',false,'pending',%s)",
                (school_id, str(event.external_tenant_id), enterprise.identity.epoch),
            )
            await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(owner),))
            await c.execute(
                "INSERT INTO oms.school_bindings(tenant_id,eduplus_tenant_id,status,"
                "verified_at,verified_by,source_ref) "
                "VALUES(%s,%s,'verified',clock_timestamp(),'@signed-webhook',%s)",
                (school_id, event.external_tenant_id, event.event_id),
            )
            binding = {
                "tenant_id": school_id,
                "status": "verified",
                "version": 1,
                "external_tid": str(event.external_tenant_id),
            }
        if binding is None:
            # 非 created 事件不能建校；已确认投递不能遗留永不完成的本地 pending。
            await c.execute(
                "UPDATE eduplus2.lifecycle_inbox SET processing_status='denied',"
                "last_error_code='school_not_bound',processed_at=clock_timestamp() "
                "WHERE tenant_id=%s AND event_id=%s",
                (owner, event.event_id),
            )
            return "unbound"
        if (
            binding["external_tid"] != str(event.external_tenant_id)
            or binding["status"] != "verified"
        ):
            raise LifecycleConflict("school binding conflicts with signed target")

        school_id = binding["tenant_id"]
        eligibility = _eligibility(event)
        projected = await (
            await c.execute(
                "INSERT INTO eduplus2.webhook_school_state(tenant_id,external_tenant_id,"
                "external_app_id,school_id,school_code,binding_version,eligibility,"
                "external_subscription_id,last_event_id,onboarding_event_id,"
                "onboarding_completed_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "CASE WHEN %s THEN clock_timestamp() ELSE NULL END) "
                "ON CONFLICT (tenant_id,external_tenant_id,external_app_id) DO UPDATE "
                "SET generation=eduplus2.webhook_school_state.generation+1,"
                "school_code=CASE WHEN EXCLUDED.school_code<>'' THEN EXCLUDED.school_code "
                "ELSE eduplus2.webhook_school_state.school_code END,"
                "binding_version=EXCLUDED.binding_version,"
                "eligibility=EXCLUDED.eligibility,"
                "external_subscription_id=EXCLUDED.external_subscription_id,"
                "last_event_id=EXCLUDED.last_event_id,updated_at=clock_timestamp() "
                " ,onboarding_event_id=COALESCE(EXCLUDED.onboarding_event_id,"
                "eduplus2.webhook_school_state.onboarding_event_id),"
                "onboarding_completed_at=COALESCE(EXCLUDED.onboarding_completed_at,"
                "eduplus2.webhook_school_state.onboarding_completed_at) "
                "WHERE eduplus2.webhook_school_state.school_id=EXCLUDED.school_id "
                "RETURNING generation",
                (
                    owner,
                    event.external_tenant_id,
                    event.external_app_id,
                    school_id,
                    event.school_code,
                    binding["version"],
                    eligibility,
                    event.external_subscription_id,
                    event.event_id,
                    event.event_id if event.event_type == "subscription.created" else None,
                    event.event_type == "subscription.created",
                ),
            )
        ).fetchone()
        if not projected:
            raise LifecycleConflict("projected school differs from signed target")
        if event.event_type == "subscription.created":
            await c.execute(
                "INSERT INTO eduplus2.webhook_school_controls(tenant_id,school_id,external_app_id) "
                "VALUES(%s,%s,%s) ON CONFLICT (tenant_id,school_id,external_app_id) "
                "DO NOTHING",
                (owner, school_id, event.external_app_id),
            )
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_id),))
        await c.execute(
            "UPDATE enterprise.tenants SET external_eligibility=%s,"
            "external_version=external_version+1 WHERE id=%s AND external_tid=%s "
            "AND external_eligibility<>%s",
            (
                "allowed" if eligibility == "allowed" else "denied",
                school_id,
                str(event.external_tenant_id),
                "allowed" if eligibility == "allowed" else "denied",
            ),
        )
        registration_status = "active" if eligibility == "allowed" else "suspended"
        if event.client_id:
            current_client = await (
                await c.execute(
                    "SELECT id,status FROM eduplus2.external_client_registrations "
                    "WHERE tenant_id=%s AND client_id=%s AND external_tenant_id=%s "
                    "AND external_app_id=%s ORDER BY updated_at DESC LIMIT 1 FOR UPDATE",
                    (
                        school_id,
                        event.client_id,
                        str(event.external_tenant_id),
                        str(event.external_app_id),
                    ),
                )
            ).fetchone()
            await c.execute(
                "UPDATE eduplus2.external_client_registrations SET status='revoked',"
                "revoked_at=clock_timestamp(),revoked_by='@signed-webhook',"
                "updated_at=clock_timestamp() WHERE tenant_id=%s AND external_tenant_id=%s "
                "AND external_app_id=%s AND status='active' AND client_id<>%s",
                (
                    school_id,
                    str(event.external_tenant_id),
                    str(event.external_app_id),
                    event.client_id,
                ),
            )
            if current_client:
                await c.execute(
                    "UPDATE eduplus2.external_client_registrations SET status=%s,"
                    "revoked_at=NULL,revoked_by='',updated_at=clock_timestamp(),"
                    "updated_by='@signed-webhook' WHERE tenant_id=%s AND id=%s",
                    (registration_status, school_id, current_client["id"]),
                )
            else:
                await c.execute(
                    "INSERT INTO eduplus2.external_client_registrations(tenant_id,id,"
                    "client_id,external_tenant_id,external_app_id,internal_tenant_id,"
                    "registered_by_surface,status,created_by,updated_by) "
                    "VALUES(%s,%s,%s,%s,%s,%s,'webhook',%s,'@signed-webhook',"
                    "'@signed-webhook')",
                    (
                        school_id,
                        uuid4(),
                        event.client_id,
                        str(event.external_tenant_id),
                        str(event.external_app_id),
                        school_id,
                        registration_status,
                    ),
                )
        elif registration_status != "active":
            await c.execute(
                "UPDATE eduplus2.external_client_registrations SET status='suspended',"
                "updated_at=clock_timestamp(),updated_by='@signed-webhook' "
                "WHERE tenant_id=%s AND external_tenant_id=%s AND external_app_id=%s "
                "AND status='active'",
                (school_id, str(event.external_tenant_id), str(event.external_app_id)),
            )
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(owner),))
        if (
            event.event_type == "subscription.created"
            and event.actor_type == "user"
            and event.actor_subject
            and enterprise.eduplus2_issuer
        ):
            await c.execute(
                "INSERT INTO eduplus2.lifecycle_actor_candidates(tenant_id,event_id,"
                "school_id,external_tenant_id,external_app_id,external_subscription_id,"
                "binding_version,actor_issuer,actor_subject) "
                "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s "
                "WHERE EXISTS (SELECT 1 FROM enterprise.tenants t "
                "WHERE t.id=%s AND NOT t.bootstrap_completed) "
                "ON CONFLICT (tenant_id,event_id) DO NOTHING",
                (
                    owner,
                    event.event_id,
                    school_id,
                    event.external_tenant_id,
                    event.external_app_id,
                    event.external_subscription_id,
                    binding["version"],
                    enterprise.eduplus2_issuer,
                    event.actor_subject,
                    school_id,
                ),
            )
        await c.execute(
            "UPDATE eduplus2.lifecycle_inbox SET processing_status=%s,processed_at=clock_timestamp() "
            "WHERE tenant_id=%s AND event_id=%s",
            ("verified" if eligibility == "allowed" else "denied", owner, event.event_id),
        )
        return eligibility
