# 实施任务

范围以 [proposal](proposal.md)、[design](design.md) 和 `enterprise-eduplus2-federated-access` delta spec 为准。当前任务已调整为：**暂不实现 TMS/OMS，也暂不要求实时撤权传播；打开/refresh/周期合法性校验由前置应用负责；当前 repo 纳入 JWT exchange/resolve、WS token refresh、owner/resource guard、审计导出 UI，以及可选 profile/permission/webhook 增强**。已完成的 exchange 主链路保持勾选；新增范围未实现前不得勾选。

## 0. 契约、环境与准入配置

- [x] 0.1 确认并记录 EduPlus2 测试环境 discovery、issuer、JWKS、token endpoint、resolve endpoint、测试租户、测试用户、测试第三方 client；profile/permission endpoint 与 webhook/事件契约仅在启用可选增强时另行确认；不得把 token、client secret 或用户隐私写入文档。
- [x] 0.2 补齐 exchange 运行时配置：discovery、issuer、JWKS、token endpoint、resolve URL、M2M client id/secret_ref、allowlist、`dt_token` TTL。
- [x] 0.3 定义 B1 allowlist/预注册格式：`client_id`、expected tenant/app、internal tenant、registration source、启停状态。
- [x] 0.4 明确真实 smoke 输入与脱敏输出规则。
- [x] 0.5 补齐新增配置：profile URL、permission URL、refresh TTL/deadline、周期校验/撤权缓存 TTL、audit export storage/ref；webhook secret/ref 作为可选增强配置。

## 1. OIDC/JWKS、resolve 与 exchange 主链路

- [x] 1.1 实现 OIDC discovery/JWKS verifier。
- [x] 1.2 实现 M2M token client。
- [x] 1.3 实现 resolve client 与响应规范化。
- [x] 1.4 实现 resolve/JWKS 短缓存与 fail closed。
- [x] 1.5 实现 allowlist/registration auto-upsert 与唯一性约束。
- [x] 1.6 实现 `POST /api/v1/auth/eduplus2/exchange`、JIT binding、短期 `dt_token`、最小响应。
- [x] 1.7 实现 replay/rate limit 与 401/403/409/429/503 脱敏错误语义。

## 2. Profile API

- [x] 2.1 实现 EduPlus2 profile client：超时、重试边界、错误规范化、脱敏日志。
- [x] 2.2 exchange/refresh 时校验 profile `tid/eui/sub` 与 JWT/registration/resolve 一致。
- [x] 2.3 新增 profile snapshot 持久化和迁移：最小字段、版本、状态、更新时间、RLS。
- [x] 2.4 用户 disabled/deleted/inactive、profile mismatch、profile unavailable 负例 fail closed。
- [x] 2.5 审计 `profile.fetch`，不得保存敏感 profile 原文。

## 3. 权限 API

- [x] 3.1 实现 EduPlus2 permission client：按 user/tenant/client/app/requested usage 查询权限。
- [x] 3.2 exchange/refresh 时计算普通 DeepTutor 能力边界；不得授予 TMS/OMS/ops 管理能力。
- [x] 3.3 新增 permission snapshot 持久化和迁移：permission version、allowed usages、expires_at、RLS。
- [x] 3.4 permission denied/revoked/unavailable/version expired 负例 fail closed。
- [x] 3.5 后续 HTTP/WS/SDK 敏感操作按 permission snapshot + owner/resource guard 重验。

## 4. WS refresh 与长连接续期

- [x] 4.1 定义 WS `auth_expiring`、`auth_refresh`、`auth_ack`、`auth_revoked` 事件/命令 schema。
- [x] 4.2 实现 refresh：重验 JWT、registration、resolve、profile、permission、auth session、owner/connection 上下文。
- [x] 4.3 刷新成功更新连接认证上下文，不扩大 scope；刷新失败拒绝新命令或断开。
- [x] 4.4 支持新 `dt_token` 重连和 `resume_from turn_id + after_seq` 安全恢复。
- [x] 4.5 测试长对话、过期前刷新、过期后新命令拒绝、断线重连、并发/重复 refresh 幂等。

## 5. 前置应用合法性校验边界与可选增强

- [x] 5.1 明确打开/refresh/周期合法性校验由前置应用负责；当前 repo 不实现该周期校验；webhook/事件接收保留为可选增强并具备签名、timestamp、event id、防重放基础校验。
- [x] 5.2 当前 repo 保留 profile/permission/revocation state/event 持久化作为可选增强和审计证据；外部合法性由前置应用处理。
- [x] 5.3 当前 repo 在 exchange/resolve、短期 token、owner/resource guard、可选撤权事件路径 fail closed；不承担前置应用周期重验。
- [x] 5.4 WS 仅处理本 repo token/session/owner/resource guard 与可选撤权事件后的下一命令关闭；外部用户合法性周期检查由前置应用负责。
- [x] 5.5 无 webhook 时当前 repo 不承诺实时撤权窗口；外部撤权窗口由前置应用周期校验策略负责，当前 repo 只保留短期 `dt_token` 与可选重验能力。
- [x] 5.6 实时撤权乱序、部分失败和恢复对账测试后移；当前仅覆盖可选 webhook 重放/签名错误/重复基础负例。

## 6. 审计与审计导出 UI

- [x] 6.1 已实现 exchange/resolve/registration/authz denied 的基础脱敏审计。
- [x] 6.2 补齐 profile、permission、refresh、revocation、audit export 的持久审计。
- [x] 6.3 实现审计查询 API：筛选、分页、租户范围、脱敏详情。
- [x] 6.4 实现最小审计导出 UI：不使用 `/tms`/`/oms`，支持筛选、导出、状态查看、错误展示。
- [x] 6.5 实现导出 job：CSV/JSONL、文件存储 ref、过期清理、导出本身审计。
- [x] 6.6 实现导出权限：显式 enterprise audit/export 权限或受控 tenant_admin；无跨租户全局导出。
- [x] 6.7 已增加日志/审计泄露扫描，确认 touched 源码/文档不含 `.secrets` token/secret；后续新增 UI/API 后需扩展扫描。

## 7. Owner guard、迁移与安全负例

- [x] 7.1 已验证 exchange 后 HTTP/WS/SDK 走现有 tenant scope、owner/resource guard。
- [x] 7.2 已验证并发首次 exchange 只创建一条 registration/binding。
- [x] 7.3 已验证迁移、RLS、重复迁移、迁移失败回滚。
- [x] 7.4 扩展迁移测试覆盖 profile/permission/revocation/audit export 表、drift、RLS。
- [x] 7.5 扩展安全负例矩阵：profile mismatch、permission denied、revoked old token/WS、audit export 越权。

## 8. upstream 可合并与发布门禁

- [x] 8.1 EduPlus2 exchange 业务逻辑默认放在 `extensions/enterprise/`；core 只保留通用 seam。
- [x] 8.2 已静态检查没有把 EduPlus2 业务硬编码进 core orchestrator/session/registry。
- [x] 8.3 新增 WS refresh/revocation/audit UI 后重新执行 upstream seam 风险审查。
- [x] 8.4 运行完整 targeted 测试、真实 EduPlus2 smoke、ruff/type/lint、迁移验证和 `openspec validate add-eduplus2-federated-access --strict`。
- [x] 8.5 更新 evidence 和 rollout 结论，明确通过门禁、未验证项、生产前阻塞、TTL/撤权风险接受。
