"""Stable application-layer facade for DeepTutor entry points."""

from __future__ import annotations

from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass
import importlib.util
import json
import os
import re
from typing import Any, AsyncIterator

from deeptutor.services.notebook import get_notebook_manager

from .contracts import TurnRequest

_SDK_AUTH_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _metadata_capability_registry():
    """Build capability metadata without constructing the PG runtime."""

    from deeptutor.runtime.capability_catalog import get_capability_catalog
    from deeptutor.runtime.registry.capability_registry import CapabilityRegistry

    catalog = get_capability_catalog()
    registry = CapabilityRegistry(catalog)
    registry.load_builtins()
    registry.load_plugins()
    return registry


@dataclass(slots=True)
class CapabilityAvailability:
    """Availability result for optional capabilities."""

    name: str
    available: bool
    install_hint: str = ""


class DeepTutorApp:
    """Facade around runtime, session, notebook, and capability contracts."""

    def __init__(
        self,
        *,
        container=None,
        metadata_only: bool = False,
        auth_token: str | None = None,
        auth_token_env: str | None = None,
        server: str | None = None,
        allow_loopback_http: bool = False,
    ) -> None:
        if auth_token and auth_token_env:
            raise ValueError("SDK auth_token and auth_token_env are mutually exclusive")
        if container is not None and server is not None:
            raise ValueError("SDK container and server modes are mutually exclusive")
        self._auth_token = auth_token
        self._auth_token_env = auth_token_env
        self._container = None
        self._container_error: BaseException | None = None
        self._remote = None
        if server is not None:
            from .remote import RemoteDeepTutorClient

            self._remote = RemoteDeepTutorClient(
                server=server,
                auth_token_resolver=self._resolved_auth_token,
                allow_loopback_http=allow_loopback_http,
            )
        elif container is not None:
            self._container = container
        elif not metadata_only:
            try:
                from deeptutor.persistence.postgres.configuration import (
                    PostgresConfigurationError,
                )

                from .container import get_application_container

                self._container = get_application_container()
            except PostgresConfigurationError as error:
                # 缺默认 PG 配置时仍允许 capability metadata / availability 查询；
                # 任一业务方法访问 container 时会重新抛出原始脱敏配置错误。
                self._container_error = error
        self.turns = (
            self._remote
            if self._remote is not None
            else self._container.turns
            if self._container is not None
            else None
        )
        self._notebooks = None
        from deeptutor.core.providers import get_providers

        # 装配能力随 SDK 对象保留，不能在 ContextVar 退出后降级为本地服务。
        self._local_notebooks_allowed = (
            self._remote is None
            and get_providers() is None
            and self._container is not None
            and getattr(getattr(self._container, "runtime_registry", None), "turn_environment", None)
            is None
        )
        self.capabilities = (
            self._container.capability_registry
            if self._container is not None
            else _metadata_capability_registry()
        )

    async def __aenter__(self) -> "DeepTutorApp":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        await self.close()

    @property
    def container(self):
        if self._container is None:
            if self._container_error is None:
                raise RuntimeError("PostgreSQL runtime is unavailable in metadata-only mode")
            raise self._container_error
        return self._container

    async def close(self) -> None:
        """Close runtime resources held by this facade."""

        if self._remote is not None:
            await self._remote.close()
        if self._container is not None:
            await self._container.close()

    def _resolved_auth_token(self) -> str:
        if self._auth_token is not None:
            token = str(self._auth_token)
            if not token:
                raise PermissionError("SDK authentication failed")
            return token
        name = str(self._auth_token_env or "").strip()
        if not name:
            return ""
        if not _SDK_AUTH_ENV_NAME.fullmatch(name):
            raise PermissionError("SDK authentication token environment reference is required")
        token = os.environ.get(name)
        if not token:
            raise PermissionError("SDK authentication failed")
        return token

    @asynccontextmanager
    async def _operation_context(self):
        await self.container.start()
        token = self._resolved_auth_token()
        current_user_token = None
        provider_scope = nullcontext()
        from deeptutor.core.providers import get_providers, provider_context

        if get_providers() is None:
            providers = getattr(self.container, "providers", None)
            if providers is not None:
                provider_scope = provider_context(providers)
        if token:
            provider = getattr(self.container, "auth_provider", None)
            if provider is None:
                raise PermissionError("SDK authentication failed")
            payload = await provider.decode(token)
            from deeptutor.multi_user.context import (
                reset_current_user,
                set_current_user,
                user_from_token_payload,
            )

            current_user_token = set_current_user(user_from_token_payload(payload))
        try:
            with provider_scope:
                yield
        finally:
            if current_user_token is not None:
                reset_current_user(current_user_token)

    @property
    def notebooks(self):
        if self._notebooks is None:
            from deeptutor.core.providers import get_providers

            if not self._local_notebooks_allowed or get_providers() is not None:
                raise RuntimeError("notebook provider is not configured")
            self._notebooks = get_notebook_manager()
        return self._notebooks

    @notebooks.setter
    def notebooks(self, value):
        self._notebooks = value

    def resolve_capability(self, value: str | None) -> str:
        requested = str(value or "chat").strip() or "chat"
        manifests = self.capabilities.get_manifests()
        for manifest in manifests:
            if manifest["name"] == requested:
                return requested
            aliases = {str(alias).strip() for alias in manifest.get("cli_aliases", [])}
            if requested in aliases:
                return str(manifest["name"])
        available = ", ".join(sorted(manifest["name"] for manifest in manifests))
        raise ValueError(f"Unknown capability `{requested}`. Available: {available}")

    def get_capability_contracts(self) -> list[dict[str, Any]]:
        contracts = []
        for manifest in self.capabilities.get_manifests():
            contracts.append(
                {
                    **manifest,
                    "availability": self.get_capability_availability(manifest["name"]).__dict__,
                }
            )
        return contracts

    def get_capability_contract(self, value: str) -> dict[str, Any]:
        resolved = self.resolve_capability(value)
        for manifest in self.capabilities.get_manifests():
            if manifest["name"] == resolved:
                return {
                    **manifest,
                    "availability": self.get_capability_availability(resolved).__dict__,
                }
        raise ValueError(f"Capability not found: {resolved}")

    def get_capability_availability(self, capability: str) -> CapabilityAvailability:
        resolved = self.resolve_capability(capability)
        if resolved == "math_animator":
            available = importlib.util.find_spec("manim") is not None
            return CapabilityAvailability(
                name=resolved,
                available=available,
                install_hint=(
                    ""
                    if available
                    else "Install with `pip install -e '.[math-animator]'` "
                    "or `pip install -r requirements/math-animator.txt`."
                ),
            )
        return CapabilityAvailability(name=resolved, available=True)

    async def start_turn(
        self, request: TurnRequest | dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if isinstance(request, dict):
            request = TurnRequest(**request)
        if self._remote is not None:
            resolved_capability = self.resolve_capability(request.capability)
            return await self._remote.start_turn(
                request.model_copy(update={"capability": resolved_capability})
            )
        async with self._operation_context():
            resolved_capability = self.resolve_capability(request.capability)
            return await self.turns.start_turn(
                {
                    **request.to_payload(),
                    "capability": resolved_capability,
                }
            )

    async def stream_turn(self, turn_id: str, after_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        if self._remote is not None:
            async for item in self._remote.stream_turn(turn_id, after_seq=after_seq):
                yield item
            return
        async with self._operation_context():
            async for item in self.turns.subscribe_turn(turn_id, after_seq=after_seq):
                yield item

    async def cancel_turn(self, turn_id: str) -> bool:
        if self._remote is not None:
            return await self._remote.cancel_turn(turn_id)
        async with self._operation_context():
            return await self.turns.cancel_turn(turn_id)

    async def submit_user_reply(
        self,
        turn_id: str,
        text: str | None = None,
        *,
        answers: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Deliver the user's reply to a turn paused on ``ask_user``."""
        if self._remote is not None:
            return await self._remote.submit_user_reply(turn_id, text=text, answers=answers)
        async with self._operation_context():
            return await self.turns.submit_user_reply(turn_id, text=text, answers=answers)

    async def regenerate_last_turn(
        self,
        session_id: str,
        overrides: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._remote is not None:
            return await self._remote.regenerate_last_turn(session_id, overrides=overrides)
        async with self._operation_context():
            return await self.turns.regenerate_last_turn(session_id, overrides=overrides)

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        if self._remote is not None:
            return await self._remote.list_sessions(limit=limit, offset=offset)
        async with self._operation_context():
            return await self.turns.list_sessions(limit=limit, offset=offset)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        if self._remote is not None:
            return await self._remote.get_session(session_id)
        async with self._operation_context():
            return await self.turns.get_session(session_id)

    async def rename_session(self, session_id: str, title: str) -> bool:
        if self._remote is not None:
            return await self._remote.rename_session(session_id, title)
        async with self._operation_context():
            return await self.turns.rename_session(session_id, title)

    async def delete_session(self, session_id: str) -> bool:
        if self._remote is not None:
            return await self._remote.delete_session(session_id)
        async with self._operation_context():
            return await self.turns.delete_session(session_id)

    async def get_active_turn(self, session_id: str) -> dict[str, Any] | None:
        if self._remote is not None:
            return await self._remote.check_active_turn(session_id)
        async with self._operation_context():
            return await self.turns.check_active_turn(session_id)

    def list_notebooks(self) -> list[dict[str, Any]]:
        return self.notebooks.list_notebooks()

    def create_notebook(
        self,
        name: str,
        description: str = "",
        *,
        color: str = "#3B82F6",
        icon: str = "book",
    ) -> dict[str, Any]:
        return self.notebooks.create_notebook(
            name=name,
            description=description,
            color=color,
            icon=icon,
        )

    def get_notebook(self, notebook_id: str) -> dict[str, Any] | None:
        return self.notebooks.get_notebook(notebook_id)

    def add_record(self, **kwargs: Any) -> dict[str, Any]:
        return self.notebooks.add_record(**kwargs)

    def update_record(
        self, notebook_id: str, record_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        return self.notebooks.update_record(notebook_id, record_id, **kwargs)

    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        return self.notebooks.remove_record(notebook_id, record_id)

    def get_records_by_references(
        self, notebook_references: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return self.notebooks.get_records_by_references(notebook_references)


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
