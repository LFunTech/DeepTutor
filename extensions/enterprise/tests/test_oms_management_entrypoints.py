"""OMS 平台权限未落地前，CLI/SDK 不提供另一条管理写入口。"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from deeptutor_enterprise.cli import parser
from pydantic import TypeAdapter, ValidationError
import pytest

from deeptutor.api.contracts.turn_protocol import PROTOCOL_VERSION, ClientCommand
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


@pytest.mark.parametrize(
    "payload",
    [
        {
            "type": "oms_grant_role",
            "protocol_version": PROTOCOL_VERSION,
            "principal_id": "p-1",
            "role_key": "platform_security_admin",
        },
        {
            "type": "tms_approve_school_admin",
            "protocol_version": PROTOCOL_VERSION,
            "school_id": "school-1",
            "principal_id": "p-1",
        },
        {
            "type": "start_turn",
            "protocol_version": PROTOCOL_VERSION,
            "content": "hello",
            "ops_action": "ops.permissions.manage",
            "target_school_id": "school-1",
        },
    ],
)
def test_websocket_turn_protocol_rejects_management_write_bypass(payload):
    with pytest.raises(ValidationError):
        TypeAdapter(ClientCommand).validate_python(payload)


def test_core_cli_ws_sdk_and_background_do_not_write_management_facts_directly():
    """通用入口不能通过导入企业授权模块或 SQL 表名绕开 Enterprise PEP。"""

    repo_root = Path(__file__).resolve().parents[3]
    forbidden = (
        "deeptutor_enterprise.management",
        "management.assignments",
        "management.principals",
        "management.approval_requests",
        "ops.permissions.manage",
        "tenant.permissions.manage",
    )
    offenders: list[str] = []
    for root_name in ("deeptutor", "deeptutor_cli"):
        root = repo_root / root_name
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            hits = [item for item in forbidden if item in text]
            if hits:
                offenders.append(f"{path.relative_to(repo_root)}: {', '.join(hits)}")
    assert offenders == []
