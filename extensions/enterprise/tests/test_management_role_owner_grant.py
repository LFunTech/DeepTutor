"""授予角色必须在程序中检查学校自定义角色 owner。"""

from uuid import UUID

from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied
from deeptutor_enterprise.management.grants import (
    validate_role_action_owner_for_grant,
    validate_role_owner_for_grant,
)
import pytest

_SCHOOL_A = UUID("10000000-0000-0000-0000-000000000001")
_SCHOOL_B = UUID("10000000-0000-0000-0000-000000000002")


@pytest.mark.parametrize(
    ("application", "school", "role"),
    [
        ("oms", None, ("platform", True, None)),
        ("oms", _SCHOOL_A, ("school", False, None)),
        ("tms", _SCHOOL_A, ("school", True, None)),
        ("tms", _SCHOOL_A, ("school", False, _SCHOOL_A)),
    ],
)
def test_role_owner_allows_matching_scope_and_school(application, school, role):
    validate_role_owner_for_grant(role, application=application, target_school_id=school)


@pytest.mark.parametrize(
    ("application", "school", "role"),
    [
        ("tms", _SCHOOL_B, ("school", False, _SCHOOL_A)),
        ("tms", _SCHOOL_A, ("school", False, None)),
        ("tms", _SCHOOL_A, ("school", True, _SCHOOL_A)),
        ("oms", _SCHOOL_A, ("school", False, _SCHOOL_A)),
        ("oms", None, ("school", False, None)),
    ],
)
def test_role_owner_denies_cross_school_or_inconsistent_role(application, school, role):
    with pytest.raises(ManagementAuthorizationDenied, match="role version or school owner"):
        validate_role_owner_for_grant(role, application=application, target_school_id=school)


def test_role_action_owner_must_match_role_before_assignment_is_created():
    validate_role_action_owner_for_grant(
        [("tenant.members.read", "active", False, _SCHOOL_A)], owner_school_id=_SCHOOL_A
    )
    with pytest.raises(ManagementAuthorizationDenied, match="role action owner"):
        validate_role_action_owner_for_grant(
            [("tenant.members.read", "active", False, _SCHOOL_B)], owner_school_id=_SCHOOL_A
        )
