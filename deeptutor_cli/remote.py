"""受控远程 CLI 客户端。

远程模式只把 bearer token 发给显式 origin；客户端不读取 PG DSN/Secret，
也不启动本地执行者。
"""

from __future__ import annotations

import inspect
import ipaddress
import json
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
import uuid

from deeptutor.api.contracts.turn_protocol import PROTOCOL_VERSION
from deeptutor.app import TurnRequest

from .common import TurnStreamRenderer, _ask_user_payload, console
from .pg_runtime import resolve_auth_token


def server_origin(value: str, *, allow_loopback_http: bool = False) -> str:
    parsed = urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or any(char.isspace() for char in value)
    ):
        raise ValueError("server must be an origin without credentials, path, or query")
    if parsed.scheme != "https":
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = False
        if parsed.scheme != "http" or not allow_loopback_http or not loopback:
            raise ValueError("HTTPS required; loopback HTTP needs explicit test opt-in")
    _ = parsed.port
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _websocket_url(origin: str) -> str:
    parsed = urlsplit(origin)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((scheme, parsed.netloc, "/ws", "", ""))


def _websocket_connect_class():
    try:
        from websockets.legacy.client import connect
    except ImportError as exc:  # pragma: no cover - exercised only by lean installs
        raise RuntimeError(
            "CLI remote run requires the websockets package; install the full "
            "deeptutor package or deeptutor-cli with updated dependencies."
        ) from exc

    class SingleOriginConnection(connect):  # type: ignore[misc, valid-type]
        """Reject authenticated redirects instead of forwarding bearer tokens."""

        def handle_redirect(self, uri):  # noqa: ANN001
            raise RuntimeError("authenticated WebSocket redirects are forbidden")

    return SingleOriginConnection


class _RemoteTurnApp:
    """Minimal app facade consumed by ``TurnStreamRenderer`` in remote mode."""

    def __init__(self) -> None:
        self.websocket = None
        self.turn_id = ""

    def bind(self, websocket) -> None:  # noqa: ANN001
        self.websocket = websocket

    async def submit_user_reply(
        self,
        turn_id: str,
        text: str | None = None,
        *,
        answers: list[dict[str, Any]] | None = None,
    ) -> bool:
        if self.websocket is None:
            return False
        resolved_turn_id = str(turn_id or self.turn_id or "").strip()
        if not resolved_turn_id:
            return False
        command: dict[str, Any] = {
            "type": "submit_user_reply",
            "turn_id": resolved_turn_id,
            "command_id": uuid.uuid4().hex,
            "protocol_version": PROTOCOL_VERSION,
        }
        if answers is not None:
            command["answers"] = answers
        else:
            command["text"] = text or ""
        await self.websocket.send(json.dumps(command, ensure_ascii=False, default=str))
        return True

    async def cancel_turn(self, turn_id: str) -> bool:
        if self.websocket is None:
            return False
        resolved_turn_id = str(turn_id or self.turn_id or "").strip()
        if not resolved_turn_id:
            return False
        await self.websocket.send(
            json.dumps(
                {
                    "type": "cancel_turn",
                    "turn_id": resolved_turn_id,
                    "command_id": uuid.uuid4().hex,
                    "protocol_version": PROTOCOL_VERSION,
                },
                ensure_ascii=False,
            )
        )
        return True


def _track_ids(app: _RemoteTurnApp, item: dict[str, Any]) -> tuple[str, str]:
    session_id = str(item.get("session_id") or "")
    turn_id = str(item.get("turn_id") or "")
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        session_id = session_id or str(metadata.get("session_id") or "")
        turn_id = turn_id or str(metadata.get("turn_id") or "")
    if turn_id:
        app.turn_id = turn_id
    return session_id, turn_id


async def _remote_events(websocket, request: TurnRequest):  # noqa: ANN001
    start_payload = {
        "type": "start_turn",
        "protocol_version": PROTOCOL_VERSION,
        **request.to_payload(),
    }
    await websocket.send(json.dumps(start_payload, ensure_ascii=False, default=str))
    async for raw in websocket:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("invalid server response") from exc
        if not isinstance(item, dict):
            raise RuntimeError("invalid server response")
        item_type = str(item.get("type") or "")
        if item_type == "command_ack":
            if not item.get("accepted", False):
                raise RuntimeError("remote command rejected")
            continue
        if item_type == "protocol_error":
            raise RuntimeError("remote turn rejected")
        yield item
        if item_type == "done":
            break


async def remote_run_and_render(
    *,
    request: TurnRequest,
    fmt: str,
    server: str,
    auth_token_env: str | None,
    allow_loopback_http: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one turn through an already-running authenticated DeepTutor API."""

    origin = server_origin(server, allow_loopback_http=allow_loopback_http)
    token = resolve_auth_token(auth_token_env)
    connect = _websocket_connect_class()
    remote_app = _RemoteTurnApp()
    session_id = ""
    turn_id = ""
    headers = {"Authorization": "Bearer " + token}
    connect_kwargs: dict[str, Any] = {"max_size": None, "open_timeout": 30}
    header_parameter = (
        "additional_headers"
        if "additional_headers" in inspect.signature(connect).parameters
        else "extra_headers"
    )
    connect_kwargs[header_parameter] = headers

    async with connect(
        _websocket_url(origin),
        **connect_kwargs,
    ) as websocket:
        remote_app.bind(websocket)
        if fmt == "json":
            async for item in _remote_events(websocket, request):
                current_session_id, current_turn_id = _track_ids(remote_app, item)
                session_id = current_session_id or session_id
                turn_id = current_turn_id or turn_id
                console.print(
                    json.dumps(item, ensure_ascii=False),
                    soft_wrap=True,
                    markup=False,
                    highlight=False,
                )
                if _ask_user_payload(item) is not None:
                    await remote_app.submit_user_reply(turn_id, text="")
        else:
            renderer = TurnStreamRenderer(app=remote_app, turn_id="")
            try:
                async for item in _remote_events(websocket, request):
                    current_session_id, current_turn_id = _track_ids(remote_app, item)
                    session_id = current_session_id or session_id
                    turn_id = current_turn_id or turn_id
                    if turn_id and not renderer.turn_id:
                        renderer.turn_id = turn_id
                    await renderer.handle(item)
            finally:
                renderer.close()
            console.print(
                f"[dim]session={session_id or '(remote)'} turn={turn_id or '(remote)'} "
                f"capability={request.capability}{renderer.summary_suffix()}[/]",
                highlight=False,
            )

    return {"id": session_id}, {"id": turn_id}


async def request_session(
    *,
    server: str,
    auth_token_env: str | None,
    allow_loopback_http: bool = False,
    action: str,
    session_id: str | None = None,
    title: str | None = None,
    limit: int = 20,
) -> dict:
    import httpx

    origin = server_origin(server, allow_loopback_http=allow_loopback_http)
    token = resolve_auth_token(auth_token_env)
    path = "/api/sessions"
    if action == "list":
        params = {"limit": max(1, min(int(limit), 200))}
    else:
        if not session_id:
            raise ValueError("--session-id is required")
        path += "/" + quote(session_id, safe="")
        params = None

    async with httpx.AsyncClient(
        base_url=origin,
        headers={"Authorization": "Bearer " + token},
        timeout=30,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        if action == "list":
            response = await client.get(path, params=params)
        elif action == "show":
            response = await client.get(path)
        elif action == "delete":
            response = await client.delete(path)
        elif action == "rename":
            if not title:
                raise ValueError("--title is required")
            response = await client.patch(path, json={"title": title})
        else:
            raise ValueError("unsupported remote session action")
        if 300 <= response.status_code < 400:
            raise RuntimeError("authenticated redirects are forbidden")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("invalid server response")
        return data
