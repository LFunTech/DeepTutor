"""学习领域中立错误和值契约；不导入文件/SQLite runtime。"""

from dataclasses import dataclass
from typing import Any

from deeptutor.learning.models import InteractionStatus, MasteryPathLease

_ACTIVE_INTERACTION_STATES = (
    InteractionStatus.REGISTERED.value,
    InteractionStatus.AWAITING_INPUT.value,
    InteractionStatus.ANSWERED.value,
)
_ALLOWED_INTERACTION_TRANSITIONS: dict[InteractionStatus, frozenset[InteractionStatus]] = {
    InteractionStatus.REGISTERED: frozenset(InteractionStatus),
    InteractionStatus.AWAITING_INPUT: frozenset(
        {
            InteractionStatus.AWAITING_INPUT,
            InteractionStatus.ANSWERED,
            InteractionStatus.GRADED,
            InteractionStatus.ABANDONED,
        }
    ),
    InteractionStatus.ANSWERED: frozenset(
        {
            InteractionStatus.ANSWERED,
            InteractionStatus.GRADED,
            InteractionStatus.ABANDONED,
        }
    ),
    InteractionStatus.GRADED: frozenset({InteractionStatus.GRADED}),
    InteractionStatus.ABANDONED: frozenset({InteractionStatus.ABANDONED}),
}


class LearningStoreError(RuntimeError):
    """Base error for durable mastery state operations."""


class LearningConflictError(LearningStoreError):
    """Raised when a stale aggregate revision attempts to overwrite a path."""

    def __init__(self, path_id: str, expected: int, actual: int) -> None:
        self.path_id = path_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Mastery path {path_id!r} changed concurrently "
            f"(expected revision {expected}, current revision {actual})"
        )


class PathLeaseConflictError(LearningStoreError):
    """Raised when another turn already owns a path's mutation lease."""

    def __init__(self, lease: MasteryPathLease) -> None:
        self.lease = lease
        super().__init__(
            f"Mastery path {lease.path_id!r} is active in session {lease.session_id!r} "
            f"(turn {lease.turn_id!r})"
        )


class LearningPaginationRequired(LearningStoreError):
    """兼容 list 超过 1000 条；调用有界 page 接口继续读取。"""


class LearningReferenceError(LearningStoreError):
    """来源不存在、已退休或正被其它资源引用。"""


@dataclass(frozen=True)
class LearningPage:
    items: list[Any]
    next_cursor: str | None
