"""已验签 EduPlus2 事件的学校与生命周期事务投影。"""

from __future__ import annotations

import hmac
from uuid import NAMESPACE_URL, uuid4, uuid5

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.tenant_state import validate_tenant_business_values

from ..management.assignment_rules import validate_assignment_relation
from ..management.authorization import ManagementAuthorizationDenied
from ..management.policy_version import advance_principal_policy_version
from ..scope import TenantScope
from .lifecycle import (
    LifecycleConflict,
    LifecycleEvent,
    LifecycleInvalid,
    validate_lifecycle_actor_candidate_row,
    validate_lifecycle_inbox_row,
    validate_webhook_school_state_row,
)

_ACTIVE = frozenset({"active", "subscribed"})
_INACTIVE = frozenset({"suspended", "terminated", "expired", "inactive", "cancelled"})


async def snapshot_webhook_authority_metrics(enterprise) -> dict[str, int]:
    """只返回聚合量；久未投递是诊断信号，不能证明外部状态已改变。"""

    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@webhook-metrics")) as c:
        inbox_rows = await (
            await c.execute(
                "SELECT processing_status FROM eduplus2.lifecycle_inbox WHERE tenant_id=%s",
                (owner,),
            )
        ).fetchall()
        for row in inbox_rows:
            validate_lifecycle_inbox_row(row)
        projection_rows = await (
            await c.execute(
                "SELECT eligibility,onboarding_event_id,onboarding_completed_at "
                "FROM eduplus2.webhook_school_state WHERE tenant_id=%s",
                (owner,),
            )
        ).fetchall()
        for row in projection_rows:
            validate_webhook_school_state_row(row)
        actor_rows = await (
            await c.execute(
                "SELECT status,resolved_at FROM eduplus2.lifecycle_actor_candidates "
                "WHERE tenant_id=%s",
                (owner,),
            )
        ).fetchall()
        for row in actor_rows:
            validate_lifecycle_actor_candidate_row(row)
        inbox = await (
            await c.execute(
                "SELECT count(*) AS stored_events,"
                "count(*) FILTER (WHERE processed_at IS NOT NULL) AS accepted_events,"
                "count(*) FILTER (WHERE processing_status IN "
                "('pending_binding','pending_reconcile','reconciling','retry')) "
                "AS legacy_pending_events,"
                "count(*) FILTER (WHERE last_error_code='school_not_bound') "
                "AS unbound_events FROM eduplus2.lifecycle_inbox "
                "WHERE tenant_id=%s",
                (owner,),
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
                "WHERE p.tenant_id=%s",
                (owner,),
            )
        ).fetchone()
        actors = await (
            await c.execute(
                "SELECT count(*) AS pending_actors FROM eduplus2.lifecycle_actor_candidates "
                "WHERE tenant_id=%s AND status='pending_verification'",
                (owner,),
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


async def _open_first_school_administrator_from_webhook(
    c,
    enterprise,
    event: LifecycleEvent,
    *,
    owner,
    school_id,
    binding_version: int,
) -> bool:
    """订阅创建事件直接开启学校首位管理员；不再等待 TMS 单独开通。"""

    if (
        event.event_type != "subscription.created"
        or event.actor_type != "user"
        or not event.actor_subject
        or not getattr(enterprise, "eduplus2_issuer", None)
    ):
        return False
    issuer = enterprise.eduplus2_issuer
    command_id = uuid5(NAMESPACE_URL, f"deeptutor:tms:first-admin:{owner}:{event.event_id}")
    try:
        await c.execute("SELECT set_config('app.management_app','tms',true)")
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_id),))
        school = await (
            await c.execute(
                "SELECT bootstrap_completed FROM enterprise.tenants WHERE id=%s FOR UPDATE",
                (school_id,),
            )
        ).fetchone()
        if not school or school["bootstrap_completed"]:
            return False
        existing_admin = await (
            await c.execute(
                "SELECT 1 FROM management.assignments WHERE application='tms' "
                "AND school_id=%s AND role_key='school_admin' AND status='active' "
                "AND valid_from<=now() AND expires_at>now() LIMIT 1",
                (school_id,),
            )
        ).fetchone()
        if existing_admin:
            return False
        principal = await (
            await c.execute(
                "SELECT id,status,policy_version FROM management.principals "
                "WHERE application='tms' AND issuer=%s AND subject=%s AND school_id=%s "
                "FOR UPDATE",
                (issuer, event.actor_subject, school_id),
            )
        ).fetchone()
        if principal and principal["status"] not in {"pending", "active"}:
            raise ManagementAuthorizationDenied("existing management principal is not activatable")
        principal_id = principal["id"] if principal else uuid4()
        expected_policy_version = principal["policy_version"] if principal else 1
        if principal:
            await c.execute(
                "UPDATE management.principals SET status='active',external_evidence_ref=%s,"
                "updated_at=clock_timestamp() WHERE id=%s",
                (event.event_id, principal_id),
            )
        else:
            await c.execute(
                "INSERT INTO management.principals(id,application,issuer,subject,school_id,"
                "status,external_evidence_ref) VALUES(%s,'tms',%s,%s,%s,'active',%s)",
                (principal_id, issuer, event.actor_subject, school_id, event.event_id),
            )
        role = await (
            await c.execute(
                "SELECT application,scope_kind FROM management.role_versions "
                "WHERE application='tms' AND role_key='school_admin' AND version=1 FOR SHARE"
            )
        ).fetchone()
        validate_assignment_relation(
            application="tms",
            principal_application="tms",
            principal_school_id=school_id,
            role_application=role["application"] if role else None,
            role_scope_kind=role["scope_kind"] if role else None,
            assignment_scope_kind="school",
            assignment_school_id=school_id,
        )
        assignment_id = uuid4()
        await c.execute(
            "INSERT INTO management.assignments(id,application,principal_id,role_key,"
            "role_version,scope_kind,school_id,school_binding_version,valid_from,"
            "expires_at,command_id,created_by) "
            "VALUES(%s,'tms',%s,'school_admin',1,'school',%s,%s,"
            "clock_timestamp()-interval '1 second',"
            "timestamptz '9998-01-01 00:00:00+00',%s,'@signed-webhook')",
            (assignment_id, principal_id, school_id, binding_version, command_id),
        )
        delegation_actions = await (
            await c.execute(
                "SELECT ra.action_key FROM management.role_actions ra "
                "JOIN management.action_catalog ac ON ac.application=ra.application "
                "AND ac.action_key=ra.action_key "
                "WHERE ra.application='tms' AND ra.role_key='school_admin' "
                "AND ra.role_version=1 AND ac.status='active' "
                "AND ac.allowed_scope='school' AND NOT ac.sensitive "
                "ORDER BY ra.action_key"
            )
        ).fetchall()
        for row in delegation_actions:
            await c.execute(
                "INSERT INTO management.delegation_policies"
                "(id,application,principal_id,action_key,scope_kind,school_id,valid_from,"
                "expires_at) VALUES(%s,'tms',%s,%s,'school',%s,"
                "clock_timestamp()-interval '1 second',"
                "timestamptz '9998-01-01 00:00:00+00')",
                (uuid4(), principal_id, row["action_key"], school_id),
            )
        next_policy_version = await advance_principal_policy_version(
            c, principal_id, expected_before=expected_policy_version
        )
        await c.execute(
            "UPDATE enterprise.tenants SET bootstrap_completed=true WHERE id=%s",
            (school_id,),
        )
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(owner),))
        await c.execute(
            "INSERT INTO eduplus2.lifecycle_actor_candidates(tenant_id,event_id,"
            "school_id,external_tenant_id,external_app_id,external_subscription_id,"
            "binding_version,actor_issuer,actor_subject,status,resolved_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'consumed',clock_timestamp()) "
            "ON CONFLICT (tenant_id,event_id) DO NOTHING",
            (
                owner,
                event.event_id,
                school_id,
                event.external_tenant_id,
                event.external_app_id,
                event.external_subscription_id,
                binding_version,
                issuer,
                event.actor_subject,
            ),
        )
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_id),))
        await c.execute(
            "INSERT INTO management.audit_events(id,application,school_id,actor_issuer,"
            "actor_subject,action_key,target_kind,target_id,request_id,result,reason,"
            "before_version,after_version,safe_summary) "
            "VALUES(%s,'tms',%s,%s,%s,'tenant.school.bootstrap','school',%s,%s,"
            "'success','signed webhook subscription opened school administrator',%s,%s,%s)",
            (
                uuid4(),
                school_id,
                issuer,
                event.actor_subject,
                str(school_id),
                event.event_id,
                expected_policy_version,
                next_policy_version,
                Jsonb({"event_id": event.event_id, "subscription_id": event.external_subscription_id}),
            ),
        )
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(owner),))
        return True
    except ManagementAuthorizationDenied as exc:
        raise RuntimeError("webhook first school administrator activation failed") from exc


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
                    "SELECT semantic_digest,processing_status FROM eduplus2.lifecycle_inbox "
                    "WHERE tenant_id=%s AND event_id=%s",
                    (owner, event.event_id),
                )
            ).fetchone()
            if previous:
                validate_lifecycle_inbox_row(previous)
            if not previous or not hmac.compare_digest(
                previous["semantic_digest"], event.semantic_digest
            ):
                raise LifecycleConflict("event id carries different business facts")
            return "duplicate"

        binding = await (
            await c.execute(
                "SELECT b.tenant_id,b.status,b.version,t.external_tid,"
                "t.external_eligibility,t.provisioning_status,t.recovery_state "
                "FROM oms.school_bindings b JOIN enterprise.tenants t ON t.id=b.tenant_id "
                "WHERE b.eduplus_tenant_id=%s FOR UPDATE OF b,t",
                (event.external_tenant_id,),
            )
        ).fetchone()
        if binding is not None:
            try:
                validate_tenant_business_values(binding)
            except ValueError as exc:
                # 这是存量数据异常而非发送方事件冲突；保持事务回滚并让发送方重试。
                raise RuntimeError("bound tenant business state is invalid") from exc
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
                "version,verified_at,verified_by,source_ref) "
                "VALUES(%s,%s,'verified',1,clock_timestamp(),'@signed-webhook',%s)",
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
            or type(binding["version"]) is not int
            or binding["version"] < 1
        ):
            raise LifecycleConflict("school binding conflicts with signed target")

        school_id = binding["tenant_id"]
        eligibility = _eligibility(event)
        existing_projection = await (
            await c.execute(
                "SELECT eligibility,onboarding_event_id,onboarding_completed_at "
                "FROM eduplus2.webhook_school_state "
                "WHERE tenant_id=%s AND external_tenant_id=%s AND external_app_id=%s "
                "FOR UPDATE",
                (owner, event.external_tenant_id, event.external_app_id),
            )
        ).fetchone()
        if existing_projection:
            validate_webhook_school_state_row(existing_projection)
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
        projections = await (
            await c.execute(
                "SELECT eligibility,binding_version,onboarding_event_id,onboarding_completed_at "
                "FROM eduplus2.webhook_school_state WHERE tenant_id=%s AND school_id=%s",
                (owner, school_id),
            )
        ).fetchall()
        for row in projections:
            validate_webhook_school_state_row(row)
        school_eligibility = (
            "allowed"
            if any(
                row["eligibility"] == "allowed"
                and row["binding_version"] == binding["version"]
                and row["onboarding_event_id"] is not None
                and row["onboarding_completed_at"] is not None
                for row in projections
            )
            else "denied"
        )
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_id),))
        await c.execute(
            "UPDATE enterprise.tenants SET external_eligibility=%s,"
            "external_version=external_version+1 WHERE id=%s AND external_tid=%s "
            "AND external_eligibility<>%s",
            (
                school_eligibility,
                school_id,
                str(event.external_tenant_id),
                school_eligibility,
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
        if eligibility == "allowed":
            await _open_first_school_administrator_from_webhook(
                c,
                enterprise,
                event,
                owner=owner,
                school_id=school_id,
                binding_version=binding["version"],
            )
        await c.execute(
            "UPDATE eduplus2.lifecycle_inbox SET processing_status=%s,processed_at=clock_timestamp() "
            "WHERE tenant_id=%s AND event_id=%s",
            ("verified" if eligibility == "allowed" else "denied", owner, event.event_id),
        )
        return eligibility
