"""OMS 全局模型目录；草稿与发布均只保存 Secret 引用。"""

from __future__ import annotations

from collections.abc import Sequence
import inspect
from uuid import uuid4

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.scope import GlobalScope, TenantScope

from ..configuration import ModelDeployment
from ..management.authorization import ManagementIdentity, require_management_permission
from ..model_catalog import MODEL_CATALOG_SETTING_KEY


class ModelDraftConflict(ValueError):
    """目录版本或模型 ID 与当前事实冲突。"""


class ModelPublishUnavailable(RuntimeError):
    """目标执行者无法确认新模型配置，active 必须保持旧版本。"""


def _catalog_from_models(models: Sequence[ModelDeployment]) -> dict:
    return {"models": [model.model_dump(mode="json") for model in models]}


def _models_from_catalog(catalog: dict) -> tuple[ModelDeployment, ...]:
    models = catalog.get("models")
    if not isinstance(models, list) or not models:
        raise RuntimeError("model catalog has no usable models")
    parsed = tuple(ModelDeployment.model_validate(model) for model in models)
    _validate_models(parsed)
    return parsed


def _validate_models(models: Sequence[ModelDeployment]) -> None:
    if not 1 <= len(models) <= 32 or any(
        not isinstance(model, ModelDeployment) for model in models
    ):
        raise ValueError("invalid OMS model catalog")
    keys = [(model.profile_id, model.model_id) for model in models]
    if len(keys) != len(set(keys)):
        raise ModelDraftConflict("model profile and model ID must be unique")


def redacted_model_items(catalog: dict, *, source: str, status: str) -> list[dict[str, object]]:
    """面向 OMS API 的模型清单；绝不输出 endpoint 或 Secret ref。"""

    models = catalog.get("models")
    if not isinstance(models, list):
        return []
    return [
        {
            "profile_id": model.get("profile_id"),
            "model_id": model.get("model_id"),
            "model": model.get("model"),
            "provider": model.get("provider"),
            "source": source,
            "managed": True,
            "status": status,
        }
        for model in models
        if isinstance(model, dict)
    ]


def _target_executors(enterprise) -> tuple[str, ...]:
    configured = getattr(enterprise, "oms_model_publish_executors", ("backend",))
    if isinstance(configured, str):
        configured = (configured,)
    executors = tuple(str(item).strip() for item in configured or ())
    if not executors or any(not item or len(item) > 64 for item in executors):
        raise RuntimeError("model target executors are invalid")
    if len(set(executors)) != len(executors):
        raise RuntimeError("model target executors must be unique")
    return executors


async def _confirm_model_catalog(enterprise, models: Sequence[ModelDeployment]) -> tuple[str, ...]:
    """逐目标执行者确认可装载；默认 backend 走真实配置解析。"""

    confirmed: list[str] = []
    hook = getattr(enterprise, "oms_model_confirmation_hook", None)
    for executor in _target_executors(enterprise):
        for model in models:
            enterprise.configuration.resolve_model_deployment(model)
        if hook is not None:
            outcome = hook(executor, tuple(models))
            if inspect.isawaitable(outcome):
                outcome = await outcome
            if outcome is False:
                raise RuntimeError("model executor rejected catalog")
        confirmed.append(executor)
    return tuple(confirmed)


async def save_global_model_draft(
    enterprise,
    actor: ManagementIdentity,
    *,
    models: Sequence[ModelDeployment],
    expected_version: int,
    reason: str,
    request_id: str,
) -> int:
    """同一事务内复核本产品权限、CAS 更新草稿并追加脱敏审计。"""

    if (
        actor.application != "oms"
        or type(expected_version) is not int
        or expected_version < 0
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ValueError("invalid OMS model draft")
    _validate_models(models)
    catalog = _catalog_from_models(models)
    async with enterprise.db.transaction(GlobalScope("@oms-model-draft")) as c:
        await require_management_permission(c, actor, "ops.providers.manage", write=True)
        current = await (
            await c.execute(
                "SELECT version FROM oms.model_catalog_config WHERE id='global' FOR UPDATE"
            )
        ).fetchone()
        if current is None:
            if expected_version != 0:
                raise ModelDraftConflict("model catalog version changed")
            version = 1
            await c.execute(
                "INSERT INTO oms.model_catalog_config"
                "(id,version,desired,updated_by) VALUES('global',1,%s,%s)",
                (Jsonb(catalog), actor.subject),
            )
        else:
            if current["version"] != expected_version:
                raise ModelDraftConflict("model catalog version changed")
            version = expected_version + 1
            await c.execute(
                "UPDATE oms.model_catalog_config SET version=%s,desired=%s,status='saved',"
                "updated_by=%s,updated_at=clock_timestamp() WHERE id='global'",
                (version, Jsonb(catalog), actor.subject),
            )
        await c.execute(
            "INSERT INTO management.audit_events"
            "(id,application,actor_issuer,actor_subject,action_key,target_kind,target_id,"
            "request_id,result,reason,before_version,after_version,safe_summary) "
            "VALUES(%s,'oms',%s,%s,'ops.providers.manage','model_catalog','global',"
            "%s,'success',%s,%s,%s,%s)",
            (
                uuid4(),
                actor.issuer,
                actor.subject,
                request_id.strip(),
                reason.strip(),
                expected_version,
                version,
                Jsonb({"model_count": len(models), "status": "saved"}),
            ),
        )
    return version


async def test_global_model_catalog(
    enterprise,
    actor: ManagementIdentity,
    *,
    expected_version: int,
    reason: str,
    request_id: str,
) -> dict[str, object]:
    """确认草稿可被目标执行者装载，但不写 active。"""

    if (
        actor.application != "oms"
        or type(expected_version) is not int
        or expected_version < 1
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ValueError("invalid OMS model test")
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@oms-model-test")
    confirmed_executors: tuple[str, ...] = ()
    confirmation_error: BaseException | None = None
    result: dict[str, object] | None = None
    async with enterprise.db.transaction(scope) as c:
        await require_management_permission(c, actor, "ops.providers.manage", write=True)
        current = await (
            await c.execute(
                "SELECT version,desired FROM oms.model_catalog_config WHERE id='global' FOR UPDATE"
            )
        ).fetchone()
        if current is None or current["version"] != expected_version:
            raise ModelDraftConflict("model catalog version changed")
        catalog = current["desired"]
        if not isinstance(catalog, dict):
            raise RuntimeError("model catalog is invalid")
        models = _models_from_catalog(catalog)
        try:
            confirmed_executors = await _confirm_model_catalog(enterprise, models)
        except (RuntimeError, ValueError) as exc:
            confirmation_error = exc
        version = expected_version + 1
        status = "failed" if confirmation_error else "tested"
        await c.execute(
            "UPDATE oms.model_catalog_config SET version=%s,status=%s,"
            "updated_by=%s,updated_at=clock_timestamp() WHERE id='global'",
            (version, status, actor.subject),
        )
        await c.execute(
            "INSERT INTO management.audit_events"
            "(id,application,actor_issuer,actor_subject,action_key,target_kind,target_id,"
            "request_id,result,reason,before_version,after_version,safe_summary) "
            "VALUES(%s,'oms',%s,%s,'ops.providers.manage','model_catalog','global',"
            "%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                actor.issuer,
                actor.subject,
                request_id.strip(),
                "failed" if confirmation_error else "success",
                reason.strip(),
                expected_version,
                version,
                Jsonb(
                    {
                        "model_count": len(models),
                        "status": status,
                        "confirmed_executors": list(confirmed_executors),
                    }
                ),
            ),
        )
        result = {
            "version": version,
            "status": status,
            "confirmed_executors": list(confirmed_executors),
        }
    if confirmation_error is not None:
        raise ModelPublishUnavailable("model catalog confirmation failed") from confirmation_error
    if result is None:
        raise RuntimeError("model catalog test did not produce a result")
    return result


async def publish_global_model_catalog(
    enterprise,
    actor: ManagementIdentity,
    *,
    expected_version: int,
    reason: str,
    request_id: str,
) -> dict[str, object]:
    """将已保存草稿发布为执行者可读取的 active 配置。

    当前切片只有同进程 backend 执行者：发布前用真实解析路径确认所有模型
    Secret ref 与 transport descriptor 可装载；后续多实例确认可在此事务模型上扩展。
    """

    if (
        actor.application != "oms"
        or type(expected_version) is not int
        or expected_version < 1
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ValueError("invalid OMS model publish")
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@oms-model-publish")
    confirmed_executors: tuple[str, ...] = ()
    confirmation_error: BaseException | None = None
    result: dict[str, object] | None = None
    async with enterprise.db.transaction(scope) as c:
        await require_management_permission(c, actor, "ops.providers.manage", write=True)
        current = await (
            await c.execute(
                "SELECT version,desired FROM oms.model_catalog_config WHERE id='global' FOR UPDATE"
            )
        ).fetchone()
        if current is None or current["version"] != expected_version:
            raise ModelDraftConflict("model catalog version changed")
        catalog = current["desired"]
        if not isinstance(catalog, dict):
            raise RuntimeError("model catalog is invalid")
        models = _models_from_catalog(catalog)
        try:
            confirmed_executors = await _confirm_model_catalog(enterprise, models)
        except (RuntimeError, ValueError) as exc:
            confirmation_error = exc
            version = expected_version + 1
            await c.execute(
                "UPDATE oms.model_catalog_config SET version=%s,status='failed',"
                "updated_by=%s,updated_at=clock_timestamp() WHERE id='global'",
                (version, actor.subject),
            )
            await c.execute(
                "INSERT INTO management.audit_events"
                "(id,application,actor_issuer,actor_subject,action_key,target_kind,target_id,"
                "request_id,result,reason,before_version,after_version,safe_summary) "
                "VALUES(%s,'oms',%s,%s,'ops.providers.manage','model_catalog','global',"
                "%s,'failed',%s,%s,%s,%s)",
                (
                    uuid4(),
                    actor.issuer,
                    actor.subject,
                    request_id.strip(),
                    reason.strip(),
                    expected_version,
                    version,
                    Jsonb({"model_count": len(models), "status": "failed"}),
                ),
            )
        if confirmation_error is None:
            version = expected_version + 1
            await c.execute(
                "UPDATE oms.model_catalog_config SET version=%s,active_version=%s,"
                "active=desired,status='active',updated_by=%s,updated_at=clock_timestamp() "
                "WHERE id='global'",
                (version, expected_version, actor.subject),
            )
            await c.execute(
                "INSERT INTO enterprise.runtime_settings"
                "(tenant_id,scope_kind,scope_id,key,version,desired,active,status,updated_by) "
                "VALUES(%s,'tenant','',%s,1,%s,%s,'active',%s) "
                "ON CONFLICT (tenant_id,scope_kind,scope_id,key) DO UPDATE "
                "SET desired=EXCLUDED.desired,active=EXCLUDED.active,status='active',"
                "version=enterprise.runtime_settings.version+1,updated_by=EXCLUDED.updated_by,"
                "updated_at=clock_timestamp()",
                (
                    enterprise.deployment.tenant_id,
                    MODEL_CATALOG_SETTING_KEY,
                    Jsonb(catalog),
                    Jsonb(catalog),
                    actor.subject,
                ),
            )
            await c.execute(
                "INSERT INTO management.audit_events"
                "(id,application,actor_issuer,actor_subject,action_key,target_kind,target_id,"
                "request_id,result,reason,before_version,after_version,safe_summary) "
                "VALUES(%s,'oms',%s,%s,'ops.providers.manage','model_catalog','global',"
                "%s,'success',%s,%s,%s,%s)",
                (
                    uuid4(),
                    actor.issuer,
                    actor.subject,
                    request_id.strip(),
                    reason.strip(),
                    expected_version,
                    version,
                    Jsonb(
                        {
                            "model_count": len(models),
                            "status": "active",
                            "active_version": expected_version,
                            "confirmed_executors": list(confirmed_executors),
                        }
                    ),
                ),
            )
            result = {
                "version": version,
                "active_version": expected_version,
                "status": "active",
                "confirmed_executors": list(confirmed_executors),
            }
    if confirmation_error is not None:
        raise ModelPublishUnavailable("model catalog confirmation failed") from confirmation_error
    if result is None:
        raise RuntimeError("model catalog publish did not produce a result")
    return result


async def rollback_global_model_catalog(
    enterprise,
    actor: ManagementIdentity,
    *,
    expected_version: int,
    reason: str,
    request_id: str,
) -> dict[str, object]:
    """丢弃未生效草稿/失败状态，恢复 desired 到当前 active。"""

    if (
        actor.application != "oms"
        or type(expected_version) is not int
        or expected_version < 1
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ValueError("invalid OMS model rollback")
    scope = TenantScope(str(enterprise.deployment.tenant_id), "@oms-model-rollback")
    async with enterprise.db.transaction(scope) as c:
        await require_management_permission(c, actor, "ops.providers.manage", write=True)
        current = await (
            await c.execute(
                "SELECT version,active_version,active FROM oms.model_catalog_config "
                "WHERE id='global' FOR UPDATE"
            )
        ).fetchone()
        if current is None or current["version"] != expected_version:
            raise ModelDraftConflict("model catalog version changed")
        active = current["active"]
        if not isinstance(active, dict) or not active:
            raise ModelDraftConflict("model catalog has no active version")
        # 复验 active 仍为合法目录；回退不得把坏草稿复制成 active。
        _models_from_catalog(active)
        version = expected_version + 1
        await c.execute(
            "UPDATE oms.model_catalog_config SET version=%s,desired=active,status='active',"
            "updated_by=%s,updated_at=clock_timestamp() WHERE id='global'",
            (version, actor.subject),
        )
        await c.execute(
            "INSERT INTO management.audit_events"
            "(id,application,actor_issuer,actor_subject,action_key,target_kind,target_id,"
            "request_id,result,reason,before_version,after_version,safe_summary) "
            "VALUES(%s,'oms',%s,%s,'ops.providers.manage','model_catalog','global',"
            "%s,'success',%s,%s,%s,%s)",
            (
                uuid4(),
                actor.issuer,
                actor.subject,
                request_id.strip(),
                reason.strip(),
                expected_version,
                version,
                Jsonb(
                    {
                        "status": "active",
                        "active_version": current["active_version"],
                        "rollback": "discard_desired",
                    }
                ),
            ),
        )
    return {
        "version": version,
        "active_version": current["active_version"],
        "status": "active",
    }
