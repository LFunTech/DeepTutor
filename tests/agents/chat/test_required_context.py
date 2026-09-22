from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.services.session.required_context import (
    ContextResolutionError,
    finalized_capability_usage,
    initial_capability_usage,
    record_capability_usage_event,
)


class FakeMCPTool(BaseTool):
    deferred = True
    provider_kind = "mcp"

    def __init__(self, name: str, provider: str = "lightrag") -> None:
        self._name = name
        self.provider_id = provider

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=f"desc {self._name}",
            raw_parameters={"type": "object", "properties": {}},
        )

    async def execute(self, **kwargs: Any) -> ToolResult:  # pragma: no cover - unused
        return ToolResult(content="ok")


class FakeRegistry:
    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools = {tool.get_definition().name: tool for tool in tools}

    def deferred_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)


class FakeManager:
    async def ensure_started(self) -> None:
        return None

    async def ensure_scope(self, _owner: str) -> list[BaseTool]:
        return []


def _pipe(monkeypatch, tools: list[BaseTool]) -> AgenticChatPipeline:
    monkeypatch.setattr(
        "deeptutor.agents.loop.pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    monkeypatch.setattr("deeptutor.services.mcp.get_mcp_manager", lambda: FakeManager())
    monkeypatch.setattr("deeptutor.services.mcp.load_loaded_tools", lambda _sid: set())
    monkeypatch.setattr("deeptutor.multi_user.tool_access.allowed_mcp_tools", lambda: None)
    pipe = AgenticChatPipeline(language="zh")
    pipe.registry = FakeRegistry(tools)
    return pipe


def test_required_mcp_tools_are_preloaded_before_the_first_model_call(monkeypatch) -> None:
    pipe = _pipe(monkeypatch, [FakeMCPTool("lightrag.query")])
    ctx = UnifiedContext(
        session_id="session-1",
        metadata={"context_policy": "required", "mcp_tools": ["lightrag.query"]},
    )

    asyncio.run(pipe._prepare_deferred_tools(ctx))

    assert pipe._deferred_loader is not None
    assert [schema["function"]["name"] for schema in pipe._deferred_loader.initial_schemas()] == [
        "lightrag.query"
    ]
    assert ctx.metadata["context_resolution"]["resolved"]["mcp_tools"] == ["lightrag.query"]


def test_required_mcp_tool_missing_fails_closed_before_model_call(monkeypatch) -> None:
    pipe = _pipe(monkeypatch, [FakeMCPTool("lightrag.query")])
    ctx = UnifiedContext(
        session_id="session-1",
        metadata={"context_policy": "required", "mcp_tools": ["missing.tool"]},
    )

    with pytest.raises(ContextResolutionError) as exc:
        asyncio.run(pipe._prepare_deferred_tools(ctx))

    assert exc.value.error_code == "mcp_tool_unavailable"
    assert ctx.metadata["context_resolution"]["unavailable"][0]["kind"] == "mcp_tool"


def test_best_effort_mcp_tool_missing_is_recorded_without_failing(monkeypatch) -> None:
    pipe = _pipe(monkeypatch, [FakeMCPTool("lightrag.query")])
    ctx = UnifiedContext(
        session_id="session-1",
        metadata={"context_policy": "best_effort", "mcp_tools": ["missing.tool"]},
    )

    asyncio.run(pipe._prepare_deferred_tools(ctx))

    assert ctx.metadata["context_resolution"]["unavailable"][0]["kind"] == "mcp_tool"
    assert ctx.metadata["context_resolution"]["unavailable"][0]["code"] == "mcp_tool_unavailable"


def test_usage_summary_marks_best_effort_unavailable_items(monkeypatch) -> None:
    pipe = _pipe(monkeypatch, [FakeMCPTool("lightrag.query")])
    ctx = UnifiedContext(
        session_id="session-1",
        metadata={"context_policy": "best_effort", "mcp_tools": ["missing.tool"]},
    )
    summary = initial_capability_usage(
        {"mcp_tools": ["missing.tool"], "context_policy": "best_effort"}
    )

    asyncio.run(pipe._prepare_deferred_tools(ctx))
    finalized = finalized_capability_usage(summary, ctx.metadata)

    assert finalized["items"][0]["status"] == "unavailable"


def test_required_knowledge_base_missing_fails_closed_before_model_call(monkeypatch) -> None:
    from fastapi import HTTPException

    pipe = _pipe(monkeypatch, [])

    def missing_kb(_kb_ref: str, *, require_write: bool = False):
        raise HTTPException(status_code=404)

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb", missing_kb)
    ctx = UnifiedContext(
        session_id="session-1",
        knowledge_bases=["missing-kb"],
        metadata={"context_policy": "required"},
    )

    with pytest.raises(ContextResolutionError) as exc:
        pipe._validate_required_knowledge_bases(ctx)

    assert exc.value.error_code == "knowledge_base_unavailable"
    assert ctx.metadata["context_resolution"]["unavailable"][0]["code"] == (
        "knowledge_base_unavailable"
    )


def test_required_knowledge_base_not_ready_fails_closed_before_model_call(monkeypatch) -> None:
    pipe = _pipe(monkeypatch, [])

    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb",
        lambda _kb_ref, require_write=False: SimpleNamespace(name="warming-up"),
    )
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.manager_for_resource",
        lambda _resource: SimpleNamespace(
            get_kb_entry=lambda _name: {"status": "indexing"}
        ),
    )
    ctx = UnifiedContext(
        session_id="session-1",
        knowledge_bases=["kb-indexing"],
        metadata={"context_policy": "required"},
    )

    with pytest.raises(ContextResolutionError) as exc:
        pipe._validate_required_knowledge_bases(ctx)

    assert exc.value.error_code == "knowledge_base_unavailable"
    assert ctx.metadata["context_resolution"]["unavailable"][0]["name"] == "kb-indexing"


def test_required_knowledge_base_unauthorized_fails_with_authorization_code(monkeypatch) -> None:
    from fastapi import HTTPException

    pipe = _pipe(monkeypatch, [])

    def unauthorized_kb(_kb_ref: str, *, require_write: bool = False):
        raise HTTPException(status_code=403)

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb", unauthorized_kb)
    ctx = UnifiedContext(
        session_id="session-1",
        knowledge_bases=["private-kb"],
        metadata={"context_policy": "required"},
    )

    with pytest.raises(ContextResolutionError) as exc:
        pipe._validate_required_knowledge_bases(ctx)

    assert exc.value.error_code == "context_authorization_failed"
    assert ctx.metadata["context_resolution"]["unavailable"][0]["name"] == "private-kb"


def test_auto_context_usage_does_not_report_unavailable_kb_as_used() -> None:
    summary = initial_capability_usage(
        {"knowledge_bases": ["kb-offline"], "context_policy": "auto"}
    )
    finalized = finalized_capability_usage(
        summary,
        {
            "context_resolution": {
                "policy": "auto",
                "requested": {"knowledge_bases": ["kb-offline"]},
                "resolved": {},
                "unavailable": [
                    {
                        "kind": "knowledge_base",
                        "name": "kb-offline",
                        "code": "knowledge_base_unavailable",
                    }
                ],
            }
        },
    )

    assert finalized["items"][0]["kind"] == "knowledge_base"
    assert finalized["items"][0]["status"] == "unavailable"
    assert finalized["items"][0]["status"] != "used"


def test_usage_summary_marks_model_used_when_llm_call_completes() -> None:
    summary = initial_capability_usage(
        {"content": "hello", "context_policy": "required"},
        model_label="qwen3.8-max",
    )

    record_capability_usage_event(
        summary,
        StreamEvent(
            type=StreamEventType.PROGRESS,
            source="chat",
            stage="responding",
            metadata={
                "trace_kind": "call_status",
                "call_state": "complete",
                "call_id": "chat-responding-1",
            },
        ),
    )

    assert summary["items"][0]["kind"] == "model"
    assert summary["items"][0]["label"] == "qwen3.8-max"
    assert summary["items"][0]["status"] == "used"
    assert summary["items"][0]["count"] == 1


def test_required_builtin_tool_missing_fails_closed_before_model_call(monkeypatch) -> None:
    pipe = _pipe(monkeypatch, [])
    ctx = UnifiedContext(
        session_id="session-1",
        enabled_tools=["rag"],
        metadata={"context_policy": "required"},
    )

    with pytest.raises(ContextResolutionError) as exc:
        pipe._validate_required_builtin_tools(ctx, enabled_tools=[])

    assert exc.value.error_code == "required_context_unavailable"
    assert ctx.metadata["context_resolution"]["unavailable"][0]["kind"] == "tool"

def test_configured_turn_runtime_allows_prepared_rag_tool_for_required_kb() -> None:
    from deeptutor.services.session.turns.configured import ConfiguredTurnRuntime
    from deeptutor.services.session.turns.environment import PreparedTurnEnvironment

    class Store:
        def __init__(self) -> None:
            self.request_payload = None

        async def get_session(self, session_id):
            return None

        async def begin_request(self, payload, operation_id=None):
            self.request_payload = payload
            return {"id": "session-1"}, {"id": "turn-1", "status": "running"}, False

        async def finalize_turn(self, *args, **kwargs):
            return []

    class Environment:
        async def authorize_request(self, action, *, session_id=None, turn_id=None):
            return None

        async def prepare_request(self, payload, *, session=None):
            return PreparedTurnEnvironment(
                {
                    **payload,
                    "tools": ["ask_user", "rag"],
                    "knowledge_bases": ["user:kb:test"],
                    "context_policy": "required",
                    "llm_selection": {"profile_id": "chat", "model_id": "primary"},
                },
                llm_config=SimpleNamespace(model="test-model", max_tokens=128),
                chat_params={"temperature": 0.2, "max_rounds": 8},
                allowed_tools=("ask_user", "rag"),
            )

    class Runtime(ConfiguredTurnRuntime):
        def __init__(self) -> None:
            self.store = Store()
            self.turn_environment = Environment()
            self._lock = asyncio.Lock()
            self._executions = {}
            self._reply_queues = {}

        async def _ensure_accepting_turns(self):
            return None

        def _turns_blocked_for_update_locked(self):
            return False

        async def _run_turn(self, execution):
            return None

    runtime = Runtime()

    session, turn = asyncio.run(
        runtime._start_configured_turn(
            {
                "content": "请使用知识库回答",
                "capability": "chat",
                "knowledge_bases": ["user:kb:test"],
                "context_policy": "required",
            }
        )
    )

    assert session["id"] == "session-1"
    assert turn["id"] == "turn-1"
    execution = runtime._executions["turn-1"]
    assert execution.payload["tools"] == ["ask_user", "rag"]
    assert execution.payload["knowledge_bases"] == ["user:kb:test"]


def test_configured_turn_runtime_required_missing_skill_fails_closed(monkeypatch) -> None:
    from deeptutor.services.session._turn_runtime_shared import _TurnExecution
    from deeptutor.services.session.turns.configured import ConfiguredTurnRuntime
    from deeptutor.services.session.turns.environment import PreparedTurnEnvironment

    class Store:
        def __init__(self) -> None:
            self.finalized: dict[str, Any] | None = None

        async def update_session_preferences(self, *_args, **_kwargs):
            return None

        async def append_turn_event(self, turn_id, event):
            return {"turn_id": turn_id, **event}

        async def finalize_turn(self, turn_id, **kwargs):
            self.finalized = {"turn_id": turn_id, **kwargs}
            return {"events": kwargs["events"]}

    class Environment:
        async def authorize_request(self, action, *, session_id=None, turn_id=None):
            return None

    class Runtime(ConfiguredTurnRuntime):
        def __init__(self) -> None:
            self.store = Store()
            self.turn_environment = Environment()
            self._lock = asyncio.Lock()
            self._executions = {}
            self._reply_queues = {}
            self.turn_engine = SimpleNamespace(
                execute=lambda _context: (_ for _ in ()).throw(
                    AssertionError("missing required skills must fail before the model")
                )
            )

    runtime = Runtime()
    payload = {
        "content": "请按指定 skill 作答",
        "capability": "chat",
        "tools": [],
        "skills": ["missing-skill"],
        "context_policy": "required",
        "language": "zh",
        "llm_selection": {"profile_id": "chat", "model_id": "primary"},
    }
    execution = _TurnExecution(
        turn_id="turn-1",
        session_id="session-1",
        capability="chat",
        payload=payload,
        prepared_environment=PreparedTurnEnvironment(
            payload=payload,
            llm_config=SimpleNamespace(model="test-model", max_tokens=128),
            chat_params={"temperature": 0.2},
            allowed_tools=(),
        ),
    )
    runtime._executions[execution.turn_id] = execution
    monkeypatch.setattr(
        "deeptutor.services.skill.runtime.get_runtime_skill_service",
        lambda: SimpleNamespace(summary_entries=lambda: []),
    )

    asyncio.run(runtime._run_configured_turn(execution))

    assert runtime.store.finalized is not None
    assert runtime.store.finalized["status"] == "failed"
    assert runtime.store.finalized["failure_code"] == "skill_unavailable"
    done_event = runtime.store.finalized["events"][-1]
    assert done_event["metadata"]["error_code"] == "skill_unavailable"
    usage = done_event["metadata"]["capability_usage"]
    skill_rows = [item for item in usage["items"] if item["kind"] == "skill"]
    assert skill_rows == [
        {"kind": "skill", "label": "missing-skill", "status": "unavailable", "count": 0}
    ]
