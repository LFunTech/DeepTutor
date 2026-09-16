"""PocketBase 只读 exporter 与 manifest。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


class _Page:
    def __init__(self, items: list[Any], total: int) -> None:
        self.items = items
        self.total_items = total
        self.totalItems = total


class _FakeCollection:
    def __init__(
        self,
        name: str,
        records: list[dict[str, Any]],
        calls: list[tuple[str, int, int, dict[str, Any]]],
        *,
        fail: bool = False,
        mutate_after_first_pass: bool = False,
    ) -> None:
        self.name = name
        self._records = [dict(record) for record in records]
        self._calls = calls
        self._fail = fail
        self._mutate_after_first_pass = mutate_after_first_pass
        self._first_pass_done = False
        self.write_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def get_list(self, page: int, per_page: int, query_params: dict[str, Any] | None = None):
        if self._fail:
            raise PermissionError(f"collection {self.name} denied")
        params = dict(query_params or {})
        assert params.get("sort") == "id"
        self._calls.append((self.name, page, per_page, params))
        if self._mutate_after_first_pass and self._first_pass_done and self._records:
            self._records[0]["content"] = "changed while exporting"
            self._mutate_after_first_pass = False
        rows = sorted(self._records, key=lambda item: str(item.get("id") or ""))
        start = (page - 1) * per_page
        end = start + per_page
        items = [SimpleNamespace(**row) for row in rows[start:end]]
        if page * per_page >= len(rows) and not self._first_pass_done:
            self._first_pass_done = True
        return _Page(items, len(rows))

    def create(self, *args: Any, **kwargs: Any):
        self.write_calls.append(("create", args, kwargs))
        raise AssertionError("exporter must not create PocketBase records")

    def update(self, *args: Any, **kwargs: Any):
        self.write_calls.append(("update", args, kwargs))
        raise AssertionError("exporter must not update PocketBase records")

    def delete(self, *args: Any, **kwargs: Any):
        self.write_calls.append(("delete", args, kwargs))
        raise AssertionError("exporter must not delete PocketBase records")


class _FakeCollectionsApi:
    def __init__(self, schemas: dict[str, list[dict[str, Any]]], *, fail: bool = False) -> None:
        self._schemas = schemas
        self._fail = fail
        self.write_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def get_full_list(self):
        if self._fail:
            raise PermissionError("collections metadata denied")
        return [
            SimpleNamespace(
                id=f"col_{name}",
                name=name,
                type="auth" if name == "users" else "base",
                schema=[SimpleNamespace(**field) for field in fields],
                indexes=[],
            )
            for name, fields in self._schemas.items()
        ]

    def create(self, *args: Any, **kwargs: Any):
        self.write_calls.append(("create", args, kwargs))
        raise AssertionError("exporter must not create PocketBase collections")

    def update(self, *args: Any, **kwargs: Any):
        self.write_calls.append(("update", args, kwargs))
        raise AssertionError("exporter must not update PocketBase collections")


class _FakePocketBase:
    def __init__(
        self,
        records: dict[str, list[dict[str, Any]]],
        schemas: dict[str, list[dict[str, Any]]],
        *,
        fail_collection: str | None = None,
        fail_schema: bool = False,
        mutate_collection: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, int, int, dict[str, Any]]] = []
        self.collections = _FakeCollectionsApi(schemas, fail=fail_schema)
        self._collections = {
            name: _FakeCollection(
                name,
                rows,
                self.calls,
                fail=name == fail_collection,
                mutate_after_first_pass=name == mutate_collection,
            )
            for name, rows in records.items()
        }

    def collection(self, name: str) -> _FakeCollection:
        return self._collections[name]


_SCHEMA = {
    "users": [
        {"name": "email", "type": "email", "required": False},
        {"name": "username", "type": "text", "required": False},
        {"name": "name", "type": "text", "required": False},
        {"name": "role", "type": "text", "required": False},
        {"name": "tokenKey", "type": "text", "required": False},
    ],
    "sessions": [
        {"name": "session_id", "type": "text", "required": True},
        {"name": "user_id", "type": "text", "required": False},
        {"name": "title", "type": "text", "required": False},
        {"name": "compressed_summary", "type": "text", "required": False},
        {"name": "summary_up_to_msg_id", "type": "number", "required": False},
        {"name": "preferences_json", "type": "json", "required": False},
        {"name": "capability", "type": "text", "required": False},
        {"name": "status", "type": "text", "required": False},
        {"name": "session_created_at", "type": "number", "required": False},
        {"name": "session_updated_at", "type": "number", "required": False},
    ],
    "messages": [
        {"name": "session_id", "type": "text", "required": True},
        {"name": "role", "type": "text", "required": True},
        {"name": "content", "type": "text", "required": False},
        {"name": "capability", "type": "text", "required": False},
        {"name": "events_json", "type": "json", "required": False},
        {"name": "attachments_json", "type": "json", "required": False},
        {"name": "metadata_json", "type": "json", "required": False},
        {"name": "msg_created_at", "type": "number", "required": False},
    ],
    "turns": [
        {"name": "turn_id", "type": "text", "required": True},
        {"name": "session_id", "type": "text", "required": True},
        {"name": "capability", "type": "text", "required": False},
        {"name": "status", "type": "text", "required": False},
        {"name": "error", "type": "text", "required": False},
        {"name": "turn_created_at", "type": "number", "required": False},
        {"name": "turn_updated_at", "type": "number", "required": False},
        {"name": "finished_at", "type": "number", "required": False},
        {"name": "owner_id", "type": "text", "required": False},
        {"name": "fencing_token", "type": "number", "required": False},
        {"name": "state_version", "type": "number", "required": False},
        {"name": "failure_code", "type": "text", "required": False},
        {"name": "retryable", "type": "bool", "required": False},
        {"name": "assistant_message_id", "type": "text", "required": False},
    ],
    "turn_events": [
        {"name": "turn_id", "type": "text", "required": True},
        {"name": "session_id", "type": "text", "required": False},
        {"name": "seq", "type": "number", "required": True},
        {"name": "type", "type": "text", "required": False},
        {"name": "source", "type": "text", "required": False},
        {"name": "stage", "type": "text", "required": False},
        {"name": "content", "type": "text", "required": False},
        {"name": "metadata_json", "type": "json", "required": False},
        {"name": "event_timestamp", "type": "number", "required": False},
    ],
    "knowledge_bases": [
        {"name": "kb_name", "type": "text", "required": True},
        {"name": "user_id", "type": "text", "required": False},
        {"name": "description", "type": "text", "required": False},
        {"name": "rag_provider", "type": "text", "required": False},
        {"name": "needs_reindex", "type": "bool", "required": False},
        {"name": "status", "type": "text", "required": False},
        {"name": "kb_created_at", "type": "text", "required": False},
        {"name": "raw_files", "type": "file", "required": False},
    ],
}


def _records() -> dict[str, list[dict[str, Any]]]:
    return {
        "users": [
            {
                "id": "pb-user-1",
                "email": "learner@example.org",
                "username": "learner",
                "name": "Learner",
                "role": "user",
                "tokenKey": "PB_USER_TOKEN_SECRET",
                "created": "2026-01-01 00:00:00Z",
                "updated": "2026-01-02 00:00:00Z",
            }
        ],
        "sessions": [
            {
                "id": "pb-session-row-1",
                "session_id": "s1",
                "user_id": "pb-user-1",
                "title": "Algebra",
                "compressed_summary": "summary",
                "summary_up_to_msg_id": 0,
                "preferences_json": {"layout": "default"},
                "capability": "chat",
                "status": "idle",
                "session_created_at": 10.0,
                "session_updated_at": 20.0,
            }
        ],
        "messages": [
            {
                "id": "pb-msg-a",
                "session_id": "s1",
                "role": "user",
                "content": "hello",
                "capability": "chat",
                "events_json": [],
                "attachments_json": [{"id": "att-1", "name": "diagram.png"}],
                "metadata_json": {"source": "test"},
                "msg_created_at": 11.0,
            },
            {
                "id": "pb-msg-b",
                "session_id": "s1",
                "role": "assistant",
                "content": "hi",
                "capability": "chat",
                "events_json": [],
                "attachments_json": [],
                "metadata_json": {},
                "msg_created_at": 12.0,
            },
        ],
        "turns": [
            {
                "id": "pb-turn-row-1",
                "turn_id": "t1",
                "session_id": "s1",
                "capability": "chat",
                "status": "completed",
                "assistant_message_id": "pb-msg-b",
            }
        ],
        "turn_events": [
            {
                "id": "pb-event-row-1",
                "turn_id": "t1",
                "session_id": "s1",
                "seq": 1,
                "type": "text_delta",
                "metadata_json": {"message_id": "pb-msg-b"},
            }
        ],
        "knowledge_bases": [
            {
                "id": "pb-kb-row-1",
                "kb_name": "math",
                "user_id": "pb-user-1",
                "description": "Math KB",
                "rag_provider": "lightrag",
                "needs_reindex": False,
                "status": "ready",
                "kb_created_at": "2026-01-01T00:00:00Z",
                "raw_files": ["intro.pdf", "chapter.pdf"],
            }
        ],
    }


def test_pocketbase_export_manifest_is_read_only_stable_and_secret_free(tmp_path: Path) -> None:
    """生产 exporter 若遗漏 PB collection、文件清单、分页稳定性或泄露凭证应失败。"""

    from deeptutor.persistence.postgres.offline_import import source_check_manifest
    from deeptutor.persistence.postgres.offline_import.pocketbase_export import (
        create_pocketbase_source_export,
    )

    pb = _FakePocketBase(_records(), _SCHEMA)
    result = create_pocketbase_source_export(
        pb_client=pb,
        source_endpoint="https://admin:PB_ADMIN_PASSWORD@example.org?token=PB_TOKEN",
        output_dir=tmp_path,
        source_id="pb-main",
        source_owner_id="pb-user-1",
        target_tenant_id="tenant-1",
        owner_mappings={"pb-user-1": "owner-1"},
        freeze_id="freeze-pb",
        stopped_writers=["web", "api", "pocketbase"],
        operator="unit-test",
        page_size=1,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    snapshot = json.loads(result.snapshot_path.read_text(encoding="utf-8"))
    serialized = json.dumps({"manifest": manifest, "snapshot": snapshot}, ensure_ascii=False)
    assert "PB_ADMIN_PASSWORD" not in serialized
    assert "PB_TOKEN" not in serialized
    assert "PB_USER_TOKEN_SECRET" not in serialized
    assert manifest["sources"][0]["source_version"] == "pocketbase/v1"
    assert manifest["sources"][0]["snapshot"]["record_counts"] == {
        "knowledge_bases": 1,
        "messages": 2,
        "sessions": 1,
        "turn_events": 1,
        "turns": 1,
        "users": 1,
    }
    assert snapshot["snapshot_format"] == "pocketbase_export/v1"
    assert snapshot["collections"]["messages"]["records"][0]["id"] == "pb-msg-a"
    assert snapshot["collections"]["knowledge_bases"]["file_fields"] == ["raw_files"]
    assert snapshot["files"] == [
        {
            "collection": "knowledge_bases",
            "record_id": "pb-kb-row-1",
            "field": "raw_files",
            "filename": "chapter.pdf",
        },
        {
            "collection": "knowledge_bases",
            "record_id": "pb-kb-row-1",
            "field": "raw_files",
            "filename": "intro.pdf",
        },
    ]
    assert source_check_manifest(result.manifest_path).ok is True
    assert all(call[2] == 1 for call in pb.calls)
    assert all(call[3]["sort"] == "id" for call in pb.calls)
    assert not pb.collections.write_calls
    assert all(not collection.write_calls for collection in pb._collections.values())


def test_pocketbase_export_rejects_source_changes_during_stable_read(tmp_path: Path) -> None:
    """生产 exporter 若分页期间同记录内容变化却仍生成 manifest 应失败。"""

    from deeptutor.persistence.postgres.offline_import.pocketbase_export import (
        PocketBaseExportError,
        create_pocketbase_source_export,
    )

    pb = _FakePocketBase(_records(), _SCHEMA, mutate_collection="messages")

    with pytest.raises(PocketBaseExportError, match="changed during export"):
        create_pocketbase_source_export(
            pb_client=pb,
            source_endpoint="https://pb.example.org",
            output_dir=tmp_path,
            source_id="pb-changing",
            source_owner_id="pb-user-1",
            target_tenant_id="tenant-1",
            owner_mappings={"pb-user-1": "owner-1"},
            freeze_id="freeze-pb",
            stopped_writers=["web", "api", "pocketbase"],
            operator="unit-test",
            page_size=1,
        )

    assert not (tmp_path / "pb-changing.snapshot.json").exists()


def test_pocketbase_export_rejects_missing_collection_permission(tmp_path: Path) -> None:
    """生产 exporter 若读取任一受支持 collection 权限不足却生成残缺制品应失败。"""

    from deeptutor.persistence.postgres.offline_import.pocketbase_export import (
        PocketBaseExportError,
        create_pocketbase_source_export,
    )

    pb = _FakePocketBase(_records(), _SCHEMA, fail_collection="turn_events")

    with pytest.raises(PocketBaseExportError, match="turn_events"):
        create_pocketbase_source_export(
            pb_client=pb,
            source_endpoint="https://pb.example.org",
            output_dir=tmp_path,
            source_id="pb-denied",
            source_owner_id="pb-user-1",
            target_tenant_id="tenant-1",
            owner_mappings={"pb-user-1": "owner-1"},
            freeze_id="freeze-pb",
            stopped_writers=["web", "api", "pocketbase"],
            operator="unit-test",
            page_size=2,
        )
