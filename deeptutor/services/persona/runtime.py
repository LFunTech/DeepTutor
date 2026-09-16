"""Runtime selection for local-dev vs externalized persona services."""

from __future__ import annotations

import inspect
from typing import Any

from deeptutor.core.providers import get_providers
from deeptutor.runtime.data_gate import RuntimeMode
from deeptutor.services.persona.externalized import ExternalizedPersonaService
from deeptutor.services.persona.service import PersonaService, get_persona_service
from deeptutor.services.skill.runtime import _resolve_object_store, _resolve_scoped_store


def get_runtime_persona_service() -> PersonaService | ExternalizedPersonaService:
    """Return the active persona service for this request/scope."""

    providers = get_providers()
    if providers is not None:
        store = _resolve_scoped_store(providers.store)
        object_store = _resolve_object_store(providers.object_store)
        if store is not None and object_store is not None:
            return ExternalizedPersonaService(store, object_store)
    if RuntimeMode.from_environ().production:
        raise RuntimeError("production persona provider requires PostgreSQL + ObjectStore")
    return get_persona_service()


async def call_persona_service(service: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    result = getattr(service, method)(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


__all__ = ["call_persona_service", "get_runtime_persona_service"]
