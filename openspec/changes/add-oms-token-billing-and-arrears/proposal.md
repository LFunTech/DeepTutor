# OMS Token 计费与 EduPlus2 欠费协同

> **退役目标已获用户批准（2026-09-26）**：本提案及下列正文仅保留历史，不得按旧 tasks 实施、同步其冲突 spec 或归档。现行替代为已批准的 `add-enterprise-oms-business-logic`（服务供给、统一充值/赠送额度与真实消耗）；退役决议见 `replacement-decision-draft-2026-09-26.md`。

## Why
DeepTutor 当前只有可估算的 turn 级 `cost_summary`，没有可审计的逐调用计费事实、历史单价或跨租户欠费处理。OMS 需要按租户和用户精确统计 Token 费用；欠费只应限制模型使用，不能让用户失去登录、管理和历史查询能力。

## What Changes
- 仅对 `enterprise-exact-token-usage` 已核算且可信的 token 调用按有效期单价计费；租户每百万 Token 单价按币种和版本保存，支持租户、用户、调用明细及期间汇总。
- 供应商成本价按 provider/model/有效期独立保存、计算和拆分，仅进入获授权 OMS 成本视图；无价格或无用量时显示待核算，不把零当作事实。
- OMS 可记录欠费、处置和向 EduPlus2 发起**模型使用限制/恢复**请求；独立模型资格只由签名 webhook 确认。限制只在实际模型 provider dispatch 生效，登录、管理、历史查询、非模型操作继续可用；超时、拒绝、重放及对账异常有明确状态和审计。
- **BREAKING（相对旧 OMS 草案）**：移除“OMS 直接设置租户停机/恢复”及“欠费停用整个租户”的设计。账单、在线支付、发票、税、阶梯价及预充值不在本 change。

## Capabilities
### New Capabilities
- `enterprise-oms-token-billing`: 可追溯 Token 价格、费用、供应商成本及欠费协同。
### Modified Capabilities
无；若既有正式财务/租户资格 spec 产生冲突，实施前补明确 delta。

## Impact
依赖 `add-enterprise-exact-token-usage-ledger`、`add-b2-eduplus2-tenant-lifecycle-webhook` 的独立模型资格事件和平台 OMS 权限。DeepTutor 企业扩展承载 PG 价格版本、核算结果、欠费请求/outbox、API 与审计；core 只保留通用 usage/模型调用准入 seam。EduPlus2 发送/接收协议需双方确认；若无模型资格请求接口，只能记录待处理欠费，不能宣称自动限制模型。需要 DB migration；OpenFGA/Keycloak 仅在其能力模型实际改动时迁移。
