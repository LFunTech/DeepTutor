"""EduPlus2 receiver 持久值域由程序校验，不能依赖数据库 CHECK。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
import uuid

from deeptutor_enterprise.migrations.runner import MigrationRunner
from deeptutor_enterprise.scope import TenantScope
from deeptutor_enterprise.stores.postgres.connection import Database
from jose import jwt
from psycopg.types.json import Jsonb
import pytest

from tests.fixtures.postgres import single_database_user_dsn

pytestmark = pytest.mark.asyncio

SIGNING_KEY = "s" * 48
EDUPLUS2_KEY = "e" * 48
BOOTSTRAP_SECRET = "b" * 48
ISSUER = "https://eduplus2.test"


@pytest.fixture
async def enterprise_db(pg_dsn):
    await MigrationRunner(pg_dsn).apply()
    async with Database(
        single_database_user_dsn(pg_dsn), resource="eduplus2-value-validation-test"
    ) as db:
        yield db


@pytest.fixture
async def identity(enterprise_db):
    from deeptutor_enterprise.identity.service import IdentityService

    tenant_id = str(uuid.uuid4())
    service = IdentityService(
        enterprise_db,
        tenant_id=tenant_id,
        signing_key=SIGNING_KEY,
        auth_epoch="epoch-eduplus2-values",
        bootstrap_secret=BOOTSTRAP_SECRET,
        token_seconds=900,
    )
    await service.bootstrap("admin", "long-password-1", secret=BOOTSTRAP_SECRET)
    return service


def user_jwt(*, tid: str = "tenant-a", eui: str, azp: str = "client-a", sub: str | None = None):
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": "eduplus2-api",
            "tid": tid,
            "eui": eui,
            "sub": sub or f"sub-{eui}",
            "eit": "teacher",
            "azp": azp,
            "iat": now,
            "exp": now + 600,
            "jti": f"jti-{uuid.uuid4().hex}",
        },
        EDUPLUS2_KEY,
        algorithm="HS256",
        headers={"kid": "test-kid"},
    )


def service_with_clients(enterprise_db, identity, *, with_permission: bool = False):
    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import (
        StaticEduPlus2PermissionClient,
        StaticEduPlus2ProfileClient,
        StaticEduPlus2Resolver,
    )

    profile_client = None
    permission_client = None
    if with_permission:
        profile_client = StaticEduPlus2ProfileClient(
            {
                ("tenant-a", "u-permission"): {
                    "external_tenant_id": "tenant-a",
                    "external_user_id": "u-permission",
                    "external_subject": "sub-u-permission",
                    "external_identity_type": "teacher",
                    "display_name": "权限老师",
                    "status": "active",
                    "version": "profile-v1",
                }
            }
        )
        permission_client = StaticEduPlus2PermissionClient(
            {
                ("tenant-a", "u-permission", "client-a", "app-math"): {
                    "allowed": True,
                    "reason": "ok",
                    "allowed_usages": ["deeptutor.chat"],
                    "scopes": ["chat"],
                    "version": "permission-v1",
                    "expires_at": (
                        datetime.now(timezone.utc) + timedelta(days=30)
                    ).isoformat(),
                }
            }
        )
    return EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=StaticEduPlus2Resolver(
            {
                "client-a": {
                    "client_id": "client-a",
                    "external_tenant_id": "tenant-a",
                    "external_tenant_name": "学校 A",
                    "external_app_id": "app-math",
                    "external_app_name": "数学应用",
                    "status": "active",
                    "subscription_status": "active",
                    "policy": {"scopes": ["chat"]},
                    "version": "resolve-v1",
                }
            }
        ),
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
        allowed_clients=(
            {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "internal_tenant_id": identity.tenant_id,
                "source": "env_allowlist",
                "status": "active",
            },
        ),
        profile_client=profile_client,
        permission_client=permission_client,
    )


async def drop_constraints(c, table: str, *names: str) -> None:
    for name in names:
        await c.execute(f"ALTER TABLE eduplus2.{table} DROP CONSTRAINT IF EXISTS {name}")


async def test_exchange_rejects_unknown_registration_and_binding_values_without_db_checks(
    enterprise_db, identity
):
    service = service_with_clients(enterprise_db, identity)
    await service.exchange_user_jwt(user_jwt(eui="u-registration"), request_id="req-seed")

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await drop_constraints(
            c,
            "external_client_registrations",
            "external_client_registrations_provider_check",
            "external_client_registrations_registered_by_surface_check",
            "external_client_registrations_status_check",
        )
        await drop_constraints(
            c,
            "identity_bindings",
            "identity_bindings_provider_check",
            "identity_bindings_status_check",
        )
        await c.execute(
            """
            UPDATE eduplus2.external_client_registrations
               SET provider='future-provider'
             WHERE client_id='client-a'
            """
        )
    with pytest.raises(RuntimeError, match="registration provider"):
        await service.exchange_user_jwt(user_jwt(eui="u-registration-2"), request_id="req-provider")

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await c.execute(
            """
            UPDATE eduplus2.external_client_registrations
               SET provider='eduplus2', registered_by_surface='future-surface'
             WHERE client_id='client-a'
            """
        )
    with pytest.raises(RuntimeError, match="registration surface"):
        await service.exchange_user_jwt(user_jwt(eui="u-registration-3"), request_id="req-surface")

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await c.execute(
            """
            UPDATE eduplus2.external_client_registrations
               SET registered_by_surface='env_allowlist', status='future-status'
             WHERE client_id='client-a'
            """
        )
    with pytest.raises(RuntimeError, match="registration status"):
        await service.exchange_user_jwt(user_jwt(eui="u-registration-4"), request_id="req-status")

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await c.execute(
            """
            UPDATE eduplus2.external_client_registrations
               SET status='active'
             WHERE client_id='client-a'
            """
        )
        await c.execute(
            """
            UPDATE eduplus2.identity_bindings
               SET provider='future-provider'
             WHERE external_user_id='u-registration'
            """
        )
    with pytest.raises(RuntimeError, match="identity binding provider"):
        await service.exchange_user_jwt(user_jwt(eui="u-registration"), request_id="req-binding-provider")

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await c.execute(
            """
            UPDATE eduplus2.identity_bindings
               SET provider='eduplus2'
             WHERE external_user_id='u-registration'
            """
        )
        await c.execute(
            """
            UPDATE eduplus2.identity_bindings
               SET status='future-status'
             WHERE external_user_id='u-registration'
            """
        )
    with pytest.raises(RuntimeError, match="identity binding status"):
        await service.exchange_user_jwt(user_jwt(eui="u-registration"), request_id="req-binding")


async def test_auto_registration_rejects_unknown_active_registration_for_same_target_without_db_check(
    enterprise_db, identity
):
    service = service_with_clients(enterprise_db, identity)
    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await drop_constraints(
            c,
            "external_client_registrations",
            "external_client_registrations_provider_check",
            "external_client_registrations_status_check",
        )
        await c.execute(
            """
            INSERT INTO eduplus2.external_client_registrations(
              tenant_id,id,provider,client_id,external_tenant_id,external_app_id,
              internal_tenant_id,registered_by_surface,status,policy_snapshot
            ) VALUES(%s,%s,'future-provider','client-other','tenant-a','app-math',
                     %s,'env_allowlist','active',%s)
            """,
            (identity.tenant_id, str(uuid.uuid4()), identity.tenant_id, Jsonb({})),
        )

    with pytest.raises(RuntimeError, match="registration provider"):
        await service.exchange_user_jwt(user_jwt(eui="u-target-conflict"), request_id="req-conflict")


async def test_token_permission_snapshot_rejects_unknown_provider_without_db_check(
    enterprise_db, identity
):
    service = service_with_clients(enterprise_db, identity, with_permission=True)
    exchanged = await service.exchange_user_jwt(
        user_jwt(eui="u-permission", sub="sub-u-permission"), request_id="req-permission"
    )

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await drop_constraints(c, "permission_snapshots", "permission_snapshots_provider_check")
        await c.execute(
            """
            UPDATE eduplus2.permission_snapshots
               SET provider='future-provider', updated_at=now() - interval '2 hours'
             WHERE external_user_id='u-permission'
            """
        )

    with pytest.raises(RuntimeError, match="permission snapshot provider"):
        await service.ensure_token_allowed(exchanged["dt_token"])


async def test_profile_snapshot_status_is_validated_before_persisting_without_db_check(
    enterprise_db, identity
):
    from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
    from deeptutor_enterprise.eduplus2.testing import (
        StaticEduPlus2PermissionClient,
        StaticEduPlus2Resolver,
    )

    class FutureStatusProfileClient:
        async def fetch_profile(
            self,
            *,
            external_tenant_id: str,
            external_user_id: str,
            external_subject: str,
            client_id: str,
            external_app_id: str,
        ) -> dict:
            return {
                "external_tenant_id": external_tenant_id,
                "external_user_id": external_user_id,
                "external_subject": external_subject,
                "external_identity_type": "teacher",
                "display_name": "未知状态老师",
                "status": "future-status",
                "version": "profile-future",
                "summary": {"status": "future-status"},
            }

    service = EduPlus2AccessService(
        enterprise_db,
        identity=identity,
        resolver=StaticEduPlus2Resolver(
            {
                "client-a": {
                    "client_id": "client-a",
                    "external_tenant_id": "tenant-a",
                    "external_app_id": "app-math",
                    "status": "active",
                    "subscription_status": "active",
                    "policy": {"scopes": ["chat"]},
                    "version": "resolve-profile-future",
                }
            }
        ),
        eduplus2_signing_key=EDUPLUS2_KEY,
        eduplus2_issuer=ISSUER,
        allowed_clients=(
            {
                "client_id": "client-a",
                "external_tenant_id": "tenant-a",
                "external_app_id": "app-math",
                "internal_tenant_id": identity.tenant_id,
                "source": "env_allowlist",
                "status": "active",
            },
        ),
        profile_client=FutureStatusProfileClient(),
        permission_client=StaticEduPlus2PermissionClient(
            {
                ("tenant-a", "u-profile-future", "client-a", "app-math"): {
                    "allowed": True,
                    "reason": "ok",
                    "allowed_usages": ["deeptutor.chat"],
                    "scopes": ["chat"],
                    "version": "permission-profile-future",
                }
            }
        ),
    )
    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await drop_constraints(c, "profile_snapshots", "profile_snapshots_status_check")

    with pytest.raises(ValueError, match="profile snapshot status"):
        await service.exchange_user_jwt(
            user_jwt(eui="u-profile-future", sub="sub-u-profile-future"),
            request_id="req-profile-future",
        )


async def test_revocation_state_rejects_unknown_target_and_shape_without_db_checks(
    enterprise_db, identity
):
    service = service_with_clients(enterprise_db, identity)
    exchanged = await service.exchange_user_jwt(user_jwt(eui="u-revocation"), request_id="req-rev")

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await drop_constraints(
            c,
            "revocation_state",
            "revocation_state_target_kind_check",
            "revocation_state_check",
            "revocation_state_check1",
            "revocation_state_check2",
            "revocation_state_check3",
            "revocation_state_check4",
        )
        await c.execute(
            """
            INSERT INTO eduplus2.revocation_events(
              tenant_id,event_id,event_type,target_kind,external_tenant_id,
              processing_status,payload_summary
            ) VALUES(%s,'evt-invalid-revocation-kind','tenant.revoked','tenant','tenant-a','applied',%s)
            """,
            (identity.tenant_id, Jsonb({"seed": True})),
        )
        await c.execute(
            """
            INSERT INTO eduplus2.revocation_state(
              tenant_id,target_kind,external_tenant_id,event_id,active
            ) VALUES(%s,'future-kind','tenant-a','evt-invalid-revocation-kind',true)
            """,
            (identity.tenant_id,),
        )
    with pytest.raises(RuntimeError, match="revocation target kind"):
        await service.ensure_token_allowed(exchanged["dt_token"])

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await c.execute("DELETE FROM eduplus2.revocation_state WHERE target_kind='future-kind'")
        await c.execute(
            """
            INSERT INTO eduplus2.revocation_state(
              tenant_id,target_kind,external_tenant_id,event_id,active
            ) VALUES(%s,'user','tenant-a','evt-invalid-revocation-kind',true)
            """,
            (identity.tenant_id,),
        )
    with pytest.raises(RuntimeError, match="revocation target shape"):
        await service.ensure_token_allowed(exchanged["dt_token"])


async def test_revocation_event_duplicate_rejects_unknown_persisted_values_without_db_checks(
    enterprise_db, identity
):
    service = service_with_clients(enterprise_db, identity)
    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await drop_constraints(
            c,
            "revocation_events",
            "revocation_events_processing_status_check",
            "revocation_events_target_kind_check",
        )
        await c.execute(
            """
            INSERT INTO eduplus2.revocation_events(
              tenant_id,event_id,event_type,target_kind,processing_status,payload_summary
            ) VALUES(%s,'evt-invalid-processing','user.revoked','user','future-status',%s)
            """,
            (identity.tenant_id, Jsonb({"seed": True})),
        )
    with pytest.raises(RuntimeError, match="revocation processing status"):
        await service.apply_revocation_event(
            {"event_id": "evt-invalid-processing", "event_type": "user.revoked"},
            request_id="req-invalid-processing",
        )

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await c.execute(
            """
            UPDATE eduplus2.revocation_events
               SET target_kind='future-kind', processing_status='applied'
             WHERE event_id='evt-invalid-processing'
            """
        )
    with pytest.raises(RuntimeError, match="revocation target kind"):
        await service.apply_revocation_event(
            {"event_id": "evt-invalid-processing", "event_type": "user.revoked"},
            request_id="req-invalid-target",
        )


async def test_audit_result_is_validated_on_write_and_projection_without_db_check(
    enterprise_db, identity
):
    service = service_with_clients(enterprise_db, identity)
    exchanged = await service.exchange_user_jwt(user_jwt(eui="u-audit"), request_id="req-audit")

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await drop_constraints(c, "audit_events", "audit_events_result_check")

    with pytest.raises(ValueError, match="audit result"):
        await service.record_refresh_audit(
            exchanged["dt_token"], request_id="req-bad-audit", reason="test", result="future-result"
        )

    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await c.execute(
            """
            INSERT INTO eduplus2.audit_events(
              tenant_id,id,event_kind,result,summary
            ) VALUES(%s,%s,'manual.bad','future-result',%s)
            """,
            (identity.tenant_id, str(uuid.uuid4()), Jsonb({"seed": True})),
        )
    with pytest.raises(RuntimeError, match="audit result"):
        await service.query_audit_events({"event_kind": "manual.bad"})


async def test_audit_export_format_is_validated_without_db_check(enterprise_db, identity):
    service = service_with_clients(enterprise_db, identity)
    async with enterprise_db.transaction(TenantScope(identity.tenant_id, "@test")) as c:
        await drop_constraints(
            c,
            "audit_export_jobs",
            "audit_export_jobs_format_check",
            "audit_export_jobs_status_check",
        )

    with pytest.raises(ValueError, match="unsupported audit export format"):
        await service.create_audit_export({}, export_format="xml", actor_id="auditor")

    created = await service.create_audit_export({}, export_format="csv", actor_id="auditor")
    assert created["format"] == "csv"
    assert created["status"] == "completed"
