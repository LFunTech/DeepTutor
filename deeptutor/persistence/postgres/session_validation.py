"""明确机器引用形状；不把普通聊天正文中的词语解释成资源授权。"""

from .session_references import REFERENCE_TABLES, SNAPSHOT_REFERENCE_KEYS

EXTERNAL_KEYS = frozenset(
    {
        "attachments",
        "attachment_ids",
        "course_id",
        "mastery_path_id",
        "reading_workspace_id",
        "reading_material_id",
        "material_id",
        "kb_name",
        "kb_id",
        "knowledge_base",
        "notebook_id",
        "notebook_ids",
        "learning_state",
        "quiz",
        "quiz_result",
        "question_bank",
        "external_dependencies",
        "generated_files",
        "file_id",
        "file_ids",
    }
)


def validate_reference_shape(value, *, allow_snapshot_attachments=False):
    def is_source_citation_path(path):
        return any(
            item == "sources" and index + 1 < len(path) and isinstance(path[index + 1], int)
            for index, item in enumerate(path)
        )

    def is_turn_event_metadata_path(path):
        return bool(path) and isinstance(path[0], int) and "metadata" in path

    def walk(node, path=()):
        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, (*path, index))
        elif isinstance(node, dict):
            for key, item in node.items():
                canonical = (
                    SNAPSHOT_REFERENCE_KEYS.get(key, key)
                    if path and path[-1] == "request_snapshot"
                    else key
                )
                if key == "request_snapshot" and not isinstance(item, dict):
                    raise ValueError("request_snapshot must be an object")
                if (
                    key == "attachments"
                    and path == ("request_snapshot",)
                    and allow_snapshot_attachments
                ):
                    if type(item) is not list or any(type(a) is not dict for a in item):
                        raise ValueError("snapshot attachments must be a list of objects")
                    # 这里只允许形状，调用方仍必须在同一事务验证/登记每个对象。
                    walk(item, (*path, key))
                elif canonical in REFERENCE_TABLES and item:
                    if type(item) is not str:
                        raise ValueError("invalid typed session reference")
                elif (
                    key in EXTERNAL_KEYS
                    and item
                    and key not in {"quiz", "quiz_result", "question_bank"}
                    and not (key == "kb_name" and is_source_citation_path(path))
                    and not (key == "kb_name" and is_turn_event_metadata_path(path))
                ):
                    raise ValueError("session dependency lacks an authority provider: " + key)
                elif isinstance(item, (dict, list)):
                    walk(item, (*path, key))

    walk(value)


def snapshot_attachments(metadata):
    """仅在 metadata 通过上述 shape 校验之后取真实快照路径。"""
    if not isinstance(metadata, dict):
        return []
    return metadata.get("request_snapshot", {}).get("attachments", [])
