"""PG 题库查询过滤与有界稳定游标的纯辅助函数。"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from typing import Any

from deeptutor.services.session.question_bank import QuestionBankCursorError, QuestionBankQuery

_ASCII_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ASCII_LOWER = "abcdefghijklmnopqrstuvwxyz"


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _ascii_fold(value: str) -> str:
    """匹配 SQLite ``NOCASE``：只折叠 ASCII，非 ASCII 保持精确。"""
    return value.translate(str.maketrans(_ASCII_UPPER, _ASCII_LOWER))


def _query_fingerprint(query: QuestionBankQuery) -> str:
    """绑定游标的排序和全部过滤语义，不包含页长及 offset。"""
    session_ids = (
        None
        if query.session_ids is None
        else sorted({str(session_id) for session_id in query.session_ids})
    )
    payload = {
        "category_id": query.category_id,
        "uncategorized": query.uncategorized,
        "bookmarked": query.bookmarked,
        "is_correct": query.is_correct,
        "source": query.source,
        "material_id": query.material_id,
        "section_id": query.section_id,
        "resolved": query.resolved,
        "score_trend": query.score_trend,
        "search": query.search,
        "session_id": query.session_id,
        "session_ids": session_ids,
        "sort": query.sort,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _cursor_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError from exc
    if not math.isfinite(number):
        raise ValueError
    return number


def _cursor_id(value: Any) -> int:
    if type(value) is not int or not 0 < value <= 9_223_372_036_854_775_807:
        raise ValueError
    return value


def encode_cursor(
    query: QuestionBankQuery,
    *,
    boundary_created_at: float,
    boundary_id: int,
    after_created_at: float,
    after_id: int,
    fence_id: int | None = None,
) -> str:
    payload = {
        "v": 1,
        "f": _query_fingerprint(query),
        "b": [boundary_created_at, boundary_id],
        "a": [after_created_at, after_id],
        "x": boundary_id if fence_id is None else fence_id,
    }
    raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(query: QuestionBankQuery) -> tuple[float, int, float, int, int]:
    cursor = query.cursor
    if not cursor:
        raise QuestionBankCursorError("question-bank cursor is empty")
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(cursor + padding, altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or set(payload) != {"v", "f", "b", "a", "x"}:
            raise ValueError
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError
        if payload["f"] != _query_fingerprint(query):
            if payload.get("f") != _query_fingerprint(query):
                raise QuestionBankCursorError(
                    "question-bank cursor does not match the current filter and sort"
                )
        boundary, after = payload["b"], payload["a"]
        if not (
            isinstance(boundary, list)
            and isinstance(after, list)
            and len(boundary) == len(after) == 2
        ):
            raise ValueError
        return (
            _cursor_number(boundary[0]),
            _cursor_id(boundary[1]),
            _cursor_number(after[0]),
            _cursor_id(after[1]),
            _cursor_id(payload["x"]),
        )
    except QuestionBankCursorError:
        raise
    except (OverflowError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise QuestionBankCursorError("invalid question-bank cursor") from exc


def question_bank_filters(query: QuestionBankQuery) -> tuple[str, str, list[Any]]:
    joins: list[str] = []
    conditions: list[str] = []
    params: list[Any] = []
    if query.category_id is not None:
        joins.append(
            " INNER JOIN enterprise.notebook_entry_categories ec"
            " ON ec.tenant_id=n.tenant_id AND ec.owner_id=n.owner_id AND ec.entry_id=n.id"
        )
        conditions.append("ec.category_id=%s")
        params.append(query.category_id)
    elif query.uncategorized:
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM enterprise.notebook_entry_categories ec"
            " WHERE ec.tenant_id=n.tenant_id AND ec.owner_id=n.owner_id"
            " AND ec.entry_id=n.id)"
        )
    for column, value in (
        ("bookmarked", query.bookmarked),
        ("is_correct", query.is_correct),
        ("resolved", query.resolved),
    ):
        if value is not None:
            conditions.append(f"n.{column}=%s")
            params.append(bool(value))
    for column, value in (
        ("source", query.source),
        ("material_id", query.material_id),
        ("section_id", query.section_id),
        ("score_trend", query.score_trend),
    ):
        if value:
            conditions.append(f"n.{column}=%s")
            params.append(value)
    if query.session_id is not None:
        conditions.append("n.session_id=%s")
        params.append(query.session_id)
    if query.session_ids is not None:
        conditions.append("n.session_id=ANY(%s)")
        params.append(list(query.session_ids))
    if query.search:
        needle = f"%{escape_like(_ascii_fold(query.search))}%"
        folded = "translate({column},'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"
        conditions.append(
            f"({folded.format(column='n.question')} LIKE %s ESCAPE '\\'"
            f" OR {folded.format(column='n.user_answer')} LIKE %s ESCAPE '\\'"
            f" OR {folded.format(column='n.correct_answer')} LIKE %s ESCAPE '\\'"
            f" OR {folded.format(column='n.explanation')} LIKE %s ESCAPE '\\')"
        )
        params.extend([needle] * 4)
    return "".join(joins), (" AND " + " AND ".join(conditions)) if conditions else "", params


__all__ = ["decode_cursor", "encode_cursor", "escape_like", "question_bank_filters"]
