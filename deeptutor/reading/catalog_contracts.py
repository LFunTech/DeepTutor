"""PG 阅读目录的中立 CAS、分页和事务内资源计划合同。"""

from dataclasses import dataclass
from typing import Generic, TypeVar

from .models import ReadingError

T = TypeVar("T")


class ReadingConflictError(ReadingError):
    def __init__(self, expected, actual):
        self.expected, self.actual = expected, actual
        super().__init__(f"reading version conflict: expected {expected}, actual {actual}")


class ReadingReferenceError(ReadingError):
    pass


class ReadingPageRequired(ReadingError):
    """旧完整结果超过 500 条时显式要求调用分页入口，不返回被截断的 DTO。"""


@dataclass(frozen=True, slots=True)
class ReadingPage(Generic[T]):
    items: tuple[T, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceSummaryRecord:
    workspace_id: str
    title: str
    description: str
    active_material_id: str | None
    created_at: float
    updated_at: float
    version: int
    tab_count: int


@dataclass(frozen=True, slots=True)
class MembershipRecord:
    material_id: str
    workspace_id: str
    title: str


@dataclass(frozen=True, slots=True)
class ContentDeletionPlan:
    """只在 locked_content 的同一 unit 内有效，不是提交后文件删除许可。"""

    material_id: str
    content_id: str
    material_version: int
    reference_count: int

    @property
    def last_reference(self):
        return self.reference_count == 1
