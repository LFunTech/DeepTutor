"""企业纯文本会话仓库。

共享连接池不保存当前身份；每个仓库永久绑定可信 tenant/owner。写操作只在
事务提交后返回，终态事件必须通过 finalize_turn 与最终消息一起提交。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import time
from uuid import uuid4

from psycopg.types.json import Jsonb

from deeptutor.services.session.ask_user_trace import filter_ask_user_events
from deeptutor.services.session.event_preview import MAX_TRACE_PREVIEW_EVENTS, compact_trace_preview
from deeptutor.services.session.provider_response_state import redact_private_message_metadata
from deeptutor.services.session.question_bank import QuestionBankReferenceConflict
from deeptutor.services.session.scope import StoreScope
from deeptutor.services.session.workspace_preferences import upgrade_workspace_preferences

from . import session_workflows
from .connection import Database
from .notebook import PostgresNotebookMixin
from .scope import TenantScope
from .session_references import REFERENCE_TABLES, record_references
from .session_statements import (
    SQL_GET_SESSION_ROW,
    SQL_LOCK_SESSION_ROW,
    SQL_UNREGISTERED_ATTACHMENTS,
    session_statement_contract,
)
from .session_validation import EXTERNAL_KEYS, snapshot_attachments, validate_reference_shape

ACTIVE = frozenset({"queued", "running", "waiting_input"})
TERMINAL = frozenset({"completed", "cancelled", "failed"})
_PARENT_AUTO = object()
_EXTERNAL_KEYS = EXTERNAL_KEYS
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "credentials",
        "provider_response_state",
        "cookie",
        "cookies",
    }
)


def _json(value):
    return Jsonb(
        value, dumps=lambda v: json.dumps(v, ensure_ascii=False, allow_nan=False, default=str)
    )


def _public(value):
    """公开 trace 递归隐藏 provider 私有状态，不修改模型上下文原值。"""
    if isinstance(value, dict):
        return {k: _public(v) for k, v in value.items() if k != "provider_response_state"}
    if isinstance(value, list):
        return [_public(v) for v in value]
    return value


def _request_record(value):
    if isinstance(value, dict):
        return {
            k: _request_record(v)
            for k, v in value.items()
            if k.lower() not in _SECRET_KEYS
            and not k.lower().endswith(("_api_key", "_password", "_secret", "_token"))
        }
    if isinstance(value, list):
        return [_request_record(v) for v in value]
    return value


def _has_dependencies(value):
    if isinstance(value, dict):
        return any(
            (k in _EXTERNAL_KEYS and bool(v)) or _has_dependencies(v) for k, v in value.items()
        )
    if isinstance(value, list):
        return any(_has_dependencies(v) for v in value)
    return False


@dataclass(frozen=True, slots=True)
class PostgresSessionStore(PostgresNotebookMixin):
    db: Database
    scope: TenantScope
    supports_session_versions = True

    def __post_init__(self):
        if not isinstance(self.scope, TenantScope):
            raise ValueError("trusted tenant/owner scope is required")

    @property
    def store_scope(self):
        return StoreScope(
            "postgres", self.db.resource, self.scope.user_id, tenant_id=self.scope.tenant_id
        )

    @property
    def _owner(self):
        return self.scope.tenant_id, self.scope.user_id

    async def _session(self, c, session_id, *, lock=False):
        return await (
            await c.execute(
                SQL_LOCK_SESSION_ROW if lock else SQL_GET_SESSION_ROW,
                (*self._owner, session_id),
            )
        ).fetchone()

    async def _turn(self, c, turn_id, *, lock=False):
        return await (
            await c.execute(
                "SELECT * FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND id=%s"
                + (" FOR UPDATE" if lock else ""),
                (*self._owner, turn_id),
            )
        ).fetchone()

    async def _message(self, c, session_id, message_id):
        return await (
            await c.execute(
                "SELECT * FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND session_id=%s AND id=%s",
                (*self._owner, session_id, int(message_id)),
            )
        ).fetchone()

    _require_session = staticmethod(session_workflows.require_session)

    @staticmethod
    def _turn_payload(row):
        if row is None:
            return None
        payload = {
            key: value
            for key, value in row.items()
            if key not in ("tenant_id", "user_id", "next_seq")
        }
        payload["turn_id"] = row["id"]
        payload["last_seq"] = row["next_seq"]
        return payload

    _SUMMARY_SQL = """SELECT s.*,
        coalesce(latest.status,'idle') AS status,
        coalesce(latest.capability,'') AS capability,
        coalesce(active.id,'') AS active_turn_id,
        (SELECT count(*) FROM enterprise.messages m WHERE (m.tenant_id,m.owner_id,m.session_id)=(s.tenant_id,s.owner_id,s.id) AND m.role<>'system') AS message_count,
        coalesce((SELECT content FROM enterprise.messages m WHERE (m.tenant_id,m.owner_id,m.session_id)=(s.tenant_id,s.owner_id,s.id) AND m.role<>'system' AND btrim(content)<>'' ORDER BY id DESC LIMIT 1),'') AS last_message
        FROM enterprise.sessions s
        LEFT JOIN LATERAL (SELECT status,capability FROM enterprise.turns t WHERE (t.tenant_id,t.user_id,t.session_id)=(s.tenant_id,s.owner_id,s.id) ORDER BY updated_at DESC,id DESC LIMIT 1) latest ON true
        LEFT JOIN LATERAL (SELECT id FROM enterprise.turns t WHERE (t.tenant_id,t.user_id,t.session_id)=(s.tenant_id,s.owner_id,s.id) AND status IN ('queued','running','waiting_input') ORDER BY updated_at DESC,id DESC LIMIT 1) active ON true
        WHERE s.tenant_id=%s AND s.owner_id=%s"""

    _summary_payload = staticmethod(session_workflows.summary_payload)

    async def _session_payload(self, c, row):
        summary = await (
            await c.execute(self._SUMMARY_SQL + " AND s.id=%s", (*self._owner, row["id"]))
        ).fetchone()
        return self._summary_payload(summary)

    async def _workflow(self, c, workflow):
        value = None
        while True:
            try:
                step = workflow.send(value)
            except StopIteration as result:
                return result.value
            sql, arity = session_statement_contract(step.statement)
            if len(step.params) != arity or any(type(v) is not str for v in step.params):
                raise ValueError("invalid Session workflow parameters")
            cursor = await c.execute(sql, (*self._owner, *step.params))
            value = await cursor.fetchall() if step.many else await cursor.fetchone()

    async def _create_session(self, c, title=None, session_id=None):
        return await self._workflow(c, session_workflows.create_session(title, session_id))

    async def create_session(self, title=None, session_id=None):
        async with self.db.transaction(self.scope) as c:
            return await self._create_session(c, title, session_id)

    async def get_session(self, session_id):
        async with self.db.transaction(self.scope) as c:
            row = await self._session(c, session_id)
            return await self._session_payload(c, row) if row else None

    async def ensure_session(self, session_id=None):
        if session_id:
            async with self.db.transaction(self.scope) as c:
                row = self._require_session(await self._session(c, session_id))
                return await self._session_payload(c, row)
        return await self.create_session()

    async def list_sessions(self, limit=50, offset=0):
        return await self._list_sessions(limit, offset, imported=False)

    async def _list_sessions(self, limit, offset, *, imported):
        async with self.db.transaction(self.scope) as c:
            rows = await (
                await c.execute(
                    self._SUMMARY_SQL
                    + " AND starts_with(s.id,'imported_')=%s ORDER BY s.updated_at DESC,s.id DESC LIMIT %s OFFSET %s",
                    (*self._owner, imported, max(0, min(int(limit), 1000)), max(0, int(offset))),
                )
            ).fetchall()
            return [self._summary_payload(row) for row in rows]

    async def get_session_summaries(self, session_ids):
        ids = list(dict.fromkeys(session_ids))
        if len(ids) > 1000:
            raise ValueError("session summary batch limit exceeded")
        async with self.db.transaction(self.scope) as c:
            rows = await (
                await c.execute(
                    self._SUMMARY_SQL + " AND s.id=ANY(%s) ORDER BY s.updated_at DESC,s.id DESC",
                    (*self._owner, ids),
                )
            ).fetchall()
            return [self._summary_payload(row) for row in rows]

    _check_version = staticmethod(session_workflows.check_version)

    async def update_session_title(self, session_id, title, *, expected_version=None):
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            return await self._workflow(
                c, session_workflows.update_title(session_id, title, expected_version)
            )

    async def update_generated_session_title(self, session_id, title):
        """生成期间用户可能已改名；数据库条件更新不能覆盖新的手动标题。"""
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            changed = await c.execute(
                "UPDATE enterprise.sessions SET title=%s,updated_at=%s,version=version+1 WHERE tenant_id=%s AND owner_id=%s AND id=%s AND title='New conversation' AND NOT deleting",
                (
                    (title or "New conversation").strip()[:100],
                    time.time(),
                    *self._owner,
                    session_id,
                ),
            )
            if changed.rowcount:
                await self._audit(c, "session.generated_title", session_id, "updated")
            return changed.rowcount > 0

    async def _check_parent(self, c, session_id, parent_id):
        seen = {session_id}
        while parent_id:
            if parent_id in seen:
                raise ValueError("Session parent cycle")
            seen.add(parent_id)
            parent = await self._session(c, parent_id)
            if not parent or parent["deleting"]:
                raise ValueError("Parent session not found")
            parent_id = parent["parent_session_id"]

    async def _check_branches(self, c, session_id, branches):
        if not isinstance(branches, dict):
            raise ValueError("selected_branches must be a mapping")
        for parent_id, child_id in branches.items():
            child = await self._message(c, session_id, child_id)
            expected_parent = (
                None if str(parent_id) in ("root", "null", "None", "0") else int(parent_id)
            )
            if not child or child["parent_message_id"] != expected_parent:
                raise ValueError("Invalid selected branch parent/child")

    async def _selected_leaf(self, c, session_id, branches):
        children = {}
        for message in await self._message_rows(c, session_id):
            children.setdefault(message["parent_message_id"], []).append(message["id"])
        parent = None
        while children.get(parent):
            options = children[parent]
            if parent is None:
                selected = next(
                    (branches[k] for k in ("root", "null", "None", "0") if k in branches), None
                )
            else:
                selected = branches.get(str(parent))
            parent = int(selected) if selected is not None else options[-1]
        return parent

    async def update_session_preferences(self, session_id, preferences, *, expected_version=None):
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            return await self._workflow(
                c, session_workflows.update_preferences(session_id, preferences, expected_version)
            )

    async def select_active_leaf(self, session_id, message_id):
        return await self.update_session_preferences(
            session_id, {"active_leaf_id": int(message_id) if message_id is not None else None}
        )

    async def update_summary(self, session_id, summary, up_to_msg_id):
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            row = await self._session(c, session_id, lock=True)
            if not row:
                return False
            self._require_session(row)
            mid = max(0, int(up_to_msg_id)) or None
            if mid and not await self._message(c, session_id, mid):
                raise ValueError("Summary message not found in session")
            await c.execute(
                "UPDATE enterprise.sessions SET summary=%s,summary_up_to_msg_id=%s,version=version+1 WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (summary, mid, *self._owner, session_id),
            )
            return True

    async def _begin_turn(
        self, c, session_id, capability="", *, turn_id=None, owner_id="", fencing_token=0
    ):
        self._require_session(await self._session(c, session_id, lock=True))
        active = await (
            await c.execute(
                "SELECT id FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND session_id=%s AND status=ANY(%s)",
                (*self._owner, session_id, list(ACTIVE)),
            )
        ).fetchone()
        if active:
            raise RuntimeError("Session already has an active turn")
        row = await (
            await c.execute(
                "INSERT INTO enterprise.turns(tenant_id,user_id,session_id,id,capability,owner_id,fencing_token) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    *self._owner,
                    session_id,
                    turn_id or f"turn_{uuid4().hex}",
                    capability or "",
                    owner_id or "",
                    max(0, int(fencing_token)),
                ),
            )
        ).fetchone()
        await self._audit(c, "turn.begin", row["id"], "running")
        return self._turn_payload(row)

    async def begin_turn(
        self, session_id, capability="", *, turn_id=None, owner_id="", fencing_token=0
    ):
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            return await self._begin_turn(
                c,
                session_id,
                capability,
                turn_id=turn_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
            )

    async def create_turn(self, session_id, capability=""):
        return await self.begin_turn(session_id, capability)

    async def begin_request(self, payload, operation_id=None, *, owner_id="", fencing_token=0):
        """原始公开请求登记与 turn 原子创建；重放永不自动派发模型。"""
        if not isinstance(payload, dict):
            raise ValueError("request must be an object")
        request = _request_record(
            {k: v for k, v in payload.items() if k not in ("operation_id", "type")}
        )
        fingerprint = hashlib.sha256(
            json.dumps(
                request, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
        if operation_id is not None and (
            not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 255
        ):
            raise ValueError("invalid operation ID")
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            if operation_id is not None:
                await c.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    (json.dumps([*self._owner, operation_id]),),
                )
                await c.execute(
                    "DELETE FROM enterprise.operations WHERE tenant_id=%s AND owner_id=%s AND operation_id=%s AND expires_at<=now()",
                    (*self._owner, operation_id),
                )
                operation = await (
                    await c.execute(
                        "SELECT * FROM enterprise.operations WHERE tenant_id=%s AND owner_id=%s AND operation_id=%s",
                        (*self._owner, operation_id),
                    )
                ).fetchone()
                if operation:
                    if operation["fingerprint"] != fingerprint:
                        raise ValueError("Operation ID conflict: request differs")
                    if operation["status"] == "deleted":
                        return (
                            {"id": None, "session_id": None, "status": "deleted"},
                            {"id": None, "turn_id": None, "status": "deleted"},
                            True,
                        )
                    session = self._require_session(
                        await self._session(c, operation["session_id"]), allow_deleting=True
                    )
                    turn = await self._turn(c, operation["turn_id"])
                    if not turn:
                        raise RuntimeError("Operation result is unavailable")
                    return await self._session_payload(c, session), self._turn_payload(turn), True
            if payload.get("session_id"):
                row = self._require_session(
                    await self._session(c, payload["session_id"], lock=True)
                )
                session = await self._session_payload(c, row)
            else:
                session = await self._create_session(c, payload.get("title"))
            parent = None
            if payload.get("parent_message_id") is not None:
                parent = await self._message(c, session["id"], payload["parent_message_id"])
                if not parent:
                    raise ValueError("Parent message not found in session")
            if payload.get("persist_user_message") is False:
                if (
                    not parent
                    or parent["role"] != "user"
                    or parent["content"] != payload.get("content")
                ):
                    raise ValueError("Regenerate requires the original user message and content")
            turn = await self._begin_turn(
                c,
                session["id"],
                payload.get("capability") or "chat",
                owner_id=owner_id,
                fencing_token=fencing_token,
            )
            if operation_id is not None:
                await c.execute(
                    "INSERT INTO enterprise.operations(tenant_id,owner_id,operation_id,fingerprint,request,session_id,turn_id) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        *self._owner,
                        operation_id,
                        fingerprint,
                        _json(request),
                        session["id"],
                        turn["id"],
                    ),
                )
            return session, turn, False

    async def get_turn(self, turn_id):
        async with self.db.transaction(self.scope) as c:
            return self._turn_payload(await self._turn(c, turn_id))

    async def _active_turns(self, c, session_id=None):
        query = (
            "SELECT * FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND status=ANY(%s)"
        )
        args = (*self._owner, list(ACTIVE))
        if session_id is not None:
            query += " AND session_id=%s"
            args += (session_id,)
        return [
            self._turn_payload(row)
            for row in await (
                await c.execute(query + " ORDER BY updated_at DESC,id DESC", args)
            ).fetchall()
        ]

    async def list_nonterminal_turns(self):
        async with self.db.transaction(self.scope) as c:
            return await self._active_turns(c)

    async def list_active_turns(self, session_id):
        async with self.db.transaction(self.scope) as c:
            return await self._active_turns(c, session_id)

    async def get_active_turn(self, session_id):
        turns = await self.list_active_turns(session_id)
        return turns[0] if turns else None

    async def transition_turn(
        self,
        turn_id,
        status,
        *,
        expected_status=None,
        fencing_token=None,
        error="",
        failure_code="",
        retryable=False,
    ):
        if status not in ACTIVE | TERMINAL:
            raise ValueError("Unsupported turn status")
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            row = await self._turn(c, turn_id, lock=True)
            if not row or (expected_status is not None and row["status"] != expected_status):
                return False
            if fencing_token is not None and row["fencing_token"] != int(fencing_token):
                return False
            if row["status"] in TERMINAL:
                return row["status"] == status
            if status == "queued" and row["status"] != "queued":
                return False
            await self._set_status(c, turn_id, status, error, failure_code, retryable)
            return True

    async def reserve_command(self, turn_id, command_id, kind, payload):
        """在投递前登记命令；同 key 的重放只返回原 ask 状态版本，不再次派发。

        原始回复正文不存进命令表，只保存规范 JSON 的指纹。进程崩溃后的
        已登记命令也不会因 replay 自动重跑；执行恢复由 turn 生命周期负责。
        """
        if (
            not isinstance(command_id, str)
            or not command_id.strip()
            or len(command_id) > 255
            or "\x00" in command_id
        ):
            raise ValueError("Invalid command ID")
        if kind not in {"reply", "cancel"}:
            raise ValueError("Unsupported command kind")
        fingerprint = hashlib.sha256(
            json.dumps(
                {"kind": kind, "payload": payload},
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            turn = await self._turn(c, turn_id, lock=True)
            if turn is None:
                raise ValueError("Turn not found")
            existing = await (
                await c.execute(
                    "SELECT kind,fingerprint,accepted,state_version FROM enterprise.turn_commands WHERE tenant_id=%s AND owner_id=%s AND turn_id=%s AND command_id=%s",
                    (*self._owner, turn_id, command_id),
                )
            ).fetchone()
            if existing:
                if existing["kind"] != kind or existing["fingerprint"] != fingerprint:
                    raise ValueError("Command ID conflict: command differs")
                return {
                    "replayed": True,
                    "accepted": existing["accepted"],
                    "state_version": existing["state_version"],
                }
            accepted = (kind == "reply" and turn["status"] == "waiting_input") or (
                kind == "cancel" and turn["status"] in ACTIVE | {"cancelled"}
            )
            await c.execute(
                "INSERT INTO enterprise.turn_commands(tenant_id,owner_id,session_id,turn_id,command_id,kind,fingerprint,accepted,state_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    *self._owner,
                    turn["session_id"],
                    turn_id,
                    command_id,
                    kind,
                    fingerprint,
                    accepted,
                    turn["state_version"],
                ),
            )
            return {
                "replayed": False,
                "accepted": accepted,
                "state_version": turn["state_version"],
            }

    async def finish_command(self, turn_id, command_id, accepted):
        """修正投递失败；保留指纹/原状态版本，拒绝结果不可升级为可再次投递。"""
        if not isinstance(accepted, bool):
            raise ValueError("accepted must be a boolean")
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            if await self._turn(c, turn_id, lock=True) is None:
                raise ValueError("Turn not found")
            updated = await c.execute(
                "UPDATE enterprise.turn_commands SET accepted=accepted AND %s WHERE tenant_id=%s AND owner_id=%s AND turn_id=%s AND command_id=%s",
                (accepted, *self._owner, turn_id, command_id),
            )
            if not updated.rowcount:
                raise ValueError("Command not found")

    async def _set_status(self, c, turn_id, status, error="", failure_code="", retryable=False):
        now = time.time()
        await c.execute(
            "UPDATE enterprise.turns SET status=%s,error=%s,failure_code=%s,retryable=%s,updated_at=%s,finished_at=%s,state_version=state_version+1 WHERE tenant_id=%s AND user_id=%s AND id=%s",
            (
                status,
                error or "",
                failure_code or "",
                bool(retryable),
                now,
                now if status in TERMINAL else None,
                *self._owner,
                turn_id,
            ),
        )

    async def update_turn_status(self, turn_id, status, error=""):
        return await self.transition_turn(turn_id, status, error=error)

    async def _append_events(self, c, turn, events, *, fencing_token=None):
        if fencing_token is not None and turn["fencing_token"] != int(fencing_token):
            raise RuntimeError("Turn lease lost")
        await self._validate_references(c, events)
        await record_references(self, c, turn["session_id"], "turn", turn["id"], events)
        seq = turn["next_seq"]
        output = []
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("event must be an object")
            if event.get("session_id") not in (None, "", turn["session_id"]) or event.get(
                "turn_id"
            ) not in (None, "", turn["id"]):
                raise ValueError("Event scope mismatch")
            provided = int(event.get("seq") or 0)
            n = provided if provided > 0 else seq + 1
            payload = {
                **deepcopy(event),
                "type": event.get("type", ""),
                "source": event.get("source") or "",
                "stage": event.get("stage") or "",
                "content": event.get("content") or "",
                "metadata": deepcopy(event.get("metadata") or {}),
                "session_id": turn["session_id"],
                "turn_id": turn["id"],
                "seq": n,
                "timestamp": float(event.get("timestamp") or time.time()),
            }
            if n <= seq:
                existing = await (
                    await c.execute(
                        "SELECT event FROM enterprise.turn_events WHERE tenant_id=%s AND owner_id=%s AND turn_id=%s AND seq=%s",
                        (*self._owner, turn["id"], n),
                    )
                ).fetchone()
                ignored = {"timestamp"}
                if not existing or {
                    k: v for k, v in existing["event"].items() if k not in ignored
                } != {k: v for k, v in payload.items() if k not in ignored}:
                    raise ValueError("Turn event conflict")
                output.append(existing["event"])
                continue
            if turn["status"] in TERMINAL:
                raise RuntimeError("Cannot append to a terminal turn")
            if n != seq + 1:
                raise ValueError("Turn event sequence must be monotonic without gaps")
            await c.execute(
                "INSERT INTO enterprise.turn_events(tenant_id,owner_id,session_id,turn_id,seq,event) VALUES(%s,%s,%s,%s,%s,%s)",
                (*self._owner, turn["session_id"], turn["id"], n, _json(payload)),
            )
            seq = n
            output.append(payload)
        if seq != turn["next_seq"]:
            await c.execute(
                "UPDATE enterprise.turns SET next_seq=%s,updated_at=%s WHERE tenant_id=%s AND user_id=%s AND id=%s",
                (seq, time.time(), *self._owner, turn["id"]),
            )
        return output

    async def append_events(self, turn_id, events, *, fencing_token=None):
        if any(isinstance(event, dict) and event.get("type") == "done" for event in events):
            raise ValueError("done must be committed through finalize_turn")
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            turn = await self._turn(c, turn_id, lock=True)
            if not turn:
                raise ValueError("Turn not found")
            return await self._append_events(c, turn, events, fencing_token=fencing_token)

    async def append_turn_event(self, turn_id, event):
        return (await self.append_events(turn_id, [event]))[0]

    async def append_turn_events(self, turn_id, events):
        return await self.append_events(turn_id, events)

    async def _events(self, c, turn_id, after_seq=0, limit=None):
        query = "SELECT event FROM enterprise.turn_events WHERE tenant_id=%s AND owner_id=%s AND turn_id=%s AND seq>%s ORDER BY seq"
        args = (*self._owner, turn_id, max(0, int(after_seq)))
        if limit is not None:
            query += " LIMIT %s"
            args += (limit,)
        return [row["event"] for row in await (await c.execute(query, args)).fetchall()]

    async def get_events(self, turn_id, after_seq=0):
        async with self.db.transaction(self.scope) as c:
            return _public(await self._events(c, turn_id, after_seq))

    async def get_turn_events(self, turn_id, after_seq=0):
        return await self.get_events(turn_id, after_seq)

    async def _add_message(
        self,
        c,
        session_id,
        role,
        content,
        capability="",
        events=None,
        attachments=None,
        metadata=None,
        parent_message_id=_PARENT_AUTO,
        *,
        allow_deleting=False,
    ):
        session = self._require_session(
            await self._session(c, session_id, lock=True), allow_deleting=allow_deleting
        )
        if role not in {"user", "assistant", "system", "tool"}:
            raise ValueError("Unsupported message role")
        await self._validate_references(c, metadata or {}, allow_snapshot_attachments=True)
        await self._validate_references(c, events or [])
        if parent_message_id is _PARENT_AUTO:
            parent = session["active_leaf_id"]
            if parent is None:
                last = await (
                    await c.execute(
                        "SELECT id FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND session_id=%s ORDER BY id DESC LIMIT 1",
                        (*self._owner, session_id),
                    )
                ).fetchone()
                parent = last["id"] if last else None
        else:
            parent = int(parent_message_id) if parent_message_id is not None else None
        if parent is not None and not await self._message(c, session_id, parent):
            raise ValueError("Parent message not found in session")
        row = await (
            await c.execute(
                "INSERT INTO enterprise.messages(tenant_id,owner_id,session_id,role,content,capability,events,attachments,metadata,parent_message_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (
                    *self._owner,
                    session_id,
                    role,
                    content or "",
                    capability or "",
                    _json(events or []),
                    _json(attachments or []),
                    _json(metadata or {}),
                    parent,
                ),
            )
        ).fetchone()
        from .session_resources import link_attachments

        await link_attachments(self, c, session, row["id"], attachments)
        await link_attachments(self, c, session, row["id"], snapshot_attachments(metadata))
        await record_references(
            self, c, session_id, "message", row["id"], [metadata or {}, events or []]
        )
        await c.execute(
            "UPDATE enterprise.sessions SET active_leaf_id=%s,updated_at=%s,version=version+1 WHERE tenant_id=%s AND owner_id=%s AND id=%s",
            (row["id"], time.time(), *self._owner, session_id),
        )
        return row["id"]

    async def add_message(
        self,
        session_id,
        role,
        content,
        capability="",
        events=None,
        attachments=None,
        metadata=None,
        parent_message_id=_PARENT_AUTO,
    ):
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            return await self._add_message(
                c,
                session_id,
                role,
                content,
                capability,
                events,
                attachments,
                metadata,
                parent_message_id,
            )

    async def _link_message(self, turn_id, message_id, *, user_message=False):
        async with self.db.transaction(self.scope) as c:
            current = await self._turn(c, turn_id)
            if not current:
                return False
            self._require_session(
                await self._session(c, current["session_id"], lock=True), allow_deleting=True
            )
            turn = await self._turn(c, turn_id, lock=True)
            if not turn:
                return False
            message = await self._message(c, turn["session_id"], message_id)
            field = "user_message_id" if user_message else "assistant_message_id"
            role = "user" if user_message else "assistant"
            if not message or message["role"] != role or turn[field] is not None:
                return False
            if not user_message and await self._linked_turn(c, turn["session_id"], int(message_id)):
                return False
            await c.execute(
                f"UPDATE enterprise.turns SET {field}=%s,updated_at=%s WHERE tenant_id=%s AND user_id=%s AND id=%s",
                (int(message_id), time.time(), *self._owner, turn_id),
            )
            return True

    async def link_turn_message(self, turn_id, assistant_message_id):
        return await self._link_message(turn_id, assistant_message_id)

    async def link_turn_user_message(self, turn_id, user_message_id):
        return await self._link_message(turn_id, user_message_id, user_message=True)

    async def finalize_turn(
        self,
        turn_id,
        *,
        status,
        content="",
        capability="chat",
        parent_message_id=_PARENT_AUTO,
        metadata=None,
        attachments=None,
        user_message_id=None,
        error="",
        events=None,
        fencing_token=None,
        failure_code="",
        retryable=False,
    ):
        """返回的 events 已提交；调用方只能在本方法返回后发布 done。"""
        if status not in TERMINAL:
            raise ValueError("finalize_turn requires a terminal status")
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            current = await self._turn(c, turn_id)
            if not current:
                raise ValueError("Turn not found")
            self._require_session(
                await self._session(c, current["session_id"], lock=True), allow_deleting=True
            )
            turn = await self._turn(c, turn_id, lock=True)
            if fencing_token is not None and turn["fencing_token"] != int(fencing_token):
                raise RuntimeError("Turn lease lost")
            if turn["status"] in TERMINAL:
                committed = [
                    e
                    for e in await self._events(c, turn_id)
                    if e.get("type") in {"done", "error", "cancelled"}
                ]
                return {
                    "turn": self._turn_payload(turn),
                    "assistant_message_id": turn["assistant_message_id"],
                    "events": _public(committed),
                    "replayed": True,
                }
            if user_message_id is not None:
                user = await self._message(c, turn["session_id"], user_message_id)
                if not user or user["role"] != "user":
                    raise ValueError("User message not found in session")
                if turn["user_message_id"] not in (None, int(user_message_id)):
                    raise ValueError("Turn user message conflict")
                await c.execute(
                    "UPDATE enterprise.turns SET user_message_id=%s WHERE tenant_id=%s AND user_id=%s AND id=%s",
                    (int(user_message_id), *self._owner, turn_id),
                )
                if parent_message_id is _PARENT_AUTO:
                    parent_message_id = int(user_message_id)
            message_id = turn["assistant_message_id"]
            if message_id is None and (content or attachments or status == "completed"):
                message_id = await self._add_message(
                    c,
                    turn["session_id"],
                    "assistant",
                    content,
                    capability,
                    attachments=attachments,
                    metadata=metadata,
                    parent_message_id=parent_message_id,
                    allow_deleting=True,
                )
                await c.execute(
                    "UPDATE enterprise.turns SET assistant_message_id=%s WHERE tenant_id=%s AND user_id=%s AND id=%s",
                    (message_id, *self._owner, turn_id),
                )
            terminal_events = deepcopy(events or [])
            if sum(e.get("type") == "done" for e in terminal_events) > 1:
                raise ValueError("Only one done event is allowed")
            if not any(e.get("type") == "done" for e in terminal_events):
                terminal_events.append({"type": "done", "metadata": {}})
            if terminal_events[-1].get("type") != "done":
                raise ValueError("done must be the last terminal event")
            done = terminal_events[-1]
            done["metadata"] = {
                **(done.get("metadata") or {}),
                "status": status,
                "message_id": message_id,
                "assistant_message_id": message_id,
                "user_message_id": int(user_message_id)
                if user_message_id is not None
                else turn["user_message_id"],
            }
            if error:
                done["metadata"]["error"] = error
            committed = await self._append_events(
                c, turn, terminal_events, fencing_token=fencing_token
            )
            await self._set_status(c, turn_id, status, error, failure_code, retryable)
            await self._audit(c, "turn.finalize", turn_id, status)
            return {
                "turn": self._turn_payload(await self._turn(c, turn_id)),
                "assistant_message_id": message_id,
                "events": _public(committed),
                "replayed": False,
            }

    async def _message_rows(self, c, session_id):
        return await (
            await c.execute(
                "SELECT * FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND session_id=%s ORDER BY id",
                (*self._owner, session_id),
            )
        ).fetchall()

    async def _linked_turn(self, c, session_id, message_id):
        return await (
            await c.execute(
                "SELECT * FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND session_id=%s AND assistant_message_id=%s ORDER BY created_at LIMIT 1",
                (*self._owner, session_id, message_id),
            )
        ).fetchone()

    async def _preview(self, c, turn, legacy_events):
        if turn:
            stats = await (
                await c.execute(
                    "SELECT count(*) AS total,coalesce(max(seq),0) AS last_seq,min((event->>'timestamp')::double precision) AS started_at,max((event->>'timestamp')::double precision) AS ended_at FROM enterprise.turn_events WHERE tenant_id=%s AND owner_id=%s AND turn_id=%s",
                    (*self._owner, turn["id"]),
                )
            ).fetchone()
            cards = "(event->'metadata' ?| array['ask_user','ask_user_resolved','mastery_question'] OR event->'metadata'->'tool_metadata' ?| array['ask_user','mastery_question'])"
            rows_by_seq = {}
            for types in (
                ["done", "error", "cancelled", "result"],
                ["done", "error", "cancelled", "result", "tool_call", "tool_result"],
            ):
                rows = await (
                    await c.execute(
                        f"SELECT seq,event FROM enterprise.turn_events WHERE tenant_id=%s AND owner_id=%s AND turn_id=%s AND (event->>'type'=ANY(%s) OR {cards}) ORDER BY seq DESC LIMIT %s",
                        (*self._owner, turn["id"], types, MAX_TRACE_PREVIEW_EVENTS),
                    )
                ).fetchall()
                rows_by_seq.update({r["seq"]: r["event"] for r in rows})
            source = [rows_by_seq[seq] for seq in sorted(rows_by_seq)]
        else:
            source = legacy_events
            stamps = [
                e["timestamp"] for e in source if isinstance(e.get("timestamp"), (int, float))
            ]
            stats = {
                "total": len(source),
                "last_seq": max((int(e.get("seq") or 0) for e in source), default=0),
                "started_at": min(stamps, default=None),
                "ended_at": max(stamps, default=None),
            }
        preview, compacted = compact_trace_preview(_public(source))
        trace = {
            "turn_id": turn["id"] if turn else None,
            "total": stats["total"],
            "last_seq": stats["last_seq"],
            "truncated": compacted or stats["total"] != len(preview),
        }
        if stats["started_at"] is not None and stats["ended_at"] is not None:
            trace.update(
                started_at=stats["started_at"], ended_at=max(stats["started_at"], stats["ended_at"])
            )
        return preview, trace

    async def _messages(self, c, session_id):
        result = []
        for row in await self._message_rows(c, session_id):
            payload = {k: v for k, v in row.items() if k not in ("tenant_id", "owner_id")}
            if row["role"] == "assistant":
                turn = await self._linked_turn(c, session_id, row["id"])
                payload["events"], payload["trace"] = await self._preview(c, turn, row["events"])
            result.append(payload)
        return result

    async def get_messages(self, session_id):
        async with self.db.transaction(self.scope) as c:
            return await self._messages(c, session_id)

    async def get_last_message(self, session_id, role=None):
        async with self.db.transaction(self.scope) as c:
            query = "SELECT * FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND session_id=%s"
            args = (*self._owner, session_id)
            if role is not None:
                query += " AND role=%s"
                args += (role,)
            row = await (await c.execute(query + " ORDER BY id DESC LIMIT 1", args)).fetchone()
            return (
                {k: v for k, v in row.items() if k not in ("tenant_id", "owner_id")}
                if row
                else None
            )

    async def _path(self, c, session_id, leaf_message_id):
        rows = await self._message_rows(c, session_id)
        by_id = {r["id"]: r for r in rows}
        current = int(leaf_message_id)
        if current not in by_id:
            raise ValueError("Leaf message not found in session")
        chain = []
        seen = set()
        while current is not None:
            if current in seen or current not in by_id:
                raise RuntimeError("Invalid message parent chain")
            seen.add(current)
            row = by_id[current]
            chain.append(row)
            current = row["parent_message_id"]
        return list(reversed(chain))

    async def get_message_path(self, session_id, leaf_message_id):
        async with self.db.transaction(self.scope) as c:
            return [
                {k: v for k, v in row.items() if k not in ("tenant_id", "owner_id")}
                for row in await self._path(c, session_id, leaf_message_id)
            ]

    async def get_messages_for_context(self, session_id, leaf_message_id=None):
        async with self.db.transaction(self.scope) as c:
            session = await self._session(c, session_id)
            if not session:
                return []
            leaf = leaf_message_id if leaf_message_id is not None else session["active_leaf_id"]
            rows = (
                await self._path(c, session_id, leaf)
                if leaf is not None
                else await self._message_rows(c, session_id)
            )
            result = []
            for row in rows:
                if row["role"] not in ("user", "assistant", "system"):
                    continue
                turn = await self._linked_turn(c, session_id, row["id"])
                if turn:
                    events = [
                        r["event"]
                        for r in await (
                            await c.execute(
                                "SELECT event FROM enterprise.turn_events WHERE tenant_id=%s AND owner_id=%s AND turn_id=%s AND (event->'metadata' ?| array['ask_user','ask_user_resolved'] OR event->'metadata'->'tool_metadata' ? 'ask_user') ORDER BY seq DESC LIMIT %s",
                                (*self._owner, turn["id"], MAX_TRACE_PREVIEW_EVENTS),
                            )
                        ).fetchall()
                    ]
                    events.reverse()
                else:
                    events = row["events"]
                result.append(
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"],
                        "metadata": row["metadata"],
                        "events": filter_ask_user_events(events),
                    }
                )
            return result

    async def get_session_with_messages(self, session_id):
        async with self.db.transaction(self.scope) as c:
            row = await self._session(c, session_id)
            if not row:
                return None
            session = await self._session_payload(c, row)
            session["messages"] = await self._messages(c, session_id)
            redact_private_message_metadata(session["messages"])
            session["messages"] = _public(session["messages"])
            session["active_turns"] = await self._active_turns(c, session_id)
            return session

    async def get_message_trace(self, session_id, message_id, after_seq=0, limit=None):
        async with self.db.transaction(self.scope) as c:
            if not await self._message(c, session_id, message_id):
                return None
            turn = await self._linked_turn(c, session_id, int(message_id))
            events = (
                await self._events(
                    c,
                    turn["id"],
                    after_seq,
                    500 if limit is None else max(1, min(1000, int(limit))),
                )
                if turn
                else []
            )
            stats = (
                await (
                    await c.execute(
                        "SELECT count(*) AS total,coalesce(max(seq),0) AS last_seq FROM enterprise.turn_events WHERE tenant_id=%s AND owner_id=%s AND turn_id=%s",
                        (*self._owner, turn["id"]),
                    )
                ).fetchone()
                if turn
                else {"total": 0, "last_seq": 0}
            )
            cursor = events[-1]["seq"] if events else max(0, int(after_seq))
            complete = cursor >= stats["last_seq"]
            return {
                "session_id": session_id,
                "message_id": int(message_id),
                "turn_id": turn["id"] if turn else None,
                "events": _public(events),
                "total": stats["total"],
                "last_seq": stats["last_seq"],
                "next_seq": None if complete else cursor,
                "complete": complete,
            }

    async def _validate_references(self, c, value, *, allow_snapshot_attachments=False):
        from .session_references import references

        validate_reference_shape(value, allow_snapshot_attachments=allow_snapshot_attachments)
        for key, item in set(references(value)):
            table, column = REFERENCE_TABLES[key]
            if not await (
                await c.execute(
                    f"SELECT 1 FROM enterprise.{table} WHERE tenant_id=%s AND owner_id=%s AND {column}=%s",
                    (*self._owner, item),
                )
            ).fetchone():
                raise ValueError("session reference unavailable in this scope")

    async def _check_dependencies(self, c, session):
        if session["unresolved_dependencies"]:
            raise QuestionBankReferenceConflict(
                "Session external dependency requires an upstream authority provider"
            )
        try:
            await self._validate_references(c, session["preferences"])
        except ValueError as exc:
            raise RuntimeError("Session external dependency is not supported") from exc
        # 不把所有 message/trace 载荷拉到 Python。旧未登记附件仍须受控拒绝。
        bad = await (
            await c.execute(
                SQL_UNREGISTERED_ATTACHMENTS,
                (*self._owner, session["id"]),
            )
        ).fetchone()
        if bad:
            raise RuntimeError("Message external dependency is not registered")

    async def mark_deleting(self, session_id):
        return bool(await self.claim_deletion(session_id))

    async def claim_deletion(self, session_id):
        """返回当前删除意图 token；跨 await 回调必须带回此 token。"""
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            session = await self._session(c, session_id, lock=True)
            if not session:
                return None
            await self._check_dependencies(c, session)
            token = session["deletion_token"] or uuid4()
            await c.execute(
                "UPDATE enterprise.sessions SET deleting=true,deletion_token=%s,version=version+1,updated_at=%s WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (token, time.time(), *self._owner, session_id),
            )
            return str(token)

    async def _release_known_failed_delete(self, session_id, token):
        if token is None:
            return
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            session = await self._session(c, session_id, lock=True)
            if (
                session
                and str(session["deletion_token"]) == str(token)
                and not await self._active_turns(c, session_id)
            ):
                await c.execute(
                    "UPDATE enterprise.sessions SET deleting=false,deletion_token=NULL,version=version+1 WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                    (*self._owner, session_id),
                )

    async def _tombstone(self, c, *, session_id, turn_ids=None):
        query = "UPDATE enterprise.operations SET status='deleted',request=NULL,session_id=NULL,turn_id=NULL WHERE tenant_id=%s AND owner_id=%s AND session_id=%s"
        args = (*self._owner, session_id)
        if turn_ids is not None:
            query += " AND turn_id=ANY(%s)"
            args += (turn_ids,)
        await c.execute(query, args)

    async def _audit(self, c, action, target, result="deleted"):
        await c.execute(
            "INSERT INTO enterprise.audit(tenant_id,actor_id,action,target_id,request_id,result) VALUES(%s,%s,%s,%s,%s,%s)",
            (*self._owner, action, str(target), uuid4().hex, result),
        )

    async def delete_session(self, session_id, *, deletion_token=None):
        import psycopg

        if deletion_token is None:
            # 兼容 mark_deleting + delete；先绑定既有代际，后续锁内仍验证 token。
            async with self.db.transaction(self.scope) as c:
                row = await self._session(c, session_id)
                if row and row["deletion_token"]:
                    deletion_token = str(row["deletion_token"])
        try:
            return await self._delete_session(session_id, deletion_token)
        except QuestionBankReferenceConflict:
            await self._release_known_failed_delete(session_id, deletion_token)
            raise
        except psycopg.errors.ForeignKeyViolation as exc:
            # 仅驱动确定已回滚的引用错误可解除门禁；取消/COMMIT unknown 不走此分支。
            await self._release_known_failed_delete(session_id, deletion_token)
            raise QuestionBankReferenceConflict(
                "Session is referenced by another domain; detach the reference first"
            ) from exc

    async def _delete_session(self, session_id, deletion_token):
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            return await self._workflow(
                c, session_workflows.delete_session(session_id, deletion_token)
            )

    async def _delete_messages(self, c, session, ids):
        session_id = session["id"]
        await self._check_dependencies(c, session)
        # 删除 user 代表删除该轮所有回答分支；不能删除 turn 后遗留无 trace 的回答。
        users = await (
            await c.execute(
                "SELECT id FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND session_id=%s AND id=ANY(%s) AND role='user'",
                (*self._owner, session_id, ids),
            )
        ).fetchall()
        if users:
            siblings = await (
                await c.execute(
                    "SELECT id FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND session_id=%s AND parent_message_id=ANY(%s) AND role='assistant'",
                    (*self._owner, session_id, [row["id"] for row in users]),
                )
            ).fetchall()
            ids = list(dict.fromkeys([*ids, *(row["id"] for row in siblings)]))
        turns = await (
            await c.execute(
                "SELECT id,assistant_message_id FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND session_id=%s AND (assistant_message_id=ANY(%s) OR user_message_id=ANY(%s))",
                (*self._owner, session_id, ids, ids),
            )
        ).fetchall()
        # 显式 user_message_id 是权威关联，不能只按 parent 指针寻找最终回答。
        ids = list(
            dict.fromkeys(
                [
                    *ids,
                    *(
                        row["assistant_message_id"]
                        for row in turns
                        if row["assistant_message_id"] is not None
                    ),
                ]
            )
        )
        turn_ids = [row["id"] for row in turns]
        if turn_ids:
            referenced = await (
                await c.execute(
                    "SELECT id FROM enterprise.notebook_entries"
                    " WHERE tenant_id=%s AND owner_id=%s AND execution_turn_id=ANY(%s) LIMIT 1",
                    (*self._owner, turn_ids),
                )
            ).fetchone()
            if referenced is not None:
                raise QuestionBankReferenceConflict(
                    "Turn is still referenced by a question-bank entry; delete the entry first"
                )
        await self._tombstone(c, session_id=session_id, turn_ids=turn_ids)
        await c.execute(
            "DELETE FROM enterprise.turns WHERE tenant_id=%s AND user_id=%s AND session_id=%s AND id=ANY(%s)",
            (*self._owner, session_id, turn_ids),
        )
        # 先从叶向根收缩树，再删除消息，保持其余分支及复合 FK 有效。
        leaf = session["active_leaf_id"]
        for mid in sorted(ids, reverse=True):
            row = await self._message(c, session_id, mid)
            if row:
                await c.execute(
                    "UPDATE enterprise.messages SET parent_message_id=%s WHERE tenant_id=%s AND owner_id=%s AND session_id=%s AND parent_message_id=%s",
                    (row["parent_message_id"], *self._owner, session_id, mid),
                )
                if leaf == mid:
                    leaf = row["parent_message_id"]
        reset_summary = session["summary_up_to_msg_id"] is not None and any(
            mid <= session["summary_up_to_msg_id"] for mid in ids
        )
        prefs = dict(session["preferences"])
        if "selected_branches" in prefs:
            prefs["selected_branches"] = {
                k: v
                for k, v in prefs["selected_branches"].items()
                if v not in ids and k not in {str(i) for i in ids}
            }
        if "active_leaf_id" in prefs:
            prefs["active_leaf_id"] = leaf
        await c.execute(
            "UPDATE enterprise.sessions SET active_leaf_id=%s,preferences=%s,summary=%s,summary_up_to_msg_id=%s,updated_at=%s,version=version+1 WHERE tenant_id=%s AND owner_id=%s AND id=%s",
            (
                leaf,
                _json(prefs),
                "" if reset_summary else session["summary"],
                None if reset_summary else session["summary_up_to_msg_id"],
                time.time(),
                *self._owner,
                session_id,
            ),
        )
        object_ids = [
            r["object_id"]
            for r in await (
                await c.execute(
                    "SELECT DISTINCT object_id FROM enterprise.message_objects WHERE tenant_id=%s AND owner_id=%s AND session_id=%s AND message_id=ANY(%s)",
                    (*self._owner, session_id, ids),
                )
            ).fetchall()
        ]
        await c.execute(
            "DELETE FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND session_id=%s AND id=ANY(%s)",
            (*self._owner, session_id, ids),
        )
        if object_ids:
            await c.execute(
                "UPDATE enterprise.session_objects o SET state='cleanup',updated_at=now() WHERE o.tenant_id=%s AND o.owner_id=%s AND o.object_id=ANY(%s) AND NOT EXISTS(SELECT 1 FROM enterprise.message_objects m WHERE m.tenant_id=o.tenant_id AND m.owner_id=o.owner_id AND m.object_id=o.object_id)",
                (*self._owner, object_ids),
            )
        if session["active_leaf_id"] in ids:
            leaf = await self._selected_leaf(c, session_id, prefs.get("selected_branches", {}))
            if "active_leaf_id" in prefs:
                prefs["active_leaf_id"] = leaf
            await c.execute(
                "UPDATE enterprise.sessions SET active_leaf_id=%s,preferences=%s WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (leaf, _json(prefs), *self._owner, session_id),
            )
        await self._audit(c, "message.delete", ",".join(map(str, ids)))
        return turn_ids

    async def delete_message(self, message_id):
        import psycopg

        try:
            return await self._delete_message(message_id)
        except psycopg.errors.ForeignKeyViolation as exc:
            raise QuestionBankReferenceConflict(
                "Message or turn is referenced by another domain; detach the reference first"
            ) from exc

    async def _delete_message(self, message_id):
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            row = await (
                await c.execute(
                    "SELECT session_id FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                    (*self._owner, int(message_id)),
                )
            ).fetchone()
            if not row:
                return False
            session = self._require_session(await self._session(c, row["session_id"], lock=True))
            if await self._active_turns(c, row["session_id"]):
                raise RuntimeError("Session has active execution")
            await self._delete_messages(c, session, [int(message_id)])
            return True

    async def delete_turn_by_message(self, session_id, message_id):
        import psycopg

        try:
            return await self._delete_turn_by_message(session_id, message_id)
        except psycopg.errors.ForeignKeyViolation as exc:
            raise QuestionBankReferenceConflict(
                "Message or turn is referenced by another domain; detach the reference first"
            ) from exc

    async def _delete_turn_by_message(self, session_id, message_id):
        result = {"deleted": False, "attachment_ids": [], "turn_id": None, "was_running": False}
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            session = await self._session(c, session_id, lock=True)
            message = await self._message(c, session_id, message_id) if session else None
            if not message:
                return result
            active = await self._active_turns(c, session_id)
            if active:
                return {**result, "turn_id": active[0]["id"], "was_running": True}
            self._require_session(session)
            ids = [int(message_id)]
            pair = None
            if message["role"] == "assistant" and message["parent_message_id"] is not None:
                parent = await self._message(c, session_id, message["parent_message_id"])
                if parent and parent["role"] == "user":
                    sibling = await (
                        await c.execute(
                            "SELECT id FROM enterprise.messages WHERE tenant_id=%s AND owner_id=%s AND session_id=%s AND parent_message_id=%s AND id<>%s LIMIT 1",
                            (*self._owner, session_id, parent["id"], int(message_id)),
                        )
                    ).fetchone()
                    # regenerate 复用 user；删除一个回答不能连带摧毁兄弟分支的根与 trace。
                    if not sibling:
                        pair = parent
            if pair:
                ids.append(pair["id"])
            turns = await self._delete_messages(c, session, ids)
            return {**result, "deleted": True, "turn_id": turns[0] if turns else None}

    async def import_session(
        self, session_id, title, created_at, updated_at, preferences, messages
    ):
        from .session_import import merge_import_attribution, validate_import

        title, created_at, updated_at, preferences, messages = validate_import(
            session_id, title, created_at, updated_at, preferences, messages
        )
        if _has_dependencies(preferences) or any(
            _has_dependencies(m["metadata"]) for m in messages
        ):
            raise ValueError("import contains unsupported external references")
        async with self.db.transaction(self.scope) as c:
            await self._lock_notebook_export_scope(c)
            # 同 tenant 的 ID 唯一；两个 owner 猜中同一 ID 不能覆盖或泄露对方内容。
            await c.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("session-import:" + self.scope.tenant_id + ":" + session_id,),
            )
            existing = await self._session(c, session_id, lock=True)
            if existing:
                self._require_session(existing)
                merged, changed = merge_import_attribution(existing["preferences"], preferences)
                if changed:
                    await c.execute(
                        "UPDATE enterprise.sessions SET preferences=%s,version=version+1 WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                        (_json(merged), *self._owner, session_id),
                    )
                    await self._audit(c, "session.import_attribution", session_id, "updated")
                return {
                    "session_id": session_id,
                    "imported": False,
                    "updated": changed,
                    "message_count": 0,
                }
            await self._create_session(c, title, session_id)
            parent = str(preferences.get("parent_session_id") or "").strip() or None
            await self._check_parent(c, session_id, parent)
            prefs = upgrade_workspace_preferences(preferences)
            leaf = None
            for message in messages:
                leaf = await self._add_message(
                    c,
                    session_id,
                    message["role"],
                    message["content"],
                    metadata=message["metadata"],
                    parent_message_id=leaf,
                )
                await c.execute(
                    "UPDATE enterprise.messages SET created_at=%s WHERE tenant_id=%s AND owner_id=%s AND session_id=%s AND id=%s",
                    (message["created_at"], *self._owner, session_id, leaf),
                )
            if "selected_branches" in prefs or "active_leaf_id" in prefs:
                raise ValueError("import cannot specify target message IDs")
            await c.execute(
                "UPDATE enterprise.sessions SET created_at=%s,updated_at=%s,preferences=%s,parent_session_id=%s,pinned=%s,archived=%s WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (
                    created_at,
                    updated_at,
                    _json(prefs),
                    parent,
                    bool(prefs.get("pinned")),
                    bool(prefs.get("archived")),
                    *self._owner,
                    session_id,
                ),
            )
            await self._audit(c, "session.import", session_id, "created")
            return {"session_id": session_id, "imported": True, "message_count": len(messages)}

    async def list_imported_sessions(self, limit=50, offset=0):
        return await self._list_sessions(limit, offset, imported=True)

    async def migrate_workspace_preferences(self):
        # 企业不扫描旧文件；所有新写偏好已经通过统一规范化函数。
        return 0

    async def import_legacy_session(
        self, session_id, title, created_at, updated_at, preferences, messages
    ):
        raise NotImplementedError(
            "Legacy import requires a separately approved ownership and migration workflow"
        )
