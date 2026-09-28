"""课程状态在 PG CHECK 退役前后都由程序拒绝未知值。"""

import pytest

from deeptutor.persistence.postgres.courses import PostgresCourseService
from deeptutor.services.courses import StudyCourse


def test_unknown_persisted_course_status_is_not_silently_reinterpreted_as_active():
    with pytest.raises(ValueError, match="Unknown course status"):
        PostgresCourseService._course_from_row(
            {"id": "c", "name": "课程", "status": "unknown", "resources": [], "syllabus": []}
        )


def test_course_replacement_rejects_invalid_status_before_any_sql():
    class NoSql:
        def execute(self, *args, **kwargs):
            raise AssertionError("invalid status must be rejected before a DELETE")

    service = object.__new__(PostgresCourseService)
    service._owner = ("00000000-0000-0000-0000-000000000001", "owner")
    course = StudyCourse("c", "课程", "", "", 1.0, 1.0, status="unknown")
    with pytest.raises(ValueError, match="Unknown course status"):
        service._replace_all(NoSql(), [course])
