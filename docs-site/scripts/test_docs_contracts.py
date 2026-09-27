"""文档站的可复现安装、调用示例和路由检查的回归测试。"""

from __future__ import annotations

import ast
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from check_enterprise_routes import main as check_enterprise_routes, mounted_routes
from deeptutor.api.routers.reading_extensions import ACTION_TIMEOUT_S
from deeptutor.core.capability_protocol import CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.core.tool_protocol import ToolDefinition, ToolParameter, ToolResult
from deeptutor_enterprise.api.application import create_application
from deeptutor.reading.extensions import ReadingContext, ReadingExtensionManifest, ReadingExtensionResult
from deeptutor.services.cli_apps.models import APP_ID_RE, ENTRY_POINT_RE
from deeptutor.services.cli_apps.runner import DEFAULT_TIMEOUT_S, MAX_OUTPUT_CHARS, MAX_TIMEOUT_S
from deeptutor.services.mcp.config import MCPServerConfig
from deeptutor.services.mcp.user_config import MAX_SERVERS_PER_OWNER
from deeptutor.services.skill.service import (
    _IMPORT_MAX_FILE_BYTES,
    _IMPORT_MAX_FILES,
    _IMPORT_MAX_TOTAL_BYTES,
    _MAX_READ_CHARS,
)
from deeptutor.services.session.turns.environment import validate_text_request
from deeptutor.utils.document_validator import DocumentValidator
from deeptutor.visualizers.protocol import MAX_MANIFEST_SCHEMA_CHARS, MAX_PAYLOAD_CHARS, VisualizerManifest
from deeptutor.visualizers.store import _MAX_ARCHIVE_BYTES, _MAX_ENTRIES, _MAX_ENTRY_BYTES


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

    def test_capacity_development_guides_are_independent_and_not_api_claims(self):
        slugs = (
            "mcp", "tool", "skill", "knowledge-base", "turn-capability",
            "loop-extension", "visualizer", "reading-extension", "cli-app",
        )
        directory = DOCS / "capacities"
        self.assertEqual(
            {page.stem for page in directory.glob("*.mdx")},
            {"index", *slugs},
        )
        sidebar = (ROOT / "sidebars.ts").read_text()
        self.assertIn("Capacity 开发规范", sidebar)
        overview = (directory / "index.mdx").read_text()
        self.assertIn("开发规范不等于企业入口已开放安装或调用", overview)
        for slug in slugs:
            page = (directory / f"{slug}.mdx").read_text()
            self.assertIn(f"agent-developer/capacities/{slug}", sidebar)
            self.assertIn(f"{slug}.mdx", overview)
            for heading in (
                "## 企业入口适用状态", "## 交付物与格式", "## 输入与输出",
                "## 安全与资源边界", "## 失败处理", "## 可验证样例", "## 开发自测",
            ):
                self.assertIn(heading, page, slug)
            self.assertNotIn("/api/space/", page, slug)
            self.assertNotIn("/api/settings/", page, slug)
            self.assertNotIn("/api/v1/oms/", page, slug)
            self.assertNotIn("/api/v1/tms/", page, slug)
        self.assertIn("当前企业入口仅支持", (directory / "turn-capability.mdx").read_text())
        self.assertIn("当前不要提交非空", (directory / "mcp.mdx").read_text())
        self.assertIn("## 开发规范与调用契约", (DOCS / "capability-selection.mdx").read_text())

    def test_capacity_development_examples_match_current_formats(self):
        directory = DOCS / "capacities"

        def first_fence(slug: str, language: str) -> str:
            body = (directory / f"{slug}.mdx").read_text()
            match = re.search(rf"```{language}\n(.*?)\n```", body, re.DOTALL)
            self.assertIsNotNone(match, slug)
            return match.group(1)

        visualizer = json.loads(first_fence("visualizer", "json"))
        VisualizerManifest.model_validate(visualizer)
        point_schema = visualizer["payload_schema"]["properties"]["points"]["items"]
        self.assertEqual(set(point_schema["required"]), {"x", "y"})

        reading = json.loads(first_fence("reading-extension", "json"))
        ReadingExtensionManifest.model_validate(reading)
        entry_point = tomllib.loads(first_fence("reading-extension", "toml"))
        self.assertIn(reading["id"], entry_point["project"]["entry-points"]["deeptutor.reading_extensions"])

        turn_entry_point = tomllib.loads(first_fence("turn-capability", "toml"))
        self.assertEqual(
            turn_entry_point["project"]["entry-points"]["deeptutor.extensions"]["echo_turn"],
            "echo_turn:EchoTurn",
        )
        ast.parse(first_fence("tool", "python"))
        ast.parse(first_fence("turn-capability", "python"))
        ast.parse(first_fence("loop-extension", "python"))
        ast.parse(first_fence("reading-extension", "python"))

        tool_namespace: dict[str, object] = {}
        exec(first_fence("tool", "python"), tool_namespace)
        add_numbers = tool_namespace["AddNumbers"]()
        self.assertEqual(asyncio.run(add_numbers.execute(a=2, b=3)).content, "5")
        self.assertFalse(asyncio.run(add_numbers.execute(a="2", b=3)).success)

        reading_namespace: dict[str, object] = {}
        exec(first_fence("reading-extension", "python"), reading_namespace)
        extension = reading_namespace["ExplainSelection"]()
        context = ReadingContext(material_id="sample", locator=1, visible_text="函数有定义域", selection="定义域")
        self.assertEqual(extension.run_action("explain", context).type, "card")
        with self.assertRaises(ValueError):
            extension.run_action("unknown", context)

        turn_namespace: dict[str, object] = {}
        exec(first_fence("turn-capability", "python"), turn_namespace)
        emitted = []

        class FakeStream:
            async def emit(self, event):
                emitted.append(event)

            @asynccontextmanager
            async def stage(self, name, *, source=""):
                yield

        turn_context = UnifiedContext(user_message="测试")
        asyncio.run(turn_namespace["EchoTurn"]().run(turn_context, FakeStream()))
        self.assertEqual(turn_context.capability_output.agent_output, "收到：测试")
        self.assertEqual([event.type for event in emitted], [StreamEventType.RESULT])

    def test_capacity_guides_track_implemented_limits_and_semantics(self):
        directory = DOCS / "capacities"

        def body(slug: str) -> str:
            return (directory / f"{slug}.mdx").read_text()

        mcp = body("mcp")
        self.assertIn(str(MAX_SERVERS_PER_OWNER), mcp)
        self.assertIn(str(MCPServerConfig.model_fields["tool_timeout"].default), mcp)
        for value in ("streamableHttp", "sse", "stdio", "structuredContent", "isError", "不会自动"):
            self.assertIn(value, mcp)

        tool = body("tool")
        for name in ToolDefinition.__dataclass_fields__:
            self.assertIn(f"`{name}`", tool)
        for name in ToolParameter.__dataclass_fields__:
            self.assertIn(f"`{name}`", tool)
        for name in ToolResult.__dataclass_fields__:
            self.assertIn(f"`{name}`", tool)
        self.assertIn("不会替 `execute` 自动验证参数", tool)

        skill = body("skill")
        for limit in (_IMPORT_MAX_FILE_BYTES, _IMPORT_MAX_TOTAL_BYTES, _IMPORT_MAX_FILES, _MAX_READ_CHARS):
            self.assertIn(f"{limit:,}", skill)
        for value in ("`always`", "`requires.bins`", "`requires.env`", "`requires.sandbox`", "`SKILL.md`"):
            self.assertIn(value, skill)

        kb = body("knowledge-base")
        self.assertIn(str(DocumentValidator.MAX_FILE_SIZE // (1024 * 1024)), kb)
        self.assertIn("没有定义可由第三方自行上传", kb)
        self.assertIn("不等同", kb)

        turn = body("turn-capability")
        for name in CapabilityManifest.__dataclass_fields__:
            self.assertIn(name, turn)
        for event_type in StreamEventType:
            self.assertIn(f"`{event_type.value}`", turn)
        for name in ("user_message", "session_id", "conversation_history", "knowledge_bases", "attachments", "capability_output"):
            self.assertIn(f"`{name}", turn)
        self.assertIn("`run(context, stream)`", turn)
        self.assertIn("不会仅因填写", turn)

        loop = body("loop-extension")
        for name in ("owned_tools", "is_active", "system_block", "augment_kwargs", "pre_loop_seed", "pre_loop", "on_user_pause", "on_user_resume", "owned_kbs"):
            self.assertIn(f"`{name}", loop)
        self.assertIn("排他", loop)

        visualizer = body("visualizer")
        for name in VisualizerManifest.model_fields:
            self.assertIn(f"`{name}`", visualizer)
        for limit in (MAX_PAYLOAD_CHARS, MAX_MANIFEST_SCHEMA_CHARS):
            self.assertIn(f"{limit:,}", visualizer)
        for limit in (_MAX_ARCHIVE_BYTES // (1024 * 1024), _MAX_ENTRY_BYTES // (1024 * 1024), _MAX_ENTRIES):
            self.assertIn(str(limit), visualizer)
        self.assertIn('只接受 `iframe`', visualizer)

        reading = body("reading-extension")
        for name in ReadingExtensionManifest.model_fields | ReadingContext.model_fields | ReadingExtensionResult.model_fields:
            self.assertIn(f"`{name}`", reading)
        self.assertIn(str(ACTION_TIMEOUT_S), reading)
        for value in ("`toolbar`", "`selection`", "`visible_text`", "`browser_speech`", "`quiz`"):
            self.assertIn(value, reading)

        cli = body("cli-app")
        self.assertIn(APP_ID_RE.pattern, cli)
        self.assertIn(ENTRY_POINT_RE.pattern, cli)
        for limit in (DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, MAX_OUTPUT_CHARS):
            self.assertIn(f"{limit:,}" if limit >= 1000 else str(limit), cli)
        for value in ("`args`", "`timeout_s`", "`exit_code`", "`timed_out`", "`ToolResult.success`", "仍为 `true`"):
            self.assertIn(value, cli)

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
