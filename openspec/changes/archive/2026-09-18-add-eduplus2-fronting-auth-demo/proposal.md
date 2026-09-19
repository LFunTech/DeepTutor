# EduPlus2 统一认证前置应用可视化 Demo

## Why

P1 `add-eduplus2-fronting-app-integration-contract` 已交付前置应用接入契约、命令行 smoke 和审计排障说明，但它仍要求测试人员手工提供 EduPlus2 user JWT。用户当前需要一个可视化 demo，真实模拟前置应用对接 EduPlus2 统一认证：点击按钮跳转 EduPlus2 登录，回跳后由 DeepTutor demo 后端完成 code 换 token、调用现有 EduPlus2 exchange，最后用 `dt_token` 调 DeepTutor API，直观看到整条链路是否可用。

该 demo 用于 local/test 联调，不是生产登录入口，不交付 TMS/OMS、Handoff/OIDC callback 的正式产品化治理，也不改变 P1 中“前置应用负责打开/refresh/周期合法性校验”的边界。

## What Changes

- 新增 demo-only 后端接口：
  - `GET /api/v1/auth/eduplus2/demo/start`
  - `GET /api/v1/auth/eduplus2/demo/callback`
  - `GET /api/v1/auth/eduplus2/demo/result`
  - `POST /api/v1/auth/eduplus2/demo/refresh`
- 新增前端可视化页面：`/enterprise/eduplus2/fronting-demo`。
- Demo start 读取 EduPlus2 OIDC authorization endpoint、token endpoint、client id/secret/ref、redirect URI、frontend return URL 等配置，生成 state/PKCE 后跳转 EduPlus2。
- Demo callback 校验 state，用 authorization code 换取 EduPlus2 user JWT，调用现有 `enterprise.eduplus2.exchange_user_jwt()`，保存短期内存 demo session，并重定向回 demo 页面。
- Demo result 返回脱敏摘要和仅供页面内存使用的 `dt_token`；页面随后用 `Authorization: Bearer <dt_token>` 调 `/api/auth/status` 做真实 DeepTutor API probe，并使用同一 token 建立 `/api/v1/ws` 对话。
- Demo refresh 在 `dt_token` 临期或超过超时时间时由页面自动触发；后端使用 EduPlus2 refresh grant 换取新的 EduPlus2 user JWT，再复用现有 `enterprise.eduplus2.exchange_user_jwt()` 签发新的 `dt_token`，页面对已连接 WS 发送 `auth_refresh`。
- 所有展示脱敏：不在 URL、日志、审计正文或前端持久存储中写入 EduPlus2 user JWT、`dt_token`、client secret、M2M token 或 code verifier。

## Scope

### In scope

- Local/test 可视化 demo 链路。
- OIDC authorization code + PKCE state 管理。
- `dt_token` 内存态 API probe 和 `/api/v1/ws` 真实对话。
- `dt_token` 临期/过期自动续签与 WS `auth_refresh`。
- 错误矩阵可视化：配置缺失、state 失效、code exchange 失败、user JWT 缺失/过期、DeepTutor exchange 401/403/409/429/503。
- 后端路由测试、前端工具测试、页面可打开验证。

### Out of scope

- 不实现 TMS/OMS 正式登录入口。
- 不实现生产 Handoff/OIDC callback 治理、在线 client 注册、长期 session、持久 refresh token 保存或实时撤权 SLA。
- 不新增数据库表或持久 demo session。
- 不将该 demo 作为普通用户登录入口或生产路由承诺。

## Success Criteria

- 用户访问 `/enterprise/eduplus2/fronting-demo`，点击按钮即可跳转 EduPlus2 统一认证。
- EduPlus2 回跳后页面展示：authorization、code exchange、DeepTutor exchange、DeepTutor API probe、WebSocket chat、token refresh 的分步状态。
- 成功时页面显示 DeepTutor API 已接受 `dt_token`，并能通过 `/api/v1/ws` 完成一轮真实对话，但不显示 token 原文。
- `dt_token` 临期或超过超时时间后，页面自动续签并保持/恢复 WS 对话认证。
- 失败时页面给出脱敏原因与下一步，不泄露 secret/token/code。
- OpenSpec strict validation、后端路由测试、前端测试、lint/typecheck/Playwright 可打开验证通过或记录明确阻塞。
