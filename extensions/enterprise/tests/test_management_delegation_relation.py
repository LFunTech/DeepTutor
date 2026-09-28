"""原 validate_delegation_policy 触发器的程序关系校验。"""

from uuid import UUID

from deeptutor_enterprise.management.authorization import ManagementAuthorizationDenied
from deeptutor_enterprise.management.delegation_rules import validate_delegation_relation
import pytest

SCHOOL_A = UUID("10000000-0000-0000-0000-000000000001")
SCHOOL_B = UUID("10000000-0000-0000-0000-000000000002")


@pytest.mark.parametrize(
    ("application", "principal_school", "action_scope", "scope", "school"),
    [
        ("oms", None, "platform", "platform", None),
        ("oms", None, "both", "school", SCHOOL_A),
        ("tms", SCHOOL_A, "school", "school", SCHOOL_A),
    ],
)
def test_delegation_relation_accepts_matching_action_and_principal(
    application, principal_school, action_scope, scope, school
):
    validate_delegation_relation(
        application=application,
        principal_application=application,
        principal_school_id=principal_school,
        action_application=application,
        action_status="active",
        action_allowed_scope=action_scope,
        delegation_scope_kind=scope,
        delegation_school_id=school,
    )


@pytest.mark.parametrize(
    (
        "principal_app",
        "principal_school",
        "action_app",
        "action_status",
        "action_scope",
        "scope",
        "school",
    ),
    [
        ("tms", SCHOOL_B, "tms", "active", "school", "school", SCHOOL_A),
        ("tms", SCHOOL_A, "tms", "active", "platform", "school", SCHOOL_A),
        ("tms", SCHOOL_A, "tms", "retired", "school", "school", SCHOOL_A),
        ("tms", SCHOOL_A, None, None, None, "school", SCHOOL_A),
        ("oms", None, "tms", "active", "both", "school", SCHOOL_A),
        ("tms", SCHOOL_A, "tms", "active", "school", "platform", None),
        ("tms", SCHOOL_A, "tms", "active", "both", "school", SCHOOL_A),
    ],
)
def test_delegation_relation_rejects_missing_or_mismatched_facts(
    principal_app, principal_school, action_app, action_status, action_scope, scope, school
):
    with pytest.raises(ManagementAuthorizationDenied, match="delegation relation"):
        validate_delegation_relation(
            application="tms",
            principal_application=principal_app,
            principal_school_id=principal_school,
            action_application=action_app,
            action_status=action_status,
            action_allowed_scope=action_scope,
            delegation_scope_kind=scope,
            delegation_school_id=school,
        )


def test_retired_action_is_historical_read_fact_but_cannot_be_written():
    facts = dict(
        application="tms",
        principal_application="tms",
        principal_school_id=SCHOOL_A,
        action_application="tms",
        action_status="retired",
        action_allowed_scope="school",
        delegation_scope_kind="school",
        delegation_school_id=SCHOOL_A,
    )
    validate_delegation_relation(**facts, for_write=False)
    with pytest.raises(ManagementAuthorizationDenied, match="delegation relation"):
        validate_delegation_relation(**facts, for_write=True)
