# 设计：供应商 attempt、硬上界预留与原生单位

一笔 ledger 对应一次**实际可能计费的 provider attempt**，不是一轮对话。`operation_id` 是逻辑动作，可关联多个 `attempt_id`；每次重试可能计费就新增 attempt 与独立预留。上下文只从可信用户/应用/后台主体、tenant、授权服务、session/turn/job 和配置版本传入，不信 prompt 或 header 中的任意 tenant/user。Provider adapter 返回供应商 request/task ID、原生 `unit_code`、白名单原始 usage、安全的来源与核对状态，不存私密文本。Token input/output/total/cache/reasoning 子项按供应商合同规范化，不重复相加；非 Token 保持 credits、秒/字符、张、任务、页数或经证明的真实请求数，不虚构 Token。

发出前的同一 PG 事务锁定兼容供给批次与按“赠送优先、同类有效期及稳定顺序”排列的 grant，校验服务/主体授权、配置 ready、可信保守硬上界、批次和 grant 的有效期与余额，将 `committed_unspent` **转移**为 `reserved_inflight` 并固定 attempt 分摊；网络调用不持事务。有限批次终身满足 `settled_lifetime + committed_unspent + reserved_inflight <= hard_ceiling`，预留不重复扣。无硬上界/不可兼容即拒新调用，不允无限放行。可信结算把预留转实际消耗，未使用部分只在原 grant 有效时归还；同一 attempt 重复回执幂等，不同 attempt 分别结算。供应商超上界是契约违规，停止该服务新调用并待人工核对。原始证据不可覆盖，更正只追加 adjustment 和审计。

仅可信 provider 最终 usage、可核验账单或明确固定计费合同可以 settled；流中断、发出后超时/取消、异步 submit 后 polling/download 失败或写入不确定保持 `needs_reconciliation` 且保留预留，不以字符估算、输出 bytes、空回执或本地 cache hit 推零。供应商确认未消费后才能释放；可验证账单按 provider/account/request ID 幂等核对。Agent 顶层只观察子服务，不再扣同一单位；每个真实外部子调用都继承可信 operation/主体。查询按 tenant、主体、service、provider/model、单位、时间分页，区分 settled 与 pending；OMS 成本另授权，TMS 仅当前租户安全用量。PG migration 添加 attempt/预留/分摊/证据/调整、唯一键、RLS、索引及审计；聚合以总账为准，不建第二权威。

实施先盘点 LLM/task/embedding、search/web fetch、TTS/STT、image/video、解析/OCR、LightRAG、工具/外部 Agent 的真实发出边界、usage 合同、可信硬上界及取消语义；缺任一项保持 `unsupported` 并禁止硬额度调用。优先在企业执行适配层包装；仅当证明它无法覆盖 retry/stream/异步及 CLI/HTTP/WS/SDK/后台时，审阅 upstream-neutral ProviderAttemptHook/CallContext seam，不向核心灌入 OMS 余额逻辑。合成 PG 并发测试两笔超上界授予、一次 attempt 跨两笔 grant/lot、同 operation 两次可计费 retry、重复/迟到回执、批次过期仍保留历史与未知预留、解析 cache hit、视频下载失败、Agent 防双扣；覆盖 session owner、审计 request ID 和 upstream 合并兼容。
