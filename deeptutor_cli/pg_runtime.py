"""CLI PostgreSQL identity binding helpers.

业务 CLI 只能使用显式环境变量里的认证 token。这里不接受 argv 内联 token，
并负责在命令结束时关闭默认 PG runtime，释放单执行者登记。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
import re
from typing import AsyncIterator

import typer

DEFAULT_CLI_AUTH_TOKEN_ENV = "DEEPTUTOR_AUTH_TOKEN"
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_SAFE_CLI_MESSAGES = (
    "server must be an origin",
    "HTTPS required;",
    "--session-id is required",
    "--title is required",
    "unsupported remote session action",
    "authenticated redirects are forbidden",
    "authenticated WebSocket redirects are forbidden",
    "CLI remote run requires the websockets package",
    "invalid server response",
    "remote command rejected",
    "remote turn rejected",
)


class CliAuthenticationError(RuntimeError):
    """CLI token 缺失或认证失败；消息不得包含 token 值。"""


def resolve_auth_token_env(auth_token_env: str | None) -> str:
    name = (auth_token_env or "").strip()
    if not name:
        if os.environ.get(DEFAULT_CLI_AUTH_TOKEN_ENV):
            return DEFAULT_CLI_AUTH_TOKEN_ENV
        raise CliAuthenticationError(
            "CLI authentication token environment reference is required"
        )
    if not _ENV_NAME.fullmatch(name):
        raise CliAuthenticationError(
            "CLI authentication token environment reference is required"
        )
    return name


def resolve_auth_token(auth_token_env: str | None) -> str:
    name = resolve_auth_token_env(auth_token_env)
    token = os.environ.get(name)
    if not token:
        raise CliAuthenticationError("CLI authentication failed")
    return token


@asynccontextmanager
async def authenticated_app(auth_token_env: str | None = None) -> AsyncIterator[object]:
    """启动默认 PG 容器，把 token 解码为当前 user，并在退出时清理。"""

    token_value = resolve_auth_token(auth_token_env)
    app = None
    current_user_token = None
    try:
        from deeptutor.app import DeepTutorApp
        from deeptutor.multi_user.context import (
            reset_current_user,
            set_current_user,
            user_from_token_payload,
        )

        app = DeepTutorApp()
        await app.container.start()
        provider = getattr(app.container, "auth_provider", None)
        if provider is None:
            raise CliAuthenticationError("CLI authentication failed")
        try:
            payload = await provider.decode(token_value)
        except PermissionError:
            raise CliAuthenticationError("CLI authentication failed") from None
        current_user_token = set_current_user(user_from_token_payload(payload))
        yield app
    finally:
        if current_user_token is not None:
            reset_current_user(current_user_token)
        if app is not None:
            await app.close()


def handle_cli_error(error: BaseException) -> None:
    """把业务 CLI 异常收敛为脱敏错误。"""

    from deeptutor.persistence.postgres.configuration import PostgresConfigurationError

    if isinstance(error, CliAuthenticationError):
        typer.echo(str(error), err=True)
    elif isinstance(error, PermissionError):
        typer.echo("CLI authentication failed", err=True)
    elif isinstance(error, PostgresConfigurationError):
        typer.echo(str(error), err=True)
    elif isinstance(error, RuntimeError) and "another executor" in str(error):
        typer.echo(
            "PostgreSQL executor is already active; use --server for authenticated remote control",
            err=True,
        )
    elif isinstance(error, (RuntimeError, ValueError)) and str(error).startswith(
        _SAFE_CLI_MESSAGES
    ):
        typer.echo(str(error), err=True)
    else:
        typer.echo("CLI business operation failed; check PostgreSQL configuration and identity", err=True)
    raise typer.Exit(code=1)


def run_business(coro):  # noqa: ANN001
    """运行业务 coroutine，并避免 Typer 打印含内部细节的 traceback。"""

    from .common import maybe_run

    try:
        return maybe_run(coro)
    except typer.Exit:
        raise
    except BaseException as error:
        handle_cli_error(error)
