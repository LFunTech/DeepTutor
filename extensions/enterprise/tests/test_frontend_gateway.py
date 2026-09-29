from __future__ import annotations

import contextlib
import http.server
import os
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class _TargetHandler(http.server.BaseHTTPRequestHandler):
    target_name = "unknown"

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        self.send_response(200)
        self.send_header("content-type", "text/plain")
        self.end_headers()
        self.wfile.write(f"{self.target_name}:{self.path}".encode())

    def log_message(self, *_args: object) -> None:
        return


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_target(name: str, port: int) -> http.server.ThreadingHTTPServer:
    handler = type(f"{name.title()}Handler", (_TargetHandler,), {"target_name": name})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _fetch(port: int, path: str) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return response.read().decode()


def test_frontend_gateway_routes_base_path_queries_to_enterprise_apps() -> None:
    backend_port = _free_port()
    core_port = _free_port()
    oms_port = _free_port()
    tms_port = _free_port()
    gateway_port = _free_port()
    servers = [
        _start_target("backend", backend_port),
        _start_target("core", core_port),
        _start_target("oms", oms_port),
        _start_target("tms", tms_port),
    ]
    env = {
        **os.environ,
        "BACKEND_PORT": str(backend_port),
        "CORE_FRONTEND_PORT": str(core_port),
        "OMS_FRONTEND_PORT": str(oms_port),
        "TMS_FRONTEND_PORT": str(tms_port),
        "FRONTEND_PORT": str(gateway_port),
        "FRONTEND_HOST": "127.0.0.1",
    }
    process = subprocess.Popen(
        ["node", str(REPO_ROOT / "deploy/docker-runtime/start-frontend-gateway.mjs")],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                if _fetch(gateway_port, "/ready").startswith("core:"):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("frontend gateway did not become reachable")

        assert _fetch(gateway_port, "/oms?oms_login=ok").startswith("oms:/oms?oms_login=ok")
        assert _fetch(gateway_port, "/oms/auth/callback?code=x").startswith("oms:/oms/auth/callback?code=x")
        assert _fetch(gateway_port, "/tms/test-school?tab=members").startswith(
            "tms:/tms/test-school?tab=members"
        )
        assert _fetch(gateway_port, "/api/v1/oms/auth/status?probe=1").startswith(
            "backend:/api/v1/oms/auth/status?probe=1"
        )
        assert _fetch(gateway_port, "/health?probe=1").startswith("backend:/health?probe=1")
        assert _fetch(gateway_port, "/settings?tab=tools").startswith("core:/settings?tab=tools")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        for server in servers:
            server.shutdown()
            server.server_close()
