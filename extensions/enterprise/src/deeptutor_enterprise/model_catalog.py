"""企业模型目录：PG 保存 profile 与 secret ref，Secret provider 保存 key 明文。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from psycopg.types.json import Jsonb

from .configuration import ModelDeployment

MODEL_CATALOG_SETTING_KEY = "model_catalog"


def _provider(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"anthropic"}:
        return "anthropic"
    # DeepTutor core/local catalog 常见 binding: dashscope/openai_compat/openai。
    # 企业 ModelDeployment 只区分 wire provider；OpenAI-compatible 均走 openai。
    return "openai"


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _roles(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        roles = tuple(str(item).strip() for item in value if str(item).strip())
        if roles:
            return roles
    return ("user", "tenant_admin")


def _user_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


async def _secret_reference(store, name: str) -> str:
    async with store.db.transaction(store.scope) as c:
        row = await (
            await c.execute(
                "SELECT provider,reference,status FROM enterprise.secret_references "
                "WHERE tenant_id=%s AND scope_kind='tenant' AND scope_id='' AND name=%s "
                "AND status IN ('active','saved') ORDER BY updated_at DESC LIMIT 1",
                (store.scope.tenant_id, name),
            )
        ).fetchone()
    if row is None:
        raise RuntimeError("model secret reference is unavailable")
    if row["provider"] != "env":
        raise RuntimeError("unsupported model secret provider")
    return str(row["reference"] or "").strip()


async def _entry_to_model(store, entry: dict[str, Any]) -> ModelDeployment:
    secret = str(entry.get("secret") or "").strip()
    secret_ref = str(entry.get("secret_ref") or entry.get("secret_name") or "").strip()
    if secret_ref:
        secret = await _secret_reference(store, secret_ref)
    if not secret:
        raise RuntimeError("model secret reference is required")
    payload = {
        "profile_id": str(entry.get("profile_id") or entry.get("profile") or "").strip(),
        "model_id": str(entry.get("model_id") or entry.get("id") or "").strip(),
        "model": str(entry.get("model") or entry.get("name") or "").strip(),
        "base_url": str(entry.get("base_url") or "").strip(),
        "secret": secret,
        "provider": _provider(entry.get("provider") or entry.get("binding")),
        "allowed_roles": _roles(entry.get("allowed_roles")),
        "allowed_user_ids": _user_ids(entry.get("allowed_user_ids")),
        "max_tokens": _int(entry.get("max_tokens"), 4096),
        "context_window": _int(entry.get("context_window"), 32768),
        "request_timeout_seconds": _float(entry.get("request_timeout_seconds"), 90),
        "connect_timeout_seconds": _float(entry.get("connect_timeout_seconds"), 10),
        "max_retries": _int(entry.get("max_retries"), 0),
    }
    return ModelDeployment.model_validate(payload)


def _flat_entries(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    flat = catalog.get("models")
    if isinstance(flat, list):
        return [entry for entry in flat if isinstance(entry, dict)]

    service = (catalog.get("services") or {}).get("llm") if isinstance(catalog.get("services"), dict) else None
    profiles = (service or {}).get("profiles") if isinstance(service, dict) else None
    entries: list[dict[str, Any]] = []
    if not isinstance(profiles, list):
        return entries
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        models = profile.get("models") if isinstance(profile.get("models"), list) else []
        for model in models:
            if not isinstance(model, dict):
                continue
            entries.append(
                {
                    "profile_id": profile.get("id"),
                    "model_id": model.get("id"),
                    "model": model.get("model") or model.get("name"),
                    "base_url": profile.get("base_url"),
                    "secret": profile.get("secret"),
                    "secret_ref": profile.get("secret_ref") or profile.get("secret_name"),
                    "provider": profile.get("provider") or profile.get("binding"),
                    "allowed_roles": profile.get("allowed_roles"),
                    "allowed_user_ids": profile.get("allowed_user_ids"),
                    "max_tokens": model.get("max_tokens") or profile.get("max_tokens"),
                    "context_window": model.get("context_window") or profile.get("context_window"),
                    "request_timeout_seconds": profile.get("request_timeout_seconds"),
                    "connect_timeout_seconds": profile.get("connect_timeout_seconds"),
                    "max_retries": profile.get("max_retries"),
                }
            )
    return entries


async def load_runtime_model_deployments(
    store,
    fallback: Iterable[ModelDeployment],
) -> tuple[ModelDeployment, ...]:
    """加载当前 tenant 的活动模型目录；未配置时回退部署文件。"""

    async with store.db.transaction(store.scope) as c:
        row = await (
            await c.execute(
                "SELECT active,desired,status FROM enterprise.runtime_settings "
                "WHERE tenant_id=%s AND scope_kind='tenant' AND scope_id='' AND key=%s "
                "ORDER BY updated_at DESC LIMIT 1",
                (store.scope.tenant_id, MODEL_CATALOG_SETTING_KEY),
            )
        ).fetchone()
    if row is None:
        return tuple(fallback)
    catalog = row["active"] if row["status"] == "active" and row["active"] else row["desired"]
    if not isinstance(catalog, dict):
        raise RuntimeError("model catalog setting is invalid")
    models = [await _entry_to_model(store, entry) for entry in _flat_entries(catalog)]
    if not models:
        raise RuntimeError("model catalog has no usable model profiles")
    keys = [(model.profile_id, model.model_id) for model in models]
    if len(keys) != len(set(keys)):
        raise RuntimeError("model catalog contains duplicate model selections")
    return tuple(models)


async def save_runtime_model_catalog(store, *, catalog: dict[str, Any], actor_id: str) -> None:
    """测试/维护入口：保存并激活脱敏模型目录。"""

    async with store.db.transaction(store.scope) as c:
        await c.execute(
            "INSERT INTO enterprise.runtime_settings"
            "(tenant_id,scope_kind,scope_id,key,version,desired,active,status,updated_by) "
            "VALUES(%s,'tenant','',%s,1,%s,%s,'active',%s) "
            "ON CONFLICT (tenant_id,scope_kind,scope_id,key) DO UPDATE "
            "SET desired=EXCLUDED.desired,active=EXCLUDED.active,status='active',"
            "version=enterprise.runtime_settings.version+1,updated_by=EXCLUDED.updated_by,"
            "updated_at=now()",
            (
                store.scope.tenant_id,
                MODEL_CATALOG_SETTING_KEY,
                Jsonb(catalog),
                Jsonb(catalog),
                actor_id,
            ),
        )


__all__ = [
    "MODEL_CATALOG_SETTING_KEY",
    "load_runtime_model_deployments",
    "save_runtime_model_catalog",
]
