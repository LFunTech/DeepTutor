"""文档站的可复现安装、调用示例和路由检查的回归测试。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from check_enterprise_routes import main as check_enterprise_routes, mounted_routes
from deeptutor_enterprise.api.application import create_application
from deeptutor.services.session.turns.environment import validate_text_request


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "agent-developer"


class DocumentationContractTests(unittest.TestCase):
    def test_only_third_party_routes_have_unique_detail_pages(self):
        routes = json.loads((ROOT / "src/data/enterprise-routes.json").read_text())
        self.assertEqual(len(routes), 15)
        self.assertEqual({route["audience"] for route in routes}, {"agent"})
        pages = list((DOCS / "api/http").glob("*.mdx"))
        self.assertEqual(len(pages), len(routes))
        for route in routes:
            page = DOCS / f'{route["doc"]}.mdx'
            self.assertTrue(page.is_file(), f'{route["method"]} {route["path"]}')
            body = page.read_text()
            self.assertIn(f'method: {route["method"]}', body)
            self.assertIn(f'path: "{route["path"]}"', body)
            for heading in ("## 用途与时机", "## 前置条件", "## 请求", "## 响应", "## 错误与恢复"):
                self.assertIn(heading, body, page.name)
            self.assertIn(f'# {route["method"]} `{route["path"]}`', body)

    def test_every_ws_command_has_detail_page(self):
        commands = [
            "start_turn", "subscribe_turn", "subscribe_session", "resume_from",
            "unsubscribe", "cancel_turn", "regenerate", "submit_user_reply",
            "check_active_turn", "auth_refresh", "ping",
        ]
        pages = list((DOCS / "api/ws").glob("*.mdx"))
        self.assertEqual(len(pages), len(commands))
        self.assertFalse((DOCS / "api/ws/user_input.mdx").exists())
        for command in commands:
            page = DOCS / "api/ws" / f"{command}.mdx"
            self.assertTrue(page.is_file(), command)
            body = page.read_text()
            self.assertIn(f'command: {command}', body)
            self.assertIn('<!-- ws-command -->', body)
            for heading in ("## 用途与时机", "## 前置条件", "## 请求字段", "## 响应与事件", "## 错误与恢复"):
                self.assertIn(heading, body, page.name)

    def test_public_pages_do_not_expose_private_surfaces_or_implementation(self):
        content = "\n".join(page.read_text() for page in DOCS.rglob("*.mdx"))
        content += (ROOT / "src/components/EnterpriseApiTable.tsx").read_text()
        content += (ROOT / "src/data/enterprise-routes.json").read_text()
        forbidden = [
            "/api/auth/login", "/api/auth/logout", "/api/auth/status",
            "/api/v1/auth/eduplus2/revocations", "/api/v1/eduplus2/webhooks",
            "/api/v1/enterprise/audit", "/health/", "/api/v1/oms/", "/api/v1/tms/",
            "AuthenticationMiddleware", "Postgres", "Redis", "ASGI", "OpenSpec",
            "deeptutor/", "extensions/enterprise/", "租约", "内部实现",
        ]
        for term in forbidden:
            self.assertNotIn(term, content, term)
    def test_lockfile_uses_public_https_registry(self):
        packages = json.loads((ROOT / "package-lock.json").read_text())["packages"]
        urls = [item["resolved"] for item in packages.values() if "resolved" in item]
        self.assertGreater(len(urls), 100)
        self.assertTrue(all(url.startswith("https://registry.npmjs.org/") for url in urls))

    def test_route_catalog_is_not_git_ignored(self):
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(ROOT / "src/data/enterprise-routes.json")],
            cwd=ROOT.parents[0],
            check=False,
        )
        self.assertEqual(result.returncode, 1)

    def test_direct_http_route_is_seen(self):
        def with_extra_route(enterprise):
            app = create_application(enterprise)

            @app.get("/api/v1/review-new-route")
            async def new_route():
                return {"ok": True}

            return app

        with patch("check_enterprise_routes.create_application", with_extra_route):
            http, _ = mounted_routes()
        self.assertIn(("GET", "/api/v1/review-new-route"), http)

    def test_direct_websocket_route_is_seen(self):
        def with_extra_route(enterprise):
            app = create_application(enterprise)

            @app.websocket("/api/v1/review-ws")
            async def new_route(ws):
                await ws.close()

            return app

        with patch("check_enterprise_routes.create_application", with_extra_route):
            _, ws = mounted_routes()
        self.assertIn("/api/v1/review-ws", ws)

    def test_new_direct_route_fails_catalog_check(self):
        def with_extra_route(enterprise):
            app = create_application(enterprise)

            @app.get("/api/v1/review-new-route")
            async def new_route():
                return {"ok": True}

            return app

        with patch("check_enterprise_routes.create_application", with_extra_route):
            with self.assertRaisesRegex(AssertionError, "missing=.*review-new-route"):
                check_enterprise_routes()

    def test_first_event_disconnect_keeps_original_request(self):
        quickstart = (DOCS / "quickstart.mdx").read_text()
        self.assertIn("operation_id = str(uuid.uuid4())", quickstart)
        self.assertIn("operation_id: string", quickstart)
        self.assertIn("startRequest: StartTurnRequest", quickstart)
        self.assertIn("原样重发预先保存的完整", quickstart)
        self.assertIn("幂等有效期以部署方提供的契约为准", quickstart)

    def test_upload_is_an_actionable_put_flow(self):
        create = (DOCS / "api/http/upload-intent.mdx").read_text()
        complete = (DOCS / "api/http/complete-upload.mdx").read_text()
        self.assertIn('"purpose":"chat_turn"', create)
        self.assertIn('method="PUT"', create)
        self.assertIn('start_turn.resource_ids', complete)

    def test_public_docs_have_no_demo_flow(self):
        published = "\n".join(page.read_text() for page in DOCS.rglob("*.mdx"))
        published += (ROOT / "sidebars.ts").read_text()
        published += (ROOT / "src/components/EnterpriseApiTable.tsx").read_text()
        published += (ROOT / "src/data/enterprise-routes.json").read_text()
        published += (ROOT / "README.md").read_text()
        for value in ("/demo/", "demo-start", "demo-callback", "demo-result", "demo-refresh", "identity-and-demo", "演示"):
            self.assertNotIn(value, published, value)
        self.assertFalse(list((DOCS / "api/http").glob("demo-*.mdx")))
        self.assertFalse((DOCS / "identity-and-demo.mdx").exists())
        self.assertIn("agent-developer/api/http/exchange", (ROOT / "sidebars.ts").read_text())

    def test_capability_selection_uses_published_turn_contract(self):
        guide = (DOCS / "capability-selection.mdx").read_text()
        for value in (
            "knowledge_bases", "skills", "mcp_tools", "context_policy",
            "required", "auto", "capability_usage", "mcp_tool_unavailable",
            '"capability":"chat"',
        ):
            self.assertIn(value, guide)
        self.assertIn("当前没有面向第三方 Agent 发布的选项发现接口", guide)
        self.assertIn("capability-selection.mdx", (DOCS / "api/ws/start_turn.mdx").read_text())

    def test_context_selection_is_per_turn_not_live_mutation(self):
        guide = (DOCS / "capability-selection.mdx").read_text()
        self.assertIn("同一会话的下一轮", guide)
        self.assertIn('"session_id":"session-001"', guide)
        self.assertIn("不能在运行中的 turn 更改", guide)
        self.assertIn("submit_user_reply", guide)
        self.assertNotIn("user_input", "\n".join(page.read_text() for page in DOCS.rglob("*.mdx")))
        self.assertNotIn("agent-developer/api/ws/user_input", (ROOT / "sidebars.ts").read_text())

    def test_capability_guide_covers_selection_validation_and_observed_usage(self):
        guide = (DOCS / "capability-selection.mdx").read_text()
        for value in (
            "## 选择并发送：TypeScript 示例",
            "knowledgeBaseIds",
            "skillIds",
            "done.metadata.capability_usage",
            "requested",
            "used",
            "unavailable",
            "不可将 `enabled` 解释为实际调用",
        ):
            self.assertIn(value, guide)
        self.assertIn("capability-selection.mdx", (DOCS / "quickstart.mdx").read_text())
        self.assertIn("capability-selection.mdx", (DOCS / "http-api.mdx").read_text())

    def test_capability_typescript_example_compiles(self):
        guide = (DOCS / "capability-selection.mdx").read_text()
        snippets = re.findall(r"```ts\n(.*?)\n```", guide, re.DOTALL)
        self.assertEqual(len(snippets), 1)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capability-selection.ts"
            source.write_text(snippets[0] + "\n")
            result = subprocess.run(
                [
                    str(ROOT / "node_modules/.bin/tsc"), "--noEmit", "--strict",
                    "--skipLibCheck", "--target", "ES2022", "--lib", "ES2022,DOM",
                    str(source),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_demo_page_options_are_not_a_published_agent_api(self):
        route = "/api/v1/enterprise/conversation-test/options"
        catalog = (ROOT / "src/data/enterprise-routes.json").read_text()
        published = "\n".join(page.read_text() for page in DOCS.rglob("*.mdx"))
        published += (ROOT / "sidebars.ts").read_text()
        self.assertNotIn(route, catalog)
        self.assertNotIn(route, published)
        self.assertNotIn("conversation-options", published)
        self.assertFalse((DOCS / "api/http/conversation-options.mdx").exists())

    def test_start_turn_page_covers_selected_context_errors(self):
        page = (DOCS / "api/ws/start_turn.mdx").read_text()
        for value in (
            '"knowledge_bases":[', '"skills":[', '"context_policy":"required"',
            "knowledge_base_unavailable", "skill_unavailable",
            "mcp_tool_unavailable", "required_context_unavailable",
            "done.metadata.capability_usage",
        ):
            self.assertIn(value, page)

    def test_enterprise_turn_limits_are_explicit_not_generic(self):
        page = (DOCS / "api/ws/start_turn.mdx").read_text()
        guide = (DOCS / "capability-selection.mdx").read_text()
        self.assertIn("当前企业入口仅支持 `chat`", page)
        self.assertIn("不支持非空 `config`", page)
        self.assertIn("`tools` 不是知识库、Skills 或外部工具选择器", page)
        self.assertIn("不能选择其他顶层 `capability`", guide)
        validate_text_request({"content": "你好", "capability": "chat", "config": {}})
        with self.assertRaisesRegex(ValueError, "capability is unavailable"):
            validate_text_request({"content": "你好", "capability": "deep_solve"})
        with self.assertRaisesRegex(ValueError, "configuration overrides are unavailable"):
            validate_text_request({"content": "你好", "capability": "chat", "config": {"x": 1}})

    def test_minimum_node_matches_docs_and_publish_command(self):
        package = json.loads((ROOT / "package.json").read_text())
        readme = (ROOT / "README.md").read_text()
        self.assertEqual(package["engines"]["node"], ">=22.12.0")
        self.assertIn("Node.js 22.12", readme)
        self.assertIn("DOCS_SITE_URL='https://", readme)

    def test_footer_contains_only_copyright_and_configured_filings(self):
        config = (ROOT / "docusaurus.config.ts").read_text()
        footer = config.split("footer: {", 1)[1].split("prism:", 1)[0]
        self.assertNotIn("links:", footer)
        self.assertIn("Copyright ©", footer)
        self.assertIn("DOCS_ICP_NUMBER", config)
        self.assertIn("DOCS_PUBLIC_SECURITY_NUMBER", config)

    def test_session_subscription_and_school_terminology(self):
        protocol = (DOCS / "websocket-protocol.mdx").read_text()
        self.assertIn("不会自动订阅未来", protocol)
        display = (ROOT / "src" / "components" / "EnterpriseApiTable.tsx").read_text()
        catalog = (ROOT / "src" / "data" / "enterprise-routes.json").read_text()
        http_page = (DOCS / "http-api.mdx").read_text()
        for content in (display, catalog, http_page):
            self.assertNotIn("租户" + "管理员", content)


if __name__ == "__main__":
    unittest.main()
