"""已发布 EduPlus2 resolve 响应的学校状态契约。"""

from deeptutor_enterprise.eduplus2.client import normalize_resolve_response
from deeptutor_enterprise.eduplus2.service import EduPlus2AccessService
import pytest


def _published_response(*, subscription_status="subscribed", tenant_status="trial"):
    return {
        "code": 0,
        "data": {
            "verified": True,
            "reason": "ok",
            "version": "security-hash",
            "client": {"client_id": "school-client", "status": "active"},
            "tenant": {
                "tenant_id": 92,
                "tenant_code": "jygjzx",
                "tenant_name": "示例学校",
                "status": tenant_status,
                "subscription_status": subscription_status,
            },
            "app": {"app_id": 11, "app_name": "智能体基座", "status": "active"},
            "oauth": {},
            "policy": {"allowed_usages": ["authorization_code"]},
        },
    }


def test_published_resolve_shape_accepts_trial_and_subscribed():
    resolved = normalize_resolve_response("school-client", _published_response())
    assert resolved["external_tenant_id"] == "92"
    assert resolved["external_tenant_code"] == "jygjzx"
    assert resolved["subscription_status"] == "subscribed"
    assert resolved["tenant_status"] == "trial"
    assert EduPlus2AccessService._is_active(resolved)


@pytest.mark.parametrize("missing", ["status", "subscription_status"])
def test_resolve_does_not_invent_school_or_subscription_status(missing):
    payload = _published_response()
    payload["data"]["tenant"].pop(missing)
    with pytest.raises(RuntimeError, match="missing required fields"):
        normalize_resolve_response("school-client", payload)


def test_resolve_rejects_inactive_school_subscription():
    resolved = normalize_resolve_response(
        "school-client", _published_response(subscription_status="inactive")
    )
    assert not EduPlus2AccessService._is_active(resolved)


@pytest.mark.parametrize("field", ["tenant", "app"])
@pytest.mark.parametrize("invalid", ["school-code", 0, -1, True, 2**63])
def test_resolve_rejects_non_authoritative_or_out_of_range_ids(field, invalid):
    payload = _published_response()
    key = "tenant_id" if field == "tenant" else "app_id"
    payload["data"][field][key] = invalid
    with pytest.raises(RuntimeError, match="identifier"):
        normalize_resolve_response("school-client", payload)


def test_resolve_rejects_string_verified_flag():
    payload = _published_response()
    payload["data"]["verified"] = "false"
    with pytest.raises(RuntimeError, match="verification flag"):
        normalize_resolve_response("school-client", payload)


@pytest.mark.parametrize("missing", ["tenant_status", "app_status", "subscription_status"])
def test_exchange_state_check_fails_closed_for_incomplete_resolver(missing):
    resolved = normalize_resolve_response("school-client", _published_response())
    resolved.pop(missing)
    assert not EduPlus2AccessService._is_active(resolved)
