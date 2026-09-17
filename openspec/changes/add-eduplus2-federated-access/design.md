# 设计说明

## Context

本 change 当前边界：**不做 TMS/OMS，但要完成 EduPlus2 第三方联邦访问闭环**。关键原则：

1. EduPlus2 是用户、租户、账号生命周期、外部 profile 和外部权限的权威来源。
2. DeepTutor 不提供普通用户注册，不做 TMS/OMS Handoff 登录；第三方应用已经完成 EduPlus2 登录。
3. JWT exchange 以 `azp` 作为 OAuth client id 主校验项；resolve API 是 client/app/tenant/status/policy 权威来源。
4. profile/权限 API、WS refresh、前置应用合法性校验、审计导出 UI 纳入本 change；TMS/OMS 管理面与实时撤权推送/复杂对账仍不纳入。

## 决策 1：API-only exchange + profile/permission 复核

入口：

```text
POST /api/v1/auth/eduplus2/exchange
Authorization: Bearer <eduplus2_user_jwt>
```

处理顺序：

1. 验证 EduPlus2 user JWT：issuer/JWKS/`exp/iat/nbf`/`tid/eui/sub/azp`。
2. `azp` 命中 allowlist/registration，并通过 resolve 校验 client/app/tenant/policy active。
3. 调用 profile API 获取用户状态、身份类型、展示名/组织摘要等最小必要 profile。
4. 调用权限 API 获取该用户在当前 client/app/tenant 下允许使用 DeepTutor 的能力边界。
5. `tid`、profile tenant、permission tenant、registration tenant、resolve tenant 必须一致。
6. JIT 创建/更新 identity binding、profile/permission snapshot，签发短期 `dt_token`。
7. 写入脱敏审计，响应不包含 EduPlus2 token、refresh token、raw claims、secret 或私密正文。

## 决策 2：Profile API

profile client 要求：

- 使用 EduPlus2 access token 或服务端可信调用方式获取当前 JWT 用户 profile。
- 校验 profile 中的 external user id / subject / tenant 与 JWT claims 一致。
- 只保存最小快照：external user id、subject、identity type、display name hash/脱敏名、状态、profile version、updated_at。
- 用户 disabled/deleted/inactive、tenant 不匹配或 profile API 不可用时，新 exchange/refresh fail closed。
- profile 原文、手机号、邮箱、身份证等敏感字段不得进入审计或普通日志。

## 决策 3：权限 API

permission client 要求：

- 根据 external user、tenant、client/app 和 requested usage 查询 EduPlus2 权限。
- 权限 API 结果只决定“是否允许使用 DeepTutor 普通能力”和可选的能力边界，不授予 TMS/OMS/ops 管理能力。
- 权限快照包含 permission version、allowed usages/scopes、expires_at；短 TTL 缓存，撤权事件可失效。
- 权限不可用、返回 denied、版本过期或 tenant/app/client 不一致时，新 exchange/refresh fail closed。
- 后续个人资源访问仍由 DeepTutor owner/grant/resource guard 决定。

## 决策 4：WS refresh

`dt_token` TTL 保持短期。WS 支持以下协议之一：

- Server 发 `auth_expiring`：包含 expiry、deadline、request id，不含 secret。
- Client 发 `auth_refresh`：携带新的 EduPlus2 user JWT 或新 `dt_token`。
- Server 重验 JWT/registration/resolve/profile/permission/auth session/owner 后发 `auth_ack`。

规则：

- 已接受的单个 turn 不因自然过期强制中断，但新 turn、reply、cancel、订阅、历史读取、artifact/source 下载和敏感工具操作必须使用最新有效身份。
- 刷新失败后，连接进入只读/待重连或断开；不得继续读取新事件或提交新命令。
- 支持用新 `dt_token` 重连并通过 `resume_from turn_id + after_seq` 恢复该用户有权访问的事件。

## 决策 5：前置应用合法性校验

本 change 不要求实时撤权传播 SLA。合法性来源：

- exchange/refresh 时重验 JWT、registration、resolve、profile 和 permission。
- HTTP/WS/SDK 每次打开、新敏感操作或后台任务安全检查点，先检查本地短 TTL profile/permission/resolve 快照；快照超过 `DT_EDUPLUS2_REVOCATION_CACHE_TTL_SECONDS` 等配置窗口时重新调用 EduPlus2 profile/permission/resolve。
- 本地 ops：registration suspended/revoked、auth session revoked。
- EduPlus2 webhook/事件可作为可选增强，用于缩短撤权窗口，但不是本 proposal 的生产门禁。

校验行为：

- 当前用户、client/app/tenant、subscription 或 permission 不再合法时，拒绝新 exchange、新 refresh、新 WS 命令和敏感 HTTP/SDK 操作。
- 活跃 WS 不要求被外部事件主动推送断开；在下一次新命令、refresh 或周期安全检查点 fail closed。
- 后台任务在下一安全检查点 fail closed。
- 若启用 webhook，事件仍需幂等、有 event id、防重放、签名/timestamp 校验和审计；乱序/部分失败/恢复对账属于后续实时撤权增强。

## 决策 6：审计导出 UI

在不实现 TMS/OMS 的前提下，提供最小企业审计导出入口：

- 路由可为独立企业审计页面，例如 `/enterprise/audit/eduplus2` 或现有企业壳层下的 feature-flagged 页面；不得伪装为 TMS/OMS 已完成。
- 后端 API 支持列表、筛选、详情摘要和导出 job。
- 范围过滤：时间、event kind、client_id、external tenant/app/user、internal user、result/reason。
- 导出格式：CSV/JSONL，默认脱敏；导出本身写审计。
- 权限：仅显式 enterprise audit/export 权限或受控 tenant_admin 可访问本租户范围；无平台角色体系前不提供跨租户全局导出。
- UI 不展示 raw token、M2M token、client secret、完整 profile、私密正文或上游敏感响应。

## 决策 7：Persistence

扩展表建议：

- `eduplus2.profile_snapshots`：external user profile 最小快照与版本。
- `eduplus2.permission_snapshots`：permission result、version、expires_at。
- `eduplus2.revocation_events`：外部事件 id、类型、目标、版本、处理结果、幂等键。
- `eduplus2.audit_export_jobs`：导出请求、范围、状态、文件引用、导出审计。
- 既有 `audit_events` 增加或复用 event kinds：`profile.fetch`、`permission.check`、`token.refresh`、`revocation.apply`、`audit.export`。

全部表必须 RLS/tenant scoped，密钥和 raw token 不落库。

## 决策 8：upstream 可合并

- EduPlus2 client、profile/permission/revocation/audit export 逻辑放在 `extensions/enterprise/`。
- core 只新增通用 seam：WS auth refresh hook、session revoke/check hook、audit/event composition hook、router composition hook。
- 不复制上游大文件，不使用全局 monkey patch，不把 EduPlus2 业务写入 orchestrator/session/registry。

## Failure Modes

| 故障 | 处理 |
| --- | --- |
| discovery/JWKS/resolve/profile/permission 不可用 | 新 exchange/refresh fail closed；短缓存只在明确 TTL 内用于非扩权路径。 |
| profile user/tenant 与 JWT 不一致 | 401/409，禁止 JIT binding。 |
| permission denied/revoked | 403，拒绝 exchange/refresh/新敏感操作。 |
| WS refresh 失败 | 拒绝新命令，发送错误或断开。 |
| 可选 revocation webhook 重放/签名错误 | 若启用 webhook，则拒绝事件并审计，不改变状态。 |
| audit export 权限不足 | 403，记录 authz denied。 |
| 审计/合法性校验写入失败 | 安全关键路径 fail closed。 |

## Verification Strategy

- OpenSpec strict validation。
- 单元/集成：JWT、resolve、profile、permission、allowlist、exchange、refresh、打开/周期重验、audit export；webhook 仅覆盖已实现的可选基础签名/重放负例。
- 真实 smoke：discovery/JWKS、M2M token、resolve、profile、permission、真实 user-JWT exchange、WS refresh；不以真实撤权事件作为本 proposal 门禁。
- 安全负例：错 `azp`、错 `tid`、profile mismatch、permission denied、inactive client/app/tenant、JWT replay、rate limit、权限失效后旧 token/WS、新导出越权、日志泄露。
- owner guard：租户成员不等于个人资源授权。
- upstream 检查：core seam diff 审查、静态检查、相关回归测试。
