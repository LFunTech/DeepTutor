import importlib.util
import subprocess
import sys
from types import SimpleNamespace

import pytest


def test_scoped_providers_never_construct_local_store_and_reset():
    assert importlib.util.find_spec("deeptutor.core.providers"), "显式 provider seam 尚未实现"
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.services.session import get_session_store

    store = object()
    provider = SimpleNamespace(get=lambda: store)
    with provider_context(ApplicationProviders(store=provider)):
        assert get_session_store() is store
        with pytest.raises(RuntimeError, match="configured"):
            from deeptutor.app.container import get_application_container

            get_application_container()


def test_sdk_does_not_create_notebook_until_requested(monkeypatch):
    from deeptutor.app import container as app_container
    from deeptutor.app import facade

    monkeypatch.setattr(
        app_container,
        "get_application_container",
        lambda: SimpleNamespace(turns=None, capability_registry=None),
    )

    def forbidden():
        raise AssertionError("不应构造 notebook")

    monkeypatch.setattr(facade, "get_notebook_manager", forbidden)
    app = facade.DeepTutorApp()
    with pytest.raises(AssertionError, match="notebook"):
        _ = app.notebooks


def test_operation_id_preserved():
    from deeptutor.core.turn_request import TurnRequest

    request = TurnRequest(content="text", operation_id="request-1")
    assert request.to_payload()["operation_id"] == "request-1"


def test_import_llm_config_does_not_read_runtime_files():
    code = """
from unittest.mock import patch
from deeptutor.services import config
with patch.object(config, 'resolve_llm_runtime_config', side_effect=AssertionError('implicit config read')) as read:
    import deeptutor.services.llm.config
    assert read.call_count == 0, 'LLM module import reads local runtime settings'
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_configured_scope_requires_identity_and_cannot_resolve_files():
    from deeptutor.core.providers import ApplicationProviders, provider_context
    from deeptutor.multi_user.context import get_current_user, reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.multi_user.paths import get_current_path_service

    with provider_context(ApplicationProviders()):
        with pytest.raises(PermissionError):
            get_current_user()
        user = CurrentUser(
            id="u",
            username="u",
            role="user",
            scope=UserScope(kind="tenant", user_id="u", root=None, tenant_id="t"),
        )
        token = set_current_user(user)
        try:
            assert get_current_user() is user
            with pytest.raises(RuntimeError, match="local"):
                get_current_path_service()
        finally:
            reset_current_user(token)
