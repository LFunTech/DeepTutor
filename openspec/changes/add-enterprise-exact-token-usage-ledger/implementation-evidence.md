# 执行证据

## 2026-09-28 任务 1.1 attempt 边界盘点

- 新增 `attempt-boundary-matrix.md`，覆盖 LLM/task/embedding、search/web fetch、TTS/STT、image/video、解析/OCR、LightRAG、工具/外部 Agent、本地 cache/本地计算的真实发出边界、原生单位、usage/证据来源、可信硬上界、重试/流/异步/取消语义和当前开放判断。
- 与 `add-enterprise-all-service-provider-settings/service-provider-settings-matrix.md` 对齐，明确 provider descriptor 不等于可计费调用可用；无可信硬上界、无 adapter usage 合同、无法核验远端结果时保持 `unsupported` 或 `needs_reconciliation`，不得用本地估算按零/免费结算。
- 此任务仅完成枚举与门禁固定；CallContext/attempt 包装、PG 迁移、并发预留、adapter 白名单、聚合 API 和真实全入口样本仍未完成。

## 2026-09-28 验证

- OpenSpec change-scoped 与全量 strict validation 通过（全量 **30 passed、0 failed**）。
- attempt 边界矩阵是设计/盘点证据；企业后端全量 **761 passed、3 skipped** 证明既有 OMS ledger/attempt 测试未被破坏，但不替代后续 CallContext/adapter 接入任务。

## 2026-09-28 任务 1.2/1.3：CallContext 包装与 OMS attempt PG 总账基线

完成任务：1.2、1.3。

实现内容：

- 新增 `deeptutor_enterprise.oms.call_context`，在 Enterprise 扩展内定义可信 `UsageCallContext` → `AttemptRequest` 转换层，不让 core 直接依赖余额、供给或 OMS 总账逻辑。
  - 一个 `operation_id` 可生成多个可计费 `attempt_id`，支持重试/多次 provider 发出；
  - `safe_request_hash()` 仅接受安全元数据并拒绝 `prompt/messages/answer/content/attachment(s)` 等私有正文，确保账本 fingerprint 不保存提示词、回答或附件内容；
  - 通用 core 后续若需 hook，只需传递无正文的服务、主体、配置与 caller-owned operation id。
- 复核并以现有 OMS PG 版本化迁移作为唯一企业总账基线：`usage_attempts`、`attempt_allocations`、`attempt_evidence_events`、`grant_commitments`、`supply_lots`、`quota_grants` 与审计表覆盖预留、attempt、grant/lot 双维分摊、dispatch/unknown/provider usage/overage/reconciliation 证据、唯一键、RLS、索引和状态事实。
- 既有 `0017_relocate_database_business_rules.sql` 已以前向迁移退役 OMS 旧数据库函数/触发器和 enum-like CHECK；最终业务值校验由 `oms.value_validation` 与 `OmsAttemptLedger` 应用层事务承担。
- `OmsAttemptLedger` 已验证：发出前预留、赠送优先、跨 grant/lot 稳定分摊、同 operation 多 attempt、重复回放 fingerprint、防双扣、未知远端保留预留、provider usage 幂等、超预留进入 `reconcile_required`、释放/撤销/过期与供应不变量。

验证：

- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_oms_call_context.py --tb=short` → 2 passed。
- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/oms/call_context.py extensions/enterprise/tests/test_oms_call_context.py` → passed。
- 迁移/attempt ledger 的既有回归已在 OMS 业务 change 中反复执行；本轮全量回归前将继续跑 `test_oms_ledger_migration.py` 与 `test_oms_attempt_ledger.py` 确认没有被 0019 迁移和治理 API 破坏。

限制：

- 1.2/1.3 完成的是企业扩展边界和 PG 总账基础；尚未把所有 CLI/HTTP/WS/SDK/后台/Agent 真实发出路径接入预留/结算，因此 2.1–3.2 不因此完成。
- 对没有可信硬上界或 usage 合同的 provider，正式准入仍应 fail closed；缺项清单仍以 1.1 矩阵为准。

补充验证：`PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_oms_call_context.py extensions/enterprise/tests/test_oms_ledger_migration.py extensions/enterprise/tests/test_oms_attempt_ledger.py --tb=short` → 41 passed。

## 2026-09-28 任务 2.4：OMS/TMS 分级用量聚合与分页 API

完成任务：2.4。

实现内容：

- 增强 `deeptutor_enterprise.oms.governance.usage_projection()`：OMS 学校用量 API 支持 `service_id/provider_id/model_id/unit_code/status/subject_id/limit/offset` 白名单过滤、按 service/unit/status 聚合，以及 attempt 级分页明细。
- OMS 明细返回 attempt/operation、service/unit、provider/model、subject/user/app、状态 descriptor、reserved/settled 单位和时间；不返回 `evidence`、`provider_request_id`、prompt、回答、附件或成本。
- TMS `GET /api/v1/tms/quotas` 增加当前学校只读 `usage_page` 与 `usage_details`，支持 `service_id/unit_code/status/subject_id/limit/offset`；刻意不返回 provider/model/成本/供给/跨学校字段。
- 保持 `Cache-Control: no-store` 与现有当前学校 TMS 身份/`tenant.*` 授权检查；OMS 仍要求 `ops.usage.read` 的 school-scope grant。

验证：

- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_application.py::test_oms_governance_read_api_filters_by_local_school_grants_and_descriptors extensions/enterprise/tests/test_webhook_authority.py::test_tms_quota_summary_is_current_school_read_only_and_redacted --tb=short` → 2 passed。
- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/ruff check extensions/enterprise/src/deeptutor_enterprise/oms/governance.py extensions/enterprise/src/deeptutor_enterprise/api/application.py extensions/enterprise/tests/test_application.py extensions/enterprise/tests/test_webhook_authority.py` → passed。

限制：

- 2.4 只完成分级查询 API；全入口真实 adapter 发出、准入预留、供应商 usage 核对、更正和崩溃/重放演练仍属 2.1–2.3 与 3.x。

## 2026-09-28 任务 2.1/2.2：预留/准入/幂等结算应用层实现

完成任务：2.1、2.2。

实现与既有证据：

- `deeptutor_enterprise.oms.attempts.OmsAttemptLedger` 已在应用层实现发出前同事务准入与预留：
  - 校验服务定义、租户服务 entitlement、provider/pool/unit 供给兼容性、有效 grant、硬上界和可用额度；
  - 按赠送优先、grant/lot 稳定排序分摊预留，更新 supply lot、grant commitment、usage attempt 与 allocations；
  - 同一 operation 可有多个可计费 attempt；相同 attempt/请求 hash 的重复调用幂等返回；不同 fingerprint、防双扣和跨租户归属由主键/RLS/应用校验共同约束；
  - dispatch、remote_unknown、provider_usage、release、overage/reconcile_required 均通过只追加 evidence 事件记录，不保存 prompt/回答/附件。
- `test_oms_attempt_ledger.py` 覆盖：额度不足不改变学校 lifecycle、gift-first 分摊、未知远端保留预留、provider usage 幂等、已发出 attempt 不能释放、超 usage 进入核对、并发 reservation 不超额、同 operation 多次可计费 attempt、缺失 allocation fail closed、entitlement 后续撤销不破坏既有幂等、grant revoke/expire 只释放未使用承诺且保留 inflight/unknown。
- `test_oms_call_context.py` 覆盖 CallContext 不保存私有正文并能为同 operation 生成不同 billable attempt。

验证：

- `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest -c extensions/enterprise/pytest.ini -q extensions/enterprise/tests/test_oms_call_context.py extensions/enterprise/tests/test_oms_ledger_migration.py extensions/enterprise/tests/test_oms_attempt_ledger.py --tb=short` → 41 passed。
- 本轮新增 Provider/TMS/usage API 后，会在最终回归再次运行上述 ledger 测试以确认没有破坏事务不变量。

限制：

- 2.1/2.2 完成的是 OMS 总账和预留准入服务；真实 CLI/HTTP/WS/SDK/后台/Agent adapter 尚未全部调用该服务，因此全入口验收仍归 3.1/3.2 与 OMS 业务 7.4/7.5。
- request/task ID 对账、pending 告警、供应商账单核对与只追加更正仍属 2.3，未因本任务完成。
