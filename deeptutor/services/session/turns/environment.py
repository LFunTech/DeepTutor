"""显式装配的文本 turn 依赖边界；没有 provider 时保留独立 local 模式。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from deeptutor.core.context import Attachment
    from deeptutor.services.llm.config import LLMConfig


@dataclass(frozen=True)
class PreparedTurnEnvironment:
    """执行者内存中的受控配置；不得序列化进请求、事件或消息 metadata。"""

    payload: dict[str, Any]
    llm_config: LLMConfig
    chat_params: dict[str, Any]
    allowed_tools: tuple[str, ...] = ("ask_user",)
    resource_attachments: tuple[Attachment, ...] = ()
    summary_agent_params: dict[str, Any] | None = None
    context_resolution: dict[str, Any] | None = None


class TurnEnvironment(Protocol):
    async def prepare_request(
        self,
        payload: dict[str, Any],
        *,
        session: dict[str, Any] | None = None,
    ) -> PreparedTurnEnvironment: ...

    async def authorize_request(
        self,
        action: str,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> None: ...


def validate_text_request(
    payload: dict[str, Any],
    *,
    allowed_tools: tuple[str, ...] | None = ("ask_user",),
) -> None:
    """未装配的资源必须在写 session/turn 或调用模型之前明确拒绝。"""
    if payload.get("capability") not in {None, "chat"}:
        raise ValueError("Requested capability is unavailable in this turn environment")
    resource_fields = (
        "notebook_references",
        "history_references",
        "partner_group_references",
        "question_notebook_references",
        "book_references",
        "reading_references",
        "memory_references",
        "attachments",
        "persona",
        "workspace_mode",
        "mastery_path_id",
        "mastery_session_mode",
        "mastery_answer",
        "mastery_skip",
        "reading_material_id",
        "reading_material_revision",
        "reading_workspace_id",
        "reading_viewport",
        "timed_media_id",
        "timed_media_viewport",
        "course_id",
        "followup_question_context",
        "selection_tutor_context",
        "subagent_consult_budget",
        "auto_route",
        "mastery_path_lease_managed",
    )
    for field in resource_fields:
        if payload.get(field) not in (None, "", False, [], {}):
            raise ValueError(f"Requested resource is unavailable: {field}")
    if allowed_tools is not None and any(
        tool not in set(allowed_tools) for tool in payload.get("tools") or []
    ):
        raise ValueError("Requested tool is unavailable in this turn environment")
    if payload.get("config"):
        raise ValueError("Per-turn configuration overrides are unavailable")


__all__ = ["PreparedTurnEnvironment", "TurnEnvironment", "validate_text_request"]
