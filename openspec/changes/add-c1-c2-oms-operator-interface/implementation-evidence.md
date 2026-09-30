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

### 2026-09-30 正式 OMS 学校权益详情与按学校用量深链

- 学校详情抽屉继续沿用正式 OMS 原型导航/列表→详情形态，新增展示 `/api/v1/oms/tenants` 安全 DTO 中的 `service_entitlements`、`quota_grants`、`usage` 聚合摘要；只显示后端状态文案与原生单位，不读取学校账号、不展示租户费用或私有正文。
- 学校详情“查看该学校用量入口”改为 `/oms/usage/school/{school_id}`，正式入口会在已授权学校列表内校验该 school id 后读取 `/api/v1/oms/schools/{school_id}/usage` 与 `/jobs`，不再固定首个学校；未命中已授权学校时仍回退到首个可见学校，不向后端发起任意 school id 读取。
- Skill 清单在具备 `ops.skills.review/publish/grant` 写权限时仍保留“查看 Skill 详情”动作，避免写按钮覆盖详情抽屉；写按钮 payload 仍只取后端 DTO 的 revision/version/sha256/school_id。
- 红绿验证：先新增失败测试 `npm test --prefix extensions/enterprise/frontends -- --run tests/formal-management-gates.test.tsx` → 3 failed（缺服务授权/额度摘要、用量深链仍读取首个学校、Skill 写权限下无详情按钮）；修复后同命令 → **42 passed**。
- 回归验证：`npm test --prefix extensions/enterprise/frontends` → **27 files / 295 tests passed**；`npm run typecheck:oms --prefix extensions/enterprise/frontends`、`npm run build:oms --prefix extensions/enterprise/frontends`、`npm run lint --prefix extensions/enterprise/frontends` → **通过**。
- 仍未完成：后端 display catalog 全量 descriptor 页面复用、真实筛选分页/授权导出、供给补充/服务授权写入、额度调整、核对动作、真实跨学校负例和完整 E2E。

### 2026-09-30 正式 OMS 后端 display catalog 状态呈现

- 正式 `/oms` 在读取 `/api/v1/oms/me/permissions` 后补充请求 `/api/v1/oms/status/catalog`，用后端拥有的 display descriptor 呈现 raw 状态码；`remote_unknown`、`settled` 等状态的 label/description 不再由前端硬编码。
- 用量/任务详情在 attempt 状态旁展示后端 descriptor 的核对说明，例如远端结果未知时提示“必须核对后才能释放或结算”，避免把缺失 usage 当零消耗或把待核对误渲染为已结算。
- 学校绑定/生命周期、资源状态、供给批次、用量任务、审计结果与成本状态均优先使用同一 status catalog；catalog 获取失败时仅退回安全 DTO 原文，不新增前端 enum 语义或 mock 数据。
- 红绿验证：先新增失败测试 `npm test --prefix extensions/enterprise/frontends -- --run tests/formal-management-gates.test.tsx -t "OMS 状态展示复用后端 display catalog"` → 1 failed（旧 UI 显示 raw `remote_unknown` 且无说明）；修复后同命令 → **1 passed**。
- 回归验证：`npm test --prefix extensions/enterprise/frontends -- --run tests/formal-management-gates.test.tsx` → **43 passed**；`npm test --prefix extensions/enterprise/frontends` → **27 files / 296 tests passed**；`npm run typecheck:oms --prefix extensions/enterprise/frontends`、`npm run build:oms --prefix extensions/enterprise/frontends`、`npm run lint --prefix extensions/enterprise/frontends` → **通过**；`openspec validate add-c1-c2-oms-operator-interface --strict` 与 `openspec validate add-enterprise-management-authorization --strict` → **valid**；`git diff --check` → **通过**。
- 仍未完成：真实筛选分页/授权导出、供给补充/服务授权写入、额度调整、核对动作、真实跨学校负例、真实账号按钮级验收和完整 E2E。

### 2026-09-30 正式 OMS 服务授权与额度写入口接线

- 正式 `/oms/supply` 在当前平台主体同时具有 `ops.quotas.read` 与 `ops.entitlements.read` 且存在已授权学校时，读取 `/api/v1/oms/schools/{school_id}/quota`，展示该学校服务 entitlement 与 quota grant 明细。
- 在 `ops.entitlements.manage` 下，服务定义行展示“授权当前学校服务/撤销当前学校服务授权”，调用 `/api/v1/oms/schools/{school_id}/entitlements/{service_id}`；payload 使用当前已授权 school、service、后端 entitlement version、idempotency key 与原因，不接受页面输入 school id。
- 在 `ops.quotas.manage` 下，服务授权行展示“赠送当前学校额度”，用当前 entitlement version 和 supply lot 的 provider/pool/unit 组装 `/quota-grants` payload；quota grant 行展示“调整当前额度/撤销当前额度/过期当前额度”，分别调用 PATCH `/quota-grants/{grant_id}`、POST `/revoke`、POST `/expire`，版本来自安全 DTO。
- 前端仍不展示 Secret、成本或学校账号；无 manage 权限时既有只读测试继续断言不出现授权/调整类按钮。
- 红绿验证：先新增失败测试 `npm test --prefix extensions/enterprise/frontends -- --run tests/formal-management-gates.test.tsx -t "OMS 正式入口接入学校服务授权和额度"` → 1 failed（旧 UI 没有服务授权/额度写按钮）；修复后同命令 → **1 passed**。
- 回归验证：`npm test --prefix extensions/enterprise/frontends -- --run tests/formal-management-gates.test.tsx` → **44 passed**；`npm run typecheck:oms --prefix extensions/enterprise/frontends` → **通过**。
- 仍未完成：供给补充、核对动作、真实账号按钮级验收、真实跨学校负例、完整 E2E 和 test-cn 综合验收。

### 2026-09-30 正式 OMS 供给批次撤销写入口与后端 API

- 后端新增正式 OMS 供给批次写 API：`POST /api/v1/oms/supply/lots` 注册供给批次、`POST /api/v1/oms/supply/lots/{lot_id}/revoke` 撤销供给批次，均调用 `_authorize_oms_request(..., "ops.supply.manage")`，因此需要 DeepTutor Enterprise 本地 `ops.supply.manage` 的 `platform` 范围授权；school-scope operator 不能冒充平台供给。
- `/api/v1/oms/supply` 的供给批次安全 DTO 补充 `lot_id` 与 `version`，供正式 UI 执行版本化撤销；返回体不回显 `evidence_ref`、Secret 或采购明文。
- 正式 `/oms/supply` 在 `ops.supply.manage` 下展示“撤销供给批次”，payload 只使用安全 DTO 的 `lot_id`、`version` 与固定审计原因。供给“补充/注册”按钮暂不在前端开放，因为当前正式 UI 没有真实采购证据输入/合同，不能伪造 `evidence_ref` 作为生产路径。
- 红绿验证：先调整/运行失败测试 `npm test --prefix extensions/enterprise/frontends -- --run tests/formal-management-gates.test.tsx -t "OMS 正式入口接入学校服务授权和额度"` → **1 failed**（缺少“撤销供给批次”按钮）；实现后同命令 → **1 passed**。
- 后端验证：`.venv/bin/python -m pytest extensions/enterprise/tests/test_application.py -k "oms_permissions_summary_allows_school_scoped_operator_without_platform_grant or oms_school_entitlement_and_quota_commands_are_authorized_and_audited or enterprise_management_route_allowlist_is_narrow" -q` → **3 passed, 52 deselected, 1 warning**。覆盖 platform supply manager 注册/撤销成功、`evidence_ref` 不泄露、审计 `supply.register/supply.revoke`、school-scope operator 调用平台供给注册 403，以及企业管理 route allowlist。
- 仍未完成：正式 UI 供给补充输入/采购证据合同、核对动作、真实账号按钮级验收、真实跨学校负例、完整 E2E 和 test-cn 综合验收。

### 2026-09-30 本地可执行全量验证与迁移 catalog 修正

- 在供给批次 API/UI 切片后执行当前本地可运行的完整验证，发现 `extensions/enterprise/tests/test_persistence.py` 的迁移期望清单未包含已存在的 `eduplus2/0014_actor_identity_context.sql`，导致所有 `migrated()` 相关持久化测试同源失败；修复为仅补齐期望清单，不改迁移或业务逻辑。
- 验证命令：
  - `npm test --prefix extensions/enterprise/frontends` → **27 files / 297 tests passed**。
  - `npm run typecheck:oms --prefix extensions/enterprise/frontends && npm run typecheck:tms --prefix extensions/enterprise/frontends && npm run build:oms --prefix extensions/enterprise/frontends && npm run build:tms --prefix extensions/enterprise/frontends` → **通过**。
  - `npm run lint --prefix extensions/enterprise/frontends` → **通过**。
  - `.venv/bin/python -m pytest extensions/enterprise/tests/test_persistence.py -q` → **42 passed**。
  - `.venv/bin/python -m pytest extensions/enterprise/tests -q` → **803 passed, 3 skipped, 2 warnings**。
  - `openspec validate add-c1-c2-oms-operator-interface --strict` 与 `openspec validate add-enterprise-management-authorization --strict` → **valid**。
  - `git diff --check` → **通过**；`git merge-tree $(git merge-base HEAD upstream/main) HEAD upstream/main` → 未发现冲突标记，未执行 merge/rebase/reset。
- 任务影响：新增勾选 **4.2.1**。父任务 **4.1/4.2/5.1** 仍不关闭；真实部署、真实 API 无 mock 浏览器 E2E、真实角色矩阵/跨学校负例和 test-cn 综合验收仍待完成。
