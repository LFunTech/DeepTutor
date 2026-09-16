"""离线导入批次 verify/report。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Literal
from urllib.request import pathname2url

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


@dataclass(slots=True)
class OfflineVerifyReport:
    ok: bool
    batch_id: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    owners: dict[str, dict[str, Any]] = field(default_factory=dict)
    domains: dict[str, dict[str, Any]] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "batch_id": self.batch_id,
            "sources": self.sources,
            "owners": self.owners,
            "domains": self.domains,
            "issues": self.issues,
        }


def _sqlite_uri(path: Path, *, immutable: bool = True) -> str:
    query = "mode=ro"
    if immutable:
        query += "&immutable=1"
    return f"file:{pathname2url(str(path))}?{query}"


def _artifact_path(value: str | None) -> Path:
    return Path(str(value or ""))


def _json_obj(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dict(value: Any) -> dict[str, Any]:
    parsed = _json_obj(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[Any]:
    parsed = _json_obj(value, [])
    return parsed if isinstance(parsed, list) else []


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _issue(
    issues: list[dict[str, Any]],
    code: str,
    message: str,
    *,
    source_id: str | None = None,
    domain: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    item: dict[str, Any] = {"code": code, "message": message}
    if source_id:
        item["source_id"] = source_id
    if domain:
        item["domain"] = domain
    if detail:
        item["detail"] = detail
    issues.append(item)


def _nested_message_refs(value: Any) -> list[Any]:
    refs: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {
                "message_id",
                "source_message_id",
                "assistant_message_id",
                "user_message_id",
            }:
                refs.append(child)
            refs.extend(_nested_message_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_nested_message_refs(child))
    return refs


def _source_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    path = _artifact_path(source.get("snapshot", {}).get("path"))
    return json.loads(path.read_text(encoding="utf-8"))


def _source_record_counts(source: dict[str, Any]) -> dict[str, int]:
    snapshot = source.get("snapshot", {}) if isinstance(source.get("snapshot"), dict) else {}
    counts = snapshot.get("record_counts") or snapshot.get("table_counts")
    if isinstance(counts, dict):
        return {str(k): int(v) for k, v in counts.items()}
    return {}


def _read_sqlite_rows(snapshot: Path, orders: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    with sqlite3.connect(_sqlite_uri(snapshot), uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        rows: dict[str, list[dict[str, Any]]] = {}
        for table, order in orders.items():
            if table not in tables:
                rows[table] = []
                continue
            rows[table] = [
                dict(row)
                for row in connection.execute(
                    f'SELECT * FROM "{table}" {order}'  # nosec B608 - table/order 来自常量
                ).fetchall()
            ]
        return rows


def _read_chat_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_sqlite_rows(
        snapshot,
        {
            "sessions": "ORDER BY created_at, id",
            "messages": "ORDER BY id",
            "turns": "ORDER BY created_at, id",
            "turn_events": "ORDER BY turn_id, seq",
            "notebook_entries": "ORDER BY id",
            "notebook_categories": "ORDER BY id",
            "notebook_entry_categories": "ORDER BY entry_id, category_id",
        },
    )


def _read_mastery_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_sqlite_rows(
        snapshot,
        {
            "mastery_paths": "ORDER BY created_at, path_id",
            "mastery_path_sessions": "ORDER BY last_seen_at, path_id, session_id",
            "mastery_interactions": "ORDER BY created_at, interaction_id",
            "mastery_events": "ORDER BY revision, id",
            "mastery_topic_meta": "ORDER BY path_id",
            "mastery_topic_sources": "ORDER BY path_id, position, created_at, source_id",
        },
    )


def _read_reading_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_sqlite_rows(
        snapshot,
        {
            "reading_materials": "ORDER BY created_at, material_id",
            "reading_workspaces": "ORDER BY created_at, workspace_id",
            "reading_workspace_materials": "ORDER BY workspace_id, tab_order, material_id",
            "reading_workspace_sessions": "ORDER BY workspace_id, updated_at, session_id",
            "reading_session_links": "ORDER BY workspace_id, created_at, source_session_id, target_session_id",
        },
    )


def _read_cron_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_sqlite_rows(
        snapshot,
        {
            "cron_jobs": "ORDER BY COALESCE(next_run_at_ms, 0), id",
            "cron_meta": "ORDER BY singleton",
        },
    )


def _read_partner_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_sqlite_rows(
        snapshot,
        {"partner_runtime_status": "ORDER BY updated_at, partner_id"},
    )


def _read_marginnote_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_sqlite_rows(
        snapshot,
        {
            "mn4_devices": "ORDER BY paired_at, device_id",
            "mn4_cursors": "ORDER BY device_id",
            "mn4_objects": "ORDER BY updated_at, device_id, object_id",
            "mn4_tombstones": "ORDER BY deleted_at, device_id, object_id",
        },
    )


def _read_matrix_rows(snapshot: Path) -> dict[str, list[dict[str, Any]]]:
    return _read_sqlite_rows(
        snapshot,
        {
            "accounts": "ORDER BY id",
            "olmsessions": "ORDER BY sender_key, last_usage_date DESC, session_id",
            "megolminboundsessions": "ORDER BY room_id, sender_key, session_id",
            "forwardedchains": "ORDER BY session_id, id",
            "devicekeys": "ORDER BY user_id, device_id, id",
            "keys": "ORDER BY device_id, key_type",
            "devicetruststate": "ORDER BY device_id",
            "encryptedrooms": "ORDER BY room_id",
            "synctokens": "ORDER BY id",
            "outgoingkeyrequests": "ORDER BY request_id",
            "storeversion": "ORDER BY id",
        },
    )


def _source_path(source: dict[str, Any]) -> Path:
    return _artifact_path(source.get("snapshot", {}).get("path"))


def _source_hash(source: dict[str, Any]) -> str:
    path = _source_path(source)
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping_map(
    rows: list[dict[str, Any]], domain: str, *, target: Literal["key", "int"]
) -> dict[str, Any]:
    column = "target_key" if target == "key" else "target_int"
    return {
        str(row["source_key"]): row[column]
        for row in rows
        if row["domain"] == domain and row[column] is not None
    }


def _source_kb_id(source: dict[str, Any]) -> str:
    for container_key in ("resource_mappings", "target", "target_resources"):
        container = source.get(container_key)
        if isinstance(container, dict) and str(container.get("kb_id") or "").strip():
            return str(container["kb_id"]).strip()
    return ""


def _cron_was_in_flight(payload: dict[str, Any]) -> bool:
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    status = str(state.get("last_status") or "").lower()
    if status in {"claimed", "running", "in_progress", "dispatching"}:
        return True
    return any(
        bool(state.get(key))
        for key in ("dispatch_started_at_ms", "claimed_at_ms", "in_flight", "running")
    )


class OfflineImportVerifier:
    """对已导入批次做跨源、跨 owner 和语义校验。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def verify_batch(self, batch_id: str) -> OfflineVerifyReport:
        batch_id = str(batch_id)
        issues: list[dict[str, Any]] = []
        source_reports: list[dict[str, Any]] = []
        owner_reports: dict[str, dict[str, Any]] = {}
        domains: dict[str, dict[str, Any]] = {}
        async with await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row
        ) as connection:
            batch = await (
                await connection.execute(
                    """
                    SELECT batch_id, target_tenant_id, status
                      FROM migration_stage.batches
                     WHERE batch_id=%s
                    """,
                    (batch_id,),
                )
            ).fetchone()
            if batch is None:
                return OfflineVerifyReport(
                    ok=False,
                    batch_id=batch_id,
                    issues=[{"code": "batch_missing", "message": "migration batch not found"}],
                )
            rows = await (
                await connection.execute(
                    """
                    SELECT source_id, source_type, source_version, source_owner_id,
                           target_owner_id, fingerprint, manifest, status,
                           rows_total, rows_done
                      FROM migration_stage.sources
                     WHERE batch_id=%s
                     ORDER BY source_id
                    """,
                    (batch_id,),
                )
            ).fetchall()
            if not rows:
                _issue(issues, "sources_missing", "batch has no recorded sources")
            for row in rows:
                source = _json_obj(row["manifest"], {})
                source_id = str(row["source_id"])
                if row["status"] != "verified":
                    _issue(
                        issues,
                        "source_not_verified",
                        "source was not marked verified",
                        source_id=source_id,
                    )
                if int(row["rows_total"] or 0) != int(row["rows_done"] or 0):
                    _issue(
                        issues,
                        "source_rows_incomplete",
                        "source rows_done does not match rows_total",
                        source_id=source_id,
                    )
                if isinstance(source, dict):
                    expected_hash = str(source.get("snapshot", {}).get("sha256") or row["fingerprint"])
                    actual_hash = _source_hash(source)
                    if expected_hash and actual_hash and actual_hash != expected_hash:
                        _issue(
                            issues,
                            "source_fingerprint_mismatch",
                            "source artifact hash changed after import",
                            source_id=source_id,
                            detail={"expected": expected_hash, "actual": actual_hash},
                        )
                version = str(row["source_version"])
                try:
                    if version == "pocketbase/v1":
                        report = await self._verify_pocketbase(
                            connection, batch_id, row, source, issues
                        )
                    elif version == "chat_history_sqlite/v1":
                        report = await self._verify_chat_history(
                            connection, batch_id, row, source, issues
                        )
                    elif version in {"mastery_sqlite/v1", "mastery_sqlite/v2"}:
                        report = await self._verify_mastery(
                            connection, batch_id, row, source, issues
                        )
                    elif version == "reading_catalog_sqlite/v1":
                        report = await self._verify_reading(
                            connection, batch_id, row, source, issues
                        )
                    elif version == "cron_sqlite/v1":
                        report = await self._verify_cron(
                            connection, batch_id, row, source, issues
                        )
                    elif version == "partner_runtime_status_sqlite/v1":
                        report = await self._verify_partner_status(
                            connection, batch_id, row, source, issues
                        )
                    elif version == "marginnote_sqlite/v1":
                        report = await self._verify_marginnote(
                            connection, batch_id, row, source, issues
                        )
                    elif version == "matrix_nio_sqlite/v0.26":
                        report = await self._verify_matrix(
                            connection, batch_id, row, source, issues
                        )
                    else:
                        report = self._empty_source_report(row, version)
                        _issue(
                            issues,
                            "source_verify_not_implemented",
                            f"semantic verification for {version!r} is not implemented",
                            source_id=source_id,
                        )
                except Exception as exc:  # noqa: BLE001 - verify/report 必须报告坏源而非静默跳过
                    try:
                        await connection.rollback()
                    except Exception:
                        pass
                    report = self._empty_source_report(row, version)
                    _issue(
                        issues,
                        "source_verify_failed",
                        "source semantic verification failed",
                        source_id=source_id,
                        detail={"error": str(exc)},
                    )
                source_reports.append(report)
                for domain, counts in report.get("domain_counts", {}).items():
                    domains.setdefault(domain, {"source": 0, "target": 0})
                    domains[domain]["source"] += int(counts.get("source") or 0)
                    domains[domain]["target"] += int(counts.get("target") or 0)
                owner_key = f"{row['source_owner_id']}->{row['target_owner_id']}"
                owner_report = owner_reports.setdefault(
                    owner_key,
                    {
                        "source_owner_id": row["source_owner_id"],
                        "target_owner_id": row["target_owner_id"],
                        "sources": 0,
                        "domains": {},
                    },
                )
                owner_report["sources"] += 1
                for domain, counts in report.get("domain_counts", {}).items():
                    owner_domain = owner_report["domains"].setdefault(
                        domain, {"source": 0, "target": 0}
                    )
                    owner_domain["source"] += int(counts.get("source") or 0)
                    owner_domain["target"] += int(counts.get("target") or 0)
            result = OfflineVerifyReport(
                ok=not issues,
                batch_id=batch_id,
                sources=source_reports,
                owners=owner_reports,
                domains=domains,
                issues=issues,
            )
            await connection.execute(
                """
                UPDATE migration_stage.batches
                   SET verify_report=%s::jsonb, updated_at=now()
                 WHERE batch_id=%s
                """,
                (Jsonb(result.to_dict()), batch_id),
            )
            return result

    @staticmethod
    def _empty_source_report(row: dict[str, Any], version: str) -> dict[str, Any]:
        return {
            "source_id": row["source_id"],
            "source_version": version,
            "source_owner_id": row["source_owner_id"],
            "target_owner_id": row["target_owner_id"],
            "domain_counts": {},
            "content_digest": "",
        }

    async def _verify_pocketbase(
        self,
        connection,
        batch_id: str,
        row: dict[str, Any],
        source: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_id = str(row["source_id"])
        tenant_id = await self._tenant_for_batch(connection, batch_id)
        owner_id = str(row["target_owner_id"])
        await self._check_owner(connection, tenant_id, owner_id, source_id, issues)
        counts = _source_record_counts(source)
        mapping_rows = await self._mapping_rows(connection, batch_id, row)
        message_ids = {
            int(item["target_int"])
            for item in mapping_rows
            if item["domain"] == "messages" and item["target_int"] is not None
        }
        session_ids = {
            str(item["target_key"])
            for item in mapping_rows
            if item["domain"] == "sessions" and item["target_key"]
        }
        turn_ids = {
            str(item["target_key"])
            for item in mapping_rows
            if item["domain"] == "turns" and item["target_key"]
        }
        target_counts: dict[str, int] = {}
        target_payload: dict[str, Any] = {}
        sessions = await self._sessions(connection, tenant_id, owner_id, session_ids)
        target_counts["sessions"] = len(sessions)
        target_payload["sessions"] = sessions
        messages = await self._messages(connection, tenant_id, owner_id, message_ids)
        target_counts["messages"] = len(messages)
        target_payload["messages"] = messages
        self._verify_message_refs(source_id, session_ids, message_ids, messages, issues)
        turns = await self._turns(connection, tenant_id, owner_id, turn_ids)
        target_counts["turns"] = len(turns)
        target_payload["turns"] = turns
        self._verify_turn_refs(source_id, session_ids, message_ids, turns, issues)
        events = await self._turn_events(connection, tenant_id, owner_id, turn_ids)
        target_counts["turn_events"] = len(events)
        target_payload["turn_events"] = events
        self._verify_turn_event_refs(source_id, session_ids, message_ids, turn_ids, events, issues)
        file_refs = [item for item in mapping_rows if item["domain"] == "knowledge_base_file_refs"]
        target_counts["knowledge_base_file_refs"] = len(file_refs)
        source_file_count = int((source.get("pocketbase") or {}).get("file_count") or 0)
        domain_counts = {
            "sessions": {"source": counts.get("sessions", 0), "target": target_counts["sessions"]},
            "messages": {"source": counts.get("messages", 0), "target": target_counts["messages"]},
            "turns": {"source": counts.get("turns", 0), "target": target_counts["turns"]},
            "turn_events": {
                "source": counts.get("turn_events", 0),
                "target": target_counts["turn_events"],
            },
            "knowledge_base_file_refs": {
                "source": source_file_count,
                "target": target_counts["knowledge_base_file_refs"],
            },
        }
        self._compare_counts(issues, source_id, domain_counts)
        return self._source_report(row, "pocketbase/v1", domain_counts, target_payload)

    async def _verify_chat_history(
        self,
        connection,
        batch_id: str,
        row: dict[str, Any],
        source: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_id = str(row["source_id"])
        tenant_id = await self._tenant_for_batch(connection, batch_id)
        owner_id = str(row["target_owner_id"])
        await self._check_owner(connection, tenant_id, owner_id, source_id, issues)
        rows = _read_chat_rows(_source_path(source))
        mapping_rows = await self._mapping_rows(connection, batch_id, row)
        session_map = _mapping_map(mapping_rows, "sessions", target="key")
        message_map = _mapping_map(mapping_rows, "messages", target="int")
        turn_map = _mapping_map(mapping_rows, "turns", target="key")
        entry_map = _mapping_map(mapping_rows, "notebook_entries", target="int")
        category_map = _mapping_map(mapping_rows, "notebook_categories", target="int")
        session_ids = {str(value) for value in session_map.values()}
        message_ids = {int(value) for value in message_map.values()}
        turn_ids = {str(value) for value in turn_map.values()}
        entry_ids = {int(value) for value in entry_map.values()}
        category_ids = {int(value) for value in category_map.values()}

        target_payload: dict[str, Any] = {}
        sessions = await self._sessions(connection, tenant_id, owner_id, session_ids)
        messages = await self._messages(connection, tenant_id, owner_id, message_ids)
        turns = await self._turns(connection, tenant_id, owner_id, turn_ids)
        events = await self._turn_events(connection, tenant_id, owner_id, turn_ids)
        entries = await self._notebook_entries(connection, tenant_id, owner_id, entry_ids)
        categories = await self._notebook_categories(connection, tenant_id, owner_id, category_ids)
        entry_categories = await self._notebook_entry_categories(
            connection, tenant_id, owner_id, entry_ids, category_ids
        )
        target_payload.update(
            {
                "sessions": sessions,
                "messages": messages,
                "turns": turns,
                "turn_events": events,
                "notebook_entries": entries,
                "notebook_categories": categories,
                "notebook_entry_categories": entry_categories,
            }
        )
        self._verify_expected_mappings(
            issues,
            source_id,
            {
                "sessions": (rows["sessions"], session_map),
                "messages": (rows["messages"], message_map),
                "turns": (rows["turns"], turn_map),
                "notebook_entries": (rows["notebook_entries"], entry_map),
                "notebook_categories": (rows["notebook_categories"], category_map),
            },
        )
        self._verify_message_refs(source_id, session_ids, message_ids, messages, issues)
        self._verify_turn_refs(source_id, session_ids, message_ids, turns, issues)
        self._verify_turn_event_refs(source_id, session_ids, message_ids, turn_ids, events, issues)
        for entry in entries:
            if str(entry["session_id"]) not in session_ids:
                _issue(
                    issues,
                    "notebook_session_missing",
                    "notebook entry points to unmapped session",
                    source_id=source_id,
                    domain="notebook_entries",
                    detail={"entry_id": entry["id"], "session_id": entry["session_id"]},
                )
            if entry.get("turn_id") and str(entry["turn_id"]) not in turn_ids:
                _issue(
                    issues,
                    "notebook_turn_missing",
                    "notebook entry points to unmapped turn",
                    source_id=source_id,
                    domain="notebook_entries",
                    detail={"entry_id": entry["id"], "turn_id": entry["turn_id"]},
                )
        domain_counts = {
            "sessions": {"source": len(rows["sessions"]), "target": len(sessions)},
            "messages": {"source": len(rows["messages"]), "target": len(messages)},
            "turns": {"source": len(rows["turns"]), "target": len(turns)},
            "turn_events": {"source": len(rows["turn_events"]), "target": len(events)},
            "notebook_entries": {
                "source": len(rows["notebook_entries"]),
                "target": len(entries),
            },
            "notebook_categories": {
                "source": len(rows["notebook_categories"]),
                "target": len(categories),
            },
            "notebook_entry_categories": {
                "source": len(rows["notebook_entry_categories"]),
                "target": len(entry_categories),
            },
        }
        self._compare_counts(issues, source_id, domain_counts)
        return self._source_report(row, "chat_history_sqlite/v1", domain_counts, target_payload)

    async def _verify_mastery(
        self,
        connection,
        batch_id: str,
        row: dict[str, Any],
        source: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_id = str(row["source_id"])
        version = str(row["source_version"])
        tenant_id = await self._tenant_for_batch(connection, batch_id)
        owner_id = str(row["target_owner_id"])
        await self._check_owner(connection, tenant_id, owner_id, source_id, issues)
        rows = _read_mastery_rows(_source_path(source))
        mapping_rows = await self._mapping_rows(connection, batch_id, row)
        path_map = _mapping_map(mapping_rows, "mastery_paths", target="key")
        interaction_map = _mapping_map(mapping_rows, "mastery_interactions", target="key")
        path_ids = {str(value) for value in path_map.values()}
        interaction_ids = {str(value) for value in interaction_map.values()}
        target_payload: dict[str, Any] = {}
        paths = await self._fetch_by_text_ids(
            connection,
            """
            SELECT path_id,state,revision,creator_session_id,creator_assigned
              FROM enterprise.mastery_paths
             WHERE tenant_id=%s AND owner_id=%s AND path_id = ANY(%s)
             ORDER BY path_id
            """,
            tenant_id,
            owner_id,
            path_ids,
        )
        interactions = await self._fetch_by_text_ids(
            connection,
            """
            SELECT path_id,interaction_id,status,session_id,turn_id,result
              FROM enterprise.mastery_interactions
             WHERE tenant_id=%s AND owner_id=%s AND interaction_id = ANY(%s)
             ORDER BY interaction_id
            """,
            tenant_id,
            owner_id,
            interaction_ids,
        )
        path_sessions = await self._fetch_by_text_ids(
            connection,
            """
            SELECT path_id,session_id
              FROM enterprise.mastery_path_sessions
             WHERE tenant_id=%s AND owner_id=%s AND path_id = ANY(%s)
             ORDER BY path_id,session_id
            """,
            tenant_id,
            owner_id,
            path_ids,
        )
        events = await self._fetch_by_text_ids(
            connection,
            """
            SELECT path_id,revision,event_type,session_id,turn_id,payload
              FROM enterprise.mastery_events
             WHERE tenant_id=%s AND owner_id=%s AND path_id = ANY(%s)
             ORDER BY path_id,revision,id
            """,
            tenant_id,
            owner_id,
            path_ids,
        )
        topic_meta = await self._fetch_by_text_ids(
            connection,
            """
            SELECT path_id,goal,description,emoji,map_seed,status
              FROM enterprise.mastery_topic_meta
             WHERE tenant_id=%s AND owner_id=%s AND path_id = ANY(%s)
             ORDER BY path_id
            """,
            tenant_id,
            owner_id,
            path_ids,
        )
        topic_sources = await self._fetch_by_text_ids(
            connection,
            """
            SELECT path_id,id,kind,external_id,position,available
              FROM enterprise.mastery_topic_sources
             WHERE tenant_id=%s AND owner_id=%s AND path_id = ANY(%s)
             ORDER BY path_id,position,id
            """,
            tenant_id,
            owner_id,
            path_ids,
        )
        target_payload.update(
            {
                "mastery_paths": paths,
                "mastery_path_sessions": path_sessions,
                "mastery_interactions": interactions,
                "mastery_events": events,
                "mastery_topic_meta": topic_meta,
                "mastery_topic_sources": topic_sources,
            }
        )
        self._verify_expected_mappings(
            issues,
            source_id,
            {
                "mastery_paths": (rows["mastery_paths"], path_map),
                "mastery_interactions": (rows["mastery_interactions"], interaction_map),
            },
            source_key_field={
                "mastery_paths": "path_id",
                "mastery_interactions": "interaction_id",
            },
        )
        await self._verify_mastery_source_refs(
            connection,
            tenant_id,
            owner_id,
            source_id,
            str(row["source_owner_id"]),
            rows,
            path_map,
            issues,
        )
        domain_counts = {
            "mastery_paths": {"source": len(rows["mastery_paths"]), "target": len(paths)},
            "mastery_path_sessions": {
                "source": len(rows["mastery_path_sessions"]),
                "target": len(path_sessions),
            },
            "mastery_interactions": {
                "source": len(rows["mastery_interactions"]),
                "target": len(interactions),
            },
            "mastery_events": {"source": len(rows["mastery_events"]), "target": len(events)},
            "mastery_topic_meta": {
                "source": len(rows["mastery_topic_meta"]) or len(rows["mastery_paths"]),
                "target": len(topic_meta),
            },
            "mastery_topic_sources": {
                "source": len(rows["mastery_topic_sources"]),
                "target": len(topic_sources),
            },
        }
        if version == "mastery_sqlite/v1":
            domain_counts["mastery_topic_sources"] = {"source": 0, "target": len(topic_sources)}
        self._compare_counts(issues, source_id, domain_counts)
        return self._source_report(row, version, domain_counts, target_payload)

    async def _verify_reading(
        self,
        connection,
        batch_id: str,
        row: dict[str, Any],
        source: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_id = str(row["source_id"])
        tenant_id = await self._tenant_for_batch(connection, batch_id)
        owner_id = str(row["target_owner_id"])
        await self._check_owner(connection, tenant_id, owner_id, source_id, issues)
        rows = _read_reading_rows(_source_path(source))
        mapping_rows = await self._mapping_rows(connection, batch_id, row)
        material_map = _mapping_map(mapping_rows, "reading_materials", target="key")
        workspace_map = _mapping_map(mapping_rows, "reading_workspaces", target="key")
        material_ids = {str(value) for value in material_map.values()}
        workspace_ids = {str(value) for value in workspace_map.values()}
        target_payload: dict[str, Any] = {}
        materials = await self._fetch_by_text_ids(
            connection,
            """
            SELECT material_id,content_id,filename,title,status,progress
              FROM enterprise.reading_materials
             WHERE tenant_id=%s AND owner_id=%s AND material_id = ANY(%s)
             ORDER BY material_id
            """,
            tenant_id,
            owner_id,
            material_ids,
        )
        workspaces = await self._fetch_by_text_ids(
            connection,
            """
            SELECT workspace_id,title,active_material_id,version
              FROM enterprise.reading_workspaces
             WHERE tenant_id=%s AND owner_id=%s AND workspace_id = ANY(%s)
             ORDER BY workspace_id
            """,
            tenant_id,
            owner_id,
            workspace_ids,
        )
        workspace_materials = await self._fetch_by_text_ids(
            connection,
            """
            SELECT workspace_id,material_id,tab_order,pinned,opened
              FROM enterprise.reading_workspace_materials
             WHERE tenant_id=%s AND owner_id=%s AND workspace_id = ANY(%s)
             ORDER BY workspace_id,tab_order,material_id
            """,
            tenant_id,
            owner_id,
            workspace_ids,
        )
        workspace_sessions = await self._fetch_by_text_ids(
            connection,
            """
            SELECT workspace_id,session_id,title,active_material_id,version
              FROM enterprise.reading_workspace_sessions
             WHERE tenant_id=%s AND owner_id=%s AND workspace_id = ANY(%s)
             ORDER BY workspace_id,session_id
            """,
            tenant_id,
            owner_id,
            workspace_ids,
        )
        links = await self._fetch_by_text_ids(
            connection,
            """
            SELECT workspace_id,source_session_id,target_session_id
              FROM enterprise.reading_session_links
             WHERE tenant_id=%s AND owner_id=%s AND workspace_id = ANY(%s)
             ORDER BY workspace_id,source_session_id,target_session_id
            """,
            tenant_id,
            owner_id,
            workspace_ids,
        )
        target_payload.update(
            {
                "reading_materials": materials,
                "reading_workspaces": workspaces,
                "reading_workspace_materials": workspace_materials,
                "reading_sessions": workspace_sessions,
                "reading_links": links,
            }
        )
        self._verify_expected_mappings(
            issues,
            source_id,
            {
                "reading_materials": (rows["reading_materials"], material_map),
                "reading_workspaces": (rows["reading_workspaces"], workspace_map),
            },
            source_key_field={
                "reading_materials": "material_id",
                "reading_workspaces": "workspace_id",
            },
        )
        workspace_material_pairs = {
            (str(item["workspace_id"]), str(item["material_id"])) for item in workspace_materials
        }
        for source_row in rows["reading_workspace_materials"]:
            expected = (
                str(workspace_map.get(str(source_row["workspace_id"]) or "")),
                str(material_map.get(str(source_row["material_id"]) or "")),
            )
            if expected not in workspace_material_pairs:
                _issue(
                    issues,
                    "reading_workspace_material_missing",
                    "reading workspace material link is missing",
                    source_id=source_id,
                    domain="reading_workspace_materials",
                    detail={"expected": list(expected)},
                )
        await self._verify_reading_source_refs(
            connection,
            tenant_id,
            owner_id,
            source_id,
            str(row["source_owner_id"]),
            rows,
            workspace_map,
            material_map,
            workspace_sessions,
            links,
            issues,
        )
        domain_counts = {
            "reading_materials": {"source": len(rows["reading_materials"]), "target": len(materials)},
            "reading_workspaces": {"source": len(rows["reading_workspaces"]), "target": len(workspaces)},
            "reading_workspace_materials": {
                "source": len(rows["reading_workspace_materials"]),
                "target": len(workspace_materials),
            },
            "reading_sessions": {
                "source": len(rows["reading_workspace_sessions"]),
                "target": len(workspace_sessions),
            },
            "reading_links": {"source": len(rows["reading_session_links"]), "target": len(links)},
        }
        self._compare_counts(issues, source_id, domain_counts)
        return self._source_report(row, "reading_catalog_sqlite/v1", domain_counts, target_payload)

    async def _verify_cron(
        self,
        connection,
        batch_id: str,
        row: dict[str, Any],
        source: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_id = str(row["source_id"])
        tenant_id = await self._tenant_for_batch(connection, batch_id)
        owner_id = str(row["target_owner_id"])
        await self._check_owner(connection, tenant_id, owner_id, source_id, issues)
        source_jobs = self._read_cron_jobs(source)
        target_jobs = await self._fetch_by_text_ids(
            connection,
            """
            SELECT job_id,schedule_kind,at_ms,every_seconds,cron_expr,tz,
                   enabled,delete_after_run,next_run_at_ms,last_status,payload
              FROM enterprise.cron_jobs
             WHERE tenant_id=%s AND owner_id=%s AND job_id = ANY(%s)
             ORDER BY job_id
            """,
            tenant_id,
            owner_id,
            set(source_jobs),
        )
        by_id = {str(job["job_id"]): job for job in target_jobs}
        for job_id, payload in source_jobs.items():
            target = by_id.get(job_id)
            if target is None:
                _issue(
                    issues,
                    "cron_job_missing",
                    "cron job is missing in target",
                    source_id=source_id,
                    domain="cron_jobs",
                    detail={"job_id": job_id},
                )
                continue
            expected_schedule = payload.get("schedule") if isinstance(payload.get("schedule"), dict) else {}
            expected_tz = str(expected_schedule.get("tz") or "")
            if str(target.get("tz") or "") != expected_tz:
                _issue(
                    issues,
                    "cron_timezone_mismatch",
                    "cron timezone differs from source payload",
                    source_id=source_id,
                    domain="cron_jobs",
                    detail={"job_id": job_id, "expected": expected_tz, "actual": target.get("tz")},
                )
            if str(target.get("schedule_kind") or "") != str(expected_schedule.get("kind") or ""):
                _issue(
                    issues,
                    "cron_schedule_mismatch",
                    "cron schedule kind differs from source payload",
                    source_id=source_id,
                    domain="cron_jobs",
                    detail={"job_id": job_id},
                )
            owner = target.get("payload", {}).get("owner") if isinstance(target.get("payload"), dict) else {}
            if isinstance(owner, dict) and owner.get("user_id") != owner_id:
                _issue(
                    issues,
                    "cron_owner_mismatch",
                    "cron owner user_id was not rewritten to target owner",
                    source_id=source_id,
                    domain="cron_jobs",
                    detail={"job_id": job_id, "actual": owner.get("user_id")},
                )
        expected_uncertain = [job_id for job_id, payload in source_jobs.items() if _cron_was_in_flight(payload)]
        uncertain_rows = await self._fetch_by_text_ids(
            connection,
            """
            SELECT job_id,execution_id,status,worker_id
              FROM enterprise.cron_executions
             WHERE tenant_id=%s AND owner_id=%s
               AND job_id = ANY(%s) AND status='uncertain'
             ORDER BY job_id,execution_id
            """,
            tenant_id,
            owner_id,
            set(expected_uncertain),
        )
        domain_counts = {
            "cron_jobs": {"source": len(source_jobs), "target": len(target_jobs)},
            "cron_uncertain_executions": {
                "source": len(expected_uncertain),
                "target": len(uncertain_rows),
            },
        }
        self._compare_counts(issues, source_id, domain_counts)
        target_payload = {"cron_jobs": target_jobs, "cron_uncertain_executions": uncertain_rows}
        return self._source_report(row, "cron_sqlite/v1", domain_counts, target_payload)

    async def _verify_partner_status(
        self,
        connection,
        batch_id: str,
        row: dict[str, Any],
        source: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_id = str(row["source_id"])
        tenant_id = await self._tenant_for_batch(connection, batch_id)
        owner_id = str(row["target_owner_id"])
        await self._check_owner(connection, tenant_id, owner_id, source_id, issues)
        rows = _read_partner_rows(_source_path(source))["partner_runtime_status"]
        partner_ids = {str(item["partner_id"]) for item in rows}
        target_rows = await self._fetch_by_text_ids(
            connection,
            """
            SELECT partner_id,worker_id,version,running,state,payload,updated_at_ms,expires_at_ms,ttl_ms
              FROM enterprise.partner_runtime_status
             WHERE tenant_id=%s AND owner_id=%s AND partner_id = ANY(%s)
             ORDER BY partner_id
            """,
            tenant_id,
            owner_id,
            partner_ids,
        )
        by_partner = {str(item["partner_id"]): item for item in target_rows}
        for source_row in rows:
            partner_id = str(source_row["partner_id"])
            target = by_partner.get(partner_id)
            if target is None:
                _issue(
                    issues,
                    "partner_status_missing",
                    "partner runtime status row is missing in target",
                    source_id=source_id,
                    domain="partner_status",
                    detail={"partner_id": partner_id},
                )
                continue
            payload = target.get("payload") if isinstance(target.get("payload"), dict) else {}
            if "channels" in payload:
                _issue(
                    issues,
                    "partner_secret_payload_leaked",
                    "partner runtime payload retained channel Secret data",
                    source_id=source_id,
                    domain="partner_status",
                    detail={"partner_id": partner_id},
                )
        domain_counts = {"partner_status": {"source": len(rows), "target": len(target_rows)}}
        self._compare_counts(issues, source_id, domain_counts)
        return self._source_report(
            row,
            "partner_runtime_status_sqlite/v1",
            domain_counts,
            {"partner_status": target_rows},
        )

    async def _verify_marginnote(
        self,
        connection,
        batch_id: str,
        row: dict[str, Any],
        source: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_id = str(row["source_id"])
        tenant_id = await self._tenant_for_batch(connection, batch_id)
        owner_id = str(row["target_owner_id"])
        await self._check_owner(connection, tenant_id, owner_id, source_id, issues)
        kb_id = _source_kb_id(source)
        if not kb_id:
            _issue(
                issues,
                "marginnote_kb_mapping_missing",
                "MarginNote source has no target kb_id mapping",
                source_id=source_id,
                domain="marginnote_devices",
            )
        rows = _read_marginnote_rows(_source_path(source))
        device_ids = {str(item["device_id"]) for item in rows["mn4_devices"]}
        object_pairs = {(str(item["device_id"]), str(item["object_id"])) for item in rows["mn4_objects"]}
        tombstone_pairs = {
            (str(item["device_id"]), str(item["object_id"])) for item in rows["mn4_tombstones"]
        }
        devices = await self._fetch_by_text_ids(
            connection,
            """
            SELECT device_id,device_name,device_kind,token_hash,active,last_seen
              FROM enterprise.marginnote_devices
             WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s AND device_id = ANY(%s)
             ORDER BY device_id
            """,
            tenant_id,
            owner_id,
            device_ids,
            extra=(kb_id,),
        )
        cursors = await self._fetch_by_text_ids(
            connection,
            """
            SELECT device_id,cursor,updated_at
              FROM enterprise.marginnote_cursors
             WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s AND device_id = ANY(%s)
             ORDER BY device_id
            """,
            tenant_id,
            owner_id,
            {str(item["device_id"]) for item in rows["mn4_cursors"]},
            extra=(kb_id,),
        )
        objects = await self._fetch_margin_objects(
            connection, tenant_id, owner_id, kb_id, object_pairs
        )
        tombstones = await self._fetch_margin_tombstones(
            connection, tenant_id, owner_id, kb_id, tombstone_pairs
        )
        target_devices = {str(item["device_id"]) for item in devices}
        for source_row in rows["mn4_devices"]:
            if str(source_row["device_id"]) not in target_devices:
                _issue(
                    issues,
                    "marginnote_device_missing",
                    "MarginNote device is missing in target",
                    source_id=source_id,
                    domain="marginnote_devices",
                    detail={"device_id": source_row["device_id"]},
                )
        for device_id, _object_id in object_pairs | tombstone_pairs:
            if device_id not in target_devices:
                _issue(
                    issues,
                    "marginnote_object_device_missing",
                    "MarginNote object/tombstone points to missing target device",
                    source_id=source_id,
                    domain="marginnote_objects",
                    detail={"device_id": device_id},
                )
        domain_counts = {
            "marginnote_devices": {"source": len(rows["mn4_devices"]), "target": len(devices)},
            "marginnote_cursors": {"source": len(rows["mn4_cursors"]), "target": len(cursors)},
            "marginnote_objects": {"source": len(rows["mn4_objects"]), "target": len(objects)},
            "marginnote_tombstones": {
                "source": len(rows["mn4_tombstones"]),
                "target": len(tombstones),
            },
        }
        self._compare_counts(issues, source_id, domain_counts)
        target_payload = {
            "marginnote_devices": devices,
            "marginnote_cursors": cursors,
            "marginnote_objects": objects,
            "marginnote_tombstones": tombstones,
        }
        return self._source_report(row, "marginnote_sqlite/v1", domain_counts, target_payload)

    async def _verify_matrix(
        self,
        connection,
        batch_id: str,
        row: dict[str, Any],
        source: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_id = str(row["source_id"])
        tenant_id = await self._tenant_for_batch(connection, batch_id)
        owner_id = str(row["target_owner_id"])
        await self._check_owner(connection, tenant_id, owner_id, source_id, issues)
        cfg = source.get("matrix") if isinstance(source.get("matrix"), dict) else {}
        rows = _read_matrix_rows(_source_path(source))
        account_rows = [
            item
            for item in rows["accounts"]
            if str(item.get("user_id")) == str(cfg.get("user_id") or "")
            and str(item.get("device_id")) == str(cfg.get("device_id") or "")
        ]
        source_account_id = str(account_rows[0]["id"]) if len(account_rows) == 1 else ""
        if len(account_rows) != 1:
            _issue(
                issues,
                "matrix_source_account_invalid",
                "Matrix source must contain exactly one configured account",
                source_id=source_id,
                domain="matrix_accounts",
                detail={"matches": len(account_rows)},
            )
        values = (
            tenant_id,
            owner_id,
            str(cfg.get("partner_id") or ""),
            str(cfg.get("user_id") or ""),
            str(cfg.get("device_id") or ""),
        )
        account = await (
            await connection.execute(
                """
                SELECT secret_id, secret_version, shared
                  FROM enterprise.matrix_accounts
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                """,
                values,
            )
        ).fetchone()
        if account is None:
            _issue(
                issues,
                "matrix_account_missing",
                "Matrix account is missing",
                source_id=source_id,
                domain="matrix_accounts",
            )
            account_payload: list[dict[str, Any]] = []
        else:
            account_payload = [dict(account)]
            if str(account["secret_id"]) != str(cfg.get("secret_id") or "") or int(
                account["secret_version"]
            ) != int(cfg.get("secret_version") or 0):
                _issue(
                    issues,
                    "matrix_secret_mismatch",
                    "Matrix account Secret metadata differs from manifest",
                    source_id=source_id,
                    domain="matrix_accounts",
                    detail={
                        "expected_secret_id": cfg.get("secret_id"),
                        "actual_secret_id": account["secret_id"],
                    },
                )
        source_counts = self._matrix_expected_counts(rows, source_account_id)
        target_counts, target_payload = await self._matrix_target_counts(connection, values)
        target_payload["matrix_accounts"] = account_payload
        domain_counts = {
            domain: {"source": source_counts.get(domain, 0), "target": target_counts.get(domain, 0)}
            for domain in sorted(set(source_counts) | set(target_counts))
        }
        self._compare_counts(issues, source_id, domain_counts)
        return self._source_report(row, "matrix_nio_sqlite/v0.26", domain_counts, target_payload)

    def _source_report(
        self,
        row: dict[str, Any],
        version: str,
        domain_counts: dict[str, dict[str, int]],
        target_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "source_id": row["source_id"],
            "source_version": version,
            "source_owner_id": row["source_owner_id"],
            "target_owner_id": row["target_owner_id"],
            "domain_counts": domain_counts,
            "content_digest": _digest(target_payload),
        }

    @staticmethod
    def _compare_counts(
        issues: list[dict[str, Any]], source_id: str, domain_counts: dict[str, dict[str, int]]
    ) -> None:
        for domain, counts in domain_counts.items():
            if int(counts.get("source") or 0) != int(counts.get("target") or 0):
                _issue(
                    issues,
                    "domain_count_mismatch",
                    "source and target counts differ",
                    source_id=source_id,
                    domain=domain,
                    detail=counts,
                )

    @staticmethod
    def _verify_expected_mappings(
        issues: list[dict[str, Any]],
        source_id: str,
        expected: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]],
        *,
        source_key_field: dict[str, str] | None = None,
    ) -> None:
        source_key_field = source_key_field or {}
        default_key = {
            "sessions": "id",
            "messages": "id",
            "turns": "id",
            "notebook_entries": "id",
            "notebook_categories": "id",
        }
        for domain, (source_rows, mapping) in expected.items():
            key_field = source_key_field.get(domain) or default_key.get(domain) or "id"
            source_keys = {str(item[key_field]) for item in source_rows}
            missing = sorted(source_keys - set(mapping))
            if missing:
                _issue(
                    issues,
                    "id_mapping_missing",
                    "source row has no target ID mapping",
                    source_id=source_id,
                    domain=domain,
                    detail={"source_keys": missing[:20], "missing": len(missing)},
                )

    @staticmethod
    def _verify_message_refs(
        source_id: str,
        session_ids: set[str],
        message_ids: set[int],
        messages: list[dict[str, Any]],
        issues: list[dict[str, Any]],
    ) -> None:
        for message in messages:
            if str(message["session_id"]) not in session_ids:
                _issue(
                    issues,
                    "message_session_missing",
                    "message points to an unmapped session",
                    source_id=source_id,
                    domain="messages",
                    detail={"message_id": message["id"], "session_id": message["session_id"]},
                )
            parent = message.get("parent_message_id")
            if parent is not None and int(parent) not in message_ids:
                _issue(
                    issues,
                    "message_parent_missing",
                    "message parent points to a missing mapped message",
                    source_id=source_id,
                    domain="messages",
                    detail={"message_id": message["id"], "parent_message_id": parent},
                )
            for ref in _nested_message_refs(message.get("metadata") or {}):
                if ref is not None and int(ref) not in message_ids:
                    _issue(
                        issues,
                        "message_reference_missing",
                        "message metadata points to a missing mapped message",
                        source_id=source_id,
                        domain="messages",
                        detail={"message_id": message["id"], "ref": ref},
                    )

    @staticmethod
    def _verify_turn_refs(
        source_id: str,
        session_ids: set[str],
        message_ids: set[int],
        turns: list[dict[str, Any]],
        issues: list[dict[str, Any]],
    ) -> None:
        for turn in turns:
            if str(turn["session_id"]) not in session_ids:
                _issue(
                    issues,
                    "turn_session_missing",
                    "turn points to unmapped session",
                    source_id=source_id,
                    domain="turns",
                    detail={"turn_id": turn["id"], "session_id": turn["session_id"]},
                )
            for key in ("assistant_message_id", "user_message_id"):
                ref = turn.get(key)
                if ref is not None and int(ref) not in message_ids:
                    _issue(
                        issues,
                        "turn_message_reference_missing",
                        "turn message reference is not mapped",
                        source_id=source_id,
                        domain="turns",
                        detail={"turn_id": turn["id"], "field": key, "ref": ref},
                    )

    @staticmethod
    def _verify_turn_event_refs(
        source_id: str,
        session_ids: set[str],
        message_ids: set[int],
        turn_ids: set[str],
        events: list[dict[str, Any]],
        issues: list[dict[str, Any]],
    ) -> None:
        for event in events:
            if str(event["turn_id"]) not in turn_ids:
                _issue(
                    issues,
                    "event_turn_missing",
                    "event points to unmapped turn",
                    source_id=source_id,
                    domain="turn_events",
                )
            if str(event["session_id"]) not in session_ids:
                _issue(
                    issues,
                    "event_session_missing",
                    "event points to unmapped session",
                    source_id=source_id,
                    domain="turn_events",
                )
            metadata = (event.get("event") or {}).get("metadata") or {}
            for ref in _nested_message_refs(metadata):
                if ref is not None and int(ref) not in message_ids:
                    _issue(
                        issues,
                        "message_reference_missing",
                        "turn event metadata points to a missing mapped message",
                        source_id=source_id,
                        domain="turn_events",
                        detail={"turn_id": event["turn_id"], "seq": event["seq"], "ref": ref},
                    )

    async def _verify_mastery_source_refs(
        self,
        connection,
        tenant_id: str,
        owner_id: str,
        source_id: str,
        source_owner: str,
        rows: dict[str, list[dict[str, Any]]],
        path_map: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> None:
        path_ids = {str(value) for value in path_map.values()}
        for table in ("mastery_path_sessions", "mastery_interactions", "mastery_events"):
            for source_row in rows[table]:
                if str(path_map.get(str(source_row.get("path_id") or "")) or "") not in path_ids:
                    _issue(
                        issues,
                        "mastery_path_reference_missing",
                        "mastery row points to an unmapped path",
                        source_id=source_id,
                        domain=table,
                    )
                raw_session = str(source_row.get("session_id") or "")
                if raw_session:
                    mapped = await self._resolve_text_reference(
                        connection,
                        tenant_id,
                        owner_id,
                        source_owner,
                        "sessions",
                        raw_session,
                        table="enterprise.sessions",
                        key_column="id",
                    )
                    if not mapped:
                        _issue(
                            issues,
                            "mastery_session_reference_missing",
                            "mastery row points to a missing target session",
                            source_id=source_id,
                            domain=table,
                            detail={"session_id": raw_session},
                        )
                raw_turn = str(source_row.get("turn_id") or "")
                if raw_turn:
                    mapped = await self._resolve_text_reference(
                        connection,
                        tenant_id,
                        owner_id,
                        source_owner,
                        "turns",
                        raw_turn,
                        table="enterprise.turns",
                        key_column="id",
                    )
                    if not mapped:
                        _issue(
                            issues,
                            "mastery_turn_reference_missing",
                            "mastery row points to a missing target turn",
                            source_id=source_id,
                            domain=table,
                            detail={"turn_id": raw_turn},
                        )
        for source_row in rows["mastery_topic_sources"]:
            kind = str(source_row.get("kind") or "")
            raw = str(source_row.get("external_id") or "")
            if kind == "chat" and raw and not raw.startswith("partner:"):
                mapped = await self._resolve_text_reference(
                    connection,
                    tenant_id,
                    owner_id,
                    source_owner,
                    "sessions",
                    raw,
                    table="enterprise.sessions",
                    key_column="id",
                )
                if not mapped:
                    _issue(
                        issues,
                        "mastery_topic_chat_reference_missing",
                        "mastery topic source points to a missing chat session",
                        source_id=source_id,
                        domain="mastery_topic_sources",
                        detail={"external_id": raw},
                    )
            if kind == "question_bank" and raw:
                mapped_int = await self._resolve_int_reference(
                    connection,
                    tenant_id,
                    owner_id,
                    source_owner,
                    "notebook_entries",
                    raw,
                    table="enterprise.notebook_entries",
                    key_column="id",
                )
                if mapped_int is None:
                    _issue(
                        issues,
                        "mastery_topic_question_reference_missing",
                        "mastery topic source points to a missing question bank entry",
                        source_id=source_id,
                        domain="mastery_topic_sources",
                        detail={"external_id": raw},
                    )

    async def _verify_reading_source_refs(
        self,
        connection,
        tenant_id: str,
        owner_id: str,
        source_id: str,
        source_owner: str,
        rows: dict[str, list[dict[str, Any]]],
        workspace_map: dict[str, Any],
        material_map: dict[str, Any],
        workspace_sessions: list[dict[str, Any]],
        links: list[dict[str, Any]],
        issues: list[dict[str, Any]],
    ) -> None:
        workspace_session_pairs = {
            (str(item["workspace_id"]), str(item["session_id"])) for item in workspace_sessions
        }
        link_pairs = {
            (str(item["workspace_id"]), str(item["source_session_id"]), str(item["target_session_id"]))
            for item in links
        }
        for source_row in rows["reading_workspaces"]:
            active = str(source_row.get("active_material_id") or "")
            if active and active not in material_map:
                _issue(
                    issues,
                    "reading_active_material_missing",
                    "reading workspace active material has no target mapping",
                    source_id=source_id,
                    domain="reading_workspaces",
                    detail={"material_id": active},
                )
        for source_row in rows["reading_workspace_sessions"]:
            workspace_id = str(workspace_map.get(str(source_row["workspace_id"])) or "")
            target_session = await self._resolve_text_reference(
                connection,
                tenant_id,
                owner_id,
                source_owner,
                "sessions",
                source_row["session_id"],
                table="enterprise.sessions",
                key_column="id",
            )
            if not target_session or (workspace_id, target_session) not in workspace_session_pairs:
                _issue(
                    issues,
                    "reading_session_reference_missing",
                    "reading workspace session points to a missing target session",
                    source_id=source_id,
                    domain="reading_sessions",
                    detail={"session_id": source_row["session_id"]},
                )
        for source_row in rows["reading_session_links"]:
            workspace_id = str(workspace_map.get(str(source_row["workspace_id"])) or "")
            source_session = await self._resolve_text_reference(
                connection,
                tenant_id,
                owner_id,
                source_owner,
                "sessions",
                source_row["source_session_id"],
                table="enterprise.sessions",
                key_column="id",
            )
            target_session = await self._resolve_text_reference(
                connection,
                tenant_id,
                owner_id,
                source_owner,
                "sessions",
                source_row["target_session_id"],
                table="enterprise.sessions",
                key_column="id",
            )
            if not source_session or not target_session or (
                workspace_id,
                source_session,
                target_session,
            ) not in link_pairs:
                _issue(
                    issues,
                    "reading_link_reference_missing",
                    "reading session link points to missing target sessions",
                    source_id=source_id,
                    domain="reading_links",
                    detail={
                        "source_session_id": source_row["source_session_id"],
                        "target_session_id": source_row["target_session_id"],
                    },
                )

    @staticmethod
    async def _fetch_rows(connection, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        rows = await (await connection.execute(query, params)).fetchall()
        return [dict(row) for row in rows]

    async def _fetch_by_text_ids(
        self,
        connection,
        query: str,
        tenant_id: str,
        owner_id: str,
        ids: set[str],
        *,
        extra: tuple[Any, ...] = (),
    ) -> list[dict[str, Any]]:
        if not ids:
            return []
        params = (tenant_id, owner_id, *extra, sorted(ids))
        return await self._fetch_rows(connection, query, params)

    async def _sessions(
        self, connection, tenant_id: str, owner_id: str, session_ids: set[str]
    ) -> list[dict[str, Any]]:
        return await self._fetch_by_text_ids(
            connection,
            """
            SELECT id,title,summary,summary_up_to_msg_id,preferences
              FROM enterprise.sessions
             WHERE tenant_id=%s AND owner_id=%s AND id = ANY(%s)
             ORDER BY id
            """,
            tenant_id,
            owner_id,
            session_ids,
        )

    async def _messages(
        self, connection, tenant_id: str, owner_id: str, message_ids: set[int]
    ) -> list[dict[str, Any]]:
        if not message_ids:
            return []
        return await self._fetch_rows(
            connection,
            """
            SELECT id,session_id,role,content,attachments,metadata,parent_message_id
              FROM enterprise.messages
             WHERE tenant_id=%s AND owner_id=%s AND id = ANY(%s)
             ORDER BY id
            """,
            (tenant_id, owner_id, sorted(message_ids)),
        )

    async def _turns(
        self, connection, tenant_id: str, owner_id: str, turn_ids: set[str]
    ) -> list[dict[str, Any]]:
        return await self._fetch_by_text_ids(
            connection,
            """
            SELECT id,session_id,assistant_message_id,user_message_id,status
              FROM enterprise.turns
             WHERE tenant_id=%s AND user_id=%s AND id = ANY(%s)
             ORDER BY id
            """,
            tenant_id,
            owner_id,
            turn_ids,
        )

    async def _turn_events(
        self, connection, tenant_id: str, owner_id: str, turn_ids: set[str]
    ) -> list[dict[str, Any]]:
        return await self._fetch_by_text_ids(
            connection,
            """
            SELECT turn_id,session_id,seq,event
              FROM enterprise.turn_events
             WHERE tenant_id=%s AND owner_id=%s AND turn_id = ANY(%s)
             ORDER BY turn_id,seq
            """,
            tenant_id,
            owner_id,
            turn_ids,
        )

    async def _notebook_entries(
        self, connection, tenant_id: str, owner_id: str, entry_ids: set[int]
    ) -> list[dict[str, Any]]:
        if not entry_ids:
            return []
        return await self._fetch_rows(
            connection,
            """
            SELECT id,session_id,turn_id,followup_session_id,question_id,question
              FROM enterprise.notebook_entries
             WHERE tenant_id=%s AND owner_id=%s AND id = ANY(%s)
             ORDER BY id
            """,
            (tenant_id, owner_id, sorted(entry_ids)),
        )

    async def _notebook_categories(
        self, connection, tenant_id: str, owner_id: str, category_ids: set[int]
    ) -> list[dict[str, Any]]:
        if not category_ids:
            return []
        return await self._fetch_rows(
            connection,
            """
            SELECT id,name
              FROM enterprise.notebook_categories
             WHERE tenant_id=%s AND owner_id=%s AND id = ANY(%s)
             ORDER BY id
            """,
            (tenant_id, owner_id, sorted(category_ids)),
        )

    async def _notebook_entry_categories(
        self,
        connection,
        tenant_id: str,
        owner_id: str,
        entry_ids: set[int],
        category_ids: set[int],
    ) -> list[dict[str, Any]]:
        if not entry_ids or not category_ids:
            return []
        return await self._fetch_rows(
            connection,
            """
            SELECT entry_id,category_id
              FROM enterprise.notebook_entry_categories
             WHERE tenant_id=%s AND owner_id=%s
               AND entry_id = ANY(%s) AND category_id = ANY(%s)
             ORDER BY entry_id,category_id
            """,
            (tenant_id, owner_id, sorted(entry_ids), sorted(category_ids)),
        )

    async def _mapping_rows(self, connection, batch_id: str, row: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._fetch_rows(
            connection,
            """
            SELECT domain, source_key, target_key, target_int, metadata
              FROM migration_stage.id_mappings
             WHERE batch_id=%s AND source_id=%s AND source_owner_id=%s
             ORDER BY domain, source_key
            """,
            (batch_id, str(row["source_id"]), str(row["source_owner_id"])),
        )

    async def _resolve_text_reference(
        self,
        connection,
        tenant_id: str,
        owner_id: str,
        source_owner: str,
        domain: str,
        source_key: Any,
        *,
        table: str,
        key_column: str,
    ) -> str | None:
        value = str(source_key or "")
        if not value:
            return None
        rows = await (
            await connection.execute(
                """
                SELECT DISTINCT m.target_key AS target
                  FROM migration_stage.id_mappings m
                  JOIN migration_stage.sources s
                    ON s.batch_id=m.batch_id AND s.source_id=m.source_id
                 WHERE m.domain=%s
                   AND m.source_owner_id=%s
                   AND m.source_key=%s
                   AND s.target_owner_id=%s
                   AND s.status='verified'
                   AND m.target_key IS NOT NULL
                """,
                (domain, source_owner, value, owner_id),
            )
        ).fetchall()
        if len(rows) == 1:
            target = str(rows[0]["target"])
            if await self._target_exists(connection, tenant_id, owner_id, table, key_column, target):
                return target
            return None
        if len(rows) > 1:
            return None
        if await self._target_exists(connection, tenant_id, owner_id, table, key_column, value):
            return value
        return None

    async def _resolve_int_reference(
        self,
        connection,
        tenant_id: str,
        owner_id: str,
        source_owner: str,
        domain: str,
        source_key: Any,
        *,
        table: str,
        key_column: str,
    ) -> int | None:
        value = str(source_key or "")
        if not value:
            return None
        rows = await (
            await connection.execute(
                """
                SELECT DISTINCT m.target_int AS target
                  FROM migration_stage.id_mappings m
                  JOIN migration_stage.sources s
                    ON s.batch_id=m.batch_id AND s.source_id=m.source_id
                 WHERE m.domain=%s
                   AND m.source_owner_id=%s
                   AND m.source_key=%s
                   AND s.target_owner_id=%s
                   AND s.status='verified'
                   AND m.target_int IS NOT NULL
                """,
                (domain, source_owner, value, owner_id),
            )
        ).fetchall()
        if len(rows) == 1:
            target = int(rows[0]["target"])
            if await self._target_exists(connection, tenant_id, owner_id, table, key_column, target):
                return target
            return None
        if len(rows) > 1:
            return None
        if value.isdecimal() and await self._target_exists(
            connection, tenant_id, owner_id, table, key_column, int(value)
        ):
            return int(value)
        return None

    @staticmethod
    async def _target_exists(
        connection,
        tenant_id: str,
        owner_id: str,
        table: str,
        key_column: str,
        value: str | int,
    ) -> bool:
        owner_column = "user_id" if table == "enterprise.turns" else "owner_id"
        row = await (
            await connection.execute(
                f"""
                SELECT 1 FROM {table}
                 WHERE tenant_id=%s AND {owner_column}=%s AND {key_column}=%s
                 LIMIT 1
                """,  # nosec B608 - table/column 来自封闭常量
                (tenant_id, owner_id, value),
            )
        ).fetchone()
        return row is not None

    @staticmethod
    async def _tenant_for_batch(connection, batch_id: str) -> str:
        row = await (
            await connection.execute(
                "SELECT target_tenant_id FROM migration_stage.batches WHERE batch_id=%s",
                (batch_id,),
            )
        ).fetchone()
        return str(row["target_tenant_id"])

    @staticmethod
    async def _check_owner(
        connection,
        tenant_id: str,
        owner_id: str,
        source_id: str,
        issues: list[dict[str, Any]],
    ) -> None:
        row = await (
            await connection.execute(
                """
                SELECT disabled
                  FROM enterprise.users
                 WHERE tenant_id=%s AND id=%s
                """,
                (tenant_id, owner_id),
            )
        ).fetchone()
        if row is None:
            _issue(
                issues,
                "target_owner_missing",
                "target owner does not exist",
                source_id=source_id,
                detail={"target_owner_id": owner_id},
            )
        elif row["disabled"]:
            _issue(
                issues,
                "target_owner_disabled",
                "target owner is disabled",
                source_id=source_id,
                detail={"target_owner_id": owner_id},
            )

    @staticmethod
    def _read_cron_jobs(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
        rows = _read_cron_rows(_source_path(source))["cron_jobs"]
        jobs: dict[str, dict[str, Any]] = {}
        for row in rows:
            jobs[str(row["id"])] = _json_dict(row["payload"])
        return jobs

    async def _fetch_margin_objects(
        self,
        connection,
        tenant_id: str,
        owner_id: str,
        kb_id: str,
        pairs: set[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        if not pairs:
            return []
        rows = await self._fetch_rows(
            connection,
            """
            SELECT device_id,object_id,object_type,title,updated_at,synced_at
              FROM enterprise.marginnote_objects
             WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
             ORDER BY device_id,object_id
            """,
            (tenant_id, owner_id, kb_id),
        )
        return [row for row in rows if (str(row["device_id"]), str(row["object_id"])) in pairs]

    async def _fetch_margin_tombstones(
        self,
        connection,
        tenant_id: str,
        owner_id: str,
        kb_id: str,
        pairs: set[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        if not pairs:
            return []
        rows = await self._fetch_rows(
            connection,
            """
            SELECT device_id,object_id,deleted_at
              FROM enterprise.marginnote_tombstones
             WHERE tenant_id=%s AND owner_id=%s AND kb_id=%s
             ORDER BY device_id,object_id
            """,
            (tenant_id, owner_id, kb_id),
        )
        return [row for row in rows if (str(row["device_id"]), str(row["object_id"])) in pairs]

    @staticmethod
    def _matrix_expected_counts(
        rows: dict[str, list[dict[str, Any]]], source_account_id: str
    ) -> dict[str, int]:
        account_rows = [row for row in rows["accounts"] if str(row.get("id")) == source_account_id]
        account_device_pks = {
            int(row["id"])
            for row in rows["devicekeys"]
            if str(row.get("account_id")) == source_account_id
        }
        megolm_session_ids = {
            str(row["session_id"])
            for row in rows["megolminboundsessions"]
            if str(row.get("account_id")) == source_account_id
        }
        return {
            "matrix_accounts": len(account_rows),
            "matrix_olm_sessions": len(
                [row for row in rows["olmsessions"] if str(row.get("account_id")) == source_account_id]
            ),
            "matrix_megolm_sessions": len(megolm_session_ids),
            "matrix_forwarded_chains": len(
                [row for row in rows["forwardedchains"] if str(row.get("session_id")) in megolm_session_ids]
            ),
            "matrix_device_keys": len(account_device_pks),
            "matrix_device_key_values": len(
                [row for row in rows["keys"] if int(row.get("device_id") or -1) in account_device_pks]
            ),
            "matrix_device_trust_state": len(
                [
                    row
                    for row in rows["devicetruststate"]
                    if int(row.get("device_id") or -1) in account_device_pks
                ]
            ),
            "matrix_encrypted_rooms": len(
                [row for row in rows["encryptedrooms"] if str(row.get("account_id")) == source_account_id]
            ),
            "matrix_sync_tokens": min(
                1,
                len([row for row in rows["synctokens"] if str(row.get("account_id")) == source_account_id]),
            ),
            "matrix_outgoing_key_requests": len(
                [
                    row
                    for row in rows["outgoingkeyrequests"]
                    if str(row.get("account_id")) == source_account_id
                ]
            ),
        }

    async def _matrix_target_counts(
        self, connection, values: tuple[str, str, str, str, str]
    ) -> tuple[dict[str, int], dict[str, Any]]:
        target_counts: dict[str, int] = {}
        target_payload: dict[str, Any] = {}
        table_queries = {
            "matrix_olm_sessions": (
                "enterprise.matrix_olm_sessions",
                "sender_key,session_id",
            ),
            "matrix_megolm_sessions": (
                "enterprise.matrix_megolm_inbound_sessions",
                "room_id,sender_key,session_id",
            ),
            "matrix_forwarded_chains": (
                "enterprise.matrix_forwarded_chains",
                "room_id,sender_key,session_id,position,chain_sender_key",
            ),
            "matrix_device_keys": (
                "enterprise.matrix_device_keys",
                "user_id,key_device_id,deleted",
            ),
            "matrix_device_key_values": (
                "enterprise.matrix_device_key_values",
                "user_id,key_device_id,key_type",
            ),
            "matrix_device_trust_state": (
                "enterprise.matrix_device_trust_state",
                "user_id,key_device_id,state",
            ),
            "matrix_encrypted_rooms": ("enterprise.matrix_encrypted_rooms", "room_id"),
            "matrix_sync_tokens": ("enterprise.matrix_sync_tokens", "token"),
            "matrix_outgoing_key_requests": (
                "enterprise.matrix_outgoing_key_requests",
                "request_id,session_id,room_id,algorithm",
            ),
        }
        for domain, (table, columns) in table_queries.items():
            rows = await self._fetch_rows(
                connection,
                f"""
                SELECT {columns}
                  FROM {table}
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                 ORDER BY 1
                """,  # nosec B608 - table/columns 来自封闭常量
                values,
            )
            target_counts[domain] = len(rows)
            target_payload[domain] = rows
        target_counts["matrix_accounts"] = 1 if await (
            await connection.execute(
                """
                SELECT 1 FROM enterprise.matrix_accounts
                 WHERE tenant_id=%s AND owner_id=%s AND partner_id=%s
                   AND matrix_user_id=%s AND device_id=%s
                """,
                values,
            )
        ).fetchone() else 0
        return target_counts, target_payload


__all__ = ["OfflineImportVerifier", "OfflineVerifyReport"]
