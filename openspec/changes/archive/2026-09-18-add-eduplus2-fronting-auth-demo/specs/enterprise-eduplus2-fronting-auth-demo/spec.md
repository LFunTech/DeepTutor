## Purpose

提供一个 local/test 专用的 EduPlus2 统一认证前置应用可视化 demo，用于验证“跳转 EduPlus2 登录 → authorization code 回跳 → 换取 EduPlus2 user JWT → DeepTutor exchange → `dt_token` 调 DeepTutor API 与 `/api/v1/ws` 对话 → 临期/超时自动续签”的端到端接入链路。该能力不交付生产 Handoff/OIDC callback、TMS/OMS 登录或长期 session。

## ADDED Requirements

### Requirement: Demo 必须通过 EduPlus2 统一认证启动

系统 SHALL 提供 `/enterprise/eduplus2/fronting-demo` 页面，允许用户点击按钮跳转 EduPlus2 authorization endpoint。系统 SHALL 由后端生成 state 和 PKCE verifier，并在 callback 时校验 state。

#### Scenario: 用户点击 demo 登录
- **WHEN** 用户在 demo 页面点击“使用 EduPlus2 统一认证测试”
- **THEN** 浏览器被重定向到配置的 EduPlus2 authorization endpoint，且请求包含 `client_id`、`redirect_uri`、`response_type=code`、`scope`、`state` 和 PKCE challenge

### Requirement: Callback 必须换取 user JWT 并调用现有 exchange

系统 SHALL 在 demo callback 中用 authorization code 调 EduPlus2 token endpoint，并从 token response 中取得 `id_token` 或可用 user JWT。系统 SHALL 调用现有 `enterprise.eduplus2.exchange_user_jwt()`，不得复制 exchange 授权逻辑。

#### Scenario: EduPlus2 成功回跳
- **WHEN** callback 收到有效 `code` 和 `state`
- **THEN** 系统换取 user JWT、调用现有 exchange、生成短期 demo session，并重定向回 demo 页面

### Requirement: Demo 不得泄露 token 或 secret

系统 SHALL NOT 将 EduPlus2 user JWT、DeepTutor `dt_token`、authorization code、code verifier、client secret、M2M token、refresh token 或 webhook secret 写入 URL、持久存储、普通日志、审计正文或页面可见文本。页面 MAY 在内存中暂存 `dt_token` 并立即调用 DeepTutor API probe 与 WebSocket 对话。

#### Scenario: Callback 重定向回前端
- **WHEN** demo callback 完成后重定向到前端页面
- **THEN** URL 只包含不透明 `demo_session` 或错误摘要，不包含 JWT、`dt_token`、code、secret 或 verifier

### Requirement: Demo 页面必须验证 DeepTutor API 可用

系统 SHALL 在 demo result 可用时让页面使用 `Authorization: Bearer <dt_token>` 调用 DeepTutor API（至少 `/api/auth/status`），并展示后端是否接受该 token 的脱敏结果。

#### Scenario: DeepTutor 接受 dt_token
- **WHEN** demo 页面拿到 callback 生成的 `dt_token`
- **THEN** 页面调用 `/api/auth/status` 并展示 authenticated、role、user hash 等脱敏结果，不展示 token 原文

### Requirement: Demo 页面必须通过 WebSocket 完成真实对话

系统 SHALL 在 demo result 可用后允许用户通过 `/api/v1/ws` 发起一轮真实 DeepTutor `start_turn` 对话。系统 SHALL 使用内存中的 `dt_token` 认证 WebSocket，不得把 token 放入 WebSocket URL、query、localStorage 或 sessionStorage。页面 SHALL 展示 WS 连接状态、发送的 prompt、stream event 摘要和 assistant content。

#### Scenario: 用户在 demo 中发起对话
- **WHEN** demo 页面已有有效 `dt_token` 且用户点击“开始 WebSocket 对话”
- **THEN** 页面连接 `/api/v1/ws`、发送 `start_turn`，并展示来自 DeepTutor 的 content/progress/done 等事件

### Requirement: Demo 必须自动续签超时 token

系统 SHALL 在 demo session 保存短期 refresh proof（如 EduPlus2 token endpoint 返回 refresh token），并提供 `POST /api/v1/auth/eduplus2/demo/refresh` 用于自动续签。页面 SHALL 根据 `expires_at` 在临期或超过超时时间时自动请求 refresh，后端 SHALL 使用 refresh grant 换取新的 EduPlus2 user JWT，并复用现有 `enterprise.eduplus2.exchange_user_jwt()` 签发新的 `dt_token`。若 WebSocket 仍连接，页面 SHALL 发送 `auth_refresh`；若连接已关闭，页面 SHALL 用新 token 重新连接。

#### Scenario: dt_token 超时后自动续签
- **WHEN** demo 页面持有的 `dt_token` 已临期或超过 `expires_at`
- **THEN** 页面自动请求 demo refresh，获得新 `dt_token` 后刷新 API/WS 认证状态，不要求用户手工输入 token

### Requirement: Demo 必须 fail closed 并展示可操作错误

系统 SHALL 对配置缺失、state 不匹配、code exchange 失败、token response 缺字段、exchange 失败、demo session 过期等情况 fail closed，并展示脱敏错误矩阵和下一步。

#### Scenario: State 不匹配
- **WHEN** callback 收到未知或过期 state
- **THEN** 系统拒绝继续换 token，不调用 DeepTutor exchange，并返回或重定向脱敏错误

### Requirement: Demo 不得声明为生产登录能力

文档和页面 SHALL 明确该 demo 仅用于 local/test 前置应用联调，不代表 TMS/OMS、生产 Handoff/OIDC callback、在线 client 治理、实时撤权 SLA、M1/G1 或生产上线完成。

#### Scenario: 用户打开 demo 页面
- **WHEN** 页面加载
- **THEN** 页面清楚标注 demo-only/local-test，不把它描述为生产登录入口
