"""受控远程 SDK 客户端。

远程模式只把 bearer token 发给显式 origin；客户端不读取 PG DSN/Secret，
也不启动本地执行者。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
import inspect
import ipaddress
import json
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
import uuid

from deeptutor.api.contracts.turn_protocol import PROTOCOL_VERSION

from .contracts import TurnRequest


def server_origin(value: str, *, allow_loopback_http: bool = False) -> str:
    """Return a normalized origin accepted for authenticated remote SDK calls."""

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
            "SDK remote mode requires the websockets package; install the full "
            "deeptutor package or deeptutor-cli with updated dependencies."
        ) from exc

    class SingleOriginConnection(connect):  # type: ignore[misc, valid-type]
        """Reject authenticated redirects instead of forwarding bearer tokens."""

        def handle_redirect(self, uri):  # noqa: ANN001
            raise RuntimeError("authenticated WebSocket redirects are forbidden")

    return SingleOriginConnection


def _decode_server_frame(raw: str) -> dict[str, Any]:
    try:
        item = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("invalid server response") from exc
    if not isinstance(item, dict):
        raise RuntimeError("invalid server response")
    return item


def _extract_ids(item: dict[str, Any]) -> tuple[str, str]:
    session_id = str(item.get("session_id") or "")
    turn_id = str(item.get("turn_id") or "")
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        session_id = session_id or str(metadata.get("session_id") or "")
        turn_id = turn_id or str(metadata.get("turn_id") or "")
    return session_id, turn_id


class RemoteDeepTutorClient:
    """SDK-side client for an already-running authenticated DeepTutor API."""

    def __init__(
        self,
        *,
        server: str,
        auth_token_resolver: Callable[[], str],
        allow_loopback_http: bool = False,
    ) -> None:
        self.origin = server_origin(server, allow_loopback_http=allow_loopback_http)
        self._auth_token_resolver = auth_token_resolver

    async def close(self) -> None:
        """Keep the local facade close contract symmetric with local containers."""

    def _headers(self) -> dict[str, str]:
        token = self._auth_token_resolver()
        if not token:
            raise PermissionError("SDK authentication failed")
        return {"Authorization": "Bearer " + token}

    def _connect(self):  # noqa: ANN202
        connect = _websocket_connect_class()
        connect_kwargs: dict[str, Any] = {"max_size": None, "open_timeout": 30}
        header_parameter = (
            "additional_headers"
            if "additional_headers" in inspect.signature(connect).parameters
            else "extra_headers"
        )
        connect_kwargs[header_parameter] = self._headers()
        return connect(_websocket_url(self.origin), **connect_kwargs)

    async def _events(
        self,
        websocket,  # noqa: ANN001
        *,
        include_command_ack: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        async for raw in websocket:
            item = _decode_server_frame(raw)
            item_type = str(item.get("type") or "")
            if item_type == "command_ack":
                if include_command_ack:
                    yield item
                    continue
                if not item.get("accepted", False):
                    raise RuntimeError("remote command rejected")
                continue
            if item_type == "protocol_error":
                message = str(item.get("message") or "remote request rejected")
                raise RuntimeError(message)
            yield item

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        import httpx

        async with httpx.AsyncClient(
            base_url=self.origin,
            headers=self._headers(),
            timeout=30,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            if method == "GET":
                response = await client.get(path, params=params)
            elif method == "PATCH":
                response = await client.patch(path, json=json_body or {})
            elif method == "DELETE":
                response = await client.delete(path)
            else:  # pragma: no cover - internal programming error
                raise ValueError(f"unsupported HTTP method: {method}")
            if 300 <= response.status_code < 400:
                raise RuntimeError("authenticated redirects are forbidden")
            if response.status_code == 404:
                return response.status_code, {}
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError("invalid server response")
            return response.status_code, data

    @staticmethod
    def _session_path(session_id: str) -> str:
        resolved = str(session_id or "").strip()
        if not resolved:
            raise ValueError("session_id is required")
        return "/api/sessions/" + quote(resolved, safe="")

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        _, data = await self._request_json(
            "GET",
            "/api/sessions",
            params={"limit": max(1, min(int(limit), 200)), "offset": max(0, int(offset))},
        )
        sessions = data.get("sessions")
        if not isinstance(sessions, list):
            raise RuntimeError("invalid server response")
        return sessions

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        status_code, data = await self._request_json("GET", self._session_path(session_id))
        return None if status_code == 404 else data

    async def rename_session(self, session_id: str, title: str) -> bool:
        status_code, _data = await self._request_json(
            "PATCH",
            self._session_path(session_id),
            json_body={"title": str(title)},
        )
        return status_code != 404

    async def delete_session(self, session_id: str) -> bool:
        status_code, data = await self._request_json("DELETE", self._session_path(session_id))
        if status_code == 404:
            return False
        return bool(data.get("deleted", False))

    async def start_turn(
        self,
        request: TurnRequest,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = {
            "type": "start_turn",
            "protocol_version": PROTOCOL_VERSION,
            **request.to_payload(),
        }
        async with self._connect() as websocket:
            await websocket.send(json.dumps(payload, ensure_ascii=False, default=str))
            session_id = ""
            async for item in self._events(websocket):
                current_session_id, turn_id = _extract_ids(item)
                session_id = current_session_id or session_id
                if turn_id:
                    return {"id": session_id}, {"id": turn_id}
                if item.get("type") == "done":
                    break
        raise RuntimeError("remote turn did not start")

    async def stream_turn(
        self, turn_id: str, after_seq: int = 0
    ) -> AsyncIterator[dict[str, Any]]:
        command = {
            "type": "subscribe_turn",
            "turn_id": str(turn_id),
            "after_seq": max(0, int(after_seq)),
            "protocol_version": PROTOCOL_VERSION,
        }
        async with self._connect() as websocket:
            await websocket.send(json.dumps(command, ensure_ascii=False, default=str))
            async for item in self._events(websocket):
                yield item
                if item.get("type") == "done":
                    break

    async def _send_command_and_wait_ack(self, command: dict[str, Any]) -> bool:
        async with self._connect() as websocket:
            await websocket.send(json.dumps(command, ensure_ascii=False, default=str))
            async for item in self._events(websocket, include_command_ack=True):
                if item.get("type") != "command_ack":
                    continue
                if str(item.get("command_id") or "") == command["command_id"]:
                    return bool(item.get("accepted", False))
        raise RuntimeError("remote command acknowledgement missing")

    async def cancel_turn(self, turn_id: str) -> bool:
        command = {
            "type": "cancel_turn",
            "turn_id": str(turn_id),
            "command_id": uuid.uuid4().hex,
            "protocol_version": PROTOCOL_VERSION,
        }
        return await self._send_command_and_wait_ack(command)

    async def submit_user_reply(
        self,
        turn_id: str,
        text: str | None = None,
        *,
        answers: list[dict[str, Any]] | None = None,
    ) -> bool:
        command: dict[str, Any] = {
            "type": "submit_user_reply",
            "turn_id": str(turn_id),
            "command_id": uuid.uuid4().hex,
            "protocol_version": PROTOCOL_VERSION,
        }
        if answers is not None:
            command["answers"] = answers
        else:
            command["text"] = text or ""
        return await self._send_command_and_wait_ack(command)

    async def regenerate_last_turn(
        self,
        session_id: str,
        overrides: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        command = {
            "type": "regenerate",
            "session_id": str(session_id),
            "overrides": overrides or {},
            "protocol_version": PROTOCOL_VERSION,
        }
        async with self._connect() as websocket:
            await websocket.send(json.dumps(command, ensure_ascii=False, default=str))
            resolved_session_id = str(session_id)
            async for item in self._events(websocket):
                current_session_id, turn_id = _extract_ids(item)
                resolved_session_id = current_session_id or resolved_session_id
                if turn_id:
                    return {"id": resolved_session_id}, {"id": turn_id}
                if item.get("type") == "done":
                    break
        raise RuntimeError("remote turn did not start")

    async def check_active_turn(self, session_id: str) -> dict[str, Any] | None:
        command = {
            "type": "check_active_turn",
            "session_id": str(session_id),
            "protocol_version": PROTOCOL_VERSION,
        }
        async with self._connect() as websocket:
            await websocket.send(json.dumps(command, ensure_ascii=False, default=str))
            async for item in self._events(websocket):
                if item.get("type") != "active_turn_info":
                    continue
                status = str(item.get("status") or "none")
                if status == "none":
                    return None
                return {
                    "turn_id": str(item.get("turn_id") or ""),
                    "status": status,
                    "owner_id": str(item.get("owner_id") or ""),
                }
        raise RuntimeError("remote active turn response missing")
