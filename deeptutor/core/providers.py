"""显式应用组合边界；任务局部绑定，不修改默认进程容器或 local 配置。"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

APPLICATION_HOOK_VERSION = 1


@dataclass(frozen=True, slots=True)
class ApplicationProviders:
    store: Any = None
    container: Any = None
    configuration: Any = None
    auth: Any = None
    resources: Any = None
    object_store: Any = None
    learning: Any = None
    reading: Any = None


_providers: ContextVar[ApplicationProviders | None] = ContextVar(
    "application_providers", default=None
)


def get_providers() -> ApplicationProviders | None:
    return _providers.get()


@contextmanager
def provider_context(providers: ApplicationProviders):
    token = _providers.set(providers)
    try:
        yield providers
    finally:
        _providers.reset(token)
