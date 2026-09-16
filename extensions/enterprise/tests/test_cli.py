import asyncio
import importlib.util
import json
import uuid

import pytest


def test_cli_schema_bootstrap_and_accounts(pg_dsn, monkeypatch, tmp_path, capsys):
    assert importlib.util.find_spec("deeptutor_enterprise.cli"), "企业 CLI 尚未实现"
    from deeptutor_enterprise.cli import main

    deployment = {
        "version": 1,
        "tenant_id": str(uuid.uuid4()),
        "resource": "cli-test",
        "database_secret": "env:CLI_DB",
        "signing_secret": "env:CLI_SIGN",
        "auth_epoch_secret": "env:CLI_EPOCH",
        "bootstrap_secret": "env:CLI_BOOT",
        "origins": ["https://school.example"],
        "models": [
            {
                "profile_id": "chat",
                "model_id": "primary",
                "model": "model",
                "base_url": "https://model.example/v1",
                "secret": "env:CLI_MODEL",
                "allowed_roles": ["user", "tenant_admin"],
            }
        ],
    }
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(deployment))
    for name, value in {
        "CLI_DB": pg_dsn.replace("user=postgres", "user=dt_enterprise_app"),
        "CLI_MIGRATION": pg_dsn,
        "CLI_SIGN": "s" * 48,
        "CLI_EPOCH": "epoch-1",
        "CLI_BOOT": "b" * 48,
        "CLI_PASSWORD": "long-password-1",
        "CLI_MODEL": "model-secret",
    }.items():
        monkeypatch.setenv(name, value)
    prefix = ["--config", str(path)]
    assert main(prefix + ["schema", "plan", "--dsn-env", "CLI_MIGRATION"]) == 0
    assert main(prefix + ["schema", "apply", "--dsn-env", "CLI_MIGRATION"]) == 0
    assert main(prefix + ["schema", "verify", "--dsn-env", "CLI_MIGRATION"]) == 0
    assert (
        main(prefix + ["bootstrap", "--username", "admin", "--password-env", "CLI_PASSWORD"]) == 0
    )
    assert (
        main(prefix + ["bootstrap", "--username", "admin", "--password-env", "CLI_PASSWORD"]) == 0
    )
    output = capsys.readouterr().out
    for secret in ["long-password-1", "s" * 48, "b" * 48, "model-secret"]:
        assert secret not in output
    with pytest.raises(SystemExit):
        main(prefix + ["bootstrap", "--username", "admin", "--password", "inline-forbidden"])

    async def identity_call(action, *args):
        from deeptutor_enterprise.identity.service import IdentityService
        from deeptutor_enterprise.stores.postgres.connection import Database

        async with Database(
            pg_dsn.replace("user=postgres", "user=dt_enterprise_app"), resource="cli-test"
        ) as db:
            identity = IdentityService(
                db,
                tenant_id=deployment["tenant_id"],
                signing_key="s" * 48,
                auth_epoch="epoch-1",
                bootstrap_secret=None,
            )
            if action == "login":
                return await identity.login(*args, client="cli-regression")
            return await identity.authenticate(*args)

    admin_token = asyncio.run(identity_call("login", "admin", "long-password-1"))
    monkeypatch.setenv("CLI_ADMIN", admin_token)
    monkeypatch.setenv("CLI_USER_PASSWORD", "ordinary-password-1")
    assert (
        main(
            prefix
            + [
                "account",
                "create",
                "--auth-token-env",
                "CLI_ADMIN",
                "--username",
                "ordinary",
                "--password-env",
                "CLI_USER_PASSWORD",
            ]
        )
        == 0
    )
    user = json.loads(capsys.readouterr().out.splitlines()[-1])
    ordinary_token = asyncio.run(identity_call("login", "ordinary", "ordinary-password-1"))
    monkeypatch.setenv("CLI_ORDINARY", ordinary_token)
    assert (
        main(
            prefix
            + [
                "account",
                "create",
                "--auth-token-env",
                "CLI_ORDINARY",
                "--username",
                "intruder",
                "--password-env",
                "CLI_USER_PASSWORD",
            ]
        )
        == 1
    )
    for action in ("disable", "enable", "revoke"):
        assert (
            main(
                prefix
                + ["account", action, "--auth-token-env", "CLI_ADMIN", "--user-id", user["id"]]
            )
            == 0
        )
        with pytest.raises(PermissionError):
            asyncio.run(identity_call("authenticate", ordinary_token))
        if action == "disable":
            with pytest.raises(PermissionError):
                asyncio.run(identity_call("login", "ordinary", "ordinary-password-1"))
    monkeypatch.setenv("CLI_USER_PASSWORD", "ordinary-password-2")
    assert (
        main(
            prefix
            + [
                "account",
                "password",
                "--auth-token-env",
                "CLI_ADMIN",
                "--user-id",
                user["id"],
                "--password-env",
                "CLI_USER_PASSWORD",
            ]
        )
        == 0
    )
    with pytest.raises(PermissionError):
        asyncio.run(identity_call("login", "ordinary", "ordinary-password-1"))
    assert asyncio.run(identity_call("login", "ordinary", "ordinary-password-2"))
    output = capsys.readouterr()
    assert all(
        secret not in output.out + output.err
        for secret in (admin_token, ordinary_token, "ordinary-password-1", "ordinary-password-2")
    )
