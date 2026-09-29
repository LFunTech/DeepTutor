"""全服务 Provider 设置的应用层校验、版本化配置和旧 JSON 映射 dry-run。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.scope import GlobalScope

from ..configuration import resolve_secret
from ..management.authorization import ManagementIdentity, require_management_permission

PROVIDER_SETTINGS_CONFIG_KEY = "global"
_REDACTED = "<redacted>"
_SECRET_KEYS = {"secret", "api_key", "apiSecret", "client_secret", "access_key", "secret_key"}
_KNOWN_SECTIONS = {
    "connections",
    "models",
    "task_models",
    "embedding",
    "search",
    "tts",
    "stt",
    "image",
    "video",
    "document_parsing",
    "rag",
    "external_agents",
    "tools",
}
_STATUS_VALUES = {"unconfigured", "saved", "tested", "active", "failed"}


class ProviderSettingsConflict(ValueError):
    """Provider 设置版本冲突或当前状态不能执行目标命令。"""


class ProviderSettingsUnavailable(RuntimeError):
    """目标执行者无法确认 Provider 设置。"""


@dataclass(frozen=True, slots=True)
class ProviderSettingsDryRun:
    id: UUID
    source_hash: str
    recognized_sections: tuple[str, ...]
    unsupported_sections: tuple[str, ...]
    secret_paths: tuple[str, ...]
    result: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderSettingsSnapshot:
    version: int
    active_version: int
    status: str
    descriptor_version: int
    settings: dict[str, Any]
    active: dict[str, Any]


def _redact(value: Any, *, path: str = "") -> tuple[Any, list[str]]:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        secret_paths: list[str] = []
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if str(key) in _SECRET_KEYS:
                redacted[str(key)] = _REDACTED if item else ""
                secret_paths.append(child_path)
            else:
                child, child_secrets = _redact(item, path=child_path)
                redacted[str(key)] = child
                secret_paths.extend(child_secrets)
        return redacted, secret_paths
    if isinstance(value, list):
        output = []
        secret_paths = []
        for index, item in enumerate(value):
            child, child_secrets = _redact(item, path=f"{path}[{index}]")
            output.append(child)
            secret_paths.extend(child_secrets)
        return output, secret_paths
    return value, []


def _secret_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("env:") and len(value) > 4


def _walk(value: Any, *, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield child_path, str(key), item
            yield from _walk(item, path=child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, path=f"{path}[{index}]")


def _validate_https_endpoint(value: str, *, path: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"provider settings endpoint is invalid at {path}")


def _validate_provider_settings(settings: dict[str, Any]) -> None:
    if not isinstance(settings, dict):
        raise ValueError("provider settings must be a JSON object")
    if not settings:
        raise ValueError("provider settings must not be empty")
    top_level = {str(key) for key in settings}
    unsupported = sorted(top_level - _KNOWN_SECTIONS)
    if unsupported:
        raise ValueError("provider settings contain unsupported sections")
    if not (top_level & _KNOWN_SECTIONS):
        raise ValueError("provider settings contain no supported sections")
    for path, key, value in _walk(settings):
        if key in _SECRET_KEYS and value not in (None, "") and not _secret_ref(value):
            raise ValueError("provider settings secrets must be env: references")
        if key in {"endpoint", "base_url"} and value:
            if not isinstance(value, str):
                raise ValueError(f"provider settings endpoint must be text at {path}")
            _validate_https_endpoint(value, path=path)


def build_provider_settings_dry_run(raw_settings: dict[str, Any]) -> dict[str, Any]:
    """把本地 JSON 设置映射为 OMS 草稿候选，但只输出脱敏 dry-run。"""

    if not isinstance(raw_settings, dict):
        raise ValueError("provider settings must be a JSON object")
    sanitized, secret_paths = _redact(raw_settings)
    top_level = {str(key) for key in raw_settings}
    recognized = tuple(sorted(top_level & _KNOWN_SECTIONS))
    unsupported = tuple(sorted(top_level - _KNOWN_SECTIONS))
    return {
        "descriptor_version": 1,
        "recognized_sections": list(recognized),
        "unsupported_sections": list(unsupported),
        "secret_paths": sorted(secret_paths),
        "sanitized_preview": sanitized,
        "write_ready": bool(recognized) and not unsupported,
    }


def _snapshot_from_row(row) -> ProviderSettingsSnapshot:
    if row is None:
        return ProviderSettingsSnapshot(
            version=0,
            active_version=0,
            status="unconfigured",
            descriptor_version=1,
            settings={},
            active={},
        )
    desired = row["desired"]
    active = row["active"]
    status = str(row["status"] or "unconfigured")
    if not isinstance(desired, dict) or not isinstance(active, dict) or status not in _STATUS_VALUES:
        raise RuntimeError("provider settings fact is invalid")
    return ProviderSettingsSnapshot(
        version=int(row["version"]),
        active_version=int(row["active_version"]),
        status=status,
        descriptor_version=int(row["descriptor_version"]),
        settings=desired,
        active=active,
    )


def redacted_provider_settings_response(snapshot: ProviderSettingsSnapshot) -> dict[str, Any]:
    desired, desired_secret_paths = _redact(snapshot.settings)
    active, active_secret_paths = _redact(snapshot.active)
    return {
        "config_key": PROVIDER_SETTINGS_CONFIG_KEY,
        "version": snapshot.version,
        "active_version": snapshot.active_version,
        "status": snapshot.status,
        "descriptor_version": snapshot.descriptor_version,
        "settings": desired,
        "active": active,
        "secret_paths": sorted(set(desired_secret_paths)),
        "active_secret_paths": sorted(set(active_secret_paths)),
    }


async def read_provider_settings(enterprise) -> dict[str, Any]:
    async with enterprise.db.transaction(GlobalScope("@oms-provider-settings-read")) as c:
        row = await (
            await c.execute(
                "SELECT version,desired,active,active_version,status,descriptor_version "
                "FROM oms.provider_setting_configs WHERE config_key=%s",
                (PROVIDER_SETTINGS_CONFIG_KEY,),
            )
        ).fetchone()
    return redacted_provider_settings_response(_snapshot_from_row(row))


async def record_provider_settings_dry_run(
    enterprise,
    actor: ManagementIdentity,
    *,
    source_kind: str,
    raw_settings: dict[str, Any],
) -> ProviderSettingsDryRun:
    if actor.application != "oms":
        raise ValueError("provider settings dry-run requires OMS identity")
    if not isinstance(source_kind, str) or not 1 <= len(source_kind.strip()) <= 64:
        raise ValueError("provider settings source kind is invalid")
    result = build_provider_settings_dry_run(raw_settings)
    canonical = json.dumps(raw_settings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    dry_run_id = uuid4()
    async with enterprise.db.transaction(GlobalScope("@oms-provider-settings-dry-run")) as c:
        await require_management_permission(c, actor, "ops.providers.read", write=False)
        await c.execute(
            "INSERT INTO oms.provider_setting_import_dry_runs"
            "(id,source_kind,source_hash,result,created_by) VALUES(%s,%s,%s,%s,%s)",
            (dry_run_id, source_kind.strip(), source_hash, Jsonb(result), actor.subject),
        )
    return ProviderSettingsDryRun(
        id=dry_run_id,
        source_hash=source_hash,
        recognized_sections=tuple(result["recognized_sections"]),
        unsupported_sections=tuple(result["unsupported_sections"]),
        secret_paths=tuple(result["secret_paths"]),
        result=result,
    )


def _target_executors(enterprise) -> tuple[str, ...]:
    configured = getattr(enterprise, "oms_provider_settings_publish_executors", ("backend",))
    if isinstance(configured, str):
        configured = (configured,)
    executors = tuple(str(item).strip() for item in configured or ())
    if not executors or any(not item or len(item) > 64 for item in executors):
        raise RuntimeError("provider setting target executors are invalid")
    if len(set(executors)) != len(executors):
        raise RuntimeError("provider setting target executors must be unique")
    return executors


def _secret_refs(settings: dict[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for _path, key, value in _walk(settings):
        if key in _SECRET_KEYS and _secret_ref(value):
            refs.append(value)
    return tuple(sorted(set(refs)))


async def _confirm_provider_settings(enterprise, settings: dict[str, Any]) -> tuple[str, ...]:
    """逐执行者确认配置可装载；默认 backend 校验 Secret ref 可解析。"""

    _validate_provider_settings(settings)
    confirmed: list[str] = []
    hook = getattr(enterprise, "oms_provider_settings_confirmation_hook", None)
    for executor in _target_executors(enterprise):
        for reference in _secret_refs(settings):
            resolve_secret(reference)
        if hook is not None:
            outcome = hook(executor, settings)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            if outcome is False:
                raise RuntimeError("provider settings executor rejected configuration")
        confirmed.append(executor)
    return tuple(confirmed)


async def save_provider_settings_draft(
    enterprise,
    actor: ManagementIdentity,
    *,
    settings: dict[str, Any],
    expected_version: int,
    reason: str,
    request_id: str,
) -> dict[str, Any]:
    if (
        actor.application != "oms"
        or type(expected_version) is not int
        or expected_version < 0
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ValueError("invalid provider settings draft")
    _validate_provider_settings(settings)
    async with enterprise.db.transaction(GlobalScope("@oms-provider-settings-draft")) as c:
        await require_management_permission(c, actor, "ops.providers.manage", write=True)
        current = await (
            await c.execute(
                "SELECT version FROM oms.provider_setting_configs WHERE config_key=%s FOR UPDATE",
                (PROVIDER_SETTINGS_CONFIG_KEY,),
            )
        ).fetchone()
        if current is None:
            if expected_version != 0:
                raise ProviderSettingsConflict("provider settings version changed")
            version = 1
            await c.execute(
                "INSERT INTO oms.provider_setting_configs"
                "(config_key,version,desired,status,updated_by) VALUES(%s,1,%s,'saved',%s)",
                (PROVIDER_SETTINGS_CONFIG_KEY, Jsonb(settings), actor.subject),
            )
        else:
            if current["version"] != expected_version:
                raise ProviderSettingsConflict("provider settings version changed")
            version = expected_version + 1
            await c.execute(
                "UPDATE oms.provider_setting_configs SET version=%s,desired=%s,status='saved',"
                "updated_by=%s,updated_at=clock_timestamp() WHERE config_key=%s",
                (version, Jsonb(settings), actor.subject, PROVIDER_SETTINGS_CONFIG_KEY),
            )
        await _audit_provider_settings(
            c,
            actor,
            request_id=request_id,
            reason=reason,
            result="success",
            before_version=expected_version,
            after_version=version,
            summary={"section_count": len(settings), "status": "saved"},
        )
    return {"version": version, "status": "saved"}


async def test_provider_settings(
    enterprise,
    actor: ManagementIdentity,
    *,
    expected_version: int,
    reason: str,
    request_id: str,
) -> dict[str, Any]:
    return await _confirm_and_optionally_activate(
        enterprise,
        actor,
        expected_version=expected_version,
        reason=reason,
        request_id=request_id,
        activate=False,
    )


async def publish_provider_settings(
    enterprise,
    actor: ManagementIdentity,
    *,
    expected_version: int,
    reason: str,
    request_id: str,
) -> dict[str, Any]:
    return await _confirm_and_optionally_activate(
        enterprise,
        actor,
        expected_version=expected_version,
        reason=reason,
        request_id=request_id,
        activate=True,
    )


async def _confirm_and_optionally_activate(
    enterprise,
    actor: ManagementIdentity,
    *,
    expected_version: int,
    reason: str,
    request_id: str,
    activate: bool,
) -> dict[str, Any]:
    if (
        actor.application != "oms"
        or type(expected_version) is not int
        or expected_version < 1
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ValueError("invalid provider settings confirmation")
    confirmed_executors: tuple[str, ...] = ()
    confirmation_error: BaseException | None = None
    result: dict[str, Any] | None = None
    async with enterprise.db.transaction(GlobalScope("@oms-provider-settings-confirm")) as c:
        await require_management_permission(c, actor, "ops.providers.manage", write=True)
        current = await (
            await c.execute(
                "SELECT version,desired FROM oms.provider_setting_configs "
                "WHERE config_key=%s FOR UPDATE",
                (PROVIDER_SETTINGS_CONFIG_KEY,),
            )
        ).fetchone()
        if current is None or current["version"] != expected_version:
            raise ProviderSettingsConflict("provider settings version changed")
        settings = current["desired"]
        if not isinstance(settings, dict):
            raise RuntimeError("provider settings are invalid")
        try:
            confirmed_executors = await _confirm_provider_settings(enterprise, settings)
        except (RuntimeError, ValueError) as exc:
            confirmation_error = exc
        status = "failed" if confirmation_error else ("active" if activate else "tested")
        version = expected_version + 1
        if activate and confirmation_error is None:
            await c.execute(
                "UPDATE oms.provider_setting_configs SET version=%s,active_version=%s,"
                "active=desired,status='active',updated_by=%s,updated_at=clock_timestamp() "
                "WHERE config_key=%s",
                (version, expected_version, actor.subject, PROVIDER_SETTINGS_CONFIG_KEY),
            )
        else:
            await c.execute(
                "UPDATE oms.provider_setting_configs SET version=%s,status=%s,"
                "updated_by=%s,updated_at=clock_timestamp() WHERE config_key=%s",
                (version, status, actor.subject, PROVIDER_SETTINGS_CONFIG_KEY),
            )
        await c.execute(
            "DELETE FROM oms.provider_setting_confirmations WHERE config_key=%s AND version=%s",
            (PROVIDER_SETTINGS_CONFIG_KEY, expected_version),
        )
        now = datetime.now(timezone.utc)
        for executor in confirmed_executors:
            await c.execute(
                "INSERT INTO oms.provider_setting_confirmations"
                "(config_key,version,executor_id,status,observed_at,safe_summary) "
                "VALUES(%s,%s,%s,'confirmed',%s,%s)",
                (
                    PROVIDER_SETTINGS_CONFIG_KEY,
                    expected_version,
                    executor,
                    now,
                    Jsonb({"section_count": len(settings), "activated": activate}),
                ),
            )
        await _audit_provider_settings(
            c,
            actor,
            request_id=request_id,
            reason=reason,
            result="failed" if confirmation_error else "success",
            before_version=expected_version,
            after_version=version,
            summary={
                "section_count": len(settings),
                "status": status,
                "active_version": expected_version if activate and confirmation_error is None else None,
                "confirmed_executors": list(confirmed_executors),
            },
        )
        result = {
            "version": version,
            "status": status,
            "confirmed_executors": list(confirmed_executors),
        }
        if activate and confirmation_error is None:
            result["active_version"] = expected_version
    if confirmation_error is not None:
        raise ProviderSettingsUnavailable("provider settings confirmation failed") from confirmation_error
    if result is None:
        raise RuntimeError("provider settings confirmation did not produce a result")
    return result


async def rollback_provider_settings(
    enterprise,
    actor: ManagementIdentity,
    *,
    expected_version: int,
    reason: str,
    request_id: str,
) -> dict[str, Any]:
    if (
        actor.application != "oms"
        or type(expected_version) is not int
        or expected_version < 1
        or not isinstance(reason, str)
        or not 1 <= len(reason.strip()) <= 1000
        or not isinstance(request_id, str)
        or not 1 <= len(request_id.strip()) <= 128
    ):
        raise ValueError("invalid provider settings rollback")
    async with enterprise.db.transaction(GlobalScope("@oms-provider-settings-rollback")) as c:
        await require_management_permission(c, actor, "ops.providers.manage", write=True)
        current = await (
            await c.execute(
                "SELECT version,active_version,active FROM oms.provider_setting_configs "
                "WHERE config_key=%s FOR UPDATE",
                (PROVIDER_SETTINGS_CONFIG_KEY,),
            )
        ).fetchone()
        if current is None or current["version"] != expected_version:
            raise ProviderSettingsConflict("provider settings version changed")
        active = current["active"]
        if not isinstance(active, dict) or not active:
            raise ProviderSettingsConflict("provider settings have no active version")
        _validate_provider_settings(active)
        version = expected_version + 1
        await c.execute(
            "UPDATE oms.provider_setting_configs SET version=%s,desired=active,status='active',"
            "updated_by=%s,updated_at=clock_timestamp() WHERE config_key=%s",
            (version, actor.subject, PROVIDER_SETTINGS_CONFIG_KEY),
        )
        await _audit_provider_settings(
            c,
            actor,
            request_id=request_id,
            reason=reason,
            result="success",
            before_version=expected_version,
            after_version=version,
            summary={"status": "active", "active_version": current["active_version"]},
        )
    return {"version": version, "active_version": current["active_version"], "status": "active"}


async def _audit_provider_settings(
    connection,
    actor: ManagementIdentity,
    *,
    request_id: str,
    reason: str,
    result: str,
    before_version: int,
    after_version: int,
    summary: dict[str, Any],
) -> None:
    safe_summary = {key: value for key, value in summary.items() if value is not None}
    await connection.execute(
        "INSERT INTO management.audit_events"
        "(id,application,actor_issuer,actor_subject,action_key,target_kind,target_id,"
        "request_id,result,reason,before_version,after_version,safe_summary) "
        "VALUES(%s,'oms',%s,%s,'ops.providers.manage','provider_settings','global',"
        "%s,%s,%s,%s,%s,%s)",
        (
            uuid4(),
            actor.issuer,
            actor.subject,
            request_id.strip(),
            result,
            reason.strip(),
            before_version,
            after_version,
            Jsonb(safe_summary),
        ),
    )
