"""OMS 全局模型目录草稿；不发布、不执行模型测试、不接收凭据明文。"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.scope import GlobalScope

from ..configuration import ModelDeployment
from ..management.authorization import ManagementIdentity, require_management_permission


class ModelDraftConflict(ValueError):
    """目录版本或模型 ID 与当前事实冲突。"""


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
        or not 1 <= len(models) <= 32
        or any(not isinstance(model, ModelDeployment) for model in models)
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ValueError("invalid OMS model draft")
    keys = [(model.profile_id, model.model_id) for model in models]
    if len(keys) != len(set(keys)):
        raise ModelDraftConflict("model profile and model ID must be unique")
    catalog = {"models": [model.model_dump(mode="json") for model in models]}
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
