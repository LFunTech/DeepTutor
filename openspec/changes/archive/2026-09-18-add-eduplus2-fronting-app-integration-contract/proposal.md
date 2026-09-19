# EduPlus2 前置应用接入联调契约

## Why

`enterprise-eduplus2-federated-access` 已完成 DeepTutor 当前 repo 侧的 API-only 联邦访问闭环：EduPlus2 user JWT → DeepTutor `dt_token`、WS refresh seam、owner/resource guard、可选 profile/permission/webhook 增强和独立审计导出 UI。下一步 P1 的目标不是继续扩展 DeepTutor 认证逻辑，而是让**前置应用**和 DeepTutor 之间有一份可执行、可验证、可交接的集成契约。

当前风险是：虽然 DeepTutor 端 API 已可用，但前置应用仍需要明确：何时获取/刷新 EduPlus2 user JWT、如何调用 exchange、如何持有和刷新 `dt_token`、WS 如何续期与重连、哪些错误必须 fail closed、打开/refresh/周期合法性校验由谁负责，以及如何使用审计查询/导出定位问题。如果这些边界只散落在 docs 和实现测试里，联调容易出现重复登录、错误缓存、token 泄露、将 DeepTutor 当成合法性周期检查方，或误把审计页面/TMS/OMS 混为一体。

因此 P1 规划为 **前置应用接入契约与联调 smoke 包**：输出一份面向前置应用团队、DeepTutor 部署方和联调人员的协议文档、配置清单、错误矩阵、时序图/流程、示例请求、可重复 smoke 命令和证据模板。

## What Changes

- 新增前置应用接入契约文档，建议路径：`docs/enterprise/eduplus2-fronting-app-integration-contract.md`。
- 明确 DeepTutor 已有 API 的外部调用契约：
  - `POST /api/v1/auth/eduplus2/exchange`
  - WS `auth_refresh` / `auth_ack` / `auth_revoked` / 可选 `auth_expiring`
  - `GET /api/v1/enterprise/audit/eduplus2/events`
  - `POST /api/v1/enterprise/audit/eduplus2/exports`
  - 可选 `POST /api/v1/auth/eduplus2/revocations`
- 明确前置应用职责：打开 DeepTutor、refresh 时用户合法性校验、周期合法性校验、获取新的 EduPlus2 user JWT、处理 `dt_token` 临近过期、重连与 `resume_from`。
- 输出错误码和恢复策略矩阵：401/403/409/429/503、WS refresh 失败、token replay/rate-limit、resolve/profile/permission 不可用、owner guard 失败。
- 输出运行配置清单：必须和 `.secrets/token-test.secrets`、`.secrets/deeptutor-local-eduplus2.env` 的真实测试配置对齐，但不得写入 token、client secret 或用户隐私。
- 新增或规划 smoke harness：用当前 `.secrets` 中的测试 token/client 配置执行 discovery/JWKS/M2M/resolve/user-JWT exchange、`dt_token` 调用、WS refresh、audit export 的可重复验证，并输出脱敏摘要。
- 更新 `docs/enterprise/readme.md` 的“下一步”状态，指向 P1 契约，而不是把 TMS/OMS 当作前提。

## Scope

### In scope

- 契约文档、联调手册、示例 HTTP/WS payload、错误矩阵、配置矩阵和 smoke 证据模板。
- 面向 local/test 环境的 smoke 脚本或测试入口；读取 `.secrets` 但不打印 secret。
- 对现有 API 的 contract drift 检查：如文档与实际 schema/错误码不一致，优先修正文档；只有确认为实现 bug 时再立任务修正实现。
- 前置应用职责和 DeepTutor 职责分界：尤其是打开/refresh/周期合法性校验归前置应用。
- 后续 TMS/OMS、Handoff、实时撤权 SLA 和 M1/G1 生产基线的依赖说明。

### Out of scope

- 不实现 TMS、OMS、Handoff/OIDC callback、在线 client 注册治理页面。
- 不新增 DeepTutor 周期合法性校验后台任务；不把前置应用职责迁回当前 repo。
- 不承诺实时撤权传播；可选 webhook 仅作为增强入口说明。
- 不改 EduPlus2 端接口、Keycloak/OpenFGA 配置或真实用户数据。
- 不提交 `.secrets`、token、client secret、JWT 原文或用户隐私。
- 不把 P1 视为 M1/G1、B2/G2 或生产上线门禁完成。

## Capabilities

### New Capability

- `enterprise-eduplus2-fronting-app-integration`：规定前置应用与 DeepTutor API-only 联邦访问之间的交接契约、调用流程、错误处理、配置清单、smoke 验证和证据格式。

### Related Existing Capabilities

- `enterprise-eduplus2-federated-access`：P1 复用该已归档能力，不重复实现 exchange/WS/audit。
- `enterprise-runtime-composition`：P1 的 smoke 必须验证企业应用装配路径，而非未适配原生入口。
- `enterprise-local-identity` / `enterprise-scoped-persistence`：P1 文档必须说明内部 tenant/user binding 和 owner guard，不允许前置应用传未签名 tenant/user 覆盖。

## Delivery Plan

1. 先冻结实际 API/WS/audit schema 与错误码，确认文档来源为代码和已归档 spec。
2. 编写前置应用接入契约文档与时序/错误矩阵。
3. 增加 smoke harness 或明确现有 pytest/命令的封装入口，使用 `.secrets` local/test 配置生成脱敏验证摘要。
4. 执行本地和真实 EduPlus2 test smoke；验证不会打印 token/client secret。
5. 更新 `docs/enterprise/readme.md` 与 P1 execution evidence，明确下一步是否进入 M1/G1 生产基线或 TMS/OMS 专项 proposal。

## Success Criteria

- 前置应用团队只阅读 P1 文档即可完成 exchange、HTTP/WS 使用、refresh/reconnect、错误处理和审计联调。
- smoke 命令在 local/test 配置下可重复执行，输出只包含脱敏状态、request id、过期时间窗口、client/app/tenant 摘要，不输出 secret/token 原文。
- `openspec validate add-eduplus2-fronting-app-integration-contract --strict` 通过。
- 不新增 active TMS/OMS 实现声明；不改变已归档 P0/P1 前置职责边界。
