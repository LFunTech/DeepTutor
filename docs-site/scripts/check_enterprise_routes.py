"""校验第三方目录与企业入口实际路由的一致性；非第三方路由不进入站点。"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import textwrap

from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import Route, WebSocketRoute

from deeptutor_enterprise.api.application import AuthenticationMiddleware, create_application


CATALOG = Path(__file__).resolve().parents[1] / "src/data/enterprise-routes.json"
EXPECTED_WS = "/api/v1/ws"
SENSITIVE = {
    "/api/auth/login": ("account", "password"),
    "/api/auth/status": ("account", "none"),
    "/api/auth/logout": ("account", "dt_token"),
    "/api/v1/auth/eduplus2/exchange": ("agent", "eduplus2_user_jwt"),
    "/api/v1/auth/eduplus2/revocations": ("system", "hmac_signature"),
    "/api/v1/eduplus2/webhooks": ("system", "hmac_signature"),
    "/api/v1/enterprise/audit/eduplus2/events": ("admin", "dt_token_admin"),
    "/api/v1/enterprise/audit/eduplus2/exports": ("admin", "dt_token_admin"),
    "/api/settings/ui": ("agent", "none"),
    "/health/live": ("operations", "none"),
    "/health/ready": ("operations", "none"),
}
FORBIDDEN = {
    "/api/v1/external/turns",
    "/api/v1/tms/eduplus2/clients",
    "/api/v1/oms/eduplus2/clients",
}
PRIVATE_ROUTES = {
    ("POST", "/api/auth/login"),
    ("GET", "/api/auth/status"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/v1/auth/eduplus2/revocations"),
    ("POST", "/api/v1/eduplus2/webhooks"),
    ("GET", "/api/v1/enterprise/audit/eduplus2/events"),
    ("POST", "/api/v1/enterprise/audit/eduplus2/exports"),
    ("GET", "/api/v1/auth/eduplus2/demo/start"),
    ("GET", "/api/v1/auth/eduplus2/demo/callback"),
    ("GET", "/api/v1/auth/eduplus2/demo/result"),
    ("POST", "/api/v1/auth/eduplus2/demo/refresh"),
    ("GET", "/api/v1/enterprise/conversation-test/options"),
    ("GET", "/health/live"),
    ("GET", "/health/ready"),
}


def anonymous_paths() -> set[str]:
    """从当前中间件源码取白名单，避免复制一份易漂移的数组。"""

    tree = ast.parse(textwrap.dedent(inspect.getsource(AuthenticationMiddleware.__call__)))
    matches: list[set[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name):
            continue
        if node.left.id != "path" or len(node.ops) != 1 or not isinstance(node.ops[0], ast.In):
            continue
        value = node.comparators[0]
        if not isinstance(value, ast.Tuple):
            continue
        values = {item.value for item in value.elts if isinstance(item, ast.Constant)}
        if values and all(isinstance(item, str) for item in values):
            matches.append(values)
    if len(matches) != 1:
        raise AssertionError("无法唯一定位 AuthenticationMiddleware 的匿名白名单")
    return matches[0]


def mounted_routes() -> tuple[set[tuple[str, str]], set[str]]:
    """只装配路由，不启动数据库、Redis 或后台任务。"""

    enterprise = SimpleNamespace(deployment=SimpleNamespace(origins=["https://example.invalid"]))
    app = create_application(enterprise)
    http: set[tuple[str, str]] = set()
    ws: set[str] = set()
    for included in app.routes:
        if type(included).__name__ == "_IncludedRouter":
            for route in included.effective_candidates():
                if isinstance(route.original_route, APIRoute):
                    for method in route.methods:
                        http.add((method, route.path))
                elif isinstance(route.original_route, APIWebSocketRoute):
                    ws.add(included.include_context.prefix + route.original_route.path)
                else:
                    raise AssertionError(f"未知企业路由类型: {type(route.original_route).__name__}")
        elif isinstance(included, Route):
            if included.path == "/openapi.json" and included.methods == {"GET", "HEAD"}:
                continue  # FastAPI 自带的机器可读 schema，不是产品业务路由。
            for method in included.methods or set():
                http.add((method, included.path))
        elif isinstance(included, WebSocketRoute):
            ws.add(included.path)
        else:
            raise AssertionError(f"未知企业路由容器: {type(included).__name__}")
    return http, ws


def main() -> None:
    if not CATALOG.is_file():
        raise AssertionError(f"缺少企业 HTTP 目录: {CATALOG}")
    entries = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise AssertionError("企业 HTTP 目录必须是 JSON 数组")
    actual, websockets = mounted_routes()
    documented: set[tuple[str, str]] = set()
    anon = anonymous_paths()
    for entry in entries:
        if not isinstance(entry, dict):
            raise AssertionError(f"目录项必须是对象: {entry!r}")
        if set(entry) != {"method", "path", "audience", "credential", "summary", "doc"}:
            raise AssertionError(f"目录项字段不完整或存在多余字段: {entry!r}")
        method, path = entry["method"], entry["path"]
        key = (method, path)
        if key in documented:
            raise AssertionError(f"重复目录项: {method} {path}")
        documented.add(key)
        if entry["audience"] != "agent":
            raise AssertionError(f"非第三方接口不得发布: {method} {path}")
        if key in PRIVATE_ROUTES:
            raise AssertionError(f"私有接口不得发布: {method} {path}")
        detail = CATALOG.parents[2] / "docs/agent-developer" / f"{entry['doc']}.mdx"
        if not detail.is_file():
            raise AssertionError(f"缺少接口独立页面: {method} {path}: {detail}")
        if not isinstance(entry["summary"], str) or not entry["summary"].strip():
            raise AssertionError(f"缺少用途说明: {method} {path}")
        if path in FORBIDDEN:
            raise AssertionError(f"规划或本地专用接口被误列为企业契约: {path}")
        required = SENSITIVE.get(path)
        if required and (entry["audience"], entry["credential"]) != required:
            raise AssertionError(f"安全分类错误: {method} {path}，应为 {required}")
        if path in anon:
            if entry["credential"] not in {
                "none", "password", "eduplus2_user_jwt", "hmac_signature"
            }:
                raise AssertionError(f"匿名白名单凭证分类错误: {method} {path}")
        elif entry["credential"] not in {"dt_token", "dt_token_admin"}:
            raise AssertionError(f"中间件保护路由被误标为匿名: {method} {path}")
    if documented | PRIVATE_ROUTES != actual:
        missing = sorted(actual - documented - PRIVATE_ROUTES)
        extra = sorted(documented - actual)
        raise AssertionError(f"企业目录与路由不一致: missing={missing}, extra={extra}")
    if anon - {path for _, path in actual}:
        raise AssertionError(f"匿名白名单包含未挂载路径: {sorted(anon - {p for _, p in actual})}")
    if websockets != {EXPECTED_WS}:
        raise AssertionError(f"企业 WebSocket 路由不符: {websockets}")
    print(f"第三方 API 目录校验通过：{len(documented)} 个 HTTP，{len(websockets)} 个 WebSocket")


if __name__ == "__main__":
    main()
