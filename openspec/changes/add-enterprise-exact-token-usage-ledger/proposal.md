# DeepTutor 可信逐 attempt 服务用量与核对总账

> **实施已获批准（2026-09-26）**：本版替换旧 Token-only/费用下游目标，用户已单独批准按现版实施。供给、授予、预留、用量与更正以 `add-enterprise-oms-business-logic` 为**唯一**总账，不另建平行事实。

## Why
现有 `UsageTracker` 可从响应取得 usage，但也会字符估算，最终只附 turn 级 `cost_summary`；非 Token 服务又有 credits、时长、张数、任务/页数等异构单位。它们不能构成可硬准入、可追溯的租户额度消耗。需要以真实供应商 attempt 和可核验用量证据建立持久总账。

## What Changes
- 在最窄的通用 provider 调用边界传播可信 CallContext，企业扩展 PG 总账保存 `operation_id` 下每次可能计费的 `attempt_id`、主体/tenant/service/provider/model/配置版本、预留、供应商证据、原生单位和核对状态。
- 发出前在同一事务校验授权、有效赠送/充值 grant、兼容供给与可信硬上界，把未用承诺转移为在途预留；不能预留则拒新调用。发出后超时/流中断/取消/异步远端未知保留预留待核对，不按零释放。
- 仅以 provider usage、可核验账单或明确固定计费合同结算 Token/非 Token 原生单位；同一 attempt 重复回执幂等，不同可计费重试分别结算，一次 attempt 可跨多笔 grant/lot。Agent 顶层不重复扣子服务。
- 覆盖 CLI、HTTP/WS、SDK、后台、Agent 子调用，以及搜索、语音、图像、视频、解析/OCR、LightRAG 和工具的真实外部调用；缺用量证据/硬上界的服务不得标为可硬配额放行。原始安全证据不可覆盖，更正只追加审计；不存完整 prompt/回答/附件。
- **BREAKING**：不再依赖旧 OMS Token billing/欠费 change，不推出租户售价、费用、账单或欠费资格；供应商成本仅由 OMS 有证据的专有规则归集。

## Capabilities
### New Capabilities
- `enterprise-exact-token-usage`: 逐 attempt 可信 Token/非 Token 原生用量、预留与核对契约（保留历史 capability ID，语义已扩展）。
### Modified Capabilities
无；若改变正式 session/turn spec 的持久协议，实施前补 delta。

## Impact
通用 provider 上下文/attempt seam（仅经 upstream-neutral 审阅）、企业 PG store/版本化迁移、OMS/TMS 分级报表 API 与可观测性。依赖可信主体、服务供给/额度和配置 ready；旧 billing proposal 不再是下游。无可信上界或 usage/对账来源时不开放硬额度，不声称已结算。
