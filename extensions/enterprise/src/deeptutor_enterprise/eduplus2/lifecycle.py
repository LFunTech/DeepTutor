"""订阅 Webhook 事件解析与历史在线对账兼容；正式接收使用 webhook_authority。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import hashlib
import hmac
import json
import re
from typing import Any

from ..scope import TenantScope

SUPPORTED_EVENTS = frozenset(
    {
        "subscription.created",
        "subscription.suspended",
        "subscription.reactivated",
        "subscription.terminated",
        "subscription.expired",
        "subscription.renewed",
        "subscription.expiring",
        "subscription.plan_changed",
    }
)


class LifecycleInvalid(ValueError):
    """真实事件不符合已知安全字段合同。"""


class LifecycleWrongApp(PermissionError):
    """事件目标不是当前配置的 EduPlus2 应用。"""


class LifecycleConflict(ValueError):
    """相同事件 ID 携带不同业务事实。"""


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    event_id: str
    event_type: str
    external_tenant_id: int
    external_app_id: int
    external_subscription_id: int
    subscription_status: str
    client_id: str
    actor_type: str
    actor_subject: str
    tenant_type: str
    school_code: str
    semantic_digest: str


def _positive_id(value: Any) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise LifecycleInvalid("invalid external identifier")
    return value


def _safe_text(value: Any, *, max_length: int, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value) > max_length:
        raise LifecycleInvalid("invalid event field")
    if required and not value:
        raise LifecycleInvalid("required event field is missing")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise LifecycleInvalid("invalid event field")
    return value


def parse_lifecycle_event(
    payload: dict[str, Any], event_type: str, *, app_id: int, digest_key: str
) -> LifecycleEvent:
    """从真实事件提取业务白名单；绝不读取/保存 OAuth Secret。"""

    if event_type not in SUPPORTED_EVENTS:
        raise LifecycleInvalid("unsupported event")
    if type(app_id) is not int or app_id <= 0 or len(digest_key) < 32:
        raise RuntimeError("lifecycle receiver is not configured")
    event_id = _safe_text(payload.get("event_id"), max_length=128, required=True)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", event_id) or event_id.startswith("mock_"):
        raise LifecycleInvalid("invalid real event id")
    tenant = payload.get("tenant")
    app = payload.get("app")
    subscription = payload.get("subscription")
    if not all(isinstance(value, dict) for value in (tenant, app, subscription)):
        raise LifecycleInvalid("missing event target")
    tenant_id = _positive_id(tenant.get("id"))
    tenant_type = _safe_text(tenant.get("tenant_type"), max_length=32)
    if tenant_type and tenant_type != "school":
        raise LifecycleInvalid("event target is not a school")
    school_code = _safe_text(tenant.get("code"), max_length=128)
    external_app_id = _positive_id(app.get("id"))
    subscription_id = _positive_id(subscription.get("id"))
    if external_app_id != app_id:
        raise LifecycleWrongApp("event target application differs")
    status = _safe_text(subscription.get("status"), max_length=64, required=True)
    app_client_id = _safe_text(app.get("client_id"), max_length=255)
    oauth = payload.get("oauth_client")
    if oauth is not None and not isinstance(oauth, dict):
        raise LifecycleInvalid("invalid OAuth client metadata")
    oauth_client_id = _safe_text((oauth or {}).get("client_id"), max_length=255)
    if app_client_id and oauth_client_id and app_client_id != oauth_client_id:
        raise LifecycleInvalid("OAuth client identifiers differ")
    client_id = app_client_id or oauth_client_id
    actor = payload.get("actor")
    if actor is not None and not isinstance(actor, dict):
        raise LifecycleInvalid("invalid event actor")
    actor_type = ""
    actor_subject = ""
    if event_type == "subscription.created" and actor:
        actor_type = _safe_text(actor.get("type"), max_length=32)
        if actor_type == "user":
            actor_subject = _safe_text(actor.get("user_id"), max_length=255)
    projection = {
        "event_type": event_type,
        "tenant_id": tenant_id,
        "app_id": external_app_id,
        "subscription_id": subscription_id,
        "subscription_status": status,
        "client_id": client_id,
        "actor_type": actor_type,
        "actor_subject": actor_subject,
        "tenant_type": tenant_type,
        "school_code": school_code,
    }
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hmac.new(digest_key.encode("utf-8"), canonical.encode("ascii"), hashlib.sha256)
    return LifecycleEvent(
        event_id=event_id,
        event_type=event_type,
        external_tenant_id=tenant_id,
        external_app_id=external_app_id,
        external_subscription_id=subscription_id,
        subscription_status=status,
        client_id=client_id,
        actor_type=actor_type,
        actor_subject=actor_subject,
        tenant_type=tenant_type,
        school_code=school_code,
        semantic_digest=digest.hexdigest(),
    )


async def ingest_lifecycle_event(enterprise, event: LifecycleEvent, *, delivery_timestamp: int):
    """历史通知/在线核验兼容入口；正式 HTTP Webhook 不再调用。"""

    digest_key = str(getattr(enterprise, "eduplus2_webhook_inbox_digest_key", "") or "")
    signing_secrets = (
        str(getattr(enterprise, "eduplus2_webhook_secret", "") or ""),
        str(getattr(enterprise, "eduplus2_webhook_previous_secret", "") or ""),
    )
    if digest_key and any(
        secret and hmac.compare_digest(digest_key, secret) for secret in signing_secrets
    ):
        raise RuntimeError("inbox integrity key must be independent")
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@eduplus2-webhook")
    async with enterprise.db.transaction(scope) as c:
        inserted = await (
            await c.execute(
                """
                INSERT INTO eduplus2.lifecycle_inbox(
                  tenant_id,event_id,semantic_digest,event_type,external_tenant_id,
                  external_app_id,external_subscription_id,subscription_status,
                  client_id,actor_subject,actor_type,delivery_timestamp
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,event_id) DO NOTHING
                RETURNING event_id
                """,
                (
                    enterprise.deployment.tenant_id,
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
        if inserted:
            # 事件只是通知，但旧在线解析缓存不能跨越本地 generation 继续使用。
            await c.execute(
                "DELETE FROM eduplus2.resolve_cache WHERE tenant_id=%s",
                (enterprise.deployment.tenant_id,),
            )
            if event.client_id:
                conflicting_client = await (
                    await c.execute(
                        "SELECT 1 FROM eduplus2.external_client_registrations r "
                        "WHERE r.client_id=%s AND r.status='active' "
                        "AND (r.external_tenant_id<>%s OR r.external_app_id<>%s) "
                        "LIMIT 1",
                        (
                            event.client_id,
                            str(event.external_tenant_id),
                            str(event.external_app_id),
                        ),
                    )
                ).fetchone()
                if conflicting_client:
                    raise LifecycleConflict("client conflicts with registered school target")
            await c.execute(
                """
                INSERT INTO eduplus2.lifecycle_targets(
                  tenant_id,external_tenant_id,external_app_id,generation,eligibility
                ) VALUES(%s,%s,%s,1,'unknown')
                ON CONFLICT (tenant_id,external_tenant_id,external_app_id)
                DO UPDATE SET generation=eduplus2.lifecycle_targets.generation+1,
                              eligibility='unknown',proof_checked_at=NULL,
                              proof_expires_at=NULL,resolve_etag='',binding_version=0,
                              retry_count=0,last_error_code='',
                              updated_at=now()
                """,
                (
                    enterprise.deployment.tenant_id,
                    event.external_tenant_id,
                    event.external_app_id,
                ),
            )
            await c.execute(
                "UPDATE enterprise.tenants t SET external_eligibility='denied',"
                "external_version=external_version+1 "
                "FROM oms.school_bindings b "
                "WHERE b.tenant_id=t.id AND b.eduplus_tenant_id=%s "
                "AND b.status='verified' AND t.external_tid=%s "
                "AND t.external_eligibility='allowed'",
                (event.external_tenant_id, str(event.external_tenant_id)),
            )
            bound = await (
                await c.execute(
                    "SELECT 1 FROM oms.school_bindings b "
                    "JOIN enterprise.tenants t ON t.id=b.tenant_id "
                    "WHERE b.eduplus_tenant_id=%s AND b.status='verified' "
                    "AND t.external_tid=%s LIMIT 1",
                    (event.external_tenant_id, str(event.external_tenant_id)),
                )
            ).fetchone()
            if bound:
                await c.execute(
                    "UPDATE eduplus2.lifecycle_inbox SET processing_status='pending_reconcile' "
                    "WHERE tenant_id=%s AND event_id=%s",
                    (enterprise.deployment.tenant_id, event.event_id),
                )
            return "pending_reconcile" if bound else "pending_binding"
        previous = await (
            await c.execute(
                "SELECT semantic_digest FROM eduplus2.lifecycle_inbox "
                "WHERE tenant_id=%s AND event_id=%s",
                (enterprise.deployment.tenant_id, event.event_id),
            )
        ).fetchone()
        if not previous or not hmac.compare_digest(
            previous["semantic_digest"], event.semantic_digest
        ):
            raise LifecycleConflict("event id carries different business facts")
        return "duplicate"


_ACTIVE = frozenset({"active", "enabled", "allowed"})
_KNOWN_INACTIVE = frozenset(
    {
        "client_revoked",
        "client_deprecated",
        "client_inactive",
        "tenant_inactive",
        "app_inactive",
        "subscription_inactive",
        "client_not_found",
    }
)


def _current_active_binding(result: dict[str, Any], client_id: str, school_id: int, app_id: int):
    if result.get("client_id") != client_id:
        return False
    if str(result.get("external_tenant_id") or "") != str(school_id):
        return False
    if str(result.get("external_app_id") or "") != str(app_id):
        return False
    return (
        str(result.get("status") or "").lower() in _ACTIVE
        and str(result.get("tenant_status") or "").lower() in _ACTIVE | {"trial"}
        and str(result.get("app_status") or "").lower() in _ACTIVE
        and str(result.get("subscription_status") or "").lower() in {"active", "subscribed"}
    )


async def reconcile_lifecycle_target(
    enterprise, *, external_tenant_id: int, external_app_id: int
) -> str:
    """PG 事务级 advisory lock 串行化同一学校—应用的在线查询。"""

    _positive_id(external_tenant_id)
    _positive_id(external_app_id)
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@eduplus2-reconcile")
    key = (
        f"deeptutor-lifecycle:{enterprise.deployment.tenant_id}:"
        f"{external_tenant_id}:{external_app_id}"
    )
    async with enterprise.db.transaction(scope) as c:
        lock = await (
            await c.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS acquired",
                (key,),
            )
        ).fetchone()
        if not lock or not lock["acquired"]:
            return "busy"
        return await _reconcile_lifecycle_target_locked(
            enterprise,
            external_tenant_id=external_tenant_id,
            external_app_id=external_app_id,
        )


async def _reconcile_lifecycle_target_locked(
    enterprise, *, external_tenant_id: int, external_app_id: int
) -> str:
    """按已验证学校绑定读在线当前态；无证明时不从事件推断允许。"""

    scope = TenantScope(str(enterprise.deployment.tenant_id), "@eduplus2-reconcile")
    async with enterprise.db.transaction(scope) as c:
        target = await (
            await c.execute(
                "SELECT generation FROM eduplus2.lifecycle_targets WHERE tenant_id=%s "
                "AND external_tenant_id=%s AND external_app_id=%s",
                (enterprise.deployment.tenant_id, external_tenant_id, external_app_id),
            )
        ).fetchone()
        binding = await (
            await c.execute(
                "SELECT b.tenant_id,b.version FROM oms.school_bindings b "
                "JOIN enterprise.tenants t ON t.id=b.tenant_id "
                "WHERE b.eduplus_tenant_id=%s AND b.status='verified' AND t.external_tid=%s",
                (external_tenant_id, str(external_tenant_id)),
            )
        ).fetchone()
        clients = await (
            await c.execute(
                "SELECT DISTINCT client_id FROM ("
                "SELECT client_id FROM eduplus2.lifecycle_inbox "
                "WHERE tenant_id=%s AND external_tenant_id=%s AND external_app_id=%s "
                "AND client_id<>'' UNION ALL "
                "SELECT client_id FROM eduplus2.external_client_registrations "
                "WHERE tenant_id=%s AND internal_tenant_id=%s AND provider='eduplus2' "
                "AND external_tenant_id=%s AND external_app_id=%s AND status='active'"
                ") candidates ORDER BY client_id",
                (
                    enterprise.deployment.tenant_id,
                    external_tenant_id,
                    external_app_id,
                    binding["tenant_id"] if binding else enterprise.deployment.tenant_id,
                    binding["tenant_id"] if binding else enterprise.deployment.tenant_id,
                    str(external_tenant_id),
                    str(external_app_id),
                ),
            )
        ).fetchall()
        checked_at = (await (await c.execute("SELECT clock_timestamp() AS checked_at")).fetchone())[
            "checked_at"
        ]
    if not target:
        return "missing"
    if not binding:
        return "pending_binding"

    resolver = getattr(enterprise, "eduplus2_resolver", None)
    result_status = "unknown"
    verified_client = ""
    etag = ""
    negatives = 0
    incomplete = False
    contradictory = False
    for row in clients:
        client_id = row["client_id"]
        try:
            if resolver is None:
                raise RuntimeError("online resolver is unavailable")
            result = await resolver.resolve_client(client_id, expected_tenant_id=external_tenant_id)
        except PermissionError as exc:
            if str(exc) in _KNOWN_INACTIVE:
                negatives += 1
            else:
                incomplete = True
            continue
        except (LookupError, RuntimeError, TimeoutError):
            incomplete = True
            continue
        if not isinstance(result, dict) or not _current_active_binding(
            result, client_id, external_tenant_id, external_app_id
        ):
            contradictory = True
            continue
        if verified_client and verified_client != client_id:
            # 多个当前 client 可能合法；稳定目标相同才允许。此处均已核验目标。
            pass
        verified_client = client_id
        etag = str(result.get("version") or "")[:255]
    if verified_client and not contradictory:
        result_status = "allowed"
    elif not verified_client and clients and negatives == len(clients) and not incomplete:
        result_status = "denied"
    proof_ttl = int(getattr(enterprise, "eduplus2_lifecycle_proof_ttl_seconds", 30) or 30)
    proof_ttl = max(1, min(proof_ttl, 60))
    proof_expires_at = (
        checked_at + timedelta(seconds=proof_ttl) if result_status == "allowed" else None
    )

    async with enterprise.db.transaction(scope) as c:
        current_time = (
            await (await c.execute("SELECT clock_timestamp() AS current_time")).fetchone()
        )["current_time"]
        if result_status == "allowed" and current_time >= proof_expires_at:
            result_status = "unknown"
            proof_expires_at = None
        current = await (
            await c.execute(
                "SELECT generation,proof_checked_at FROM eduplus2.lifecycle_targets "
                "WHERE tenant_id=%s AND external_tenant_id=%s AND external_app_id=%s FOR UPDATE",
                (enterprise.deployment.tenant_id, external_tenant_id, external_app_id),
            )
        ).fetchone()
        still_bound = await (
            await c.execute(
                "SELECT version FROM oms.school_bindings WHERE tenant_id=%s "
                "AND eduplus_tenant_id=%s AND status='verified'",
                (binding["tenant_id"], external_tenant_id),
            )
        ).fetchone()
        if (
            not current
            or current["generation"] != target["generation"]
            or current["proof_checked_at"] is not None
            and current["proof_checked_at"] > checked_at
            or not still_bound
            or still_bound["version"] != binding["version"]
        ):
            return "stale"
        await c.execute(
            "UPDATE eduplus2.lifecycle_targets SET eligibility=%s,verified_client_id=%s,"
            "resolve_etag=%s,proof_checked_at=%s,proof_expires_at=%s,binding_version=%s,"
            "retry_count=CASE WHEN %s='unknown' THEN retry_count+1 ELSE 0 END,"
            "last_error_code=CASE WHEN %s='unknown' THEN 'online_unavailable' ELSE '' END,"
            "updated_at=now() "
            "WHERE tenant_id=%s AND external_tenant_id=%s AND external_app_id=%s",
            (
                result_status,
                verified_client if result_status == "allowed" else "",
                etag if result_status == "allowed" else "",
                checked_at,
                proof_expires_at,
                binding["version"] if result_status == "allowed" else 0,
                result_status,
                result_status,
                enterprise.deployment.tenant_id,
                external_tenant_id,
                external_app_id,
            ),
        )
        await c.execute(
            "UPDATE enterprise.tenants SET external_eligibility=%s,"
            "external_version=external_version+1 "
            "WHERE id=%s AND external_tid=%s AND external_eligibility<>%s",
            (
                "allowed" if result_status == "allowed" else "denied",
                binding["tenant_id"],
                str(external_tenant_id),
                "allowed" if result_status == "allowed" else "denied",
            ),
        )
        await c.execute(
            "UPDATE eduplus2.lifecycle_inbox SET processing_status=%s,processed_at=now(),"
            "retry_count=CASE WHEN %s='unknown' THEN retry_count+1 ELSE retry_count END,"
            "last_error_code=CASE WHEN %s='unknown' THEN 'online_unavailable' ELSE '' END "
            "WHERE tenant_id=%s AND external_tenant_id=%s AND external_app_id=%s "
            "AND processing_status IN ('pending_binding','pending_reconcile','retry')",
            (
                "verified"
                if result_status == "allowed"
                else "denied"
                if result_status == "denied"
                else "retry",
                result_status,
                result_status,
                enterprise.deployment.tenant_id,
                external_tenant_id,
                external_app_id,
            ),
        )
        actor_issuer = str(getattr(enterprise, "eduplus2_issuer", "") or "").strip()
        if 0 < len(actor_issuer) <= 255:
            await c.execute(
                "INSERT INTO eduplus2.lifecycle_actor_candidates("
                "tenant_id,event_id,school_id,external_tenant_id,external_app_id,"
                "external_subscription_id,binding_version,actor_issuer,actor_subject) "
                "SELECT i.tenant_id,i.event_id,%s,i.external_tenant_id,i.external_app_id,"
                "i.external_subscription_id,%s,%s,i.actor_subject "
                "FROM eduplus2.lifecycle_inbox i "
                "WHERE i.tenant_id=%s AND i.external_tenant_id=%s AND i.external_app_id=%s "
                "AND i.event_type='subscription.created' AND i.actor_type='user' "
                "AND i.actor_subject<>'' "
                "AND EXISTS (SELECT 1 FROM enterprise.tenants t "
                "WHERE t.id=%s AND NOT t.bootstrap_completed) "
                "ON CONFLICT (tenant_id,event_id) DO NOTHING",
                (
                    binding["tenant_id"],
                    binding["version"],
                    actor_issuer,
                    enterprise.deployment.tenant_id,
                    external_tenant_id,
                    external_app_id,
                    binding["tenant_id"],
                ),
            )
    return result_status


async def reconcile_due_lifecycle_targets(enterprise, *, batch_size: int = 32) -> int:
    """扫描已绑定学校的待处理/到期证明；未知学校不在此处自动绑定。"""

    app_id = int(getattr(enterprise, "eduplus2_webhook_app_id", 0) or 0)
    if app_id <= 0:
        raise RuntimeError("lifecycle application is not configured")
    if type(batch_size) is not int or not 1 <= batch_size <= 128:
        raise ValueError("invalid lifecycle batch size")
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@eduplus2-reconcile")
    async with enterprise.db.transaction(scope) as c:
        await c.execute(
            "INSERT INTO eduplus2.lifecycle_targets(tenant_id,external_tenant_id,"
            "external_app_id,generation,eligibility) "
            "SELECT %s,b.eduplus_tenant_id,%s,1,'unknown' "
            "FROM oms.school_bindings b JOIN enterprise.tenants t ON t.id=b.tenant_id "
            "WHERE b.status='verified' AND t.external_tid=b.eduplus_tenant_id::text "
            "ON CONFLICT (tenant_id,external_tenant_id,external_app_id) DO NOTHING",
            (enterprise.deployment.tenant_id, app_id),
        )
        due = await (
            await c.execute(
                "SELECT p.external_tenant_id,p.external_app_id "
                "FROM eduplus2.lifecycle_targets p "
                "JOIN oms.school_bindings b ON b.eduplus_tenant_id=p.external_tenant_id "
                "AND b.status='verified' "
                "JOIN enterprise.tenants t ON t.id=b.tenant_id "
                "AND t.external_tid=p.external_tenant_id::text "
                "WHERE p.tenant_id=%s AND p.external_app_id=%s AND ("
                "(p.eligibility='allowed' "
                "AND p.proof_expires_at<=now()+interval '5 seconds') OR "
                "(p.eligibility<>'allowed' AND (p.retry_count=0 OR "
                "p.updated_at<=now()-make_interval(secs=>"
                "power(2,least(p.retry_count,6))::integer)))) "
                "ORDER BY p.updated_at,p.external_tenant_id LIMIT %s",
                (enterprise.deployment.tenant_id, app_id, batch_size),
            )
        ).fetchall()
    processed = 0
    for target in due:
        outcome = await reconcile_lifecycle_target(
            enterprise,
            external_tenant_id=target["external_tenant_id"],
            external_app_id=target["external_app_id"],
        )
        if outcome not in {"missing", "pending_binding", "stale"}:
            processed += 1
    return processed


async def snapshot_lifecycle_reconcile_metrics(enterprise) -> dict[str, int]:
    """仅汇总本地对账状态，供内部监测；不暴露学校或事件标识。"""

    scope = TenantScope(str(enterprise.deployment.tenant_id), "@eduplus2-metrics")
    async with enterprise.db.transaction(scope) as c:
        targets = await (
            await c.execute(
                "SELECT "
                "count(*) FILTER (WHERE eligibility='allowed' "
                "AND proof_expires_at>clock_timestamp()) AS allowed,"
                "count(*) FILTER (WHERE eligibility='allowed' "
                "AND proof_expires_at<=clock_timestamp()) AS expired_proofs,"
                "count(*) FILTER (WHERE eligibility='unknown') AS unknown,"
                "count(*) FILTER (WHERE eligibility='denied') AS denied "
                "FROM eduplus2.lifecycle_targets WHERE tenant_id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
        inbox = await (
            await c.execute(
                "SELECT "
                "count(*) FILTER (WHERE processing_status='pending_binding') "
                "AS pending_binding,"
                "count(*) FILTER (WHERE processing_status='pending_reconcile') "
                "AS pending_reconcile,"
                "count(*) FILTER (WHERE processing_status='retry') AS retry "
                "FROM eduplus2.lifecycle_inbox WHERE tenant_id=%s",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
        actor = await (
            await c.execute(
                "SELECT count(*) AS pending_actor_candidates "
                "FROM eduplus2.lifecycle_actor_candidates "
                "WHERE tenant_id=%s AND status='pending_verification'",
                (enterprise.deployment.tenant_id,),
            )
        ).fetchone()
    return {key: int(value) for row in (targets, inbox, actor) for key, value in row.items()}
