# 实施任务

## 0. 基线与配置

- [x] 0.1 核对 P1 契约、已归档 `enterprise-eduplus2-federated-access` spec 和现有 exchange/WS/audit 实现，确认 demo 只复用现有 exchange。
- [x] 0.2 核对 `.secrets/deeptutor-local-eduplus2.env` 中 authorization/token/client/redirect 相关 key 名称，不记录 secret 值。
- [x] 0.3 明确 demo-only 边界、TTL、失败模式和“不代表生产登录”的页面/文档提示。

## 1. 后端 demo API

- [x] 1.1 新增 demo state/session 内存管理，包含 TTL、PKCE verifier、return URL 和结果摘要。
- [x] 1.2 新增 `GET /api/v1/auth/eduplus2/demo/start`，生成 state/PKCE 并跳转 EduPlus2 authorization endpoint。
- [x] 1.3 新增 `GET /api/v1/auth/eduplus2/demo/callback`，校验 state、换取 user JWT、调用 `exchange_user_jwt()` 并重定向前端。
- [x] 1.4 新增 `GET /api/v1/auth/eduplus2/demo/result`，返回短期 demo result 和页面内存用 `dt_token`，但不展示 token 原文。
- [x] 1.5 新增 `POST /api/v1/auth/eduplus2/demo/refresh`，使用 refresh grant 换新 EduPlus2 user JWT，并复用 `exchange_user_jwt()` 签发新 `dt_token`。
- [x] 1.6 支持 demo WebSocket 认证使用非 URL 载体，不把 `dt_token` 放入 query/hash。
- [x] 1.7 后端错误必须脱敏，禁止 token/code/secret/verifier/refresh token 出现在 URL、响应摘要或日志。

## 2. 前端可视化 demo

- [x] 2.1 新增 `/enterprise/eduplus2/fronting-demo` 页面，展示六段链路：redirect、code exchange、DeepTutor exchange、API probe、WS chat、token refresh。
- [x] 2.2 页面按钮调用 demo start；回跳带 `demo_session` 时拉取 result。
- [x] 2.3 页面用内存态 `dt_token` 调 `/api/auth/status`，展示 authenticated/role/user hash，不落 localStorage/sessionStorage。
- [x] 2.4 页面用内存态 `dt_token` 连接 `/api/v1/ws` 并完成一轮真实对话，展示 event/content。
- [x] 2.5 页面根据 `expires_at` 自动调用 refresh，成功后对 WS 发送 `auth_refresh` 或重连。
- [x] 2.6 页面展示错误矩阵、request id、下一步建议和 demo-only 边界。

## 3. 测试与验证

- [x] 3.1 后端 TDD：start redirect、callback success、result redaction、refresh success、state mismatch / missing config fail closed。
- [x] 3.2 前端 TDD：redaction helper、页面基本渲染、不会持久化 token、WS URL 不带 token、自动 refresh/auth_refresh。
- [x] 3.3 运行 OpenSpec strict validation。
- [x] 3.4 运行后端 targeted pytest、前端 targeted test/typecheck/lint。
- [x] 3.5 使用 Playwright 打开 demo 页面并记录 URL；如真实 EduPlus2 登录无法自动完成，记录需人工完成的步骤。
- [x] 3.6 更新 execution evidence，说明完成该 demo 不代表 TMS/OMS、生产 Handoff/OIDC callback 或生产上线。
