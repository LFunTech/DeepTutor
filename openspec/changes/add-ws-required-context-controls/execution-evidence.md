# Execution Evidence — add-ws-required-context-controls

日期：2026-09-20

## 实现摘要

- 扩展 `TurnRequest` / WebSocket contract：新增 `mcp_tools` 与 `context_policy`，并生成 JSON schema / TypeScript contracts。
- 新增 turn-level required context helper：统一 `auto` / `best_effort` / `required` 解析、脱敏 requested/resolved/unavailable 记录、稳定错误码与能力使用摘要。
- 在 agentic loop 中接入 required context：
  - MCP tools 进入 provider/deferred tool preloading 链路；required 缺失时 fail closed。
  - KB required 校验存在/ready/授权，并在受限 configured 环境无法挂载 RAG 时 fail closed。
  - 内置 tools required 校验是否进入实际 enabled tool surface。
- 在普通与 enterprise configured turn runtime 中写入 request snapshot 和 DONE metadata 的 `capability_usage` / context diagnostics。
- WebSocket start rejection 尽量透传异常上的稳定 `error_code`。
- 企业扩展新增 `/api/v1/enterprise/conversation-test/options`，返回普通测试页所需的 KB / skills / MCP tools 安全展示清单，不返回 endpoint/secret/provider config。
- 新增 `/enterprise/eduplus2/conversation-test` 普通用户测试页：
  - 复用 EduPlus2 demo login/result/refresh；token 仅保留内存态。
  - 支持新建/恢复 session、本页 transcript、KB/skill/MCP 选择、默认 required/自动切换。
  - 文件选择后执行 upload intent → pre-signed PUT → complete，再把 `resource_ids` 放入真实 `start_turn`。
  - 支持 Web Speech API 语音输入，不支持时给出降级提示。
  - 每轮回答展示“本轮用了什么”的普通用户文案，排查详情默认收起且只显示脱敏 code。
- 更新 EduPlus2 fronting app 接入文档，说明 context policy、MCP tool name 边界、资源上传与示例 payload。

## 验证命令

```bash
# 合约与 required context Python tests
.venv/bin/python -m pytest tests/api/test_frontend_contract_export.py tests/agents/chat/test_required_context.py -q
# 结果：10 passed

# 企业 options / 资源 / required MCP / 生产资源边界 targeted tests
.venv/bin/python -m pytest \
  extensions/enterprise/tests/test_application.py::test_conversation_test_options_are_authenticated_and_non_secret \
  extensions/enterprise/tests/test_application.py::test_enterprise_turn_environment_materializes_image_resource_refs_for_llm \
  extensions/enterprise/tests/test_application.py::test_enterprise_turn_environment_required_mcp_fails_closed \
  extensions/enterprise/tests/test_application.py::test_enterprise_production_ws_rejects_legacy_payload_and_verifies_resource_refs \
  -q
# 结果：4 passed

# Ruff scoped check
.venv/bin/python -m ruff check \
  deeptutor/services/session/required_context.py \
  deeptutor/core/turn_request.py \
  deeptutor/api/contracts/turn_protocol.py \
  deeptutor/api/routers/unified_ws.py \
  deeptutor/agents/loop/pipeline.py \
  deeptutor/services/session/turns/executor.py \
  deeptutor/services/session/turns/configured.py \
  deeptutor/services/session/turns/environment.py \
  extensions/enterprise/src/deeptutor_enterprise/runtime.py \
  extensions/enterprise/src/deeptutor_enterprise/api/application.py \
  tests/agents/chat/test_required_context.py \
  tests/api/test_frontend_contract_export.py \
  extensions/enterprise/tests/test_application.py
# 结果：All checks passed

# 合约生成与一致性
.venv/bin/python -m deeptutor.api.contracts.export
cd web && npm run contracts:generate
cd web && npm run contracts:check
# 结果：contracts:check passed

# 前端 typecheck
cd web && npm run typecheck
# 结果：passed

# 前端 lint
cd web && npm run lint
# 结果：0 errors, 159 warnings（含本次新增页面 i18n literal warnings；仓库现有同类 warning 未在本 change 全面治理）

# 新增/相关 node tests（手动编译后只运行目标 test files）
cd web && node node_modules/typescript/bin/tsc -p tsconfig.node-tests.json && \
  node -r ./scripts/register-node-test-aliases.cjs --test \
    dist/node-tests/tests/start-turn-input.test.js \
    dist/node-tests/tests/enterprise-conversation-test.test.js
# 结果：9 passed

# OpenSpec validation
openspec validate add-ws-required-context-controls --strict
openspec validate --all --strict
# 结果：change valid；15 passed, 0 failed

# Playwright smoke（未登录态页面骨架）
cd web && npm run dev -- --hostname 127.0.0.1 --port 3311
PWCLI=$HOME/.codex/skills/playwright/scripts/playwright_cli.sh
$PWCLI open http://127.0.0.1:3311/enterprise/eduplus2/conversation-test
$PWCLI snapshot
# 结果：页面 200，展示“一个给普通用户使用的完整对话测试台”和“使用测试登录进入”；console 仅 React DevTools/HMR 信息。

# 2026-09-20 登录回跳修复验证
# RED：Next rewrite 后 API origin 为 localhost:8001 时，新普通测试页 return_to 被错误回退到旧 fronting-demo
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py::test_demo_callback_preserves_trusted_return_to_when_api_origin_is_internal \
  -q
# 修复前结果：1 failed，callback path 为 /enterprise/eduplus2/fronting-demo
# 修复后结果：1 passed

PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py -q
# 结果：10 passed

.venv/bin/python -m ruff check \
  extensions/enterprise/src/deeptutor_enterprise/eduplus2/fronting_demo.py \
  extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py
# 结果：All checks passed!

openspec validate add-ws-required-context-controls --strict
# 结果：Change 'add-ws-required-context-controls' is valid

# 真实本地 HTTPS 路由 smoke：start 携带 conversation-test return_to，callback 后回新页面
python3 - <<'PY'
import http.client, ssl, urllib.parse
base = "https://deeptutor.lfun.pub"
return_to = base + "/enterprise/eduplus2/conversation-test"
start_path = "/api/v1/auth/eduplus2/demo/start?" + urllib.parse.urlencode({"return_to": return_to})
conn = http.client.HTTPSConnection("deeptutor.lfun.pub", timeout=10, context=ssl.create_default_context())
conn.request("GET", start_path)
loc = conn.getresponse().getheader("location") or ""
state = urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query).get("state", [""])[0]
conn.close()
callback_path = "/api/v1/auth/eduplus2/demo/callback?" + urllib.parse.urlencode({"state": state, "error": "access_denied"})
conn = http.client.HTTPSConnection("deeptutor.lfun.pub", timeout=10, context=ssl.create_default_context())
conn.request("GET", callback_path)
callback_loc = conn.getresponse().getheader("location") or ""
print(urllib.parse.urlsplit(callback_loc).path)
conn.close()
PY
# 结果：/enterprise/eduplus2/conversation-test

# 2026-09-20 普通测试页不可操作问题修复验证
# 根因：前端把 demo result 顶层 expires_at（demo_session 缓存 TTL）误当成 dt_token 过期时间；
# 本地 dt_token TTL 为 60 秒，页面因此显示“已就绪”但 options/WS 使用过期 token 并 401。
cd web && node node_modules/typescript/bin/tsc -p tsconfig.node-tests.json && \
  node -r ./scripts/register-node-test-aliases.cjs --test \
    dist/node-tests/tests/start-turn-input.test.js \
    dist/node-tests/tests/enterprise-conversation-test.test.js
# 结果：10 passed；新增回归覆盖 summary.expires_at 优先于顶层 expires_at。

cd web && npm run typecheck
# 结果：passed

cd web && npx eslint \
  app/enterprise/eduplus2/conversation-test/page.tsx \
  lib/enterprise-conversation-test.ts \
  tests/enterprise-conversation-test.test.ts
# 结果：0 errors，26 个既有/页面文案 i18n warnings。

cd web && npm run build
# 结果：compiled/typecheck/static generation passed；包含 /enterprise/eduplus2/conversation-test。

openspec validate add-ws-required-context-controls --strict
# 结果：Change 'add-ws-required-context-controls' is valid

# Playwright CLI 确定性 UI smoke（网络拦截）：
# demo/result 返回 expired-token + summary.expires_at 已过期 + 顶层 expires_at 仍在未来；
# 页面必须先调用 demo/refresh，再用 fresh-token 请求 options 并展示可选能力。
PWCLI=$HOME/.codex/skills/playwright/scripts/playwright_cli.sh
$PWCLI run-code --filename /tmp/deeptutor-conversation-token-smoke.js --raw
# 结果 calls:
#   result
#   refresh body {"demo_session":"ui-smoke"}
#   options authorization "Bearer fresh-token"
# 页面正文包含“已就绪”“测试知识库”“分步讲解”“外部检索”。

# 2026-09-20 登录态页面布局修复验证
# 根因：全局 html/body overflow hidden；登录态内容超过视口但页面 main 没有自己的滚动容器，
# 中等视口下侧栏+对话区堆叠，底部输入区被裁掉且没有滚动条。
PWCLI=$HOME/.codex/skills/playwright/scripts/playwright_cli.sh
$PWCLI run-code --filename /tmp/deeptutor-layout-assert.js --raw
# 修复前结果：失败，bodyOverflow hidden、mainOverflow visible、mainCanScroll false、sendBottom 2210 > viewportHeight 620。
# 修复后结果：
#   mainOverflow auto
#   mainCanScroll true
#   滚到底后 sendBottom 562 <= viewportHeight 620

$PWCLI run-code --filename /tmp/deeptutor-layout-large-probe.js --raw
# 结果：1280x720 下 main overflow hidden；aside overflow auto 且可滚动；
# section 高度受约束；发送按钮 bottom 662 <= viewportHeight 720。
```

## 已知未完全验证项

- 浏览器端已完成真实登录态 WebSocket smoke（发送一轮对话并收到服务端帧）；文件上传、多轮长对话和 required context 选择链路仍需继续端到端跑完。
- `npm run test:node` 仓库全量仍有既有 architecture/no-v1-chat-surface 失败：
  - `app/enterprise/eduplus2/fronting-demo/page.tsx` 直接使用 browser storage / raw fetch。
  - `app/enterprise/audit/eduplus2/page.tsx` 直接 raw fetch。
  - `app/dev/eduplus/callback/route.ts` 含 `/api/v1` 字符串。
  这些失败在本 change 新页面加入前已存在；本次新增页面未增加这些 architecture violation。
- 负例覆盖已包含 missing MCP、missing KB、missing builtin tool、best-effort unavailable、生产 raw attachments/resource refs、非图片资源进入 LLM 的 fail-closed 路径；尚未逐项新增私有 KB、未 ready KB、MCP 未授权 provider 的独立测试 fixture。
- 音频/视频资源仍按 ObjectStore resource contract 上传；当前 enterprise model materialization 仅支持 image，音频/视频进入模型前会 fail closed，完整音视频转码/解析不在本 proposal 范围。

## 2026-09-20 本地 HTTPS WebSocket 入口修复验证

根因：`deeptutor.lfun.pub` 的 `local-ssl.tsv` 将真实 WebSocket 后端挂在 `/ws` 前缀：

```text
deeptutor.lfun.pub    /      http  127.0.0.1:3782
deeptutor.lfun.pub    /ws    ws    127.0.0.1:8001
```

local-ssl 会剥离匹配前缀，因此浏览器需要访问 `wss://deeptutor.lfun.pub/ws/api/v1/ws`，后端实际收到 `/api/v1/ws`。当前前端 bundle 未带本地 WS URL 配置时默认连 `wss://deeptutor.lfun.pub/api/v1/ws`，该路径走普通 HTTP/Next 入口，nginx access log 返回 `401`，无法完成 WebSocket Upgrade。

运行时修复：以本地 HTTPS WS 入口重建并重启前端：

```bash
cd web
NEXT_PUBLIC_EDUPLUS2_DEMO_WS_URL='wss://deeptutor.lfun.pub/ws/api/v1/ws' npm run build
NEXT_PUBLIC_EDUPLUS2_DEMO_WS_URL='wss://deeptutor.lfun.pub/ws/api/v1/ws' npm run start -- --hostname 127.0.0.1 --port 3782
```

验证：

```bash
# bundle 中包含本地 WS 入口
cd web && grep -R "wss://deeptutor.lfun.pub/ws/api/v1/ws" -l .next/static .next/server
# 结果包含：
# .next/static/chunks/app/enterprise/eduplus2/fronting-demo/page-*.js
# .next/static/chunks/app/enterprise/eduplus2/conversation-test/page-*.js

# 页面 200，加载新 conversation-test chunk
curl -sS https://deeptutor.lfun.pub/enterprise/eduplus2/conversation-test | grep -o 'page-[a-f0-9]*\.js' | head
curl -sS -o /dev/null -w 'page_status=%{http_code}\n' https://deeptutor.lfun.pub/enterprise/eduplus2/conversation-test
# 结果：page_status=200

# Playwright 真实浏览器发送一轮对话
# 结果：WebSocket URL = wss://deeptutor.lfun.pub/ws/api/v1/ws；framesOut=1；framesIn=24；closed=true；consoleErrors=[]。

# nginx access log 真实 Upgrade 成功
grep -E ' /(api/v1/ws|ws/api/v1/ws) ' "$HOME/Projects/maintenance/nginx-local/logs/deeptutor.lfun.pub.access.log" | tail
# 结果包含："GET /ws/api/v1/ws HTTP/1.1" 101
```

## 2026-09-20 普通测试页能力清单修复验证

根因：

- 本地企业 demo 后端未绑定 `.local/deeptutor-dev/home`，而当前可用的 DeepTutor KB 配置在 `.local/deeptutor-dev/home/data/knowledge_bases/kb_config.json`，导致 options 接口从默认 repo `data/` 读取时知识库为空。
- `conversation-test/options` 将 `SkillSummaryEntry.description` 放进 `label`，页面上显示成一大段说明；同时前端把 DeepTutor `skills` 翻成“学习方法”，普通用户和调试者都难以理解。

修复：

- 本地 `.secrets/run-local-enterprise-demo-backend.sh` 增加 `DEEPTUTOR_HOME=$PWD/.local/deeptutor-dev/home`，重启后端后 options 可读取当前 DeepTutor home 中的 KB。
- Skills 选项后端返回 `label=entry.name`，说明放在 `description`。
- 普通测试页文案从“学习方法”改为“Skills 指导技能”。

验证：

```bash
PYTHONPATH=.:extensions/enterprise/src .venv/bin/python -m pytest \
  extensions/enterprise/tests/test_application.py::test_conversation_test_options_are_authenticated_and_non_secret \
  extensions/enterprise/tests/test_application.py::test_conversation_test_options_show_skill_names_as_labels \
  -q
# 结果：2 passed

cd web && node node_modules/typescript/bin/tsc -p tsconfig.node-tests.json && \
  node -r ./scripts/register-node-test-aliases.cjs --test \
    dist/node-tests/tests/enterprise-conversation-test.test.js
# 结果：5 passed

cd web && npm run build
# 结果：compiled/typecheck/static generation passed；加载 .env.local。

openspec validate add-ws-required-context-controls --strict
# 结果：Change 'add-ws-required-context-controls' is valid

# 真实本地 options smoke（不输出 token/账号/密钥）
# 结果：
# knowledge_bases count 2：local-lightrag(status=error, disabled=true), test(status=ready, disabled=false)
# skills count 5：docx/pdf/pptx/skill-creator/xlsx，label 为短 skill 名称
# mcp_tools count 0：当前本地 registry 未暴露 MCP tool rows
```

## 2026-09-20 普通测试页流式富文本输出验证

需求：普通对话测试页在 `/api/v1/ws` 返回 `content` chunk 时即时更新 assistant 气泡，并对 assistant 输出进行 Markdown、LaTeX/KaTeX 与 fenced code block 渲染；用户 turn 保持原文展示。

实现：

- 新增 `web/app/enterprise/eduplus2/conversation-test/TranscriptTurnContent.tsx`，assistant turn 使用既有 `MarkdownRenderer`（启用 math/code，禁用外链图片），pending 状态展示“正在组织回答…”/“正在输出”。
- `conversation-test/page.tsx` 保留现有 WebSocket `content` chunk 追加逻辑，并改为用 `TranscriptTurnContent` 渲染每个 turn；用户 turn 继续 `whitespace-pre-wrap` 原文展示。

TDD 验证：

```bash
npm --prefix web run test:unit -- enterprise-conversation-rich-content.spec.tsx
# RED：组件尚不存在，Vitest import 失败。
# GREEN：2 tests passed。覆盖：
# - streaming assistant chunk 显示“正在输出”，Markdown strong、KaTeX 和 fenced code 可渲染；
# - user turn 中的 Markdown 控制符保持原文，不渲染成 assistant 富文本。
```

补充验证（同日）：

```bash
npm --prefix web run typecheck
# 结果：exit 0

cd web && npx eslint app/enterprise/eduplus2/conversation-test/TranscriptTurnContent.tsx tests/enterprise-conversation-rich-content.spec.tsx
# 结果：exit 0，无输出

npm --prefix web run build
# 结果：exit 0，/enterprise/eduplus2/conversation-test static route 构建成功

openspec validate --all --strict
# 结果：15 passed, 0 failed
```

本地服务重启与页面烟测：

```bash
# 前端使用 standalone server 重新启动在 127.0.0.1:3782；HTTPS local-ssl 入口保持 deeptutor.lfun.pub。
curl -sS -o /dev/null -w 'direct_status=%{http_code}\n' http://127.0.0.1:3782/enterprise/eduplus2/conversation-test
# 结果：direct_status=200

curl -k -sS -o /dev/null -w 'https_status=%{http_code}\n' https://deeptutor.lfun.pub/enterprise/eduplus2/conversation-test
# 结果：https_status=200

# 新 conversation-test chunk 可加载，包含 streaming/Markdown renderer 路径。
curl -sS -D /tmp/chunk.headers -o /tmp/chunk.js \
  http://127.0.0.1:3782/_next/static/chunks/app/enterprise/eduplus2/conversation-test/page-6e0634a34816c91b.js
# 结果：HTTP/1.1 200 OK；grep 可见“正在输出”和 enableMath。

PWCLI=$HOME/.codex/skills/playwright/scripts/playwright_cli.sh
$PWCLI open https://deeptutor.lfun.pub/enterprise/eduplus2/conversation-test
$PWCLI snapshot
# 结果：页面 title 为 DeepTutor，展示普通测试页未登录入口与“使用测试登录进入”。
```

## 2026-09-20 required KB 对话失败修复验证

用户现象：普通测试页登录后选择 `test` 知识库发送 WS 对话，页面返回 “Requested operation is unavailable or invalid” 或 “Turn execution failed”，无法完成 required KB 对话。

根因：

- 本地企业部署配置 `allowed_tools` 只允许 `ask_user`，options 接口却把 ready KB 展示为可选；选择 KB 后 required 模式必然在后端被拒绝。
- 企业 `DeploymentConfig.allowed_tools` 类型只接受 `ask_user`，无法把通用内置 `rag` 工具声明为部署允许项。
- configured turn 在 `TurnEnvironment.prepare_request()` 后仍用 core 默认文本校验拒绝非 `ask_user` 工具，并额外硬编码 `prepared.allowed_tools ⊆ {"ask_user"}`，导致 `rag` 即使经企业配置允许也不能进入真实执行路径。
- PG turn event 引用校验把 RAG trace 中用于显示/排查的 `kb_name`（tool args / sources metadata）误判为未授权会话外部依赖，RAG 已经执行成功后仍在事件持久化阶段失败。
- 前端收到 `error` / `protocol_error` 后没有主动释放发送态，后端保持 WS 连接时页面可能卡在“发送中…”。
- 后端重启后旧 `demo_session` 会失效；页面此前在带旧 query 的 URL 上只显示“需要登录/Demo session not found”，没有回到普通登录入口。

修复：

- `DeploymentConfig.allowed_tools` 增加通用 `rag`；本地 `.secrets/deeptutor-local-enterprise-deployment.json` 已加入 `["ask_user", "rag"]`（未提交密钥文件）。
- `conversation-test/options` 在部署未允许 `rag` 时将 KB 标为不可用，避免页面展示“可选但发送必失败”的知识库。
- configured turn 的前置文本校验改为先延迟工具授权到 enterprise turn environment，prepare 后再按 `prepared.allowed_tools` 校验；内置工具存在性改为查 `BUILTIN_TOOL_SPEC_BY_NAME`，不再硬编码只允许 `ask_user`。
- PG `validate_reference_shape` 对 turn event metadata 中的 RAG `kb_name` provenance 放行，但普通 message/session metadata 中的裸 `kb_name` 仍保持拒绝。
- 普通测试页新增 terminal WS event 判定，`error` / `protocol_error` / `done` 都释放发送态；错误事件后主动 close socket。
- 旧 demo session 加载失败时回到普通登录 landing，并显示可重新登录的按钮。

TDD/回归验证：

```bash
PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/pytest -q \
  tests/agents/chat/test_required_context.py \
  tests/persistence/postgres/business/test_session_request_snapshot.py::test_rag_sources_metadata_kb_name_is_not_treated_as_unscoped_dependency \
  extensions/enterprise/tests/test_configuration.py::test_deployment_config_allows_rag_tool_for_required_knowledge_bases \
  extensions/enterprise/tests/test_application.py::test_conversation_test_options_disable_kbs_when_rag_policy_is_not_enabled \
  -o asyncio_mode=auto
# 结果：10 passed, 1 warning

./.venv/bin/ruff check \
  deeptutor/services/session/turns/environment.py \
  deeptutor/services/session/turns/configured.py \
  deeptutor/persistence/postgres/session_validation.py \
  extensions/enterprise/src/deeptutor_enterprise/configuration.py \
  extensions/enterprise/src/deeptutor_enterprise/api/application.py \
  tests/agents/chat/test_required_context.py \
  tests/persistence/postgres/business/test_session_request_snapshot.py \
  extensions/enterprise/tests/test_configuration.py \
  extensions/enterprise/tests/test_application.py
# 结果：All checks passed!

cd web && python3 - <<'PY'
import shutil
shutil.rmtree('dist/node-tests', ignore_errors=True)
PY
node_modules/.bin/tsc -p tsconfig.node-tests.json && \
  node -r ./scripts/register-node-test-aliases.cjs --test \
    dist/node-tests/tests/enterprise-conversation-test.test.js
# 结果：7 tests passed

npm --prefix web run test:unit -- enterprise-conversation-rich-content.spec.tsx
# 结果：1 file passed, 2 tests passed

npm --prefix web run typecheck
# 结果：exit 0

cd web && npx eslint app/enterprise/eduplus2/conversation-test/page.tsx lib/enterprise-conversation-test.ts tests/enterprise-conversation-test.test.ts
# 结果：exit 0；仅既有 i18n/no-literal-ui-text warnings，无 error

npm --prefix web run build
# 结果：exit 0，/enterprise/eduplus2/conversation-test 构建成功

openspec validate add-ws-required-context-controls --strict
# 结果：Change 'add-ws-required-context-controls' is valid

openspec validate --all --strict
# 结果：15 passed, 0 failed
```

真实浏览器 smoke：

- 后端重启后，旧 `demo_session` 页面显示 “Demo session not found” 并出现“使用测试登录进入”按钮。
- 用 `.secrets/.login-credentials` 的本地测试账号完成 EduPlus2 demo 登录。
- 在普通测试页选择知识库 `test`，保持默认“强制可用”，发送：`请用知识库回答：fn(x)=x^2 的图像是什么？用一句话回答，并包含公式 $y=x^2$。`
- 结果：WS 连接成功，页面流式渲染 assistant 回复；LaTeX 被渲染为公式；“本轮用了什么”显示 `user:kb:test：已用于回答` 与 `知识库检索：已用于回答`。后端本轮无 `Configured turn failed` 堆栈。

## 2026-09-20 首个可见 token 慢 / 长耗时 WS 认证过期修复验证

用户现象：普通测试页在上传资源或选择知识库后点击开始对话，首个可见回答 token 很慢；一旦超过本地 demo token 的短有效期，页面可能长时间停在“正在组织回答…”且后端出现 `PermissionError: authentication required`。

定位证据：

- 浏览器页面复现：发送含资源/知识库的真实 WS turn 后，页面只显示 pending 状态，首个 assistant content 未出现。
- 后端日志复现：同一 turn 的 `_configured_event()` 在事件持久化/发布前重新鉴权失败，堆栈落在 `enterprise.identity.authenticate(token)`，随后订阅失败。
- 本地 demo refresh 令牌解码只打印脱敏摘要：`expires_in_seconds=60`，说明 demo `dt_token` 有效期约 60 秒。
- 页面旧实现仅在发送前/WS open 时刷新一次 token，没有在长时间模型/RAG/多模态处理期间继续发送 `auth_refresh`，因此长 turn 会在首包前或执行中因 token 过期失败。

修复：

- 普通测试页增加长连接 token refresh loop：根据 `expires_at - leeway` 计算下一次刷新时间；刷新成功后通过现有 WS `auth_refresh` 命令把新 token 送入同一 socket 的认证上下文；turn terminal/error/close 时清理 timer。
- 页面保存最新 token/expiry 到 ref，避免 React state 异步更新导致 WS loop 使用旧过期时间。
- 首个 content 前新增普通用户友好的进度提示：认证保持在线、正在查找知识库、已找到参考内容、正在规划回答等，不展示 raw WS frame。
- 保持后端 fail-closed 认证语义不变；本次只修前端长连接续期与首包前可见反馈，不把过期 token 降级为可用。

TDD/回归验证：

```bash
cd web && python3 - <<'PY'
from pathlib import Path
import shutil
p = Path('dist/node-tests')
if p.exists():
    shutil.rmtree(p)
PY
node_modules/.bin/tsc -p tsconfig.node-tests.json && \
  node -r ./scripts/register-node-test-aliases.cjs --test \
    dist/node-tests/tests/enterprise-conversation-test.test.js
# RED：新增测试先因缺少 nextConversationAuthRefreshDelayMs / formatConversationProgressForPeople 导出失败。
# GREEN：实现后 10 tests passed。

npm --prefix web run test:unit -- enterprise-conversation-rich-content.spec.tsx
# 结果：1 file passed, 2 tests passed

npm --prefix web run typecheck
# 结果：exit 0

cd web && npx eslint \
  app/enterprise/eduplus2/conversation-test/page.tsx \
  app/enterprise/eduplus2/conversation-test/TranscriptTurnContent.tsx \
  lib/enterprise-conversation-test.ts \
  tests/enterprise-conversation-test.test.ts \
  tests/enterprise-conversation-rich-content.spec.tsx
# 结果：exit 0；仅既有 i18n/no-literal-ui-text warnings，无 error

npm --prefix web run build
# 结果：exit 0，/enterprise/eduplus2/conversation-test 构建成功
```

真实浏览器 smoke：

- 重新复制 `.next/static` 到 standalone 目录并重启前端：`127.0.0.1:3782`，HTTPS 入口仍为 `https://deeptutor.lfun.pub`。
- 刷新普通测试页，选择知识库 `test`，发送：`请用知识库中的内容回答，并尽量详细说明：你能检索到什么？`
- 页面在首个回答 token 前显示“正在连接对话服务…”，后端日志出现多次 `/api/v1/auth/eduplus2/demo/refresh 200 OK`，证明 WS 长 turn 期间进行了续期；`auth_ack` 不再覆盖对话气泡文案。
- 约 18 秒出现首个可见 assistant 内容：“我先在知识库里检索一下……”；继续等待超过 60 秒 demo token 窗口后，turn 正常完成并展示 Markdown 表格/标题与“本轮用了什么”。
- 后端该轮未再出现 `Configured turn failed` / `Turn subscription failed (PermissionError)`。

## 2026-09-20 普通测试页思考过程面板验证

用户要求：普通对话页应展示类似 DeepSeek 网页的 thinking 过程。

设计边界：

- 页面展示服务端显式发出的用户可见流式轨迹：`thinking`、`progress`、`tool_call`、`sources`。
- 页面不展示 raw WS frame、raw JSON、工具调用参数、token、Secret、signed URL、ObjectStore key、MCP endpoint secret 或完整未脱敏调试 payload。
- assistant 最终答案仍独立 Markdown/LaTeX 渲染；思考过程以“思考过程”面板按 turn 展示。

实现摘要：

- `formatConversationThinkingForPeople()` 将 WS 事件转成普通用户可读步骤：`思考中`、`正在查找知识库内容`、`正在调用辅助能力`、`已找到可参考内容`。
- `TranscriptTurnContent` 新增 `thinkingSteps`，在 assistant 气泡中渲染可展开的“思考过程”步骤列表。
- 普通测试页在收到相关 WS 事件时追加/合并 thinking steps；`thinking` chunk 合并为同一段并保留 chunk 间空格；`progress` 中的 `Query:` / `Retrieved ... characters` 等技术文案转为普通中文步骤；工具调用和 sources 只展示安全标题，不展示参数正文。
- OpenSpec `enterprise-conversation-test-page` delta 新增思考过程场景与安全约束；tasks 增加并勾选 3.7。

TDD/回归验证：

```bash
cd web && python3 - <<'PY'
from pathlib import Path
import shutil
p = Path('dist/node-tests')
if p.exists():
    shutil.rmtree(p)
PY
node_modules/.bin/tsc -p tsconfig.node-tests.json && \
  node -r ./scripts/register-node-test-aliases.cjs --test \
    dist/node-tests/tests/enterprise-conversation-test.test.js
# RED：新增测试先因缺少 formatConversationThinkingForPeople 导出失败。
# GREEN：实现后 12 tests passed。

npm --prefix web run test:unit -- enterprise-conversation-rich-content.spec.tsx
# RED：新增组件测试先找不到“思考过程”。
# GREEN：实现后 1 file passed, 3 tests passed。

npm --prefix web run typecheck
# 结果：exit 0

cd web && npx eslint \
  app/enterprise/eduplus2/conversation-test/page.tsx \
  app/enterprise/eduplus2/conversation-test/TranscriptTurnContent.tsx \
  lib/enterprise-conversation-test.ts \
  tests/enterprise-conversation-test.test.ts \
  tests/enterprise-conversation-rich-content.spec.tsx
# 结果：exit 0；仅既有 i18n/no-literal-ui-text warnings，无 error

npm --prefix web run build
# 结果：exit 0，/enterprise/eduplus2/conversation-test 构建成功

openspec validate add-ws-required-context-controls --strict
# 结果：Change 'add-ws-required-context-controls' is valid

openspec validate --all --strict
# 结果：15 passed, 0 failed
```

浏览器 smoke（同日补充）：

- 重启最终 standalone 前端后，重新登录普通测试页并选择知识库 `test`。
- 发送：`请用知识库回答：当前知识库里主要是什么内容？`
- 页面在 assistant turn 中展示“思考过程”面板；可见步骤包括“正在连接对话服务”“正在理解你的问题”“正在查找知识库内容”“已找到可参考内容”“思考中”。
- progress 阶段未再把 `Query:` 或 `Retrieved ... characters` 原样展示给普通用户；浏览器控制台无错误。
- 最终答案与“思考过程”面板共存，Markdown 标题、表格和列表正常渲染。

## 2026-09-20 语音输入不可用与 raw `<think>` 混入正文修复验证

用户现象：

- 普通测试页点击“语音输入”后只能短暂进入监听状态，随后提示识别失败，实际无法把语音写入 prompt。
- 某些 assistant 回复把 provider 输出的 `<think>...</think>` 原样夹在最终答案正文中，导致“思考过程”同时出现在正文里。

定位证据：

- 浏览器 smoke 复现中，点击语音按钮后 UI 变成“停止语音”，数秒后回到“语音输入”，只显示泛化失败文案；控制台无错误，说明旧实现只依赖 Web Speech API 且没有服务端转写兜底或具体错误说明。
- 仓库已有 `deeptutor.api.routers.voice` 的 `/api/voice/stt` 与 `useVoiceRecorder` 模式，但企业最小 API app 未挂载 voice router，普通测试页也未使用 MediaRecorder + STT。
- 浏览器 AX/历史 transcript 中可见 assistant 正文包含 literal `<think>`、大段思考文本和 `</think>`，说明 raw think block 已进入 `content` 渲染路径；原思考面板仅处理 `thinking/progress/tool_call/sources` 事件，没有剥离 content 中的 think block。

修复：

- 企业 API app 挂载核心 `voice.router` 到 `/api/voice`，并通过既有企业 `AuthenticationMiddleware` 要求 Bearer/cookie 登录态；普通测试页用当前 demo Bearer token 调用 `/api/voice/stt`。
- 普通测试页语音输入优先走 MediaRecorder/getUserMedia 录音 → `/api/voice/stt` 转写 → 追加到 prompt；录音/STT 不可用时再降级到 Web Speech API；权限拒绝、无麦克风、无声音、浏览器语音服务网络失败和 STT 未配置均展示可理解提示，不阻断文字输入或音频文件上传。
- assistant 渲染层新增 `splitAssistantThinkingFromAnswer()`：从 assistant `content` 中剥离完整或未闭合的 `<think>` / `<thinking>` block；最终答案正文只渲染剩余 Markdown/LaTeX，脱标签思考文本合并到“思考过程”面板，避免标签和思考文本夹在正文中。
- OpenSpec `enterprise-conversation-test-page` 与 design 已同步记录服务端 STT fallback 和 raw think block 分离要求。

TDD/回归验证：

```bash
cd web && python3 - <<'PY'
import shutil
shutil.rmtree('dist/node-tests', ignore_errors=True)
PY
node_modules/.bin/tsc -p tsconfig.node-tests.json && \
  node -r ./scripts/register-node-test-aliases.cjs --test \
    dist/node-tests/tests/enterprise-conversation-test.test.js
# RED：新增 helper 测试先因缺少 conversationSpeechFailureNotice / isServerSpeechRecordingAvailable / splitAssistantThinkingFromAnswer 导出失败；STT 未配置错误映射测试先返回泛化失败文案。
# GREEN：实现后 15 tests passed。

npm --prefix web run test:unit -- enterprise-conversation-rich-content.spec.tsx
# RED：新增组件测试先在正文中看到 `<think>` 且找不到“思考过程”。
# GREEN：实现后 1 file passed, 4 tests passed。

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/pytest -q \
  extensions/enterprise/tests/test_application.py::test_enterprise_voice_stt_is_available_to_authenticated_test_page \
  -o asyncio_mode=auto
# RED：授权请求 `/api/voice/stt` 先返回 404 Not Found。
# GREEN：挂载 voice router 后 1 passed。
```

综合验证：

```bash
npm --prefix web run typecheck
# exit 0

cd web && npx eslint \
  app/enterprise/eduplus2/conversation-test/page.tsx \
  app/enterprise/eduplus2/conversation-test/TranscriptTurnContent.tsx \
  lib/enterprise-conversation-test.ts \
  tests/enterprise-conversation-test.test.ts \
  tests/enterprise-conversation-rich-content.spec.tsx
# exit 0；仅既有 i18n/no-literal-ui-text warnings，无 error

PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/pytest -q \
  tests/api/test_voice_routes.py \
  extensions/enterprise/tests/test_application.py::test_enterprise_voice_stt_is_available_to_authenticated_test_page \
  -o asyncio_mode=auto
# 9 passed, 1 warning

./.venv/bin/ruff check \
  extensions/enterprise/src/deeptutor_enterprise/api/application.py \
  extensions/enterprise/tests/test_application.py
# All checks passed!

npm --prefix web run build
# exit 0；/enterprise/eduplus2/conversation-test 构建成功

openspec validate add-ws-required-context-controls --strict
# Change 'add-ws-required-context-controls' is valid

openspec validate --all --strict
# 15 passed, 0 failed
```

补充验证（同日最终修复）：

- 真实 smoke 中，浏览器端录制 `audio/webm` 需要本机 `ffmpeg` 才能被 DashScope STT 归一化；普通测试页改为优先用 Web Audio 采集 PCM 并在前端编码成 canonical `audio/wav`（16 kHz、mono、16-bit PCM），避免本机缺 `ffmpeg` 时语音输入不可用。
- DashScope STT 运行时默认模型从旧的 `paraformer-v2` 修正为实时识别接口使用的 `paraformer-realtime-v2`；本地调试 catalog 已同步切到 `local-paraformer-realtime-v2`，不记录 API Key。
- 通过 EduPlus2 demo 登录后的真实 Bearer token 调用 `/api/voice/stt`，上传 macOS `say` 生成并经 `afconvert` 转成 canonical WAV 的中文测试音频，返回 HTTP 200 且响应包含 `text` 字段；页面内点击“语音输入”→“停止语音”后，后台 `/api/voice/stt` 同样返回 HTTP 200。无 `ffmpeg is required`、`Model not found` 或 401 认证错误。

最终命令：

```bash
PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/pytest -q \
  tests/services/test_voice.py \
  tests/api/test_voice_routes.py \
  extensions/enterprise/tests/test_application.py::test_enterprise_voice_stt_is_available_to_authenticated_test_page \
  tests/api/test_settings_router.py::test_media_and_voice_provider_choices_include_dashscope \
  -o asyncio_mode=auto
# 33 passed, 1 warning

cd web && python3 - <<'PY'
import shutil
shutil.rmtree('dist/node-tests', ignore_errors=True)
PY
node_modules/.bin/tsc -p tsconfig.node-tests.json && \
  node -r ./scripts/register-node-test-aliases.cjs --test \
    dist/node-tests/tests/enterprise-conversation-test.test.js
# 16 tests passed

npm --prefix web run test:unit -- enterprise-conversation-rich-content.spec.tsx
# 1 file passed, 4 tests passed

npm --prefix web run typecheck
# exit 0

cd web && npx eslint \
  app/enterprise/eduplus2/conversation-test/page.tsx \
  app/enterprise/eduplus2/conversation-test/TranscriptTurnContent.tsx \
  lib/enterprise-conversation-test.ts \
  tests/enterprise-conversation-test.test.ts \
  tests/enterprise-conversation-rich-content.spec.tsx
# exit 0；仅既有 i18n/no-literal-ui-text warnings，无 error

./.venv/bin/ruff check \
  deeptutor/services/config/provider_runtime.py \
  extensions/enterprise/src/deeptutor_enterprise/api/application.py \
  extensions/enterprise/tests/test_application.py \
  tests/services/test_voice.py \
  tests/api/test_settings_router.py
# All checks passed!

npm --prefix web run build
# exit 0；/enterprise/eduplus2/conversation-test 构建成功

openspec validate add-ws-required-context-controls --strict && \
  openspec validate --all --strict
# Change valid；15 passed, 0 failed
```

## 2026-09-20 正文流式输出被思考面板挤出可视区域修复验证

用户现象：

- 回复开始后“思考过程”持续更新，但正文看起来不再流式输出。

定位证据：

- 直接抓取同一 `/api/v1/ws` 链路的 WebSocket frame，后端仍按 chunk 推送正文：本次 smoke 中先收到多条 `thinking`，随后从约 5.5s 起连续收到 40 个 `content` chunk，到约 9.0s 累计 200 字，最后才收到 `done`。因此问题不在后端模型流或 WS 转发。
- 前端 `TranscriptTurnContent` 把“思考过程”面板放在正文前面并永久 `open`；thinking 事件较多时面板持续变高，正文虽在下方更新，但被挤出普通用户当前可视区域，表现为“正文不流式”。

修复：

- assistant 已有可见答案时，“思考过程”面板默认收起；纯 thinking 阶段仍默认展开。
- 思考过程列表增加最大高度与内部滚动，避免长思考内容持续撑高当前 assistant turn。
- 保留“思考过程”入口，用户仍可点击展开查看；正文继续按 `content` chunk 渲染 Markdown/LaTeX。

TDD/验证：

```bash
npm --prefix web run test:unit -- enterprise-conversation-rich-content.spec.tsx
# RED：新增用例先失败，details 仍带 open 属性。
# GREEN：修复后 1 file passed, 5 tests passed。

cd web && python3 - <<'PY'
import shutil
shutil.rmtree('dist/node-tests', ignore_errors=True)
PY
node_modules/.bin/tsc -p tsconfig.node-tests.json && \
  node -r ./scripts/register-node-test-aliases.cjs --test \
    dist/node-tests/tests/enterprise-conversation-test.test.js
# 16 tests passed

npm --prefix web run typecheck
# exit 0

cd web && npx eslint \
  app/enterprise/eduplus2/conversation-test/TranscriptTurnContent.tsx \
  tests/enterprise-conversation-rich-content.spec.tsx
# exit 0；仅既有 i18n/no-literal-ui-text warnings，无 error

npm --prefix web run build
# exit 0；/enterprise/eduplus2/conversation-test 构建成功
```

## 2026-09-21 EduPlus2 普通测试页登录入口修复验证

用户现象：

- 未登录访问 `https://deeptutor.lfun.pub/enterprise/eduplus2/conversation-test` 时，Next.js cookie auth gate 在页面渲染前返回 `307 /login?next=/enterprise/eduplus2/conversation-test`，普通用户看不到 EduPlus2 登录入口。
- 根因是普通对话测试页使用 EduPlus2 demo/OIDC 交换得到的内存态 Bearer token，而不是先拥有 DeepTutor `dt_token` cookie；该页面需要作为自认证 bootstrap 页面放行，真实 API/WS 仍由后端 Bearer 校验。

修复：

- 在前端 proxy policy 中只放行 `/enterprise/eduplus2/conversation-test` 和 `/enterprise/eduplus2/fronting-demo` 两个 EduPlus2 demo-auth bootstrap 页面，避免它们被重定向到本地 `/login`。
- 不放行其他 enterprise/admin 页面；后端 `/api/v1/*` 与 `/api/*` 仍由 backend rewrite 和后端认证控制。

TDD/验证：

```bash
cd web && node_modules/.bin/tsc -p tsconfig.node-tests.json && \
  node -r ./scripts/register-node-test-aliases.cjs --test \
    dist/node-tests/tests/proxy-policy.test.js
# RED：新增用例先失败，conversation-test/fronting-demo 仍不是 auth exempt。
# GREEN：修复后 13 tests passed。
```

补充验证（同日）：

```bash
cd web && python3 - <<'PY'
import shutil
shutil.rmtree('dist/node-tests', ignore_errors=True)
PY
node_modules/.bin/tsc -p tsconfig.node-tests.json && \
  node -r ./scripts/register-node-test-aliases.cjs --test \
    dist/node-tests/tests/proxy-policy.test.js \
    dist/node-tests/tests/enterprise-conversation-test.test.js
# 29 tests passed

npm --prefix web run typecheck
# exit 0

cd web && npx eslint \
  lib/proxy-policy.ts \
  tests/proxy-policy.test.ts \
  app/enterprise/eduplus2/conversation-test/page.tsx \
  lib/enterprise-conversation-test.ts \
  tests/enterprise-conversation-test.test.ts
# exit 0；仅普通测试页既有 i18n/no-literal-ui-text warnings，无 error

npm --prefix web run build
# exit 0；/enterprise/eduplus2/conversation-test 与 /enterprise/eduplus2/fronting-demo 构建成功

openspec validate add-ws-required-context-controls --strict && \
  openspec validate --all --strict
# Change valid；15 passed, 0 failed
```

本地 HTTPS 路由 smoke：

```bash
curl -sk -D /tmp/conversation-test.headers -o /tmp/conversation-test.html \
  -w '%{http_code}\n' \
  'https://deeptutor.lfun.pub/enterprise/eduplus2/conversation-test'
# 200；不再是 307 /login

curl -sk -D /tmp/eduplus2-start.headers -o /tmp/eduplus2-start.body \
  -w '%{http_code}\n' \
  'https://deeptutor.lfun.pub/api/v1/auth/eduplus2/demo/start?return_to=https%3A%2F%2Fdeeptutor.lfun.pub%2Fenterprise%2Feduplus2%2Fconversation-test'
# 303；Location 指向 eduplus-auth-test.f123.pub 的 OIDC authorization endpoint

$PWCLI open 'https://deeptutor.lfun.pub/enterprise/eduplus2/conversation-test'
$PWCLI snapshot
# 页面显示 “EDUPLUS2 CONVERSATION TEST” 与 “使用 EduPlus2 账号登录”；
# 链接为 /api/v1/auth/eduplus2/demo/start?return_to=https%3A%2F%2Fdeeptutor.lfun.pub%2Fenterprise%2Feduplus2%2Fconversation-test
```

## 2026-09-22 普通对话页 required context / 多模态 / 长对话复验

本轮按用户提供的本地前提重新验证普通对话测试页与 `/api/v1/ws` 真实链路。所有证据仅记录脱敏摘要，不记录 EduPlus2 账号密码、JWT、`dt_token`、ObjectStore signed URL、S3 key、模型 API key 或用户隐私正文。

| 命令 / 验证 | 退出码 | 脱敏结果摘要 | 限制 / 后续 |
| --- | --- | --- | --- |
| `PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q tests/agents/chat/test_required_context.py tests/services/session/test_turn_runtime_subscribe.py::test_close_drains_running_turn_before_cancelling tests/services/session/test_turn_runtime_subscribe.py::test_close_cancels_turn_after_drain_timeout` | 0 | 14 passed；覆盖 required/best-effort/auto context、KB missing/not-ready/unauthorized、missing skill、model usage summary、turn close drain/cancel。 | MCP 未授权 provider fixture 本轮暂缓，按用户指示不作为当前浏览器 smoke 阻断。 |
| `PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py extensions/enterprise/tests/test_executor.py` | 0 | 22 passed、1 skipped；覆盖 enterprise options、upload intent/complete、missing/expired upload、resource refs、image resource materialization、非图片 fail-closed、WS auth refresh、legacy payload/cross-owner refs、single executor。 | skip 为未显式开启的本地 MinIO 集成项；本轮另行开启并通过。 |
| `DEEPTUTOR_RUN_LOCAL_MINIO_TESTS=1 PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q extensions/enterprise/tests/test_application.py::test_local_minio_http_upload_intent_and_ws_resource_policy` | 0 | 1 passed；企业 ASGI 真实本地 MinIO upload intent → pre-signed PUT → complete → WS resource policy 链路通过。 | 本地 MinIO，不等同目标 K8s。 |
| `cd web && python3 ... shutil.rmtree('dist/node-tests') && node_modules/.bin/tsc -p tsconfig.node-tests.json && node -r ./scripts/register-node-test-aliases.cjs --test dist/node-tests/tests/enterprise-conversation-test.test.js` | 0 | 19 tests passed；覆盖普通页 payload、upload intent body、上传未完成阻止发送、语音降级/超时、think block 剥离、WAV 录制、token refresh、友好 thinking/首 token 提示、能力面板文案。 | Node targeted tests。 |
| `npm --prefix web run test:unit -- enterprise-conversation-rich-content.spec.tsx` | 0 | 1 file passed、5 tests passed；覆盖 Markdown/LaTeX/code、thinking 面板与正文分离。 | 前端单元测试。 |
| `cd web && npm run typecheck` / `cd web && npm run build` | 0 / 0 | TypeScript 检查通过；Next production build 通过，包含 `/enterprise/eduplus2/conversation-test`。 | 构建命令不替代目标部署。 |
| `ruff check` scoped files | 0 | `deeptutor/services/session/required_context.py`、ObjectStore completion、turn environment/configured、enterprise runtime/application/tests 等相关文件 All checks passed。 | Scoped ruff。 |
| Playwright real browser smoke（EduPlus2 SSO → conversation-test） | 0 | 页面登录状态 `已就绪`；KB 显示 `test`，Skills 显示 `skill-creator` 等；上传 32x32 红色 PNG 后显示“已加入”；发送 required `knowledge_bases=[test]` + `resource_ids` 的 WS turn，assistant 返回“红色”；随后追问“刚才你判断的颜色是什么”，assistant 再次返回“红色”，证明图片资源进入模型且会话上下文连续。能力面板显示 `qwen3.8-max：已用于回答`、`user:kb:test：已用于回答`、`上传文件 1 个：已发送给模型`。 | Browser request log 中的 signed URL 未写入 evidence；自动化环境没有真实语音输入内容。 |
| Playwright voice button smoke + `PYTHONPATH=.:extensions/enterprise/src ./.venv/bin/python -m pytest -q tests/services/test_voice.py tests/api/test_voice_routes.py extensions/enterprise/tests/test_application.py::test_enterprise_voice_stt_is_available_to_authenticated_test_page tests/api/test_settings_router.py::test_media_and_voice_provider_choices_include_dashscope -o asyncio_mode=auto` | 1 / 0 | 浏览器静音录制路径调用 `/api/voice/stt` 后服务端返回 no-valid-audio 类 502，页面展示“语音输入没有成功，可以继续手动输入，或上传音频文件一起发送”，未阻断文本/文件/对话；语音服务与路由回归 33 passed。 | 自动化环境未提供可识别人声；真实有声 STT 需人工或音频注入复验。 |

仍未勾选 `4.1`：缺失/未授权 KB、未 ready KB、缺失 skill、provider 不支持媒体、missing MCP 已覆盖；但 MCP 未授权 provider、私有 KB 的独立 fixture 本轮按“mcp 可以暂缓测试”保留为后续补齐项。

OpenSpec 与 patch 格式最终校验：

```bash
openspec validate add-ws-required-context-controls --strict
# Change 'add-ws-required-context-controls' is valid

openspec validate --all --strict
# 15 passed, 0 failed

git diff --check -- <本轮相关源码/测试/OpenSpec路径>
# exit 0
```

语音输入补充：重新发起 EduPlus2 SSO 得到新 demo session 后，用 macOS `say` + `afconvert` 生成中文 WAV，通过同一 `/api/voice/stt` Bearer 路径调用，HTTP 200，返回非空转写文本（`text_len=37`）。该命令不输出 JWT/`dt_token` 或音频正文。
