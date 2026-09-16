"""Probe/full-read dispatch behavior for snapshot adapters.

Runtime chat/quiz snapshot data now comes from PostgreSQL; the true PG
probe/full equivalence is covered by
``tests/persistence/postgres/business/test_memory_snapshot_runtime.py``.  These
unit tests keep the generic dispatch/fallback contracts without opening a
SQLite chat-history fixture.
"""

from __future__ import annotations

import pytest

from deeptutor.services.memory.snapshot import adapters
from deeptutor.services.memory.snapshot.entity import Entity


def _stamps_of(entities) -> list[tuple[str, str, str]]:
    return [(e.id, e.label, e.fingerprint) for e in entities]


def test_chat_probe_returns_empty_without_pg_runtime() -> None:
    assert adapters.probe_chat_entities() == []
    assert adapters.read_chat_entities() == []


def test_read_stamps_falls_back_for_surfaces_without_a_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A surface with no probe is slower, never unsupported."""

    monkeypatch.setitem(
        adapters._READERS,
        "book",
        lambda: [Entity(id="b1", label="Calculus", ts="2026-08-01T00:00:00+00:00", content="...")],
    )

    stamps = adapters.read_stamps("book")

    assert [(s.id, s.label) for s in stamps] == [("b1", "Calculus")]
    assert stamps[0].ts == "2026-08-01T00:00:00+00:00"


def test_read_stamps_falls_back_when_a_probe_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken probe must not read as "the surface is empty" — the diff would
    take that for a mass deletion."""

    def _boom() -> list:
        raise RuntimeError("probe exploded")

    monkeypatch.setitem(adapters._PROBES, "chat", _boom)
    monkeypatch.setitem(
        adapters._READERS,
        "chat",
        lambda: [
            Entity(
                id="s1",
                label="Chain rule",
                fingerprint="fp",
                ts="2026-08-01",
                content="conversation",
            )
        ],
    )

    stamps = adapters.read_stamps("chat")

    assert _stamps_of(stamps) == [("s1", "Chain rule", "fp")]
