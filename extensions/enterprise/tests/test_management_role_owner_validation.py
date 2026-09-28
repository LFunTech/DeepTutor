"""迁移 runner 须在撤销数据库角色保护前发现学校 owner 漂移。"""

from uuid import UUID

from deeptutor_enterprise.migrations.runner import MigrationRunner
import pytest

_SCHOOL_A = UUID("10000000-0000-0000-0000-000000000001")
_SCHOOL_B = UUID("10000000-0000-0000-0000-000000000002")
_KEY_A = f"custom_{_SCHOOL_A.hex}_readers"


def _catalog(*, school=_SCHOOL_A, action_school=_SCHOOL_A):
    roles = {("tms", _KEY_A, 1): ("school", False, school)}
    actions = {("tms", _KEY_A, 1, "tenant.members.read", action_school)}
    return roles, actions


def _actions():
    return {("tms", "tenant.members.read"): ("school", False, "active", 1)}


def test_runner_accepts_school_owned_custom_role_and_matching_action():
    MigrationRunner._validate_management_role_catalog_transition(
        ({}, set()), _catalog(), _actions()
    )


@pytest.mark.parametrize(
    "after",
    [
        _catalog(school=None),
        _catalog(school=_SCHOOL_B),
        _catalog(action_school=None),
        _catalog(action_school=_SCHOOL_B),
        ({("oms", "custom_readers", 1): ("platform", False, _SCHOOL_A)}, set()),
    ],
)
def test_runner_rejects_cross_school_or_missing_owner(after):
    with pytest.raises(RuntimeError, match="role catalog transition"):
        MigrationRunner._validate_management_role_catalog_transition(({}, set()), after, _actions())


def test_runner_rejects_school_owner_change_to_existing_version():
    before = _catalog()
    after = _catalog(school=_SCHOOL_B, action_school=_SCHOOL_B)
    with pytest.raises(RuntimeError, match="role catalog transition"):
        MigrationRunner._validate_management_role_catalog_transition(before, after, _actions())


def test_runner_can_recheck_existing_role_owner_facts_during_verify():
    roles, actions = _catalog(action_school=_SCHOOL_B)
    with pytest.raises(RuntimeError, match="role owner"):
        MigrationRunner._validate_management_role_owner_facts(roles, actions)
