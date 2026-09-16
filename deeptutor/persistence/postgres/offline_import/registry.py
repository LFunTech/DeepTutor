"""版本化导入引用字段注册表。

注册表固定“哪些字段是机器引用、必须由导入器按映射重写/验证”。普通
metadata 或正文不在这里做全文替换；未知源版本由 plan/source-check 拒绝，
避免把未识别的机器引用静默归入“其它 metadata”。
"""

from __future__ import annotations

from dataclasses import dataclass


class UnsupportedSourceVersion(ValueError):
    """导入源版本未登记。"""


@dataclass(frozen=True)
class ReferenceField:
    """一个源字段中机器引用的声明。"""

    path: str
    target: str
    rewrite: str
    required: bool = False


@dataclass(frozen=True)
class ReferenceRegistry:
    """单个离线源格式版本的 schema 与引用声明。"""

    source_version: str
    source_format: str
    required_tables: dict[str, frozenset[str]]
    reference_fields: tuple[ReferenceField, ...]


def _table(columns: list[str]) -> frozenset[str]:
    return frozenset(columns)


_CHAT_HISTORY_V1 = ReferenceRegistry(
    source_version="chat_history_sqlite/v1",
    source_format="chat_history_sqlite",
    required_tables={
        "sessions": _table(
            [
                "id",
                "created_at",
                "updated_at",
                "preferences_json",
                "summary_up_to_msg_id",
            ]
        ),
        "messages": _table(
            [
                "id",
                "session_id",
                "role",
                "content",
                "created_at",
                "parent_message_id",
                "metadata_json",
                "attachments_json",
                "events_json",
            ]
        ),
        "turns": _table(["id", "session_id", "assistant_message_id"]),
        "turn_events": _table(["turn_id", "seq", "metadata_json"]),
        "notebook_entries": _table(
            [
                "id",
                "session_id",
                "turn_id",
                "question_id",
                "user_answer_images_json",
                "followup_session_id",
            ]
        ),
        "notebook_categories": _table(["id", "name"]),
        "notebook_entry_categories": _table(["entry_id", "category_id"]),
    },
    reference_fields=(
        ReferenceField(
            "sessions.summary_up_to_msg_id",
            target="messages.id",
            rewrite="message_id_map",
        ),
        ReferenceField(
            "sessions.preferences_json.import.external_id",
            target="migration_link",
            rewrite="preserve_audit_only",
        ),
        ReferenceField(
            "sessions.preferences_json.reading.workspace_id",
            target="reading_workspaces.workspace_id",
            rewrite="resource_id_map",
        ),
        ReferenceField(
            "sessions.preferences_json.mastery.path_id",
            target="mastery_paths.path_id",
            rewrite="resource_id_map",
        ),
        ReferenceField(
            "messages.session_id",
            target="sessions.id",
            rewrite="session_id_map",
            required=True,
        ),
        ReferenceField(
            "messages.parent_message_id",
            target="messages.id",
            rewrite="message_id_map",
        ),
        ReferenceField(
            "messages.events_json[*].turn_id",
            target="turns.id",
            rewrite="turn_id_map",
        ),
        ReferenceField(
            "messages.events_json[*].metadata.assistant_message_id",
            target="messages.id",
            rewrite="message_id_map",
        ),
        ReferenceField(
            "messages.attachments_json[*].id",
            target="resources.attachment_id",
            rewrite="resource_manifest_map",
        ),
        ReferenceField(
            "messages.metadata_json.source_message_id",
            target="messages.id",
            rewrite="message_id_map",
        ),
        ReferenceField(
            "turns.session_id",
            target="sessions.id",
            rewrite="session_id_map",
            required=True,
        ),
        ReferenceField(
            "turns.assistant_message_id",
            target="messages.id",
            rewrite="message_id_map",
        ),
        ReferenceField(
            "turns.user_message_id",
            target="messages.id",
            rewrite="message_id_map",
        ),
        ReferenceField(
            "turn_events.turn_id",
            target="turns.id",
            rewrite="turn_id_map",
            required=True,
        ),
        ReferenceField(
            "turn_events.metadata_json.message_id",
            target="messages.id",
            rewrite="message_id_map",
        ),
        ReferenceField(
            "turn_events.metadata_json.assistant_message_id",
            target="messages.id",
            rewrite="message_id_map",
        ),
        ReferenceField(
            "notebook_entries.session_id",
            target="sessions.id",
            rewrite="session_id_map",
            required=True,
        ),
        ReferenceField(
            "notebook_entries.turn_id",
            target="turns.id",
            rewrite="turn_id_map",
        ),
        ReferenceField(
            "notebook_entries.followup_session_id",
            target="sessions.id",
            rewrite="session_id_map",
        ),
        ReferenceField(
            "notebook_entries.user_answer_images_json[*].id",
            target="resources.attachment_id",
            rewrite="resource_manifest_map",
        ),
        ReferenceField(
            "notebook_entry_categories.entry_id",
            target="notebook_entries.id",
            rewrite="notebook_entry_id_map",
            required=True,
        ),
        ReferenceField(
            "notebook_entry_categories.category_id",
            target="notebook_categories.id",
            rewrite="notebook_category_id_map",
            required=True,
        ),
    ),
)


def _placeholder(
    version: str,
    source_format: str,
    fields: tuple[ReferenceField, ...],
) -> ReferenceRegistry:
    """为后续导入域提供已版本化的机器引用清单。

    这些版本在 1.30 仅用于 plan/source-check 的“已知版本”门禁；正式字段
    解析和写入在 1.33–1.38 按域补齐。required_tables 为空表示该切片尚不
    对该格式做 SQLite schema 验证，但版本和 owner/manifest 仍受控。
    """

    return ReferenceRegistry(
        source_version=version,
        source_format=source_format,
        required_tables={},
        reference_fields=fields,
    )


_REGISTRIES: dict[str, ReferenceRegistry] = {
    _CHAT_HISTORY_V1.source_version: _CHAT_HISTORY_V1,
    "mastery_sqlite/v1": ReferenceRegistry(
        source_version="mastery_sqlite/v1",
        source_format="mastery_sqlite",
        required_tables={
            "mastery_paths": _table(["path_id", "state_json", "revision", "created_at", "updated_at"]),
            "mastery_path_sessions": _table(
                ["path_id", "session_id", "created_at", "last_seen_at"]
            ),
            "mastery_interactions": _table(
                [
                    "interaction_id",
                    "path_id",
                    "status",
                    "question_json",
                    "session_id",
                    "turn_id",
                    "user_answer",
                    "result_json",
                    "created_at",
                    "updated_at",
                ]
            ),
            "mastery_events": _table(
                [
                    "id",
                    "path_id",
                    "revision",
                    "event_type",
                    "payload_json",
                    "session_id",
                    "turn_id",
                    "created_at",
                ]
            ),
        },
        reference_fields=(
            ReferenceField("mastery_paths.owner_session_id", "sessions.id", "session_id_map"),
            ReferenceField("mastery_path_sessions.session_id", "sessions.id", "session_id_map"),
            ReferenceField("mastery_interactions.session_id", "sessions.id", "session_id_map"),
            ReferenceField("mastery_interactions.turn_id", "turns.id", "turn_id_map"),
            ReferenceField("mastery_events.session_id", "sessions.id", "session_id_map"),
            ReferenceField("mastery_events.turn_id", "turns.id", "turn_id_map"),
        ),
    ),
    "mastery_sqlite/v2": ReferenceRegistry(
        source_version="mastery_sqlite/v2",
        source_format="mastery_sqlite",
        required_tables={
            "mastery_paths": _table(
                [
                    "path_id",
                    "state_json",
                    "revision",
                    "created_at",
                    "updated_at",
                    "owner_session_id",
                ]
            ),
            "mastery_path_sessions": _table(
                ["path_id", "session_id", "created_at", "last_seen_at"]
            ),
            "mastery_interactions": _table(
                [
                    "interaction_id",
                    "path_id",
                    "status",
                    "question_json",
                    "session_id",
                    "turn_id",
                    "user_answer",
                    "result_json",
                    "created_at",
                    "updated_at",
                ]
            ),
            "mastery_events": _table(
                [
                    "id",
                    "path_id",
                    "revision",
                    "event_type",
                    "payload_json",
                    "session_id",
                    "turn_id",
                    "created_at",
                ]
            ),
            "mastery_topic_meta": _table(
                [
                    "path_id",
                    "goal",
                    "description",
                    "emoji",
                    "map_seed",
                    "status",
                    "created_at",
                    "updated_at",
                ]
            ),
            "mastery_topic_sources": _table(
                [
                    "source_id",
                    "path_id",
                    "kind",
                    "external_id",
                    "label",
                    "excerpt",
                    "position",
                    "available",
                    "metadata_json",
                    "created_at",
                ]
            ),
        },
        reference_fields=(
            ReferenceField("mastery_paths.owner_session_id", "sessions.id", "session_id_map"),
            ReferenceField("mastery_path_sessions.session_id", "sessions.id", "session_id_map"),
            ReferenceField("mastery_interactions.session_id", "sessions.id", "session_id_map"),
            ReferenceField("mastery_interactions.turn_id", "turns.id", "turn_id_map"),
            ReferenceField("mastery_events.session_id", "sessions.id", "session_id_map"),
            ReferenceField("mastery_events.turn_id", "turns.id", "turn_id_map"),
            ReferenceField(
                "mastery_topic_sources.external_id",
                "conditional_topic_source",
                "conditional_resource_map",
            ),
        ),
    ),
    "reading_catalog_sqlite/v1": ReferenceRegistry(
        source_version="reading_catalog_sqlite/v1",
        source_format="reading_catalog_sqlite",
        required_tables={
            "reading_materials": _table(
                [
                    "material_id",
                    "content_id",
                    "filename",
                    "title",
                    "source_kind",
                    "source_url",
                    "mime",
                    "render_mode",
                    "cover_url",
                    "duration_seconds",
                    "status",
                    "progress",
                    "error_code",
                    "error_detail",
                    "created_at",
                    "updated_at",
                    "last_opened_at",
                ]
            ),
            "reading_workspaces": _table(
                [
                    "workspace_id",
                    "title",
                    "description",
                    "active_material_id",
                    "created_at",
                    "updated_at",
                ]
            ),
            "reading_workspace_materials": _table(
                [
                    "workspace_id",
                    "material_id",
                    "tab_order",
                    "pinned",
                    "opened",
                    "added_at",
                ]
            ),
            "reading_workspace_sessions": _table(
                [
                    "workspace_id",
                    "session_id",
                    "title",
                    "active_material_id",
                    "created_at",
                    "updated_at",
                ]
            ),
            "reading_session_links": _table(
                [
                    "workspace_id",
                    "source_session_id",
                    "target_session_id",
                    "created_at",
                ]
            ),
        },
        reference_fields=(
            ReferenceField(
                "reading_workspaces.active_material_id",
                "reading_materials.material_id",
                "reading_material_id_map",
            ),
            ReferenceField(
                "reading_workspace_materials.material_id",
                "reading_materials.material_id",
                "reading_material_id_map",
                required=True,
            ),
            ReferenceField(
                "reading_workspace_sessions.session_id",
                "sessions.id",
                "session_id_map",
                required=True,
            ),
            ReferenceField(
                "reading_workspace_sessions.active_material_id",
                "reading_materials.material_id",
                "reading_material_id_map",
            ),
            ReferenceField(
                "reading_session_links.source_session_id",
                "sessions.id",
                "session_id_map",
                required=True,
            ),
            ReferenceField(
                "reading_session_links.target_session_id",
                "sessions.id",
                "session_id_map",
                required=True,
            ),
        ),
    ),
    "cron_sqlite/v1": ReferenceRegistry(
        source_version="cron_sqlite/v1",
        source_format="cron_sqlite",
        required_tables={
            "cron_jobs": _table(["id", "owner_key", "next_run_at_ms", "payload", "updated_at_ms"]),
            "cron_meta": _table(["singleton", "revision"]),
        },
        reference_fields=(
            ReferenceField("cron_jobs.payload.owner.session_id", "sessions.id", "session_id_map"),
            ReferenceField("cron_jobs.payload.owner.user_id", "identity.owner_id", "owner_id_map"),
            ReferenceField("cron_jobs.payload.state.run_history[*].message_id", "messages.id", "message_id_map"),
        ),
    ),
    "partner_runtime_status_sqlite/v1": ReferenceRegistry(
        source_version="partner_runtime_status_sqlite/v1",
        source_format="partner_runtime_status_sqlite",
        required_tables={
            "partner_runtime_status": _table(
                [
                    "partner_id",
                    "owner_id",
                    "running",
                    "state",
                    "started_at",
                    "last_reload_error",
                    "payload",
                    "updated_at",
                ]
            ),
        },
        reference_fields=(
            ReferenceField("partner_runtime_status.partner_id", "partners.partner_id", "partner_id_map", required=True),
            ReferenceField("partner_runtime_status.owner_id", "identity.owner_id", "owner_id_map", required=True),
        ),
    ),
    "marginnote_sqlite/v1": ReferenceRegistry(
        source_version="marginnote_sqlite/v1",
        source_format="marginnote_sqlite",
        required_tables={
            "mn4_objects": _table(
                [
                    "object_id",
                    "device_id",
                    "object_type",
                    "title",
                    "content",
                    "excerpt",
                    "document_id",
                    "document_title",
                    "page",
                    "tags",
                    "links",
                    "color",
                    "created_at",
                    "updated_at",
                    "synced_at",
                    "raw",
                ]
            ),
            "mn4_devices": _table(
                [
                    "device_id",
                    "device_name",
                    "device_kind",
                    "token_hash",
                    "paired_at",
                    "last_seen",
                    "active",
                ]
            ),
            "mn4_cursors": _table(["device_id", "cursor"]),
            "mn4_tombstones": _table(["object_id", "device_id", "deleted_at"]),
        },
        reference_fields=(
            ReferenceField("source.resource_mappings.kb_id", "knowledge_bases.kb_id", "resource_id_map", required=True),
            ReferenceField("mn4_objects.device_id", "marginnote_devices.device_id", "device_scope_map", required=True),
            ReferenceField("mn4_cursors.device_id", "marginnote_devices.device_id", "device_scope_map", required=True),
            ReferenceField("mn4_tombstones.object_id", "marginnote_objects.object_id", "object_scope_map"),
        ),
    ),
    "matrix_nio_sqlite/v0.26": ReferenceRegistry(
        source_version="matrix_nio_sqlite/v0.26",
        source_format="matrix_nio_sqlite",
        required_tables={
            "accounts": _table(["id", "account", "user_id", "device_id", "shared"]),
            "olmsessions": _table(
                [
                    "session_id",
                    "creation_time",
                    "last_usage_date",
                    "sender_key",
                    "account_id",
                    "session",
                ]
            ),
            "megolminboundsessions": _table(
                ["session_id", "sender_key", "account_id", "fp_key", "room_id", "session"]
            ),
            "forwardedchains": _table(["id", "sender_key", "session_id"]),
            "devicekeys": _table(
                ["id", "device_id", "user_id", "display_name", "deleted", "account_id"]
            ),
            "keys": _table(["id", "key_type", "key", "device_id"]),
            "devicetruststate": _table(["device_id", "state"]),
            "encryptedrooms": _table(["id", "room_id", "account_id"]),
            "synctokens": _table(["id", "token", "account_id"]),
            "outgoingkeyrequests": _table(
                ["id", "request_id", "session_id", "room_id", "algorithm", "account_id"]
            ),
            "storeversion": _table(["id", "version"]),
        },
        reference_fields=(
            ReferenceField("source.matrix.user_id", "matrix_accounts.user_id", "matrix_user_scope", required=True),
            ReferenceField("source.matrix.device_id", "matrix_accounts.device_id", "matrix_device_scope", required=True),
            ReferenceField("source.matrix.partner_id", "partners.partner_id", "partner_id_map", required=True),
            ReferenceField("megolminboundsessions.room_id", "matrix_rooms.room_id", "preserve_protocol_id"),
            ReferenceField("devicetruststate.device_id", "devicekeys.id", "local_device_pk_map", required=True),
            ReferenceField("synctokens.account_id", "accounts.id", "local_account_pk_map", required=True),
        ),
    ),
    "pocketbase/v1": ReferenceRegistry(
        source_version="pocketbase/v1",
        source_format="pocketbase_json",
        required_tables={
            "users": _table([]),
            "sessions": _table(
                [
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
                ]
            ),
            "messages": _table(
                [
                    "session_id",
                    "role",
                    "content",
                    "capability",
                    "events_json",
                    "attachments_json",
                    "metadata_json",
                    "msg_created_at",
                ]
            ),
            "turns": _table(
                [
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
                ]
            ),
            "turn_events": _table(
                [
                    "turn_id",
                    "session_id",
                    "seq",
                    "type",
                    "source",
                    "stage",
                    "content",
                    "metadata_json",
                    "event_timestamp",
                ]
            ),
            "knowledge_bases": _table(
                [
                    "kb_name",
                    "user_id",
                    "description",
                    "rag_provider",
                    "needs_reindex",
                    "status",
                    "kb_created_at",
                    "raw_files",
                ]
            ),
        },
        reference_fields=(
            ReferenceField("sessions.user_id", "pocketbase.users.id", "owner_id_map"),
            ReferenceField("messages.id", "pocketbase.messages.id", "string_id_map", required=True),
            ReferenceField("messages.session_id", "sessions.session_id", "session_id_map", required=True),
            ReferenceField("messages.attachments_json[*].id", "resources.attachment_id", "resource_manifest_map"),
            ReferenceField("messages.metadata_json.message_id", "messages.id", "message_id_map"),
            ReferenceField("messages.metadata_json.source_message_id", "messages.id", "message_id_map"),
            ReferenceField("turns.turn_id", "turns.id", "turn_id_map", required=True),
            ReferenceField("turns.session_id", "sessions.session_id", "session_id_map", required=True),
            ReferenceField("turns.assistant_message_id", "messages.id", "message_id_map"),
            ReferenceField("turn_events.turn_id", "turns.turn_id", "turn_id_map", required=True),
            ReferenceField("turn_events.metadata_json.message_id", "messages.id", "message_id_map"),
            ReferenceField(
                "knowledge_bases.user_id",
                "pocketbase.users.id",
                "owner_id_map",
            ),
            ReferenceField(
                "knowledge_bases.raw_files[*]",
                "knowledge_base_files.filename",
                "file_manifest_map",
            ),
        ),
    ),
}


def get_reference_registry(source_version: str) -> ReferenceRegistry:
    """Return the registry for *source_version* or raise a controlled error."""

    try:
        return _REGISTRIES[source_version]
    except KeyError as exc:
        raise UnsupportedSourceVersion(source_version) from exc


def known_source_versions() -> tuple[str, ...]:
    """Registered offline source versions."""

    return tuple(sorted(_REGISTRIES))


__all__ = [
    "ReferenceField",
    "ReferenceRegistry",
    "UnsupportedSourceVersion",
    "get_reference_registry",
    "known_source_versions",
]
