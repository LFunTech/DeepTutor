"""OMS 平台权限未落地前，CLI/SDK 不提供另一条管理写入口。"""

from __future__ import annotations

import argparse
import importlib.util

from deeptutor_enterprise.cli import parser

from deeptutor.app.facade import DeepTutorApp


def test_enterprise_cli_has_no_provider_or_oms_management_command():
    root = parser()
    commands = next(
        action.choices for action in root._actions if isinstance(action, argparse._SubParsersAction)
    )
    assert set(commands) == {
        "schema",
        "bootstrap",
        "account",
        "session",
        "serve",
        "confirm-stopped",
        "recovery",
    }
    session_actions = next(
        action.choices for action in commands["session"]._actions if action.dest == "action"
    )
    assert set(session_actions) == {"list", "show", "delete", "rename", "run", "cancel"}


def test_generic_sdk_facade_does_not_publish_platform_management_methods():
    public = {name for name in dir(DeepTutorApp) if not name.startswith("_")}
    assert public.isdisjoint(
        {
            "oms",
            "tms",
            "settings",
            "configure_provider",
            "grant_quota",
            "publish_skill",
            "upsert_secret",
        }
    )


def test_withdrawn_sender_authorization_client_is_not_packaged():
    """旧发送端在线决策端点已撤回，不能误接成 OMS 权限来源。"""

    assert importlib.util.find_spec("deeptutor_enterprise.oms.authorization") is None
