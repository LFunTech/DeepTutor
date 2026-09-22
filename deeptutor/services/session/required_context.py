"""Turn-level context policy, validation errors, and safe usage summaries."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any, Literal

from deeptutor.core.stream import StreamEvent, StreamEventType

ContextPolicy = Literal["auto", "best_effort", "required"]
CONTEXT_POLICIES: tuple[ContextPolicy, ...] = ("auto", "best_effort", "required")


class ContextResolutionError(ValueError):
    """Raised when a required turn context cannot be mounted before model use."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "required_context_unavailable",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


def string_list(value: Any) -> list[str]:
    """Normalize protocol list fields into distinct, non-empty strings."""

    if value is None:
        return []
    raw_items = value if isinstance(value, list | tuple | set) else [value]
    seen: set[str] = set()
    out: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def normalize_context_policy(value: Any) -> ContextPolicy:
    text = str(value or "auto").strip().lower()
    if text in CONTEXT_POLICIES:
        return text  # type: ignore[return-value]
    return "auto"


def policy_from_payload(payload: dict[str, Any]) -> ContextPolicy:
    return normalize_context_policy(payload.get("context_policy"))


def requested_context(payload: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "knowledge_bases": string_list(payload.get("knowledge_bases")),
        "skills": string_list(payload.get("skills")),
        "tools": string_list(payload.get("tools")),
        "mcp_tools": string_list(payload.get("mcp_tools")),
        "resource_ids": string_list(payload.get("resource_ids")),
    }


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def redacted_item(kind: str, name: str, *, status: str, code: str = "") -> dict[str, str]:
    text = str(name or "").strip()
    return {
        "kind": kind,
        "name": text[:160],
        "id_hash": _short_hash(text) if text else "",
        "status": str(status or ""),
        "code": str(code or ""),
    }


def initial_context_resolution(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy": policy_from_payload(payload),
        "requested": requested_context(payload),
        "resolved": {
            "knowledge_bases": [],
            "skills": [],
            "tools": [],
            "mcp_tools": [],
            "resource_ids": string_list(payload.get("resource_ids")),
        },
        "unavailable": [],
    }


def ensure_context_resolution(metadata: dict[str, Any]) -> dict[str, Any]:
    if {"policy", "requested", "resolved", "unavailable"} <= set(metadata):
        return metadata
    current = metadata.get("context_resolution")
    if isinstance(current, dict):
        current.setdefault("policy", normalize_context_policy(metadata.get("context_policy")))
        current.setdefault(
            "requested",
            {
                "knowledge_bases": string_list(metadata.get("knowledge_bases")),
                "skills": string_list(metadata.get("skills")),
                "tools": string_list(metadata.get("tools")),
                "mcp_tools": string_list(metadata.get("mcp_tools")),
                "resource_ids": string_list(metadata.get("resource_ids")),
            },
        )
        current.setdefault("resolved", {})
        current.setdefault("unavailable", [])
        return current
    payload_like = {
        "context_policy": metadata.get("context_policy"),
        "knowledge_bases": metadata.get("knowledge_bases"),
        "skills": metadata.get("skills"),
        "tools": metadata.get("tools"),
        "mcp_tools": metadata.get("mcp_tools"),
        "resource_ids": metadata.get("resource_ids"),
    }
    resolution = initial_context_resolution(payload_like)
    metadata["context_resolution"] = resolution
    return resolution


def mark_resolved(
    metadata: dict[str, Any],
    key: Literal["knowledge_bases", "skills", "tools", "mcp_tools", "resource_ids"],
    names: list[str],
) -> None:
    resolution = ensure_context_resolution(metadata)
    resolved = resolution.setdefault("resolved", {})
    merged = string_list([*(resolved.get(key) or []), *names])
    resolved[key] = merged


def mark_unavailable(
    metadata: dict[str, Any],
    *,
    kind: str,
    names: list[str],
    code: str,
) -> None:
    if not names:
        return
    resolution = ensure_context_resolution(metadata)
    unavailable = resolution.setdefault("unavailable", [])
    unavailable.extend(redacted_item(kind, name, status="unavailable", code=code) for name in names)


def _status_for_resolution(
    *,
    payload: dict[str, Any],
    kind: str,
    label: str,
    default: str,
) -> str:
    resolution = payload.get("context_resolution")
    if not isinstance(resolution, dict):
        return default
    for item in resolution.get("unavailable") or []:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == kind and item.get("name") == label:
            return "unavailable"
    return default


def initial_capability_usage(
    payload: dict[str, Any],
    *,
    model_label: str = "",
) -> dict[str, Any]:
    """Build a safe per-turn summary for ordinary UI and folded diagnostics."""

    resolution = payload.get("context_resolution")
    policy = (
        normalize_context_policy(resolution.get("policy"))
        if isinstance(resolution, dict)
        else policy_from_payload(payload)
    )
    requested = (
        resolution.get("requested")
        if isinstance(resolution, dict) and isinstance(resolution.get("requested"), dict)
        else {}
    )

    def requested_values(key: str) -> list[str]:
        return string_list(payload.get(key) or requested.get(key))

    items: list[dict[str, Any]] = []
    if model_label:
        items.append({"kind": "model", "label": model_label, "status": "enabled", "count": 0})
    for name in requested_values("knowledge_bases"):
        items.append(
            {
                "kind": "knowledge_base",
                "label": name,
                "status": _status_for_resolution(
                    payload=payload, kind="knowledge_base", label=name, default="enabled"
                ),
                "count": 0,
            }
        )
    for name in requested_values("skills"):
        items.append(
            {
                "kind": "skill",
                "label": name,
                "status": _status_for_resolution(
                    payload=payload, kind="skill", label=name, default="enabled"
                ),
                "count": 0,
            }
        )
    for name in requested_values("tools"):
        items.append(
            {
                "kind": "builtin_tool",
                "label": name,
                "status": _status_for_resolution(
                    payload=payload, kind="tool", label=name, default="enabled"
                ),
                "count": 0,
            }
        )
    for name in requested_values("mcp_tools"):
        items.append(
            {
                "kind": "mcp_tool",
                "label": name,
                "status": _status_for_resolution(
                    payload=payload, kind="mcp_tool", label=name, default="enabled"
                ),
                "count": 0,
            }
        )
    resource_ids = requested_values("resource_ids")
    if resource_ids:
        items.append(
            {
                "kind": "resource",
                "label": f"uploaded_resources:{len(resource_ids)}",
                "status": "sent",
                "count": len(resource_ids),
            }
        )
    if not items:
        items.append({"kind": "chat", "label": "conversation", "status": "enabled", "count": 0})
    return {
        "version": 1,
        "policy": policy,
        "items": items,
        "diagnostics": {
            "context_policy": policy,
            "requested": requested_context(payload),
            "unavailable": [],
        },
    }


def _event_type(event: StreamEvent) -> str:
    return event.type.value if isinstance(event.type, StreamEventType) else str(event.type)


def _metadata(event: StreamEvent) -> dict[str, Any]:
    return event.metadata if isinstance(event.metadata, dict) else {}


def _bump_item(summary: dict[str, Any], *, kind: str, label: str | None = None) -> None:
    for item in summary.get("items") or []:
        if not isinstance(item, dict) or item.get("kind") != kind:
            continue
        if label is not None and item.get("label") != label:
            continue
        item["status"] = "used"
        try:
            item["count"] = int(item.get("count") or 0) + 1
        except (TypeError, ValueError):
            item["count"] = 1


def record_capability_usage_event(summary: dict[str, Any], event: StreamEvent) -> None:
    """Fold trace events into the ordinary per-turn capability usage summary."""

    event_type = _event_type(event)
    metadata = _metadata(event)
    if event_type == StreamEventType.PROGRESS.value and (
        (
            str(metadata.get("trace_kind") or "") == "call_status"
            and str(metadata.get("call_state") or "") == "complete"
        )
        or (
            str(metadata.get("event") or "") == "llm_call"
            and str(metadata.get("state") or "") in {"streaming", "complete"}
        )
    ):
        model = str(metadata.get("model") or "").strip()
        _bump_item(summary, kind="model", label=model or None)
    elif event_type == StreamEventType.TOOL_CALL.value:
        tool_name = str(event.content or "").strip()
        _bump_item(summary, kind="builtin_tool", label=tool_name)
        _bump_item(summary, kind="mcp_tool", label=tool_name)
        if tool_name in {"rag", "kb_files"}:
            _bump_item(summary, kind="knowledge_base")
        if tool_name in {"read_skill", "load_skill", "load_skills"}:
            args = metadata.get("args")
            if isinstance(args, dict):
                skill = str(args.get("name") or args.get("skill") or "").strip()
                _bump_item(summary, kind="skill", label=skill or None)
            else:
                _bump_item(summary, kind="skill")
    elif event_type == StreamEventType.SOURCES.value:
        _bump_item(summary, kind="knowledge_base")


def finalized_capability_usage(summary: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with latest resolution diagnostics, without raw payload data."""

    result = deepcopy(summary)
    resolution = metadata.get("context_resolution")
    if isinstance(resolution, dict):
        diagnostics = result.setdefault("diagnostics", {})
        diagnostics["context_policy"] = resolution.get("policy") or result.get("policy")
        diagnostics["requested"] = deepcopy(resolution.get("requested") or {})
        diagnostics["resolved"] = deepcopy(resolution.get("resolved") or {})
        diagnostics["unavailable"] = deepcopy(resolution.get("unavailable") or [])
        unavailable = {
            (str(item.get("kind") or ""), str(item.get("name") or ""))
            for item in resolution.get("unavailable") or []
            if isinstance(item, dict)
        }
        for item in result.get("items") or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "")
            label = str(item.get("label") or "")
            resolution_kind = "tool" if kind == "builtin_tool" else kind
            if (resolution_kind, label) in unavailable:
                item["status"] = "unavailable"
    return result


__all__ = [
    "CONTEXT_POLICIES",
    "ContextPolicy",
    "ContextResolutionError",
    "ensure_context_resolution",
    "finalized_capability_usage",
    "initial_capability_usage",
    "initial_context_resolution",
    "mark_resolved",
    "mark_unavailable",
    "normalize_context_policy",
    "policy_from_payload",
    "record_capability_usage_event",
    "requested_context",
    "string_list",
]
