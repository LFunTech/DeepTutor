"""显式部署配置和 Secret 环境引用的受控 PG 账号命令。"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re

import typer


def _secret(name):
    if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError("Secret environment reference required")
    value = os.environ.get(name)
    if not value:
        raise ValueError("Secret environment reference is unavailable")
    return value


async def execute(
    action,
    *,
    config,
    username=None,
    user_id=None,
    password_env=None,
    token_env=None,
    preset="standard",
    role=None,
):
    from deeptutor.persistence.postgres.configuration import PostgresDeploymentConfig
    from deeptutor.persistence.postgres.connection import Database
    from deeptutor.persistence.postgres.identity.service import IdentityService
    from deeptutor.persistence.postgres.migrations.runner import MigrationRunner

    deployment = PostgresDeploymentConfig.from_file(config)
    dsn = deployment.resolve_runtime().reveal()
    await MigrationRunner(dsn).verify()
    values = deployment.resolve_identity()
    bootstrap = deployment.resolve_bootstrap().reveal() if action == "bootstrap" else None
    async with Database(dsn, **deployment.connection_kwargs()) as db:
        identity = IdentityService(
            db,
            tenant_id=str(deployment.tenant_id),
            signing_key=values.signing_key.reveal(),
            auth_epoch=values.auth_epoch.reveal(),
            bootstrap_secret=bootstrap,
            token_seconds=deployment.token_seconds,
        )
        if action == "bootstrap":
            return await identity.bootstrap(username, _secret(password_env), secret=bootstrap)
        token = _secret(token_env)
        if action == "create":
            return await identity.create_user(token, username, _secret(password_env), preset=preset)
        if action == "list":
            return await identity.list_users(token)
        if action == "password":
            await identity.change_password(token, user_id, _secret(password_env))
        elif action in ("enable", "disable"):
            await identity.set_enabled(token, user_id, action == "enable")
        elif action == "revoke":
            await identity.revoke_sessions(token, user_id)
        elif action == "role":
            await identity.set_role(token, username, role)
        elif action == "delete":
            await identity.delete_user(token, username)
        else:
            raise ValueError("unsupported account action")
        return {"ok": True}


def register(app):
    account = typer.Typer(help="受控 PostgreSQL 账号维护；不公开创建首位管理员。")
    app.add_typer(account, name="account")

    def run(action, **kwargs):
        try:
            result = asyncio.run(execute(action, **kwargs))
        except Exception as error:
            # 不回显 DSN、原始驱动异常、密码、token 或 Secret 值。
            message = (
                "账号操作被拒绝"
                if isinstance(error, PermissionError)
                else "账号操作失败；检查受控配置、输入和数据库状态"
            )
            typer.echo(message, err=True)
            raise typer.Exit(1) from None
        typer.echo(json.dumps(result, ensure_ascii=False))

    @account.command("bootstrap")
    def bootstrap(
        config: Path = typer.Option(..., "--config"),
        username: str = typer.Option(..., "--username"),
        password_env: str = typer.Option(..., "--password-env"),
    ):
        run("bootstrap", config=config, username=username, password_env=password_env)

    @account.command("create")
    def create(
        config: Path = typer.Option(..., "--config"),
        token_env: str = typer.Option(..., "--token-env"),
        username: str = typer.Option(..., "--username"),
        password_env: str = typer.Option(..., "--password-env"),
        preset: str = typer.Option("standard", "--preset"),
    ):
        run(
            "create",
            config=config,
            token_env=token_env,
            username=username,
            password_env=password_env,
            preset=preset,
        )

    @account.command("list")
    def list_accounts(
        config: Path = typer.Option(..., "--config"),
        token_env: str = typer.Option(..., "--token-env"),
    ):
        run("list", config=config, token_env=token_env)

    @account.command("password")
    def password(
        config: Path = typer.Option(..., "--config"),
        token_env: str = typer.Option(..., "--token-env"),
        user_id: str = typer.Option(..., "--user-id"),
        password_env: str = typer.Option(..., "--password-env"),
    ):
        run(
            "password",
            config=config,
            token_env=token_env,
            user_id=user_id,
            password_env=password_env,
        )

    def status_command(action):
        def command(
            config: Path = typer.Option(..., "--config"),
            token_env: str = typer.Option(..., "--token-env"),
            user_id: str = typer.Option(..., "--user-id"),
        ):
            run(action, config=config, token_env=token_env, user_id=user_id)

        account.command(action)(command)

    for action in ("enable", "disable", "revoke"):
        status_command(action)

    @account.command("role")
    def role(
        config: Path = typer.Option(..., "--config"),
        token_env: str = typer.Option(..., "--token-env"),
        username: str = typer.Option(..., "--username"),
        role: str = typer.Option(..., "--role"),
    ):
        run("role", config=config, token_env=token_env, username=username, role=role)

    @account.command("delete")
    def delete(
        config: Path = typer.Option(..., "--config"),
        token_env: str = typer.Option(..., "--token-env"),
        username: str = typer.Option(..., "--username"),
    ):
        run("delete", config=config, token_env=token_env, username=username)
