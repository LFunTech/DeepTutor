"""Session 领域算法只有一份；同步/异步 driver 只解释封闭的语句步骤。"""

from dataclasses import dataclass
import json
import time
from uuid import uuid4

from deeptutor.services.session.workspace_preferences import upgrade_workspace_preferences

from .session_references import references
from .session_statements import SessionStatement as S


@dataclass(frozen=True)
class Step:
    statement: S
    params: tuple
    many: bool = False


def normalized_creation(title=None, session_id=None):
    sid = session_id or f"unified_{uuid4().hex}"
    if not isinstance(sid, str) or not sid.strip() or len(sid) > 255:
        raise ValueError("invalid session ID")
    if title is not None and not isinstance(title, str):
        raise ValueError("invalid session title")
    return sid, (title or "New conversation").strip()[:100] or "New conversation"


def require_session(row, *, allow_deleting=False):
    if row is None:
        raise ValueError("Session not found")
    if row["deleting"] and not allow_deleting:
        raise RuntimeError("Session is deleting; dispatch is blocked")
    return row


def check_version(row, expected_version):
    if expected_version is not None:
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("Invalid session version")
        if row["version"] != expected_version:
            raise ValueError("Session version conflict")


def summary_payload(row):
    payload = {
        key: value
        for key, value in row.items()
        if key
        not in (
            "tenant_id",
            "owner_id",
            "summary",
            "incarnation",
            "deletion_token",
            "unresolved_dependencies",
        )
    }
    payload.update(
        session_id=row["id"],
        compressed_summary=row["summary"],
        summary_up_to_msg_id=row["summary_up_to_msg_id"] or 0,
    )
    return payload


def audit(action, target, result):
    return Step(S.AUDIT, (action, str(target), uuid4().hex, result))


def create_session(title=None, session_id=None, preferences=None):
    sid, title = normalized_creation(title, session_id)
    yield Step(S.CREATE_ROW, (sid, title))
    yield audit("session.create", sid, "created")
    if preferences is not None:
        yield from update_preferences(sid, preferences)
    row = yield Step(S.SUMMARY_ROW, (sid,))
    return summary_payload(row)


def update_title(session_id, title, expected_version=None):
    row = yield Step(S.LOCK_ROW, (session_id,))
    if row is None or row["deleting"]:
        return False
    check_version(row, expected_version)
    _, title = normalized_creation(title, session_id)
    yield Step(S.UPDATE_TITLE, (session_id, title, str(time.time())))
    yield audit("session.update", session_id, "updated")
    return True


def update_preferences(session_id, preferences, expected_version=None):
    if not isinstance(preferences, dict):
        raise ValueError("preferences must be an object")
    row = yield Step(S.LOCK_ROW, (session_id,))
    if row is None:
        return False
    require_session(row)
    check_version(row, expected_version)
    # 复用同一白名单/shape 算法；这里只将已存在领域引用转为固定 GET token。
    from .session_validation import validate_reference_shape

    validate_reference_shape(preferences)
    merged = upgrade_workspace_preferences({**row["preferences"], **preferences})
    refs = set(references(merged))
    for key, value in refs:
        op = {
            "mastery_path_id": S.MASTERYPATH,
            "reading_workspace_id": S.READING_WORKSPACE,
            "reading_material_id": S.READING_MATERIAL,
        }[key]
        if not (yield Step(op, (value,))):
            raise ValueError("session reference unavailable in this scope")
    parent = str(merged.get("parent_session_id") or "").strip() or None
    cursor, seen = parent, {session_id}
    while cursor:
        if cursor in seen:
            raise ValueError("Session parent cycle")
        seen.add(cursor)
        ancestor = yield Step(S.GET_ROW, (cursor,))
        if not ancestor or ancestor["deleting"]:
            raise ValueError("Parent session not found")
        cursor = ancestor["parent_session_id"]
    leaf = row["active_leaf_id"]
    if "selected_branches" in preferences:
        branches = preferences["selected_branches"]
        if not isinstance(branches, dict):
            raise ValueError("selected_branches must be a mapping")
        for parent_id, child_id in branches.items():
            child = yield Step(S.GET_MESSAGE, (session_id, str(int(child_id))))
            expected_parent = (
                None if str(parent_id) in ("root", "null", "None", "0") else int(parent_id)
            )
            if not child or child["parent_message_id"] != expected_parent:
                raise ValueError("Invalid selected branch parent/child")
        children = {}
        for message in (yield Step(S.MESSAGE_PARENTS, (session_id,), many=True)):
            children.setdefault(message["parent_message_id"], []).append(message["id"])
        leaf = None
        while children.get(leaf):
            selected = (
                next((branches[k] for k in ("root", "null", "None", "0") if k in branches), None)
                if leaf is None
                else branches.get(str(leaf))
            )
            leaf = int(selected) if selected is not None else children[leaf][-1]
        merged["active_leaf_id"] = leaf
    if "active_leaf_id" in preferences:
        leaf = preferences["active_leaf_id"]
        if leaf is not None and not (yield Step(S.GET_MESSAGE, (session_id, str(int(leaf))))):
            raise ValueError("Active leaf not found in session")
    encoded = json.dumps(merged, ensure_ascii=False, allow_nan=False)
    yield Step(
        S.UPDATE_PREFERENCES,
        (
            session_id,
            encoded,
            parent or "",
            str(bool(merged.get("pinned"))),
            str(bool(merged.get("archived"))),
            "" if leaf is None else str(leaf),
            str(time.time()),
        ),
    )
    yield Step(S.CLEAR_PREFERENCE_REFS, (session_id,), many=True)
    for key, target in refs:
        yield Step(S.RECORD_PREFERENCE_REF, (session_id, key, target))
    yield audit("session.preferences", session_id, "updated")
    return True


def delete_session(session_id, deletion_token=None):
    from deeptutor.services.session.question_bank import QuestionBankReferenceConflict

    from .session_validation import validate_reference_shape

    row = yield Step(S.LOCK_ROW, (session_id,))
    if row is None:
        return False
    if row["unresolved_dependencies"]:
        raise QuestionBankReferenceConflict(
            "Session external dependency requires an upstream authority provider"
        )
    if deletion_token is not None and str(row["deletion_token"]) != str(deletion_token):
        raise RuntimeError("Session deletion token/generation changed")
    try:
        validate_reference_shape(row["preferences"])
    except ValueError as exc:
        raise QuestionBankReferenceConflict("Session external dependency is not supported") from exc
    if (yield Step(S.UNREGISTERED_ATTACHMENTS, (session_id,))):
        raise QuestionBankReferenceConflict("Message external dependency is not registered")
    if (yield Step(S.ACTIVE_TURN, (session_id,))):
        raise RuntimeError("Session has active execution; confirm it is stopped before deletion")
    if (yield Step(S.FOLLOWUP_REF, (session_id,))):
        raise QuestionBankReferenceConflict(
            "Session is still used as a question-bank follow-up; clear the reference first"
        )
    yield Step(S.QUEUE_SESSION_OBJECTS, (session_id, str(row["incarnation"])), many=True)
    yield Step(S.TOMBSTONE_SESSION, (session_id,), many=True)
    yield Step(S.DETACH_CHILDREN, (session_id,), many=True)
    yield Step(S.DELETE_ROW, (session_id,))
    yield audit("session.delete", session_id, "deleted")
    return True
