"""受控迁移中的 assignment 事实也必须由 Python 校验。"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from deeptutor_enterprise.migrations.runner import MigrationRunner
import pytest

SCHOOL = UUID("10000000-0000-0000-0000-000000000001")
OTHER = UUID("10000000-0000-0000-0000-000000000002")
ASSIGNMENT = UUID("20000000-0000-0000-0000-000000000001")
NOW = datetime.now(timezone.utc)


def _fact(**overrides):
    value = dict(
        application="tms",
        principal_application="tms",
        principal_school_id=SCHOOL,
        role_application="tms",
        role_scope_kind="school",
        scope_kind="school",
        school_id=SCHOOL,
        status="active",
        version=1,
        valid_from=NOW,
        expires_at=NOW + timedelta(hours=1),
        revoked_at=None,
        school_binding_version=1,
    )
    value.update(overrides)
    return value


def test_assignment_migration_accepts_matching_school_and_valid_lifecycle():
    MigrationRunner._validate_management_assignment_snapshot({ASSIGNMENT: _fact()}, before={})
    MigrationRunner._validate_management_assignment_snapshot(
        {ASSIGNMENT: _fact(status="revoked", revoked_at=NOW, version=2)},
        before={ASSIGNMENT: _fact()},
    )


@pytest.mark.parametrize(
    "change",
    [
        {"principal_school_id": OTHER},
        {"role_scope_kind": "platform"},
        {"role_application": None},
        {"status": "future"},
        {"revoked_at": NOW},
        {"version": 0},
        {"expires_at": NOW},
        {"school_binding_version": 0},
    ],
)
def test_assignment_migration_rejects_mismatched_or_unknown_fact(change):
    with pytest.raises(RuntimeError, match="management assignment"):
        MigrationRunner._validate_management_assignment_snapshot(
            {ASSIGNMENT: _fact(**change)}, before={}
        )


def test_assignment_migration_rejects_silent_deletion():
    with pytest.raises(RuntimeError, match="management assignment"):
        MigrationRunner._validate_management_assignment_snapshot({}, before={ASSIGNMENT: _fact()})


@pytest.mark.parametrize(
    "changed",
    [
        {"status": "revoked", "revoked_at": NOW},
        {"status": "revoked", "revoked_at": NOW, "version": 3},
        {"school_id": OTHER, "principal_school_id": OTHER, "version": 2},
    ],
)
def test_assignment_migration_requires_versioned_non_rebinding_transition(changed):
    with pytest.raises(RuntimeError, match="management assignment"):
        MigrationRunner._validate_management_assignment_snapshot(
            {ASSIGNMENT: _fact(**changed)}, before={ASSIGNMENT: _fact()}
        )


def test_assignment_migration_rejects_new_assignment_at_noninitial_version():
    with pytest.raises(RuntimeError, match="management assignment"):
        MigrationRunner._validate_management_assignment_snapshot(
            {ASSIGNMENT: _fact(version=2)}, before={}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("has_binding_column", [False, True])
async def test_assignment_snapshot_supports_initial_and_current_schema(has_binding_column):
    class Cursor:
        def __init__(self, row=None):
            self.row = row

        async def fetchone(self):
            return self.row

        async def fetchall(self):
            return []

    class Connection:
        def __init__(self):
            self.queries = []

        async def execute(self, query, _params=None):
            self.queries.append(query)
            if "to_regclass('management.assignments')" in query:
                return Cursor(("management.assignments",))
            if "FROM pg_attribute" in query:
                return Cursor((has_binding_column,))
            return Cursor()

    connection = Connection()
    assert await MigrationRunner._management_assignment_snapshot(None, connection) == {}
    assignment_queries = [q for q in connection.queries if "FROM management.assignments a" in q]
    assert len(assignment_queries) == 2
    expected = (
        "a.school_binding_version"
        if has_binding_column
        else "NULL::bigint AS school_binding_version"
    )
    assert all(expected in query for query in assignment_queries)
