"""企业运行态知识库可见性：PG/ObjectStore 元数据是权威，不读本地 data。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.services.rag.pipelines.lightrag_server.client import LightRagServerClient
from deeptutor.services.rag.pipelines.lightrag_server.config import (
    DEFAULT_MODE,
    SUPPORTED_MODES,
    LightRagServerConfig,
)

from .configuration import resolve_secret

KNOWLEDGE_BASE_DOCUMENT_KIND = "knowledge_base_document"


@dataclass(frozen=True)
class ExternalizedKnowledgeBase:
    id: str
    label: str
    status: str
    description: str
    document_count: int
    ready_count: int
    mode: str = DEFAULT_MODE


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            data = json.loads(value)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _safe_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in SUPPORTED_MODES else DEFAULT_MODE


def _safe_label(value: Any, fallback: str) -> str:
    label = str(value or "").strip()
    return label or fallback


async def list_externalized_knowledge_bases(store) -> list[ExternalizedKnowledgeBase]:
    """列出当前 owner 在 PG 中登记、对象在 ObjectStore 中持久化的 KB 文档集合。"""

    async with store.db.transaction(store.scope) as c:
        rows = await (
            await c.execute(
                "SELECT resource_id,state,metadata,size_bytes,mime_type,updated_at "
                "FROM enterprise.resource_objects "
                "WHERE tenant_id=%s AND owner_id=%s AND resource_kind=%s "
                "AND state<>'deleted' ORDER BY updated_at DESC,id DESC",
                (*store._owner, KNOWLEDGE_BASE_DOCUMENT_KIND),
            )
        ).fetchall()

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        kb_id = str(row["resource_id"] or "").strip()
        if not kb_id:
            continue
        meta = _metadata(row["metadata"])
        item = grouped.setdefault(
            kb_id,
            {
                "id": kb_id,
                "label": _safe_label(meta.get("kb_label"), kb_id),
                "description": str(meta.get("description") or "").strip(),
                "document_count": 0,
                "ready_count": 0,
                "states": set(),
                "mode": _safe_mode(meta.get("search_mode") or meta.get("mode")),
            },
        )
        if meta.get("kb_label"):
            item["label"] = _safe_label(meta.get("kb_label"), kb_id)
        if meta.get("description") and not item["description"]:
            item["description"] = str(meta.get("description") or "").strip()
        if meta.get("search_mode") or meta.get("mode"):
            item["mode"] = _safe_mode(meta.get("search_mode") or meta.get("mode"))
        item["document_count"] += 1
        if row["state"] == "ready" and str(meta.get("status") or "ready") == "ready":
            item["ready_count"] += 1
        item["states"].add(str(row["state"] or ""))

    result: list[ExternalizedKnowledgeBase] = []
    for kb_id, item in grouped.items():
        ready_count = int(item["ready_count"])
        document_count = int(item["document_count"])
        if ready_count <= 0:
            status = "unavailable"
        elif ready_count != document_count or item["states"] - {"ready"}:
            status = "indexing"
        else:
            status = "ready"
        description = item["description"] or f"已登记到对象存储的知识库，{document_count} 个文档"
        result.append(
            ExternalizedKnowledgeBase(
                id=kb_id,
                label=str(item["label"]),
                status=status,
                description=description,
                document_count=document_count,
                ready_count=ready_count,
                mode=str(item["mode"]),
            )
        )
    result.sort(key=lambda kb: (kb.label.lower(), kb.id))
    return result


async def resolve_requested_knowledge_bases(
    store,
    requested: Iterable[str],
    *,
    rag_enabled: bool,
    lightrag_binding: Any,
) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
    """解析本轮 requested KB；不探测本地文件系统。"""

    names = [str(value).strip() for value in requested if str(value).strip()]
    if not names:
        return [], {}, {}
    if not rag_enabled or lightrag_binding is None:
        return [], {"knowledge_base_unavailable": names}, {}

    visible = {kb.id: kb for kb in await list_externalized_knowledge_bases(store)}
    resolved: list[str] = []
    unavailable: dict[str, list[str]] = {}
    modes: dict[str, str] = {}
    for name in names:
        kb = visible.get(name)
        if kb is None:
            unavailable.setdefault("knowledge_base_unavailable", []).append(name)
        elif kb.status != "ready":
            unavailable.setdefault("knowledge_base_unavailable", []).append(name)
        else:
            resolved.append(name)
            modes[name] = kb.mode
    return resolved, unavailable, modes


class EnterpriseLightRAGTool(BaseTool):
    """受控企业 turn 使用的 RAG 工具；直接调用部署绑定的 LightRAG Server。"""

    def __init__(self, *, binding, allowed_kbs: Iterable[str], modes: dict[str, str]) -> None:
        self._binding = binding
        self._allowed_kbs = {str(kb).strip() for kb in allowed_kbs if str(kb).strip()}
        self._modes = {key: _safe_mode(value) for key, value in modes.items()}

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="rag",
            description=(
                "检索本轮已选择的知识库内容。kb_name 必须来自用户在本轮选择的知识库。"
            ),
            parameters=[
                ToolParameter(name="query", type="string", description="Search query."),
                ToolParameter(
                    name="kb_name",
                    type="string",
                    description="Knowledge base selected for this turn.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        kb_name = str(kwargs.get("kb_name") or "").strip()
        if not query:
            raise ValueError("RAG query must be a non-empty string.")
        if kb_name not in self._allowed_kbs:
            raise ValueError("Knowledge base is not attached to this turn.")

        api_key = resolve_secret(self._binding.api_secret)
        config = LightRagServerConfig(base_url=self._binding.endpoint, api_key=api_key)
        mode = self._modes.get(kb_name) or DEFAULT_MODE
        result = await LightRagServerClient(config).query_context(query, mode)
        content = str(result.get("content") or "")
        sources = [
            {"type": "rag", "kb_name": kb_name, **source}
            for source in (result.get("sources") or [])
            if isinstance(source, dict)
        ] or [{"type": "rag", "query": query, "kb_name": kb_name}]
        return ToolResult(
            content=content,
            sources=sources,
            metadata={
                "provider": "lightrag_server",
                "mode": mode,
                "kb_name": kb_name,
                "answer": content,
                "content": content,
                "sources": sources,
            },
        )


__all__ = [
    "EnterpriseLightRAGTool",
    "ExternalizedKnowledgeBase",
    "KNOWLEDGE_BASE_DOCUMENT_KIND",
    "list_externalized_knowledge_bases",
    "resolve_requested_knowledge_bases",
]
