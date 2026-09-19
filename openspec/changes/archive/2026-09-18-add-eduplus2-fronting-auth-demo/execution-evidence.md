# add-eduplus2-fronting-auth-demo 执行证据

> 本文件禁止写入 EduPlus2 user JWT、DeepTutor `dt_token`、authorization code、code verifier、client secret、M2M token 或用户隐私原文；以下证据均只记录状态码、路由、脱敏摘要和外部阻塞。

## 实现摘要

- 后端新增 demo-only BFF 路由：
  - `GET /api/v1/auth/eduplus2/demo/start`
  - `GET /api/v1/auth/eduplus2/demo/callback`
  - `GET /api/v1/auth/eduplus2/demo/result`
  - `POST /api/v1/auth/eduplus2/demo/refresh`
- Demo 后端使用内存 state/session、PKCE verifier、短 TTL result、refresh proof；callback 与 refresh 均复用现有 `enterprise.eduplus2.exchange_user_jwt()`，不复制授权规则。
- WebSocket 认证支持 `Sec-WebSocket-Protocol: deeptutor-token, <jwt>`，demo 不把 `dt_token` 放入 URL query/hash。
- 前端新增 `/enterprise/eduplus2/fronting-demo`，展示 redirect、code exchange、DeepTutor exchange、API probe、WS chat、token refresh 六段链路；`dt_token` 只放 React 运行时内存，不写 `localStorage`/`sessionStorage`，页面不显示 token 原文。
- 前端根据 `expires_at` 自动调用 demo refresh，成功后向已连接 WebSocket 发送 `auth_refresh`，若连接关闭则可用新 token 重连。
- 本地 HTTPS 路由已配置：
  - `https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo` → 前端 `127.0.0.1:3782`
  - `wss://deeptutor.lfun.pub/ws/api/v1/ws` → 后端 `127.0.0.1:8001`（local-ssl `/ws` 前缀转发到后端 `/api/v1/ws`）

## 本轮验证

2026-09-18 运行：

```text
.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py -q
→ 6 passed

cd web && npm run test:unit -- eduplus2-fronting-demo.spec.tsx
→ Test Files 1 passed; Tests 6 passed

.venv/bin/python -m ruff check extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/src/deeptutor_enterprise/eduplus2/fronting_demo.py extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py
→ All checks passed

openspec validate add-eduplus2-fronting-auth-demo --strict
→ Change 'add-eduplus2-fronting-auth-demo' is valid

cd web && npm run typecheck
→ exit 0

cd web && npm exec -- eslint app/enterprise/eduplus2/fronting-demo/page.tsx app/dev/eduplus/callback/route.ts lib/eduplus2-fronting-demo.ts tests/eduplus2-fronting-demo.spec.tsx next.config.js
→ exit 0；存在 demo 页面 literal UI text 的 i18n warning

.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py::test_http_auth_csrf_revoke_and_closed_routes extensions/enterprise/tests/test_eduplus2_federated_access.py::test_exchange_api_rejects_body_identity_and_returns_sanitized_errors -q
→ 2 passed
```

本地 URL/服务验证：

```text
curl https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo
→ HTTP 200

curl https://deeptutor.lfun.pub/api/v1/auth/eduplus2/demo/start?return_to=...
→ HTTP 303；Location 指向 EduPlus2 authorization endpoint，包含 response_type=code、client_id、redirect_uri、scope、state、code_challenge、code_challenge_method=S256
```

Playwright 验证：

- 打开 `https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo` 成功，页面显示“EduPlus2 统一认证前置应用 Demo”、六段链路卡片、API probe、真实 `/api/v1/ws` 对话面板和错误矩阵。
- 点击“使用 EduPlus2 统一认证测试”后浏览器真实跳转到 EduPlus2 authorization endpoint。
- 2026-09-18 用户将 `https://deeptutor.lfun.pub/*` 加入 EduPlus2 测试 client 白名单后重新验证：
  - `GET https://deeptutor.lfun.pub/api/v1/auth/eduplus2/demo/start?...` 跟随跳转后返回 `HTTP 200` EduPlus 登录页；
  - 页面包含 `登录 EduPlus`、`username`、`password`、`手机号` 等登录表单标记；
  - 不再出现 `无效参数：redirect_uri`。

WebSocket 真实对话冒烟：

- 使用本地受控管理员登录生成短期 DeepTutor token，仅在脚本进程内使用；不输出 token。
- 通过 `wss://deeptutor.lfun.pub/ws/api/v1/ws`、`Sec-WebSocket-Protocol: deeptutor-token, <token>` 建立连接，发送 `start_turn`，收到 `session/stage_start/progress/thinking/.../done` 事件，`content_len=3`。
- 该冒烟证明 demo callback 拿到 `dt_token` 后所需的 DeepTutor API probe 与 `/api/v1/ws` 对话通道可用。

2026-09-18 追加修复验证：

- 用户完成 EduPlus2 登录后页面返回 `deeptutor_unauthorized`，且页面无法滚动到下半部分。
- 根因 1：demo 优先选择 `id_token` 交给 DeepTutor exchange；标准 OIDC `id_token` 可能缺少 exchange 必需的 `tid/eui/azp` 等业务 claims。已改为在 `id_token` / `access_token` 中优先选择包含完整 exchange claims 的 JWT，并在失败摘要中展示脱敏 `selected_token` / `detail` 诊断。
- 根因 2：全局 `html, body` 为 `overflow: hidden`，demo 根节点也使用 `overflow-hidden`，导致页面没有内部滚动容器。已改为 `h-full overflow-y-auto` 的内部滚动根。
- 新增/更新测试并通过：
  - `.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py -q` → `7 passed`
  - `cd web && npm run test:unit -- eduplus2-fronting-demo.spec.tsx` → `Test Files 1 passed; Tests 7 passed`
  - `.venv/bin/python -m ruff check extensions/enterprise/src/deeptutor_enterprise/eduplus2/fronting_demo.py extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py` → `All checks passed`
  - `cd web && npm run typecheck` → exit 0
  - `cd web && npm exec -- eslint app/enterprise/eduplus2/fronting-demo/page.tsx lib/eduplus2-fronting-demo.ts tests/eduplus2-fronting-demo.spec.tsx` → exit 0；保留 demo 页面 literal UI text 的 i18n warning
  - `openspec validate add-eduplus2-fronting-auth-demo --strict` → valid
  - `cd web && npm run build` → exit 0
- Playwright 滚动验证：
  - `data-testid=eduplus2-fronting-demo-scroll-root` 存在；
  - `overflowY=auto`；
  - `clientHeight=720`，`scrollHeight=2166`；
  - 设置 `scrollTop=1000` 后生效，`canScroll=true`。
- 重启新版服务后，同域名 API/WS 冒烟再次通过：`login_status=200`、`api_status=200 authenticated=True`、`ws_done=True`。

2026-09-18 追加诊断增强：

- 用户再次登录后页面显示 `deeptutor_unauthorized（exchange_jwt_verification_failed）`，说明已进入 DeepTutor exchange，但当前 OIDC/JWKS 验签失败。
- 本地验证 EduPlus2 discovery/JWKS：
  - discovery HTTP 200；
  - issuer 为 `https://eduplus-auth-test.f123.pub/realms/eduplus`；
  - JWKS HTTP 200；
  - 当前 JWKS 暴露 2 个 RSA key。
- 为继续定位而不暴露 token，新增安全诊断：
  - verifier 对 token 自身 `iss` 与 discovery issuer 不一致的情况返回 `EduPlus2 token issuer mismatch`，demo detail 映射为 `exchange_jwt_token_issuer_mismatch`；
  - demo failure summary 输出 `selected_token`、`selected_header_alg`、`selected_header_kid_hash`、`selected_claim_issuer`、`selected_claim_audience`、`selected_claim_azp`；
  - 原始 JWT、authorization code、refresh token、用户明文 id 和 tenant 明文 id 不写入页面。
- 新增/更新测试并通过：
  - `.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py extensions/enterprise/tests/test_eduplus2_federated_access.py::test_oidc_jwks_verifier_accepts_rs256_and_rejects_missing_azp -q` → `9 passed`
  - `.venv/bin/python -m ruff check ...` → `All checks passed`
  - `cd web && npm run test:unit -- eduplus2-fronting-demo.spec.tsx && npm run typecheck` → passed
  - `cd web && npm exec -- eslint ...` → exit 0；保留 demo 页面 literal UI text 的 i18n warning
  - `openspec validate add-eduplus2-fronting-auth-demo --strict` → valid
  - `cd web && npm run build` → exit 0
- 重启新版服务后验证：
  - demo 页面 HTTP 200；
  - EduPlus2 登录页 HTTP 200；
  - 同域名 DeepTutor API/WS 冒烟通过：`login_status=200`、`api_status=200 authenticated=True`、`ws_done=True`。

2026-09-18 真实登录后追加根因与修复：

- 用户完成 EduPlus2 登录后，demo result 安全摘要显示：
  - `reason=deeptutor_unauthorized`；
  - `detail=exchange_jwt_verification_failed`；
  - `selected_token=id_token`；
  - token header 为 `RS256`，`kid` 与当前 JWKS 的签名 key 匹配（仅记录 SHA-256 摘要）；
  - token `iss/aud/azp/iat/exp` 均符合配置与有效期窗口。
- 根因：EduPlus2 OIDC `id_token` 可能携带标准 `at_hash` claim；`python-jose` 的 `jwt.decode()` 默认启用 `verify_at_hash`，但 DeepTutor exchange verifier 只接收单个 EduPlus2 user JWT，不持有对应 access token，因而在签名/issuer/claims 均正确时仍被 OIDC at_hash 绑定校验拒绝。
- 修复：DeepTutor 的 EduPlus2 user-JWT verifier 继续校验签名、`iss`、`exp`、`iat`、`nbf` 和必需业务 claims，但在 JWT exchange 语义下禁用 `verify_at_hash`；这与当前契约“只接受 `Authorization: Bearer <eduplus2_user_jwt>` 作为身份断言”一致，不要求前置应用额外提交 raw access token。
- TDD 验证：
  - 先新增 `id_token` 携带 `at_hash` 的 RS256/JWKS verifier 用例，确认修复前失败：`PermissionError: EduPlus2 JWT verification failed`；
  - 修复后 `.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py::test_oidc_jwks_verifier_accepts_rs256_and_rejects_missing_azp -q` → `1 passed`；
  - `.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py extensions/enterprise/tests/test_eduplus2_federated_access.py::test_oidc_jwks_verifier_accepts_rs256_and_rejects_missing_azp -q` → `9 passed`；
  - `.venv/bin/python -m ruff check extensions/enterprise/src/deeptutor_enterprise/eduplus2/client.py extensions/enterprise/tests/test_eduplus2_federated_access.py extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py` → `All checks passed`。

2026-09-18 `service_unavailable` 追加定位：

- 用户重新登录后 demo result 安全摘要显示 `reason=service_unavailable`、`selected_token=id_token`，且 header/issuer/audience/azp/exp 均符合预期，说明 code exchange 与 JWT 选择已通过，失败发生在 DeepTutor exchange 后续外部/持久化边界。
- 针对该 `request_id` 查询 `eduplus2.audit_events` 返回 0 条；随后单独验证当前 M2M token + resolve：
  - M2M token received（仅记录 hash，不输出 token）；
  - resolve ok；
  - client active、tenant/app/subscription active；
  - resolved external app id 为 `36`，tenant 仅记录 SHA-256 摘要。
- 为避免页面只显示总类 `service_unavailable`，新增安全 RuntimeError detail 映射：token/resolve/profile/permission endpoint rejected/unavailable/invalid response 等均归类为固定诊断码，不回显 secret、token、响应正文或用户明文。
- TDD 验证：
  - 先新增 `_safe_error_detail` 用例，确认修复前 import 失败；
  - 修复后 `.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py::test_runtime_error_detail_is_specific_and_redacted -q` → `1 passed`；
  - `.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py extensions/enterprise/tests/test_eduplus2_federated_access.py::test_oidc_jwks_verifier_accepts_rs256_and_rejects_missing_azp -q` → `10 passed`；
  - `.venv/bin/python -m ruff check ...` → `All checks passed`。
- 重启后端后验证：demo 页面 HTTP 200，start 跳转 HTTP 303。下一次用户登录会在页面 `detail` 显示具体边界，例如 `eduplus2_profile_endpoint_rejected` 或 `eduplus2_permission_endpoint_unavailable`。

2026-09-18 `service_unavailable` 根因确认与本地 demo 配置修正：

- 对当前 `.secrets/deeptutor-local-eduplus2.env` 中的可选增强 endpoint 做独立脱敏探测：
  - `DT_EDUPLUS2_PROFILE_URL` 路径为 `/api/v1/me/profile`，demo 的 M2M POST 调用返回 `EduPlus2 profile endpoint rejected request: 405`；
  - `DT_EDUPLUS2_PERMISSION_URL` 路径为 `/v1/permissions/check`，demo 的 M2M POST 调用返回 `EduPlus2 permission endpoint rejected request: 405`。
- 结论：`service_unavailable` 不是 JWT 验签失败，也不是 client resolve 失败；它来自已配置的可选 profile/permission 增强与当前 EduPlus2 test endpoint 协议不匹配。DeepTutor 在可选增强被配置时按 fail-closed 处理，因此 exchange 终止。
- 本地 demo 运行脚本 `.secrets/run-local-enterprise-demo-backend.sh` 已在 source EduPlus2 env 后显式设置 `DT_EDUPLUS2_PROFILE_URL=off` 与 `DT_EDUPLUS2_PERMISSION_URL=off`，仅对 local visual demo 禁用这两个可选增强，保留 JWT 验签、JWKS、M2M token、resolve、allowlist/registration 主链路。
- 重启后端后验证：demo 页面 HTTP 200，start 跳转 HTTP 303。

2026-09-18 `service_unavailable` 二次定位与修正：

- 现象：用户再次登录后页面仍显示 `service_unavailable`。脱敏 synthetic exchange 复现到真实 M2M resolve 后返回 `RuntimeError: EduPlus2 profile endpoint rejected request: 404`。
- 根因：上一次脚本中 `unset DT_EDUPLUS2_PROFILE_URL/DT_EDUPLUS2_PERMISSION_URL` 不足以禁用可选增强；`DT_EDUPLUS2_BASE_URL` 仍会在 bootstrap 阶段自动派生 `/api/v1/open/profile` 与 `/api/v1/open/permissions/check`，而当前 EduPlus2 test 环境不支持该 M2M POST 协议。
- 修正：bootstrap 增加可选 URL 显式禁用值（`off`/`disabled`/`none`/`0`/`false`/`no`），本地 demo 脚本改为设置 `DT_EDUPLUS2_PROFILE_URL=off`、`DT_EDUPLUS2_PERMISSION_URL=off`，保留 `DT_EDUPLUS2_BASE_URL` 派生/兼容其它 URL 的能力。
- TDD 验证：
  - 先新增 `test_enterprise_env_can_disable_optional_eduplus2_profile_permission_clients`，修复前失败于 `eduplus2_profile_client is not None`；
  - 修复后 `.venv/bin/python -m pytest extensions/enterprise/tests/test_eduplus2_federated_access.py::test_enterprise_env_can_disable_optional_eduplus2_profile_permission_clients -q` → `1 passed`。
- 本地真实边界验证：
  - 清理旧租户残留注册后，migration DSN 查询确认当前 client 仅有一个 active registration，tenant hash 为当前本地 deployment hash；
  - 脱敏 synthetic exchange（真实 M2M token + resolve，fake verifier 仅替代用户 JWT 验签）返回 `exchange_ok=true`、`dt_token_present=true`、`expires_in=300`；
  - 诊断用户、binding、session 与诊断 audit 已清理，保留当前租户 active client registration 供真实登录复用；
  - 后端已重启，demo 页面 HTTP 200，start 跳转 HTTP 303。

2026-09-18 WebSocket 全部 failed 根因与修正：

- 用户完成登录后，nginx access log 显示浏览器多次访问 `GET /api/v1/ws`，均为 401，未出现 `101 Switching Protocols`。
- 运行中的 Next production bundle 未烘焙 `NEXT_PUBLIC_EDUPLUS2_DEMO_WS_URL`，因此 `buildDemoWebSocketUrl()` 使用 fallback `wss://deeptutor.lfun.pub/api/v1/ws`；但 local-ssl 配置为 `/ws` 前缀剥离转发，正确本地 URL 应为 `wss://deeptutor.lfun.pub/ws/api/v1/ws`，由 nginx 转给后端 `/api/v1/ws`。
- 对比验证：
  - 使用新签发 dt_token 连接 fallback `wss://deeptutor.lfun.pub/api/v1/ws` → HTTP 401；
  - 使用 `wss://deeptutor.lfun.pub/ws/api/v1/ws` → WebSocket 握手成功，发送 `ping` 收到 `pong`；
  - 直连 `ws://127.0.0.1:8001/api/v1/ws` → WebSocket 握手成功，发送 `ping` 收到 `pong`。
- 修正：本地 frontend 启动脚本在 `next start` 前带 `NEXT_PUBLIC_EDUPLUS2_DEMO_WS_URL=wss://deeptutor.lfun.pub/ws/api/v1/ws` 执行 `npm run build`，避免仅在 start 阶段 export 导致浏览器 bundle 不生效。
- 重启 frontend 后验证：
  - demo 页面 HTTP 200；
  - `.next` bundle 已包含 `/ws/api/v1/ws`；
  - fresh dt_token 连接 `wss://deeptutor.lfun.pub/ws/api/v1/ws`，发送 `ping` 收到 `pong`；
  - 真实 `start_turn` 对话收到 `session/stage_start/progress/thinking/content/result/session_meta/done`，`content_chars=17`，未出现 `protocol_error`、`error` 或 `auth_revoked`。

2026-09-18 WebSocket 浏览器握手 subprotocol 修复：

- 用户浏览器 console 仍显示 `WebSocket connection to 'wss://deeptutor.lfun.pub/ws/api/v1/ws' failed`。此时 nginx access log 对浏览器请求已显示 `101`，不是 401/403，说明 URL 与鉴权已进入握手成功路径，但浏览器仍判定握手失败。
- 根因：浏览器用 `Sec-WebSocket-Protocol: deeptutor-token, <dt_token>` 承载内存态 token；Starlette `ws.accept()` 未回选任何 subprotocol。Python `websockets` 客户端允许这种情况，但 Chrome 在客户端发送非空 subprotocol 列表而服务端没有返回 `Sec-WebSocket-Protocol` 时会判定握手失败。
- TDD 验证：
  - 新增 `test_ws_echoes_token_carrier_subprotocol_for_browser_handshake`，修复前失败：`accepted_subprotocol is None`；
  - 修复统一 WS adapter：当请求头包含固定标记 `deeptutor-token` 时，`ws.accept(subprotocol='deeptutor-token')`；只回选固定标记，不回显 JWT；
  - 修复后该测试通过。
- 回归验证：
  - `PYTHONPATH=".:extensions/enterprise/src:extensions/enterprise/tests" .venv/bin/python -m pytest tests/api/test_unified_ws_protocol.py extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py::test_websocket_token_can_be_read_from_subprotocol_without_url_query -q` → `10 passed`；
  - `.venv/bin/python -m ruff check deeptutor/api/routers/unified_ws.py tests/api/test_unified_ws_protocol.py extensions/enterprise/tests/test_eduplus2_fronting_auth_demo.py` → `All checks passed`；
  - 后端重启后，用 fresh 诊断 dt_token 连接 `wss://deeptutor.lfun.pub/ws/api/v1/ws`，服务端回选 `accepted_subprotocol='deeptutor-token'`，`ping` 收到 `pong`；
  - 同一连接发起真实 `start_turn`，收到 `session/stage_start/progress/thinking/content/result/session_meta/done`，`content_chars=20`，无 `protocol_error`/`error`/`auth_revoked`；
  - 诊断 user、binding、auth_session、chat session/messages/turn/turn_events 与诊断 audit 已清理。

2026-09-18 HTTPS 页面空白修复：

- 现象：`https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo` 返回 HTTP 200，但浏览器截图为空白；DOM 只剩 `I18nProvider` 的 `aria-busy=true` fallback。
- 对比验证：
  - 直连 `http://127.0.0.1:3782/enterprise/eduplus2/fronting-demo` 正常渲染；
  - HTTPS 域名下 Next dev HMR WebSocket `wss://deeptutor.lfun.pub/_next/webpack-hmr?...` 经 local-ssl 返回 404，页面卡在 fallback。
- 修复：`.secrets/run-local-enterprise-demo-frontend.sh` 从 `npm run dev` 改为 `npm run start -- --hostname 127.0.0.1 --port 3782`，并重新执行 `cd web && npm run build`。
- 重启 production frontend 后验证：
  - `curl https://deeptutor.lfun.pub/enterprise/eduplus2/fronting-demo` → HTTP 200；
  - Playwright 读取页面文本包含 `EduPlus2 统一认证前置应用 Demo`，`aria-busy` fallback 不存在；
  - start 跳转 → HTTP 303 到 EduPlus2 authorization endpoint；
  - `/api/settings/ui` 未登录 401 仅为 UI 语言偏好探测，不影响 demo。

## 外部阻塞与人工步骤

当前不再阻塞于 EduPlus2 redirect URI 白名单。后续完整 callback/exchange 验证需要一个可用 EduPlus2 测试账号在登录页完成登录；登录后页面会自动拉取 demo result、执行 `/api/auth/status` probe、启用 WS 对话，并按 `expires_at` 自动续签。

## 边界声明

完成该 demo 只代表 local/test 前置应用联调能力：统一认证跳转、callback 换票、现有 DeepTutor exchange、API probe、WS 对话、临期 refresh 的可视化验证。它不代表 TMS/OMS、生产 Handoff/OIDC callback、在线 client 治理、长期 session、实时撤权 SLA、M1/G1 或生产上线完成。
