# 设计：OMS 正式业务逻辑与 DeepTutor 执行契约

> 2026-09-26 用户另行授权按任务分片实施；下文“本轮不开发代码”保留原规划阶段背景，不代表当前 apply 已完成或可跳过依赖重订、权限及迁移门禁。实施证据见 `implementation-evidence.md`。

## Context

范围见 [proposal](proposal.md)，验收语义见 [delta spec](specs/enterprise-oms-business-logic/spec.md)。[OMS 原型](../add-c1-oms-operations-prototype/design.md)已定义运营人员逐级列表→详情 IA、五类资源与 OMS/TMS 独立部署，但没有给出可实施的业务状态和事务边界。[现状审计](../add-c1-oms-operations-prototype/readiness-audit.md)、[设置属性清单](../add-c1-oms-operations-prototype/settings-attribute-inventory.md)与[资源作用域清单](../add-c1-oms-operations-prototype/resource-scope-inventory.md)是源码依据，不是运行能力已实现的证据。

**提案归口**：本 change 是业务语义与正式实现的基础契约，不替代 OMS 原型的交互/共享组件验收。暂停的 `add-b2-oms-platform-read-governance`、`add-enterprise-all-service-provider-settings`、`add-enterprise-exact-token-usage-ledger`、`add-oms-token-billing-and-arrears`、`add-c1-c2-oms-operator-interface` 和含欠费部分的 lifecycle change 不能按旧 tasks 执行。它们的可复用目标分别是平台身份、全服务设置、可信逐调用 usage 和签名生命周期；租户费用/欠费目标被废止。未来可以重订这些提案或在批准后按本契约分片交付，但不得同时建立两套供给/额度/用量权威。原型中关于供给余额或“单次 call”扣量的简化描述如与本 change 冲突，以本 change 的**业务规则**为准；实施原型/正式页面前同步文案与 fixture，不可把旧示意公式当总账算法。

## 对话决策的业务落点

| 已确认原则 | 此前落点/缺口 | 本 change 补足的正式开发基础 |
| --- | --- | --- |
| OMS 是普通运营可用的 Agent 平台后台，逐级深入 | OMS 原型定义 IA，未定义写入与数据不变量 | 五类资源作用域、平台动作/状态/审计及安全投影 |
| Provider 覆盖 DeepTutor 全服务，设置属性遵守现有逻辑 | 设置清单仅静态盘点；旧 provider change 写入入口已失效 | descriptor 单一语义、条件字段、逐执行者确认和本地 Web 兼容 |
| 云端只扩展 DeepTutor，核心改动先严格审阅 | 原型有门禁，缺正式执行切片 | 企业扩展优先、全入口 seam 审阅与 upstream smoke 任务 |
| 采购形成服务供给，赠送/充值在一个配额列表，使用才消耗 | 原型有概念，旧 billing change 已废止 | 供给批次/有效期、授予承诺、预留、attempt 计量、并发和核对不变量 |
| 每项可调用服务有配额，赠送优先；额度耗尽只停对应服务 | 原型有原则，旧 Token ledger 只覆盖部分调用 | 非 Token 原生单位、硬上界准入、跨入口防绕过及失败状态 |
| 供应商成本只在 OMS，不向租户计费 | 旧成本拆分与租户账单捆绑 | 内部采购/成本证据与未核定状态，不产生售价/费用/欠费 |
| EduPlus2 管租户开停，TMS 配额只读 | 原型已决定，旧 lifecycle/OMS 只读提案冲突 | 平台与租户权限、当前租户投影、额度不足不改变 lifecycle |

## Goals / Non-Goals

- 目标：给出能够推导 API、持久化、权限、服务准入与验收的稳定业务模型，并以 DeepTutor 真实设置/执行逻辑为核心；单次服务执行可以完整追溯供给、租户授予及用量。
- 非目标：本轮不开发代码、部署 OMS、采购真实供应商资源或改变外部权限；不建设租户售价、费用、账单、欠费、支付或“停整个租户”的额度政策；不把 OMS 变成学员私有内容后台。

## Decisions

### 1. 权威矩阵与统一资源标识

| 事实 | 权威写入 | 其他端可见/不可见 |
| --- | --- | --- |
| 租户开通/暂停/恢复 | EduPlus2 签名事件；DeepTutor 独立本地隔离状态沿用已有归口 | OMS/TMS 只读来源、状态和异常；配额不足不修改 lifecycle |
| 平台服务/Provider/Agent/工具/基础能力配置 | OMS 的获授权平台动作，DeepTutor descriptor/执行者定义可用语义 | TMS 仅获授权目录与安全状态；本地 Web 维持本地设置 |
| 供应商连接/Secret 与采购供给 | OMS 高权限动作 + 外部供应商证据 | TMS/API/共享组件不得接收明文 Secret、采购成本和供给批次敏感细节 |
| 租户服务授权、赠送/充值配额 | OMS 获授权动作 | TMS 当前租户只读投影；成员/应用 grant 不更改额度 |
| 真实调用与消耗 | DeepTutor 可信执行边界、企业总账和受控对账 | OMS 按平台权限追溯；TMS 只读本租户；个人仅见自身可见范围 |
| 租户成员、应用/client、KB/文件实例与个人内容 | EduPlus2/TMS/业务 owner 按对象归口 | OMS 仅必要脱敏状态和聚合，不取私有正文 |

平台目录以稳定 service ID 标识可调用服务，provider/model/配置版本作为执行选择；Agent/工具/模板有独立资源 ID 和依赖边，不能把每个目录项强制转成一份 Provider profile。服务授权和配额分别持有 service ID 与可兼容供应商资源范围。拒绝“复制一套 DeepTutor provider 注册表给 OMS”——它会在上游新增服务时漂移。

云端 Skill 使用独立的 owner 键（`global` 或指定 `tenant`）与来源字段（内置/人工/Hub/上传），不能把现有用户级 `source=admin` 当 owner。OMS 只维护 global Skill 的安全审查、版本化发布和目标租户授权；发布且授权生效即允许目标租户使用，无 TMS 成员/应用二次分配。OMS 对已有同名 tenant Skill 的租户后授权 global Skill 时须提示该租户运行时仍选择 tenant 版本，不得覆盖 tenant 内容或把被覆盖的 global 误标为实际版本。跨 owner 同名身份不同；真实清单与 `read_skill` 必须共享 tenant 优先的解析规则，缺依赖时不静默回退。个人 Skill 仅保留在本地 DeepTutor，不成为云端第三种 owner。

非 builtin 的 global Skill 只能经完整 ZIP 包创建或以同名新 ZIP 更新；受控 Hub 必须取得实际包。服务端在隔离环境解包，按 DeepTutor 包语义验证唯一 `SKILL.md`、有效 YAML frontmatter（`name`、`description` 必填）、非空正文、目录与 `name` 一致性、资源文件白名单、路径/重复/链接/加密/膨胀/体积限制，并以包内 `SKILL.md` 作为名称、说明、标签、依赖、自动注入意图等 Skill 内容元数据的唯一来源，不接受客户端另传字段覆盖。owner、来源、审核/发布状态、授权、不可变包摘要及平台修订号由可信上下文生成，不能从上传的 YAML 提权。原始包与审查结果版本化保存，脚本及 `always` 在审查前不得执行/启用；发布替换须复核且可回滚。浏览器预检只改善反馈，不可代替服务端校验或安全审查。DeepTutor 核心保持不变，优先企业扩展。

DeepTutor builtin 来自打包目录而非 OMS 编辑表，企业层以 `owner=global, source=builtin` 映射，记录打包版本/内容摘要、依赖条件与授权，不允许修改/删除包内正文。首次云端装配与后续新增 builtin 均默认零租户授权；OMS 对已复核的 builtin 版本按租户授予/撤销，TMS 获授权后无需二次分配，但 `requires`（如 shell sandbox）仍可能使其暂不可用。当前 DeepTutor 的 `SkillService` 会自动发现 builtin，故正式企业路径须在 manifest、`read_skill` 正文/参考文件、显式请求和 `always` 自动注入的同一可信边界过滤，而不能只过滤 TMS API 或菜单；CLI、HTTP/WS、SDK、Partners 等入口都需审计。若扩展层不足以阻断，先提交 upstream-neutral seam 的严格审阅；本地产品的自动发现与用户覆盖 builtin 不改变。上游/程序升级改变 builtin 摘要时，须记录差异并复核既有租户授权影响；无经审阅的旧/新版本切换契约，不得让新内容借旧授权静默生效。

### 2. 配置发布走现有 descriptor 与执行者确认

配置流是 `draft → validated/tested → publishing → active`，失败转 `failed` 并保留上一 active；撤回/回退也是版本化写入而非覆盖历史。发布时记录目标执行者/实例集合及各自版本确认；只有全体目标确认且可继续一致服务时整体进入 active，部分确认/超时不能显示成功，未确认实例不接新流量。新实例先装载已生效版本再进入就绪。连接与凭据只存 Secret 引用，测试/诊断使用受控解析，响应和审计只记录脱敏结果。连接范围目前不含 search；search 无模型列表；task 缺单独配置时回退 LLM；embedding endpoint 是完整地址；TTS、STT、图像、视频、文档解析及外部 Agent 各用真实条件属性。这些差异由 DeepTutor descriptor 与执行适配来源维护，OMS UI 是领域化交互，不直接复制本地 `/settings` 页面。未来新增通用 OCR 配置或服务 descriptor 时，同一核心语义须能服务本地 Web 设置和云端 OMS；本地 UI 是否复用组件另议，但不得只在 OMS 造一个无法被本地产品使用的平行实现。

每个执行者的实际配置读取及确认路径须列证：LLM/task/embedding 等模型调用、search、语音、图像、视频异步任务、解析/检索、外部 Agent/工具。尚未接入的执行者显示“待接入/未生效”，不以数据库 `active` 标记或保存成功替代真实 smoke。云端旧 `/settings` 管理页面/API/CLI/SDK 旁路逐项审计并在企业装配层阻断；本地产品不因此关闭。

### 3. 一套供给—授予—预留—消耗总账

建议业务实体：`ServiceDefinition`（服务/计量/准入 descriptor）、`SupplyLot`（供应商资源方案/补充批次）、`TenantServiceEntitlement`（服务访问授权）、`QuotaGrant`（租户单笔赠送/充值）、`CallReservation`（调用前占用）、`UsageAttempt`（可信调用归属与供应商证据）、`ConsumptionAllocation`（同一调用的授予与供给归集）、`ReconciliationAdjustment`（留痕更正）。这些是业务概念，不强制某一张表或代码类名。

- `SupplyLot` 以服务、provider/model 或可交换池、原生单位、有效期、数量/硬上界形成**兼容范围**；每个批次分别保留终身上界/历史消耗和当前有效可授予量。没有可核实上界的 pay-as-you-go/金额型采购只能记录供给关系，**不得授予硬配额或放行依赖配额的新调用**；如未来要开放，另立有界风险契约并获批准。
- `QuotaGrant` 一笔代表一次获取，`acquisition_method=gift|recharge`，二者同表/同列表；授予时原子锁定/校验兼容供给，记录一笔授予对一个或多个供给批次的承诺分配。授予到期不晚于支撑批次到期；若需延长，先从新的有效批次受控重绑定未用承诺并留审计。充值是获取方式，不代表 TMS 发起支付。
- 对每个有限供给批次，终身不变量为 `历史已结算实际消耗 + 当前已承诺未使用 + 当前在途预留 ≤ 该批次可核实上界`；当前可再授予量仅在**有效批次**中计算。**在途预留已从“未使用承诺”转移出来**，不能再重复扣一次。批次过期后历史消耗仍留账，未使用承诺停止准入；过期前已发出的尝试仍可待核对结算，但不能因过期直接抹掉在途预留。
- 有效赠送先于充值；同类按有效期和稳定授予顺序。每次供应商 attempt 的授予/供给分摊在准入/预留时固定；迟到 usage 只核对该 attempt，不因后来补赠改变历史。一次 attempt 可跨多笔授予与供给批次，其真实用量在每个维度各归集一次。
- 一个逻辑 `operation_id` 可能因重试发出多个供应商请求。每次可能计费的发出动作都有唯一 `attempt_id`、可取得时关联供应商 request ID，并新增自己的上界预留；同一 attempt 的回执重复不再扣，两个确实计费的 attempt 分别结算后汇总到 operation。流式、异步和取消会产生不确定远端结果；只在可信确认未消耗后释放预留。无法实施上界预留时拒绝新调用，不一边无限放行一边声称额度用尽即停。

拒绝“授予即算消耗”与“前端余额扣减”：前者会重复计算采购和真实使用，后者无法覆盖 CLI/WS/SDK/后台及并发。

### 4. 准入、计量与核对在同一可信调用链

统一决策顺序为：可信主体/tenant 与 EduPlus2 资格 → 目标服务及适用的成员/应用/服务主体授权 → 配置真实 readiness → 租户有效配额 → 兼容供给 → attempt 预留 → provider/工具执行 → 真实 usage 或待核对 → 幂等结算。主体形态分为直接用户、应用委托用户、应用本身和受控后台服务主体；前者校验成员 grant，委托调用校验成员与应用 grant，纯应用校验应用 grant，后台调用校验可信 job 发起/归属与显式服务主体 grant，不因缺 user/app ID 免鉴权。Agent 子调用继承原可信主体和 operation 归属。具体错误分别返回租户未获授权、主体无权、租户额度不足、平台供给不足、配置未生效或调用结果待核对；这些是不同运营状态。额度/供给不足只拦该服务的新调用，不改登录、管理、历史或其他服务。TMS 服务访问 grant 不参与配额数量变更。

逐供应商尝试事实要带可信 tenant、主体类型/ID、适用时的 user/app ID、service、provider/model、配置版本、`operation_id/attempt_id`、可取得的供应商请求 ID、重试关系、供应商 usage 原始安全片段、规范化原生单位、来源与核对状态。Token 仅凭可信 provider usage/可核验账单结算，不能用 `UsageTracker` 的字符估算；非 Token 保留原生单位，调用次数仅在真实调用边界可数时使用。Agent 流程本身记录观察指标，已扣的 LLM/搜索/其他子服务不得再次在顶层扣同一单位。人工核对只新增调整和审计，不改写原始证据。

### 5. 成本、平台权限与对外投影分层

供应商采购/补充金额可作为 OMS 内部供给事实；供应商成本拆分必须基于具体 provider/model 调用证据和当时适用的合同/单价/币种口径，不同单位不可凭想象折算。合同不能可靠分摊时只展示已采购金额和“归集待核定”，不生成零成本或租户费用。OMS 成本权限与用量、配额、采购写权限拆分；TMS 不接收成本字段。旧 `ops.billing.*`、独立模型资格和欠费 webhook 不是本目标的授权依据，实施前需迁移/停用旧目标并清理入口。

OMS API 先验证平台身份与具体动作，再绑定目标 tenant、查询/写入最小字段。服务 DTO 分共同安全投影和 OMS 专有投影；共享 OCR 等业务组件只接受前者。Secret 仅以引用和安全状态呈现，成本/供给/跨租户指标留在 OMS 专有容器与 API。配置发布、供给补充、授权/额度、核对、导出均有独立权限、原因、版本与审计。状态文案由后端稳定状态/display 契约供给，普通运营默认看到影响与下一步，高级技术细节再展开。

用户选择 **EduPlus2 平台身份与权限**作为 OMS 操作者来源；现有 `tid/eui/sub/azp` 租户换票与管理权限过滤不能直接复用。根据 EduPlus2 文档，平台路径可复用同一受信 Keycloak realm issuer/JWKS，但须有专用 OMS client/audience、独立主体绑定与权限 API/OpenFGA 动作/撤权校验，不能信 JWT realm/client role；平台与租户 session 不互继承。OMS relation/object/目标范围、operator 可调用的权限端点及必要迁移尚未提供，故跨租户写 router 在双方契约和合成伪造/越权负例通过前保持未装配；不可用 DeepTutor 本地 DB 自建一个“平台管理员”绕过该门禁。

## Risks / Trade-offs

| 风险 | 缓解 |
| --- | --- |
| 不同供应商资源不能统一换算，导致虚假可授予量 | 服务/供应商/单位/有效期定义兼容池；无法核实则不作硬授予 |
| 流式与异步调用缺最终 usage，破坏严格硬额度 | 调用前保守预留；未知结果持续待核对且不释放；真实供应商/集成 smoke 验证 |
| 上游新增服务或字段后 OMS 与本地设置漂移 | descriptor/执行者为单一语义来源，新增通用能力要求本地与企业双路径回归 |
| 旧只读/计费 proposal 与新业务逻辑并存 | 标记旧任务停用；实施前逐项重订或退役，确认唯一额度与用量总账 |
| 高权限 OMS 暴露私有内容或成本 | 分级 API 投影、权限与导出负例，禁止浏览器隐藏字段作为隔离 |

## Migration Plan

1. 用户先审阅本 proposal 与配套 TMS 业务 proposal；旧实施提案、两份原型中简化的扣量/权限文案、`docs/enterprise/02-*`、`11-*`、`12-*` 及权限矩阵按权威边界重订，不把当前 OpenSpec 文档验证当成实施批准。
2. 分片完成平台可信身份/权限、全服务 descriptor 与生效、供给/授予/预留/用量总账，使用版本化 PG 迁移和必要的 OpenFGA/Keycloak 迁移；旧计费/欠费目标不得迁入生产。供应商配置/凭据与业务状态各走受控 Secret/PG 来源。
3. 真实 CLI、HTTP/WS、SDK、后台、Agent/非 Token 服务逐项验证准入/用量/取消/对账；独立 OMS 前端只在 API 与权限通过后接真实适配器，开发 fixture 不进入生产。独立部署、负例、审计、迁移 dry-run/apply/verify、故障与回退证据齐全后才开放正式入口。
4. 回退保持上一配置 active、已结算调用和授予历史不可丢；停止新授予/调用或切回上一兼容前端/API 版本前，必须先处理在途预留和待核对调用，不靠删除总账回滚。多执行者前另通过 H/G-H。核心如确需改动，逐处提交 upstream-neutral seam 审阅，未经批准不改。
