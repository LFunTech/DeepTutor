# 执行证据

## 2026-09-28 TMS 当前学校用量只读与服务访问 grant API 切片

本节是后续任务证据，不单独勾选完整 TMS 任务：

- `GET /api/v1/tms/quotas` 已在当前学校只读配额/用量 DTO 中增加分页 `usage_details`，不返回 provider/model/成本/供给/跨学校字段。
- 新增正式 TMS HTTP API：
  - `GET /api/v1/tms/service-access`：当前学校服务访问资格列表；
  - `POST /api/v1/tms/service-access`：授予成员/应用/服务主体访问资格；
  - `POST /api/v1/tms/service-access/{grant_id}/revoke`：撤销访问资格。
- API 使用已验签 EduPlus2 用户 JWT → DeepTutor TMS `ManagementIdentity`，再由本产品 `tenant.tms.access` / `tenant.access.manage` 事实授权；不信任 URL/body/header tenant 覆盖。
- `ServiceAccessLedger` 已确认 grant/revoke 不写 `quota_grants`、`grant_commitments`、`usage_attempts` 或 `attempt_allocations`，仅表达当前学校访问资格，不代表额度或供应商调用。
- 修正写事务内 lifecycle 投影复核：对 EduPlus2 webhook 投影只做只读查询，不加 `FOR SHARE`；写事务仍锁本地 school binding、tenant 与 management assignment。该调整避免单账号 + RLS 下首管激活后立即写入 TMS grant 被误拒，同时不扩大到外部权限系统。

验证：

- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_webhook_authority.py::test_tms_quota_summary_is_current_school_read_only_and_redacted extensions/enterprise/tests/test_application.py::test_enterprise_management_route_allowlist_is_narrow --tb=short` → 2 passed。
- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/src/deeptutor_enterprise/management/authorization.py extensions/enterprise/src/deeptutor_enterprise/management/actor_activation.py extensions/enterprise/src/deeptutor_enterprise/oms/service_access.py extensions/enterprise/tests/test_webhook_authority.py extensions/enterprise/tests/test_application.py` → passed。

仍未完成：

- 成员目录、应用注册/注销、资源/KB owner-grant 管理、TMS 独立前端正式入口、完整 G2 联调仍未交付，因此任务 5.2/5.4/5.6 等不得提前勾选。

## 2026-09-30 正式 TMS 入口、服务访问与只读投影同步证据

本节把已由 `add-enterprise-management-authorization` 与正式前端测试覆盖的 TMS 本地成果同步到本 change；父任务仍不因真实目录/双学校/test-cn 合同缺失而关闭。

- 正式 TMS 独立入口：
  - `/tms/{schoolCode}` 渲染 `TmsFormalApp`，页面标题/副标题使用“学校智能体管理后台”。
  - 根 `/tms` 服务端 404；`/tms/prototype*` 仅 development 可用，生产环境服务端 `notFound()`。
  - 正式入口读取 `/api/v1/tms/me/permissions` 的可信 `school_code`，与 URL code 不一致或缺失时失败关闭，不继续读取目录/成员/审批/审计/Skill 等当前学校 DTO。
- 正式 TMS DTO/UI：
  - 读取当前学校 `school-bootstrap/status`、`directory/users`、`members`、`approvals`、`authz-audit`、`skills`、`quotas`、`service-access` 安全 DTO。
  - 接入低风险角色授予、assignment 撤权、已批准审批 apply、服务访问 grant/revoke；服务访问 payload 绑定当前学校成员、entitlement version 与 grant version，不携带 quota 数量、unit、OMS 成本、Provider Secret 或跨校字段。
  - 额度/用量仅展示当前学校只读投影；无新增、赠送、充值、调整、撤销、核销或成本写入口。
  - 成员、应用、服务、额度、知识、用量、事件导航与列表→详情抽屉均按原型结构接入；知识库和应用正式 DTO 未启用时显示安全空态，不回退合成目录或私有正文。
- 验证：
  - `npm test --prefix extensions/enterprise/frontends` → **27 files / 297 tests passed**（含正式 TMS 学校码失败关闭、目录状态、服务访问 grant/revoke、额度/用量只读、角色目录、审批详情与窄屏/键盘可访问性切片）。
  - `npm run typecheck:tms --prefix extensions/enterprise/frontends` 与 `npm run build:tms --prefix extensions/enterprise/frontends` → **通过**。
  - `npm run lint --prefix extensions/enterprise/frontends` → **通过**。
  - `.venv/bin/python -m pytest extensions/enterprise/tests -q` → **803 passed, 3 skipped, 2 warnings**。
  - `openspec validate add-enterprise-tms-business-logic --strict` → 见本轮验证记录。

任务影响：新增勾选 **3.1.1、3.2.1、3.3.1、4.4.1、5.2.1、5.4.1、5.5.1、6.2.1**。父任务 **2.x、4.2/4.3、5.3/5.6/5.7、6.1、7.x、8.1** 仍未完成；真实学校目录策略合同、client/app 注册注销、KB/文档真实 owner-grant、tenant Skill ZIP/Hub、双学校真实登录和 G2/G3 联合验收仍待后续实现/外部证据。
