"""应用迁移工具：历史与实际目录双重校验；运行入口只读 verify。"""

import hashlib
from importlib.resources import files
import json

import psycopg

LOCK_ID = 0x4454454E544552
TOOL_VERSION = "1"

# 这是随应用版本发布的实际结构契约，不是可由数据库操作者一起改写的库内 baseline。
# 未来新增正式 migration 时必须同步升级此契约；本切片不修复/接管漂移对象。
_COLUMNS = {
    "schema_history": "version:text! checksum:text! applied_at:timestamptz!",
    "tenants": "id:uuid! external_tid:text external_eligibility:text! local_enabled:bool! provisioning_status:text! external_version:int8! local_version:int8! provisioning_version:int8! policy_version:int8! auth_epoch:text! bootstrap_completed:bool! recovery_state:text!",
    "users": "tenant_id:uuid! id:text! username:text! role:text! disabled:bool! auth_version:int8! created_at:timestamptz!",
    "local_credentials": "tenant_id:uuid! user_id:text! password_hash:text!",
    "auth_sessions": "tenant_id:uuid! user_id:text! id:uuid! auth_version:int8! auth_epoch:text! created_at:timestamptz! expires_at:timestamptz! revoked_at:timestamptz",
    "audit": "id:int8! tenant_id:uuid! actor_id:text! action:text! target_id:text! request_id:text! result:text! created_at:timestamptz!",
    "sessions": "tenant_id:uuid! owner_id:text! id:text! title:text! summary:text! summary_up_to_msg_id:int8 preferences:jsonb! parent_session_id:text active_leaf_id:int8 pinned:bool! archived:bool! deleting:bool! version:int8! created_at:float8! updated_at:float8!",
    "messages": "tenant_id:uuid! owner_id:text! session_id:text! id:int8! role:text! content:text! capability:text! events:jsonb! attachments:jsonb! metadata:jsonb! parent_message_id:int8 created_at:float8!",
    "turns": "tenant_id:uuid! user_id:text! session_id:text! id:text! capability:text! status:text! owner_id:text! fencing_token:int8! error:text! failure_code:text! retryable:bool! assistant_message_id:int8 user_message_id:int8 next_seq:int8! state_version:int8! finished_at:float8 created_at:float8! updated_at:float8!",
    "turn_events": "tenant_id:uuid! owner_id:text! session_id:text! turn_id:text! seq:int8! event:jsonb!",
    "operations": "tenant_id:uuid! owner_id:text! operation_id:text! fingerprint:text! request:jsonb session_id:text turn_id:text status:text! expires_at:timestamptz!",
    "turn_commands": "tenant_id:uuid! owner_id:text! session_id:text! turn_id:text! command_id:text! kind:text! fingerprint:text! accepted:bool! state_version:int8! created_at:timestamptz!",
    "executor_state": "resource:text! execution_id:uuid! status:text! updated_at:timestamptz!",
}
_OWNER_TABLES = frozenset(
    {
        "sessions",
        "messages",
        "turns",
        "turn_events",
        "operations",
        "turn_commands",
        "notebook_entries",
        "notebook_categories",
        "notebook_entry_categories",
    }
)
_TENANT_TABLES = frozenset(_COLUMNS) - {"schema_history", "executor_state"}


def _fk(columns, target, target_columns, *, cascade=False, deferred=False):
    return (
        f"FOREIGN KEY ({columns}) REFERENCES enterprise.{target}({target_columns})"
        + (" ON DELETE CASCADE" if cascade else "")
        + (" DEFERRABLE INITIALLY DEFERRED" if deferred else "")
    )


def _enum_check(column, values):
    members = ", ".join(f"'{value}'::text" for value in values)
    return f"CHECK (({column} = ANY (ARRAY[{members}])))"


_CONSTRAINTS = {
    "schema_history": {"PRIMARY KEY (version)"},
    "tenants": {
        "PRIMARY KEY (id)",
        _enum_check("external_eligibility", ["not_required", "allowed", "denied"]),
        _enum_check("provisioning_status", ["pending", "ready", "failed"]),
        _enum_check("recovery_state", ["normal", "quarantined"]),
    },
    "users": {
        "PRIMARY KEY (tenant_id, id)",
        "UNIQUE (tenant_id, username)",
        _fk("tenant_id", "tenants", "id"),
        "CHECK (((length(id) >= 1) AND (length(id) <= 255)))",
        "CHECK (((length(username) >= 1) AND (length(username) <= 128)))",
        _enum_check("role", ["tenant_admin", "user"]),
    },
    "local_credentials": {
        "PRIMARY KEY (tenant_id, user_id)",
        _fk("tenant_id, user_id", "users", "tenant_id, id", cascade=True),
    },
    "auth_sessions": {
        "PRIMARY KEY (tenant_id, id)",
        _fk("tenant_id, user_id", "users", "tenant_id, id", cascade=True),
    },
    "audit": {"PRIMARY KEY (id)"},
    "sessions": {
        "PRIMARY KEY (tenant_id, id)",
        "UNIQUE (tenant_id, owner_id, id)",
        "CHECK (((parent_session_id IS NULL) OR (parent_session_id <> id)))",
        _fk("tenant_id, owner_id", "users", "tenant_id, id"),
        _fk("tenant_id, owner_id, parent_session_id", "sessions", "tenant_id, owner_id, id"),
        _fk(
            "tenant_id, owner_id, id, active_leaf_id",
            "messages",
            "tenant_id, owner_id, session_id, id",
            deferred=True,
        ),
        _fk(
            "tenant_id, owner_id, id, summary_up_to_msg_id",
            "messages",
            "tenant_id, owner_id, session_id, id",
            deferred=True,
        ),
    },
    "messages": {
        "PRIMARY KEY (tenant_id, id)",
        "UNIQUE (tenant_id, owner_id, session_id, id)",
        "CHECK (((parent_message_id IS NULL) OR (parent_message_id < id)))",
        _enum_check("role", ["user", "assistant", "system", "tool"]),
        _fk("tenant_id, owner_id, session_id", "sessions", "tenant_id, owner_id, id", cascade=True),
        _fk(
            "tenant_id, owner_id, session_id, parent_message_id",
            "messages",
            "tenant_id, owner_id, session_id, id",
            deferred=True,
        ),
    },
    "turns": {
        "PRIMARY KEY (tenant_id, id)",
        "UNIQUE (tenant_id, user_id, session_id, id)",
        _enum_check(
            "status", ["queued", "running", "waiting_input", "completed", "cancelled", "failed"]
        ),
        _fk("tenant_id, user_id, session_id", "sessions", "tenant_id, owner_id, id", cascade=True),
        _fk(
            "tenant_id, user_id, session_id, user_message_id",
            "messages",
            "tenant_id, owner_id, session_id, id",
            deferred=True,
        ),
        _fk(
            "tenant_id, user_id, session_id, assistant_message_id",
            "messages",
            "tenant_id, owner_id, session_id, id",
            deferred=True,
        ),
    },
    "turn_events": {
        "PRIMARY KEY (tenant_id, turn_id, seq)",
        "CHECK ((seq > 0))",
        _fk(
            "tenant_id, owner_id, session_id, turn_id",
            "turns",
            "tenant_id, user_id, session_id, id",
            cascade=True,
        ),
    },
    "operations": {
        "PRIMARY KEY (tenant_id, owner_id, operation_id)",
        _fk("tenant_id, owner_id", "users", "tenant_id, id"),
        _fk(
            "tenant_id, owner_id, session_id, turn_id",
            "turns",
            "tenant_id, user_id, session_id, id",
            deferred=True,
        ),
        _enum_check("status", ["registered", "deleted"]),
        "CHECK ((((status = 'deleted'::text) AND (request IS NULL) AND (session_id IS NULL) AND (turn_id IS NULL)) OR ((status = 'registered'::text) AND (request IS NOT NULL) AND (session_id IS NOT NULL) AND (turn_id IS NOT NULL))))",
    },
    "turn_commands": {
        "PRIMARY KEY (tenant_id, owner_id, turn_id, command_id)",
        _enum_check("kind", ["reply", "cancel"]),
        _fk(
            "tenant_id, owner_id, session_id, turn_id",
            "turns",
            "tenant_id, user_id, session_id, id",
            cascade=True,
        ),
    },
    "executor_state": {"PRIMARY KEY (resource)", _enum_check("status", ["active", "stopped"])},
}


_COLUMNS_V2 = {
    **_COLUMNS,
    "users": _COLUMNS["users"]
    + " deleted_at:timestamptz avatar:text! avatar_object:text! preset:text! learner_profile:jsonb learning_policy:jsonb",
    "auth_sessions": _COLUMNS["auth_sessions"]
    + " device_credential_id:text device_generation:int8",
    "device_credentials": "tenant_id:uuid! user_id:text! id:text! device_name:text! pairing_code_hash:text! pin_hash:text! auth_version:int8! auth_epoch:text! generation:int8! created_at:timestamptz! expires_at:timestamptz! daily_limit_minutes:int4! last_login_at:timestamptz last_heartbeat_at:timestamptz usage_day:date used_seconds:int4! failed_pin_attempts:int4! pin_locked_until:timestamptz revoked_at:timestamptz revoked_by:text!",
}
_CONSTRAINTS_V2 = {
    **_CONSTRAINTS,
    "users": _CONSTRAINTS["users"] | {_enum_check("preset", ["standard", "learner", "custom"])},
    "auth_sessions": _CONSTRAINTS["auth_sessions"]
    | {
        _fk(
            "tenant_id, user_id, device_credential_id",
            "device_credentials",
            "tenant_id, user_id, id",
        ),
        "CHECK ((((device_credential_id IS NULL) AND (device_generation IS NULL)) OR ((device_credential_id IS NOT NULL) AND (device_generation IS NOT NULL))))",
    },
    "device_credentials": {
        "PRIMARY KEY (tenant_id, id)",
        "UNIQUE (tenant_id, user_id, id)",
        "UNIQUE (tenant_id, pairing_code_hash)",
        _fk("tenant_id, user_id", "users", "tenant_id, id"),
        "CHECK (((daily_limit_minutes >= 5) AND (daily_limit_minutes <= 1440)))",
        "CHECK ((used_seconds >= 0))",
        "CHECK ((failed_pin_attempts >= 0))",
    },
}
_COLUMNS_V3 = {
    **_COLUMNS_V2,
    "device_credentials": _COLUMNS_V2["device_credentials"] + " usage_remainder_us:int4!",
}
_CONSTRAINTS_V3 = {
    **_CONSTRAINTS_V2,
    "device_credentials": _CONSTRAINTS_V2["device_credentials"]
    | {"CHECK (((usage_remainder_us >= 0) AND (usage_remainder_us < 1000000)))"},
}
_COLUMNS_V4 = {
    **_COLUMNS_V3,
    "notebook_entries": "tenant_id:uuid! owner_id:text! id:int8! session_id:text! turn_id:text! question_id:text! question:text! question_type:text! options:jsonb! correct_answer:text! explanation:text! difficulty:text! user_answer:text! user_answer_images:jsonb! source:text! material_id:text! material_title:text! section_id:text! section_title:text! score_trend:text! is_correct:bool! resolved:bool! bookmarked:bool! followup_session_id:text! ai_judgment:text! created_at:float8! updated_at:float8! version:int8! execution_turn_id:text followup_session_ref:text",
    "notebook_categories": "tenant_id:uuid! owner_id:text! id:int8! name:text! created_at:float8! version:int8! name_key:text",
    "notebook_entry_categories": "tenant_id:uuid! owner_id:text! entry_id:int8! category_id:int8!",
}
_CONSTRAINTS_V4 = {
    **_CONSTRAINTS_V3,
    "notebook_entries": {
        "PRIMARY KEY (tenant_id, owner_id, id)",
        "UNIQUE (tenant_id, owner_id, session_id, turn_id, question_id)",
        _fk("tenant_id, owner_id, session_id", "sessions", "tenant_id, owner_id, id", cascade=True),
        _fk(
            "tenant_id, owner_id, session_id, execution_turn_id",
            "turns",
            "tenant_id, user_id, session_id, id",
        ),
        _fk("tenant_id, owner_id, followup_session_ref", "sessions", "tenant_id, owner_id, id"),
        _enum_check("source", ["deep_question", "book", "mastery_path", "immersive_reading"]),
        _enum_check("score_trend", ["new", "unchanged", "improved", "declined"]),
        "CHECK ((jsonb_typeof(user_answer_images) = 'array'::text))",
        "CHECK ((version >= 1))",
    },
    "notebook_categories": {
        "PRIMARY KEY (tenant_id, owner_id, id)",
        "UNIQUE (tenant_id, owner_id, name_key)",
        _fk("tenant_id, owner_id", "users", "tenant_id, id"),
        "CHECK ((length(name) > 0))",
        "CHECK ((version >= 1))",
    },
    "notebook_entry_categories": {
        "PRIMARY KEY (tenant_id, owner_id, entry_id, category_id)",
        _fk(
            "tenant_id, owner_id, entry_id",
            "notebook_entries",
            "tenant_id, owner_id, id",
            cascade=True,
        ),
        _fk(
            "tenant_id, owner_id, category_id",
            "notebook_categories",
            "tenant_id, owner_id, id",
            cascade=True,
        ),
    },
}
# 生成引用列必须验证表达式/生成属性，只有类型检查会允许 DROP EXPRESSION 绕过 FK。
_NOTEBOOK_GENERATED = {
    ("notebook_entries", "execution_turn_id"): (
        "s",
        "",
        "CASE WHEN (source <> 'book'::text) THEN NULLIF(turn_id, ''::text) ELSE NULL::text END",
        "default",
    ),
    ("notebook_entries", "followup_session_ref"): (
        "s",
        "",
        "NULLIF(followup_session_id, ''::text)",
        "default",
    ),
    ("notebook_categories", "name_key"): (
        "s",
        "",
        "translate(name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'::text, 'abcdefghijklmnopqrstuvwxyz'::text)",
        "C",
    ),
}
_NOTEBOOK_DEFAULTS = {
    "notebook_entries": {
        **dict.fromkeys(
            (
                "turn_id",
                "question_type",
                "correct_answer",
                "explanation",
                "difficulty",
                "user_answer",
                "material_id",
                "material_title",
                "section_id",
                "section_title",
                "followup_session_id",
                "ai_judgment",
            ),
            "''::text",
        ),
        "options": "'{}'::jsonb",
        "user_answer_images": "'[]'::jsonb",
        "source": "'deep_question'::text",
        "score_trend": "'new'::text",
        "is_correct": "false",
        "resolved": "false",
        "bookmarked": "false",
        "version": "1",
    },
    "notebook_categories": {"version": "1"},
    "notebook_entry_categories": {},
}
_NOTEBOOK_INDEXES = {
    "notebook_entries_recent": "CREATE INDEX notebook_entries_recent ON enterprise.notebook_entries USING btree (tenant_id, owner_id, created_at DESC, id DESC)",
    "notebook_entries_session": "CREATE INDEX notebook_entries_session ON enterprise.notebook_entries USING btree (tenant_id, owner_id, session_id, created_at DESC, id DESC)",
    "notebook_entries_material": "CREATE INDEX notebook_entries_material ON enterprise.notebook_entries USING btree (tenant_id, owner_id, source, material_id, section_id, created_at DESC, id DESC)",
    "notebook_entries_bookmarked": "CREATE INDEX notebook_entries_bookmarked ON enterprise.notebook_entries USING btree (tenant_id, owner_id, created_at DESC, id DESC) WHERE bookmarked",
    "notebook_entries_execution_turn": "CREATE INDEX notebook_entries_execution_turn ON enterprise.notebook_entries USING btree (tenant_id, owner_id, session_id, execution_turn_id) WHERE (execution_turn_id IS NOT NULL)",
    "notebook_entries_followup": "CREATE INDEX notebook_entries_followup ON enterprise.notebook_entries USING btree (tenant_id, owner_id, followup_session_ref) WHERE (followup_session_ref IS NOT NULL)",
    "notebook_entry_categories_category": "CREATE INDEX notebook_entry_categories_category ON enterprise.notebook_entry_categories USING btree (tenant_id, owner_id, category_id, entry_id)",
}
_CATALOGS = {
    "0001_identity_sessions": (_COLUMNS, _CONSTRAINTS),
    "0002_account_profiles_devices": (_COLUMNS_V2, _CONSTRAINTS_V2),
    "0003_device_usage_precision": (_COLUMNS_V3, _CONSTRAINTS_V3),
    "0004_notebook_entries_categories": (_COLUMNS_V4, _CONSTRAINTS_V4),
}


# 随 SQL 发布的不可变结构清单；不是目标库自生成或可自动接受的 baseline。
_LEARNING_CATALOG = json.loads(
    files("deeptutor.persistence.postgres.migrations")
    .joinpath("learning_catalog.json")
    .read_text(encoding="utf8")
)
_COLUMNS_V5 = {**_COLUMNS_V4, **_LEARNING_CATALOG["columns"]}
_CONSTRAINTS_V5 = {
    **_CONSTRAINTS_V4,
    **{table: set(values) for table, values in _LEARNING_CATALOG["constraints"].items()},
}
_CATALOGS["0005_learning"] = (_COLUMNS_V5, _CONSTRAINTS_V5)
_OWNER_TABLES = _OWNER_TABLES | frozenset(_LEARNING_CATALOG["columns"])


_READING_CATALOG = json.loads(
    files("deeptutor.persistence.postgres.migrations")
    .joinpath("reading_catalog.json")
    .read_text(encoding="utf8")
)
_COLUMNS_V6 = {**_COLUMNS_V5, **_READING_CATALOG["columns"]}
_CONSTRAINTS_V6 = {
    **_CONSTRAINTS_V5,
    **{table: set(values) for table, values in _READING_CATALOG["constraints"].items()},
}
_CATALOGS["0006_reading"] = (_COLUMNS_V6, _CONSTRAINTS_V6)
_OWNER_TABLES = _OWNER_TABLES | frozenset(_READING_CATALOG["columns"])


_SESSION_RESOURCES_CATALOG = json.loads(
    files("deeptutor.persistence.postgres.migrations")
    .joinpath("session_resources_catalog.json")
    .read_text(encoding="utf8")
)
_CATALOGS["0007_session_resources"] = (
    {**_COLUMNS_V6, **_SESSION_RESOURCES_CATALOG["columns"]},
    {
        **_CONSTRAINTS_V6,
        **{t: set(v) for t, v in _SESSION_RESOURCES_CATALOG["constraints"].items()},
    },
)
_OWNER_TABLES = _OWNER_TABLES | frozenset(_SESSION_RESOURCES_CATALOG["columns"])


_CRON_CATALOG = json.loads(
    files("deeptutor.persistence.postgres.migrations")
    .joinpath("cron_catalog.json")
    .read_text(encoding="utf8")
)
_CATALOGS["0008_cron"] = (
    {**_CATALOGS["0007_session_resources"][0], **_CRON_CATALOG["columns"]},
    {
        **_CATALOGS["0007_session_resources"][1],
        **{t: set(v) for t, v in _CRON_CATALOG["constraints"].items()},
    },
)
_OWNER_TABLES = _OWNER_TABLES | frozenset(_CRON_CATALOG["columns"])


_PARTNER_RUNTIME_STATUS_CATALOG = json.loads(
    files("deeptutor.persistence.postgres.migrations")
    .joinpath("partner_runtime_status_catalog.json")
    .read_text(encoding="utf8")
)
_CATALOGS["0009_partner_runtime_status"] = (
    {**_CATALOGS["0008_cron"][0], **_PARTNER_RUNTIME_STATUS_CATALOG["columns"]},
    {
        **_CATALOGS["0008_cron"][1],
        **{t: set(v) for t, v in _PARTNER_RUNTIME_STATUS_CATALOG["constraints"].items()},
    },
)
_OWNER_TABLES = _OWNER_TABLES | frozenset(_PARTNER_RUNTIME_STATUS_CATALOG["columns"])


_MATRIX_STORE_CATALOG = json.loads(
    files("deeptutor.persistence.postgres.migrations")
    .joinpath("matrix_store_catalog.json")
    .read_text(encoding="utf8")
)
_CATALOGS["0010_matrix_store"] = (
    {**_CATALOGS["0009_partner_runtime_status"][0], **_MATRIX_STORE_CATALOG["columns"]},
    {
        **_CATALOGS["0009_partner_runtime_status"][1],
        **{t: set(v) for t, v in _MATRIX_STORE_CATALOG["constraints"].items()},
    },
)
_OWNER_TABLES = _OWNER_TABLES | frozenset(_MATRIX_STORE_CATALOG["columns"])


_MARGINNOTE_STORE_CATALOG = json.loads(
    files("deeptutor.persistence.postgres.migrations")
    .joinpath("marginnote_store_catalog.json")
    .read_text(encoding="utf8")
)
_CATALOGS["0011_marginnote_store"] = (
    {**_CATALOGS["0010_matrix_store"][0], **_MARGINNOTE_STORE_CATALOG["columns"]},
    {
        **_CATALOGS["0010_matrix_store"][1],
        **{t: set(v) for t, v in _MARGINNOTE_STORE_CATALOG["constraints"].items()},
    },
)
_OWNER_TABLES = _OWNER_TABLES | frozenset(_MARGINNOTE_STORE_CATALOG["columns"])


_COLUMNS_V12 = {
    **_CATALOGS["0011_marginnote_store"][0],
    "maintenance_locks": "tenant_id:uuid! batch_id:uuid! active:bool! reason:text! entered_at:timestamptz! updated_at:timestamptz! released_at:timestamptz generation:int8!",
}
_CONSTRAINTS_V12 = {
    **_CATALOGS["0011_marginnote_store"][1],
    "maintenance_locks": {
        "PRIMARY KEY (tenant_id)",
        _fk("tenant_id", "tenants", "id"),
        "CHECK ((generation >= 1))",
    },
}
_CATALOGS["0012_offline_import_stage"] = (_COLUMNS_V12, _CONSTRAINTS_V12)

_COLUMNS_V13 = {
    **_COLUMNS_V12,
    "courses": "tenant_id:uuid! owner_id:text! id:text! name:text! description:text! color:text! instructions:text! agent_notes:text! default_capability:text! default_persona:text! resources:jsonb! syllabus:jsonb! status:text! archived_at:float8! created_at:float8! updated_at:float8! version:int8!",
}
_CONSTRAINTS_V13 = {
    **_CONSTRAINTS_V12,
    "courses": {
        "PRIMARY KEY (tenant_id, owner_id, id)",
        _fk("tenant_id, owner_id", "users", "tenant_id, id"),
        _enum_check("status", ["active", "archived"]),
        "CHECK ((jsonb_typeof(resources) = 'array'::text))",
        "CHECK ((jsonb_typeof(syllabus) = 'array'::text))",
        "CHECK ((length(id) > 0))",
        "CHECK ((length(name) > 0))",
        "CHECK ((version >= 1))",
    },
}
_CATALOGS["0013_courses"] = (_COLUMNS_V13, _CONSTRAINTS_V13)
_OWNER_TABLES = _OWNER_TABLES | frozenset({"courses"})

_COLUMNS_V14 = {
    **_COLUMNS_V13,
    "resource_objects": "tenant_id:uuid! owner_id:text! id:uuid! resource_kind:text! resource_id:text! bucket:text! object_key:text! content_hash:text! size_bytes:int8! mime_type:text! state:text! version:int8! retention:text! metadata:jsonb! created_by:text! created_at:timestamptz! updated_at:timestamptz! deleted_at:timestamptz cleanup_error:text!",
    "resource_cleanup_jobs": "tenant_id:uuid! owner_id:text! object_id:uuid! attempt:int8! state:text! last_error:text! not_before:timestamptz! updated_at:timestamptz!",
    "runtime_settings": "tenant_id:uuid! scope_kind:text! scope_id:text! key:text! version:int8! desired:jsonb! active:jsonb! status:text! updated_by:text! created_at:timestamptz! updated_at:timestamptz!",
    "runtime_policies": "tenant_id:uuid! policy_kind:text! subject_kind:text! subject_id:text! version:int8! document:jsonb! status:text! updated_by:text! created_at:timestamptz! updated_at:timestamptz!",
    "secret_references": "tenant_id:uuid! scope_kind:text! scope_id:text! name:text! provider:text! reference:text! version:int8! status:text! redacted_summary:text! updated_by:text! created_at:timestamptz! updated_at:timestamptz!",
    "runtime_audit_events": "tenant_id:uuid! id:uuid! event_kind:text! actor_id:text! scope_kind:text! scope_id:text! resource_kind:text! resource_id:text! summary:jsonb! created_at:timestamptz!",
}
_CONSTRAINTS_V14 = {
    **_CONSTRAINTS_V13,
    "resource_objects": {
        "PRIMARY KEY (tenant_id, owner_id, id)",
        "UNIQUE (tenant_id, bucket, object_key)",
        _fk("tenant_id, owner_id", "users", "tenant_id, id"),
        _enum_check("state", ["pending", "uploaded", "ready", "delete-pending", "deleted", "failed"]),
        _enum_check("retention", ["default", "temporary", "retained", "legal-hold"]),
        "CHECK ((length(resource_kind) > 0))",
        "CHECK ((length(bucket) > 0))",
        "CHECK ((length(object_key) > 0))",
        "CHECK (((content_hash = ''::text) OR (length(content_hash) = 64)))",
        "CHECK ((size_bytes >= 0))",
        "CHECK ((version >= 1))",
        "CHECK ((jsonb_typeof(metadata) = 'object'::text))",
    },
    "resource_cleanup_jobs": {
        "PRIMARY KEY (tenant_id, owner_id, object_id)",
        _fk(
            "tenant_id, owner_id, object_id",
            "resource_objects",
            "tenant_id, owner_id, id",
            cascade=True,
        ),
        _enum_check("state", ["pending", "running", "failed", "done"]),
        "CHECK ((attempt >= 0))",
    },
    "runtime_settings": {
        "PRIMARY KEY (tenant_id, scope_kind, scope_id, key)",
        _fk("tenant_id", "tenants", "id"),
        _enum_check("scope_kind", ["platform", "tenant", "owner"]),
        _enum_check("status", ["draft", "saved", "active", "failed", "draining"]),
        "CHECK ((length(key) > 0))",
        "CHECK ((version >= 1))",
        "CHECK ((jsonb_typeof(desired) = 'object'::text))",
        "CHECK ((jsonb_typeof(active) = 'object'::text))",
    },
    "runtime_policies": {
        "PRIMARY KEY (tenant_id, policy_kind, subject_kind, subject_id)",
        _fk("tenant_id", "tenants", "id"),
        _enum_check("subject_kind", ["tenant", "owner", "role", "tool", "model"]),
        _enum_check("status", ["draft", "saved", "active", "failed", "draining"]),
        "CHECK ((length(policy_kind) > 0))",
        "CHECK ((version >= 1))",
        "CHECK ((jsonb_typeof(document) = 'object'::text))",
    },
    "secret_references": {
        "PRIMARY KEY (tenant_id, scope_kind, scope_id, name)",
        _fk("tenant_id", "tenants", "id"),
        _enum_check("scope_kind", ["platform", "tenant", "owner"]),
        _enum_check("status", ["saved", "active", "failed", "draining", "missing"]),
        "CHECK ((length(name) > 0))",
        "CHECK ((length(provider) > 0))",
        "CHECK ((length(reference) > 0))",
        "CHECK ((version >= 1))",
    },
    "runtime_audit_events": {
        "PRIMARY KEY (tenant_id, id)",
        _fk("tenant_id", "tenants", "id"),
        _enum_check("scope_kind", ["platform", "tenant", "owner", "resource"]),
        "CHECK ((length(event_kind) > 0))",
        "CHECK ((jsonb_typeof(summary) = 'object'::text))",
    },
}
_CATALOGS["0014_externalized_runtime"] = (_COLUMNS_V14, _CONSTRAINTS_V14)
_OWNER_TABLES = _OWNER_TABLES | frozenset({"resource_objects", "resource_cleanup_jobs"})

_MIGRATION_STAGE_COLUMNS = {
    "batches": "batch_id:uuid! target_tenant_id:uuid! manifest_sha256:text! source_manifest:jsonb! verify_report:jsonb! status:text! operator:text! error:text! created_at:timestamptz! updated_at:timestamptz!",
    "sources": "batch_id:uuid! source_id:text! source_type:text! source_version:text! source_owner_id:text! target_owner_id:text! fingerprint:text! manifest:jsonb! status:text! rows_total:int8! rows_done:int8!",
    "id_mappings": "batch_id:uuid! domain:text! source_id:text! source_owner_id:text! source_key:text! target_key:text target_int:int8 metadata:jsonb!",
    "progress": "batch_id:uuid! domain:text! chunk_key:text! status:text! rows_done:int8! resume_cursor:jsonb! checksum:text! updated_at:timestamptz!",
    "promotion_items": "batch_id:uuid! domain:text! item_key:text! payload:jsonb! status:text! updated_at:timestamptz!",
}

# 2026-09 G1 决策改为单库单数据库用户：新迁移不再创建/授权独立
# dt_enterprise_app 角色。已经应用过旧 role-grant SQL 的环境只要目录结构校验仍通过，
# 允许这些旧 checksum 继续作为兼容历史，避免把等价的 ACL 策略调整误判为结构漂移。
_LEGACY_ROLE_GRANT_CHECKSUMS = {
    "0001_identity_sessions": frozenset({
        "06a1a9303d9d45745a31a94ec9a95ce2d864e48ff41be2a6a8d926abdeea7a3f",
    }),
    "0002_account_profiles_devices": frozenset({
        "9c55108c497f0c19b91a96e7813b711ed111540851d1c019c1876051884ae005",
    }),
    "0004_notebook_entries_categories": frozenset({
        "37baf9172c09031a6bb901daa42be7e7dde758ec549b1e7e462638fa1cf6fadf",
    }),
    "0005_learning": frozenset({
        "4ca565a95b3d7540ad0b24d7a7ec824327b2907379943eb7825e01ca86621398",
    }),
    "0006_reading": frozenset({
        "a0d69b15fc62d9786f453e8b7de430745b1806a5c53983e909972c90e501b62e",
    }),
    "0007_session_resources": frozenset({
        "f2a46b75d43c9617b3cb4a07b084a156d4e0be52e0f47d5a512f4a5a463eca69",
    }),
    "0008_cron": frozenset({
        "efe39a3661b1bd4d7f4ae4118ca16481d609157c2c4a39785157b1d5aa34f63f",
    }),
    "0009_partner_runtime_status": frozenset({
        "521a4568931864606ebd841ede44d9ae753407de645916306930ee43e4000e84",
    }),
    "0010_matrix_store": frozenset({
        "62f88dc235fad526fc1bf2d5464112e461ac4d1d5871c33e5cd509aa4abbf013",
    }),
    "0011_marginnote_store": frozenset({
        "9483eb57bdbd0d685d6130d5349ca1fae2eb0648fa453d5a8354f77c57846214",
    }),
    "0012_offline_import_stage": frozenset({
        "673e38f3cfb2adeb0a2b7d7d95063a45ae14b5b56b2ef8680b90afb1ba16b91d",
    }),
    "0013_courses": frozenset({
        "c41c2300d8ec0699fa78d7eade382e720a760d9921c3b898b62b0eb7bc0f96ef",
    }),
    "0014_externalized_runtime": frozenset({
        "27747b00005f86f528dba89ec24be52efc26ddf3b3b3886e959a4b4cb56d7023",
    }),
}


def _accepted_checksums(expected):
    return {
        version: frozenset({digest, *_LEGACY_ROLE_GRANT_CHECKSUMS.get(version, ())})
        for version, digest in expected.items()
    }


class MigrationRunner:
    def __init__(self, dsn):
        self._dsn = dsn

    def _migrations(self):
        return [
            (p.name[:-4], p.read_text(encoding="utf8"))
            for p in sorted(
                files("deeptutor.persistence.postgres.migrations").iterdir(), key=lambda p: p.name
            )
            if p.name.endswith(".sql")
        ]

    async def _history(self, c):
        exists = await (
            await c.execute("SELECT to_regclass('enterprise.schema_history')")
        ).fetchone()
        if not exists[0]:
            return {}
        return dict(
            await (
                await c.execute(
                    "SELECT version,checksum FROM enterprise.schema_history ORDER BY version"
                )
            ).fetchall()
        )

    async def _plan(self, c):
        history = await self._history(c)
        migrations = self._migrations()
        expected = {v: hashlib.sha256(sql.encode()).hexdigest() for v, sql in migrations}
        accepted = _accepted_checksums(expected)
        if any(v not in accepted or digest not in accepted[v] for v, digest in history.items()):
            raise RuntimeError("schema history drift or incompatible version")
        applied = [v for v, _ in migrations if v in history]
        if applied != [v for v, _ in migrations][: len(applied)]:
            raise RuntimeError("schema history drift: non-contiguous versions")
        return [(v, sql) for v, sql in migrations if v not in history]

    async def _verify_schema(self, c, version=None):
        version = version or self._migrations()[-1][0]
        if version not in _CATALOGS:
            raise RuntimeError("unsupported schema catalog version")
        expected_columns, expected_constraints = _CATALOGS[version]
        tenant_tables = frozenset(expected_columns) - {"schema_history", "executor_state"}
        # 明确 search_path，避免连接设置影响目录表达式反解或同名函数解析。
        await c.execute("SET LOCAL search_path = pg_catalog")
        rows = await (
            await c.execute("""
            SELECT r.relname,r.relkind,r.relrowsecurity,r.relforcerowsecurity
              FROM pg_class r JOIN pg_namespace n ON n.oid=r.relnamespace
             WHERE n.nspname='enterprise' AND r.relkind IN ('r','p','v','m','f')
        """)
        ).fetchall()
        tables = {row[0]: row[1:] for row in rows}
        if set(tables) != set(expected_columns):
            raise RuntimeError("schema drift: required table set differs")
        for name, (kind, enabled, forced) in tables.items():
            expected_rls = name in tenant_tables
            if kind != "r" or enabled != expected_rls or forced:
                raise RuntimeError(f"schema drift: {name} table kind or RLS flags differ")
        columns = {name: {} for name in expected_columns}
        rows = await (
            await c.execute("""
            SELECT r.relname,a.attname,t.typname,a.attnotnull
              FROM pg_attribute a JOIN pg_class r ON r.oid=a.attrelid
              JOIN pg_namespace n ON n.oid=r.relnamespace JOIN pg_type t ON t.oid=a.atttypid
             WHERE n.nspname='enterprise' AND r.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        """)
        ).fetchall()
        for table, column, kind, required in rows:
            columns[table][column] = (kind, required)
        for table, specification in expected_columns.items():
            expected = {
                column: (kind.removesuffix("!"), kind.endswith("!"))
                for field in specification.split()
                for column, kind in [field.split(":")]
            }
            if columns[table] != expected:
                raise RuntimeError(f"schema drift: {table} columns/types/nullability differ")
        expected_policies = {}
        for table in tenant_tables:
            tenant_column = "id" if table == "tenants" else "tenant_id"
            tenant_expression = f"({tenant_column} = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"
            expected_policies[(table, "tenant_scope")] = (
                "*",
                True,
                [0],
                tenant_expression,
                tenant_expression,
            )
            if table in _OWNER_TABLES:
                owner_column = "user_id" if table == "turns" else "owner_id"
                owner_expression = f"({owner_column} = NULLIF(current_setting('app.user_id'::text, true), ''::text))"
                expected_policies[(table, "owner_scope")] = (
                    "*",
                    False,
                    [0],
                    owner_expression,
                    owner_expression,
                )
        rows = await (
            await c.execute("""
            SELECT r.relname,p.polname,p.polcmd,p.polpermissive,p.polroles,
                   pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid)
              FROM pg_policy p JOIN pg_class r ON r.oid=p.polrelid
              JOIN pg_namespace n ON n.oid=r.relnamespace WHERE n.nspname='enterprise'
        """)
        ).fetchall()
        actual_policies = {(row[0], row[1]): tuple(row[2:]) for row in rows}
        if actual_policies != expected_policies:
            raise RuntimeError("schema drift: tenant/owner RLS policies differ")
        constraints = {name: set() for name in expected_constraints}
        rows = await (
            await c.execute("""
            SELECT r.relname,pg_get_constraintdef(co.oid,false),co.convalidated,
                   coalesce(i.indisvalid AND i.indisready AND i.indislive,true)
              FROM pg_constraint co JOIN pg_class r ON r.oid=co.conrelid
              JOIN pg_namespace n ON n.oid=r.relnamespace
              LEFT JOIN pg_index i ON i.indexrelid=co.conindid
             WHERE n.nspname='enterprise' AND co.contype IN ('p','u','f','c')
        """)
        ).fetchall()
        for table, definition, validated, index_valid in rows:
            if not validated or not index_valid:
                raise RuntimeError(f"schema drift: {table} constraint/index is not validated")
            constraints[table].add(definition)
        if constraints != expected_constraints:
            raise RuntimeError("schema drift: primary/unique/foreign/check constraints differ")
        disabled = await (
            await c.execute("""
            SELECT 1 FROM pg_trigger t JOIN pg_constraint co ON co.oid=t.tgconstraint
              JOIN pg_class r ON r.oid=co.conrelid JOIN pg_namespace n ON n.oid=r.relnamespace
             WHERE n.nspname='enterprise' AND co.contype='f' AND t.tgenabled NOT IN ('O','A') LIMIT 1
        """)
        ).fetchone()
        if disabled:
            raise RuntimeError("schema drift: foreign key enforcement trigger is disabled")
        active_index = await (
            await c.execute("""
            SELECT i.indisunique,i.indisvalid,i.indisready,i.indislive,
                   pg_get_indexdef(i.indexrelid),r.relname
              FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid
              JOIN pg_class r ON r.oid=i.indrelid JOIN pg_namespace n ON n.oid=idx.relnamespace
             WHERE n.nspname='enterprise' AND idx.relname='one_active_turn'
        """)
        ).fetchone()
        expected_index = "CREATE UNIQUE INDEX one_active_turn ON enterprise.turns USING btree (tenant_id, session_id) WHERE (status = ANY (ARRAY['queued'::text, 'running'::text, 'waiting_input'::text]))"
        if active_index != (True, True, True, True, expected_index, "turns"):
            raise RuntimeError("schema drift: active-turn unique index differs")

        if "notebook_entries" in expected_columns:
            await self._verify_notebook_metadata(
                c,
                learning="mastery_paths" in expected_columns,
                reading="reading_materials" in expected_columns,
            )
        if "mastery_paths" in expected_columns:
            await self._verify_learning_metadata(c, reading="reading_materials" in expected_columns)
        if "reading_materials" in expected_columns:
            await self._verify_learning_metadata(c, catalog=_READING_CATALOG)
        if "session_objects" in expected_columns:
            await self._verify_learning_metadata(c, catalog=_SESSION_RESOURCES_CATALOG)
        if "maintenance_locks" in expected_columns:
            await self._verify_migration_stage(c)

    async def _verify_migration_stage(self, c):
        namespace = await (
            await c.execute("SELECT to_regnamespace('migration_stage')")
        ).fetchone()
        if namespace[0] is None:
            raise RuntimeError("schema drift: migration_stage schema is missing")
        rows = await (
            await c.execute("""
            SELECT r.relname,r.relkind,r.relrowsecurity,r.relforcerowsecurity
              FROM pg_class r JOIN pg_namespace n ON n.oid=r.relnamespace
             WHERE n.nspname='migration_stage' AND r.relkind IN ('r','p','v','m','f')
        """)
        ).fetchall()
        tables = {row[0]: row[1:] for row in rows}
        if set(tables) != set(_MIGRATION_STAGE_COLUMNS):
            raise RuntimeError("schema drift: migration_stage table set differs")
        for name, (kind, enabled, forced) in tables.items():
            if kind != "r" or enabled or forced:
                raise RuntimeError(f"schema drift: migration_stage.{name} table flags differ")
        columns = {name: {} for name in _MIGRATION_STAGE_COLUMNS}
        rows = await (
            await c.execute("""
            SELECT r.relname,a.attname,t.typname,a.attnotnull
              FROM pg_attribute a JOIN pg_class r ON r.oid=a.attrelid
              JOIN pg_namespace n ON n.oid=r.relnamespace JOIN pg_type t ON t.oid=a.atttypid
             WHERE n.nspname='migration_stage' AND r.relkind='r'
               AND a.attnum>0 AND NOT a.attisdropped
        """)
        ).fetchall()
        for table, column, kind, required in rows:
            columns[table][column] = (kind, required)
        for table, specification in _MIGRATION_STAGE_COLUMNS.items():
            expected = {
                column: (kind.removesuffix("!"), kind.endswith("!"))
                for field in specification.split()
                for column, kind in [field.split(":")]
            }
            if columns[table] != expected:
                raise RuntimeError(f"schema drift: migration_stage.{table} columns differ")

    async def _verify_notebook_metadata(self, c, *, learning=False, reading=False):
        rows = await (
            await c.execute("""
            SELECT r.relname,a.attname,a.attgenerated,a.attidentity,
                   pg_get_expr(d.adbin,d.adrelid),co.collname
              FROM pg_attribute a JOIN pg_class r ON r.oid=a.attrelid
              JOIN pg_namespace n ON n.oid=r.relnamespace
              LEFT JOIN pg_attrdef d ON d.adrelid=r.oid AND d.adnum=a.attnum
              LEFT JOIN pg_collation co ON co.oid=a.attcollation
             WHERE n.nspname='enterprise' AND r.relname IN
                   ('notebook_entries','notebook_categories','notebook_entry_categories')
               AND a.attnum>0 AND NOT a.attisdropped
        """)
        ).fetchall()
        metadata = {
            (r[0], r[1]): (r[2], r[3], " ".join(r[4].split()) if r[4] else None, r[5]) for r in rows
        }
        expected_metadata = {}
        for table, defaults in _NOTEBOOK_DEFAULTS.items():
            for field in _COLUMNS_V4[table].split():
                column, kind = field.split(":")
                expected_metadata[(table, column)] = (
                    "",
                    "d" if column == "id" else "",
                    defaults.get(column),
                    "default" if kind.removesuffix("!") == "text" else None,
                )
        expected_metadata.update(_NOTEBOOK_GENERATED)
        if learning:
            for column, values in _LEARNING_CATALOG["metadata"]["notebook_entries"].items():
                expected_metadata[("notebook_entries", column)] = tuple(values)
        if reading:
            for column, values in _READING_CATALOG["metadata"]["notebook_entries"].items():
                expected_metadata[("notebook_entries", column)] = tuple(values)
        if metadata != expected_metadata:
            raise RuntimeError(
                "schema drift: notebook generated/default/identity/collation metadata differs"
            )
        rows = await (
            await c.execute(
                """
            SELECT idx.relname,pg_get_indexdef(i.indexrelid),
                   i.indisvalid AND i.indisready AND i.indislive
              FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid
              JOIN pg_namespace n ON n.oid=idx.relnamespace
             WHERE n.nspname='enterprise' AND idx.relname = ANY(%s)
        """,
                (list(_NOTEBOOK_INDEXES),),
            )
        ).fetchall()
        actual = {name: definition for name, definition, valid in rows if valid}
        if actual != _NOTEBOOK_INDEXES:
            raise RuntimeError("schema drift: notebook query/reference indexes differ")

    async def _verify_learning_metadata(self, c, *, reading=False, catalog=None):
        catalog = catalog or _LEARNING_CATALOG
        tables = list(catalog["metadata"])
        rows = await (
            await c.execute(
                """
            SELECT r.relname,a.attname,a.attgenerated,a.attidentity,
                   pg_get_expr(d.adbin,d.adrelid),co.collname
            FROM pg_attribute a JOIN pg_class r ON r.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=r.relnamespace
            LEFT JOIN pg_attrdef d ON d.adrelid=r.oid AND d.adnum=a.attnum
            LEFT JOIN pg_collation co ON co.oid=a.attcollation
            WHERE n.nspname='enterprise' AND r.relname=ANY(%s)
              AND a.attnum>0 AND NOT a.attisdropped
        """,
                (tables,),
            )
        ).fetchall()
        actual = {
            (r[0], r[1]): [r[2], r[3], " ".join(r[4].split()) if r[4] else None, r[5]] for r in rows
        }
        expected = {
            (table, column): values
            for table, columns in catalog["metadata"].items()
            for column, values in columns.items()
        }
        if reading:
            expected.update(
                {
                    ("notebook_entries", column): values
                    for column, values in _READING_CATALOG["metadata"]["notebook_entries"].items()
                }
            )
        if actual != expected:
            raise RuntimeError(
                "schema drift: learning generated/default/identity/collation differs"
            )
        rows = await (
            await c.execute(
                """
            SELECT idx.relname,pg_get_indexdef(i.indexrelid),
                   i.indisvalid AND i.indisready AND i.indislive
            FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid
            JOIN pg_namespace n ON n.oid=idx.relnamespace
            WHERE n.nspname='enterprise' AND idx.relname=ANY(%s)
        """,
                (list(catalog["indexes"]),),
            )
        ).fetchall()
        if {name: definition for name, definition, valid in rows if valid} != catalog["indexes"]:
            raise RuntimeError("schema drift: learning query/reference indexes differ")

    async def plan(self):
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            return [v for v, _ in await self._plan(c)]

    async def verify(self):
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            await c.execute("SELECT pg_advisory_xact_lock_shared(%s)", (LOCK_ID,))
            if await self._plan(c):
                raise RuntimeError("schema migration required; run the maintenance apply command")
            await self._verify_schema(c)

    async def apply(self):
        async with await psycopg.AsyncConnection.connect(self._dsn) as c:
            await c.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
            pending = await self._plan(c)
            history = await self._history(c)
            if history:
                # 先验证已应用版本；目标 DDL 不能掩盖/修复源目录漂移。
                await self._verify_schema(c, list(history)[-1])
            if not pending:
                return
            await c.execute("CREATE SCHEMA IF NOT EXISTS enterprise")
            await c.execute(
                "CREATE TABLE IF NOT EXISTS enterprise.schema_history (version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            for version, sql in pending:
                await c.execute(sql, prepare=False)
                await c.execute(
                    "INSERT INTO enterprise.schema_history(version,checksum) VALUES(%s,%s)",
                    (version, hashlib.sha256(sql.encode()).hexdigest()),
                )
            await self._verify_schema(c)
