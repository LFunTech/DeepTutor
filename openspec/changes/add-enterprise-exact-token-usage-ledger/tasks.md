> **冻结/替代状态（2026-09-30）**：本 proposal 不再作为当前 OMS 执行主线；已完成项仅作为 `deliver-oms-test-cn-management-v1` 的证据来源，未完成项除非在新 proposal 中列明，否则暂停推进。不得把本 proposal 的未完成任务当作已交付或直接 archive。

> **实施中；任务 1.1、1.2、1.3、2.1、2.2、2.4 已完成**：本版替换 Token-only/费用下游目标，依托 OMS 唯一供给—授予—预留—用量总账；用户已单独批准按现版实施。

> **职责边界（非勾选项）**：本 change 不再创建价格、费用、账单或欠费模型；只负责真实外部调用的 CallContext、预留、attempt、可信 usage/原生单位、待核对和只追加更正。OMS 业务 change 负责供给/授权/额度写入，Provider 设置 change 负责配置 ready，TMS 只读当前学校安全投影；无可信硬上界或对账来源的服务必须 fail closed 或保持 unsupported。

## U0 边界清单与迁移
- [x] 1.1 枚举 LLM/task/embedding、search/web fetch、TTS/STT、image/video、解析/OCR、LightRAG、工具/外部 Agent 的真实发出边界、原生单位、合同/usage 来源、可信硬上界、重试/流/异步/取消和 CLI、HTTP/WS、SDK、后台入口；缺项标 unsupported。
- [x] 1.2 设计可信 CallContext/attempt 包装与 OMS 唯一企业 PG 总账，先试企业扩展适配；如需通用 hook，逐处说明 upstream 合并风险及本地回归，不让核心依赖企业余额逻辑。
- [x] 1.3 企业扩展 PG 版本化 migration：预留、attempt、授予/批次双维分摊、原始安全证据、更正、唯一键/RLS/索引/状态；合成数据 plan/apply/verify/重复运行/drift/回退，不自动猜测历史消耗。
## U1 采集与对账
- [x] 2.1 测试先行：并发超授予/预留、赠送优先、同 operation 多次可计费 attempt、跨多笔 grant/lot、重复/迟到回执、流中断、取消未知、异步视频下载失败、解析 cache hit、Agent 防双扣与跨租户归属。见 `implementation-evidence.md` §2026-09-28 任务 2.1/2.2。
- [x] 2.2 发出前同事务校验主体/服务授权、配置 ready、兼容供给/有效 grant/硬上界并转移承诺至预留；adapter 白名单规范化可信原生 usage，幂等结算，不存 prompt/回答/附件。见 `implementation-evidence.md` §2026-09-28 任务 2.1/2.2。
- [ ] 2.3 实现 request/task ID/可核验账单对账、pending 告警及只追加更正；不可证明上界或用量的 provider 准入 fail closed。
  - [x] 2.3.1 已实现 provider request/task ID 回填与幂等对账切片：dispatch 可记录 provider request ID，OMS 受控对账 API 可按 provider/account/request ID 找回原 attempt 并只结算一次；未知 receipt 失败关闭且不释放预留。真实账单批处理、pending 告警、逐 provider adapter 样本仍在父任务。
- [x] 2.4 OMS/TMS 分级 API 按 tenant/主体/时间/service/provider/model/单位聚合与明细分页，已结算与待核对分列，TMS 无成本/跨租户字段。见 `implementation-evidence.md` §2026-09-28 任务 2.4。
## U2 验收
- [ ] 3.1 合成双租户 PG 集成、全入口各类服务真实 adapter 调用样本、供应商证据与 ledger 逐笔比对、崩溃/重放/未知远端演练。
  - [x] 3.1.1 已完成合成 PG attempt ledger 集成与未知远端演练：预留/赠送优先/多 attempt/重复回放/迟到 usage/remote_unknown/overage/reconcile_required/并发不超额等本地总账不变量通过；真实 adapter 调用样本与供应商证据逐笔比对仍归父任务。
  - [x] 3.1.2 已完成企业扩展内合成 provider adapter runner 样本：runner 在 provider 调用前预留并记录 dispatch intent，成功 receipt 按原 attempt 结算，发出后异常标记 `remote_unknown` 且保留预留；真实 CLI/HTTP/WS/SDK/后台/Agent adapter 接线仍归父任务。
- [ ] 3.2 隐私/成本泄露扫描、性能索引/迁移验证、session owner/审计关联、upstream review 与 OpenSpec strict validation；逐服务记录缺合同/usage/上界未开放项。
  - [x] 3.2.1 已完成当前本地隐私/验证回归：CallContext/attempt 测试拒绝 prompt/answer/attachment 入账，OMS/TMS usage DTO 不返回成本/供应商证据/私有正文；企业后端全量、前端全量、迁移 catalog、OpenSpec strict validation、`git diff --check` 与只读 upstream merge-tree smoke 均通过。
