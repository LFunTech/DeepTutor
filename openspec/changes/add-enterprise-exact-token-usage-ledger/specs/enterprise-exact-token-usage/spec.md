## Purpose
以真实供应商 attempt、可信原生单位和硬上界预留建立可追溯、幂等、可对账的 OMS 服务用量唯一总账。

## ADDED Requirements
### Requirement: 每次可能计费的 provider attempt 必须有可信归属与预留
系统 SHALL 在发出前以唯一 `attempt_id` 登记可信 tenant、主体类型及 user/app/job owner、session/turn/`operation_id`、service、provider/model、配置版本、原生单位、时间和固定 grant/供给分摊，并在同一 PG 事务校验授权/ready/兼容供给/硬上界、把未用承诺转为预留；不能预留 MUST 拒绝新调用。重试分别记录，所有 CLI、HTTP/WS、SDK、后台及 Agent 子调用入口一致。
#### Scenario: 同 turn 两次调用
- **WHEN** Agent 在一轮中实际调用目标 LLM 两次
- **THEN** 保存两笔可追溯的 attempt 与独立预留，按真实用量分别结算，Agent 顶层不重复扣

#### Scenario: 并发争抢同一批次
- **WHEN** 有限批次剩余 30 单位而两个请求各需 20 单位上界
- **THEN** 至多一个请求可预留，另一请求不得发出供应商调用或留下半笔账务

### Requirement: 只有可信原生 usage 才能标记已核算
系统 SHALL 仅凭供应商响应、可核验账单或明确固定计费合同结算 Token/非 Token 原生单位；缺失、异常、中断、异步远端未知 MUST 保留预留并标为待核对，不得用字符估算、输出 bytes、模型 tokenizer 估计或零消耗代替。无可信硬上界的服务不得放行依赖硬额度的新调用。
#### Scenario: 流中断
- **WHEN** 输出已流出而最终 usage 未收到
- **THEN** 该 attempt 保留预留并待核对，已结算用量不增加，不能把预留直接释放
#### Scenario: 可对账补录
- **WHEN** 可信供应商记录按 request ID 提供真实 usage
- **THEN** 在原 attempt 上幂等结算并保留不可覆盖原始来源、操作者、时间及追加更正

#### Scenario: 视频提交后下载失败
- **WHEN** 异步视频已获供应商 task ID 但轮询或下载失败
- **THEN** attempt 保留远端未知/待核对状态，不按本地空文件推断供应商零费用

### Requirement: 总账必须防重复、隔离和泄露
系统 SHALL 保证 `(tenant_id,attempt_id)` 唯一，同一供应商回执重复不重复计量；一个 operation 下不同可计费 attempt 分别结算，一次 attempt 可跨多笔 grant/lot 且在每维只归集一次。按 tenant/主体/service/provider/单位/时间可查询已结算与待核对数，MUST NOT 保存或输出完整 prompt、回答、附件、JWT、Secret；TMS 只能读当前租户安全投影，成本只进 OMS 特权 API。
#### Scenario: 重复完成事件
- **WHEN** 相同 attempt 的最终 usage 被重复递交
- **THEN** 已结算用量及供给/授予消耗均不增加第二次
#### Scenario: 跨租户查询
- **WHEN** 租户用户查询其他租户明细
- **THEN** 后端拒绝且不泄露元数据

### Requirement: 非 Token 服务不得被虚构成 Token 消耗或免费调用
系统 SHALL 保留搜索 credits/请求数、语音时长或字符、图像张数、视频任务/时长、解析页数、LightRAG 检索/索引及外部工具等有证据的原生单位；调用次数仅在真实发出且合同证明时计入。无合同/用量/上界时标为不支持硬额度，不能按零或估算放行。
#### Scenario: 按时长计费的语音服务
- **WHEN** provider 仅返回秒数
- **THEN** 有可信上界与回执时按秒预留/结算，否则拒新硬额度调用，不生成虚假 Token、租户费用或欠费
