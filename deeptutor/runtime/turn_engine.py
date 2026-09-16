"""Shared lower-level execution engine used by every application adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent


class TurnEngine:
    """Execute an assembled context through the canonical orchestrator."""

    def __init__(self, capability_registry=None) -> None:  # noqa: ANN001
        self.capability_registry = capability_registry

    async def execute(self, context: UnifiedContext) -> AsyncIterator[StreamEvent]:
        # Lazy loading avoids provider/plugin import side effects at process
        # boot and leaves one stable patch point for tests and embedders.
        from deeptutor.runtime.orchestrator import ChatOrchestrator

        if context.runtime.resource_capabilities is not None:
            from deeptutor.runtime.registry.capability_registry import CapabilityRegistry

            registry = self.capability_registry or CapabilityRegistry()
            if self.capability_registry is None:
                from deeptutor.agents.chat.capability import ChatCapability

                registry.register(ChatCapability)
            orchestrator = ChatOrchestrator(
                capability_registry=registry, tool_registry=context.runtime.tool_registry
            )
        else:
            orchestrator = (
                ChatOrchestrator()
                if self.capability_registry is None
                else ChatOrchestrator(capability_registry=self.capability_registry)
            )
        async with aclosing(orchestrator.handle(context)) as events:
            async for event in events:
                yield event


_default_engine: TurnEngine | None = None


def get_turn_engine() -> TurnEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = TurnEngine()
    return _default_engine


__all__ = ["TurnEngine", "get_turn_engine"]
