# 云端 OMS 业务逻辑基础契约

> 实施授权更新（2026-09-26）：用户已明确要求执行本 proposal，并确认包括重订依赖提案与正式代码/版本化 PG 或权限迁移；验证仅使用隔离合成数据。OMS 平台操作者身份/权限来源选定 EduPlus2，但发送端可执行契约仍待提供。原下文“本 change 仅创建规划文档”描述的是提案创建阶段，不再禁止本 change 的实施任务；但旧提案仍须逐项重订并获审阅，真实租户数据、生产发布、归档及提交不在此次授权内。当前完成度以 `tasks.md` 与 `implementation-evidence.md` 为准。

## Why

现有 [`add-c1-oms-operations-prototype`](../add-c1-oms-operations-prototype/proposal.md) 已确定信息架构、权责和原型目标，却没有把平台资源配置、服务供给、租户权益、精确消耗与异常处置落成可直接指导正式开发的业务契约。旧 OMS 只读、Provider 留在 DeepTutor 设置页以及 Token 计费/欠费提案均已暂停，不能作为生产实现依据。需要一份独立于页面原型的 OMS 业务逻辑基础，明确写入权威、状态、不变量及验收边界。

## What Changes

- 定义 OMS 管理的五类平台资源：模型与外部服务、Agent/能力、工具与集成、知识/内容基础能力、运行资源；区分目录对象、可调用服务和个人/租户实例，不把所有资源都视为 LLM Provider 或可计量额度。
- 云端 Skill owner 仅为 `global` 或指定 `tenant`：DeepTutor builtin 映射为不可编辑的 `global` 来源，云端默认零租户授权，由 OMS 按需授权并复核打包版本；OMS/TMS 非 builtin Skill 的创建与更新只接收包含 `SKILL.md` 的 ZIP 包，内容元数据均从包内 `SKILL.md` 解析，owner/审核状态/授权和包摘要由可信平台确定。受控 Hub 导入也必须先取得并校验包；不以单文件或正文表单冒充完整 Skill。OMS 对 global 包另行审核发布并授权。TMS 的 tenant 包仅本租户自用，同名时管理员确认后 tenant 版本优先，不新增成员/应用二次分配或独立 Token 配额。本地 builtin 自动发现保持原样。
- 将 DeepTutor 本地设置字段、后端 descriptor、运行时校验和执行结果作为配置语义来源；云端 OMS 负责全服务 Provider/连接/Secret 引用、草稿—测试—发布—执行者确认—回退，不能以表单保存或 `desired` 状态冒充生效。本地 DeepTutor Web 设置继续可用；云端企业装配阻断旧管理旁路。
- 定义服务供给→OMS 租户服务授权→统一赠送/充值配额授予→DeepTutor 真实调用→租户配额与供应商供给消耗→对账的闭环，含单位兼容、有效期、承诺与预留、赠送优先、并发幂等、撤销/过期、未知用量及供给不足等规则。**配额只由 OMS 配置，TMS 只读本租户配额和消耗。**
- 明确可信逐调用用量的租户/用户/应用/服务/provider/model 归属，Token 使用供应商可信 usage；非 Token 保留原生单位或经验证的调用次数。复合 Agent 不重复扣底层服务；无法确认的消耗待核对，不按零释放。
- 保留 OMS 专属供应商采购与可核实成本观察：只有有凭据、单位与归属证据时才按实际供应商调用归集，不能推出租户售价或账单。**不建设租户费用、每百万 Token 售价、欠费停机或支付流程。**额度耗尽只阻止对应服务的新调用。
- 定义平台动作级权限、审计、租户范围、读写 API、错误/同步状态，以及 EduPlus2 租户生命周期只读边界；TMS 的应用/client、成员和 KB 实例管理不迁入 OMS。
- **BREAKING（相对暂停的旧提案）**：OMS 不再仅只读；Provider 管理从云端 DeepTutor 设置入口改归 OMS；废止旧 Token 费用/欠费及独立模型资格设计。正式开发前，受影响旧实施提案必须按本契约重订并重新批准。

## Capabilities

### New Capabilities

- `enterprise-oms-business-logic`：平台资源/配置、服务供给与配额、可信消耗、OMS-only 供应商成本、治理权限与运行边界的正式业务契约。

### Modified Capabilities

无。原型 delta 负责信息架构与演示；本 change 负责正式业务语义。暂停的旧 change/spec 不在此静默覆盖，须另行重订或退役。

## Impact

- 未来实现涉及 `extensions/enterprise/` 的管理 API、PG 总账/迁移、Secret 引用、配置执行适配、审计和服务准入；核心仅在缺少通用 seam 且经严格审阅后作 upstream-neutral 扩展，不硬编码 OMS/租户规则。
- OMS、TMS 是两个独立部署前端，共享安全的服务业务组件而非应用源码；OMS 专有供给/Secret/成本/跨租户数据不进入 TMS DTO。后端单进程还是多服务保留实施期判断，但必须共享 DeepTutor 执行语义与同一权威业务总账。
- 依赖 B1/B2 可信租户身份与 EduPlus2 生命周期、逐调用可信计量、全服务配置生效和 C1/C2 平台权限/正式界面；原型可先评审，不能作为真实 API、额度控制或生产上线证据。
- 本 change **仅创建规划文档**，不修改运行代码、数据库、外部权限系统或真实租户数据；任务须经用户审阅批准、旧提案冲突重订及相应迁移/验证后才能实施。
