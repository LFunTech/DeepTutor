# 企业化 proposal 执行顺序与进度

> 状态快照：2026-09-29，基于当前工作区的 `openspec list --json`、各 change 的 proposal/tasks 和执行证据。本文是跨提案的**排序与阻断项索引**，不是实施批准、任务完成证明或发布放行记录。任务完成数以各 change 的 `tasks.md` 为准；OpenSpec artifact 齐备不等于业务完成。已归档的六个历史 change 不再列入待执行队列。

> 后续授权：2026-09-26 用户已明确批准执行 `add-enterprise-oms-business-logic`，包括依赖提案重订与正式代码/迁移；五份旧版依赖 change 曾分别获批。2026-09-27 用户确认 `add-enterprise-management-authorization` 已完成审阅并要求按跨提案计划继续推进；先前 PG 事实库版受影响提案曾分别获批；用户随后明确 Enterprise 程序授权与真实订阅 actor 首位引导，并分别批准受影响的当前修订版；实施和外部合同验收仍未完成。当前管理授权 change 已推进到 51/81；真实外部身份、双学校负例、真实平台目录/账号按钮验收、CLI/WS/SDK 旁路审计与开闸仍未完成。同日用户又单独批准新 `add-b1-b2-trusted-school-integration` 按现版实施，目前 14 项任务完成 3 项（批准、只读外部契约矩阵、全入口／旁路盘点）。旧 Token 费用/欠费目标获准退役但不归档/同步旧 spec。验证限隔离合成数据；用户此前另行授权了 test-cn 提交、受控发布及 Webhook mock 联调，但本次未授权真实租户数据、生产发布或归档。旧 change 的原版不得继续实施。

## 当前决策与执行原则

- 生产验收主线仍为 **M1/G1 固定租户运行与发布 → B1/B2/G2 可信多租户及 TMS → C1/C2/G3 完整 OMS**。规划、契约、原型和环境准备可提前并行；前置验收不通过时，不开放下游生产能力。
- DeepTutor 是本地部署产品；云端 OMS、TMS 分别构建和部署，共享安全的管理业务组件，不共享应用源码、数据权限或生产 fixture。OMS 是平台资源、服务供给、学校服务授权及赠送/充值额度的唯一写入权威；TMS 仅管理当前学校内部事务并只读额度与真实消耗。两端本产品权限统一由 DeepTutor Enterprise 程序按 PG 事实判定（数据库权限/RLS 非操作者授权）、应用域/会话分离、首次登录零权；首位学校管理员由真实订阅事件 actor 在 Webhook 接收事务内即时开启，OMS 不管理学校账号。
- 取消旧租户 Token 售价、费用、欠费停机和 EduPlus2 独立“欠费模型资格”闭环。额度耗尽只拒绝对应服务的新调用，不能阻断登录、管理、历史或其他服务；EduPlus2 仍独占租户生命周期权威。
- 保持 `upstream/main` 可合并：企业专有逻辑优先放 `extensions/enterprise/`；核心仅允许经单独审阅的通用 seam，并在受影响 CLI、HTTP/WS、SDK、后台路径及身份、session ownership、审计关联上留回归证据。
- [02 实施总纲](02-rollout-testing-and-migration.md)、[11 入口](11-api-and-entrypoints.md)、[12 管理](12-platform-operations-admin.md) 已同步独立前端、OMS 可维护全服务配置与权益、TMS 额度只读及无租户费用/欠费的新边界。其他历史文档若仍保留旧叙述，不得作为实施依据。

## 执行波次与门禁

| 波次 | 工作与可并行范围 | 进入下一波的门禁 |
| --- | --- | --- |
| **P0：契约与进度收敛，现在并行** | OMS 当前权威修订版及直接依赖 change 已分别获批并完成 6.1 文档复核；Enterprise 程序授权/真实订阅 actor 首位引导的实施与外部合同仍待验收；08/09/11/12 与旧入口文案已同步。TMS 业务契约与双端开发态原型浏览器审计已留证；正式身份、权限与执行者合同仍待实施。旧计费/欠费目标已批准退役但未归档/同步旧 spec。未受权威变更影响的内部事务可按原授权继续隔离验证；新平台权限、正式跨校写 API 和受影响前端须完成各自实施与验收门禁，P0 不放行真实租户数据或生产上线。 | 新旧方案无冲突；原型任务与依赖未来生产实现的任务分清，不以 fixture 宣称真实能力；既存外部身份/账号/学校接口仍须针对 OMS/TMS 适用性分别确认；TMS 管理员权限 webhook 不再是本产品授权依赖。 |
| **P1：M1/G1** | 完成固定租户 runtime 基线的确认门禁；继续 G1 各目标环境的真实 Ingress/TLS、EduPlus2、HTTP/WS、资源、LightRAG、回退、安全和证据验证。P0 的文档/原型工作可与之并行。 | M1 所需运行路径与目标环境 G1 门禁有真实证据；仅通过构建/部署或无 token 的 WS 负向探针不算完整登录与 turn smoke。 |
| **P2：B1/B2 身份与隔离** | [`add-b1-b2-trusted-school-integration`](../../openspec/changes/add-b1-b2-trusted-school-integration/proposal.md) 已获单独批准实施，覆盖最终 B1 接入和 B2 多学校可信绑定、RLS/资源/任务隔离；先用真实首校验证，再开放多校；不使用 `eit=adm` 或旧 `tenant_admin` 默认授予 TMS 管理权。EduPlus2 lifecycle webhook 负责学校状态与对账；真实 `subscription.created.actor` 另向本系统提供一次性首位管理员身份线索，不作为外部权限判定。内部合成验证可提前，生产开放受本波门禁约束。 | 首校接入及双学校全入口隔离通过；签名事件、乱序/重放、恢复和本地隔离状态不被外部事件覆盖均有证据。 |
| **P3：平台公共数据面，可按依赖并行** | 先完成可信平台/学校身份、DeepTutor 双域动作权限、TMS 真实订阅 actor 一次性首位管理员即时开启及 OMS/TMS 管理 API 边界；随后全服务 Provider/Secret 生效链与逐调用 Token/非 Token 原生单位用量总账可并行。TMS 的本租户 client、资源授权、KB/文档纵向切片可在 P2 可信身份后并行，但不能预支 OMS 权益或使用假额度。 | 平台资源/权益写入仅由授权 OMS 路径执行，学校首位管理员由 Enterprise 受控事件即时开启，后续角色由 TMS 本校授权服务管理；旧云端管理旁路关闭；配置有执行者 active 确认；可信 usage 缺失时保留待核对，不按零结算。 |
| **P4：供给、权益、TMS/G2** | 以新 change 交付服务供给 → OMS 租户授权/统一赠送与充值配额 → 预留/真实调用/核对闭环；OMS 至少要有受控、可审计的授权与配额写入路径。再将 TMS 当前租户配额/用量只读投影、应用/client、成员/资源/Skill 权限和独立前端接入真实 API，完成 G2。 | 未确定 OMS 在 B2 前如何安全配置服务授权和额度时，**不得用手工改库或原型 fixture 放行 TMS/G2**；TMS 无配额写路由、OMS 专有字段或跨租户数据，额度耗尽只影响对应服务。 |
| **P5：完整 OMS/C1/C2/G3** | 数据面及平台权限稳定后，将独立 OMS 正式界面接入真实平台资源、供给、权益、用量、审计 API；先完成 C1 可用闭环，再完成 C2 治理和 G3。旧运营界面提案须按新 IA 重订。 | 五类资源、全服务配置、供给/权益/实际消耗及异常核对端到端通过；菜单、动作、API 权限一致；不出现旧费用/欠费功能。 |

**贯穿门禁：**任何波次若实际启用多执行者或要求高可用，应先补 G-H 变更并完成跨实例一致性、故障切换与回退验证；单实例须明示非 HA、容量和恢复目标。迁移、发布、真实外部系统变更和归档各按对应 change 与授权门禁执行。

## OMS / 首个 Agent 集中推进切片

为避免再次把 OMS、TMS、Webhook、Provider 和用量任务混在一起，首个 Agent 的 test-cn 内部受控联调按以下顺序执行。每一行只说明**谁是权威 proposal**，不因另一个 proposal 的局部切片完成而自动勾选本行之外的任务。

| 切片 | 权威 proposal / tasks | 产物与完成条件 |
| --- | --- | --- |
| 1. 管理身份与 PEP | `add-enterprise-management-authorization` 1.2、2.1、3.2；`add-b2-oms-platform-read-governance` 1.x、2.1 | OMS/TMS 独立会话、DeepTutor 程序授权服务、`ops.*`/`tenant.*` 动作目录和写事务复核；禁止 `tenant_admin`、JWT role、header、PG role/RLS 直接放权。 |
| 2. Provider/模型维护 | `add-enterprise-all-service-provider-settings` 2.3、2.4、3.x；`add-enterprise-oms-business-logic` 6.3、7.4 | OMS 后端可维护模型/Provider 配置，执行者真实装载 active 版本；会产生供应商调用的测试必须走学校服务授权、供给/额度预留和 attempt 记录。 |
| 3. Global Skill 管理 | `add-enterprise-oms-business-logic` 6.5；`add-enterprise-management-authorization` 3.2；TMS 对应 `add-enterprise-tms-business-logic` 5.7 | OMS 管 global/builtin Skill 的登记、审核、发布、学校授权和运行时过滤；TMS 只管本校 tenant ZIP，自用且不二次分配额度。 |
| 4. 执行前准入与用量 | `add-enterprise-oms-business-logic` 7.4、7.5；`add-enterprise-exact-token-usage-ledger` 2.3、3.1 | CLI/HTTP/WS/SDK/后台/Agent 子调用在发出前完成授权、配置 ready、供给/额度预留；真实 usage/原生单位结算，未知保留待核对，不按零释放。 |
| 5. 正式 OMS UI | `add-c1-c2-oms-operator-interface` 1.2、2.x、3.x、4.x | 独立 OMS 前端只接真实 `/api/v1/oms/*` 和 `/me/permissions`；未启用/无权安全降级，不使用 fixture 或旧原型；平台人员/角色/学校范围不包含学校账号开通。 |
| 6. 学校侧闭环 | `add-enterprise-tms-business-logic` 4.x、5.x、6.x、7.x；`add-b1-b2-trusted-school-integration` 3.x | TMS 消费 Webhook 学校有效投影和首位 actor 即时开启，管理本校成员/应用/资源/tenant Skill；只读 OMS 配额/用量，不写额度或 Secret。 |

## 活跃 change 逐项进度与下一动作

以下 `x/y` 是**任务勾选数的快照**，不是生产完成百分比；其中原型任务含依赖后续正式实现的门禁，不能为了关闭原型而提前勾选。

| Change | 当前状态 | 顺序、依赖与下一动作 |
| --- | --- | --- |
| [`add-ws-required-context-controls`](../../openspec/changes/add-ws-required-context-controls/tasks.md) | 23/23；OpenSpec 显示 complete，仍活跃 | 已实现的协议基线，不再排实施任务；复核证据后，归档须另获明确同意。 |
| [`add-m1-fixed-tenant-runtime-baseline`](../../openspec/changes/add-m1-fixed-tenant-runtime-baseline/tasks.md) | 32/33；仅余 V.5 确认/归档门禁 | P1：核对运行证据与当前 upstream 兼容性；不以任务数推断 G1 或生产上线完成。 |
| [`add-g1-woodpecker-k8s-release-baseline`](../../openspec/changes/add-g1-woodpecker-k8s-release-baseline/tasks.md) | 22/33；真实环境与异常/回退等仍有未勾项 | P1：在选定目标环境补全真实登录及 HTTP/WS turn、LightRAG、回退、安全与 release evidence；各环境分别标记 verified/unverified。 |
| [`add-b1-b2-trusted-school-integration`](../../openspec/changes/add-b1-b2-trusted-school-integration/proposal.md) | 3/14；P0 契约矩阵及[逐入口／旁路清单](../../openspec/changes/add-b1-b2-trusted-school-integration/external-contract-and-path-audit-2026-09-27.md)已完成；合成双校 Store/KB 隔离与非 owner RLS 已测，但当前表 owner 运行模式会绕过 core 非 FORCE RLS，学校/账号在线核验亦缺，尚无 B1/G2 放行证据 | 用户确定迁移/运行共用同一个 PG 账号、不拆分；先完成[单账号 FORCE RLS 严格审阅与剩余风险确认](../../openspec/changes/add-b1-b2-trusted-school-integration/external-contract-and-path-audit-2026-09-27.md#单账号-force-rls-严格审阅及实施门禁)，不得将其当作同凭据恶意直连隔离，再推进不可变后续迁移与维护路径改造。`oms.school_bindings` 权威仍归管理授权 change；普通换票 resolve 已改每次在线查询，但 `aud`、本人状态及绑定 epoch 未接通。缺可信接口时入口关闭。 |
| [`add-c1-oms-operations-prototype`](../../openspec/changes/add-c1-oms-operations-prototype/tasks.md) | 46/49；开发态原型旧交互已验收，非生产 OMS；2.2 因最新 Enterprise 程序授权边界重新打开 | 连接/Profile/模型、搜索/解析控件、平台人员选人及角色/学校范围均为合成演示。双端浏览器矩阵与生产 404 见[审计记录](../../openspec/changes/add-c1-oms-operations-prototype/prototype-browser-audit-2026-09-27.md)。余 4.1、4.2 是旧管理旁路审计及正式实施门禁；不能用原型证明 API 403/409。 |
| [`add-b2-tms-management-prototype`](../../openspec/changes/add-b2-tms-management-prototype/tasks.md) | 37/41；开发态原型含订阅 actor 新交互已完成合成测试及桌面/窄屏浏览器复核，非生产 TMS | 学校角色、账号查询、事件 actor 本人匹配、访问关系、只读额度及共享服务安全投影已做合成原型；生产原型路径仍为 404。余 3.3、3.5、4.2、4.3 属真实身份/权限/Skill 接口与条件性 HA 门禁，需正式服务端正负例。 |
| [`add-enterprise-oms-business-logic`](../../openspec/changes/add-enterprise-oms-business-logic/proposal.md) | 15/23；当前修订版已获批，内部总账、资源状态、模型/Provider 设置/Skill 部分正式 API 与学校额度/权益切片已有合成验证；业务全链路、正式前端和真实执行仍未验收 | DeepTutor 内部 PG/供给/赠送与充值/逐 attempt 事务有隔离合成验证，仍未接真实执行者。OMS 应用 `ops.*`/目标学校授权改归 DeepTutor，EduPlus2 仅消费既存身份/学校接口；发送端草稿已撤销。正式跨学校写 API 未开放，需本仓库权限迁移、现有外部接口核验、双学校撤权负例及全链路验收；不能把内部事务或 Webhook demo 当上线证据。 |
| [`add-enterprise-management-authorization`](../../openspec/changes/add-enterprise-management-authorization/proposal.md) | 51/81；已接入正式 OMS/TMS 受控入口、TMS 授权写按钮、目录状态、额度/用量/服务访问只读、OMS 模型/Provider/资源/学校/供给/审计/成本/用量任务只读 DTO；新增审批通用 apply、模板版本显式确认、OMS 模型/Provider/Skill 写按钮，以及 OMS 平台人员/角色/学校范围授权、审批、撤权、主体停用写 API 与治理 UI；真实平台登录、真实 actor/OIDC 匹配、双学校真实负例、真实目录/账号按钮验收与开闸仍未完成 | P0/P3 继续补外部身份与真实环境证据；P5 接 OMS 写入/审批/审计回读。缺可信接口时写 API 关闭，不修改 EduPlus2。 |
| [`add-enterprise-tms-business-logic`](../../openspec/changes/add-enterprise-tms-business-logic/proposal.md) | 2/23；2026-09-28 完成 TMS 存储归属/迁移清单与分层权限测试矩阵；另已实现当前学校配额/用量分页只读与服务访问 grant/revoke HTTP 切片，但不足以勾选完整 TMS 任务；正式前端、成员/应用/资源管理仍未完成 | P0 与 OMS 固定共享 ID/授权/安全 DTO；随 P2/P4 实施，配额视图依赖真实 OMS 授予和用量。 |
| [`add-b2-eduplus2-tenant-lifecycle-webhook`](../../openspec/changes/add-b2-eduplus2-tenant-lifecycle-webhook/proposal.md) | 12/12；已实现验签后事务内学校映射、PG onboarding、生命周期投影、TMS 首管候选与隔离合成激活 API、学校—应用资格、本地冻结/诊断和聚合监测；八类事件/重试合同已只读核对 | test-cn `rc.53` 经 Woodpecker #64 部署，静态应用 ID 参数移除；真实非 mock terminated/created 及获批准的独立测试学校新增订阅→暂停→恢复均成功。PG 资格 `allowed→denied→allowed`，本地 AI 开关仍关闭，资源 pending，候选仍待核验。3.1 已验收；3.2 完整回归及 upstream 兼容审查已于 2026-09-28 完成；待单独归档，不代表 TMS 本人激活或正式管理写入口已放行。正式 TMS 尚未交付，真实本人 OIDC 登录/激活归管理授权/TMS 提案；Webhook 204 不授予人员权限或 AI 资源 ready。无来源版本时漏送/迟到风险继续披露；不修改 EduPlus2 代码、不手工补数。 |
| [`add-b2-oms-platform-read-governance`](../../openspec/changes/add-b2-oms-platform-read-governance/proposal.md) | 2/8；2026-09-28 完成 OMS 专用 PEP 入口、最小治理读 API 与后端状态 display catalog；真实身份/学校接口、前端守卫及双校验收仍未完成 | P3 继续核实 EduPlus2 既存 OIDC/账号状态/学校接口；权限 PG 迁移归 `add-enterprise-management-authorization`；本 change 消费其可信身份、动作、学校范围和撤权，完成负例后才开放更多跨学校写 API。无发送端 OMS 权限迁移。 |
| [`add-enterprise-all-service-provider-settings`](../../openspec/changes/add-enterprise-all-service-provider-settings/proposal.md) | 4/9；2026-09-28 已完成 descriptor/执行者矩阵、PG 配置事实迁移+旧 JSON dry-run、正式 OMS Provider 设置后端读写 API/权限负例/执行者确认/失败回退；正式前端与逐服务真实 adapter 探针仍未完成 | P3 继续完成既存外部身份核验、DeepTutor OMS 动作权限与 attempt 准入、版本化配置读写/逐执行者确认；本地 DeepTutor 设置不退化。 |
| [`add-enterprise-exact-token-usage-ledger`](../../openspec/changes/add-enterprise-exact-token-usage-ledger/proposal.md) | 6/9；1.1 发出边界矩阵、1.2 Enterprise CallContext 包装、1.3 OMS PG attempt 总账基线、2.1/2.2 预留/准入/幂等结算测试与实现、2.4 OMS/TMS 分级聚合与分页 API 已完成；全入口真实 adapter 接入、账单对账/更正与演练仍未完成 | P3 继续完成硬上界预留、多服务执行证据与待核对；不依赖旧费用/欠费提案，供 P4 消耗结算。 |
| [`add-oms-token-billing-and-arrears`](../../openspec/changes/add-oms-token-billing-and-arrears/proposal.md) | 0/10；用户已批准退役旧目标，禁止按旧 tasks 实施 | 不归档、不同步冲突旧 spec；现行供给—权益—实际消耗以已批准 OMS change 为准。**不得沿用售价、费用或欠费字段。** |
| [`add-c1-c2-oms-operator-interface`](../../openspec/changes/add-c1-c2-oms-operator-interface/proposal.md) | 10/26；已完成正式 OMS 页面/API/动作矩阵、独立 `/oms` 受控工作台、生产原型 404、资源/学校/供给/审计/成本/用量/任务只读 DTO 首屏接入，并接入模型/Provider/Skill 首批写按钮和平台授权治理写视图；供给/额度/核对动作、完整详情、分页导出和真实角色矩阵仍未完成 | P5 继续接 Provider/Skill/供给/额度写动作与本产品平台人员/角色/学校操作范围、审计回读；不把原型作为生产入口，TMS 不继承 OMS 权限。 |

## 尚缺的实施 change 与当前阻断项

1. **B1/B2 完整接入与多学校底座：**已归档联邦访问 change 不等于 B1 最终接入、B2 真实多学校与 G2 完成。新 [`add-b1-b2-trusted-school-integration`](../../openspec/changes/add-b1-b2-trusted-school-integration/proposal.md) 已补齐可信学校绑定、资源隔离、放量门禁的实施契约并获单独批准；外部合同和 B1/G2 真实验收仍缺，管理授权/lifecycle/TMS 各自保有权限、学校状态、业务边界。
2. **服务供给—租户权益/额度—实际消耗：**旧计费/欠费 change 已获准退役，不能重用为实施依据。OMS 内部总账与重订逐 attempt 用量 change 负责 OMS 独占写入、供给可授予量、赠送优先、并发预留、原生单位、未知用量待核对及跨入口服务准入；正式跨学校写入仍须通过最新 Enterprise 程序授权方案的复核和外部身份接口的真实验收。TMS 只读 DTO 需与已批准且尚未全部实施的 TMS 业务 change 对齐。G2 前须有安全可运营闭环，不能靠手工状态修补。
3. **其他历史文档冲突：**02/11/12 与旧入口占位已同步；本目录其他历史叙述若与现行 OMS/TMS 契约冲突，继续逐项核对，不把旧里程碑文字当作权限或发布授权。
4. **外部与发布证据：**2026-09-26 test-cn 签名 Webhook 8/8 mock HTTP 204 已验证并复用，仅证明 demo 接收；2026-09-18 discovery/JWKS、M2M、client resolve 与本地交互登录/WS 证据可复用，但 OMS 专用 client/audience、在线账号状态、学校权威核验及管理撤权仍未验收。现有 EduPlus2 lifecycle 事件与 online resolve 在目标环境的适用性、首位 actor 真实事件与本人同校一次性激活、真实测试登录与 WS turn、各目标环境 G1 回退/异常仍需对应真实证据；开发态原型浏览器审计已单独留证，未验证的生产项目保持未完成。

## 更新规则

- 每次 proposal 获批、任务验证、被取代或归档时，同时更新本页日期、状态、依赖和下一动作；先核对 `openspec list --json` 与对应 `tasks.md`/执行证据，再更新数字。不得仅根据 `openspec status` 的 artifact `isComplete` 标记业务完成。
- 真正的任务勾选、验收标准和迁移/发布证据仍留在各 change；本页只维护跨 change 顺序和阻断项。归档、提交、推送或生产发布不因本页勾选而自动获得授权。
