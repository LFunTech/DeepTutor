"""Tests for capability-based access: has_capability_access.

As of the multi-user release only the LLM capability is grantable per user, so
gating is LLM-only; embedding/search are shared admin infrastructure. The same
helper backs the turn-runtime gate and the frontend lock, so they always agree.
"""

from deeptutor.multi_user import model_access
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope


def make_user(tmp_path, role="user"):
    uid = "u_admin" if role == "admin" else "u_alice"
    if role == "tenant_admin":
        uid = "tenant-admin"
    return CurrentUser(
        id=uid,
        username="admin" if role in {"admin", "tenant_admin"} else "alice",
        role=role,
        scope=UserScope(
            kind="admin" if role == "admin" else ("tenant" if role == "tenant_admin" else "user"),
            user_id=uid,
            root=None if role == "tenant_admin" else tmp_path / uid,
            tenant_id="tenant-1" if role == "tenant_admin" else "",
        ),
    )


def _fake_access(llm=None):
    """Build a redacted_model_access return value with the given llm bucket."""
    return lambda _user_id=None: {"llm": list(llm or [])}


def test_admin_always_has_access(tmp_path, monkeypatch):
    # Admins are never gated and must not even consult the grant view.
    def _boom(_user_id=None):
        raise AssertionError("redacted_model_access should not be called for admins")

    monkeypatch.setattr(model_access, "redacted_model_access", _boom)
    token = set_current_user(make_user(tmp_path, role="admin"))
    try:
        assert model_access.has_capability_access("llm") is True
    finally:
        reset_current_user(token)


def test_tenant_admin_uses_deployment_llm_without_user_grant(tmp_path, monkeypatch):
    """A PG tenant administrator can run chat with the deployment model pool.

    ``tenant_admin`` is not the legacy filesystem/global admin, so it must not
    become ``CurrentUser.is_admin``. It still owns tenant account management and
    needs a usable LLM option; otherwise the web shell renders "Feature locked"
    immediately after the bootstrap admin signs in.
    """

    catalog = {
        "services": {
            "llm": {
                "active_profile_id": "profile",
                "active_model_id": "model",
                "profiles": [
                    {
                        "id": "profile",
                        "name": "Shared deployment key",
                        "binding": "dashscope",
                        "api_key": "secret",
                        "base_url": "https://example.invalid/v1",
                        "models": [{"id": "model", "name": "Qwen", "model": "qwen-test"}],
                    }
                ],
            }
        }
    }

    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    monkeypatch.setattr(model_access, "load_grant", lambda _user_id=None: {"models": {"llm": []}})
    token = set_current_user(make_user(tmp_path, role="tenant_admin"))
    try:
        current = model_access.get_current_user()
        assert current.can_manage_accounts is True
        assert current.is_admin is False
        assert model_access.has_capability_access("llm") is True
        options = model_access.allowed_llm_options()
        assert options["active"] == {"profile_id": "profile", "model_id": "model"}
        assert [(item["profile_id"], item["model_id"]) for item in options["options"]] == [
            ("profile", "model")
        ]
        assert "api_key" not in options["options"][0]
        assert "base_url" not in options["options"][0]
        assert model_access.apply_allowed_llm_selection(
            {"profile_id": "profile", "model_id": "model"}
        ) == {"profile_id": "profile", "model_id": "model"}
    finally:
        reset_current_user(token)


def test_user_with_available_model_has_access(tmp_path, monkeypatch):
    monkeypatch.setattr(
        model_access,
        "redacted_model_access",
        _fake_access(llm=[{"profile_id": "p", "model_id": "m", "available": True}]),
    )
    token = set_current_user(make_user(tmp_path, role="user"))
    try:
        assert model_access.has_capability_access("llm") is True
    finally:
        reset_current_user(token)


def test_user_with_unavailable_model_has_no_access(tmp_path, monkeypatch):
    # A granted profile that no longer resolves in the catalog is available=False.
    monkeypatch.setattr(
        model_access,
        "redacted_model_access",
        _fake_access(llm=[{"profile_id": "p", "available": False}]),
    )
    token = set_current_user(make_user(tmp_path, role="user"))
    try:
        assert model_access.has_capability_access("llm") is False
    finally:
        reset_current_user(token)


def test_user_with_empty_grant_has_no_access(tmp_path, monkeypatch):
    monkeypatch.setattr(model_access, "redacted_model_access", _fake_access())
    token = set_current_user(make_user(tmp_path, role="user"))
    try:
        assert model_access.has_capability_access("llm") is False
    finally:
        reset_current_user(token)
