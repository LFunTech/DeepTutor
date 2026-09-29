"""由已验签 EduPlus2 JWT 和 Webhook 建立的学校事实构造 TMS 本人身份。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from ..scope import TenantScope
from .authorization import ManagementIdentity


class TmsAuthenticationDenied(PermissionError):
    """JWT 无法作为可信 TMS 本人身份。"""


class TmsSchoolDenied(PermissionError):
    """JWT 身份未绑定当前已订阅学校/应用。"""


def _eduplus2_token_guard(enterprise, verifier):
    from ..eduplus2.service import EduPlus2AccessService

    return EduPlus2AccessService(
        enterprise.db,
        identity=enterprise.identity,
        resolver=getattr(enterprise, "eduplus2_resolver", None),
        jwt_verifier=verifier,
        dt_token_seconds=getattr(enterprise, "eduplus2_dt_token_seconds", 900),
        allowed_clients=getattr(enterprise, "eduplus2_allowed_clients", ()),
        profile_client=getattr(enterprise, "eduplus2_profile_client", None),
        permission_client=getattr(enterprise, "eduplus2_permission_client", None),
        audit_export_storage_ref=getattr(
            enterprise,
            "eduplus2_audit_export_storage_ref",
            "db://eduplus2/audit-export",
        ),
        revocation_cache_seconds=getattr(enterprise, "eduplus2_revocation_cache_ttl_seconds", 30),
    )


async def _claims_from_tms_bearer(enterprise, token: str, *, verifier, issuer: str) -> dict:
    try:
        verified = await verifier.verify(token)
        return dict(verified.claims)
    except PermissionError:
        pass
    try:
        await enterprise.identity.authenticate(token)
        claims = jwt.get_unverified_claims(token)
    except (PermissionError, JWTError, ValueError, KeyError, TypeError):
        raise TmsAuthenticationDenied("TMS bearer token is invalid") from None
    eduplus2 = claims.get("eduplus2")
    if not isinstance(eduplus2, dict):
        raise TmsAuthenticationDenied("TMS bearer token is invalid")
    try:
        await _eduplus2_token_guard(enterprise, verifier).ensure_token_allowed(token)
    except (PermissionError, JWTError, ValueError, KeyError, TypeError):
        raise TmsAuthenticationDenied("TMS bearer token is invalid") from None
    return {
        "iss": issuer,
        "sub": str(eduplus2.get("external_subject") or "").strip(),
        "azp": str(eduplus2.get("azp") or "").strip(),
        "tid": str(eduplus2.get("external_tenant_id") or "").strip(),
        "exp": claims.get("exp"),
    }


async def trusted_tms_identity_from_token(enterprise, token: str) -> ManagementIdentity:
    """只用 OIDC 签名身份、已验签 Webhook PG 投影和本地权限版本。

    不调用 online resolve，也不信任 body/header 中的学校或角色。``azp``
    必须等于该学校目标应用由 Webhook 登记的 active client。
    """

    verifier = getattr(enterprise, "eduplus2_verifier", None)
    issuer = str(getattr(enterprise, "eduplus2_issuer", "") or "").strip()
    if not verifier or not getattr(enterprise, "eduplus2_lifecycle_receiver_enabled", False):
        raise RuntimeError("TMS identity verifier is unavailable")
    if not issuer:
        raise RuntimeError("TMS school application is unavailable")
    if not isinstance(token, str) or not token or len(token) > 16_384:
        raise TmsAuthenticationDenied("TMS bearer token is missing")
    claims = await _claims_from_tms_bearer(enterprise, token, verifier=verifier, issuer=issuer)
    claim_issuer = str(claims.get("iss") or "").strip()
    subject = str(claims.get("sub") or "").strip()
    client_id = str(claims.get("azp") or "").strip()
    external_school = str(claims.get("tid") or "").strip()
    if (
        claim_issuer != issuer
        or not 1 <= len(subject) <= 255
        or not 1 <= len(client_id) <= 255
        or not external_school.isascii()
        or not external_school.isdecimal()
        or not 0 < int(external_school) < 2**63
    ):
        raise TmsAuthenticationDenied("TMS identity claims are invalid")
    owner = enterprise.deployment.tenant_id
    async with enterprise.db.transaction(TenantScope(str(owner), "@tms-identity")) as c:
        binding = await (
            await c.execute(
                "SELECT b.tenant_id,b.version FROM oms.school_bindings b "
                "JOIN enterprise.tenants t ON t.id=b.tenant_id "
                "WHERE b.eduplus_tenant_id=%s AND b.status='verified' "
                "AND t.external_tid=%s "
                "AND t.recovery_state='normal'",
                (int(external_school), external_school),
            )
        ).fetchone()
        if not binding:
            raise TmsSchoolDenied("TMS school binding is not available")
        school_id = binding["tenant_id"]
        await c.execute("SELECT set_config('app.tenant_id',%s,true)", (str(school_id),))
        registrations = await (
            await c.execute(
                "SELECT p.external_app_id FROM eduplus2.external_client_registrations r "
                "JOIN eduplus2.webhook_school_state p "
                "ON p.tenant_id=%s AND p.school_id=r.internal_tenant_id "
                "AND p.external_tenant_id=%s "
                "AND p.external_app_id::text=r.external_app_id "
                "AND p.binding_version=%s "
                "JOIN eduplus2.webhook_school_controls k "
                "ON (k.tenant_id,k.school_id,k.external_app_id)="
                "(p.tenant_id,p.school_id,p.external_app_id) AND NOT k.frozen "
                "WHERE r.tenant_id=%s AND r.internal_tenant_id=%s "
                "AND r.client_id=%s AND r.external_tenant_id=%s "
                "AND r.status='active' AND p.eligibility='allowed' "
                "AND p.onboarding_event_id IS NOT NULL "
                "AND p.onboarding_completed_at IS NOT NULL LIMIT 2",
                (
                    owner,
                    int(external_school),
                    binding["version"],
                    school_id,
                    school_id,
                    client_id,
                    external_school,
                ),
            )
        ).fetchall()
        if len(registrations) != 1:
            raise TmsSchoolDenied("TMS application client is not registered")
        app_id = registrations[0]["external_app_id"]
        await c.execute("SELECT set_config('app.management_app','tms',true)")
        principal = await (
            await c.execute(
                "SELECT policy_version FROM management.principals "
                "WHERE application='tms' AND issuer=%s AND subject=%s AND school_id=%s",
                (claim_issuer, subject, school_id),
            )
        ).fetchone()
    now = datetime.now(timezone.utc)
    expiration_epoch = claims.get("exp")
    if type(expiration_epoch) is not int or expiration_epoch > 253402300799:
        raise TmsAuthenticationDenied("TMS bearer token expiry is invalid")
    verified_until = min(
        datetime.fromtimestamp(min(expiration_epoch, int(now.timestamp()) + 30), timezone.utc),
        now + timedelta(seconds=30),
    )
    if verified_until <= now:
        raise TmsAuthenticationDenied("TMS bearer token expired")
    return ManagementIdentity(
        application="tms",
        issuer=claim_issuer,
        subject=subject,
        school_id=school_id,
        policy_version=principal["policy_version"] if principal else 1,
        school_binding_version=binding["version"],
        external_active=True,
        external_checked_at=now,
        external_verified_until=verified_until,
        webhook_app_id=app_id,
    )
