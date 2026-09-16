"""教学turn路径切换：租约、membership、Session偏好共用一个PG事务。"""

from collections.abc import Callable

from deeptutor.learning.contracts import PathLeaseConflictError
from deeptutor.learning.identity import sanitize_mastery_path_id
from deeptutor.learning.runtime import get_learning_runtime
from deeptutor.persistence.postgres.reading.base import SessionExecution

PathBinder = Callable[[str], None]


class PathBindingError(RuntimeError):
    """The requested path cannot be entered."""


async def rebind_active_path(
    *,
    path_id: str,
    session_id: str,
    turn_id: str,
    bind_turn: PathBinder | None,
    require_existing: bool = True,
    _scratch: bool = False,
) -> str:
    target = sanitize_mastery_path_id(path_id)
    runtime = get_learning_runtime()

    def handoff(unit):
        if require_existing and not unit.exists(target):
            raise PathBindingError(f"No mastery path {path_id!r} exists")
        unit.release_leases_for_turn(turn_id)
        unit.acquire_path_lease(target, session_id, turn_id)
        if _scratch:
            unit.bind_session(target, session_id, owns_path=True)
        # 复用1.15完整Session算法（规范化、version、typed refs、audit），不复制SQL。
        if not SessionExecution(unit).update_session_preferences(
            session_id, {"mastery_path_id": "" if _scratch else target}
        ):
            raise PathBindingError("Session is unavailable")

    try:
        await runtime.run(handoff)
    except PathLeaseConflictError as exc:
        raise PathBindingError(
            f"Mastery path {target!r} is active in another conversation"
        ) from exc
    if bind_turn is not None:
        bind_turn(target)
    return target


async def leave_active_path(*, session_id: str, turn_id: str, bind_turn: PathBinder | None) -> str:
    return await rebind_active_path(
        path_id=sanitize_mastery_path_id(session_id),
        session_id=session_id,
        turn_id=turn_id,
        bind_turn=bind_turn,
        require_existing=False,
        _scratch=True,
    )


async def remember_mode_on_session(session_id: str, mode: str) -> None:
    if not session_id or not mode:
        return
    runtime = get_learning_runtime()

    def remember(unit):
        authority = unit._authority()
        if authority.session_id != session_id:
            raise PermissionError("Session turn authority mismatch")
        return SessionExecution(unit).update_session_preferences(
            session_id, {"mastery_session_mode": mode}
        )

    if not await runtime.run(remember):
        raise PathBindingError("Session is unavailable")


__all__ = [
    "PathBindingError",
    "leave_active_path",
    "rebind_active_path",
    "remember_mode_on_session",
]
