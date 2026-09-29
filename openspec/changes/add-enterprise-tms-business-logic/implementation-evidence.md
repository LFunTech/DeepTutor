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
