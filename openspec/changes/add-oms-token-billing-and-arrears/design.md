# 设计：精确计费与欠费协同

## 输入与账本
唯一可收费输入是逐次 provider 调用中已结算的真实 `total_tokens`、可信 tenant/user/call_id 和发生时间。`pending`、异常、字符估算、只有 turn 汇总而缺调用事实均不产生确定费用；可在报表显示“待核算调用数”，但不可混入已核算金额。重试每次真实调用独立结算，同一 call_id/价格版本幂等；反向更正保留冲正和审计，不覆盖原始事实。总账和费用按 tenant、user、时间、服务、provider/model 可筛选，不返回 prompt、回答或 Secret。

## 价格与计算
租户单价为每百万 total token 的 Decimal 金额，附 `currency`、有效起始时间、版本、批准人和原因。为避免“价格后来改变导致旧账漂移”，每条费用快照绑定调用发生时有效的价格版本；无有效价格时标为待定价。金额公式：`Decimal(total_tokens) * Decimal(price_per_million) / Decimal(1000000)`；逐调用保留足够精度，期间合计后按币种显示规则舍入，禁止二进制浮点和逐行提前舍入。单价写入不得追溯重算已锁定历史；需要更正时生成有原因的调整记录。

供应商成本价独立按 provider、model、服务、单位、币种、有效期管理；仅对相同用量单位计算。若供应商采用 input/output、缓存、图片/音频或非 token 单位且拿不到相应可信用量/价格，成本拆分显示“待核算”，不能用 total_tokens 猜测。成本为 OMS 内部估算，不冒充供应商发票；跨币种不可直接相加，需明确汇率版本，否则分币种展示。租户/用户/TMS/API 导出均不出现成本和毛利字段。价格、成本变更需冲突检测、审计和双人复核策略（若企业配置要求）。

## 欠费与模型资格状态机
财务状态 `current|overdue|settled`、已确认模型资格 `allowed|restricted|unknown`、请求状态 `none|restriction_requested|restore_requested|needs_attention` 与租户 lifecycle 分开存储、展示和审计。OMS 记录欠费后经 outbox 调用已约定的 EduPlus2 **模型资格**业务接口；只有已验签、按模型资格版本处理的 webhook 才能改变已确认资格。请求未确认、拒绝、超时或版本滞后保留请求 ID、操作者、理由、请求/回执/生效时间，并显示待确认/需处理；请求状态本身不能触发模型限制，也不得转换为 `tenant.suspended`、`local_enabled=false`、用户禁用或会话撤销。手动撤销欠费记录不自动恢复模型资格；恢复仍走 EduPlus2。重放和并发请求用幂等键及分域状态版本防重复发起。若 EduPlus2 未提供模型资格请求接口，OMS 显示“需在 EduPlus2 处理”，不得在 DeepTutor 模拟停机。

限制仅在**实际模型调用**前检查：LLM、task、embedding、TTS/STT、图像/视频及这些模型的 Agent/工具/后台子调用和重试均覆盖；非模型的 search、管理配置、登录、token exchange、历史数据/账务查询、下载及纯非模型工具不因欠费被拦。模型相关操作在 provider dispatch 前给出稳定 `MODEL_ACCESS_RESTRICTED` 业务码和后端状态文案，不返回认证失效；已有会话和已发出的调用可继续，后续新模型调用被拒。管理动作中若包含模型步骤，应预检并保持非模型管理可用，避免半成品副作用。平台自身不归属该租户的模型测试不受该租户欠费影响。模型资格快照缺失/过期时仅模型调用保守拒绝并告警，不影响登录和管理。

## API、权限、迁移
企业 `/api/v1/oms/billing/*` 只用可信平台主体、显式 tenant 范围、分页和白名单输出。读用 `ops.oms.access + ops.billing.read`；租户单价写用 `ops.billing.manage + ops.billing.price.manage`；供应商成本读用 `ops.billing.cost.read`，成本价写再加 `ops.billing.manage + ops.billing.cost.manage`；欠费处置用 `ops.billing.manage + ops.billing.arrears.manage`。默认仅 platform_admin 持有价格/成本写权限，platform_operator 可经明确授权持有欠费处置，platform_auditor 只读；tenant_admin/user 无平台权限。后端实施授权，前端同 key 只控制显隐。价格及状态 display descriptor 由后端提供。

PG migration 新增不可变价格版本、成本版本、逐调用费用快照/调整、欠费财务状态与模型资格请求/outbox/inbox 关联、审计；外键及唯一键约束 tenant/call/request，索引按 tenant/user/时间。模型资格的权威状态/版本由 webhook change 独立维护，不重复定义 `tenant.active`。已有 usage 不凭估算迁移为“精确”；仅可经可信 provider 原始记录/外部对账回填。迁移后验证 RLS、回滚兼容和历史报表。若 OpenFGA/Keycloak 承载新增 ops key，分别使用仓库迁移机制更新，不靠启动时临时补权。

## 验收风险
没有真实 usage 就无法保证金额精确；没有 EduPlus2 模型资格请求及 webhook 闭环就不能保证欠费模型限制。成本数据是敏感内部数据，成本 API 的任何投影/导出都要做字段级负例。必须测试价格生效边界、跨币种、超大 token、重放、更正、部分失败与断网重试，以及欠费时登录/管理/非模型操作仍可用。
