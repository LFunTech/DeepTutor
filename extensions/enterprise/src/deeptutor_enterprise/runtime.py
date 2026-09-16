"""身份/配置适配器；聊天行为由原 core application/runtime 实现。"""

import asyncio
from weakref import WeakValueDictionary

from deeptutor.app.service import TurnApplicationService
from deeptutor.persistence.postgres.session import PostgresSessionStore
from deeptutor.services.session.turns.environment import (
    PreparedTurnEnvironment,
    validate_text_request,
)

from .context import current_identity
from .scope import TenantScope


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
        identity = await self.enterprise.authorize()
        config = self.enterprise.configuration
        selection = payload.get("llm_selection") or (session or {}).get("preferences", {}).get(
            "llm_selection"
        )
        model = config.select_model(selection, role=identity.role, user_id=identity.user_id)
        tools = payload.get("tools")
        allowed = config.deployment.allowed_tools
        if tools is not None and not set(tools) <= set(allowed):
            raise PermissionError("tool is not authorized")
        payload = {
            **payload,
            "language": payload.get("language") or config.deployment.language,
            "llm_selection": {"profile_id": model.profile_id, "model_id": model.model_id},
            "tools": list(allowed if tools is None else tools),
        }
        return PreparedTurnEnvironment(
            payload,
            config.resolve_model(
                payload["llm_selection"], role=identity.role, user_id=identity.user_id
            ),
            config.chat_params(),
            tuple(payload["tools"]),
        )


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
