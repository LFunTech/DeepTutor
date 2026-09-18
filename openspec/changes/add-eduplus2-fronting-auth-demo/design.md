# 设计说明

## Decision 1: Demo BFF 模式

前端不直接调用 EduPlus2 token endpoint，也不持有 client secret。点击按钮后由 DeepTutor 企业后端 demo route 生成 state/PKCE 并 302 到 EduPlus2 authorization endpoint。callback 由后端接收，后端用 code + verifier + client secret/ref 调 token endpoint，再调用现有 `EduPlus2AccessService.exchange_user_jwt()`。

这种方式最接近真实“前置应用 BFF”集成，也避免把 client secret 暴露给浏览器。

## Decision 2: Token 不进 URL，不进持久存储

callback 不把 EduPlus2 user JWT 或 DeepTutor `dt_token` 放在 query/hash 中。后端生成短期随机 `demo_session`，仅把 session id 放在 URL：

```text
/enterprise/eduplus2/fronting-demo?demo_session=<opaque-id>
```

页面用该 id 请求 `/api/v1/auth/eduplus2/demo/result`，拿到脱敏摘要和 `dt_token`。`dt_token` 只保存在 React state 中，用于立刻调用 `/api/auth/status`，并以非 URL 载体建立 `/api/v1/ws` 对话；页面不得写入 localStorage/sessionStorage，不显示 token 原文。

当 callback token response 返回 refresh token 时，后端只在短期进程内 demo session 中保存该 refresh token，不返回前端、不写数据库。前端根据 `expires_at` 倒计时，在临期或已超过超时时间时调用 `POST /api/v1/auth/eduplus2/demo/refresh`；后端使用 refresh grant 换取新的 EduPlus2 user JWT，再复用 `exchange_user_jwt()` 签发新 `dt_token`。若 WebSocket 已连接，页面随后发送 `auth_refresh` 命令；若连接已因过期关闭，则用新 token 重连并继续显示事件流。

## Decision 3: 内存短 TTL，无数据库状态

Demo 使用进程内 dict 保存：state、PKCE verifier、return URL、callback 结果、refresh token（如有）和过期时间。TTL 建议 5 分钟。进程重启或多 worker 下 state/refresh token 可能丢失；这是 demo 限制，不作为生产 Handoff 方案。

## Decision 4: 配置来源

沿用 `.secrets/deeptutor-local-eduplus2.env` 中已有 key：

- `DT_EDUPLUS2_AUTHORIZATION_ENDPOINT`
- `DT_EDUPLUS2_TOKEN_ENDPOINT`
- `DT_EDUPLUS2_CLIENT_ID`
- `DT_EDUPLUS2_CLIENT_SECRET_REF` 或 `DT_EDUPLUS2_CLIENT_SECRET`
- `DT_EDUPLUS2_OIDC_ISSUER` / `DT_EDUPLUS2_DISCOVERY_URL` / `DT_EDUPLUS2_JWKS_URI`

新增可选 key：

- `DT_EDUPLUS2_FRONTING_DEMO_ENABLED`：默认仅 local/test 可启用；值为 `0/false/off` 时禁用。
- `DT_EDUPLUS2_FRONTING_DEMO_REDIRECT_URI`：注册到 EduPlus2 的 callback URI；缺省根据请求 host 派生 `/api/v1/auth/eduplus2/demo/callback`。
- `DT_EDUPLUS2_FRONTING_DEMO_RETURN_URL`：callback 后回到的前端页面；缺省 `/enterprise/eduplus2/fronting-demo`。
- `DT_EDUPLUS2_FRONTING_DEMO_SCOPES`：默认 `openid profile offline_access`，用于尽量拿到 refresh token；如 EduPlus2 测试 client 不支持，可通过环境变量覆盖。
- `DT_EDUPLUS2_FRONTING_DEMO_REFRESH_LEEWAY_SECONDS`：默认 30，控制前端/后端建议的临期续签窗口。

## Decision 5: 前端页面定位

页面采用“联调控制台”风格，而不是审计列表：顶部是登录按钮，主体是六段 pipeline：

1. EduPlus2 Redirect
2. Authorization Code Token Exchange
3. DeepTutor Token Exchange
4. DeepTutor API Probe
5. DeepTutor WebSocket Chat
6. Token Refresh / WS Auth Refresh

每段显示 status、request id、耗时/时间、脱敏摘要、下一步建议。页面包含一个真实对话面板：输入 prompt 后建立 `/api/v1/ws`，发送 `start_turn`，展示 stream events 和 assistant content；续签倒计时触发后展示 refresh 请求、`auth_ack` 或重连结果。成功用绿色，失败用红色，pending 用琥珀色；整体风格偏工程仪表盘，强调 traceability。

## Failure Modes

- 配置缺失：start 返回 503/JSON 或页面显示配置缺失。
- state 失效/不匹配：callback 返回脱敏错误并重定向回页面显示失败。
- EduPlus2 token endpoint 失败：不显示 code/secret/token，只显示 HTTP status 或 `token_endpoint_unavailable`。
- token response 没有可用 `id_token/access_token`：失败并提示检查 scope/client 配置。
- token response 没有 refresh token：首轮对话仍可执行；自动续签面板提示需要 EduPlus2 refresh grant 或调整 scope/client。
- DeepTutor exchange 失败：映射为 401/403/409/429/503 类提示。
- WebSocket 初始认证失败：提示 `dt_token` 未被 WS 接受，并建议先检查 exchange/API probe。
- token refresh 失败：不复用旧 token 扩权，停止自动续签并提示重新发起统一认证。
- Demo session 过期：result 返回 404/410，页面提示重新开始。

## Verification Strategy

- OpenSpec strict validation。
- 后端 pytest：start 生成安全 redirect；callback 成功时不把 token 写 URL；result 返回脱敏摘要；refresh 复用 refresh grant 后再次调用 exchange；state mismatch / missing config fail closed。
- 前端测试：JWT/result redaction helper、页面渲染、不会调用 localStorage 存 token、WS URL 不带 token、临期判断会触发 refresh/auth_refresh。
- `ruff` / targeted pytest / web typecheck。
- Playwright 打开 `/enterprise/eduplus2/fronting-demo`，检查按钮与状态面板可见。
