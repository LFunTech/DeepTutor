"""Management 双人审批由程序逻辑保证，不依赖数据库 CHECK/触发器。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import uuid

from deeptutor_enterprise.management.authorization import ManagementIdentity
from deeptutor_enterprise.migrations.runner import MigrationRunner
import psycopg
import pytest

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio

ISSUER = "https://issuer.example"


def _identity(app: str, subject: str, school_id=None, *, version=2) -> ManagementIdentity:
    now = datetime.now(timezone.utc)
    return ManagementIdentity(
        application=app,
        issuer=ISSUER,
        subject=subject,
        school_id=school_id,
        policy_version=version,
        school_binding_version=1 if school_id is not None else None,
        external_active=True,
        external_checked_at=now,
        external_verified_until=now + timedelta(minutes=2),
    )


async def _tenant(connection, school_id: uuid.UUID) -> None:
    await connection.execute(
        "INSERT INTO enterprise.tenants"
        "(id,external_eligibility,auth_epoch,bootstrap_completed,local_enabled,"
        "provisioning_status,recovery_state) "
        "VALUES(%s,'allowed','synthetic',true,true,'ready','normal')",
        (school_id,),
    )
    await connection.execute(
        "INSERT INTO oms.school_bindings"
        "(tenant_id,eduplus_tenant_id,status,verified_at,verified_by,source_ref) "
        "VALUES(%s,101,'verified',now(),'synthetic-verifier','synthetic://school')",
        (school_id,),
    )


async def _principal(connection, app: str, subject: str, school_id=None, *, status="active"):
    principal_id = uuid.uuid4()
    await connection.execute(
        "INSERT INTO management.principals"
        "(id,application,issuer,subject,school_id,status) VALUES(%s,%s,%s,%s,%s,%s)",
        (principal_id, app, ISSUER, subject, school_id, status),
    )
    return principal_id


async def _assignment(connection, app: str, principal_id, role: str, scope: str, school_id=None):
    assignment_id = uuid.uuid4()
    await connection.execute(
        "INSERT INTO management.assignments"
        "(id,application,principal_id,role_key,role_version,scope_kind,school_id,"
        "school_binding_version,valid_from,expires_at,command_id,created_by) "
        "VALUES(%s,%s,%s,%s,1,%s,%s,%s,now()-interval '1 minute',"
        "now()+interval '2 hours',%s,'synthetic')",
        (
            assignment_id,
            app,
            principal_id,
            role,
            scope,
            school_id,
            1 if school_id is not None else None,
            uuid.uuid4(),
        ),
    )
    await connection.execute(
        "UPDATE management.principals SET policy_version=policy_version+1 WHERE id=%s",
        (principal_id,),
    )
    return assignment_id


async def test_sensitive_platform_approval_requires_independent_reviewer_and_is_idempotent(pg_dsn):
    from deeptutor_enterprise.management.approvals import (
        ApprovalConflict,
        CreateApprovalRequestCommand,
        ReviewApprovalCommand,
        create_management_approval_request,
        review_management_approval,
    )

    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        proposer = await _principal(c, "oms", "proposer")
        reviewer = await _principal(c, "oms", "reviewer")
        target = await _principal(c, "oms", "target", status="pending")
        await _assignment(c, "oms", proposer, "platform_security_admin", "platform")
        await _assignment(c, "oms", reviewer, "platform_security_admin", "platform")

    command = CreateApprovalRequestCommand(
        operation="platform_grant",
        target_principal_id=target,
        target_school_id=None,
        expected_target_policy_version=1,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        idempotency_key="platform-grant-1",
        reason="合成敏感平台授权",
        request_id="approval-create-1",
        external_qualification_ref="contract://platform-grant/1",
        external_qualification_version="v1",
    )
    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        created = await create_management_approval_request(
            c, _identity("oms", "proposer"), command
        )
        replay = await create_management_approval_request(
            c, _identity("oms", "proposer"), command
        )
        assert replay.replayed is True
        assert replay.approval_id == created.approval_id
        with pytest.raises(ApprovalConflict, match="idempotency"):
            await create_management_approval_request(
                c,
                _identity("oms", "proposer"),
                CreateApprovalRequestCommand(
                    **{**command.__dict__, "reason": "changed"}
                ),
            )
        with pytest.raises(ApprovalConflict, match="independent"):
            await review_management_approval(
                c,
                _identity("oms", "proposer"),
                ReviewApprovalCommand(
                    approval_id=created.approval_id,
                    decision="approved",
                    expected_target_policy_version=1,
                    reason="self approval",
                    request_id="approval-review-self",
                ),
            )
        approved = await review_management_approval(
            c,
            _identity("oms", "reviewer"),
            ReviewApprovalCommand(
                approval_id=created.approval_id,
                decision="approved",
                expected_target_policy_version=1,
                reason="independent approval",
                request_id="approval-review-1",
            ),
        )
        assert approved.status == "approved"
        assert approved.replayed is False
        replayed_review = await review_management_approval(
            c,
            _identity("oms", "reviewer"),
            ReviewApprovalCommand(
                approval_id=created.approval_id,
                decision="approved",
                expected_target_policy_version=1,
                reason="independent approval",
                request_id="approval-review-1",
            ),
        )
        assert replayed_review.replayed is True


async def test_school_activation_approval_withdraw_and_stale_target_fail_closed(pg_dsn):
    from deeptutor_enterprise.management.approvals import (
        ApprovalConflict,
        CreateApprovalRequestCommand,
        ReviewApprovalCommand,
        WithdrawApprovalCommand,
        create_management_approval_request,
        review_management_approval,
        withdraw_management_approval,
    )

    await MigrationRunner(pg_dsn).apply()
    school = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await _tenant(c, school)
        proposer = await _principal(c, "tms", "school-proposer", school)
        reviewer = await _principal(c, "tms", "school-reviewer", school)
        target = await _principal(c, "tms", "candidate-admin", school, status="pending")
        await _assignment(c, "tms", proposer, "school_admin", "school", school)
        await _assignment(c, "tms", reviewer, "school_admin", "school", school)

    runtime_dsn = single_database_user_dsn(pg_dsn)
    create = CreateApprovalRequestCommand(
        operation="school_activation",
        target_principal_id=target,
        target_school_id=school,
        expected_target_policy_version=1,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        idempotency_key="school-activation-1",
        reason="合成学校激活",
        request_id="school-create-1",
        external_qualification_ref="contract://school/1",
        external_qualification_version="v1",
    )
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        approval = await create_management_approval_request(
            c, _identity("tms", "school-proposer", school), create
        )
        withdrawn = await withdraw_management_approval(
            c,
            _identity("tms", "school-proposer", school),
            WithdrawApprovalCommand(
                approval_id=approval.approval_id,
                reason="校方撤回",
                request_id="school-withdraw-1",
            ),
        )
        assert withdrawn.status == "withdrawn"
        with pytest.raises(ApprovalConflict, match="terminal"):
            await review_management_approval(
                c,
                _identity("tms", "school-reviewer", school),
                ReviewApprovalCommand(
                    approval_id=approval.approval_id,
                    decision="approved",
                    expected_target_policy_version=1,
                    reason="late approve",
                    request_id="school-review-late",
                ),
            )

    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "UPDATE management.principals SET policy_version=policy_version+1 WHERE id=%s",
            (target,),
        )
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        stale = await create_management_approval_request(
            c,
            _identity("tms", "school-proposer", school),
            CreateApprovalRequestCommand(
                **{
                    **create.__dict__,
                    "expected_target_policy_version": 2,
                    "idempotency_key": "school-activation-2",
                    "request_id": "school-create-2",
                }
            ),
        )
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        await c.execute(
            "UPDATE management.principals SET policy_version=policy_version+1 WHERE id=%s",
            (target,),
        )
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school),))
        with pytest.raises(ApprovalConflict, match="policy version"):
            await review_management_approval(
                c,
                _identity("tms", "school-reviewer", school),
                ReviewApprovalCommand(
                    approval_id=stale.approval_id,
                    decision="approved",
                    expected_target_policy_version=2,
                    reason="stale target",
                    request_id="school-review-stale",
                ),
            )


async def test_competing_reviewers_leave_one_terminal_decision(pg_dsn):
    from deeptutor_enterprise.management.approvals import (
        ApprovalConflict,
        CreateApprovalRequestCommand,
        ReviewApprovalCommand,
        create_management_approval_request,
        review_management_approval,
    )

    await MigrationRunner(pg_dsn).apply()
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        proposer = await _principal(c, "oms", "proposer")
        reviewer_a = await _principal(c, "oms", "reviewer-a")
        reviewer_b = await _principal(c, "oms", "reviewer-b")
        target = await _principal(c, "oms", "target", status="pending")
        for principal in (proposer, reviewer_a, reviewer_b):
            await _assignment(c, "oms", principal, "platform_security_admin", "platform")

    runtime_dsn = single_database_user_dsn(pg_dsn)
    async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
        approval = await create_management_approval_request(
            c,
            _identity("oms", "proposer"),
            CreateApprovalRequestCommand(
                operation="delegation_expand",
                target_principal_id=target,
                target_school_id=None,
                expected_target_policy_version=1,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                idempotency_key="delegation-expand-1",
                reason="合成委托扩大",
                request_id="delegation-create-1",
                external_qualification_ref="contract://delegation/1",
                external_qualification_version="v1",
            ),
        )

    async def decide(subject: str, decision: str):
        try:
            async with await psycopg.AsyncConnection.connect(runtime_dsn) as c:
                result = await review_management_approval(
                    c,
                    _identity("oms", subject),
                    ReviewApprovalCommand(
                        approval_id=approval.approval_id,
                        decision=decision,
                        expected_target_policy_version=1,
                        reason=f"{subject}-{decision}",
                        request_id=f"{subject}-{decision}",
                    ),
                )
                return result.status
        except ApprovalConflict:
            return "conflict"

    outcomes = sorted(
        await asyncio.gather(
            decide("reviewer-a", "approved"),
            decide("reviewer-b", "rejected"),
        )
    )
    assert outcomes in (["approved", "conflict"], ["conflict", "rejected"])
    async with await psycopg.AsyncConnection.connect(pg_dsn) as c:
        status = await (
            await c.execute(
                "SELECT status FROM management.approval_requests WHERE id=%s",
                (approval.approval_id,),
            )
        ).fetchone()
    assert status[0] in {"approved", "rejected"}
