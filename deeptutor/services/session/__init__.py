"""Unified repository-backed session management."""

from .protocol import QuestionBankRepository, SessionStoreProtocol
from .question_bank import (
    QuestionBankCursorError,
    QuestionBankQuery,
    QuestionBankReferenceConflict,
    QuestionBankVersionConflict,
)

# 兼容符号仅在显式访问时加载；中立question_bank/protocol不再带入SQLite runtime。
_LEGACY_EXPORTS = {
    "get_sqlite_session_store": ".sqlite_store",
    "make_imported_session_id": ".import_ids",
    "TurnRuntimeManager": ".turn_runtime",
    "get_turn_runtime_manager": ".turn_runtime",
}


def __getattr__(name):
    module_name = _LEGACY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LEGACY_EXPORTS))

def get_session_store() -> SessionStoreProtocol:
    """
    Return the active session store backend.

    默认业务入口是 PostgreSQL-only。SQLite/PocketBase 工厂只保留为显式
    离线导入/旧 fixture 的兼容符号，不再作为运行期 fallback。
    """
    from deeptutor.core.providers import get_providers

    providers = get_providers()
    if providers is not None:
        if providers.store is None:
            raise RuntimeError("session store provider is not configured")
        return providers.store.get()

    from deeptutor.app.container import StoreProvider, get_application_container

    container = get_application_container()
    provider = getattr(container, "store_provider", None)
    if provider is None or isinstance(provider, StoreProvider):
        raise RuntimeError("PostgreSQL session store provider is not configured")
    return provider.get()


__all__ = [
    "SessionStoreProtocol",
    "QuestionBankCursorError",
    "QuestionBankQuery",
    "QuestionBankReferenceConflict",
    "QuestionBankRepository",
    "QuestionBankVersionConflict",
    "TurnRuntimeManager",
    "get_session_store",
    "get_sqlite_session_store",
    "get_turn_runtime_manager",
    "make_imported_session_id",
]
