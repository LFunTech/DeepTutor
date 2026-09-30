# 交付 test-cn OMS 管理后台 v1

> **收敛提案（2026-09-30）**：本 change 接管当前 OMS 相关未完成 proposal 的执行主线，目标是在 test-cn 交付一版可用、可验收、可部署的“平台智能体运营后台（OMS）v1”。旧 proposal 中已完成的实现和验证作为证据来源；未完成项不再分散推进，除非本 change 明确纳入 v1。

## Why

当前 OMS 能力分散在授权、Provider 设置、OMS 业务、用量总账、前端界面、平台治理等多个 proposal 中，任务状态交叉且大量子项已经完成但父项未闭合，导致后续推进、验收和部署判断困难。为了快速交付可用 OMS，需要把“已经实现的能力”和“剩余必要验收”收敛到一个交付型 proposal。

## What Changes

- 建立唯一 OMS v1 执行主线：`deliver-oms-test-cn-management-v1`。
- 冻结当前 OMS 相关旧 proposal 的执行主线；旧 proposal 保留历史证据，不再作为每日推进入口。
- 将当前已完成的 OMS 正式入口、认证/授权、学校列表、模型与 Provider、资源状态、Skills、供给/额度、用量/任务、审计/成本和平台授权治理纳入 v1 验收范围。
- 只保留 v1 必需的剩余工作：本地真实域名 HTTPS 浏览器验收、test-cn admin 账号验收、必要 UI 缺口、部署和回归证据。
- 明确排除 TMS 完整后台、全供应商真实 adapter、HA/多执行者、学校目录搜索合同和完整多角色矩阵；这些后续以 v2/TMS/G/H 新 proposal 重订。

## Capabilities

### New Capabilities

- `enterprise-oms-test-cn-management-v1`：面向 test-cn 的 OMS v1 交付、验收和部署收敛能力。

### Superseded / Paused Sources

- OMS v1 接管并替代为当前主线：
  - `add-enterprise-management-authorization`
  - `add-enterprise-oms-business-logic`
  - `add-c1-c2-oms-operator-interface`
  - `add-b2-oms-platform-read-governance`
  - `add-enterprise-all-service-provider-settings`
  - `add-enterprise-exact-token-usage-ledger`
  - `add-c1-oms-operations-prototype`
  - `add-oms-token-billing-and-arrears`（旧费用/欠费方向继续退役）
- 暂停且不纳入 OMS v1 当前交付：
  - `add-enterprise-tms-business-logic`
  - `add-b2-tms-management-prototype`
  - `add-b1-b2-trusted-school-integration`
  - `add-m1-fixed-tenant-runtime-baseline`
  - `add-g1-woodpecker-k8s-release-baseline` 中非本次 OMS 部署必需的剩余项

## Impact

- 主要影响 OpenSpec 执行组织方式和 OMS 验收口径；不主动修改 EduPlus2 或外部系统。
- 后续 OMS 工作应优先更新本 change 的 tasks/evidence，而不是继续在旧横向 proposal 中推进。
- 已归档的完成 proposal 继续作为正式 spec 来源；未完成旧 proposal 不因冻结而视为完成或归档。
- 本地调试必须使用 `local-ssl` 验证 `https://deeptutor.lfun.pub/oms` 真实域名链路。
