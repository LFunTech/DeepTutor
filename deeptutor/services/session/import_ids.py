"""Runtime-safe helpers for externally imported chat session identifiers."""

from __future__ import annotations

import re
import uuid

# Imported conversations share the session tables with native chats but carry
# this id prefix as their discriminator.
IMPORTED_ID_PREFIX = "imported_"
_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def make_imported_session_id(source: str, external_id: str) -> str:
    """Build a deterministic, dedup-friendly id for an imported conversation.

    ``source`` (e.g. ``claude_code``/``codex``) namespaces the original
    session uuid so two tools that happen to reuse an id never collide; the
    determinism is what makes re-importing the same folder idempotent.
    """
    src = _ID_SAFE.sub("-", (source or "external").strip()) or "external"
    ext = _ID_SAFE.sub("-", (external_id or "").strip()) or uuid.uuid4().hex
    return f"{IMPORTED_ID_PREFIX}{src}_{ext}"


__all__ = ["IMPORTED_ID_PREFIX", "make_imported_session_id"]
