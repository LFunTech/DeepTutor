"""原 validate_assignment 触发器的程序等价规则。"""

from uuid import UUID

from deeptutor_enterprise.management.assignment_rules import validate_assignment_relation
from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied
import pytest

SCHOOL_A = UUID("10000000-0000-0000-0000-000000000001")
SCHOOL_B = UUID("10000000-0000-0000-0000-000000000002")


@pytest.mark.parametrize(
    ("application", "role_scope", "assignment_scope", "principal_school", "school"),
    [
        ("oms", "platform", "platform", None, None),
        ("oms", "school", "school", None, SCHOOL_A),
        ("tms", "school", "school", SCHOOL_A, SCHOOL_A),
    ],
)
def test_assignment_relation_accepts_matching_role_and_principal(
    application, role_scope, assignment_scope, principal_school, school
):
    validate_assignment_relation(
        application=application,
        principal_application=application,
        principal_school_id=principal_school,
        role_application=application,
        role_scope_kind=role_scope,
        assignment_scope_kind=assignment_scope,
        assignment_school_id=school,
    )


@pytest.mark.parametrize(
    (
        "principal_application",
        "principal_school",
        "role_application",
        "role_scope",
        "scope",
        "school",
    ),
    [
        ("tms", SCHOOL_A, "tms", "platform", "school", SCHOOL_A),
        ("tms", SCHOOL_B, "tms", "school", "school", SCHOOL_A),
        ("oms", None, "tms", "school", "school", SCHOOL_A),
        (None, None, "tms", "school", "school", SCHOOL_A),
        ("tms", SCHOOL_A, None, None, "school", SCHOOL_A),
    ],
)
def test_assignment_relation_rejects_missing_or_mismatched_facts(
    principal_application, principal_school, role_application, role_scope, scope, school
):
    with pytest.raises(ManagementAuthorizationDenied, match="assignment relation"):
        validate_assignment_relation(
            application="tms",
            principal_application=principal_application,
            principal_school_id=principal_school,
            role_application=role_application,
            role_scope_kind=role_scope,
            assignment_scope_kind=scope,
            assignment_school_id=school,
        )
