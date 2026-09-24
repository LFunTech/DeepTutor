"""无本地资源的通用文本执行适配；教学与工具循环仍由原 chat capability 执行。"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace
import logging

from deeptutor.core.context import TurnRuntimeContext, UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.turn_request import TurnRequest
from deeptutor.services.session.provider_response_state import normalize_provider_response_state
from deeptutor.services.session.required_context import (
    ContextResolutionError,
    finalized_capability_usage,
    initial_capability_usage,
    initial_context_resolution,
    mark_resolved,
    mark_unavailable,
    normalize_context_policy,
    record_capability_usage_event,
    string_list,
)

from .._turn_runtime_shared import (
    _assemble_persisted_answer,
    _narration_marker_call_id,
    _repair_chinese_emphasis_for_persistence,
    _request_snapshot_metadata,
    _resolve_turn_outcome,
    _should_capture_assistant_content,
    _TurnExecution,
)
from .environment import PreparedTurnEnvironment, validate_text_request

logger = logging.getLogger(__name__)


class ConfiguredTurnRuntime:
    """由显式 environment 启用；不引用具体基础设施实现。"""

    async def _authorize_configured(self, action: str, *, session_id=None, turn_id=None):
        if self.turn_environment is not None:
            await self.turn_environment.authorize_request(
                action,
                session_id=session_id,
                turn_id=turn_id,
            )

    async def _start_configured_turn(self, raw_payload):
        await self._ensure_accepting_turns()
        payload = TurnRequest.model_validate(
            {key: value for key, value in raw_payload.items() if key != "type"}
        ).to_payload()
        validate_text_request(payload, allowed_tools=None)
        request_payload = dict(payload)
        await self._authorize_configured("start", session_id=payload.get("session_id"))
        session = None
        if payload.get("session_id"):
            session = await self.store.get_session(payload["session_id"])
            # begin_request 负责幂等删除重放；不通过 ensure_session 接管未知 id。
            if session is not None:
                validate_text_request(session.get("preferences") or {}, allowed_tools=None)
        prepared = await self.turn_environment.prepare_request(payload, session=session)
        if not isinstance(prepared, PreparedTurnEnvironment):
            raise TypeError("Turn environment returned an invalid prepared request")
        payload = TurnRequest.model_validate(prepared.payload).to_payload()
        validate_text_request(payload, allowed_tools=prepared.allowed_tools)
        from deeptutor.tools.builtin_specs import BUILTIN_TOOL_SPEC_BY_NAME

        if not set(prepared.allowed_tools).issubset(BUILTIN_TOOL_SPEC_BY_NAME):
            raise ValueError("Configured tools require unavailable resource providers")
        if not set(payload.get("tools") or []).issubset(prepared.allowed_tools):
            raise PermissionError("Requested tool is not authorized")
        if prepared.llm_config is None or prepared.chat_params is None:
            raise ValueError("Explicit model and chat configuration are required")
        begin_request = getattr(self.store, "begin_request", None)
        if not callable(begin_request) or not callable(getattr(self.store, "finalize_turn", None)):
            raise RuntimeError("Configured turns require atomic request and terminal persistence")
        # 注册请求与 turn 必须先于模型调用；同 key 的重放不进入执行。
        async with self._lock:
            if self._turns_blocked_for_update_locked():
                raise RuntimeError("Turn runtime is not accepting requests")
            session, turn, replayed = await begin_request(
                request_payload,
                operation_id=request_payload.get("operation_id"),
            )
            if replayed:
                return session, turn
            execution = _TurnExecution(
                turn_id=turn["id"],
                session_id=session["id"],
                capability="chat",
                payload=payload,
                prepared_environment=replace(prepared, payload=payload),
            )
            self._executions[turn["id"]] = execution
            execution.task = asyncio.create_task(self._run_turn(execution))
        return session, turn

    async def regenerate_last_turn(self, session_id, overrides=None):
        if self.turn_environment is None:
            return await super().regenerate_last_turn(session_id, overrides)
        await self._authorize_configured("regenerate", session_id=session_id)
        if "operation_id" in (overrides or {}):
            raise ValueError("operation_id is supported only for start requests, not regenerate")
        session = await self.store.get_session(session_id)
        if session is None:
            raise ValueError("Session is unavailable")
        if await self.store.get_active_turn(session_id) is not None:
            raise RuntimeError("regenerate_busy")
        overrides = dict(overrides or {})
        validate_text_request(overrides)
        rows = await self.store.get_messages_for_context(session_id)
        last_user = next((row for row in reversed(rows) if row.get("role") == "user"), None)
        if last_user is None:
            raise RuntimeError("nothing_to_regenerate")
        preferences = session.get("preferences") or {}
        payload = {
            key: preferences[key]
            for key in ("capability", "tools", "language", "llm_selection")
            if key in preferences
        }
        payload.update(overrides)
        payload.update(
            content=last_user["content"],
            session_id=session_id,
            parent_message_id=last_user["id"],
            persist_user_message=False,
            regenerate=True,
            regenerated_from_message_id=last_user["id"],
        )
        return await self.start_turn(payload)

    async def cancel_turn(self, turn_id):
        if self.turn_environment is None:
            return await super().cancel_turn(turn_id)
        await self._authorize_configured("cancel", turn_id=turn_id)
        turn = await self.store.get_turn(turn_id)
        if turn is None:
            raise ValueError("Turn is unavailable")
        if turn.get("status") == "cancelled":
            return True
        async with self._lock:
            execution = self._executions.get(turn_id)
            if execution is None or execution.task is None or execution.task.done():
                return False
            task = execution.task
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return True

    async def submit_user_reply(self, turn_id, text=None, *, answers=None):
        if self.turn_environment is None:
            return await super().submit_user_reply(turn_id, text, answers=answers)
        await self._authorize_configured("reply", turn_id=turn_id)
        if await self.store.get_turn(turn_id) is None:
            raise ValueError("Turn is unavailable")
        async with self._lock:
            execution = self._executions.get(turn_id)
            queue = self._reply_queues.get(turn_id)
            if execution is None or not execution.awaiting_user_reply or queue is None:
                return False
            # 锁内消费一次授权，重复 reply 不会排到下一次 ask_user。
            execution.awaiting_user_reply = False
            queue.put_nowait({"text": text or "", "answers": answers})
            return True

    async def subscribe_turn(self, turn_id, after_seq=0):
        if self.turn_environment is not None:
            await self._authorize_configured("subscribe", turn_id=turn_id)
            if await self.store.get_turn(turn_id) is None:
                raise ValueError("Turn is unavailable")
        async for event in super().subscribe_turn(turn_id, after_seq=after_seq):
            if self.turn_environment is not None and event.get("metadata", {}).get("synthesized"):
                # 显式存储的 done 与终态原子提交；游标重放只能返回真实已提交事件。
                continue
            await self._authorize_configured("read_event", turn_id=turn_id)
            yield event

    async def subscribe_session(self, session_id, after_seq=0):
        await self._authorize_configured("subscribe_session", session_id=session_id)
        async for event in super().subscribe_session(session_id, after_seq=after_seq):
            yield event

    async def _configured_event(self, execution, event):
        await self._authorize_configured(
            "persist_event",
            session_id=execution.session_id,
            turn_id=execution.turn_id,
        )
        if event.type == StreamEventType.ERROR:
            event.content = "Turn execution failed"
        event.session_id = execution.session_id
        event.turn_id = execution.turn_id
        persisted = await self.store.append_turn_event(execution.turn_id, event.to_dict())
        await self._authorize_configured(
            "publish_event",
            session_id=execution.session_id,
            turn_id=execution.turn_id,
        )
        await self._publish_committed_events(execution, [persisted])
        return persisted

    async def _publish_committed_events(self, execution, events):
        async with self._lock:
            for event in events:
                execution.events.append(event)
                execution.persisted_events.append(event)
                execution.next_seq = max(execution.next_seq, int(event.get("seq") or 0) + 1)
                for subscriber in execution.subscribers:
                    subscriber.queue.put_nowait(event)

    async def _run_configured_turn(self, execution):
        prepared = execution.prepared_environment
        payload = execution.payload
        reply_queue = asyncio.Queue(maxsize=1)
        content_segments = []
        narration_ids = set()
        assistant_events = []
        pending_done = None
        context = None
        user_message_id = None
        parent_message_id = None
        status, error = "completed", ""
        failure_code = ""
        retryable = False
        context_resolution = prepared.context_resolution or initial_context_resolution(payload)
        capability_usage_summary: dict[str, object] | None = None
        llm_token = None
        authority_revoked = False

        async def monitor_authorization():
            nonlocal authority_revoked
            while True:
                await asyncio.sleep(1.0)
                try:
                    await self._authorize_configured(
                        "execute",
                        session_id=execution.session_id,
                        turn_id=execution.turn_id,
                    )
                except (PermissionError, LookupError):
                    authority_revoked = True
                except Exception:
                    # DB/执行权未知不是可以降级的认证失败；停止执行，交由受控恢复仲裁。
                    execution.lease_lost = True
                else:
                    continue
                if execution.task is not None:
                    execution.task.cancel()
                return

        monitor_task = asyncio.create_task(monitor_authorization())

        def answer():
            return _assemble_persisted_answer(content_segments, narration_ids)

        async def waiter():
            if not await self.store.transition_turn(
                execution.turn_id,
                "waiting_input",
                expected_status="running",
            ):
                raise asyncio.CancelledError
            async with self._lock:
                execution.awaiting_user_reply = True
                self._reply_queues[execution.turn_id] = reply_queue
            try:
                return await reply_queue.get()
            finally:
                async with self._lock:
                    execution.awaiting_user_reply = False
                    self._reply_queues.pop(execution.turn_id, None)
                await self.store.transition_turn(
                    execution.turn_id,
                    "running",
                    expected_status="waiting_input",
                )

        try:
            await self._authorize_configured(
                "execute",
                session_id=execution.session_id,
                turn_id=execution.turn_id,
            )
            from deeptutor.runtime.registry.tool_registry import ToolRegistry
            from deeptutor.services.llm.config import set_scoped_llm_config
            from deeptutor.tools.builtin_specs import BUILTIN_TOOL_SPEC_BY_NAME

            await self.store.update_session_preferences(
                execution.session_id,
                {
                    key: payload[key]
                    for key in (
                        "capability",
                        "tools",
                        "knowledge_bases",
                        "skills",
                        "mcp_tools",
                        "context_policy",
                        "language",
                        "llm_selection",
                    )
                    if key in payload
                },
            )
            llm_token = set_scoped_llm_config(prepared.llm_config)
            registry = ToolRegistry()
            for name in prepared.allowed_tools:
                registry.register(BUILTIN_TOOL_SPEC_BY_NAME[name].create())
            for tool in prepared.tool_overrides:
                if tool.name not in set(prepared.allowed_tools):
                    raise ValueError("Configured tool override is not authorized")
                registry.register(tool)
            skills_manifest = ""
            requested_skills = string_list(payload.get("skills"))
            if requested_skills:
                from deeptutor.services.skill.runtime import (
                    call_skill_service,
                    get_runtime_skill_service,
                )
                from deeptutor.services.skill.service import render_skills_manifest

                skill_service = get_runtime_skill_service()
                skill_entries = await call_skill_service(skill_service, "summary_entries")
                entries_by_name = {entry.name: entry for entry in skill_entries}
                missing_skills = [
                    name for name in requested_skills if name not in entries_by_name
                ]
                unavailable_skills = [
                    name
                    for name in requested_skills
                    if name in entries_by_name and not entries_by_name[name].available
                ]
                resolved_skills = [
                    name
                    for name in requested_skills
                    if name in entries_by_name and entries_by_name[name].available
                ]
                skill_blocks: list[str] = []
                if resolved_skills:
                    mark_resolved(context_resolution, "skills", resolved_skills)
                    loaded = await call_skill_service(
                        skill_service,
                        "load_for_context",
                        resolved_skills,
                    )
                    if loaded:
                        skill_blocks.append(loaded)
                if missing_skills or unavailable_skills:
                    mark_unavailable(
                        context_resolution,
                        kind="skill",
                        names=[*missing_skills, *unavailable_skills],
                        code="skill_unavailable",
                    )
                    if normalize_context_policy(payload.get("context_policy")) == "required":
                        raise ContextResolutionError(
                            "Required skill is unavailable or unauthorized",
                            error_code="skill_unavailable",
                        )
                skills_manifest = "\n\n".join(
                    part for part in (*skill_blocks, render_skills_manifest(skill_entries)) if part
                )
            capability_usage_summary = initial_capability_usage(
                {**payload, "context_resolution": context_resolution},
                model_label=str(getattr(prepared.llm_config, "model", "") or ""),
            )
            session_meta = {"session_id": execution.session_id, "turn_id": execution.turn_id}
            for key in ("regenerate", "regenerated_from_message_id", "superseded_turn_id"):
                if payload.get(key) is not None:
                    session_meta[key] = payload[key]
            await self._configured_event(
                execution,
                StreamEvent(
                    type=StreamEventType.SESSION,
                    source="turn_runtime",
                    metadata=session_meta,
                ),
            )
            branch_explicit = "parent_message_id" in payload
            parent_message_id = payload.get("parent_message_id")
            rows = await self.store.get_messages_for_context(
                execution.session_id,
                leaf_message_id=parent_message_id,
            )
            if branch_explicit and parent_message_id is None:
                rows = []
            if parent_message_id is not None and (not rows or rows[-1]["id"] != parent_message_id):
                raise ValueError("Parent message is unavailable in this session")
            # 上下文与新 user 必须锚定同一次读取；期间切换活动分支不能改写本 turn 的父链。
            # 即使没有历史也显式固定 None，避免 add_message 的 AUTO 再读活动叶子。
            parent_message_id = rows[-1]["id"] if rows else None
            if payload.get("persist_user_message", True) is False:
                if not rows or rows[-1].get("role") != "user":
                    raise ValueError("Regenerate requires a valid user parent")
                user_message_id = rows[-1]["id"]
                if rows[-1]["content"] != payload.get("content"):
                    raise ValueError("Regenerate content must match its user message")
                rows = rows[:-1]
            # 原 context-builder 的 chronology/provider replay 规则，不把展示trace截断带入模型。
            from deeptutor.services.session.context_builder import ContextBuilder

            summary_params = prepared.summary_agent_params or {
                "temperature": float(prepared.chat_params.get("temperature", 0.2)),
                "max_tokens": int(prepared.llm_config.max_tokens),
                "max_retries": 3,
            }
            builder = ContextBuilder(self.store, summary_agent_params=summary_params)
            history_leaf_message_id = rows[-1]["id"] if rows else None
            if history_leaf_message_id is not None:
                history_result = await builder.build(
                    session_id=execution.session_id,
                    llm_config=prepared.llm_config,
                    language=payload.get("language") or "en",
                    leaf_message_id=history_leaf_message_id,
                    on_event=lambda event: self._configured_event(execution, event),
                )
                history = history_result.conversation_history
            else:
                history = []
            if payload.get("persist_user_message", True):
                user_message_id = await self.store.add_message(
                    execution.session_id,
                    "user",
                    payload["content"],
                    capability="chat",
                    metadata=_request_snapshot_metadata(
                        payload={**payload, "context_resolution": context_resolution},
                        content=payload["content"],
                        capability="chat",
                        config={},
                        attachments=[],
                        notebook_references=[],
                        history_references=[],
                        partner_group_references=[],
                        question_notebook_references=[],
                        book_references=[],
                        reading_references=(),
                        persona="",
                        memory_references=(),
                        llm_selection=payload.get("llm_selection"),
                    ),
                    parent_message_id=parent_message_id,
                )
            link_user = getattr(self.store, "link_turn_user_message", None)
            if callable(link_user):
                await link_user(execution.turn_id, user_message_id)
            parent_message_id = user_message_id
            context = UnifiedContext(
                session_id=execution.session_id,
                user_message=payload["content"],
                conversation_history=history,
                active_capability="chat",
                enabled_tools=list(payload.get("tools") or []),
                allowed_builtin_tools=list(prepared.allowed_tools),
                knowledge_bases=list(payload.get("knowledge_bases") or []),
                attachments=list(prepared.resource_attachments),
                language=payload.get("language") or "en",
                skills_manifest=skills_manifest,
                runtime=TurnRuntimeContext(
                    turn_id=execution.turn_id,
                    wait_for_user_reply=waiter,
                    resource_capabilities=frozenset(),
                    llm_config=prepared.llm_config,
                    chat_params=prepared.chat_params,
                    tool_registry=registry,
                ),
                metadata={
                    "turn_id": execution.turn_id,
                    "context_policy": normalize_context_policy(payload.get("context_policy")),
                    "knowledge_bases": string_list(payload.get("knowledge_bases")),
                    "skills": string_list(payload.get("skills")),
                    "tools": string_list(payload.get("tools")),
                    "mcp_tools": string_list(payload.get("mcp_tools")),
                    "resource_ids": string_list(payload.get("resource_ids")),
                    "context_resolution": context_resolution,
                    "capability_usage": capability_usage_summary or {},
                },
            )
            async with contextlib.aclosing(self.turn_engine.execute(context)) as events:
                async for event in events:
                    if event.type == StreamEventType.SESSION:
                        continue
                    if event.type == StreamEventType.DONE:
                        pending_done = event
                        continue
                    if event.type == StreamEventType.ERROR:
                        # Provider 错误可能包含 endpoint/credential；不向客户端或持久trace传播。
                        event.content = "Turn execution failed"
                    if capability_usage_summary is not None:
                        record_capability_usage_event(capability_usage_summary, event)
                    if event.metadata.get("ask_user_resolved"):
                        event.metadata.setdefault("assistant_content_offset", len(answer()))
                    persisted = await self._configured_event(execution, event)
                    assistant_events.append(persisted)
                    if _should_capture_assistant_content(event):
                        call_id = event.metadata.get("call_id")
                        content_segments.append((str(call_id) if call_id else None, event.content))
                    marker = _narration_marker_call_id(event)
                    if marker:
                        narration_ids.add(marker)
            status, error = _resolve_turn_outcome(assistant_events, pending_done)
            if status == "completed" and not payload.get("regenerate"):
                await self._authorize_configured(
                    "generate_title",
                    session_id=execution.session_id,
                    turn_id=execution.turn_id,
                )
                await self._maybe_generate_session_title(
                    execution=execution,
                    session_id=execution.session_id,
                    ui_language=payload.get("language") or "en",
                    assistant_content=answer(),
                )
        except asyncio.CancelledError:
            status, error = "cancelled", "Turn cancelled"
        except Exception as exc:
            status, error = "failed", "Turn execution failed"
            raw_failure_code = str(getattr(exc, "error_code", "") or "")
            failure_code = raw_failure_code or "internal_error"
            retryable_attr = getattr(exc, "retryable", None)
            retryable = retryable_attr if isinstance(retryable_attr, bool) else not raw_failure_code
            logger.warning("Configured turn failed: %s", execution.turn_id, exc_info=True)
        finally:
            self._reply_queues.pop(execution.turn_id, None)
            execution.awaiting_user_reply = False
            try:
                if execution.lease_lost:
                    raise RuntimeError("Turn execution authority is unavailable")
                revoked = authority_revoked
                if revoked:
                    status, error = "failed", "Turn authorization is no longer valid"
                try:
                    await self._authorize_configured(
                        "finalize",
                        session_id=execution.session_id,
                        turn_id=execution.turn_id,
                    )
                except (PermissionError, LookupError):
                    # 此处只允许记录受控失败，不再提交撤销后的成功输出或调用模型。
                    revoked = True
                    status, error = "failed", "Turn authorization is no longer valid"
                if revoked and not failure_code:
                    failure_code = "turn_authorization_expired"
                    retryable = True
                metadata = None
                if context is not None and not revoked:
                    state = normalize_provider_response_state(
                        context.runtime.provider_response_state
                    )
                    if state is not None:
                        metadata = {"provider_response_state": state}
                if capability_usage_summary is None:
                    capability_usage_summary = initial_capability_usage(
                        {**payload, "context_resolution": context_resolution},
                        model_label=str(getattr(prepared.llm_config, "model", "") or ""),
                    )
                if capability_usage_summary is not None:
                    usage_metadata_source = context.metadata if context is not None else {
                        "context_resolution": context_resolution
                    }
                    usage = finalized_capability_usage(
                        capability_usage_summary,
                        usage_metadata_source,
                    )
                    metadata = {**(metadata or {}), "capability_usage": usage}
                terminal = pending_done or StreamEvent(type=StreamEventType.DONE, source="chat")
                terminal.session_id, terminal.turn_id = execution.session_id, execution.turn_id
                terminal.metadata = {**terminal.metadata, "status": status}
                if failure_code:
                    terminal.metadata["error_code"] = failure_code
                if retryable:
                    terminal.metadata["retryable"] = retryable
                if metadata and "capability_usage" in metadata:
                    terminal.metadata["capability_usage"] = metadata["capability_usage"]
                terminal_events = []
                if status == "failed" and error:
                    terminal_events.append(
                        StreamEvent(
                            type=StreamEventType.ERROR,
                            source="turn_runtime",
                            content=error,
                            session_id=execution.session_id,
                            turn_id=execution.turn_id,
                            metadata={
                                "turn_terminal": True,
                                "status": "failed",
                                "error_code": failure_code,
                                "retryable": retryable,
                            },
                        ).to_dict()
                    )
                terminal_events.append(terminal.to_dict())
                # finalize 内的 CAS 是最终仲裁；取消不能把已提交completed翻写为cancelled。
                committing = asyncio.create_task(
                    self.store.finalize_turn(
                        execution.turn_id,
                        status=status,
                        content=""
                        if revoked
                        else _repair_chinese_emphasis_for_persistence(
                            answer(), payload.get("language") or "en"
                        ),
                        capability="chat",
                        parent_message_id=parent_message_id,
                        user_message_id=user_message_id,
                        metadata=metadata,
                        error=error,
                        events=terminal_events,
                        failure_code=failure_code,
                        retryable=retryable,
                    )
                )
                while True:
                    try:
                        result = await asyncio.shield(committing)
                        break
                    except asyncio.CancelledError:
                        # 重复 cancel 也不能中断已经开始的终态原子仲裁。
                        if committing.cancelled():
                            raise
                await self._publish_committed_events(execution, result["events"])
            except Exception:
                # 没有成功提交便不发布 done、不虚构成功；保留已提交事件供恢复审计。
                logger.error("Configured turn finalization failed: %s", execution.turn_id)
            finally:
                monitor_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor_task
                if llm_token is not None:
                    from deeptutor.services.llm.config import reset_scoped_llm_config

                    reset_scoped_llm_config(llm_token)
                async with self._lock:
                    self._executions.pop(execution.turn_id, None)
                    for subscriber in execution.subscribers:
                        subscriber.queue.put_nowait(None)
                    execution.subscribers.clear()
