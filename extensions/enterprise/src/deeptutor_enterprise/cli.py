"""受控运维/单执行 CLI。Secret 从指定环境引用读取，不能出现在 argv。"""

import argparse
import asyncio
import ipaddress
import json
import sys
from urllib.parse import quote, urlsplit, urlunsplit
import uuid

from deeptutor.persistence.postgres.configuration import SecretReference

from .configuration import DeploymentConfig, postgres_configuration, resolve_secret


def parser():
    p = argparse.ArgumentParser(
        allow_abbrev=False,
        prog="deeptutor-enterprise",
        description="A1 隔离集成入口，非完整企业生产版本",
    )
    p.add_argument("--config", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    schema = sub.add_parser("schema", allow_abbrev=False)
    schema.add_argument("action", choices=("plan", "apply", "verify"))
    schema.add_argument("--dsn-env", required=True, help="目标库迁移/运行 DSN 的环境变量名")
    boot = sub.add_parser("bootstrap", allow_abbrev=False)
    boot.add_argument("--username", required=True)
    boot.add_argument("--password-env", required=True)
    account = sub.add_parser("account", allow_abbrev=False)
    account.add_argument("action", choices=("create", "password", "disable", "enable", "revoke"))
    account.add_argument("--auth-token-env", required=True)
    account.add_argument("--username")
    account.add_argument("--user-id")
    account.add_argument("--password-env")
    session = sub.add_parser("session", allow_abbrev=False)
    session.add_argument("action", choices=("list", "show", "delete", "rename", "run", "cancel"))
    session.add_argument("--auth-token-env", required=True)
    session.add_argument(
        "--server", required=True, help="现有企业服务的 HTTPS origin；客户端不启动执行者"
    )
    session.add_argument(
        "--allow-loopback-http", action="store_true", help="仅本机隔离测试允许回环 IP 的 HTTP"
    )
    session.add_argument("--session-id")
    session.add_argument("--turn-id")
    session.add_argument("--text")
    session.add_argument("--operation-id")
    serve = sub.add_parser("serve", allow_abbrev=False)
    serve.add_argument("--port", type=int, default=8002)
    confirm = sub.add_parser("confirm-stopped", allow_abbrev=False)
    confirm.add_argument("--execution-id", required=True)
    confirm.add_argument("--old-process-confirmed-stopped", action="store_true", required=True)
    recovery = sub.add_parser("recovery", allow_abbrev=False)
    recovery.add_argument("action", choices=("quarantine", "reset-account", "release"))
    recovery.add_argument("--old-process-confirmed-stopped", action="store_true", required=True)
    recovery.add_argument("--user-id")
    recovery.add_argument("--password-env")
    recovery.add_argument(
        "--enable", action="store_true", help="仅重置且核验过的账号可显式启用；默认仍禁用"
    )
    return p


def _env(name):
    if not name:
        raise ValueError("required Secret reference is missing")
    return resolve_secret("env:" + name)


def _server_url(value, *, allow_loopback_http=False):
    parsed = urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or any(c.isspace() for c in value)
    ):
        raise ValueError("server must be an origin without credentials or query")
    # 不接受 hostname 的 HTTP 例外，避免 DNS 重绑定把 bearer 发往远端。
    if parsed.scheme != "https":
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = False
        if parsed.scheme != "http" or not allow_loopback_http or not loopback:
            raise ValueError("HTTPS required; loopback HTTP needs explicit test opt-in")
    _ = parsed.port
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


async def _question_is_waiting(server, token, event):
    """只回应当前 waiting 的末尾问题；历史重放不能再次读取 stdin。"""
    import httpx

    path = "/api/sessions/" + quote(event["session_id"], safe="")
    async with httpx.AsyncClient(
        base_url=server,
        headers={"Authorization": "Bearer " + token},
        timeout=10,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        async with asyncio.timeout(15):
            while True:
                response = await client.get(path)
                response.raise_for_status()
                turn = next(
                    (
                        row
                        for row in response.json().get("active_turns", [])
                        if row.get("id") == event["turn_id"]
                    ),
                    None,
                )
                if turn is None or int(turn["last_seq"]) != int(event["seq"]):
                    return False
                if turn["status"] == "waiting_input":
                    return True
                # tool_result 已提交而 waiter 的状态事务可能尚未完成。
                await asyncio.sleep(0.05)


async def _session_socket(args, config, server, token):
    # legacy 的客户端 API 同时兼容 core 声明的 websockets>=12 与当前发行版。
    from websockets.legacy.client import connect

    class SingleOriginConnection(connect):
        def handle_redirect(self, uri):
            # 库默认会向重定向目标转发 extra_headers，不能把 bearer 带到另一地址。
            raise RuntimeError("authenticated WebSocket redirects are forbidden")

    command_id = uuid.uuid4().hex
    if args.action == "cancel":
        if not args.turn_id:
            raise ValueError("--turn-id required")
        command = {"type": "cancel_turn", "turn_id": args.turn_id, "command_id": command_id}
    else:
        if not args.text:
            raise ValueError("--text required")
        command = {"type": "start_turn", "content": args.text}
        command.update(
            {
                key: value
                for key, value in {
                    "session_id": args.session_id,
                    "operation_id": args.operation_id,
                }.items()
                if value is not None
            }
        )
    uri = (
        ("wss" if server.startswith("https:") else "ws")
        + server[server.index(":") :]
        + "/api/v1/ws"
    )
    async with SingleOriginConnection(
        uri,
        extra_headers={"Authorization": "Bearer " + token},
        origin=config.origins[0],
        open_timeout=10,
        close_timeout=5,
        max_size=8 * 1024 * 1024,
    ) as ws:

        async def send(value):
            await ws.send(json.dumps({"protocol_version": "2.0", **value}, ensure_ascii=False))

        input_task = receive_task = stdin_transport = stdin_reader = None
        reply_turn_id = None
        try:
            await send(command)
            while True:
                receive_task = asyncio.create_task(ws.recv())
                if input_task is not None:
                    ready, _ = await asyncio.wait(
                        (receive_task, input_task), return_when=asyncio.FIRST_COMPLETED
                    )
                    # 远端终态/撤销优先，不因等待键盘而阻断取消或退出。
                    if receive_task not in ready:
                        reply = input_task.result()
                        input_task = None
                        if not reply:
                            raise RuntimeError("input required; reconnect to the waiting turn")
                        await send(
                            {
                                "type": "submit_user_reply",
                                "turn_id": reply_turn_id,
                                "text": reply.decode(sys.stdin.encoding or "utf-8").rstrip("\r\n"),
                                "command_id": uuid.uuid4().hex,
                            }
                        )
                # run 可能正在等待模型或人的交互；控制命令不能无限等 ACK。
                raw = (
                    await asyncio.wait_for(receive_task, 30)
                    if args.action == "cancel"
                    else await receive_task
                )
                receive_task = None
                event = json.loads(raw)
                if not isinstance(event, dict) or event.get("protocol_version") != "2.0":
                    raise RuntimeError("invalid server protocol")
                if event.get("type") == "protocol_error":
                    if event.get("error_code") == "operation_deleted" and args.action == "run":
                        return {"status": "deleted"}
                    raise RuntimeError("server rejected the operation")
                if event.get("type") == "command_ack":
                    if not event.get("accepted"):
                        raise RuntimeError("server rejected the command")
                    if args.action == "cancel" and event.get("command_id") == command_id:
                        return {"cancelled": True, "turn_id": args.turn_id}
                    continue
                if args.action != "run":
                    continue
                print(json.dumps(event, ensure_ascii=False), flush=True)
                metadata = event.get("metadata") or {}
                if event.get("type") == "done":
                    status = metadata.get("status")
                    if status not in ("completed", "cancelled"):
                        raise RuntimeError("turn did not complete successfully")
                    return {
                        "session_id": event.get("session_id"),
                        "turn_id": event.get("turn_id"),
                        "status": status,
                    }
                if event.get("type") == "tool_result" and (
                    metadata.get("ask_user")
                    or (metadata.get("tool_metadata") or {}).get("ask_user")
                ):
                    if not await _question_is_waiting(server, token, event):
                        continue
                    if input_task is not None:
                        raise RuntimeError("a question is already awaiting input")
                    if stdin_reader is None:
                        stdin_reader = asyncio.StreamReader()
                        stdin_transport, _ = await asyncio.get_running_loop().connect_read_pipe(
                            lambda: asyncio.StreamReaderProtocol(stdin_reader), sys.stdin
                        )
                    print("回复: ", end="", file=sys.stderr, flush=True)
                    reply_turn_id = event["turn_id"]
                    input_task = asyncio.create_task(stdin_reader.readline())
        finally:
            pending = [task for task in (input_task, receive_task) if task is not None]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if stdin_transport is not None:
                stdin_transport.close()


async def _remote_session(args, config):
    import httpx

    server = _server_url(args.server, allow_loopback_http=args.allow_loopback_http)
    token = _env(args.auth_token_env)
    if args.action in ("run", "cancel"):
        return await _session_socket(args, config, server, token)
    path = "/api/sessions"
    if args.action != "list":
        if not args.session_id:
            raise ValueError("--session-id required")
        path += "/" + quote(args.session_id, safe="")
    async with httpx.AsyncClient(
        base_url=server,
        headers={"Authorization": "Bearer " + token},
        timeout=30,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        if args.action == "rename":
            if not args.text:
                raise ValueError("--text required")
            response = await client.patch(path, json={"title": args.text})
        elif args.action == "delete":
            response = await client.delete(path)
        else:
            response = await client.get(path)
        response.raise_for_status()
        return response.json()


async def _run(args, config):
    if args.command == "session":
        return await _remote_session(args, config)
    from .migrations.runner import MigrationRunner

    postgres = postgres_configuration(config)
    if args.command == "schema":
        dsn = postgres.resolve_migration(
            secret_reference=SecretReference.environment(args.dsn_env)
        ).reveal()
        runner = MigrationRunner(dsn)
        if args.action == "plan":
            return {"pending": await runner.plan()}
        await getattr(runner, args.action)()
        return {"schema": args.action, "success": True}
    from deeptutor.persistence.postgres.executor import ExecutorLease
    from deeptutor.persistence.postgres.identity.service import IdentityService

    from .stores.postgres.connection import Database

    dsn = postgres.resolve_runtime().reveal()
    if args.command == "confirm-stopped":
        if not config.maintenance:
            raise ValueError("maintenance deployment is required")
        await ExecutorLease.confirm_stopped(
            dsn, resource=config.resource, execution_id=args.execution_id
        )
        return {"confirmed_stopped": args.execution_id}
    if args.command == "recovery":
        from .recovery import RecoveryOperations

        if not config.maintenance or not args.old_process_confirmed_stopped:
            raise ValueError("explicit stopped confirmation and maintenance deployment required")
        if args.action != "reset-account" and (args.user_id or args.password_env or args.enable):
            raise ValueError("account arguments require reset-account")
        if args.action == "reset-account" and (not args.user_id or not args.password_env):
            raise ValueError("--user-id and --password-env required")
        await MigrationRunner(dsn).verify()
        identity_secrets = postgres.resolve_identity()
        async with Database(dsn, **postgres.connection_kwargs()) as db:
            recovery = RecoveryOperations(
                db,
                tenant_id=str(config.tenant_id),
                resource=config.resource,
                auth_epoch=identity_secrets.auth_epoch.reveal(),
                maintenance=config.maintenance,
            )
            if args.action == "quarantine":
                await recovery.quarantine(old_process_confirmed_stopped=True)
            elif args.action == "reset-account":
                await recovery.reset_account(
                    args.user_id, _env(args.password_env), enabled=args.enable
                )
            else:
                await recovery.release()
        return {"success": True, "action": args.action}
    if args.command in ("bootstrap", "account"):
        await MigrationRunner(dsn).verify()
        identity_secrets = postgres.resolve_identity(include_bootstrap=args.command == "bootstrap")
        async with Database(dsn, **postgres.connection_kwargs()) as db:
            identity = IdentityService(
                db,
                tenant_id=str(config.tenant_id),
                signing_key=identity_secrets.signing_key.reveal(),
                auth_epoch=identity_secrets.auth_epoch.reveal(),
                bootstrap_secret=(
                    identity_secrets.bootstrap_secret.reveal()
                    if identity_secrets.bootstrap_secret
                    else None
                ),
                token_seconds=config.token_seconds,
            )
            if args.command == "bootstrap":
                return await identity.bootstrap(
                    args.username,
                    _env(args.password_env),
                    secret=identity_secrets.bootstrap_secret.reveal(),
                )
            token = _env(args.auth_token_env)
            if args.action == "create":
                return await identity.create_user(token, args.username, _env(args.password_env))
            if not args.user_id:
                raise ValueError("--user-id required")
            if args.action == "password":
                await identity.change_password(token, args.user_id, _env(args.password_env))
            elif args.action == "revoke":
                await identity.revoke_sessions(token, args.user_id)
            else:
                await identity.set_enabled(token, args.user_id, args.action == "enable")
            return {"success": True, "action": args.action, "user_id": args.user_id}
    raise ValueError("unsupported operation")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        config = DeploymentConfig.from_file(args.config)
        if args.command == "serve":
            import uvicorn

            from .bootstrap import create_application

            uvicorn.run(create_application(config), host="127.0.0.1", port=args.port, workers=1)
            return 0
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("use the async SDK inside an active event loop")
        result = asyncio.run(_run(args, config))
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        # 异常对象可能来自驱动/Secret解析，不输出其 repr/DSN/token。
        print(f"企业操作失败（{type(exc).__name__}）；检查配置、权限和运行状态", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
