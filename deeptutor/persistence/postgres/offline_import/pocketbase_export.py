"""PocketBase 受控只读导出为离线 manifest/snapshot 制品。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .sqlite_snapshot import MANIFEST_VERSION, SourceSnapshotResult

POCKETBASE_SOURCE_VERSION = "pocketbase/v1"
POCKETBASE_SNAPSHOT_FORMAT = "pocketbase_export/v1"
MANIFEST_FILENAME = "deeptutor-pocketbase-source-manifest.json"
_TOOL_NAME = "deeptutor-pocketbase-offline-export"

APP_POCKETBASE_COLLECTIONS = (
    "users",
    "sessions",
    "messages",
    "turns",
    "turn_events",
    "knowledge_bases",
)

_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "users": frozenset(),
    "sessions": frozenset(
        {
            "session_id",
            "user_id",
            "title",
            "compressed_summary",
            "summary_up_to_msg_id",
            "preferences_json",
            "capability",
            "status",
            "session_created_at",
            "session_updated_at",
        }
    ),
    "messages": frozenset(
        {
            "session_id",
            "role",
            "content",
            "capability",
            "events_json",
            "attachments_json",
            "metadata_json",
            "msg_created_at",
        }
    ),
    "turns": frozenset(
        {
            "turn_id",
            "session_id",
            "capability",
            "status",
            "error",
            "turn_created_at",
            "turn_updated_at",
            "finished_at",
            "owner_id",
            "fencing_token",
            "state_version",
            "failure_code",
            "retryable",
            "assistant_message_id",
        }
    ),
    "turn_events": frozenset(
        {
            "turn_id",
            "session_id",
            "seq",
            "type",
            "source",
            "stage",
            "content",
            "metadata_json",
            "event_timestamp",
        }
    ),
    "knowledge_bases": frozenset(
        {
            "kb_name",
            "user_id",
            "description",
            "rag_provider",
            "needs_reindex",
            "status",
            "kb_created_at",
            "raw_files",
        }
    ),
}

_SENSITIVE_FIELD_PARTS = ("password", "token", "secret", "credential", "hash")
_USER_ALLOWED_FIELDS = frozenset(
    {"id", "created", "updated", "email", "username", "name", "role", "avatar"}
)
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class PocketBaseExportError(RuntimeError):
    """PocketBase 源无法生成一致的只读导出制品。"""


@dataclass(frozen=True)
class _CollectionSnapshot:
    schema: list[dict[str, Any]]
    records: list[dict[str, Any]]
    digest: str
    file_fields: list[str]
    files: list[dict[str, str]]



def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")



def _safe_name(value: str) -> str:
    safe = _SAFE_NAME_RE.sub("-", str(value).strip())
    return safe.strip(".-") or "pocketbase-source"



def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()



def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return _public_dict(value)
    return str(value)



def _canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))



def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()



def _public_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        raw = dict(value)
    else:
        raw = {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_") and not callable(item)
        }
    return {str(key): _jsonable(item) for key, item in sorted(raw.items(), key=lambda item: str(item[0]))}



def _is_sensitive_field(name: str) -> bool:
    lowered = name.lower()
    if lowered == "fencing_token":
        return False
    return any(part in lowered for part in _SENSITIVE_FIELD_PARTS)



def _redact_endpoint(endpoint: str) -> str:
    if not endpoint:
        return ""
    parsed = urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        return endpoint.split("?", 1)[0].split("#", 1)[0]
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))



def _collection_metadata(pb_client: Any) -> dict[str, dict[str, Any]]:
    try:
        collections = pb_client.collections.get_full_list()
    except Exception as exc:  # noqa: BLE001 - SDK/HTTP exceptions vary
        raise PocketBaseExportError("PocketBase collection metadata cannot be read") from exc

    result: dict[str, dict[str, Any]] = {}
    for collection in collections:
        name = str(getattr(collection, "name", "") or "")
        if name not in APP_POCKETBASE_COLLECTIONS:
            continue
        schema = [_public_dict(field) for field in (getattr(collection, "schema", None) or [])]
        result[name] = {
            "id": str(getattr(collection, "id", "") or ""),
            "name": name,
            "type": str(getattr(collection, "type", "") or ""),
            "schema": sorted(schema, key=lambda item: str(item.get("name") or "")),
            "indexes": _jsonable(getattr(collection, "indexes", []) or []),
        }

    missing = sorted(set(APP_POCKETBASE_COLLECTIONS) - set(result))
    if missing:
        raise PocketBaseExportError(f"PocketBase collections missing: {', '.join(missing)}")
    for name, required in _REQUIRED_FIELDS.items():
        fields = {str(field.get("name") or "") for field in result[name]["schema"]}
        absent = sorted(required - fields)
        if absent:
            raise PocketBaseExportError(
                f"PocketBase collection {name} schema missing fields: {', '.join(absent)}"
            )
    return result



def _page_total(page: Any, fallback: int) -> int:
    raw = getattr(page, "total_items", getattr(page, "totalItems", None))
    try:
        return int(raw if raw is not None else fallback)
    except (TypeError, ValueError):
        return fallback



def _page_items(page: Any) -> list[Any]:
    return list(getattr(page, "items", ()) or ())



def _schema_field_names(schema: list[dict[str, Any]]) -> list[str]:
    return [str(field.get("name") or "") for field in schema if field.get("name")]



def _file_fields(schema: list[dict[str, Any]]) -> list[str]:
    return sorted(
        str(field.get("name") or "")
        for field in schema
        if str(field.get("type") or "") == "file" and field.get("name")
    )



def _record_payload(record: Any, collection: str, schema: list[dict[str, Any]]) -> dict[str, Any]:
    public = _public_dict(record)
    payload: dict[str, Any] = {}
    for system_field in ("id", "created", "updated"):
        if system_field in public:
            payload[system_field] = public[system_field]
        elif hasattr(record, system_field):
            payload[system_field] = _jsonable(getattr(record, system_field))
    for field in _schema_field_names(schema):
        if _is_sensitive_field(field):
            continue
        if collection == "users" and field not in _USER_ALLOWED_FIELDS:
            continue
        if field in public:
            payload[field] = public[field]
        elif hasattr(record, field):
            payload[field] = _jsonable(getattr(record, field))
    if "id" not in payload:
        payload["id"] = str(getattr(record, "id", "") or "")
    return {key: payload[key] for key in sorted(payload)}



def _read_collection_once(
    pb_client: Any,
    name: str,
    *,
    schema: list[dict[str, Any]],
    page_size: int,
) -> list[dict[str, Any]]:
    collection = pb_client.collection(name)
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    expected_total: int | None = None
    page_no = 1
    while True:
        try:
            page = collection.get_list(page_no, page_size, query_params={"sort": "id"})
        except Exception as exc:  # noqa: BLE001 - SDK/HTTP exceptions vary
            raise PocketBaseExportError(f"PocketBase collection {name} cannot be read") from exc
        items = _page_items(page)
        total = _page_total(page, len(records) + len(items))
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise PocketBaseExportError(f"PocketBase collection {name} changed during export")
        for item in items:
            payload = _record_payload(item, name, schema)
            record_id = str(payload.get("id") or "")
            if not record_id:
                raise PocketBaseExportError(f"PocketBase collection {name} has a record without id")
            if record_id in seen_ids:
                raise PocketBaseExportError(f"PocketBase collection {name} changed during export")
            seen_ids.add(record_id)
            records.append(payload)
        if not items:
            break
        if expected_total is not None and len(records) >= expected_total:
            break
        page_no += 1
    if expected_total is not None and len(records) != expected_total:
        raise PocketBaseExportError(f"PocketBase collection {name} changed during export")
    records.sort(key=lambda item: str(item.get("id") or ""))
    return records



def _files_for_records(
    collection: str, records: list[dict[str, Any]], file_fields: list[str]
) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for record in records:
        record_id = str(record.get("id") or "")
        for field in file_fields:
            raw = record.get(field)
            values = raw if isinstance(raw, list) else ([raw] if raw else [])
            for value in values:
                filename = str(value or "").strip()
                if not filename:
                    continue
                files.append(
                    {
                        "collection": collection,
                        "record_id": record_id,
                        "field": field,
                        "filename": filename,
                    }
                )
    return sorted(
        files,
        key=lambda item: (item["collection"], item["record_id"], item["field"], item["filename"]),
    )



def _read_stable_collection(
    pb_client: Any,
    name: str,
    *,
    schema: list[dict[str, Any]],
    page_size: int,
) -> _CollectionSnapshot:
    first = _read_collection_once(pb_client, name, schema=schema, page_size=page_size)
    first_digest = _digest(first)
    second = _read_collection_once(pb_client, name, schema=schema, page_size=page_size)
    second_digest = _digest(second)
    if first_digest != second_digest:
        raise PocketBaseExportError(f"PocketBase collection {name} changed during export")
    files = _files_for_records(name, first, _file_fields(schema))
    return _CollectionSnapshot(
        schema=schema,
        records=first,
        digest=first_digest,
        file_fields=_file_fields(schema),
        files=files,
    )



def _manifest_owner_mappings(owner_mappings: Mapping[str, str]) -> list[dict[str, str]]:
    return [
        {"source_owner_id": str(source), "target_owner_id": str(target)}
        for source, target in sorted(owner_mappings.items(), key=lambda item: str(item[0]))
    ]



def create_pocketbase_source_export(
    *,
    pb_client: Any,
    source_endpoint: str,
    output_dir: str | Path,
    source_id: str,
    source_owner_id: str,
    target_tenant_id: str,
    owner_mappings: Mapping[str, str],
    freeze_id: str,
    stopped_writers: list[str],
    operator: str,
    page_size: int = 200,
) -> SourceSnapshotResult:
    """稳定分页读取 PocketBase 并生成 Secret-free 离线 manifest。"""

    if not str(freeze_id or "").strip() or not stopped_writers:
        raise PocketBaseExportError("freeze_id and stopped_writers are required")
    owner_map = {str(k): str(v) for k, v in owner_mappings.items()}
    if str(source_owner_id) not in owner_map:
        raise PocketBaseExportError("source owner must have an explicit target owner mapping")
    per_page = max(1, min(500, int(page_size)))

    schema_before = _collection_metadata(pb_client)
    schema_hash_before = _digest(schema_before)

    collection_snapshots: dict[str, _CollectionSnapshot] = {}
    for name in APP_POCKETBASE_COLLECTIONS:
        metadata = schema_before[name]
        collection_snapshots[name] = _read_stable_collection(
            pb_client,
            name,
            schema=metadata["schema"],
            page_size=per_page,
        )

    schema_after = _collection_metadata(pb_client)
    schema_hash_after = _digest(schema_after)
    if schema_hash_after != schema_hash_before:
        raise PocketBaseExportError("PocketBase collection schema changed during export")

    all_files = [file for snapshot in collection_snapshots.values() for file in snapshot.files]
    all_files.sort(key=lambda item: (item["collection"], item["record_id"], item["field"], item["filename"]))
    record_counts = {
        name: len(collection_snapshots[name].records) for name in sorted(APP_POCKETBASE_COLLECTIONS)
    }
    collections_payload = {
        name: {
            "schema": collection_snapshots[name].schema,
            "records": collection_snapshots[name].records,
            "count": len(collection_snapshots[name].records),
            "digest": collection_snapshots[name].digest,
            "file_fields": collection_snapshots[name].file_fields,
        }
        for name in sorted(APP_POCKETBASE_COLLECTIONS)
    }
    content_fingerprint = _digest({"collections": collections_payload, "files": all_files})
    snapshot_payload = {
        "snapshot_format": POCKETBASE_SNAPSHOT_FORMAT,
        "exported_at": _utc_now(),
        "source": {
            "endpoint": _redact_endpoint(source_endpoint),
            "collections": list(APP_POCKETBASE_COLLECTIONS),
        },
        "summary": {
            "record_counts": record_counts,
            "schema_hash": schema_hash_before,
            "content_sha256": content_fingerprint,
            "file_count": len(all_files),
        },
        "collections": collections_payload,
        "files": all_files,
    }

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    snapshot_path = out / f"{_safe_name(source_id)}.snapshot.json"
    manifest_path = out / MANIFEST_FILENAME
    snapshot_path.write_text(
        json.dumps(snapshot_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    snapshot_record = {
        "path": str(snapshot_path),
        "format": POCKETBASE_SNAPSHOT_FORMAT,
        "sha256": _sha256(snapshot_path),
        "size_bytes": snapshot_path.stat().st_size,
        "record_counts": record_counts,
        "schema_hash": schema_hash_before,
        "content_sha256": content_fingerprint,
        "file_count": len(all_files),
    }
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": _utc_now(),
        "producer": {
            "tool": _TOOL_NAME,
            "snapshot_format": POCKETBASE_SNAPSHOT_FORMAT,
        },
        "freeze": {
            "freeze_id": freeze_id,
            "operator": operator,
            "stopped_writers": list(stopped_writers),
            "recorded_at": _utc_now(),
        },
        "target": {"tenant_id": target_tenant_id},
        "owner_mappings": _manifest_owner_mappings(owner_map),
        "sources": [
            {
                "source_id": source_id,
                "source_type": "pocketbase",
                "source_version": POCKETBASE_SOURCE_VERSION,
                "source_owner_id": source_owner_id,
                "source_path": _redact_endpoint(source_endpoint),
                "snapshot": snapshot_record,
                "pocketbase": {
                    "endpoint": _redact_endpoint(source_endpoint),
                    "collections": list(APP_POCKETBASE_COLLECTIONS),
                    "file_count": len(all_files),
                    "credentials_exported": False,
                },
            }
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return SourceSnapshotResult(
        manifest_path=manifest_path,
        snapshot_path=snapshot_path,
        source_id=source_id,
    )


__all__ = [
    "APP_POCKETBASE_COLLECTIONS",
    "MANIFEST_FILENAME",
    "POCKETBASE_SNAPSHOT_FORMAT",
    "POCKETBASE_SOURCE_VERSION",
    "PocketBaseExportError",
    "create_pocketbase_source_export",
]
