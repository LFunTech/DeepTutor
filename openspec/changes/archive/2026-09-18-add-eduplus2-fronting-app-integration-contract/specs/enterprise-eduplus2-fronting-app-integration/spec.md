## Purpose

规定前置应用与 DeepTutor API-only EduPlus2 联邦访问能力之间的交接契约：前置应用负责 EduPlus2 登录态、打开/refresh/周期合法性校验和 user JWT 刷新；DeepTutor 负责 user JWT exchange、短期 `dt_token`、WS refresh、owner/resource guard、可选 profile/permission/webhook fail closed 和审计。该能力交付文档、配置矩阵、错误处理、smoke 验证和脱敏证据，不交付 TMS/OMS 或实时撤权 SLA。

## ADDED Requirements

### Requirement: 前置应用接入契约必须自包含且版本化

系统 SHALL 提供一份面向前置应用团队的接入契约文档，覆盖架构边界、端到端时序、HTTP/WS payload、错误矩阵、配置矩阵、安全禁令、审计排障和 smoke 命令。文档 MUST 指向当前正式 OpenSpec specs 和已实现 API，不得引用已删除的 active change 目录作为主契约来源。

#### Scenario: 前置应用团队首次接入
- **WHEN** 前置应用团队只阅读 P1 接入契约文档
- **THEN** 应能理解如何获取 EduPlus2 user JWT、调用 DeepTutor exchange、保存和刷新 `dt_token`、接入 WS、处理错误、查询审计，并知道哪些能力不在当前范围

### Requirement: Exchange contract 必须禁止未签名身份覆盖

接入契约 SHALL 明确 `POST /api/v1/auth/eduplus2/exchange` 只接受 `Authorization: Bearer <eduplus2_user_jwt>` 作为身份断言。请求 body、query 或非签名 header 中的 tenant/user/client 信息 MUST NOT 被前置应用或 DeepTutor 视为授权证据。响应和示例 MUST NOT 包含 raw EduPlus2 JWT、DeepTutor `dt_token` 示例真值、client secret 或 M2M token。

#### Scenario: 前置应用传入 body tenant
- **WHEN** 前置应用示例或 smoke 请求试图通过 body/query/header 传入 `tenant_id`、`user_id` 或 `client_id` 来覆盖 JWT claims
- **THEN** P1 契约必须标记该做法无效且危险；DeepTutor 仅以验签 JWT、resolve 和 registration 作为授权依据

### Requirement: WS refresh contract 必须覆盖 refresh、失败和恢复

接入契约 SHALL 记录 WS `auth_refresh` 命令字段：`type`、`command_id`、`dt_token` 或 `external_token`、`protocol_version`。文档 SHALL 说明 `auth_ack`、`auth_revoked`、可选 `auth_expiring` 和 `resume_from` 的时序，并要求 refresh 不得扩大 tenant/user/client/app scope。

#### Scenario: dt_token 临近过期
- **WHEN** WS 连接中的 `dt_token` 临近过期或前置应用完成外部 refresh
- **THEN** 前置应用应获取新的 EduPlus2 user JWT 或 DeepTutor `dt_token`，发送 `auth_refresh`，收到 `auth_ack` 后继续；失败时重新 exchange 并用 `resume_from` 恢复事件流

### Requirement: 前置应用合法性校验职责必须外置到调用方

接入契约 SHALL 明确前置应用负责打开 DeepTutor 前、refresh 时和周期窗口内的 EduPlus2 用户合法性校验。DeepTutor 当前 repo SHALL 不被描述为负责外部用户周期合法性调度；DeepTutor 仅在 exchange、WS refresh、新 HTTP/WS/SDK 敏感操作和可选 webhook/profile/permission 路径内 fail closed。

#### Scenario: 用户外部权限撤销但没有 webhook
- **WHEN** EduPlus2 侧用户或 client 权限被撤销，但当前部署没有实时 webhook SLA
- **THEN** 前置应用的周期校验策略决定外部撤权窗口；DeepTutor 仍通过短 `dt_token`、下一次 exchange/refresh 和自身 owner guard 限制访问，但不承诺即时感知

### Requirement: 错误处理矩阵必须可直接用于产品逻辑

接入契约 SHALL 为 401、403、409、429、503、WS `auth_revoked`、owner guard denied 和 audit export denied 定义前置应用处理建议，包括是否重新登录、是否重试、是否指数退避、是否提示配置冲突或联系管理员。错误示例 MUST 脱敏且不泄露路径、secret、token、签名或私密正文。

#### Scenario: exchange 返回 429
- **WHEN** DeepTutor exchange 返回 429
- **THEN** 前置应用应执行退避或稍后重试，不应循环获取 JWT 或并发刷票放大流量

### Requirement: Smoke harness 必须验证真实链路且脱敏

系统 SHALL 提供或封装可重复执行的 smoke 入口，读取 local/test `.secrets` 配置，验证 discovery/JWKS、M2M token、resolve、user JWT exchange、`dt_token` 解码、WS refresh 和审计 query/export 中的适用部分。smoke 输出 MUST 只包含脱敏摘要、布尔状态、request id 和非敏感元数据，不得打印 token、client secret、M2M token、JWT 原文或用户隐私。

#### Scenario: token-test.secrets 有未过期 JWT
- **WHEN** `.secrets/token-test.secrets` 提供未过期 EduPlus2 user JWT 且 local/test env 配置完整
- **THEN** smoke 应验证 user JWT exchange 成功、`dt_token` 当前有效、`azp` 匹配、审计可查询，并输出脱敏成功摘要

#### Scenario: token 缺失或过期
- **WHEN** `.secrets/token-test.secrets` 缺失 token 或 token 已过期
- **THEN** smoke 应 fail closed，输出脱敏原因和需要前置应用重新获取 user JWT 的提示，不得打印 token 内容

### Requirement: 审计联调必须覆盖权限和脱敏

接入契约和 smoke SHALL 说明如何使用 `/api/v1/enterprise/audit/eduplus2/events` 与 `/api/v1/enterprise/audit/eduplus2/exports` 进行联调排障。普通用户或无权限 token MUST 被拒绝；有权限 tenant admin 只能查询授权范围内脱敏事件。导出结果 MUST 不包含 raw token、client secret、完整 profile 或私密正文。

#### Scenario: 前置应用排查一次失败 exchange
- **WHEN** 前置应用提供 request id 给 DeepTutor 管理员排查失败 exchange
- **THEN** 管理员可用审计接口按 request id 查询脱敏 reason、client/app/tenant/user 摘要和结果；无法查看 token/secret 原文

### Requirement: P1 不得扩展为 TMS/OMS 或生产上线声明

P1 SHALL 明确自身交付边界：完成后仅代表前置应用联调契约和 smoke 包可用，不代表 `/tms`、`/oms`、Handoff/OIDC callback、在线 client 治理、实时撤权 SLA、M1/G1 或生产上线完成。

#### Scenario: 文档或 evidence 声称 TMS/OMS 可用
- **WHEN** P1 文档、evidence 或 README 声称 `/tms`、`/oms` 或在线 client 治理已经实现
- **THEN** 该声明必须被视为错误并修正，除非对应后续 proposal 已实现并验证
