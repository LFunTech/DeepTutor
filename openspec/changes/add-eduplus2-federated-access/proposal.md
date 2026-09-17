# EduPlus2 无 TMS/OMS 联邦访问闭环

## Why

当前约束是：**暂不实现 TMS 和 OMS**，也**暂不要求实时撤权传播**。EduPlus2 第三方联邦访问不能只停留在一次性 JWT exchange；生产可接受的被调用方能力还需要：用户 profile/权限复核、长连接/长对话 token refresh、前置应用完成的用户合法性校验，以及可查询/导出的审计证据。

因此本 proposal 从“B1-lite 只做预注册第三方换票”扩展为 **无 TMS/OMS 的联邦访问闭环**：第三方应用已完成 EduPlus2 登录后，DeepTutor 通过 EduPlus2 user JWT 换取短期 `dt_token`，并在后续 profile/permission、HTTP/WS 打开或刷新、周期安全检查和审计导出中持续以 EduPlus2 为权威来源。

TMS/OMS 管理面、Handoff/OIDC 交互式登录、在线 client 治理页面、平台运营角色和实时撤权推送/对账仍后移；但 profile/权限 API、WS refresh、前置应用合法性校验、审计导出 UI 不再作为非目标。

## What Changes

- 保留已实现的 API-only 第三方 JWT exchange：`POST /api/v1/auth/eduplus2/exchange` 只接受 `Authorization: Bearer <eduplus2_user_jwt>`，以 `azp` 作为 OAuth client id 主校验项，结合 allowlist/registration 与 resolve API 校验 client/app/tenant/policy。
- 纳入 EduPlus2 profile API：exchange 或 refresh 时获取/复核用户 profile，更新内部 identity binding 的外部用户摘要；profile 不可用或用户状态不可用时 fail closed。
- 纳入 EduPlus2 权限 API：exchange、refresh 和敏感操作前根据 EduPlus2 权限/角色/策略结果计算普通能力边界；EduPlus2 租户成员身份不自动获得个人内容访问权或管理 capability。
- 纳入 WS refresh：短期 `dt_token` 即将过期时，WS 通知客户端刷新；客户端提交新的 EduPlus2 user JWT 或通过 HTTP refresh/exchange 获得的新 `dt_token`，服务端重验 JWT、registration、resolve、profile、权限、session/owner 后更新连接认证上下文。
- 纳入打开/refresh/周期安全检查：每次 exchange、refresh、HTTP/WS/SDK 打开或新敏感操作，以及后台任务安全检查点，都结合短 TTL profile/permission/resolve 重验当前用户、client/app/tenant 和权限是否合法；webhook/事件仅作为可选增强，不作为本 proposal 门禁。
- 纳入审计导出 UI：在不依赖 TMS/OMS 的前提下提供最小企业审计查询/导出页面或独立企业路由，展示脱敏的 exchange、refresh、resolve、profile/permission、撤权、authz denied 和敏感操作记录。
- 保持 upstream 可合并：EduPlus2 业务逻辑位于 `extensions/enterprise/`；core 只允许增加通用 auth/session/WS/router/provider seam，并记录目的、风险和验证。

## Capabilities

### New Capability

- `enterprise-eduplus2-federated-access`：规定无 TMS/OMS 的 EduPlus2 JWT 验证、resolve 权威校验、受控 client registration、profile/权限复核、第三方换票、WS refresh、前置应用合法性校验、审计导出 UI 和 owner/resource guard。

### Related Existing Capabilities

- `enterprise-local-identity`：不恢复普通用户本地注册；仅允许对已验证外部身份做内部 binding/JIT provisioning。
- `enterprise-session-lifecycle`：复用已有 session、token、WS 和 owner guard；本 change 补充外部身份 claim、短期 token refresh 和撤权状态。
- `enterprise-scoped-persistence`：复用 PG/RLS/tenant scope/审计原则，新增或扩展 EduPlus2 registration、binding、profile/permission snapshot、resolve cache、revocation state 和 audit/export 表。
- `enterprise-runtime-composition`：复用企业扩展包装配与缺依赖 fail closed 机制。

## Scope and Delivery Status

**状态：已完成第三方 exchange 主链路的大部分本地实现与真实 resolve smoke；本次重新纳入 profile/权限 API、WS refresh、前置应用合法性校验、审计导出 UI。实时撤权推送/复杂事件对账后移，未生产上线。**

### 已完成/保留范围

- OIDC/JWKS verifier、M2M token client、resolve client、allowlist/registration auto-upsert。
- `POST /api/v1/auth/eduplus2/exchange`、短期 `dt_token`、JIT identity binding、owner/resource guard、脱敏审计、replay/rate limit、真实 discovery/JWKS/token/resolve smoke。

### 新增交付范围

- Profile API：获取/复核 EduPlus2 用户状态、名称/身份类型/组织摘要，更新内部绑定和审计；不保存不必要隐私。
- 权限 API：获取/复核用户对当前 client/app/tenant 的能力边界；普通 exchange 不授予 TMS/OMS/ops 管理能力。
- WS refresh：支持 `auth_expiring` / `auth_refresh` 或等效 HTTP refresh + WS ack；刷新成功不中断长对话，失败后拒绝新敏感命令。
- 合法性重验：每次前置应用打开/refresh/周期检查结合短 TTL profile/permission/resolve 快照重验，发现用户、client/app/tenant 或权限不可用时 fail closed；不要求实时撤权推送。
- 审计导出 UI：提供不依赖 `/tms` 或 `/oms` 的最小企业审计查看/导出入口，支持范围过滤、脱敏、权限控制和导出审计。

### 仍然后移 / 非目标

- 不实现 `/tms`、`/oms` 页面、路由、菜单、管理 API 或 Handoff/OIDC callback。
- 不实现 TMS/OMS 的在线 client 注册、暂停、恢复、注销页面。
- 不开放第三方 client 自助注册；不保存第三方 client secret。
- 不实现平台运营完整角色体系或 OMS 全局治理面；审计导出 UI 仅限本 change 明确的最小企业审计入口。
- 不以完成本 change 宣称完整 B2/G2、TMS/OMS、生产上线或 HA/G-H 通过。

## Impact

- **API**：保留 `/api/v1/auth/eduplus2/exchange`；新增 refresh/profile/permission/revocation/audit export 相关 API；不新增 TMS/OMS 管理 API。
- **Persistence**：扩展 EduPlus2 provider config、registration、identity binding、profile/permission snapshot、revocation state、refresh metadata、audit/export job 表；需要版本化迁移、RLS/tenant 约束和脱敏字段。
- **Security**：新增 profile/permission client、WS refresh 重验、短 TTL 周期校验、可选 webhook/事件签名校验、导出权限、导出水印/审计、日志脱敏。
- **Permissions**：普通 exchange/refresh 只授予普通使用能力；审计导出 UI 需要显式 enterprise audit/export 权限或现有 tenant_admin 受控能力，后端强制校验。
- **Frontend**：新增最小审计导出 UI；不做 TMS/OMS 壳层。
- **External dependency**：依赖 EduPlus2 OIDC/JWKS、token endpoint、resolve API、profile API、权限 API；webhook/事件或可轮询状态 API 为实时撤权增强，不作为本 proposal 门禁。
- **Upstream**：core 改动仅允许通用 seam；企业逻辑在 `extensions/enterprise/`，不得复制上游大文件或依赖 monkey patch。

## Approval and Rollout

1. 先完成 exchange 已有链路与真实 user-JWT smoke。
2. 再接入 profile/权限 API，并验证停用/无权限用户 fail closed。
3. 再实现 WS refresh 与前置应用合法性校验，验证长对话、断线重连、权限失效后新命令拒绝。
4. 最后交付最小审计导出 UI，完成权限、脱敏、导出审计和泄露扫描。
5. 生产前必须确认 token TTL、周期校验间隔/撤权窗口、审计保留、导出权限、限流、监控和 upstream 合并证据；若要求实时撤权 SLA，再补 webhook/事件或对账 proposal。
