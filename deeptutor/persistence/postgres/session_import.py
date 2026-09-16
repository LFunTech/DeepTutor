"""浏览器手动导入的有限纯验证；绝不读取旧库或本地 CLI 历史。"""

from copy import deepcopy
import json
import math
import re

MAX_IMPORT_MESSAGES = 10_000
MAX_IMPORT_BYTES = 4 * 1024 * 1024


def validate_import(session_id, title, created_at, updated_at, preferences, messages):
    if type(session_id) is not str or not re.fullmatch(
        r"imported_[A-Za-z0-9_-]{1,246}", session_id
    ):
        raise ValueError("invalid imported session ID")
    if title is not None and type(title) is not str:
        raise ValueError("invalid imported title")
    if type(messages) is not list or len(messages) > MAX_IMPORT_MESSAGES:
        raise ValueError("import message limit exceeded")
    preferences = {} if preferences is None else preferences
    if type(preferences) is not dict or type(preferences.get("import", {})) is not dict:
        raise ValueError("invalid import preferences")
    try:
        encoded = json.dumps([preferences, messages], ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid import JSON") from exc
    if len(encoded.encode("utf8")) > MAX_IMPORT_BYTES:
        raise ValueError("import byte limit exceeded")

    def timestamp(value):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("import timestamp must be finite")
        return float(value)

    created_at, updated_at = timestamp(created_at), timestamp(updated_at)
    prepared = []
    for message in messages:
        if type(message) is not dict or message.get("role") not in {"user", "assistant"}:
            raise ValueError("unsupported imported message role")
        if (
            type(message.get("content", "")) is not str
            or type(message.get("metadata", {})) is not dict
        ):
            raise ValueError("invalid imported message content/metadata")
        if set(message) - {"role", "content", "metadata", "created_at"}:
            raise ValueError("unsupported imported message fields")
        prepared.append(
            {
                "role": message["role"],
                "content": message.get("content", ""),
                "metadata": deepcopy(message.get("metadata", {})),
                "created_at": timestamp(
                    created_at if message.get("created_at") is None else message["created_at"]
                ),
            }
        )
    return (
        (title or "").strip()[:100] or "Imported conversation",
        created_at,
        updated_at,
        deepcopy(preferences),
        prepared,
    )


def merge_import_attribution(current, incoming):
    prefs = deepcopy(current)
    meta = dict(prefs.get("import") or {})
    changed = False
    for key in ("agent_id", "agent_name", "source_cwd"):
        value = incoming.get("import", {}).get(key)
        if value and meta.get(key) != value:
            meta[key], changed = value, True
    if changed:
        prefs["import"] = meta
    return prefs, changed
