"""Tests for the MarginNote 4 tools against an injected PG-style store."""

from __future__ import annotations

import json

import pytest

from deeptutor.capabilities.marginnote4.models import (
    CARD,
    NOTE,
    MarginNoteObject,
)
from deeptutor.capabilities.marginnote4.tools import (
    MarginNoteCardsTool,
    MarginNoteDocumentsTool,
    MarginNoteLinksTool,
    MarginNoteListTool,
    MarginNoteReadTool,
    MarginNoteSearchTool,
    MarginNoteTagsTool,
    _clear_store_cache,
)


class _FakeMarginNoteStore:
    """Small synchronous test double matching the PG store read API."""

    def __init__(self, objects: list[MarginNoteObject]) -> None:
        self._objects = {obj.object_id: obj for obj in objects}

    def search(self, query: str, *, object_type: str = "", limit: int = 20):
        needle = query.lower()
        results = []
        for obj in self._objects.values():
            if object_type and obj.object_type != object_type:
                continue
            haystack = " ".join([obj.title, obj.content, obj.excerpt or ""]).lower()
            if needle in haystack:
                results.append(obj.to_dict())
        return results[:limit]

    def get(self, object_id: str):
        return self._objects.get(object_id)

    def list_objects(self, *, object_type: str = "", document_id: str = "", limit: int = 200):
        results = []
        for obj in self._objects.values():
            if object_type and obj.object_type != object_type:
                continue
            if document_id and obj.document_id != document_id:
                continue
            results.append(obj.to_dict())
        return results[:limit]

    def list_documents(self):
        counts: dict[tuple[str, str], int] = {}
        for obj in self._objects.values():
            if not obj.document_id:
                continue
            key = (obj.document_id, obj.document_title or obj.document_id)
            counts[key] = counts.get(key, 0) + 1
        return [
            {"document_id": doc_id, "title": title, "count": count}
            for (doc_id, title), count in counts.items()
        ]

    def linked_objects(self, object_id: str):
        obj = self._objects.get(object_id)
        linked: set[str] = set(obj.links if obj else [])
        for candidate in self._objects.values():
            if object_id in candidate.links:
                linked.add(candidate.object_id)
        return [
            self._objects[linked_id].to_dict()
            for linked_id in sorted(linked)
            if linked_id in self._objects
        ]

    def collect_tags(self, *, limit: int = 200):
        counts: dict[str, int] = {}
        for obj in self._objects.values():
            for tag in obj.tags:
                counts[tag] = counts.get(tag, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [{"tag": tag, "count": count} for tag, count in ranked[:limit]]


def _seed_store() -> _FakeMarginNoteStore:
    """Seed a PG-style store test double for tool calls."""
    _clear_store_cache()
    return _FakeMarginNoteStore(
        [
            MarginNoteObject(
                object_id="note1",
                object_type=NOTE,
                title="Photosynthesis",
                content="Plants convert light into chemical energy.",
                excerpt="The process by which green plants use sunlight...",
                document_id="doc1",
                document_title="Biology Textbook",
                page=42,
                tags=["biology"],
                links=["card1"],
                device_id="dev1",
            ),
            MarginNoteObject(
                object_id="card1",
                object_type=CARD,
                title="What is photosynthesis?",
                content="Process of converting light to chemical energy",
                tags=["biology"],
                links=["note1"],
                device_id="dev1",
            ),
        ]
    )


def _kw(store: _FakeMarginNoteStore) -> dict[str, object]:
    return {
        "_marginnote_store": store,
        "_mn4_kb_id": "biology",
    }


@pytest.mark.asyncio
async def test_search_finds_results() -> None:
    store = _seed_store()
    # "green plants" appears only in note1's excerpt
    res = await MarginNoteSearchTool().execute(query="green plants", **_kw(store))
    assert res.success
    data = json.loads(res.content)
    assert data["count"] == 1
    assert data["results"][0]["object_id"] == "note1"


@pytest.mark.asyncio
async def test_search_finds_common_term() -> None:
    store = _seed_store()
    # "photosynthesis" appears in both note1 and card1 titles
    res = await MarginNoteSearchTool().execute(query="photosynthesis", **_kw(store))
    assert res.success
    data = json.loads(res.content)
    assert data["count"] >= 1


@pytest.mark.asyncio
async def test_search_empty_query_fails() -> None:
    store = _seed_store()
    res = await MarginNoteSearchTool().execute(query="", **_kw(store))
    assert res.success is False


@pytest.mark.asyncio
async def test_read_returns_full_object() -> None:
    store = _seed_store()
    res = await MarginNoteReadTool().execute(object_id="note1", **_kw(store))
    assert res.success
    data = json.loads(res.content)
    assert data["title"] == "Photosynthesis"
    assert data["document_title"] == "Biology Textbook"
    assert data["page"] == 42
    assert data["tags"] == ["biology"]


@pytest.mark.asyncio
async def test_read_missing_object_fails() -> None:
    store = _seed_store()
    res = await MarginNoteReadTool().execute(object_id="nonexistent", **_kw(store))
    assert res.success is False


@pytest.mark.asyncio
async def test_list_by_type() -> None:
    store = _seed_store()
    res = await MarginNoteListTool().execute(object_type="card", **_kw(store))
    assert res.success
    data = json.loads(res.content)
    assert data["count"] == 1
    assert data["objects"][0]["object_id"] == "card1"


@pytest.mark.asyncio
async def test_documents_lists_sources() -> None:
    store = _seed_store()
    res = await MarginNoteDocumentsTool().execute(**_kw(store))
    assert res.success
    data = json.loads(res.content)
    assert data["count"] == 1
    assert data["documents"][0]["title"] == "Biology Textbook"


@pytest.mark.asyncio
async def test_links_finds_connections() -> None:
    store = _seed_store()
    res = await MarginNoteLinksTool().execute(object_id="note1", **_kw(store))
    assert res.success
    data = json.loads(res.content)
    linked_ids = {item["object_id"] for item in data["links"]}
    assert "card1" in linked_ids


@pytest.mark.asyncio
async def test_tags_returns_ranked() -> None:
    store = _seed_store()
    res = await MarginNoteTagsTool().execute(**_kw(store))
    assert res.success
    data = json.loads(res.content)
    assert any(t["tag"] == "biology" for t in data["tags"])


@pytest.mark.asyncio
async def test_cards_lists_flashcards() -> None:
    store = _seed_store()
    res = await MarginNoteCardsTool().execute(**_kw(store))
    assert res.success
    data = json.loads(res.content)
    assert data["count"] == 1
    assert data["cards"][0]["object_type"] == "card"


@pytest.mark.asyncio
async def test_tools_fail_without_store() -> None:
    res = await MarginNoteSearchTool().execute(query="test")
    assert res.success is False
    assert "MarginNote" in res.content


@pytest.mark.asyncio
async def test_tools_ignore_legacy_db_path_without_store() -> None:
    res = await MarginNoteSearchTool().execute(query="test", _db_path="/tmp/legacy.sqlite3")
    assert res.success is False
