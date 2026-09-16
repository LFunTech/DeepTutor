"""离线导入 ID 映射、DAG 分配与 typed 引用重写。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .registry import ReferenceField, get_reference_registry


class MissingReferenceError(ValueError):
    """已登记机器引用缺少对应 ID 映射。"""


class UnknownMachineReferenceError(ValueError):
    """发现未在版本化注册表中声明的机器引用字段。"""


@dataclass(frozen=True, slots=True)
class SourceMessage:
    source_id: int
    parent_id: int | None = None
    created_at: float = 0.0


@dataclass(frozen=True, slots=True)
class RewriteResult:
    record: dict[str, Any]
    old_links: list[dict[str, Any]]


def stable_text_id(
    *,
    domain: str,
    source_id: str,
    source_owner_id: str,
    source_key: str,
    prefix: str,
) -> str:
    """为文本 ID 生成稳定、可重试、跨 owner/source 不串线的候选目标 ID。"""

    digest = hashlib.sha256(
        "\x1f".join([domain, source_id, source_owner_id, source_key]).encode("utf-8")
    ).hexdigest()
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", source_key).strip(".-")[:24]
    readable = f"{slug}-" if slug else ""
    return f"{prefix}-{readable}{digest[:20]}"


class MigrationIdAllocator:
    """使用 migration_stage.id_mappings 持久化稳定 ID 分配。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def allocate_session_id(
        self,
        batch_id,
        *,
        tenant_id: str,
        source_id: str,
        source_owner_id: str,
        source_session_id: str,
    ) -> str:
        async with await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row
        ) as connection:
            async with connection.transaction():
                existing = await (
                    await connection.execute(
                        """
                        SELECT target_key
                          FROM migration_stage.id_mappings
                         WHERE batch_id=%s AND domain='sessions'
                           AND source_id=%s AND source_owner_id=%s
                           AND source_key=%s
                         FOR UPDATE
                        """,
                        (str(batch_id), source_id, source_owner_id, source_session_id),
                    )
                ).fetchone()
                if existing is not None:
                    return str(existing["target_key"])
                base = stable_text_id(
                    domain="sessions",
                    source_id=source_id,
                    source_owner_id=source_owner_id,
                    source_key=source_session_id,
                    prefix="sess",
                )
                candidate = base
                suffix = 1
                while await self._session_target_exists(connection, tenant_id, batch_id, candidate):
                    suffix += 1
                    candidate = f"{base}-{suffix}"
                await connection.execute(
                    """
                    INSERT INTO migration_stage.id_mappings(
                        batch_id, domain, source_id, source_owner_id, source_key,
                        target_key, metadata
                    ) VALUES (%s,'sessions',%s,%s,%s,%s,%s::jsonb)
                    """,
                    (
                        str(batch_id),
                        source_id,
                        source_owner_id,
                        source_session_id,
                        candidate,
                        Jsonb({"allocated": "stable_text_id"}),
                    ),
                )
                return candidate

    async def _session_target_exists(self, connection, tenant_id, batch_id, candidate) -> bool:
        row = await (
            await connection.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM enterprise.sessions
                     WHERE tenant_id=%s AND id=%s
                    UNION ALL
                    SELECT 1 FROM migration_stage.id_mappings
                     WHERE batch_id=%s AND domain='sessions' AND target_key=%s
                ) AS exists
                """,
                (tenant_id, candidate, str(batch_id), candidate),
            )
        ).fetchone()
        return bool(row["exists"])


def allocate_message_dag_ids(
    messages: list[SourceMessage],
    *,
    start_after: int = 0,
) -> dict[int, int]:
    """按 parent DAG 拓扑给消息分配 GENERATED ALWAYS 可导入整数 ID。"""

    by_id: dict[int, SourceMessage] = {}
    for message in messages:
        if message.source_id in by_id:
            raise ValueError(f"duplicate source message id: {message.source_id}")
        by_id[message.source_id] = message
    for message in messages:
        if message.parent_id is not None and message.parent_id not in by_id:
            raise ValueError(f"missing parent for message {message.source_id}")

    state: dict[int, str] = {}
    ordered: list[int] = []

    def visit(message_id: int) -> None:
        current = state.get(message_id)
        if current == "visiting":
            raise ValueError("cycle in message parent graph")
        if current == "done":
            return
        state[message_id] = "visiting"
        parent = by_id[message_id].parent_id
        if parent is not None:
            visit(parent)
        state[message_id] = "done"
        if message_id not in ordered:
            ordered.append(message_id)

    for message in sorted(messages, key=lambda item: (item.created_at, item.source_id)):
        visit(message.source_id)

    return {source_id: start_after + index + 1 for index, source_id in enumerate(ordered)}


async def advance_identity_sequence(connection, table: str, column: str) -> None:
    """将 identity/serial sequence 推进到目标表已占用 ID 上界。"""

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError("table must be schema-qualified")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column):
        raise ValueError("invalid column")
    schema, name = table.split(".", 1)
    seq_row = await (
        await connection.execute("SELECT pg_get_serial_sequence(%s,%s)", (table, column))
    ).fetchone()
    seq_name = _first_value(seq_row)
    if seq_name is None:
        raise ValueError(f"{table}.{column} has no identity sequence")
    max_row = await (
        await connection.execute(
            sql.SQL("SELECT COALESCE(max({column}),0) FROM {schema}.{table}").format(
                column=sql.Identifier(column),
                schema=sql.Identifier(schema),
                table=sql.Identifier(name),
            )
        )
    ).fetchone()
    max_id = int(_first_value(max_row) or 0)
    await connection.execute("SELECT setval(%s,%s,%s)", (seq_name, max(max_id, 1), max_id > 0))


def _first_value(row):
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


class TypedReferenceRewriter:
    """按版本化 registry 重写结构化字段和 typed JSON 机器引用。"""

    def __init__(self, source_version: str) -> None:
        self.registry = get_reference_registry(source_version)

    def rewrite(
        self,
        table: str,
        record: dict[str, Any],
        mappings: dict[str, dict[Any, Any]],
    ) -> RewriteResult:
        import copy

        result = copy.deepcopy(record)
        old_links: list[dict[str, Any]] = []
        fields = [
            field
            for field in self.registry.reference_fields
            if field.path.startswith(f"{table}.")
        ]
        self._reject_unknown_machine_refs(table, result, fields)
        for field in fields:
            parts = field.path.removeprefix(f"{table}.").split(".")
            self._rewrite_path(result, parts, field, mappings, old_links)
        return RewriteResult(record=result, old_links=old_links)

    def _rewrite_path(
        self,
        current: Any,
        parts: list[str],
        field: ReferenceField,
        mappings: dict[str, dict[Any, Any]],
        old_links: list[dict[str, Any]],
    ) -> None:
        if not parts:
            return
        head = parts[0]
        if head.endswith("[*]"):
            key = head[:-3]
            values = current.get(key) if isinstance(current, dict) else None
            if not isinstance(values, list):
                return
            for item in values:
                self._rewrite_path(item, parts[1:], field, mappings, old_links)
            return
        if not isinstance(current, dict) or head not in current:
            return
        if len(parts) > 1:
            self._rewrite_path(current[head], parts[1:], field, mappings, old_links)
            return
        value = current.get(head)
        if value in (None, "", 0):
            return
        if field.rewrite == "preserve_audit_only":
            old_links.append({"path": field.path, "value": value, "target": field.target})
            return
        current[head] = self._mapped_value(field, value, mappings)

    @staticmethod
    def _mapped_value(
        field: ReferenceField,
        value: Any,
        mappings: dict[str, dict[Any, Any]],
    ) -> Any:
        table = mappings.get(field.target)
        if table is None:
            raise MissingReferenceError(f"missing mapping table for {field.target}")
        if value in table:
            return table[value]
        text = str(value)
        if text in table:
            return table[text]
        raise MissingReferenceError(f"missing mapping for {field.path}={value!r}")

    def _reject_unknown_machine_refs(
        self,
        table: str,
        record: dict[str, Any],
        fields: list[ReferenceField],
    ) -> None:
        known = {field.path for field in fields}

        def scan(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    child_path = f"{path}.{key}"
                    if (
                        child not in (None, "", 0)
                        and (key == "id" or key.endswith("_id"))
                        and child_path not in known
                    ):
                        raise UnknownMachineReferenceError(
                            f"unknown machine reference path: {child_path}"
                        )
                    scan(child, child_path)
            elif isinstance(value, list):
                for child in value:
                    scan(child, f"{path}[*]")

        for key, value in record.items():
            if key.endswith("_json"):
                scan(value, f"{table}.{key}")


__all__ = [
    "MigrationIdAllocator",
    "MissingReferenceError",
    "RewriteResult",
    "SourceMessage",
    "TypedReferenceRewriter",
    "UnknownMachineReferenceError",
    "advance_identity_sequence",
    "allocate_message_dag_ids",
    "stable_text_id",
]
