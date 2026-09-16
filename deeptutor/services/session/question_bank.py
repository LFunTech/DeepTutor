"""题库 Store 共用的中立查询值对象与领域错误。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

ASSESSMENT_SOURCES = frozenset({"deep_question", "mastery_path", "immersive_reading", "book"})
SCORE_TRENDS = frozenset({"new", "improved", "declined", "unchanged"})
MAX_QUESTION_BANK_CURSOR_LENGTH = 2048


class QuestionBankCursorError(ValueError):
    """游标损坏、过大或与当前查询语义不匹配。"""


class QuestionBankVersionConflict(RuntimeError):
    """客户端的 expected_version 已过期。"""

    def __init__(self, entity: str, entity_id: int, expected: int, actual: int):
        super().__init__(
            f"{entity} {entity_id} version conflict: expected {expected}, actual {actual}"
        )
        self.entity = entity
        self.entity_id = entity_id
        self.expected = expected
        self.actual = actual


class QuestionBankReferenceConflict(RuntimeError):
    """删除或改写会破坏题库的受保护引用。"""


@dataclass(frozen=True, slots=True)
class QuestionBankQuery:
    """SQLite 与 PostgreSQL 可共同消费的纯查询值对象。"""

    category_id: int | None = None
    uncategorized: bool = False
    bookmarked: bool | None = None
    is_correct: bool | None = None
    source: str = ""
    material_id: str = ""
    section_id: str = ""
    resolved: bool | None = None
    score_trend: str = ""
    search: str = ""
    session_id: str | None = None
    session_ids: Sequence[str] | None = None
    sort: str = "recent"
    limit: int = 50
    offset: int = 0
    # None 保留原 offset 返回；空串显式开启稳定游标的第一页。
    cursor: str | None = None

    def normalized(self) -> "QuestionBankQuery":
        cursor = self.cursor
        if cursor is not None:
            if not isinstance(cursor, str):
                raise QuestionBankCursorError("question-bank cursor must be a string")
            if len(cursor) > MAX_QUESTION_BANK_CURSOR_LENGTH:
                raise QuestionBankCursorError("question-bank cursor is too large")
            if int(self.offset) != 0:
                raise QuestionBankCursorError("offset cannot be combined with a cursor")
        return QuestionBankQuery(
            category_id=self.category_id,
            uncategorized=bool(self.uncategorized and self.category_id is None),
            bookmarked=self.bookmarked,
            is_correct=self.is_correct,
            source=(self.source or "").strip()
            if (self.source or "").strip() in ASSESSMENT_SOURCES
            else "",
            material_id=(self.material_id or "").strip(),
            section_id=(self.section_id or "").strip(),
            resolved=self.resolved,
            score_trend=(self.score_trend or "").strip()
            if (self.score_trend or "").strip() in SCORE_TRENDS
            else "",
            search=(self.search or "").strip()[:200],
            session_id=self.session_id,
            session_ids=None if self.session_ids is None else tuple(self.session_ids),
            sort="oldest" if self.sort == "oldest" else "recent",
            limit=max(1, min(int(self.limit), 500)),
            offset=max(0, int(self.offset)),
            cursor=cursor,
        )


__all__ = [
    "ASSESSMENT_SOURCES",
    "MAX_QUESTION_BANK_CURSOR_LENGTH",
    "QuestionBankCursorError",
    "QuestionBankQuery",
    "QuestionBankReferenceConflict",
    "QuestionBankVersionConflict",
    "SCORE_TRENDS",
]
