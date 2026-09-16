"""CLI commands for shared session management."""

from __future__ import annotations

import json

import typer

from deeptutor.app import DeepTutorApp

from .chat import ChatState, _chat_repl
from .common import console, print_session_table
from .pg_runtime import authenticated_app, run_business
from .remote import request_session


def register(app: typer.Typer) -> None:
    @app.command("list")
    def list_sessions(
        limit: int = typer.Option(20, "--limit", help="Maximum sessions to show."),
        fmt: str = typer.Option("rich", "--format", help="Output format: rich | json."),
        auth_token_env: str | None = typer.Option(
            None,
            "--auth-token-env",
            help="Environment variable containing the PG auth token.",
        ),
        server: str | None = typer.Option(
            None,
            "--server",
            help="Existing DeepTutor API origin for authenticated remote control.",
        ),
        allow_loopback_http: bool = typer.Option(
            False,
            "--allow-loopback-http",
            help="Allow http://127.0.0.1 only for isolated local tests.",
        ),
    ) -> None:
        """List existing sessions."""
        run_business(
            _list_sessions(
                limit,
                fmt,
                auth_token_env=auth_token_env,
                server=server,
                allow_loopback_http=allow_loopback_http,
            )
        )

    @app.command("show")
    def show_session(
        session_id: str = typer.Argument(..., help="Session id."),
        fmt: str = typer.Option("rich", "--format", help="Output format: rich | json."),
        auth_token_env: str | None = typer.Option(
            None,
            "--auth-token-env",
            help="Environment variable containing the PG auth token.",
        ),
        server: str | None = typer.Option(
            None,
            "--server",
            help="Existing DeepTutor API origin for authenticated remote control.",
        ),
        allow_loopback_http: bool = typer.Option(
            False,
            "--allow-loopback-http",
            help="Allow http://127.0.0.1 only for isolated local tests.",
        ),
    ) -> None:
        """Show a session and its persisted messages."""
        run_business(
            _show_session(
                session_id,
                fmt,
                auth_token_env=auth_token_env,
                server=server,
                allow_loopback_http=allow_loopback_http,
            )
        )

    @app.command("open")
    def open_session(
        session_id: str = typer.Argument(..., help="Session id."),
        auth_token_env: str | None = typer.Option(
            None,
            "--auth-token-env",
            help="Environment variable containing the PG auth token.",
        ),
    ) -> None:
        """Enter the interactive chat REPL with an existing session."""
        run_business(_chat_repl(ChatState(session_id=session_id), auth_token_env=auth_token_env))

    @app.command("delete")
    def delete_session(
        session_id: str = typer.Argument(..., help="Session id."),
        auth_token_env: str | None = typer.Option(
            None,
            "--auth-token-env",
            help="Environment variable containing the PG auth token.",
        ),
        server: str | None = typer.Option(
            None,
            "--server",
            help="Existing DeepTutor API origin for authenticated remote control.",
        ),
        allow_loopback_http: bool = typer.Option(
            False,
            "--allow-loopback-http",
            help="Allow http://127.0.0.1 only for isolated local tests.",
        ),
    ) -> None:
        """Move a session to the recycle bin, or delete via the configured PG runtime."""
        run_business(
            _delete_session(
                session_id,
                auth_token_env=auth_token_env,
                server=server,
                allow_loopback_http=allow_loopback_http,
            )
        )

    @app.command("rename")
    def rename_session(
        session_id: str = typer.Argument(..., help="Session id."),
        title: str = typer.Option(..., "--title", help="New session title."),
        auth_token_env: str | None = typer.Option(
            None,
            "--auth-token-env",
            help="Environment variable containing the PG auth token.",
        ),
        server: str | None = typer.Option(
            None,
            "--server",
            help="Existing DeepTutor API origin for authenticated remote control.",
        ),
        allow_loopback_http: bool = typer.Option(
            False,
            "--allow-loopback-http",
            help="Allow http://127.0.0.1 only for isolated local tests.",
        ),
    ) -> None:
        """Rename a session."""
        run_business(
            _rename_session(
                session_id,
                title,
                auth_token_env=auth_token_env,
                server=server,
                allow_loopback_http=allow_loopback_http,
            )
        )


async def _list_sessions(
    limit: int,
    fmt: str = "rich",
    *,
    auth_token_env: str | None = None,
    server: str | None = None,
    allow_loopback_http: bool = False,
) -> None:
    if server:
        payload = await request_session(
            server=server,
            auth_token_env=auth_token_env,
            allow_loopback_http=allow_loopback_http,
            action="list",
            limit=limit,
        )
        sessions = list(payload.get("sessions") or [])
    else:
        async with authenticated_app(auth_token_env) as client:
            sessions = await client.list_sessions(limit=limit)
    if fmt == "json":
        typer.echo(json.dumps({"sessions": sessions}, ensure_ascii=False, default=str))
        return
    print_session_table(sessions)


async def _show_session(
    session_id: str,
    fmt: str,
    *,
    auth_token_env: str | None = None,
    server: str | None = None,
    allow_loopback_http: bool = False,
) -> None:
    if server:
        session = await request_session(
            server=server,
            auth_token_env=auth_token_env,
            allow_loopback_http=allow_loopback_http,
            action="show",
            session_id=session_id,
        )
    else:
        async with authenticated_app(auth_token_env) as client:
            session = await client.get_session(session_id)
    if session is None:
        console.print(f"[red]Session not found:[/] {session_id}")
        raise typer.Exit(code=1)

    if fmt == "json":
        console.print(json.dumps(session, ensure_ascii=False, indent=2, default=str))
        return

    console.print(f"[bold]{session.get('title', '')}[/] ({session.get('id', '')})")
    console.print(
        f"[dim]capability={session.get('capability', '') or 'chat'} "
        f"status={session.get('status', '')} "
        f"messages={len(session.get('messages', []))}[/]",
        highlight=False,
    )
    for message in session.get("messages", []):
        role = str(message.get("role", "")).upper()
        content = str(message.get("content", "") or "").strip()
        console.print(f"\n[cyan]{role}[/]")
        if content:
            console.print(content)


async def _delete_session(
    session_id: str,
    *,
    auth_token_env: str | None = None,
    server: str | None = None,
    allow_loopback_http: bool = False,
) -> None:
    if server:
        payload = await request_session(
            server=server,
            auth_token_env=auth_token_env,
            allow_loopback_http=allow_loopback_http,
            action="delete",
            session_id=session_id,
        )
        success = bool(payload.get("deleted", True))
    else:
        async with authenticated_app(auth_token_env) as client:
            success = await client.delete_session(session_id)
    if not success:
        console.print(f"[red]Session not found:[/] {session_id}")
        raise typer.Exit(code=1)
    console.print(f"Deleted session {session_id}")


async def _rename_session(
    session_id: str,
    title: str,
    *,
    auth_token_env: str | None = None,
    server: str | None = None,
    allow_loopback_http: bool = False,
) -> None:
    if server:
        payload = await request_session(
            server=server,
            auth_token_env=auth_token_env,
            allow_loopback_http=allow_loopback_http,
            action="rename",
            session_id=session_id,
            title=title,
        )
        success = bool(payload.get("session"))
    else:
        async with authenticated_app(auth_token_env) as client:
            success = await client.rename_session(session_id, title)
    if not success:
        console.print(f"[red]Session not found:[/] {session_id}")
        raise typer.Exit(code=1)
    console.print(f"Renamed {session_id} -> {title}")


async def _legacy_list_sessions(limit: int) -> None:
    client = DeepTutorApp()
    sessions = await client.list_sessions(limit=limit)
    print_session_table(sessions)


async def _legacy_show_session(session_id: str, fmt: str) -> None:
    client = DeepTutorApp()
    session = await client.get_session(session_id)
    if session is None:
        console.print(f"[red]Session not found:[/] {session_id}")
        raise typer.Exit(code=1)

    if fmt == "json":
        console.print(json.dumps(session, ensure_ascii=False, indent=2, default=str))
        return

    console.print(f"[bold]{session.get('title', '')}[/] ({session.get('id', '')})")
    console.print(
        f"[dim]capability={session.get('capability', '') or 'chat'} "
        f"status={session.get('status', '')} "
        f"messages={len(session.get('messages', []))}[/]",
        highlight=False,
    )
    for message in session.get("messages", []):
        role = str(message.get("role", "")).upper()
        content = str(message.get("content", "") or "").strip()
        console.print(f"\n[cyan]{role}[/]")
        if content:
            console.print(content)


async def _legacy_delete_session(session_id: str) -> None:
    client = DeepTutorApp()
    success = await client.delete_session(session_id)
    if not success:
        console.print(f"[red]Session not found:[/] {session_id}")
        raise typer.Exit(code=1)
    console.print(f"Deleted session {session_id}")


async def _legacy_rename_session(session_id: str, title: str) -> None:
    client = DeepTutorApp()
    success = await client.rename_session(session_id, title)
    if not success:
        console.print(f"[red]Session not found:[/] {session_id}")
        raise typer.Exit(code=1)
    console.print(f"Renamed {session_id} -> {title}")
