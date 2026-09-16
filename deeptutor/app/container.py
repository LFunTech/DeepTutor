"""Process-level dependency container and scoped runtime registry."""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
from typing import Any
import uuid

from deeptutor.runtime.capability_catalog import get_capability_catalog
from deeptutor.runtime.coordination import (
    CoordinationSettings,
    MemoryCoordinator,
    RedisCoordinator,
    RuntimeConfigurationError,
    RuntimeCoordinator,
    TurnRecoveryService,
)
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.turn_engine import TurnEngine
from deeptutor.services.config import (
    load_auth_settings,
    load_integrations_settings,
    load_system_settings,
)
from deeptutor.services.session.protocol import SessionStoreProtocol
from deeptutor.services.session.scope import store_scope
from deeptutor.services.session.turn_runtime import TurnRuntimeManager

from .service import TurnApplicationService

_LEGACY_STARTUP_MIGRATION_DISABLED = (
    "PostgreSQL-only runtime no longer runs legacy startup data migrations. "
    "Use the controlled offline import tooling for historical SQLite/PocketBase "
    "data before cutover; business startup only verifies PostgreSQL state."
)


class StoreProvider:
    def get(self) -> SessionStoreProtocol:
        raise RuntimeError("PostgreSQL session store provider is not configured")


class RuntimeRegistry:
    def __init__(
        self,
        coordinator: RuntimeCoordinator,
        worker_id: str,
        turn_engine: TurnEngine | None = None,
        *,
        turn_environment=None,
        coordinator_factory=None,
    ) -> None:
        self.coordinator = coordinator
        self.worker_id = worker_id
        self.turn_engine = turn_engine
        self.turn_environment = turn_environment
        self.coordinator_factory = coordinator_factory
        self._runtimes: dict[str, TurnRuntimeManager] = {}

    def get(self, store: SessionStoreProtocol) -> TurnRuntimeManager:
        key = store_scope(store).cache_key
        runtime = self._runtimes.get(key)
        if runtime is None:
            runtime = TurnRuntimeManager(
                store,
                coordinator=(
                    self.coordinator_factory() if self.coordinator_factory else self.coordinator
                ),
                owner_id=self.worker_id,
                turn_engine=self.turn_engine,
                **(
                    {"turn_environment": self.turn_environment}
                    if self.turn_environment is not None
                    else {}
                ),
            )
            self._runtimes[key] = runtime
        return runtime

    async def close(self, *, drain_timeout_seconds: float = 60.0) -> None:
        runtimes = list(self._runtimes.values())
        self._runtimes.clear()
        if runtimes:
            await asyncio.gather(
                *(
                    runtime.close(drain_timeout_seconds=drain_timeout_seconds)
                    for runtime in runtimes
                ),
                return_exceptions=True,
            )

    def owner_turn_count(self) -> int:
        return sum(len(runtime._executions) for runtime in self._runtimes.values())


class ApplicationContainer:
    def __init__(
        self,
        *,
        settings: CoordinationSettings,
        coordinator: RuntimeCoordinator,
        worker_id: str,
        store_provider=None,
        auth_provider=None,
        learning_provider=None,
        reading_provider=None,
        resources_provider=None,
        object_store_provider=None,
        postgres_runtime=None,
        turn_environment=None,
        capability_registry=None,
        load_plugins: bool = True,
        coordinator_factory=None,
        turn_service_factory=TurnApplicationService,
    ) -> None:
        self.settings = settings
        self.coordinator = coordinator
        self.worker_id = worker_id
        if capability_registry is None:
            self.capability_catalog = get_capability_catalog()
            self.capability_registry = CapabilityRegistry(self.capability_catalog)
            self.capability_registry.load_builtins()
        else:
            self.capability_registry = capability_registry
            self.capability_catalog = capability_registry.catalog
        if load_plugins:
            self.capability_registry.load_plugins()
        self.turn_engine = TurnEngine(self.capability_registry)
        self.store_provider = store_provider if store_provider is not None else StoreProvider()
        self.auth_provider = auth_provider
        self.learning_provider = learning_provider
        self.reading_provider = reading_provider
        self.resources_provider = resources_provider
        self.object_store_provider = object_store_provider
        self.postgres_runtime = postgres_runtime
        from deeptutor.core.providers import ApplicationProviders

        self.providers = ApplicationProviders(
            store=self.store_provider,
            container=self,
            auth=self.auth_provider,
            resources=self.resources_provider,
            object_store=self.object_store_provider,
            learning=self.learning_provider,
            reading=self.reading_provider,
        )
        self.runtime_registry = RuntimeRegistry(
            coordinator,
            worker_id,
            self.turn_engine,
            turn_environment=turn_environment,
            coordinator_factory=coordinator_factory,
        )
        self.turns = turn_service_factory(
            self.store_provider,
            self.runtime_registry,
            coordinator,
        )
        self._recovery_services: dict[str, TurnRecoveryService] = {}
        self._started = False

    @classmethod
    def build(cls) -> "ApplicationContainer":
        auth_settings = load_auth_settings()
        settings = CoordinationSettings.from_runtime_settings(
            load_system_settings(), load_integrations_settings()
        )
        coordinator: RuntimeCoordinator
        if settings.backend == "redis":
            coordinator = RedisCoordinator(
                settings.redis_url,
                key_prefix=settings.key_prefix,
                lease_ttl_seconds=settings.lease_ttl_seconds,
                stream_retention_seconds=settings.stream_retention_seconds,
            )
        else:
            coordinator = MemoryCoordinator(lease_ttl_seconds=settings.lease_ttl_seconds)
        worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        from deeptutor.app.postgres_runtime import DefaultPostgresRuntime

        postgres_runtime = DefaultPostgresRuntime.from_environment(
            cookie_secure=bool(auth_settings.get("cookie_secure", True))
        )
        return cls(
            settings=settings,
            coordinator=coordinator,
            worker_id=worker_id,
            store_provider=postgres_runtime.store_provider,
            auth_provider=postgres_runtime.auth_provider,
            learning_provider=postgres_runtime.learning_provider,
            reading_provider=postgres_runtime.reading_provider,
            resources_provider=postgres_runtime.resources,
            object_store_provider=postgres_runtime.object_store,
            postgres_runtime=postgres_runtime,
        )

    async def start(self) -> None:
        if self._started:
            return
        try:
            if self.postgres_runtime is not None:
                await self.postgres_runtime.start()
            if not await self.coordinator.health():
                raise RuntimeConfigurationError(
                    "Turn coordination backend is unavailable; refusing to start"
                )
        except BaseException:
            if self.postgres_runtime is not None:
                with contextlib.suppress(Exception):
                    await self.postgres_runtime.close()
            raise
        self._started = True

    async def close(self) -> None:
        if self._started:
            await self.runtime_registry.close(drain_timeout_seconds=60.0)
            with contextlib.suppress(Exception):
                await self.coordinator.close()
            self._started = False
        if self.postgres_runtime is not None:
            await self.postgres_runtime.close()

    async def recover_once(self) -> None:
        """Recover expired turns across every registered user repository.

        Missing turns are deliberately not acknowledged by a repository's
        recovery service; the next user scope therefore still gets a chance
        to claim and recover them.
        """

        from deeptutor.core.providers import get_providers

        providers = get_providers()
        if providers is not None and providers.learning is not None:
            from deeptutor.learning.runtime import get_learning_runtime

            await get_learning_runtime().recover_once()
            return
        if self.postgres_runtime is not None:
            await self.postgres_runtime.recover_once()
            return

        from deeptutor.multi_user.paths import user_context

        seen: set[str] = set()
        for user in self._local_users():
            with user_context(user):
                store = self.store_provider.get()
                scope_key = store_scope(store).cache_key
                if scope_key in seen:
                    continue
                seen.add(scope_key)
                recovery = self._recovery_services.get(scope_key)
                if recovery is None:
                    recovery = TurnRecoveryService(self.coordinator, store)
                    self._recovery_services[scope_key] = recovery
                await recovery.recover_once()

    @staticmethod
    def _local_users() -> list[Any]:
        """Return the admin plus every registered local user scope."""

        from deeptutor.multi_user.identity import list_user_info
        from deeptutor.multi_user.models import CurrentUser
        from deeptutor.multi_user.paths import local_admin_user, scope_for_user

        users = [local_admin_user()]
        for record in list_user_info():
            user_id = str(record.get("id") or "").strip()
            role = str(record.get("role") or "user")
            if not user_id or role == "admin":
                continue
            users.append(
                CurrentUser(
                    id=user_id,
                    username=str(record.get("username") or user_id),
                    role="user",
                    scope=scope_for_user(user_id, is_admin=False),
                )
            )
        return users

    async def migrate_legacy_chat(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Migrate the current scope's removed v1 JSON chat store."""

        raise RuntimeError(_LEGACY_STARTUP_MIGRATION_DISABLED)

    async def migrate_all_legacy_chats(self, *, dry_run: bool = False) -> list[dict[str, Any]]:
        """Migrate admin and every registered local user scope."""

        raise RuntimeError(_LEGACY_STARTUP_MIGRATION_DISABLED)

    async def migrate_all_workspace_preferences(self) -> list[dict[str, Any]]:
        """Upgrade legacy Reading/Mastery metadata in every account scope."""

        raise RuntimeError(_LEGACY_STARTUP_MIGRATION_DISABLED)

    async def run_startup_data_migrations(self) -> dict[str, list[dict[str, Any]]]:
        """Run every idempotent migration shared by all server launch modes."""

        raise RuntimeError(_LEGACY_STARTUP_MIGRATION_DISABLED)

    async def runtime_report(self) -> dict[str, Any]:
        report = self.settings.runtime_report()
        coordinator_healthy = await self.coordinator.health()
        objectstore_status = "not_configured"
        if self.object_store_provider is not None:
            check_bucket = getattr(self.object_store_provider, "check_bucket", None)
            if callable(check_bucket):
                try:
                    status = await asyncio.to_thread(check_bucket)
                    objectstore_status = status.safe_summary()
                except Exception:
                    objectstore_status = "objectstore:unavailable:provider_error"
            else:
                objectstore_status = "configured"
        data_gate_summary = ""
        try:
            from deeptutor.runtime.data_gate import RuntimeDataGate, RuntimeMode
            from deeptutor.services.path_service import get_runtime_data_root

            data_gate_summary = RuntimeDataGate(
                get_runtime_data_root(), mode=RuntimeMode.from_environ()
            ).evaluate(
                active_authorities={
                    "owner_resources": "objectstore"
                    if self.object_store_provider is not None
                    else "local"
                }
            ).safe_summary()
        except Exception:
            data_gate_summary = "data_gate:unknown:blocked:data_gate_unavailable"
        migration_version = ""
        try:
            from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

            migration_version = MigrationRunner("host=not-used")._migrations()[-1][0]
        except Exception:
            migration_version = ""
        report.update(
            {
                "worker_id": self.worker_id,
                "redis_status": (
                    "ok"
                    if self.settings.backend == "redis" and coordinator_healthy
                    else ("unavailable" if self.settings.backend == "redis" else "not_configured")
                ),
                "leader_id": await self.coordinator.leader_id(),
                "owner_turn_count": self.runtime_registry.owner_turn_count(),
                "recovery_backlog": sum(
                    recovery.backlog for recovery in self._recovery_services.values()
                ),
                "providers": {
                    "postgres": "configured" if self.postgres_runtime is not None else "external",
                    "objectstore": objectstore_status,
                    "settings": "postgres" if self.postgres_runtime is not None else "local",
                    "secret": "env:configured",
                },
                "data_gate": data_gate_summary,
                "cleanup_backlog": 0,
                "migration_version": migration_version,
            }
        )
        return report


_default_container: ApplicationContainer | None = None


def get_application_container() -> ApplicationContainer:
    from deeptutor.core.providers import get_providers

    providers = get_providers()
    if providers is not None:
        if providers.container is None:
            raise RuntimeError("application container is not configured")
        return providers.container
    global _default_container
    if _default_container is None:
        _default_container = ApplicationContainer.build()
    return _default_container


def set_application_container(container: ApplicationContainer | None) -> None:
    global _default_container
    _default_container = container


__all__ = [
    "ApplicationContainer",
    "RuntimeRegistry",
    "StoreProvider",
    "get_application_container",
    "set_application_container",
]
