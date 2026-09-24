"""身份/配置适配器；聊天行为由原 core application/runtime 实现。"""

import asyncio
import base64
import mimetypes
from weakref import WeakValueDictionary

from deeptutor.app.service import TurnApplicationService
from deeptutor.core.context import Attachment
from deeptutor.persistence.postgres.object_resources import PostgresObjectResourceStore
from deeptutor.persistence.postgres.session import PostgresSessionStore
from deeptutor.services.llm.capabilities import supports_vision
from deeptutor.services.session.required_context import (
    ContextResolutionError,
    initial_context_resolution,
    mark_resolved,
    mark_unavailable,
    normalize_context_policy,
    string_list,
)
from deeptutor.services.session.turns.environment import (
    PreparedTurnEnvironment,
    validate_text_request,
)

from .context import current_identity
from .knowledge_bases import EnterpriseLightRAGTool, resolve_requested_knowledge_bases
from .model_catalog import load_runtime_model_deployments
from .scope import TenantScope

MAX_INLINE_IMAGE_RESOURCE_BYTES = 20 * 1024 * 1024


class StoreProvider:
    def __init__(self, enterprise):
        self.enterprise = enterprise

    def get(self):
        identity = current_identity()
        if identity.tenant_id != self.enterprise.identity.tenant_id:
            raise PermissionError("invalid identity scope")
        return PostgresSessionStore(
            self.enterprise.db, TenantScope(identity.tenant_id, identity.user_id)
        )


class TurnEnvironment:
    def __init__(self, enterprise):
        self.enterprise = enterprise

    async def authorize_request(self, action, *, session_id=None, turn_id=None):
        await self.enterprise.authorize()
        store = self.enterprise.store_provider.get()
        if action != "start" and session_id and not await store.get_session(session_id):
            raise LookupError("Session not found")
        if turn_id and not await store.get_turn(turn_id):
            raise LookupError("Turn not found")

    async def prepare_request(self, payload, *, session=None):
        validate_text_request(payload)
        context_resolution = initial_context_resolution(payload)
        policy = normalize_context_policy(payload.get("context_policy"))
        identity = await self.enterprise.authorize()
        config = self.enterprise.configuration
        store = self.enterprise.store_provider.get()
        models = await load_runtime_model_deployments(store, config.deployment.models)
        selection = payload.get("llm_selection") or (session or {}).get("preferences", {}).get(
            "llm_selection"
        )
        model = config.select_model(
            selection,
            role=identity.role,
            user_id=identity.user_id,
            models=models,
        )
        tools = payload.get("tools")
        allowed = config.deployment.allowed_tools
        if tools is not None and not set(tools) <= set(allowed):
            raise PermissionError("tool is not authorized")
        requested_mcp_tools = string_list(payload.get("mcp_tools"))
        if requested_mcp_tools:
            mark_unavailable(
                context_resolution,
                kind="mcp_tool",
                names=requested_mcp_tools,
                code="mcp_tool_unavailable",
            )
            if policy == "required":
                raise ContextResolutionError(
                    "Required MCP tool is unavailable in this turn environment",
                    error_code="mcp_tool_unavailable",
                )
        requested_kbs = string_list(payload.get("knowledge_bases"))
        resolved_kbs: list[str] = []
        kb_modes: dict[str, str] = {}
        if requested_kbs:
            resolved_kbs, unavailable_kbs, kb_modes = await resolve_requested_knowledge_bases(
                store,
                requested_kbs,
                rag_enabled="rag" in set(allowed),
                lightrag_binding=getattr(config.deployment, "lightrag", None),
            )
            if resolved_kbs:
                mark_resolved(context_resolution, "knowledge_bases", resolved_kbs)
            for code, names in unavailable_kbs.items():
                mark_unavailable(
                    context_resolution,
                    kind="knowledge_base",
                    names=names,
                    code=code,
                )
            if unavailable_kbs and policy == "required":
                raise ContextResolutionError(
                    "Required knowledge base cannot be mounted in this turn environment",
                    error_code=next(iter(unavailable_kbs)),
                )
        payload = {
            **payload,
            "language": payload.get("language") or config.deployment.language,
            "llm_selection": {"profile_id": model.profile_id, "model_id": model.model_id},
            "tools": list(allowed if tools is None else tools),
            "knowledge_bases": resolved_kbs,
            "mcp_tools": [],
            "context_policy": policy,
        }
        llm_config = config.resolve_model_deployment(model)
        resource_attachments = await self._materialize_resource_attachments(
            payload,
            llm_config=llm_config,
        )
        return PreparedTurnEnvironment(
            payload,
            llm_config,
            config.chat_params(),
            tuple(payload["tools"]),
            resource_attachments=resource_attachments,
            tool_overrides=(
                (
                    EnterpriseLightRAGTool(
                        binding=config.deployment.lightrag,
                        allowed_kbs=resolved_kbs,
                        modes=kb_modes,
                    ),
                )
                if "rag" in set(payload["tools"]) and config.deployment.lightrag is not None
                else ()
            ),
            context_resolution=context_resolution,
        )

    async def _materialize_resource_attachments(self, payload, *, llm_config):
        resource_ids = [str(value).strip() for value in payload.get("resource_ids") or []]
        resource_ids = [value for value in resource_ids if value]
        if not resource_ids:
            return ()
        resource_store = PostgresObjectResourceStore(
            self.enterprise.store_provider.get(), self.enterprise.object_store
        )
        verified = []
        for resource_id in resource_ids:
            handle = await resource_store.verify_ready_reference(
                resource_id=resource_id,
                session_id=str(payload.get("session_id") or ""),
                purpose="chat_turn",
            )
            mime_type = str(handle.mime_type or "application/octet-stream").split(";", 1)[0].lower()
            if not mime_type.startswith("image/"):
                raise ContextResolutionError(
                    "Only image resources are supported for model input",
                    error_code="required_context_unavailable",
                )
            if int(handle.size_bytes) > MAX_INLINE_IMAGE_RESOURCE_BYTES:
                raise ContextResolutionError(
                    "Image resource is too large for model input",
                    error_code="required_context_unavailable",
                )
            verified.append((handle, mime_type))
        if not supports_vision(
            getattr(llm_config, "binding", "openai"),
            getattr(llm_config, "model", ""),
        ):
            raise ContextResolutionError(
                "Configured model does not support image resources",
                error_code="required_context_unavailable",
            )
        attachments = []
        for handle, mime_type in verified:
            data = await resource_store.read(handle)
            filename = _resource_attachment_filename(handle.resource_id, mime_type)
            attachments.append(
                Attachment(
                    type="image",
                    base64=base64.b64encode(data).decode("ascii"),
                    filename=filename,
                    mime_type=mime_type,
                    id=handle.resource_id,
                )
            )
        return tuple(attachments)


def _resource_attachment_filename(resource_id, mime_type):
    extension = mimetypes.guess_extension(str(mime_type or "").lower()) or ""
    if extension == ".jpe":
        extension = ".jpg"
    if not extension:
        extension = ".bin"
    return f"{resource_id}{extension}"


class GuardedTurns:
    """每次调用重新认证；每个 scope 使用独立事件/命令 coordinator。"""

    def __init__(self, enterprise, store_provider, runtime_registry, coordinator):
        self.enterprise = enterprise
        self.store_provider = store_provider
        self.runtime_registry = runtime_registry
        self._command_locks = WeakValueDictionary()

    async def _service(self):
        await self.enterprise.authorize()
        store = self.store_provider.get()
        runtime = self.runtime_registry.get(store)
        return TurnApplicationService(
            self.store_provider, self.runtime_registry, runtime.coordinator
        )

    async def start_turn(self, payload):
        return await (await self._service()).start_turn(payload)

    async def regenerate_last_turn(self, session_id, overrides=None):
        return await (await self._service()).regenerate_last_turn(session_id, overrides=overrides)

    async def subscribe_turn(self, turn_id, after_seq=0):
        service = await self._service()
        if not await self.store_provider.get().get_turn(turn_id):
            raise LookupError("Turn not found")
        runtime = self.runtime_registry.get(self.store_provider.get())
        async for event in runtime.subscribe_turn(turn_id, after_seq):
            await self.enterprise.authorize()
            yield event

    async def subscribe_session(self, session_id, after_seq=0):
        active = await self.check_active_turn(session_id)
        if active:
            async for event in self.subscribe_turn(active["turn_id"], after_seq):
                yield event

    async def check_active_turn(self, session_id):
        await self._service()
        turn = await self.store_provider.get().get_active_turn(session_id)
        return (
            {"turn_id": turn["id"], "status": turn["status"], "owner_id": turn.get("owner_id", "")}
            if turn
            else None
        )

    async def _command(self, turn_id, kind, payload, command_id):
        await self._service()
        store = self.store_provider.get()
        runtime = self.runtime_registry.get(store)
        key = (store.scope, turn_id)
        lock = self._command_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._command_locks[key] = lock

        async def deliver():
            # ACK 丢失/客户端断线不能让同一条回复进入下一次 ask_user。
            async with lock:
                if command_id is not None:
                    claim = await store.reserve_command(turn_id, command_id, kind, payload)
                    if claim["replayed"] or not claim["accepted"]:
                        return claim["accepted"]
                accepted = False
                try:
                    if kind == "cancel":
                        accepted = await runtime.cancel_turn(turn_id)
                    else:
                        accepted = await runtime.submit_user_reply(turn_id, **payload)
                    return accepted
                finally:
                    if command_id is not None:
                        await store.finish_command(turn_id, command_id, accepted)

        task = asyncio.create_task(deliver())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # 等待已登记命令完成，再结束请求；不留下无主投递任务。
            try:
                await task
            finally:
                raise

    async def cancel_turn(self, turn_id, *, command_id=None):
        return await self._command(turn_id, "cancel", {}, command_id)

    async def submit_user_reply(self, turn_id, text=None, *, answers=None, command_id=None):
        return await self._command(turn_id, "reply", {"text": text, "answers": answers}, command_id)

    async def submit_user_input(self, turn_id, content, *, command_id=None):
        raise ValueError("interrupting user_input is not supported in this slice")

    async def list_sessions(self, limit=50, offset=0):
        return await (await self._service()).list_sessions(limit, offset)

    async def get_session(self, session_id):
        return await (await self._service()).get_session(session_id)

    async def rename_session(self, session_id, title):
        return await (await self._service()).rename_session(session_id, title)

    async def delete_session(self, session_id):
        await self._service()
        store = self.store_provider.get()
        runtime = self.runtime_registry.get(store)
        from deeptutor.services.session.deletion import delete_session_lifecycle

        return await delete_session_lifecycle(store, runtime.cancel_turn, session_id)
