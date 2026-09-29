# add-c1-c2-oms-operator-interface 实施证据

## 2026-09-29 正式 OMS 受控入口与只读治理聚合切片

- 新增独立 OMS 正式入口 `/oms`，使用 `OmsFormalApp` 同源读取 `/api/v1/oms/me`、`/api/v1/oms/me/permissions` 和后端安全 DTO；认证或本地 `ops.*` 授权失败时失败关闭，不回退 `/oms/prototype`。
- 现有 `/oms/prototype` 服务端 route 与 proxy 在非 development 环境返回 404；正式入口不保留旧“学校后台开通”深链或学校账号管理按钮。
- 首屏已接入只读 DTO：`/summary`、`/resources/status`、`/models/draft`、`/provider-settings`、`/tenants`、`/supply`、`/audit`、`/cost`、`/skills`。读取面由 `/me/permissions` 的本地 `ops.*` 动作摘要决定，未授权模块显示空/未读取状态，不预取 Secret、成本明细或跨学校数据。
- 前端测试：`cd extensions/enterprise/frontends && npm test -- formal-management-gates.test.tsx`，覆盖正式 OMS/TMS 入口失败关闭、DTO 接线、Secret/成本/学校账号写入口不暴露、OMS 资源/学校/供给/审计/成本只读聚合和 TMS 目录状态。

## 2026-09-29 正式 OMS 学校用量/任务只读切片

- 在 `/oms` 正式入口中按本地 `ops.usage.read`/`ops.jobs.read` 动作摘要，对首个已授权学校读取 `/api/v1/oms/schools/{school_id}/usage` 与 `/api/v1/oms/schools/{school_id}/jobs`。
- UI 展示 attempt、operation、service、后端状态 label、预留/结算原生单位摘要；不显示用户私有正文、学校数据明文、成本估算或结算/释放/核销写按钮。
- 前端测试：`cd extensions/enterprise/frontends && npm test -- formal-management-gates.test.tsx` 中 “OMS 正式入口按首个已授权学校展示用量 attempt 与待核对任务只读 DTO”。

## 2026-09-29 正式 OMS 写按钮首切片

- `/oms` 在 `ops.providers.manage` 存在时显示模型草稿测试/发布/回滚，以及 Provider 设置测试/发布/回滚按钮；请求体只携带后端 DTO version 与固定原因，不接受页面输入 Secret 或任意配置正文。
- `/oms` 在 `ops.skills.review`、`ops.skills.publish`、`ops.skills.grant` 存在时分别显示 Skill 批准、发布和首个已授权学校 grant 按钮；请求体使用列表 DTO 的 revision、sha256、latest version 和已授权学校 ID，不从 URL/query/body 切校。
- 前端测试：`cd extensions/enterprise/frontends && npm test -- formal-management-gates.test.tsx` 覆盖 Provider/模型写按钮与 Skill review/publish/grant 调用；组合回归 `npm test -- formal-management-gates.test.tsx management-authorization-prototype.test.tsx tms-drawer.test.tsx tms-service-projection.test.tsx apps.test.tsx` → **55 passed**；`npm run typecheck:oms`、`npm run typecheck:tms` 均通过。
- 说明：供给补充、服务授权、统一赠送/充值额度、核对动作、平台人员/角色/学校范围授权 UI、真实平台目录候选和完整 E2E 仍未完成。

### 2026-09-29 正式 OMS 平台授权治理 UI/API 切片

- 正式 `/oms` 新增“平台授权治理”区，仅在 `ops.permissions.manage` 下读取 `/api/v1/oms/permissions` 与 `/api/v1/oms/approvals`，展示平台主体、角色模板、学校范围 assignment、审批与审计回读。
- UI 接入正式写 API：平台授权审批创建、审批批准、审批 apply、低风险学校范围角色授予、assignment 撤权和平台主体停用；所有 payload 均取自后端 DTO 的 principal/role/school/assignment/approval/policy version，不允许手工输入学校 ID 或 Secret。
- 后端新增/复用 `/api/v1/oms/approvals*`、`/api/v1/oms/principals/{principal_id}/roles`、`/api/v1/oms/assignments/{assignment_id}/revoke`、`/api/v1/oms/principals/{principal_id}/disable`，逐次走 DeepTutor Enterprise 本地 `ops.*` PEP、委托上界、学校绑定/版本、幂等和审计。
- 验证：`.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -k 'oms_approval_api_applies_platform_sensitive_role or oms_principal_school_scope_grant_and_disable_are_guarded' -q` → 2 passed；`cd extensions/enterprise/frontends && npm test -- formal-management-gates.test.tsx -t 'OMS 正式入口接入平台人员'` → 1 passed。
- 仍未完成：供给补充、服务授权、额度调整、核对动作、真实平台目录候选、跨学校真实负例、并发冲突和完整 E2E。
