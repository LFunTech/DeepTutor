# Provider attempt 边界与用量合同矩阵（2026-09-28）

> 本矩阵完成任务 1.1 的边界枚举：列出各服务的真实发出点、原生单位、usage 来源、可信硬上界及 retry/stream/async/cancel 处理原则。它不表示全入口已接入预留/结算；正式 CallContext、PG 迁移和 adapter 包装仍归后续任务。

| 服务族 | 真实发出边界 | 原生单位 | usage/证据来源 | 可信硬上界 | 重试/流/异步/取消 | 当前开放判断 |
| --- | --- | --- | --- | --- | --- | --- |
| LLM 对话 | chat/model provider adapter；HTTP/WS/CLI/SDK/Agent 子调用均可能触发 | input/output/total/cache/reasoning tokens | provider response usage、request id、模型/profile 版本 | max_tokens、模型上下文与本地估算中的保守上界；无上界拒绝可计费测试 | 每次可能计费 retry 独立 attempt；流中断保持 pending，重复 final usage 幂等 | 可建账；未完成全入口 hook 前不开放统一扣量 |
| task 模型 | 后台/Agent/异步任务 adapter，未配置时可能回退 LLM | tokens 或 provider 原生单位 | provider usage/task id | 同 LLM；回退按实际 provider/service 记录 | 同 operation 可有多 attempt；不得双扣顶层 Agent | 可建账；需 runtime wrapper |
| embedding | embedding adapter、KB 索引/检索构建 | tokens/向量请求/维度相关单位 | provider usage 或固定请求合同 | 文本长度、batch size 与 provider 上限；无合同仅 pending/unsupported | batch 局部失败按 attempt 拆分或保持 pending | 条件支持，需 adapter 白名单 |
| search / web fetch | web_search/web_fetch tool 与搜索 provider | request 次数、credits 或 provider usage | provider request id、HTTP status、账单回执 | 每次请求固定 1 或 provider credits 上界 | 429/网络未知不按零结算；本地 cache hit 不新增外部 attempt | 支持固定请求上界 provider；其他 unsupported |
| TTS | TTS adapter | 字符/秒/credits | provider usage 或输入字符固定合同 | 待合成字符数；provider 明确免费预检除外 | 生成失败但远端未知保持 pending | 条件支持 |
| STT | STT adapter | 秒/分钟/credits | provider response/账单、音频时长 | 音频时长与 provider rate 上界 | 上传后取消未知保持 pending | 条件支持 |
| imagegen | image generation adapter | 张/任务/credits | task id、completion receipt | 请求张数/尺寸档位固定合同 | 异步 submit 成功后 polling 失败保持 pending | 条件支持 |
| videogen | video generation adapter | 任务/秒/credits | task id、账单/完成回执 | duration/resolution 上界；无固定价格拒绝硬额度 | 下载/轮询失败保持 pending，不释放预留 | 条件支持但默认需核对 |
| 文档解析/OCR | document parser / OCR worker | 页、任务、credits | parser manifest、OCR provider receipt | 页数/文件 manifest；无法解析页数前不可硬预留 | cache hit 不新增外部 attempt；远端任务未知 pending | 条件支持 |
| LightRAG | LightRAG API adapter（检索/索引），不直连内部 PG/图 | request、tokens 或服务遥测单位 | LightRAG operation id、service telemetry | 仅受控 API 给出硬上界时支持；内部图操作不可估算 | workspace pipeline 不等同单文档取消；未知保留 pending | 多数先 unsupported/pending |
| 工具/外部 Agent | 各工具/Agent adapter | 原生请求/credits/子服务单位 | 子服务 usage 与可核验账单 | 每个子调用单独硬上界；顶层 Agent 不重复扣 | Agent 子调用按 attempt 继承 operation_id，防双扣 | 需逐工具白名单 |
| 本地 cache / 本地计算 | 不触发外部 provider | 无 | 本地审计 | 不预留 | 不生成可计费 attempt | 非计费 |

## 入口覆盖边界

- CLI、HTTP、WS、SDK、后台 job 和 Agent 子调用最终都必须传入可信 `operation_id`、主体、school、service、configuration version 和 request id；请求 body/header 不能自带 tenant/user 覆盖。
- 在全入口 wrapper 未完成前，正式服务准入应 fail closed 或只记录 unsupported，不把局部 API 账本当作全入口完成。
- OMS/TMS 查询只读 DTO 必须来自同一 ledger，TMS 不含供应商成本、采购或跨学校字段。
