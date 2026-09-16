"""MarginNote 4 loop capability -- agentic retrieval over a synced MN4 library."""

from __future__ import annotations

__all__ = [
    "MARGINNOTE_TOOL_NAMES",
    "MARGINNOTE_TOOL_TYPES",
    "MarginNoteCapability",
]


def __getattr__(name: str):
    """惰性导出，避免 PG store 导入模型时触发 tools 的反向导入。"""

    if name == "MarginNoteCapability":
        from deeptutor.capabilities.marginnote4.capability import MarginNoteCapability

        return MarginNoteCapability
    if name in {"MARGINNOTE_TOOL_NAMES", "MARGINNOTE_TOOL_TYPES"}:
        from deeptutor.capabilities.marginnote4.tools import (
            MARGINNOTE_TOOL_NAMES,
            MARGINNOTE_TOOL_TYPES,
        )

        return {
            "MARGINNOTE_TOOL_NAMES": MARGINNOTE_TOOL_NAMES,
            "MARGINNOTE_TOOL_TYPES": MARGINNOTE_TOOL_TYPES,
        }[name]
    raise AttributeError(name)
