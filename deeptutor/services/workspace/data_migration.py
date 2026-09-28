"""Fail-closed workspace data migration facade for PostgreSQL-only runtimes.

Upstream workspace data migration is built around legacy local SQLite snapshots.
DeepTutor Enterprise does not expose SQLite as a supported business runtime, so
these public functions intentionally refuse migration/export requests until a
PostgreSQL-native migration path is specified and implemented.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

from deeptutor.services.workspace.models import WorkspaceError

_UNAVAILABLE = (
    "Workspace data migration/export is unavailable in the PostgreSQL-only runtime. "
    "Use controlled offline import tooling for historical SQLite data."
)


def _unavailable() -> NoReturn:
    raise WorkspaceError(_UNAVAILABLE)


def assert_no_pending_recovery() -> None:
    """No legacy migration operations can be pending in this runtime."""
    return None


def operations() -> list[dict]:
    return []


def discover(source_workspace_id: str = "") -> dict:
    _unavailable()


def preview(source_workspace_id: str, target_workspace_id: str, features: list[str]) -> dict:
    _unavailable()


def migrate_data(source_workspace_id: str, target_workspace_id: str, features: list[str]) -> dict:
    _unavailable()


def export_data(
    source_workspace_id: str,
    features: list[str],
    *,
    include_historical: bool = False,
) -> dict:
    _unavailable()


def recover_operation(operation_id: str) -> dict:
    _unavailable()


def export_path(operation_id: str) -> Path:
    _unavailable()
