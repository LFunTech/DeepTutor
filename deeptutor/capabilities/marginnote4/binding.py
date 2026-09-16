"""Resolve which connected MarginNote 4 library (if any) the current turn targets.

The selected KB reference becomes the PostgreSQL ``kb_id`` used by the MN4
store.  Runtime authorization comes from the current PG tenant/owner identity;
legacy ``db_path`` metadata is ignored during normal operation.
"""

from __future__ import annotations

from deeptutor.core.context import UnifiedContext
from deeptutor.knowledge.kb_types import MARGINNOTE4_KB_TYPE

_CACHE_KEY = "_marginnote4_binding"
_UNSET = object()


def marginnote_binding(context: UnifiedContext) -> dict[str, str] | None:
    """Return ``{"name", "kb_id"}`` of the selected MN4 KB, or ``None``."""

    state = context.extension("marginnote4")
    cached = state.get(_CACHE_KEY, _UNSET)
    if cached is not _UNSET:
        return cached or None
    resolved = _resolve(context)
    state[_CACHE_KEY] = resolved or ""
    return resolved


def _resolve(context: UnifiedContext) -> dict[str, str] | None:
    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

    for ref in context.knowledge_bases or []:
        ref = str(ref).strip()
        if not ref:
            continue
        meta = resolve_kb_metadata(ref)
        if not meta or meta.get("type") != MARGINNOTE4_KB_TYPE:
            continue
        return {"name": str(meta.get("name") or ref), "kb_id": ref}
    return None


def marginnote_kb_refs(context: UnifiedContext) -> set[str]:
    """Return every selected KB ref that resolves to a connected MN4 library."""

    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

    refs: set[str] = set()
    for ref in context.knowledge_bases or []:
        ref = str(ref).strip()
        if not ref:
            continue
        meta = resolve_kb_metadata(ref)
        if meta and meta.get("type") == MARGINNOTE4_KB_TYPE:
            refs.add(ref)
    return refs


__all__ = ["marginnote_binding", "marginnote_kb_refs"]
