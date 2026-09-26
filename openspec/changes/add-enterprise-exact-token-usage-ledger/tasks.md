> **实施已获批准（2026-09-26）**：本版替换 Token-only/费用下游目标，依托 OMS 唯一供给—授予—预留—用量总账；用户已单独批准按现版实施，以下仍未完成。

## U0 边界清单与迁移
- [ ] 1.1 枚举 LLM/task/embedding、search/web fetch、TTS/STT、image/video、解析/OCR、LightRAG、工具/外部 Agent 的真实发出边界、原生单位、合同/usage 来源、可信硬上界、重试/流/异步/取消和 CLI、HTTP/WS、SDK、后台入口；缺项标 unsupported。
- [ ] 1.2 设计可信 CallContext/attempt 包装与 OMS 唯一企业 PG 总账，先试企业扩展适配；如需通用 hook，逐处说明 upstream 合并风险及本地回归，不让核心依赖企业余额逻辑。
- [ ] 1.3 企业扩展 PG 版本化 migration：预留、attempt、授予/批次双维分摊、原始安全证据、更正、唯一键/RLS/索引/状态；合成数据 plan/apply/verify/重复运行/drift/回退，不自动猜测历史消耗。
## U1 采集与对账
- [ ] 2.1 测试先行：并发超授予/预留、赠送优先、同 operation 多次可计费 attempt、跨多笔 grant/lot、重复/迟到回执、流中断、取消未知、异步视频下载失败、解析 cache hit、Agent 防双扣与跨租户归属。
- [ ] 2.2 发出前同事务校验主体/服务授权、配置 ready、兼容供给/有效 grant/硬上界并转移承诺至预留；adapter 白名单规范化可信原生 usage，幂等结算，不存 prompt/回答/附件。
- [ ] 2.3 实现 request/task ID/可核验账单对账、pending 告警及只追加更正；不可证明上界或用量的 provider 准入 fail closed。
- [ ] 2.4 OMS/TMS 分级 API 按 tenant/主体/时间/service/provider/model/单位聚合与明细分页，已结算与待核对分列，TMS 无成本/跨租户字段。
## U2 验收
- [ ] 3.1 合成双租户 PG 集成、全入口各类服务真实 adapter 调用样本、供应商证据与 ledger 逐笔比对、崩溃/重放/未知远端演练。
- [ ] 3.2 隐私/成本泄露扫描、性能索引/迁移验证、session owner/审计关联、upstream review 与 OpenSpec strict validation；逐服务记录缺合同/usage/上界未开放项。
