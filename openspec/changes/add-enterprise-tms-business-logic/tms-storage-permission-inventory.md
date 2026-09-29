# TMS 存储归属与权限基线盘点（2026-09-28）

## 结论

TMS 正式业务必须以当前可信学校 `tenant_id/school_id` 为唯一管理边界；旧 `tenant_admin`、URL `schoolCode`、JWT role、header/query/body 中的 tenant 字段、EduPlus2 `eit` 或 Webhook secret 都不能自动成为本产品 `tenant.*` 授权。管理授权由 `management.*` 本地 PG 事实与 Enterprise PEP 判定；个人正文仍由 owner/显式 grant 决定。

## 已有可信存储

| 领域 | 表/模块 | 当前归属键 | 可复用性 | 风险/备注 |
| --- | --- | --- | --- | --- |
| 学校主体 | `enterprise.tenants` | `id` 为内部学校 UUID；`external_tid` 仅作绑定输入 | 可复用 | RLS 以 `app.tenant_id` 限定；school_code 不是授权凭据。 |
| 用户/本地会话 | `enterprise.users/auth_sessions` | `tenant_id,user_id` | 只作本地/测试账号，不作 TMS 授权来源 | 旧 `role=tenant_admin` 不自动升级为 `tenant.*`。 |
| 会话/消息/turn | `enterprise.sessions/messages/turns` | `tenant_id,owner_id` | 可做 owner 受控读取 | 管理员无私有正文旁路；导出需另有显式 grant。 |
| 对象/文件/KB | `enterprise.resource_objects` | `tenant_id,owner_id,id/resource_id` | 可作为 TMS KB/文档清单基础 | 下载、引用、删除、重试仍需 owner/显式 grant；不得暴露 S3 key/长期 URL。 |
| runtime 设置 | `enterprise.runtime_settings` | `tenant_id,scope_kind,scope_id,key` | TMS 只读安全投影 | OMS Provider/Secret 设置不下发 TMS。 |
| OMS 学校绑定 | `oms.school_bindings` | `tenant_id` | TMS 登录/服务 grant 前置复核 | 只接受 verified 且版本匹配，不从 external_tid 文本猜测。 |
| 生命周期投影 | `eduplus2.webhook_school_state/controls` | `school_id/external_app_id/binding_version` | TMS 资格门禁 | Webhook-only；online resolve 不再覆盖状态。 |
| TMS 主体与授权 | `management.principals/assignments/delegation_policies/audit_events` | `application='tms', school_id` | 必须复用 | 统一 PEP；默认零权；首位管理员需真实 actor 本人激活。 |
| 服务权益/额度/用量 | `oms.tenant_service_entitlements/quota_grants/usage_attempts` | `tenant_id` | TMS 只读 | TMS 无写路由，不含供应商成本/Secret。 |
| 服务访问资格 | `oms.tenant_service_access_grants` | `tenant_id,service_id,subject_kind,subject_id` | 可作为 TMS 成员/应用服务访问 grant 基础 | 只表示调用资格，不生成额度、不写 usage。 |
| Skill 包 | `oms.skill_revisions/publications/grants` | `owner_kind/global|tenant`, `owner_school_id` | 可复用存储 | 仍缺 TMS tenant 上传/审核 API 与 ObjectStore 对账。 |

## 需要的后续迁移/适配清单

1. **成员/应用访问事实**：当前已有 `tenant_service_access_grants` 覆盖服务访问资格；后续 TMS 成员—应用、资源分享/转授权可优先复用 `management.*` assignment/delegation 与 resource owner/grant seam，若需新表必须只存事实，不使用 DB enum/CHECK/函数。
2. **TMS tenant Skill 管理**：现有 `oms.skill_revisions` 已支持 `owner_kind='tenant'` 和 `owner_school_id`，后续主要缺应用层 ZIP 上传、review/publish/grant 事务和 ObjectStore 孤儿对账；不需要把个人 Skill 迁入云端。
3. **KB/文档任务**：现有 `resource_objects` 可承载文档对象，LightRAG 任务/派生 manifest 的真实状态仍需后续文档 worker/API 适配；TMS 不得写内部 workspace/graph locator。
4. **当前学校只读配额/用量**：已有 `/api/v1/tms/quotas` 和 OMS 总账；后续仅需筛选/分页/详情 API，不得增加 TMS 写额度表。
5. **审计与导出**：TMS 授权/资源动作写 `management.audit_events` 或 OMS 安全审计；导出响应必须脱敏并以当前学校过滤。

## 权限负例清单

- 旧 `tenant_admin` 登录 TMS：无 `management.principals` + active `tenant.tms.access` 时 403/待激活。
- 同租户管理员读取他人私有消息/文件正文：除 owner 或显式 resource grant 外拒绝。
- URL `/tms/{schoolCode}` 指向其他学校：必须与可信身份 school 绑定比对失败。
- 伪造 `X-Tenant-ID`、body/query tenant 或 school_id：中间件/API 拒绝，不改 scope。
- TMS 调用 OMS 配额写、Provider/Secret、成本或跨校 API：403/404，前端不渲染入口。
- 服务访问 grant 被撤销或 OMS 服务权益版本变化：旧 grant 不自动放行新调用。
- Skill 草稿未审核/未发布/未授权：不进入 `read_skill`、manifest、`always` 或 TMS 清单可执行状态。
