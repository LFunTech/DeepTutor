"""Best-effort aggregation for the course learning container."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import Any

logger = logging.getLogger(__name__)

ResourceIndex = dict[str, dict[str, Any]]


def _as_int(value: object) -> int:
    try:
        return int(value or 0)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0


def _as_float(value: object) -> float:
    try:
        return float(value or 0.0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _as_text(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value or "")


async def _safe_index(
    kind: str,
    loader: Callable[[], Awaitable[ResourceIndex]] | None,
) -> ResourceIndex:
    if kind in {"mastery_path", "reading_workspace"}:
        assert loader is not None
        try:
            return await loader()
        except Exception:
            logger.debug("Course %s index is unavailable", kind, exc_info=True)
            return {}
    from deeptutor.learning.runtime import get_learning_runtime

    try:
        runtime = get_learning_runtime()
    except Exception:
        if loader is None:
            return {}
        try:
            return await loader()
        except Exception:
            logger.debug("Course %s fallback index is unavailable", kind, exc_info=True)
            return {}
    if runtime.source_provider is None:
        return {}
    try:
        await runtime.authorize()
        result = await runtime.source_provider.course_index(runtime.scope, kind)
        await runtime.authorize()
        return result
    except Exception:
        logger.debug("PostgreSQL course %s authority index is unavailable", kind, exc_info=True)
        return {}


async def _knowledge_base_index() -> ResourceIndex:
    from deeptutor.multi_user.knowledge_access import current_kb_manager

    manager = current_kb_manager()
    names = await asyncio.to_thread(manager.list_knowledge_bases)
    return {name: {"name": name} for raw_name in names if (name := str(raw_name or "").strip())}


async def _book_index() -> ResourceIndex:
    from deeptutor.book.engine import get_book_engine

    books = await asyncio.to_thread(get_book_engine().list_books)
    result: ResourceIndex = {}
    for book in books:
        book_id = str(getattr(book, "id", "") or "").strip()
        if not book_id:
            continue
        result[book_id] = {
            "title": str(getattr(book, "title", "") or book_id),
            "description": str(getattr(book, "description", "") or ""),
            "status": _as_text(getattr(book, "status", "")),
            "pages": _as_int(getattr(book, "page_count", 0)),
        }
    return result


async def _notebook_index() -> ResourceIndex:
    from deeptutor.services.notebook.service import get_notebook_manager

    rows = await asyncio.to_thread(get_notebook_manager().list_notebooks)
    result: ResourceIndex = {}
    for row in rows:
        notebook_id = str(row.get("id") or "").strip()
        if not notebook_id:
            continue
        result[notebook_id] = {
            "name": str(row.get("name") or notebook_id),
            "description": str(row.get("description") or ""),
            "records": _as_int(row.get("record_count")),
        }
    return result


def _mastery_stage(row: dict[str, Any], objectives_mastered: int) -> str:
    stage = _as_text(row.get("stage") or row.get("current_stage")).strip()
    if stage:
        return stage
    if row.get("complete"):
        return "complete"
    if row.get("open_question") or _as_int(row.get("learning")) or objectives_mastered:
        return "learning"
    return "not_started"


def _weak_points(row: dict[str, Any]) -> list[str]:
    raw_points = row.get("weak_points")
    if not isinstance(raw_points, list):
        return []
    points: list[str] = []
    for item in raw_points:
        if isinstance(item, dict):
            value = item.get("name") or item.get("label") or item.get("id")
        else:
            value = item
        text = str(value or "").strip()
        if text:
            points.append(text)
    return points


async def _mastery_path_index() -> ResourceIndex:
    from deeptutor.learning.contracts import LearningPaginationRequired
    from deeptutor.learning.navigation import path_overview_page

    rows, cursor = [], None
    while True:
        page = await path_overview_page(cursor=cursor)
        rows.extend(page["paths"])
        if len(rows) > 1000:
            raise LearningPaginationRequired("course mastery index requires cursor pagination")
        cursor = page["next_cursor"]
        if cursor is None:
            break
    result: ResourceIndex = {}
    for row in rows:
        path_id = str(row.get("path_id") or row.get("book_id") or "").strip()
        if not path_id:
            continue
        # Objectives, not modules: mastery is a per-objective gate, so the fact
        # is "3 of 8 cleared" (see LearningService.list_path_overviews). Naming
        # the field after modules while carrying objective counts would put a
        # number on screen that does not mean what its label says.
        objectives_total = _as_int(row.get("objectives"))
        objectives_mastered = _as_int(row.get("mastered"))
        result[path_id] = {
            "path_id": path_id,
            "name": str(row.get("name") or path_id),
            "objectives_total": objectives_total,
            "objectives_mastered": objectives_mastered,
            "stage": _mastery_stage(row, objectives_mastered),
            "weak_points": _weak_points(row),
        }
    return result


async def _reading_workspace_index() -> ResourceIndex:
    from deeptutor.learning.contracts import LearningPaginationRequired
    from deeptutor.learning.runtime import get_learning_runtime
    from deeptutor.persistence.postgres.reading import AsyncReadingCatalogStore

    runtime = get_learning_runtime()
    catalog = AsyncReadingCatalogStore(runtime.database, runtime.scope)
    rows, cursor = [], None
    while True:
        await runtime.authorize()
        page = await catalog.run(lambda u: u.list_workspaces_page(cursor=cursor))
        rows.extend(page.items)
        if len(rows) > 1000:
            raise LearningPaginationRequired("course reading index requires cursor pagination")
        cursor = page.next_cursor
        if cursor is None:
            break
    result: ResourceIndex = {}
    for row in rows:
        workspace_id = str(getattr(row, "workspace_id", "") or "").strip()
        if not workspace_id:
            continue
        result[workspace_id] = {
            "workspace_id": workspace_id,
            "title": str(getattr(row, "title", "") or workspace_id),
            "materials": len(getattr(row, "tabs", ()) or ()),
        }
    return result


async def _partner_index() -> ResourceIndex:
    from deeptutor.services.partners import get_partner_manager

    rows = await asyncio.to_thread(get_partner_manager().list_partners)
    result: ResourceIndex = {}
    for row in rows:
        partner_id = str(row.get("partner_id") or row.get("id") or "").strip()
        if not partner_id:
            continue
        result[partner_id] = {
            "name": str(row.get("name") or partner_id),
            "description": str(row.get("description") or ""),
            "running": bool(row.get("running")),
        }
    return result


async def resolve_resource_reference(kind: str, ref_id: str) -> dict[str, Any] | None:
    """Look one reference up in the system that owns that kind.

    Membership of a *course* is the wrong question for "can this be opened?" —
    a mastery path the learner built outside this course is perfectly routable.
    What must be checked is that the id exists at all in the subsystem the link
    points at. Loads only the one index it needs; enumerating all seven walks
    four other subsystems for a single lookup.
    """
    loader = _INDEX_LOADERS.get(kind)
    clean_ref = str(ref_id or "").strip()
    if loader is None or not clean_ref:
        return None
    index = await _safe_index(kind, loader)
    detail = index.get(clean_ref)
    return dict(detail) if isinstance(detail, dict) else None


#: One loader per kind that has a registry to enumerate. Shared by the whole-set
#: aggregate and the single-reference lookup above, so the two can never
#: disagree about what a kind's ids are.
_INDEX_LOADERS: dict[str, Callable[[], Awaitable[ResourceIndex]]] = {
    "knowledge_base": _knowledge_base_index,
    "book": _book_index,
    "notebook": _notebook_index,
    "mastery_path": _mastery_path_index,
    "reading_workspace": _reading_workspace_index,
    "partner": _partner_index,
}


async def _resource_indexes() -> dict[str, ResourceIndex]:
    from deeptutor.services.courses import COURSE_RESOURCE_KINDS

    loaded = await asyncio.gather(
        *(_safe_index(kind, _INDEX_LOADERS.get(kind)) for kind in COURSE_RESOURCE_KINDS)
    )
    return dict(zip(COURSE_RESOURCE_KINDS, loaded, strict=True))


async def _session_state(course_id: str) -> tuple[dict[str, Any], set[str]]:
    from deeptutor.learning.contracts import LearningPaginationRequired
    from deeptutor.learning.runtime import get_learning_runtime

    empty = {"active": 0, "archived": 0, "recent": []}
    try:
        runtime = get_learning_runtime()
        await runtime.authorize()
        sessions, offset = [], 0
        while True:
            page = await runtime.session_store.list_sessions(limit=200, offset=offset)
            sessions.extend(page)
            if len(sessions) > 1000:
                raise LearningPaginationRequired("course session index requires pagination")
            if len(page) < 200:
                break
            offset += len(page)
        await runtime.authorize()
    except Exception:
        logger.debug("Course session index is unavailable", exc_info=True)
        return empty, set()

    matched = []
    for session in sessions:
        preferences = session.get("preferences") or {}
        if str(preferences.get("course_id") or "") == course_id:
            matched.append(session)

    matched.sort(key=lambda row: _as_float(row.get("updated_at")), reverse=True)
    archived = sum(bool((row.get("preferences") or {}).get("archived")) for row in matched)
    recent = [
        {
            "session_id": str(row.get("session_id") or row.get("id") or ""),
            "title": str(row.get("title") or ""),
            "updated_at": _as_float(row.get("updated_at")),
        }
        for row in matched[:5]
    ]
    session_ids = {
        str(row.get("session_id") or row.get("id") or "").strip()
        for row in matched
        if str(row.get("session_id") or row.get("id") or "").strip()
    }
    return {"active": len(matched) - archived, "archived": archived, "recent": recent}, session_ids


async def _question_bank_state(session_ids: set[str]) -> dict[str, Any]:
    empty = {"total": 0, "wrong": 0, "weak_categories": []}
    if not session_ids:
        return empty

    from deeptutor.learning.runtime import get_learning_runtime

    runtime = get_learning_runtime()
    await runtime.authorize()
    store = runtime.session_store
    total = 0
    wrong = 0
    category_counts: dict[str, int] = {}
    for session_id in sorted(session_ids):
        all_rows = await store.list_notebook_entries(limit=1, session_id=session_id)
        total += _as_int(all_rows.get("total"))

        offset = 0
        while True:
            wrong_rows = await store.list_notebook_entries(
                is_correct=False,
                limit=500,
                offset=offset,
                session_id=session_id,
            )
            if offset == 0:
                wrong += _as_int(wrong_rows.get("total"))
            items = wrong_rows.get("items") or []
            for item in items:
                for category in item.get("categories") or []:
                    name = str(category.get("name") or "").strip()
                    if name:
                        category_counts[name] = category_counts.get(name, 0) + 1
            if len(items) < 500:
                break
            offset += len(items)
    await runtime.authorize()

    weak_categories = [
        {"name": name, "wrong": count}
        for name, count in sorted(
            category_counts.items(),
            key=lambda item: (-item[1], item[0].casefold()),
        )
    ]
    return {"total": total, "wrong": wrong, "weak_categories": weak_categories}


def _candidate_label(kind: str, ref_id: str, detail: dict[str, Any]) -> str:
    fields = {
        "knowledge_base": ("name",),
        "book": ("title",),
        "notebook": ("name",),
        "mastery_path": ("name",),
        "reading_workspace": ("title",),
        "partner": ("name",),
        "partner_group": ("name",),
    }
    for field in fields.get(kind, ()):
        label = str(detail.get(field) or "").strip()
        if label:
            return label
    return ref_id


async def build_course_resource_candidates() -> dict[str, list[dict[str, str]]]:
    """Enumerate attachable resource references, degrading one kind at a time."""
    from deeptutor.services.courses import COURSE_RESOURCE_KINDS

    indexes = await _resource_indexes()
    candidates: dict[str, list[dict[str, str]]] = {}
    for kind in COURSE_RESOURCE_KINDS:
        rows = [
            {"ref_id": ref_id, "label": _candidate_label(kind, ref_id, detail)}
            for ref_id, detail in indexes[kind].items()
        ]
        rows.sort(key=lambda row: (row["label"].casefold(), row["ref_id"]))
        candidates[kind] = rows
    return candidates


async def build_course_state(course_id: str) -> dict[str, Any]:
    """课程全景快照。前端课程页与 course_study capability 的工具共用这一个真相源。"""
    from deeptutor.services.courses import get_course_service

    course = await asyncio.to_thread(get_course_service().get, course_id)
    indexes, session_result = await asyncio.gather(
        _resource_indexes(),
        _session_state(course_id),
    )
    sessions, session_ids = session_result
    question_bank = await _question_bank_state(session_ids)

    resources: list[dict[str, Any]] = []
    for resource in course.resources:
        detail = indexes.get(resource.kind, {}).get(resource.ref_id)
        resources.append(
            {
                **resource.to_dict(),
                "available": detail is not None,
                "detail": dict(detail or {}),
            }
        )

    mastery_paths = [
        dict(indexes["mastery_path"][resource.ref_id])
        for resource in course.resources
        if resource.kind == "mastery_path" and resource.ref_id in indexes["mastery_path"]
    ]
    reading_workspaces = [
        dict(indexes["reading_workspace"][resource.ref_id])
        for resource in course.resources
        if resource.kind == "reading_workspace" and resource.ref_id in indexes["reading_workspace"]
    ]

    weak_categories = question_bank["weak_categories"]
    syllabus_units = []
    for unit in course.syllabus:
        topics = [topic.casefold() for topic in unit.topics if topic]
        wrong_questions = sum(
            _as_int(category.get("wrong"))
            for category in weak_categories
            if (category_name := str(category.get("name") or "").strip().casefold())
            and any(topic in category_name or category_name in topic for topic in topics)
        )
        syllabus_units.append(
            {
                **unit.to_dict(),
                "wrong_questions": wrong_questions,
            }
        )

    next_unit = next(
        (
            {
                "id": unit.id,
                "title": unit.title,
                "position": unit.position,
            }
            for unit in course.syllabus
            if not unit.covered
        ),
        None,
    )
    syllabus = {
        "total": len(course.syllabus),
        "covered": sum(unit.covered for unit in course.syllabus),
        "next": next_unit,
        "units": syllabus_units,
    }

    return {
        "course": course.to_dict(),
        "resources": resources,
        "sessions": sessions,
        "mastery": {"paths": mastery_paths},
        "question_bank": question_bank,
        "syllabus": syllabus,
        "reading": {"workspaces": reading_workspaces},
    }
