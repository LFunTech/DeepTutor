"""Workspace write activity guards without database-backed runtime state.

Enterprise runtimes are PostgreSQL-only and must not reintroduce SQLite as a
runtime lock or cache.  The public API mirrors upstream's workspace activity
module, but the lock is a process/file-system coordination primitive rather
than a database connection.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import threading
from typing import IO, Iterator

from deeptutor.services.workspace.models import WorkspaceError

try:  # POSIX deployment path (Linux/macOS).
    import fcntl
except ImportError:  # pragma: no cover - Windows is fail-closed below.
    fcntl = None  # type: ignore[assignment]


_tenant_process_lock = threading.RLock()


class _ProcessActivityHandle:
    def __init__(self) -> None:
        if not _tenant_process_lock.acquire(blocking=False):
            raise WorkspaceError(
                "Workspace data is busy. Wait for active requests and tasks before retrying."
            )
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            _tenant_process_lock.release()


def _activity_lock_path():
    from deeptutor.multi_user.paths import get_account_path_service

    try:
        return get_account_path_service().ensure_runtime_state_dir() / "workspace-activity.lock"
    except (PermissionError, RuntimeError):
        # Tenant-scoped enterprise requests deliberately have no local
        # filesystem PathService, and enterprise process probes forbid local
        # authority IO.  Use an in-process guard there; enterprise PG stores and
        # executor leases provide the durable cross-process guarantees.
        return None


def acquire_activity(*, exclusive: bool = False) -> IO[str] | _ProcessActivityHandle:
    """Acquire a non-blocking workspace activity lock.

    Shared locks guard ordinary writers; exclusive locks guard maintenance
    operations such as moving workspace storage.  The returned file handle owns
    the lock and releases it on ``close()``.
    """
    path = _activity_lock_path()
    if path is None:
        return _ProcessActivityHandle()
    if fcntl is None:
        raise WorkspaceError(
            "Workspace activity locking requires POSIX file locks in this runtime."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(handle.fileno(), flags | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate()
        handle.write("exclusive\n" if exclusive else "shared\n")
        handle.flush()
    except OSError as exc:
        handle.close()
        raise WorkspaceError(
            "Workspace data is busy. Wait for active requests and tasks before retrying."
        ) from exc
    except BaseException:
        handle.close()
        raise
    return handle


@contextmanager
def data_activity(*, exclusive: bool = False) -> Iterator[None]:
    handle = acquire_activity(exclusive=exclusive)
    try:
        yield
    finally:
        handle.close()


def workspace_writer(function):
    """Guard workspace writes and reject archived workspace mutation."""

    @wraps(function)
    async def guarded(*args, **kwargs):
        from deeptutor.services.workspace.context import (
            get_workspace_scope,
            resolve_workspace_scope,
        )

        scope = get_workspace_scope()
        if scope is not None and resolve_workspace_scope(scope.workspace_id).archived:
            raise WorkspaceError("Restore this workspace before changing its data.")
        with data_activity():
            return await function(*args, **kwargs)

    return guarded


class WorkspaceActivityMiddleware:
    """Close a request-scoped activity handle if an upstream caller installed one."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        finally:
            handle = scope.get("state", {}).pop("workspace_activity", None)
            if handle is not None:
                handle.close()
