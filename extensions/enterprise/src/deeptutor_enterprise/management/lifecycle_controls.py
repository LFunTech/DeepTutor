"""OMS 逐校授权的生命周期本地冻结；不改写 EduPlus2 Webhook 权威。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from ..scope import TenantScope
from .authorization import (
    ManagementAuthorizationDenied,
    ManagementIdentity,
    require_management_permission,
)


class SchoolFreezeConflict(ValueError):
    """冻结命令的预期版本或幂等事实不匹配。"""


@dataclass(frozen=True, slots=True)
class SchoolFreezeResult:
    frozen: bool
    version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class SchoolLifecycleDiagnosis:
    school_id: UUID
    external_app_id: int
    generation: int
    eligibility: str
    frozen: bool
    control_version: int
    database_onboarded: bool


async def inspect_school_lifecycle(
    enterprise, actor: ManagementIdentity, *, school_id: UUID, request_id: str
) -> SchoolLifecycleDiagnosis:
    """返回本校脱敏状态，并以 OMS 动作权限审计诊断读取。"""

    if (
        not isinstance(actor, ManagementIdentity)
        or actor.application != "oms"
        or not isinstance(school_id, UUID)
        or actor.webhook_app_id != getattr(enterprise, "eduplus2_webhook_app_id", None)
        or type(request_id) is not str
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ManagementAuthorizationDenied("school diagnosis identity is invalid")
    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@webhook-school-diagnosis")) as c:
        await require_management_permission(
            c, actor, "ops.reconciliation.manage", target_school_id=school_id, write=True
        )
        row = await (
            await c.execute(
                "SELECT p.generation,p.eligibility,p.onboarding_completed_at IS NOT NULL "
                "AS database_onboarded,k.frozen,k.version AS control_version "
                "FROM eduplus2.webhook_school_state p "
                "JOIN eduplus2.webhook_school_controls k "
                "ON (k.tenant_id,k.school_id,k.external_app_id)="
                "(p.tenant_id,p.school_id,p.external_app_id) "
                "WHERE p.tenant_id=%s AND p.school_id=%s AND p.external_app_id=%s "
                "FOR SHARE OF p,k",
                (owner, school_id, actor.webhook_app_id),
            )
        ).fetchone()
        if not row:
            raise ManagementAuthorizationDenied("school lifecycle state is unavailable")
        await c.execute(
            "INSERT INTO management.audit_events(id,application,school_id,actor_issuer,"
            "actor_subject,action_key,target_kind,target_id,request_id,result,reason,"
            "safe_summary) VALUES(%s,'oms',%s,%s,%s,'ops.reconciliation.manage',"
            "'school',%s,%s,'success','lifecycle diagnosis',%s)",
            (
                uuid4(),
                school_id,
                actor.issuer,
                actor.subject,
                str(school_id),
                request_id.strip(),
                Jsonb({"diagnostic": True}),
            ),
        )
        return SchoolLifecycleDiagnosis(
            school_id=school_id,
            external_app_id=actor.webhook_app_id,
            generation=row["generation"],
            eligibility=row["eligibility"],
            frozen=row["frozen"],
            control_version=row["control_version"],
            database_onboarded=row["database_onboarded"],
        )


async def set_school_lifecycle_freeze(
    enterprise,
    actor: ManagementIdentity,
    *,
    school_id: UUID,
    frozen: bool,
    expected_version: int,
    command_id: UUID,
    reason: str,
    request_id: str,
) -> SchoolFreezeResult:
    """经本产品 ``ops.reconciliation.manage`` 判定后版本化冻结/解除。

    解除只释放本地额外门禁，不把被 Webhook 停用的学校改为 allowed。
    ``actor`` 只能来自未来 OMS 可信会话适配器，不能由请求体构造。
    """

    if (
        not isinstance(actor, ManagementIdentity)
        or actor.application != "oms"
        or not isinstance(school_id, UUID)
        or type(frozen) is not bool
        or type(expected_version) is not int
        or expected_version < 1
        or not isinstance(command_id, UUID)
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
        or actor.webhook_app_id != getattr(enterprise, "eduplus2_webhook_app_id", None)
    ):
        raise ManagementAuthorizationDenied("school freeze command is invalid")
    owner = enterprise.deployment.tenant_id
    app_id = actor.webhook_app_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@webhook-school-control")) as c:
        decision = await require_management_permission(
            c, actor, "ops.reconciliation.manage", target_school_id=school_id, write=True
        )
        previous = await (
            await c.execute(
                "SELECT actor_issuer,actor_subject,school_id,external_app_id,frozen,"
                "expected_version,result_version,reason FROM "
                "eduplus2.webhook_school_control_commands "
                "WHERE tenant_id=%s AND command_id=%s",
                (owner, command_id),
            )
        ).fetchone()
        if previous:
            if previous != {
                "actor_issuer": actor.issuer,
                "actor_subject": actor.subject,
                "school_id": school_id,
                "external_app_id": app_id,
                "frozen": frozen,
                "expected_version": expected_version,
                "result_version": previous["result_version"],
                "reason": reason.strip(),
            }:
                raise SchoolFreezeConflict("school freeze command conflicts with prior facts")
            return SchoolFreezeResult(previous["frozen"], previous["result_version"], True)
        control = await (
            await c.execute(
                "SELECT frozen,version FROM eduplus2.webhook_school_controls "
                "WHERE tenant_id=%s AND school_id=%s AND external_app_id=%s FOR UPDATE",
                (owner, school_id, app_id),
            )
        ).fetchone()
        if not control or control["version"] != expected_version:
            raise SchoolFreezeConflict("school freeze version is stale")
        if control["frozen"] == frozen:
            raise SchoolFreezeConflict("school freeze state is unchanged")
        updated = await (
            await c.execute(
                "UPDATE eduplus2.webhook_school_controls SET frozen=%s,version=version+1,"
                "reason=%s,updated_by=%s,updated_at=clock_timestamp() "
                "WHERE tenant_id=%s AND school_id=%s AND external_app_id=%s "
                "AND version=%s RETURNING version",
                (
                    frozen,
                    reason.strip(),
                    actor.subject,
                    owner,
                    school_id,
                    app_id,
                    expected_version,
                ),
            )
        ).fetchone()
        if not updated:
            raise SchoolFreezeConflict("school freeze version changed")
        await c.execute(
            "INSERT INTO eduplus2.webhook_school_control_commands(tenant_id,command_id,"
            "school_id,external_app_id,actor_issuer,actor_subject,frozen,"
            "expected_version,result_version,reason,request_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                owner,
                command_id,
                school_id,
                app_id,
                actor.issuer,
                actor.subject,
                frozen,
                expected_version,
                updated["version"],
                reason.strip(),
                request_id.strip(),
            ),
        )
        await c.execute(
            "INSERT INTO management.audit_events(id,application,school_id,actor_issuer,"
            "actor_subject,action_key,target_kind,target_id,request_id,result,reason,"
            "before_version,after_version,safe_summary) "
            "VALUES(%s,'oms',%s,%s,%s,'ops.reconciliation.manage','school',%s,%s,"
            "'success',%s,%s,%s,%s)",
            (
                uuid4(),
                school_id,
                actor.issuer,
                actor.subject,
                str(school_id),
                request_id.strip(),
                reason.strip(),
                expected_version,
                updated["version"],
                Jsonb(
                    {
                        "frozen": frozen,
                        "command_id": str(command_id),
                        "assignment_id": str(decision.assignment_id),
                    }
                ),
            ),
        )
        return SchoolFreezeResult(frozen, updated["version"], False)
