"""Unified WebSocket adapter for turn execution and replayable streaming.

All mutating operations are commands on :class:`TurnApplicationService`.
Subscriptions and active-turn checks are deliberately read-only, including
when the owner worker has disappeared and leader recovery is still pending.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from deeptutor.api.contracts.turn_protocol import (
    PROTOCOL_VERSION,
    ClientCommand,
)
from deeptutor.persistence.postgres.connection import CommitCompletedAfterCancellation

router = APIRouter()
logger = logging.getLogger(__name__)
_CLIENT_COMMAND_ADAPTER = TypeAdapter(ClientCommand)
TOKEN_CARRIER_SUBPROTOCOL = "deeptutor-token"


def _accepted_subprotocol(ws: WebSocket) -> str | None:
    raw_protocols = str(ws.headers.get("sec-websocket-protocol", "") or "")
    protocols = [item.strip() for item in raw_protocols.split(",") if item.strip()]
    if TOKEN_CARRIER_SUBPROTOCOL in protocols:
        return TOKEN_CARRIER_SUBPROTOCOL
    return None


def _clean_answers(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    cleaned: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        question_id = str(entry.get("questionId") or entry.get("id") or "").strip()
        if question_id:
            cleaned.append({"questionId": question_id, "text": str(entry.get("text") or "")})
    return cleaned or None


@router.websocket("/ws")
async def unified_websocket(ws: WebSocket) -> None:
    from deeptutor.app.container import get_application_container
    from deeptutor.multi_user.context import reset_current_user

    auth_provider = getattr(ws.app.state, "auth_provider", None)
    if auth_provider is None:
        from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth

        user_token = await ws_require_auth(ws)
        if user_token is ws_auth_failed:
            return
    else:
        user_token = await auth_provider.authenticate(ws)

    await ws.accept(subprotocol=_accepted_subprotocol(ws))
    closed = False
    subscription_tasks: dict[str, asyncio.Task[None]] = {}
    retiring_tasks: set[asyncio.Task[None]] = set()

    # Resolve once after authentication. Context variables are copied into
    # subscription tasks, so the socket remains in one stable StoreScope.
    container = getattr(ws.app.state, "application_container", None)
    if container is None:
        container = get_application_container()
        await container.start()
    turns = container.turns
    provider_scope = None
    try:
        from deeptutor.core.providers import get_providers, provider_context

        if get_providers() is None:
            providers = getattr(container, "providers", None)
            if providers is not None:
                provider_scope = provider_context(providers)
                provider_scope.__enter__()
    except Exception:
        if provider_scope is not None:
            with suppress(Exception):
                provider_scope.__exit__(None, None, None)
        raise

    def public_error(error):
        sanitizer = getattr(auth_provider, "error_message", None)
        return sanitizer(error) if sanitizer is not None else str(error)

    def report_error(message, error):
        if auth_provider is not None:
            logger.error("%s (%s)", message, type(error).__name__)
        else:
            logger.error("%s: %s", message, error, exc_info=True)

    def is_retired_commit_cancellation(error: Exception) -> bool:
        task = asyncio.current_task()
        return (
            isinstance(error, CommitCompletedAfterCancellation)
            and task in retiring_tasks
            and bool(task.cancelling())
        )

    async def safe_send(data: dict[str, Any]) -> None:
        nonlocal closed
        if closed:
            return
        try:
            if auth_provider is not None:
                await auth_provider.revalidate(ws)
            payload = {**data, "protocol_version": PROTOCOL_VERSION}
            await ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
        except PermissionError:
            closed = True
            await ws.close(code=1008, reason="Authentication required")
        except Exception as exc:
            if is_retired_commit_cancellation(exc):
                raise asyncio.CancelledError() from exc
            closed = True

    async def send_protocol_error(
        message: str,
        *,
        error_code: str,
        session_id: str = "",
        turn_id: str = "",
        retryable: bool = False,
    ) -> None:
        denial = getattr(auth_provider, "record_denial", None)
        if denial is not None:
            await denial()
        await safe_send(
            {
                "type": "protocol_error",
                "error_code": error_code,
                "message": message,
                "retryable": retryable,
                "session_id": session_id,
                "turn_id": turn_id,
            }
        )

    async def send_error(
        content: str,
        *,
        error_code: str,
        session_id: str = "",
        turn_id: str = "",
        retryable: bool = False,
        terminal: bool = False,
    ) -> None:
        await send_protocol_error(
            content,
            error_code=error_code,
            session_id=session_id,
            turn_id=turn_id,
            retryable=retryable or terminal,
        )

    async def send_command_ack(
        msg: dict[str, Any],
        *,
        accepted: bool,
        error_code: str = "",
        message: str = "",
    ) -> None:
        await safe_send(
            {
                "type": "command_ack",
                "command_id": str(msg["command_id"]),
                "command_type": str(msg["type"]),
                "accepted": accepted,
                "turn_id": str(msg.get("turn_id") or ""),
                "error_code": error_code,
                "message": message,
            }
        )

    async def stop_subscription(key: str) -> None:
        task = subscription_tasks.pop(key, None)
        if task is None:
            return
        retiring_tasks.add(task)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            retiring_tasks.discard(task)

    async def start_subscription(key, events, failure_message, **identifiers) -> None:
        async def _forward() -> None:
            try:
                async for event in events():
                    await safe_send(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # 只读订阅被本 WS 明确退休时，已提交后的取消不是新订阅的失败。
                # 按具体 task 判定，不让同 key 的下一代继承退休状态。
                if is_retired_commit_cancellation(exc):
                    raise asyncio.CancelledError() from exc
                report_error(failure_message, exc)
                await send_error(
                    public_error(exc),
                    error_code="subscription_failed",
                    retryable=True,
                    **identifiers,
                )

        await stop_subscription(key)
        subscription_tasks[key] = asyncio.create_task(_forward())

    async def subscribe_turn(turn_id: str, after_seq: int = 0) -> None:
        await start_subscription(
            turn_id,
            lambda: turns.subscribe_turn(turn_id, after_seq=after_seq),
            "Turn subscription failed",
            turn_id=turn_id,
        )

    async def subscribe_session(session_id: str, after_seq: int = 0) -> None:
        await start_subscription(
            f"session:{session_id}",
            lambda: turns.subscribe_session(session_id, after_seq=after_seq),
            "Session subscription failed",
            session_id=session_id,
        )

    try:
        while not closed:
            raw = await ws.receive_text()
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                await send_protocol_error("Invalid JSON.", error_code="invalid_json")
                continue

            if not isinstance(decoded, dict):
                await send_protocol_error(
                    "WebSocket commands must be JSON objects.",
                    error_code="invalid_command",
                )
                continue
            if decoded.get("protocol_version") != PROTOCOL_VERSION:
                await send_protocol_error(
                    f"Unsupported or missing protocol_version; expected {PROTOCOL_VERSION}.",
                    error_code="unsupported_protocol_version",
                )
                continue
            try:
                command = _CLIENT_COMMAND_ADAPTER.validate_python(decoded)
            except ValidationError:
                await send_protocol_error(
                    "Command does not match the turn protocol.",
                    error_code="invalid_command",
                )
                continue

            msg = command.model_dump(mode="python", exclude_unset=True)

            msg_type = msg.get("type")

            if msg_type == "auth_refresh":
                refresher = getattr(auth_provider, "refresh", None)
                if refresher is None:
                    await send_protocol_error(
                        "Authentication refresh is not supported.",
                        error_code="auth_refresh_unsupported",
                    )
                    continue
                try:
                    refreshed = await refresher(ws, msg)
                except PermissionError:
                    closed = True
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "auth_revoked",
                                "reason": "refresh_rejected",
                                "protocol_version": PROTOCOL_VERSION,
                            },
                            ensure_ascii=False,
                        )
                    )
                    await ws.close(code=1008, reason="Authentication refresh rejected")
                    continue
                await safe_send(
                    {
                        "type": "auth_ack",
                        "command_id": str(msg["command_id"]),
                        "accepted": True,
                        "expires_at": int(refreshed.get("expires_at") or 0),
                        "refresh_deadline": int(refreshed.get("refresh_deadline") or 0),
                    }
                )
                continue

            if auth_provider is not None:
                await auth_provider.revalidate(ws)

            if msg_type in {"message", "start_turn"}:
                start_validator = (
                    getattr(auth_provider, "validate_start_turn", None)
                    if auth_provider is not None
                    else None
                )
                if start_validator is not None:
                    try:
                        await start_validator(ws, msg)
                    except (PermissionError, RuntimeError, ValueError, LookupError) as exc:
                        await send_error(
                            public_error(exc),
                            error_code="start_turn_rejected",
                            session_id=str(msg.get("session_id") or ""),
                            terminal=True,
                        )
                        continue
                try:
                    _, turn = await turns.start_turn(
                        {
                            key: value
                            for key, value in msg.items()
                            if key not in {"type", "protocol_version"}
                        }
                    )
                except (RuntimeError, ValueError, LookupError) as exc:
                    await send_error(
                        public_error(exc),
                        error_code="start_turn_rejected",
                        session_id=str(msg.get("session_id") or ""),
                        terminal=True,
                    )
                    continue
                if turn.get("status") == "deleted":
                    await send_protocol_error(
                        "The original operation was deleted.", error_code="operation_deleted"
                    )
                    continue
                await subscribe_turn(turn["id"])
                continue

            if msg_type == "ping":
                await safe_send({"type": "pong"})
                continue

            if msg_type in {"subscribe_turn", "resume_from"}:
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await send_error("Missing turn_id.", error_code="missing_turn_id")
                    continue
                after_seq = int(
                    (msg.get("seq") if msg_type == "resume_from" else msg.get("after_seq")) or 0
                )
                await subscribe_turn(turn_id, after_seq=after_seq)
                continue

            if msg_type == "subscribe_session":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await send_error("Missing session_id.", error_code="missing_session_id")
                    continue
                await subscribe_session(session_id, after_seq=int(msg.get("after_seq") or 0))
                continue

            if msg_type == "check_active_turn":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await send_error("Missing session_id.", error_code="missing_session_id")
                    continue
                active = await turns.check_active_turn(session_id)
                await safe_send(
                    {
                        "type": "active_turn_info",
                        "turn_id": str((active or {}).get("turn_id") or ""),
                        "status": str((active or {}).get("status") or "none"),
                        "owner_id": str((active or {}).get("owner_id") or ""),
                    }
                )
                continue

            if msg_type == "unsubscribe":
                turn_id = str(msg.get("turn_id") or "").strip()
                session_id = str(msg.get("session_id") or "").strip()
                if turn_id:
                    await stop_subscription(turn_id)
                if session_id:
                    await stop_subscription(f"session:{session_id}")
                continue

            if msg_type == "cancel_turn":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await send_error("Missing turn_id.", error_code="missing_turn_id")
                    continue
                accepted = await turns.cancel_turn(turn_id, command_id=str(msg["command_id"]))
                if not accepted:
                    await send_command_ack(
                        msg,
                        accepted=False,
                        error_code="turn_not_active",
                        message=f"Turn is not active or recoverable: {turn_id}",
                    )
                else:
                    await send_command_ack(msg, accepted=True)
                continue

            if msg_type == "submit_user_reply":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await send_error("Missing turn_id.", error_code="missing_turn_id")
                    continue
                text = msg.get("text")
                accepted = await turns.submit_user_reply(
                    turn_id,
                    text=str(text) if text is not None else None,
                    answers=_clean_answers(msg.get("answers")),
                    command_id=str(msg["command_id"]),
                )
                if not accepted:
                    await send_command_ack(
                        msg,
                        accepted=False,
                        error_code="turn_not_waiting_input",
                        message=f"Turn {turn_id} is not awaiting a user reply.",
                    )
                else:
                    await send_command_ack(msg, accepted=True)
                continue

            if msg_type == "regenerate":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await send_error("Missing session_id.", error_code="missing_session_id")
                    continue
                overrides = msg.get("overrides") if isinstance(msg.get("overrides"), dict) else None
                try:
                    _, turn = await turns.regenerate_last_turn(session_id, overrides=overrides)
                except RuntimeError as exc:
                    await send_error(
                        public_error(exc),
                        error_code="regenerate_rejected",
                        session_id=session_id,
                        terminal=True,
                    )
                    continue
                await subscribe_turn(turn["id"])
                continue

            if msg_type == "user_input":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await send_error(
                        "Missing turn_id for user_input.", error_code="missing_turn_id"
                    )
                    continue
                accepted = await turns.submit_user_input(
                    turn_id,
                    str(msg.get("content") or ""),
                    command_id=str(msg["command_id"]),
                )
                if not accepted:
                    await send_command_ack(
                        msg,
                        accepted=False,
                        error_code="turn_not_active",
                        message=f"Turn is not active: {turn_id}",
                    )
                else:
                    await send_command_ack(msg, accepted=True)
                continue

            await send_protocol_error(
                f"Unknown type: {msg_type}", error_code="unknown_message_type"
            )

    except PermissionError:
        closed = True
        await ws.close(code=1008, reason="Authentication required")
    except WebSocketDisconnect:
        logger.debug("Client disconnected from /ws")
    except Exception as exc:
        report_error("Unified WS error", exc)
        await send_error(public_error(exc), error_code="internal_error", retryable=True)
    finally:
        closed = True
        for key in list(subscription_tasks):
            await stop_subscription(key)
        if user_token is not None:
            reset_current_user(user_token)
        if provider_scope is not None:
            with suppress(Exception):
                provider_scope.__exit__(None, None, None)
