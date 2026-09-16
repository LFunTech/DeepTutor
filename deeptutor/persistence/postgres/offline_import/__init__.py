"""受控离线 SQLite/PocketBase → PostgreSQL 导入工具基础。

本包只提供只读源制品检查与计划能力；真正写入 PG staging/正式表由后续
切片实现。业务运行路径不得导入旧 SQLite Store 或触发运行时自动迁移。
"""

from __future__ import annotations

from typing import Any

from .chat_sqlite import SQLiteChatHistoryImporter
from .cutover import (
    CutoverCheckReport,
    CutoverReleaseRequest,
    OfflineCutoverCoordinator,
    RollbackCheckRequest,
)
from .id_mapping import MigrationIdAllocator, TypedReferenceRewriter
from .learning_reading_sqlite import SQLiteLearningReadingImporter
from .planner import ImportPlanReport, plan_sqlite_import, source_check_manifest
from .pocketbase_export import PocketBaseExportError, create_pocketbase_source_export
from .pocketbase_import import PocketBaseOfflineImporter
from .registry import ReferenceRegistry, get_reference_registry
from .runtime_sqlite import SQLiteRuntimeProjectionImporter
from .sqlite_snapshot import SourceSnapshotResult, create_sqlite_source_snapshot
from .stage import MigrationStageRepository, PromotionStep
from .verify_report import OfflineImportVerifier, OfflineVerifyReport


def __getattr__(name: str) -> Any:
    if name == "SQLiteMatrixStoreImporter":
        # Matrix import is optional for the default PG-only runtime.  Only the
        # offline Matrix importer needs matrix-nio/vodozemac, so defer this
        # import until that symbol is explicitly requested.
        from .matrix_sqlite import SQLiteMatrixStoreImporter

        return SQLiteMatrixStoreImporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CutoverCheckReport",
    "CutoverReleaseRequest",
    "ImportPlanReport",
    "MigrationStageRepository",
    "MigrationIdAllocator",
    "OfflineImportVerifier",
    "OfflineCutoverCoordinator",
    "OfflineVerifyReport",
    "PocketBaseExportError",
    "PocketBaseOfflineImporter",
    "PromotionStep",
    "ReferenceRegistry",
    "RollbackCheckRequest",
    "SourceSnapshotResult",
    "SQLiteChatHistoryImporter",
    "SQLiteLearningReadingImporter",
    "SQLiteMatrixStoreImporter",
    "SQLiteRuntimeProjectionImporter",
    "TypedReferenceRewriter",
    "create_pocketbase_source_export",
    "create_sqlite_source_snapshot",
    "get_reference_registry",
    "plan_sqlite_import",
    "source_check_manifest",
]
