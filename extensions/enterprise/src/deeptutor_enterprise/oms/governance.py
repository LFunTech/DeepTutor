"""OMS 治理只读投影与后端拥有的状态展示目录。

本模块只读取 DeepTutor Enterprise 本仓库 PG 事实；不调用或修改
EduPlus2 权限系统，也不把 PG/RLS 可见性当作操作者授权。调用方必须先
通过可信 OMS 身份适配器构造 ``ManagementIdentity``。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from deeptutor.persistence.postgres.scope import GlobalScope

from ..management.authorization import (
    ManagementAuthorizationDenied,
    ManagementDecision,
    ManagementIdentity,
    require_management_permission,
)
from ..scope import TenantScope
from .resource_status import build_resource_status


def _decimal_text(value: Any) -> str:
    text = format(Decimal(value).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return ""


_STATUS_DESCRIPTORS: dict[str, dict[str, str]] = {
    "active": {
        "label": "生效",
        "tone": "success",
        "description": "当前事实处于可用状态；仍须按动作和范围逐次鉴权。",
    },
    "revoked": {
        "label": "已撤销",
        "tone": "danger",
        "description": "授权、权益或授予已被撤销，不能继续用于新的业务写入。",
    },
    "verified": {
        "label": "已核验",
        "tone": "success",
        "description": "绑定或事实已经由受控流程核验，可作为程序授权输入继续复核。",
    },
    "success": {
        "label": "成功",
        "tone": "success",
        "description": "命令或审计事件已按预期完成。",
    },
    "conflict": {
        "label": "版本冲突",
        "tone": "warning",
        "description": "预期版本、幂等键或并发状态不匹配，调用方必须重新回读。",
    },
    "failed": {
        "label": "失败",
        "tone": "danger",
        "description": "命令未完成；需依据安全摘要继续排查，不能假定部分成功。",
    },
    "expired": {
        "label": "已过期",
        "tone": "warning",
        "description": "有效期已结束，仅保留历史核对与审计价值。",
    },
    "allowed": {
        "label": "学校订阅有效",
        "tone": "success",
        "description": "EduPlus2 已验签生命周期投影允许该学校访问智能体基座。",
    },
    "denied": {
        "label": "学校订阅不可用",
        "tone": "danger",
        "description": "EduPlus2 生命周期投影禁止新调用；管理侧只可做安全核对。",
    },
    "unknown": {
        "label": "待核对",
        "tone": "warning",
        "description": "尚无足够生命周期投影，不得把缺失状态当作已允许。",
    },
    "ready": {
        "label": "本地资源就绪",
        "tone": "success",
        "description": "DeepTutor 本地 PG/S3/运行时事实已完成初始化。",
    },
    "pending": {
        "label": "初始化中",
        "tone": "warning",
        "description": "本地初始化尚未完成，写入入口须失败关闭或进入排队。",
    },
    "normal": {
        "label": "恢复状态正常",
        "tone": "success",
        "description": "未处于恢复、冻结或人工核对状态。",
    },
    "reserved": {
        "label": "已预留",
        "tone": "info",
        "description": "调用额度已预留，尚未确认远端执行结果。",
    },
    "remote_unknown": {
        "label": "远端结果未知",
        "tone": "warning",
        "description": "远端调用可能已经发生，必须核对后才能释放或结算。",
    },
    "reconcile_required": {
        "label": "需要人工核对",
        "tone": "danger",
        "description": "供应商回执与本地预留不一致或超额，禁止自动释放。",
    },
    "settled": {
        "label": "已结算",
        "tone": "success",
        "description": "已按可信 usage evidence 写入实际消耗。",
    },
    "released": {
        "label": "已释放",
        "tone": "neutral",
        "description": "确认未发送或可安全释放，预留已退回。",
    },
    "not_configured": {
        "label": "未配置",
        "tone": "neutral",
        "description": "尚未在 OMS 中配置或发布该能力。",
    },
    "unavailable": {
        "label": "不可用",
        "tone": "danger",
        "description": "依赖缺失或健康检查不可用，业务入口必须失败关闭。",
    },
    "readiness_unverified": {
        "label": "就绪未验证",
        "tone": "warning",
        "description": "来自部署基线或草稿，尚未完成目标执行者确认。",
    },
    "requires_school_grant": {
        "label": "需学校授权",
        "tone": "info",
        "description": "平台已持有能力，但目标学校未授权前运行时不可见。",
    },
    "single_instance": {
        "label": "单实例",
        "tone": "warning",
        "description": "当前未声明高可用；不得用静态页面冒充多执行者容灾。",
    },
}


def describe_status(code: object) -> dict[str, str]:
    key = str(code or "unknown").strip() or "unknown"
    item = _STATUS_DESCRIPTORS.get(key)
    if item is None:
        return {
            "code": key,
            "label": "状态说明缺失，请联系支持",
            "tone": "warning",
            "description": "后端未登记该状态的展示语义；前端不得硬编码 raw code。",
        }
    return {"code": key, **item}


def status_catalog() -> dict[str, object]:
    return {
        "descriptor_version": 1,
        "statuses": [describe_status(code) for code in sorted(_STATUS_DESCRIPTORS)],
    }


async def require_platform_permission(
    connection,
    identity: ManagementIdentity,
    action: str,
    *,
    target_school_id: UUID | None = None,
    write: bool = False,
) -> ManagementDecision:
    """OMS 专用 PEP 入口；EduPlus2 身份只定位主体，不提供 ops.* 权限。"""

    if not isinstance(identity, ManagementIdentity) or identity.application != "oms":
        raise ManagementAuthorizationDenied("OMS platform identity is required")
    if not isinstance(action, str) or not action.startswith("ops."):
        raise ManagementAuthorizationDenied("OMS action key is required")
    return await require_management_permission(
        connection,
        identity,
        action,
        target_school_id=target_school_id,
        write=write,
        _lock_school_id=target_school_id if write else None,
    )


async def oms_permission_summary(enterprise, identity: ManagementIdentity) -> dict[str, object]:
    """返回正式 OMS 前端可用于显隐/路由守卫的同源动作摘要。

    摘要仅展示动作 key 与学校范围；真正 API 仍必须逐次调用 PEP。
    """

    async with enterprise.db.transaction(GlobalScope("@oms-permissions-candidates")) as c:
        await c.execute("SELECT set_config('app.management_app','oms',true)")
        rows = await (
            await c.execute(
                "SELECT DISTINCT a.scope_kind,a.school_id,ra.action_key "
                "FROM management.principals p "
                "JOIN management.assignments a ON a.application=p.application "
                "AND a.principal_id=p.id "
                "JOIN management.role_actions ra ON ra.application=a.application "
                "AND ra.role_key=a.role_key AND ra.role_version=a.role_version "
                "JOIN management.action_catalog ac ON ac.application=ra.application "
                "AND ac.action_key=ra.action_key "
                "WHERE p.application='oms' AND p.issuer=%s AND p.subject=%s "
                "AND p.status='active' AND p.policy_version=%s "
                "AND a.status='active' AND a.valid_from<=now() AND a.expires_at>now() "
                "AND ac.status='active' AND ac.allowed_scope IN (a.scope_kind,'both') "
                "ORDER BY a.scope_kind,a.school_id,ra.action_key",
                (identity.issuer, identity.subject, identity.policy_version),
            )
        ).fetchall()

    platform_actions: set[str] = set()
    school_actions: dict[UUID, set[str]] = {}
    for row in rows:
        action = row["action_key"]
        if not isinstance(action, str) or not action.startswith("ops."):
            continue
        if row["scope_kind"] == "platform":
            try:
                async with enterprise.db.transaction(
                    GlobalScope("@oms-permissions-platform-check")
                ) as c:
                    await require_platform_permission(c, identity, action, write=False)
            except ManagementAuthorizationDenied:
                continue
            platform_actions.add(action)
            continue
        school_id = row["school_id"]
        if not isinstance(school_id, UUID):
            continue
        try:
            async with enterprise.db.transaction(
                TenantScope(str(school_id), "@oms-permissions-school-check")
            ) as c:
                await require_platform_permission(
                    c, identity, action, target_school_id=school_id, write=False
                )
        except ManagementAuthorizationDenied:
            continue
        school_actions.setdefault(school_id, set()).add(action)

    return {
        "application": "oms",
        "subject": identity.subject,
        "policy_version": identity.policy_version,
        "platform_actions": sorted(platform_actions),
        "school_actions": [
            {"school_id": str(school_id), "actions": sorted(actions)}
            for school_id, actions in sorted(school_actions.items(), key=lambda item: str(item[0]))
        ],
    }


async def authorized_oms_school_ids(
    enterprise, identity: ManagementIdentity, action: str
) -> tuple[UUID, ...]:
    """返回当前 OMS 主体对某 school-scope 动作真实可用的学校集合。"""

    async with enterprise.db.transaction(GlobalScope("@oms-authorized-school-candidates")) as c:
        await c.execute("SELECT set_config('app.management_app','oms',true)")
        rows = await (
            await c.execute(
                "SELECT DISTINCT a.school_id "
                "FROM management.principals p "
                "JOIN management.assignments a ON a.application=p.application "
                "AND a.principal_id=p.id "
                "JOIN management.role_actions ra ON ra.application=a.application "
                "AND ra.role_key=a.role_key AND ra.role_version=a.role_version "
                "JOIN management.action_catalog ac ON ac.application=ra.application "
                "AND ac.action_key=ra.action_key "
                "WHERE p.application='oms' AND p.issuer=%s AND p.subject=%s "
                "AND p.status='active' AND p.policy_version=%s "
                "AND a.scope_kind='school' AND a.school_id IS NOT NULL "
                "AND a.status='active' AND a.valid_from<=now() AND a.expires_at>now() "
                "AND ra.action_key=%s AND ac.status='active' "
                "ORDER BY a.school_id",
                (identity.issuer, identity.subject, identity.policy_version, action),
            )
        ).fetchall()
    allowed: list[UUID] = []
    for row in rows:
        school_id = row["school_id"]
        if not isinstance(school_id, UUID):
            continue
        try:
            async with enterprise.db.transaction(
                TenantScope(str(school_id), "@oms-authorized-school-check")
            ) as c:
                await require_management_permission(
                    c, identity, action, target_school_id=school_id, write=False
                )
        except ManagementAuthorizationDenied:
            continue
        allowed.append(school_id)
    return tuple(allowed)


async def tenant_projection(enterprise, school_id: UUID) -> dict[str, object]:
    async with enterprise.db.transaction(TenantScope(str(school_id), "@oms-tenant-projection")) as c:
        row = await (
            await c.execute(
                "SELECT t.id,t.external_tid,t.external_eligibility,t.local_enabled,"
                "t.bootstrap_completed,t.provisioning_status,t.recovery_state,"
                "b.eduplus_tenant_id,b.status AS binding_status,b.version AS binding_version "
                "FROM enterprise.tenants t "
                "LEFT JOIN oms.school_bindings b ON b.tenant_id=t.id "
                "WHERE t.id=%s",
                (school_id,),
            )
        ).fetchone()
        if not row:
            raise LookupError("school not found")
        entitlements = await (
            await c.execute(
                "SELECT status,count(*) AS count FROM oms.tenant_service_entitlements "
                "GROUP BY status ORDER BY status"
            )
        ).fetchall()
        grants = await (
            await c.execute(
                "SELECT status,COALESCE(sum(quantity-adjustment_released),0) AS units "
                "FROM oms.quota_grants GROUP BY status ORDER BY status"
            )
        ).fetchall()
        usage = await (
            await c.execute(
                "SELECT status,count(*) AS attempts,COALESCE(sum(settled_units),0) AS settled "
                "FROM oms.usage_attempts GROUP BY status ORDER BY status"
            )
        ).fetchall()
    external_tid = str(row["external_tid"] or "")
    return {
        "school_id": str(row["id"]),
        "external_binding": {
            "has_external_tid": bool(external_tid),
            "eduplus_tenant_id": str(row["eduplus_tenant_id"] or ""),
            "status": describe_status(row["binding_status"] or "unknown"),
            "version": row["binding_version"] or 0,
        },
        "lifecycle": {
            "external_eligibility": describe_status(row["external_eligibility"]),
            "local_enabled": bool(row["local_enabled"]),
            "bootstrap_completed": bool(row["bootstrap_completed"]),
            "provisioning_status": describe_status(row["provisioning_status"]),
            "recovery_state": describe_status(row["recovery_state"]),
        },
        "service_entitlements": [
            {"status": describe_status(item["status"]), "count": item["count"]}
            for item in entitlements
        ],
        "quota_grants": [
            {"status": describe_status(item["status"]), "units": _decimal_text(item["units"])}
            for item in grants
        ],
        "usage": [
            {
                "status": describe_status(item["status"]),
                "attempts": item["attempts"],
                "settled_units": _decimal_text(item["settled"]),
            }
            for item in usage
        ],
    }


async def build_oms_summary(enterprise, identity: ManagementIdentity) -> dict[str, object]:
    school_ids = await authorized_oms_school_ids(enterprise, identity, "ops.tenants.read")
    resources = await build_resource_status(enterprise)
    return {
        "authorized_school_count": len(school_ids),
        "resource_count": len(resources.get("resources", ())),
        "descriptor_version": status_catalog()["descriptor_version"],
        "notices": [
            {
                "code": "oms_scope_is_explicit",
                "label": "OMS 仅显示已授权学校范围",
                "description": "跨学校列表来自本产品 ops.* school grant，不从 header、学校码或租户管理员角色推导。",
            }
        ],
    }


async def list_tenants_for_oms(enterprise, identity: ManagementIdentity) -> dict[str, object]:
    schools = await authorized_oms_school_ids(enterprise, identity, "ops.tenants.read")
    items = [await tenant_projection(enterprise, school_id) for school_id in schools]
    return {"tenants": items, "count": len(items)}


def _bounded_page(*, limit: int, offset: int) -> tuple[int, int]:
    return min(max(int(limit), 1), 200), min(max(int(offset), 0), 10_000)


def _usage_filter(
    *,
    service_id: str = "",
    provider_id: str = "",
    model_id: str = "",
    unit_code: str = "",
    status: str = "",
    subject_id: str = "",
) -> tuple[str, tuple[object, ...]]:
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (
        ("service_id", service_id),
        ("provider_id", provider_id),
        ("model_id", model_id),
        ("unit_code", unit_code),
        ("status", status),
        ("subject_id", subject_id),
    ):
        text = str(value or "").strip()
        if not text:
            continue
        if len(text) > 255:
            raise ValueError("usage filter is too long")
        clauses.append(f"{column}=%s")
        params.append(text)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, tuple(params)


async def usage_projection(
    enterprise,
    school_id: UUID,
    *,
    service_id: str = "",
    provider_id: str = "",
    model_id: str = "",
    unit_code: str = "",
    status: str = "",
    subject_id: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    limit, offset = _bounded_page(limit=limit, offset=offset)
    where, params = _usage_filter(
        service_id=service_id,
        provider_id=provider_id,
        model_id=model_id,
        unit_code=unit_code,
        status=status,
        subject_id=subject_id,
    )
    async with enterprise.db.transaction(TenantScope(str(school_id), "@oms-usage-projection")) as c:
        rows = await (
            await c.execute(
                "SELECT service_id,unit_code,status,count(*) AS attempts,"
                "COALESCE(sum(reserved_units),0) AS reserved_units,"
                "COALESCE(sum(settled_units),0) AS settled_units "
                f"FROM oms.usage_attempts {where} "
                "GROUP BY service_id,unit_code,status "
                "ORDER BY service_id,unit_code,status",
                params,
            )
        ).fetchall()
        detail_rows = await (
            await c.execute(
                "SELECT attempt_id,operation_id,service_id,unit_code,provider_id,model_id,"
                "subject_kind,subject_id,user_id,app_id,status,reserved_units,settled_units,"
                "started_at,updated_at "
                f"FROM oms.usage_attempts {where} "
                "ORDER BY started_at DESC,attempt_id LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
        ).fetchall()
    return {
        "school_id": str(school_id),
        "page": {"limit": limit, "offset": offset, "count": len(detail_rows)},
        "usage": [
            {
                "service_id": row["service_id"],
                "unit_code": row["unit_code"],
                "status": describe_status(row["status"]),
                "attempts": row["attempts"],
                "reserved_units": _decimal_text(row["reserved_units"]),
                "settled_units": _decimal_text(row["settled_units"]),
            }
            for row in rows
        ],
        "details": [
            {
                "attempt_id": str(row["attempt_id"]),
                "operation_id": str(row["operation_id"]),
                "service_id": row["service_id"],
                "unit_code": row["unit_code"],
                "provider_id": row["provider_id"],
                "model_id": row["model_id"],
                "subject_kind": row["subject_kind"],
                "subject_id": row["subject_id"],
                "user_id": row["user_id"],
                "app_id": row["app_id"],
                "status": describe_status(row["status"]),
                "reserved_units": _decimal_text(row["reserved_units"]),
                "settled_units": _decimal_text(row["settled_units"]),
                "started_at": _iso(row["started_at"]),
                "updated_at": _iso(row["updated_at"]),
            }
            for row in detail_rows
        ],
    }


async def jobs_projection(enterprise, school_id: UUID) -> dict[str, object]:
    async with enterprise.db.transaction(TenantScope(str(school_id), "@oms-jobs-projection")) as c:
        rows = await (
            await c.execute(
                "SELECT attempt_id,operation_id,service_id,unit_code,status,updated_at,"
                "reserved_units,settled_units "
                "FROM oms.usage_attempts "
                "WHERE status IN ('remote_unknown','reconcile_required') "
                "ORDER BY updated_at DESC,attempt_id LIMIT 100"
            )
        ).fetchall()
    return {
        "school_id": str(school_id),
        "jobs": [
            {
                "attempt_id": str(row["attempt_id"]),
                "operation_id": str(row["operation_id"]),
                "service_id": row["service_id"],
                "unit_code": row["unit_code"],
                "status": describe_status(row["status"]),
                "updated_at": _iso(row["updated_at"]),
                "reserved_units": _decimal_text(row["reserved_units"]),
                "settled_units": _decimal_text(row["settled_units"]),
            }
            for row in rows
        ],
    }


async def supply_projection(enterprise) -> dict[str, object]:
    async with enterprise.db.transaction(GlobalScope("@oms-supply-projection")) as c:
        definitions = await (
            await c.execute(
                "SELECT service_id,unit_code,resource_category,enabled,version "
                "FROM oms.service_definitions ORDER BY service_id"
            )
        ).fetchall()
        lots = await (
            await c.execute(
                "SELECT service_id,provider_id,pool_id,unit_code,status,hard_ceiling,"
                "settled_lifetime,committed_unspent,reserved_inflight,starts_at,expires_at "
                "FROM oms.supply_lots ORDER BY service_id,pool_id,expires_at,id LIMIT 200"
            )
        ).fetchall()
    return {
        "service_definitions": [
            {
                "service_id": row["service_id"],
                "unit_code": row["unit_code"],
                "resource_category": row["resource_category"],
                "enabled": bool(row["enabled"]),
                "version": row["version"],
            }
            for row in definitions
        ],
        "supply_lots": [
            {
                "service_id": row["service_id"],
                "provider_id": row["provider_id"],
                "pool_id": row["pool_id"],
                "unit_code": row["unit_code"],
                "status": describe_status(row["status"]),
                "hard_ceiling": None
                if row["hard_ceiling"] is None
                else _decimal_text(row["hard_ceiling"]),
                "settled_lifetime": _decimal_text(row["settled_lifetime"]),
                "committed_unspent": _decimal_text(row["committed_unspent"]),
                "reserved_inflight": _decimal_text(row["reserved_inflight"]),
                "starts_at": _iso(row["starts_at"]),
                "expires_at": _iso(row["expires_at"]),
            }
            for row in lots
        ],
    }


async def audit_projection(
    enterprise, *, application: str, school_id: UUID | None, limit: int
) -> dict[str, object]:
    limit = min(max(int(limit), 1), 200)
    scope = (
        GlobalScope("@oms-audit-projection")
        if school_id is None
        else TenantScope(str(school_id), "@oms-audit-projection")
    )
    async with enterprise.db.transaction(scope) as c:
        await c.execute("SELECT set_config('app.management_app',%s,true)", (application,))
        if school_id is None:
            management_rows = await (
                await c.execute(
                    "SELECT application,school_id,actor_issuer,actor_subject,action_key,"
                    "target_kind,target_id,request_id,result,reason,before_version,after_version,"
                    "safe_summary,created_at FROM management.audit_events "
                    "WHERE application=%s ORDER BY created_at DESC,id LIMIT %s",
                    (application, limit),
                )
            ).fetchall()
            oms_rows = await (
                await c.execute(
                    "SELECT actor_subject,action,target_tenant_id,object_kind,object_id,"
                    "request_id,result,reason,safe_summary,created_at "
                    "FROM oms.audit_events ORDER BY created_at DESC,id LIMIT %s",
                    (limit,),
                )
            ).fetchall()
        else:
            management_rows = await (
                await c.execute(
                    "SELECT application,school_id,actor_issuer,actor_subject,action_key,"
                    "target_kind,target_id,request_id,result,reason,before_version,after_version,"
                    "safe_summary,created_at FROM management.audit_events "
                    "WHERE application=%s AND school_id=%s ORDER BY created_at DESC,id LIMIT %s",
                    (application, school_id, limit),
                )
            ).fetchall()
            oms_rows = await (
                await c.execute(
                    "SELECT actor_subject,action,target_tenant_id,object_kind,object_id,"
                    "request_id,result,reason,safe_summary,created_at "
                    "FROM oms.audit_events WHERE target_tenant_id=%s "
                    "ORDER BY created_at DESC,id LIMIT %s",
                    (school_id, limit),
                )
            ).fetchall()
    return {
        "management_events": [
            {
                "application": row["application"],
                "school_id": str(row["school_id"] or ""),
                "actor": {"issuer": row["actor_issuer"], "subject": row["actor_subject"]},
                "action": row["action_key"],
                "target_kind": row["target_kind"],
                "target_id": row["target_id"],
                "request_id": row["request_id"],
                "result": describe_status(row["result"]),
                "reason": row["reason"],
                "before_version": row["before_version"],
                "after_version": row["after_version"],
                "safe_summary": row["safe_summary"],
                "created_at": _iso(row["created_at"]),
            }
            for row in management_rows
        ],
        "oms_events": [
            {
                "actor_subject": row["actor_subject"],
                "action": row["action"],
                "school_id": str(row["target_tenant_id"] or ""),
                "object_kind": row["object_kind"],
                "object_id": row["object_id"],
                "request_id": row["request_id"],
                "result": describe_status(row["result"]),
                "reason": row["reason"],
                "safe_summary": row["safe_summary"],
                "created_at": _iso(row["created_at"]),
            }
            for row in oms_rows
        ],
    }
