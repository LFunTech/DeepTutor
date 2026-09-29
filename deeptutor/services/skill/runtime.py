"""Runtime selection for local-dev vs externalized skill services."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from deeptutor.core.providers import get_providers
from deeptutor.runtime.data_gate import RuntimeMode
from deeptutor.services.skill.externalized import ExternalizedSkillService
from deeptutor.services.skill.service import BUILTIN_SKILLS_ROOT, get_skill_service


def _resolve_scoped_store(value: Any) -> Any | None:
    if value is None:
        return None
    if hasattr(value, "db") and hasattr(value, "scope"):
        return value
    getter = getattr(value, "get", None)
    if callable(getter):
        return getter()
    return value


def _resolve_object_store(value: Any) -> Any | None:
    if value is None:
        return None
    if hasattr(value, "put_bytes") and hasattr(value, "get_bytes"):
        return value
    getter = getattr(value, "get", None)
    if callable(getter):
        candidate = getter()
        if hasattr(candidate, "put_bytes") and hasattr(candidate, "get_bytes"):
            return candidate
    return value


def get_runtime_skill_service(*, builtin_root: Path | None = BUILTIN_SKILLS_ROOT) -> Any:
    """Return the active skill service for this request/scope.

    When a PG store and S3-compatible ObjectStore are bound, dynamic skills are
    read/written through PG metadata + ObjectStore.  Local filesystem skills
    remain only for local-dev/no-provider execution; production mode fails
    closed instead of silently falling back to ``data/user/workspace/skills``.
    """

    providers = get_providers()
    if providers is not None:
        if providers.skill_service_factory is not None:
            if not callable(providers.skill_service_factory):
                raise RuntimeError("configured skill service unavailable")
            service = providers.skill_service_factory()
            if service is None:
                raise RuntimeError("configured skill service unavailable")
            return service
        store = _resolve_scoped_store(providers.store)
        object_store = _resolve_object_store(providers.object_store)
        if store is not None and object_store is not None:
            return ExternalizedSkillService(store, object_store, builtin_root=builtin_root)
    if RuntimeMode.from_environ().production:
        raise RuntimeError("production skill provider requires PostgreSQL + ObjectStore")
    return get_skill_service()


def skill_sources(*, workspace_id: str = "", builtin_root: Path | None = BUILTIN_SKILLS_ROOT):
    """Return skill catalogs visible to workspace/resource callers.

    Older workspace code expected a ``skill_sources`` helper that yielded
    ``(service, allowed_ids, source_label)`` tuples.  The runtime now resolves a
    single request-scoped skill service through ``get_runtime_skill_service``;
    keep this small compatibility seam so workspace resource validation and
    legacy tests do not reach into local user skill folders directly.
    """

    del workspace_id
    yield (get_runtime_skill_service(builtin_root=builtin_root), None, "runtime")


async def call_skill_service(service: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    result = getattr(service, method)(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


__all__ = ["call_skill_service", "get_runtime_skill_service", "skill_sources"]
