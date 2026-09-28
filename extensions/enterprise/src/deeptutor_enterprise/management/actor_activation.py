"""已验签订阅 actor 的首位 TMS 管理员一次性激活。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.tenant_state import validate_tenant_business_values

from ..eduplus2.lifecycle import (
    validate_lifecycle_actor_candidate_row,
    validate_webhook_school_state_row,
)
from ..scope import TenantScope
from .assignment_rules import validate_assignment_relation
from .authorization import ManagementAuthorizationDenied, ManagementIdentity, _identity_is_current
from .policy_version import advance_principal_policy_version

_SCHOOL_ADMIN_EXPIRES_AT = datetime(9998, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class FirstAdministratorActivation:
    principal_id: UUID
    assignment_id: UUID
    policy_version: int
    replayed: bool


async def activate_first_school_administrator(
    enterprise, identity: ManagementIdentity, *, event_id: str, request_id: str
) -> FirstAdministratorActivation:
    """只接受可信 TMS 登录适配器构造的本人身份；不接受请求体身份。"""

    if (
        not isinstance(identity, ManagementIdentity)
        or identity.application != "tms"
        or not _identity_is_current(identity, write=True)
        or not getattr(enterprise, "eduplus2_lifecycle_receiver_enabled", False)
        or identity.issuer != getattr(enterprise, "eduplus2_issuer", None)
        or type(identity.webhook_app_id) is not int
        or identity.webhook_app_id <= 0
        or type(event_id) is not str
        or not 1 <= len(event_id) <= 128
        or type(request_id) is not str
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ManagementAuthorizationDenied("trusted school activation identity is unavailable")
    app_id = identity.webhook_app_id
    owner = enterprise.deployment.tenant_id
    command_id = uuid5(NAMESPACE_URL, f"deeptutor:tms:first-admin:{owner}:{event_id}")
    async with enterprise.db.transaction(TenantScope(str(owner), "@school-activation")) as c:
        school = await (
            await c.execute(
                "SELECT b.eduplus_tenant_id,b.version,t.bootstrap_completed,"
                "t.external_eligibility,t.provisioning_status,t.recovery_state "
                "FROM oms.school_bindings b JOIN enterprise.tenants t ON t.id=b.tenant_id "
                "WHERE b.tenant_id=%s AND b.status='verified' "
                "AND t.external_tid=b.eduplus_tenant_id::text "
                "FOR UPDATE OF b,t",
                (identity.school_id,),
            )
        ).fetchone()
        if not school or school["version"] != identity.school_binding_version:
            raise ManagementAuthorizationDenied("school lifecycle or binding is unavailable")
        try:
            validate_tenant_business_values(school)
        except ValueError as exc:
            raise ManagementAuthorizationDenied("school lifecycle or state is unavailable") from exc
        if school["recovery_state"] != "normal" or school["external_eligibility"] != "allowed":
            raise ManagementAuthorizationDenied("school lifecycle or state is unavailable")
        projection = await (
            await c.execute(
                "SELECT eligibility,onboarding_event_id,onboarding_completed_at "
                "FROM eduplus2.webhook_school_state "
                "WHERE tenant_id=%s AND external_tenant_id=%s AND external_app_id=%s "
                "AND school_id=%s AND binding_version=%s AND eligibility='allowed' "
                "AND onboarding_event_id IS NOT NULL "
                "AND onboarding_completed_at IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM eduplus2.webhook_school_controls k "
                "WHERE (k.tenant_id,k.school_id,k.external_app_id)="
                "(%s,%s,%s) AND NOT k.frozen) "
                "FOR SHARE",
                (
                    owner,
                    school["eduplus_tenant_id"],
                    app_id,
                    identity.school_id,
                    school["version"],
                    owner,
                    identity.school_id,
                    app_id,
                ),
            )
        ).fetchone()
        if projection:
            validate_webhook_school_state_row(projection)
        if not projection:
            raise ManagementAuthorizationDenied("school webhook projection is unavailable")
        candidate = await (
            await c.execute(
                "SELECT school_id,external_tenant_id,external_app_id,binding_version,"
                "actor_issuer,actor_subject,status,resolved_at "
                "FROM eduplus2.lifecycle_actor_candidates "
                "WHERE tenant_id=%s AND event_id=%s FOR UPDATE",
                (owner, event_id),
            )
        ).fetchone()
        if candidate:
            validate_lifecycle_actor_candidate_row(candidate)
        if not candidate or (
            candidate["school_id"] != identity.school_id
            or candidate["external_tenant_id"] != school["eduplus_tenant_id"]
            or candidate["external_app_id"] != app_id
            or candidate["binding_version"] != school["version"]
            or candidate["actor_issuer"] != identity.issuer
            or candidate["actor_subject"] != identity.subject
        ):
            raise ManagementAuthorizationDenied("school actor candidate does not match identity")
        await c.execute("SELECT set_config('app.management_app','tms',true)")
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(identity.school_id),))
        principal = await (
            await c.execute(
                "SELECT id,status,policy_version FROM management.principals "
                "WHERE application='tms' AND issuer=%s AND subject=%s AND school_id=%s "
                "FOR UPDATE",
                (identity.issuer, identity.subject, identity.school_id),
            )
        ).fetchone()
        if candidate["status"] == "consumed":
            assignment = await (
                await c.execute(
                    "SELECT id,principal_id FROM management.assignments "
                    "WHERE application='tms' AND command_id=%s AND role_key='school_admin' "
                    "AND school_id=%s AND status='active'",
                    (command_id, identity.school_id),
                )
            ).fetchone()
            if (
                not school["bootstrap_completed"]
                or not principal
                or principal["status"] != "active"
                or not assignment
                or assignment["principal_id"] != principal["id"]
            ):
                raise ManagementAuthorizationDenied("school activation replay is inconsistent")
            return FirstAdministratorActivation(
                principal["id"], assignment["id"], principal["policy_version"], True
            )
        if candidate["status"] != "pending_verification" or school["bootstrap_completed"]:
            raise ManagementAuthorizationDenied("school activation was already decided")
        if principal and (
            principal["status"] != "pending"
            or principal["policy_version"] != identity.policy_version
        ):
            raise ManagementAuthorizationDenied("existing management principal is not activatable")
        if not principal and identity.policy_version != 1:
            raise ManagementAuthorizationDenied("initial management policy version is invalid")
        existing_admin = await (
            await c.execute(
                "SELECT 1 FROM management.assignments WHERE application='tms' "
                "AND school_id=%s AND role_key='school_admin' AND status='active' "
                "AND valid_from<=now() AND expires_at>now() LIMIT 1",
                (identity.school_id,),
            )
        ).fetchone()
        if existing_admin:
            raise ManagementAuthorizationDenied("school administrator already exists")
        principal_id = principal["id"] if principal else uuid4()
        if principal:
            await c.execute(
                "UPDATE management.principals SET status='active',external_evidence_ref=%s,"
                "updated_at=clock_timestamp() WHERE id=%s",
                (event_id, principal_id),
            )
        else:
            await c.execute(
                "INSERT INTO management.principals(id,application,issuer,subject,school_id,"
                "status,external_evidence_ref) VALUES(%s,'tms',%s,%s,%s,'active',%s)",
                (principal_id, identity.issuer, identity.subject, identity.school_id, event_id),
            )
        role = await (
            await c.execute(
                "SELECT scope_kind FROM management.role_versions "
                "WHERE application='tms' AND role_key='school_admin' AND version=1 FOR SHARE"
            )
        ).fetchone()
        validate_assignment_relation(
            application="tms",
            principal_application="tms",
            principal_school_id=identity.school_id,
            role_application="tms" if role else None,
            role_scope_kind=role["scope_kind"] if role else None,
            assignment_scope_kind="school",
            assignment_school_id=identity.school_id,
        )
        assignment_id = uuid4()
        await c.execute(
            "INSERT INTO management.assignments(id,application,principal_id,role_key,"
            "role_version,scope_kind,school_id,school_binding_version,valid_from,"
            "expires_at,command_id,created_by) "
            "VALUES(%s,'tms',%s,'school_admin',1,'school',%s,%s,clock_timestamp(),"
            "%s,%s,'@webhook-actor-activation')",
            (
                assignment_id,
                principal_id,
                identity.school_id,
                school["version"],
                _SCHOOL_ADMIN_EXPIRES_AT,
                command_id,
            ),
        )
        next_policy_version = await advance_principal_policy_version(
            c, principal_id, expected_before=identity.policy_version
        )
        await c.execute(
            "UPDATE enterprise.tenants SET bootstrap_completed=true WHERE id=%s",
            (identity.school_id,),
        )
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(owner),))
        consumed = await c.execute(
            "UPDATE eduplus2.lifecycle_actor_candidates SET status='consumed',"
            "resolved_at=clock_timestamp() WHERE tenant_id=%s AND event_id=%s "
            "AND status='pending_verification' AND resolved_at IS NULL",
            (owner, event_id),
        )
        if consumed.rowcount != 1:
            raise ManagementAuthorizationDenied("school actor candidate changed during activation")
        await c.execute(
            "UPDATE eduplus2.lifecycle_actor_candidates SET status='revoked',"
            "resolved_at=clock_timestamp() WHERE tenant_id=%s AND school_id=%s "
            "AND event_id<>%s AND status='pending_verification'",
            (owner, identity.school_id, event_id),
        )
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(identity.school_id),))
        await c.execute(
            "INSERT INTO management.audit_events(id,application,school_id,actor_issuer,"
            "actor_subject,action_key,target_kind,target_id,request_id,result,reason,"
            "before_version,after_version,safe_summary) "
            "VALUES(%s,'tms',%s,%s,%s,'tenant.school.bootstrap','school',%s,%s,"
            "'success','signed webhook actor matched trusted TMS identity',%s,%s,%s)",
            (
                uuid4(),
                identity.school_id,
                identity.issuer,
                identity.subject,
                str(identity.school_id),
                request_id,
                identity.policy_version,
                next_policy_version,
                Jsonb({"event_id": event_id}),
            ),
        )
        return FirstAdministratorActivation(
            principal_id, assignment_id, next_policy_version, False
        )
