"""PostgreSQL-backed study course registry."""

from __future__ import annotations

import json
import time
from typing import Any
import uuid

from psycopg.types.json import Jsonb

from deeptutor.persistence.postgres.connection import SyncDatabase
from deeptutor.persistence.postgres.scope import TenantScope
from deeptutor.services.courses import (
    AGENT_NOTES_LIMIT,
    COURSE_RESOURCE_KINDS,
    COURSE_STATUSES,
    INSTRUCTIONS_LIMIT,
    CourseNameConflictError,
    CourseNotFoundError,
    CourseResource,
    CourseResourceNotFoundError,
    StudyCourse,
    SyllabusUnit,
    SyllabusUnitNotFoundError,
    UnknownResourceKindError,
    _clip,
    _parse_resources,
    _parse_syllabus,
)


def _jsonb(value: Any) -> Jsonb:
    return Jsonb(value, dumps=lambda item: json.dumps(item, ensure_ascii=False, allow_nan=False))


class PostgresCourseService:
    """Same domain API as ``CourseService``, stored under tenant/owner RLS."""

    def __init__(self, database: SyncDatabase, scope: TenantScope) -> None:
        if not isinstance(database, SyncDatabase) or not isinstance(scope, TenantScope):
            raise TypeError("SyncDatabase and trusted TenantScope required")
        self.db = database
        self.scope = scope
        self._owner = (scope.tenant_id, scope.user_id)

    @staticmethod
    def _clean_name(value: str) -> str:
        name = " ".join(str(value or "").split()).strip()
        if not name:
            raise ValueError("Course name is required.")
        return name[:60]

    @staticmethod
    def _clean_description(value: str) -> str:
        return str(value or "").strip()[:300]

    @staticmethod
    def _clean_color(value: str, fallback_index: int = 0) -> str:
        from deeptutor.services.courses import COURSE_COLORS

        candidate = str(value or "").strip().upper()
        allowed = {color.upper(): color for color in COURSE_COLORS}
        return allowed.get(candidate, COURSE_COLORS[fallback_index % len(COURSE_COLORS)])

    @staticmethod
    def _assert_unique(courses: list[StudyCourse], name: str, except_id: str = "") -> None:
        folded = name.casefold()
        if any(course.id != except_id and course.name.casefold() == folded for course in courses):
            raise CourseNameConflictError(f"A course named {name!r} already exists.")

    @staticmethod
    def _course_from_row(row: dict[str, Any]) -> StudyCourse:
        created_at = float(row.get("created_at") or time.time())
        return StudyCourse(
            id=str(row.get("id") or ""),
            name=str(row.get("name") or "")[:60],
            description=PostgresCourseService._clean_description(
                str(row.get("description") or "")
            ),
            color=PostgresCourseService._clean_color(str(row.get("color") or "")),
            created_at=created_at,
            updated_at=float(row.get("updated_at") or created_at),
            instructions=_clip(str(row.get("instructions") or ""), INSTRUCTIONS_LIMIT),
            agent_notes=_clip(str(row.get("agent_notes") or ""), AGENT_NOTES_LIMIT),
            default_capability=str(row.get("default_capability") or "").strip(),
            default_persona=str(row.get("default_persona") or "").strip(),
            resources=_parse_resources(row.get("resources")),
            syllabus=_parse_syllabus(row.get("syllabus")),
            status="archived" if str(row.get("status") or "").strip() == "archived" else "active",
            archived_at=float(row.get("archived_at") or 0.0),
        )

    @staticmethod
    def _resources_payload(resources: list[CourseResource]) -> list[dict[str, object]]:
        return [resource.to_dict() for resource in resources]

    @staticmethod
    def _syllabus_payload(units: list[SyllabusUnit]) -> list[dict[str, object]]:
        return [unit.to_dict() for unit in units]

    def _lock_owner(self, connection) -> None:
        key = json.dumps(
            ["deeptutor-courses", *self._owner],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))

    def _load(self, connection, *, for_update: bool = False) -> list[StudyCourse]:
        sql = """
            SELECT id,name,description,color,instructions,agent_notes,
                   default_capability,default_persona,resources,syllabus,status,
                   archived_at,created_at,updated_at
              FROM enterprise.courses
             WHERE tenant_id=%s AND owner_id=%s
        """
        if for_update:
            sql += " FOR UPDATE"
        rows = connection.execute(sql, self._owner).fetchall()
        courses = [self._course_from_row(row) for row in rows]
        return sorted(courses, key=lambda course: (course.created_at, course.name.casefold()))

    def _replace_all(self, connection, courses: list[StudyCourse]) -> None:
        connection.execute(
            "DELETE FROM enterprise.courses WHERE tenant_id=%s AND owner_id=%s",
            self._owner,
        )
        for course in courses:
            connection.execute(
                """
                INSERT INTO enterprise.courses(
                    tenant_id,owner_id,id,name,description,color,instructions,
                    agent_notes,default_capability,default_persona,resources,
                    syllabus,status,archived_at,created_at,updated_at,version
                ) VALUES(
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1
                )
                """,
                (
                    *self._owner,
                    course.id,
                    course.name,
                    course.description,
                    course.color,
                    course.instructions,
                    course.agent_notes,
                    course.default_capability,
                    course.default_persona,
                    _jsonb(self._resources_payload(course.resources)),
                    _jsonb(self._syllabus_payload(course.syllabus)),
                    course.status,
                    course.archived_at,
                    course.created_at,
                    course.updated_at,
                ),
            )

    def list_courses(self) -> list[StudyCourse]:
        with self.db.transaction(self.scope) as connection:
            return self._load(connection)

    def get(self, course_id: str) -> StudyCourse:
        target = str(course_id or "").strip()
        with self.db.transaction(self.scope) as connection:
            for course in self._load(connection):
                if course.id == target:
                    return course
        raise CourseNotFoundError(target)

    def create(
        self,
        *,
        name: str,
        description: str = "",
        color: str = "",
        instructions: str = "",
        default_capability: str = "",
        default_persona: str = "",
    ) -> StudyCourse:
        with self.db.transaction(self.scope) as connection:
            self._lock_owner(connection)
            courses = self._load(connection, for_update=True)
            clean_name = self._clean_name(name)
            self._assert_unique(courses, clean_name)
            now = time.time()
            course = StudyCourse(
                id=f"course_{uuid.uuid4().hex[:12]}",
                name=clean_name,
                description=self._clean_description(description),
                color=self._clean_color(color, len(courses)),
                created_at=now,
                updated_at=now,
                instructions=_clip(instructions, INSTRUCTIONS_LIMIT),
                default_capability=str(default_capability or "").strip()[:64],
                default_persona=str(default_persona or "").strip()[:80],
            )
            courses.append(course)
            self._replace_all(connection, courses)
            return course

    def update(
        self,
        course_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        color: str | None = None,
        instructions: str | None = None,
        default_capability: str | None = None,
        default_persona: str | None = None,
    ) -> StudyCourse:
        target = str(course_id or "").strip()
        with self.db.transaction(self.scope) as connection:
            self._lock_owner(connection)
            courses = self._load(connection, for_update=True)
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            if name is not None:
                clean_name = self._clean_name(name)
                self._assert_unique(courses, clean_name, except_id=target)
                course.name = clean_name
            if description is not None:
                course.description = self._clean_description(description)
            if color is not None:
                course.color = self._clean_color(color)
            if instructions is not None:
                course.instructions = _clip(instructions, INSTRUCTIONS_LIMIT)
            if default_capability is not None:
                course.default_capability = str(default_capability).strip()
            if default_persona is not None:
                course.default_persona = str(default_persona).strip()
            course.updated_at = time.time()
            self._replace_all(connection, courses)
            return course

    def attach_resource(
        self,
        course_id: str,
        *,
        kind: str,
        ref_id: str,
        label: str = "",
    ) -> CourseResource:
        clean_kind = str(kind or "").strip()
        if clean_kind not in COURSE_RESOURCE_KINDS:
            raise UnknownResourceKindError(clean_kind)
        clean_ref = str(ref_id or "").strip()
        if not clean_ref:
            raise ValueError("A resource reference is required.")
        target = str(course_id or "").strip()
        with self.db.transaction(self.scope) as connection:
            self._lock_owner(connection)
            courses = self._load(connection, for_update=True)
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            existing = next(
                (
                    item
                    for item in course.resources
                    if item.kind == clean_kind and item.ref_id == clean_ref
                ),
                None,
            )
            if existing is not None:
                return existing
            resource = CourseResource(
                id=f"res_{uuid.uuid4().hex[:12]}",
                kind=clean_kind,
                ref_id=clean_ref,
                label=(str(label or "").strip() or clean_ref)[:120],
                position=len(course.resources),
                added_at=time.time(),
            )
            course.resources.append(resource)
            course.updated_at = resource.added_at
            self._replace_all(connection, courses)
            return resource

    def detach_resource(self, course_id: str, resource_id: str) -> None:
        target = str(course_id or "").strip()
        wanted = str(resource_id or "").strip()
        with self.db.transaction(self.scope) as connection:
            self._lock_owner(connection)
            courses = self._load(connection, for_update=True)
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            kept = [item for item in course.resources if item.id != wanted]
            if len(kept) == len(course.resources):
                raise CourseResourceNotFoundError(wanted)
            for position, resource in enumerate(kept):
                resource.position = position
            course.resources = kept
            course.updated_at = time.time()
            self._replace_all(connection, courses)

    def append_agent_note(self, course_id: str, note: str) -> StudyCourse:
        clean_note = " ".join(str(note or "").split()).strip()
        if not clean_note:
            raise ValueError("A note is required.")
        target = str(course_id or "").strip()
        with self.db.transaction(self.scope) as connection:
            self._lock_owner(connection)
            courses = self._load(connection, for_update=True)
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            merged = (
                f"{course.agent_notes}\n- {clean_note}".strip()
                if course.agent_notes
                else f"- {clean_note}"
            )
            if len(merged) > AGENT_NOTES_LIMIT:
                merged = merged[-AGENT_NOTES_LIMIT:]
                newline = merged.find("\n")
                if newline != -1:
                    merged = merged[newline + 1 :]
            course.agent_notes = merged.strip()
            course.updated_at = time.time()
            self._replace_all(connection, courses)
            return course

    def set_syllabus(
        self,
        course_id: str,
        units: list[dict[str, object]],
    ) -> StudyCourse:
        target = str(course_id or "").strip()
        with self.db.transaction(self.scope) as connection:
            self._lock_owner(connection)
            courses = self._load(connection, for_update=True)
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            course.syllabus = _parse_syllabus(units)
            course.updated_at = time.time()
            self._replace_all(connection, courses)
            return course

    def set_unit_covered(self, course_id: str, unit_id: str, covered: bool) -> SyllabusUnit:
        target = str(course_id or "").strip()
        wanted = str(unit_id or "").strip()
        with self.db.transaction(self.scope) as connection:
            self._lock_owner(connection)
            courses = self._load(connection, for_update=True)
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            unit = next((item for item in course.syllabus if item.id == wanted), None)
            if unit is None:
                raise SyllabusUnitNotFoundError(wanted)
            unit.covered = bool(covered)
            course.updated_at = time.time()
            self._replace_all(connection, courses)
            return unit

    def set_status(self, course_id: str, status: str) -> StudyCourse:
        clean = str(status or "").strip()
        if clean not in COURSE_STATUSES:
            raise ValueError(f"Unknown course status {clean!r}; expected active or archived.")
        target = str(course_id or "").strip()
        with self.db.transaction(self.scope) as connection:
            self._lock_owner(connection)
            courses = self._load(connection, for_update=True)
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            now = time.time()
            course.status = clean
            course.archived_at = now if clean == "archived" else 0.0
            course.updated_at = now
            self._replace_all(connection, courses)
            return course

    def delete(self, course_id: str) -> None:
        target = str(course_id or "").strip()
        with self.db.transaction(self.scope) as connection:
            self._lock_owner(connection)
            courses = self._load(connection, for_update=True)
            kept = [course for course in courses if course.id != target]
            if len(kept) == len(courses):
                raise CourseNotFoundError(target)
            self._replace_all(connection, kept)


__all__ = ["PostgresCourseService"]
