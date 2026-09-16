"""现已存在 PG 权威的 typed 引用；外部 notebook/KB/course 不冒充题库 ID。"""

REFERENCE_TABLES = {
    "mastery_path_id": ("mastery_paths", "path_id"),
    "reading_workspace_id": ("reading_workspaces", "workspace_id"),
    "reading_material_id": ("reading_materials", "material_id"),
}


# 仅 request_snapshot 对象的真实消费者字段；持久 JSON 保持原拼写。
SNAPSHOT_REFERENCE_KEYS = {
    "masteryPathId": "mastery_path_id",
    "readingWorkspaceId": "reading_workspace_id",
    "readingMaterialId": "reading_material_id",
}


def references(value, *, _snapshot=False):
    if isinstance(value, list):
        for item in value:
            yield from references(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            canonical = SNAPSHOT_REFERENCE_KEYS.get(key, key) if _snapshot else key
            if canonical in REFERENCE_TABLES and item:
                if type(item) is not str:
                    raise ValueError("invalid typed reference ID")
                yield canonical, item
            elif isinstance(item, (dict, list)):
                yield from references(item, _snapshot=key == "request_snapshot")


async def record_references(store, c, session_id, source_kind, source_id, value, *, replace=False):
    if replace:
        await c.execute(
            "DELETE FROM enterprise.session_references WHERE tenant_id=%s AND owner_id=%s AND session_id=%s AND source_kind=%s AND source_id=%s",
            (*store._owner, session_id, source_kind, str(source_id)),
        )
    for key, target in set(references(value)):
        await c.execute(
            "INSERT INTO enterprise.session_references(tenant_id,owner_id,session_id,source_kind,source_id,kind,target_id) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (*store._owner, session_id, source_kind, str(source_id), key, target),
        )
