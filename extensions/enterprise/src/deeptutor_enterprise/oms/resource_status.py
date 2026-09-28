"""OMS 平台资源安全状态投影；只暴露描述符和脱敏条件字段。"""

from __future__ import annotations

from deeptutor.persistence.postgres.scope import GlobalScope

from .model_drafts import redacted_model_items

OMS_RESOURCE_CATEGORIES = (
    "model_external",
    "agent_capability",
    "tool_integration",
    "knowledge_content",
    "runtime",
)


async def build_resource_status(enterprise) -> dict[str, object]:
    """从部署配置与已发布 OMS active 生成脱敏状态，不解析 Secret。"""

    model_items = []
    async with enterprise.db.transaction(GlobalScope("@oms-resource-status")) as c:
        row = await (
            await c.execute(
                "SELECT active,status FROM oms.model_catalog_config WHERE id='global'", ()
            )
        ).fetchone()
    if row and isinstance(row["active"], dict) and row["active"]:
        model_items = redacted_model_items(row["active"], source="oms_active", status="active")
    if not model_items:
        model_items = [
            {
                "profile_id": model.profile_id,
                "model_id": model.model_id,
                "model": model.model,
                "provider": model.provider,
                "source": "deployment",
                "managed": False,
                "status": "readiness_unverified",
            }
            for model in enterprise.deployment.models
        ]

    resources: list[dict[str, object]] = []
    for item in model_items:
        resources.append(
            {
                "id": f"model:{item['profile_id']}:{item['model_id']}",
                "category": "model_external",
                "kind": "chat_model",
                "status": item["status"],
                "managed": item["managed"],
                "display_name": item["model_id"],
                "safe_fields": {
                    "profile_id": item["profile_id"],
                    "model_id": item["model_id"],
                    "provider": item["provider"],
                    "task_fallback": "uses_chat_model_when_task_model_missing",
                },
            }
        )
    resources.extend(
        [
            {
                "id": "model:embedding",
                "category": "model_external",
                "kind": "embedding",
                "status": "not_configured",
                "managed": False,
                "display_name": "Embedding",
                "safe_fields": {
                    "endpoint_contract": "full_https_url_required",
                    "usage_source": "provider_usage_or_reconciliation",
                },
            },
            {
                "id": "media:tts",
                "category": "model_external",
                "kind": "tts",
                "status": "not_configured",
                "managed": False,
                "display_name": "TTS",
                "safe_fields": {
                    "native_unit": "character_or_second",
                    "usage_source": "provider_usage_or_call_count",
                },
            },
            {
                "id": "media:stt",
                "category": "model_external",
                "kind": "stt",
                "status": "not_configured",
                "managed": False,
                "display_name": "STT",
                "safe_fields": {
                    "native_unit": "audio_second",
                    "usage_source": "provider_usage_or_call_count",
                },
            },
            {
                "id": "media:image",
                "category": "model_external",
                "kind": "image_generation",
                "status": "not_configured",
                "managed": False,
                "display_name": "Image",
                "safe_fields": {
                    "native_unit": "image",
                    "async_result": "provider_receipt_required",
                },
            },
            {
                "id": "media:video",
                "category": "model_external",
                "kind": "video_generation",
                "status": "not_configured",
                "managed": False,
                "display_name": "Video",
                "safe_fields": {
                    "native_unit": "second",
                    "async_result": "provider_receipt_required",
                },
            },
        ]
    )

    deployment = enterprise.deployment
    resources.extend(
        [
            {
                "id": "agent:external",
                "category": "agent_capability",
                "kind": "external_agent",
                "status": "not_configured",
                "managed": False,
                "display_name": "外部 Agent 接入",
                "safe_fields": {
                    "contract": "requires_oms_descriptor_and_runtime_adapter",
                    "callable": False,
                },
            },
            {
                "id": "skill:global",
                "category": "agent_capability",
                "kind": "global_skill_catalog",
                "status": "requires_school_grant",
                "managed": True,
                "display_name": "global Skill",
                "safe_fields": {
                    "owner": "global",
                    "tenant_override": "tenant_skill_takes_precedence",
                },
            },
            {
                "id": "tool:web_search",
                "category": "tool_integration",
                "kind": "search",
                "status": "ready" if "web_search" in deployment.allowed_tools else "not_configured",
                "managed": False,
                "display_name": "Web Search",
                "safe_fields": {
                    "usage_source": "provider_response_or_call_count",
                    "hard_quota_allowed": False,
                },
            },
            {
                "id": "tool:mcp",
                "category": "tool_integration",
                "kind": "mcp",
                "status": "not_configured",
                "managed": False,
                "display_name": "MCP 工具",
                "safe_fields": {"requires_tenant_binding": True},
            },
        ]
    )

    lightrag = deployment.lightrag
    object_store = deployment.object_store
    resources.extend(
        [
            {
                "id": "knowledge:lightrag",
                "category": "knowledge_content",
                "kind": "rag",
                "status": "ready" if lightrag and object_store else "unavailable",
                "managed": bool(lightrag),
                "display_name": "LightRAG",
                "safe_fields": {
                    "workspace_binding": lightrag.workspace_binding if lightrag else "",
                    "index_version": lightrag.index_version if lightrag else "",
                    "contract_version": lightrag.contract_version if lightrag else "",
                    "object_store": "configured" if object_store else "missing",
                },
            },
            {
                "id": "knowledge:document_parsing",
                "category": "knowledge_content",
                "kind": "document_parsing",
                "status": "ready" if lightrag else "unavailable",
                "managed": bool(lightrag),
                "display_name": "解析 / OCR",
                "safe_fields": {
                    "execution_owner": "lightrag_server",
                    "derived_storage": "registered_manifest_required",
                },
            },
        ]
    )

    resources.extend(
        [
            {
                "id": "runtime:postgres",
                "category": "runtime",
                "kind": "postgres",
                "status": "ready",
                "managed": True,
                "display_name": "PostgreSQL",
                "safe_fields": {"sqlite_runtime": "forbidden"},
            },
            {
                "id": "runtime:object_store",
                "category": "runtime",
                "kind": "object_store",
                "status": "ready" if object_store else "unavailable",
                "managed": bool(object_store),
                "display_name": "Object Store",
                "safe_fields": {"provider": object_store.provider if object_store else ""},
            },
            {
                "id": "runtime:secret_provider",
                "category": "runtime",
                "kind": "secret_provider",
                "status": "ready" if deployment.secret_provider else "unavailable",
                "managed": bool(deployment.secret_provider),
                "display_name": "Secret Provider",
                "safe_fields": {
                    "kind": deployment.secret_provider.kind if deployment.secret_provider else ""
                },
            },
            {
                "id": "runtime:executor",
                "category": "runtime",
                "kind": "executor",
                "status": "single_instance",
                "managed": True,
                "display_name": "Backend Executor",
                "safe_fields": {
                    "backend_workers": deployment.backend_workers,
                    "ha": False,
                },
            },
        ]
    )
    return {"categories": list(OMS_RESOURCE_CATEGORIES), "resources": resources}
