"""受控迁移写委托时，程序应接管旧触发器的关系校验。"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from deeptutor_enterprise.migrations.runner import MigrationRunner
import pytest

SCHOOL = UUID("10000000-0000-0000-0000-000000000001")
DELEGATION = UUID("20000000-0000-0000-0000-000000000001")
NOW = datetime.now(timezone.utc)


def _fact(**overrides):
    values = dict(
        application="tms",
        principal_application="tms",
        principal_school_id=SCHOOL,
        action_application="tms",
        action_status="active",
        action_allowed_scope="school",
        scope_kind="school",
        school_id=SCHOOL,
        status="active",
        version=1,
        valid_from=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    values.update(overrides)
    return values


def test_new_delegation_requires_active_matching_action_and_school():
    MigrationRunner._validate_management_delegation_snapshot({DELEGATION: _fact()}, before={})
    for change in (
        {"action_status": "retired"},
        {"action_allowed_scope": "platform"},
        {"principal_school_id": UUID("30000000-0000-0000-0000-000000000001")},
        {"expires_at": NOW},
    ):
        with pytest.raises(RuntimeError, match="delegation"):
            MigrationRunner._validate_management_delegation_snapshot(
                {DELEGATION: _fact(**change)}, before={}
            )


def test_unchanged_retired_action_is_readable_but_mutation_is_denied():
    old = _fact(action_status="retired")
    MigrationRunner._validate_management_delegation_snapshot({DELEGATION: old})
    MigrationRunner._validate_management_delegation_snapshot(
        {DELEGATION: old}, before={DELEGATION: old}
    )
    with pytest.raises(RuntimeError, match="delegation"):
        MigrationRunner._validate_management_delegation_snapshot(
            {DELEGATION: _fact(action_status="retired", version=2)},
            before={DELEGATION: old},
        )


def test_migration_cannot_silently_delete_delegation():
    with pytest.raises(RuntimeError, match="delegation"):
        MigrationRunner._validate_management_delegation_snapshot({}, before={DELEGATION: _fact()})
