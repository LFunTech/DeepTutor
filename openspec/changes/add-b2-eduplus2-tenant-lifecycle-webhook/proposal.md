# EduPlus2 租户生命周期 webhook 与 DeepTutor 租户级准入

> **重订已获单独批准（2026-09-26）**：本版移除独立欠费模型资格与欠费停模目标，只保留 EduPlus2 权威租户 lifecycle。用户批准按现版实施；发送端事件/对账契约仍须由 EduPlus2 确认，批准不等于已完成。

> **Webhook URL 联调顺序修订（2026-09-26）**：用户指出应先提供可验签的接收 URL，经 EduPlus2 控制台 Webhook URL demo 测试后再完成接入配置；测试 secret 已在本地忽略的 `.secrets/.test-secrets` 存放。发送端现行 demo 使用 `X-EduPlus-Mock: true` 和 `mock_` event ID，以 `timestamp.event.raw-body` 三段式 HMAC 签名。mock 仅验证可达性/验签，不是租户状态事件。真实事件的单调版本与对账仍待合同锁定，未完成前不得 2xx 确认或改变租户状态。

## Why
当前 DeepTutor 只有撤销 webhook 和固定租户状态检查；撤销处理器把任意 `tenant.*` 当撤销，不能安全处理开通/恢复。用户决定租户开停只由 EduPlus2 权威变更驱动，OMS 不得直接开停。

## What Changes
- 建立 EduPlus2→DeepTutor 明确的租户 `enabled|suspended|resumed` 生命周期事件契约：签名、事件 ID、租户绑定、单调来源版本、发生时间、原因和重放限制；未知事件拒绝，不凭 `reason=billing` 推断资格域。
- DeepTutor PG 持久化 inbox、外部资格状态/版本、同步异常和审计；拒绝过期版本/错误目标，保留独立本地恢复隔离，外部 active 不覆盖本地隔离。受控 EduPlus2 快照对账修复漏送。
- EduPlus2 租户暂停在登录、token exchange、HTTP/WS turn、下载授权及后台派发执行现有租户级准入；OMS 额度耗尽只拒**对应服务新调用**，不生成 `tenant.suspended`、不改变生命周期或注销会话。
- **BREAKING**：废止旧独立欠费模型资格事件/请求；OMS 不提供租户开停写接口。旧 `revocations` 行为保留给撤销，启用/恢复事件必须走明确分支，不能进入通用 `tenant.*` 撤销路径。

## Capabilities
### New Capabilities
- `enterprise-eduplus2-tenant-lifecycle`: 外部租户生命周期的安全同步与租户级准入（保留历史 capability ID，移除欠费模型资格）。
### Modified Capabilities
无；若实施改变既有正式联邦访问要求，再补相应 delta，不悄然覆盖。

## Impact
优先改 `extensions/enterprise/eduplus2/`、企业 API、PG migration 与测试；core 仅补经审阅的通用准入 seam。EduPlus2 发送端须提供签名事件/对账契约及必要迁移。依赖 B1 联邦访问和 B2 多租户绑定；无发送端版本/状态契约不得宣称验收完成。OMS 仅只读展示脱敏状态，不需要平台租户开停写权限。
