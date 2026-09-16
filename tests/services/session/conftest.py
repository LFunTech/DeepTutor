from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope

pytest_plugins = ("tests.fixtures.postgres",)


@pytest.fixture(autouse=True)
def _session_tests_authenticated_owner(tmp_path: Path):
    """Legacy session-unit tests now run under an explicit synthetic owner.

    Default production entrypoints require PostgreSQL identity.  The remaining
    direct SQLite store tests are legacy/offline fixtures, so they get a local
    authenticated owner explicitly instead of depending on the removed implicit
    local-admin fallback.
    """

    root = tmp_path / "owner"
    root.mkdir(parents=True, exist_ok=True)
    token = set_current_user(
        CurrentUser(
            id="session-test-owner",
            username="session-test-owner",
            role="admin",
            scope=UserScope(kind="user", user_id="session-test-owner", root=root),
        )
    )
    try:
        yield
    finally:
        reset_current_user(token)
