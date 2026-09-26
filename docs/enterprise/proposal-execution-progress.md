# 企业化 proposal 执行顺序与进度

> 状态快照：2026-09-26，基于当前工作区的 `openspec list --json`、各 change 的 proposal/tasks 和执行证据。本文是跨提案的**排序与阻断项索引**，不是实施批准、任务完成证明或发布放行记录。任务完成数以各 change 的 `tasks.md` 为准；OpenSpec artifact 齐备不等于业务完成。已归档的六个历史 change 不再列入待执行队列。

> 后续授权：2026-09-26 用户已明确批准执行 `add-enterprise-oms-business-logic`，包括依赖提案重订与正式代码/迁移；五份重订后的依赖 change 已分别获批，旧 Token 费用/欠费目标获准退役但不归档/同步旧 spec。验证限隔离合成数据；真实租户数据、生产发布、归档和提交不在授权内。旧 change 的原版不得继续实施。

## 当前决策与执行原则

- 生产验收主线仍为 **M1/G1 固定租户运行与发布 → B1/B2/G2 可信多租户及 TMS → C1/C2/G3 完整 OMS**。规划、契约、原型和环境准备可提前并行；前置验收不通过时，不开放下游生产能力。
- DeepTutor 是本地部署产品；云端 OMS、TMS 分别构建和部署，共享安全的管理业务组件，不共享应用源码、数据权限或生产 fixture。OMS 是平台资源、服务供给、租户服务授权及赠送/充值配额的唯一写入权威；TMS 仅管理当前租户内部事务并只读配额与真实消耗。
- 取消旧租户 Token 售价、费用、欠费停机和 EduPlus2 独立“欠费模型资格”闭环。额度耗尽只拒绝对应服务的新调用，不能阻断登录、管理、历史或其他服务；EduPlus2 仍独占租户生命周期权威。
- 保持 `upstream/main` 可合并：企业专有逻辑优先放 `extensions/enterprise/`；核心仅允许经单独审阅的通用 seam，并在受影响 CLI、HTTP/WS、SDK、后台路径及身份、session ownership、审计关联上留回归证据。
- 旧 [02 实施总纲](02-rollout-testing-and-migration.md)、[11 入口](11-api-and-entrypoints.md)、[12 管理](12-platform-operations-admin.md) 中尚未同步的“单体 Web / OMS 只读 / TMS 可写配额 / Token 费用欠费”表述**不得作为新实施依据**；逐处修订列为下面的 P0 工作，不因本文新增而视作已修完。

## 执行波次与门禁

| 波次 | 工作与可并行范围 | 进入下一波的门禁 |
| --- | --- | --- |
| **P0：契约与进度收敛，现在并行** | OMS 业务契约及五份重订依赖 change 已分别获批；TMS 业务契约、两端开发态原型浏览器/组件验收、02/11/12 与入口文案逐处同步仍待完成。旧计费/欠费目标已批准退役但未归档/同步旧 spec。隔离合成数据下的正式实现/迁移已获授权，P0 本身不放行真实租户数据或生产上线。 | 新旧方案无冲突；原型任务与依赖未来生产实现的任务分清，不以 fixture 宣称真实能力；外部权限/事件契约仍须确认。 |
| **P1：M1/G1** | 完成固定租户 runtime 基线的确认门禁；继续 G1 各目标环境的真实 Ingress/TLS、EduPlus2、HTTP/WS、资源、LightRAG、回退、安全和证据验证。P0 的文档/原型工作可与之并行。 | M1 所需运行路径与目标环境 G1 门禁有真实证据；仅通过构建/部署或无 token 的 WS 负向探针不算完整登录与 turn smoke。 |
| **P2：B1/B2 身份与隔离** | 补齐覆盖最终 B1 接入和 B2 多租户可信绑定、RLS/资源/任务隔离的实施 change；先用真实首租户验证，再开放多租户。收敛 EduPlus2 lifecycle webhook，只保留租户状态与对账。外部契约准备可提前，但实施、生产开放受本波门禁约束。 | 首租户接入及双租户全入口隔离通过；签名事件、乱序/重放、恢复和本地隔离状态不被外部事件覆盖均有证据。 |
| **P3：平台公共数据面，可按依赖并行** | 先完成可信平台身份、动作权限及 OMS 管理 API 边界；随后全服务 Provider/Secret 生效链与逐调用 Token/非 Token 原生单位用量总账可并行。TMS 的本租户 client、资源授权、KB/文档纵向切片可在 P2 可信身份后并行，但不能预支 OMS 权益或使用假额度。 | 管理写入仅由受权 OMS 路径执行；旧云端管理旁路关闭；配置有执行者 active 确认；可信 usage 缺失时保留待核对，不按零结算。 |
| **P4：供给、权益、TMS/G2** | 以新 change 交付服务供给 → OMS 租户授权/统一赠送与充值配额 → 预留/真实调用/核对闭环；OMS 至少要有受控、可审计的授权与配额写入路径。再将 TMS 当前租户配额/用量只读投影、应用/client、成员/资源/Skill 权限和独立前端接入真实 API，完成 G2。 | 未确定 OMS 在 B2 前如何安全配置服务授权和额度时，**不得用手工改库或原型 fixture 放行 TMS/G2**；TMS 无配额写路由、OMS 专有字段或跨租户数据，额度耗尽只影响对应服务。 |
| **P5：完整 OMS/C1/C2/G3** | 数据面及平台权限稳定后，将独立 OMS 正式界面接入真实平台资源、供给、权益、用量、审计 API；先完成 C1 可用闭环，再完成 C2 治理和 G3。旧运营界面提案须按新 IA 重订。 | 五类资源、全服务配置、供给/权益/实际消耗及异常核对端到端通过；菜单、动作、API 权限一致；不出现旧费用/欠费功能。 |

**贯穿门禁：**任何波次若实际启用多执行者或要求高可用，应先补 G-H 变更并完成跨实例一致性、故障切换与回退验证；单实例须明示非 HA、容量和恢复目标。迁移、发布、真实外部系统变更和归档各按对应 change 与授权门禁执行。

## 活跃 change 逐项进度与下一动作

以下 `x/y` 是**任务勾选数的快照**，不是生产完成百分比；其中原型任务含依赖后续正式实现的门禁，不能为了关闭原型而提前勾选。

| Change | 当前状态 | 顺序、依赖与下一动作 |
| --- | --- | --- |
| [`add-ws-required-context-controls`](../../openspec/changes/add-ws-required-context-controls/tasks.md) | 23/23；OpenSpec 显示 complete，仍活跃 | 已实现的协议基线，不再排实施任务；复核证据后，归档须另获明确同意。 |
| [`add-m1-fixed-tenant-runtime-baseline`](../../openspec/changes/add-m1-fixed-tenant-runtime-baseline/tasks.md) | 32/33；仅余 V.5 确认/归档门禁 | P1：核对运行证据与当前 upstream 兼容性；不以任务数推断 G1 或生产上线完成。 |
| [`add-g1-woodpecker-k8s-release-baseline`](../../openspec/changes/add-g1-woodpecker-k8s-release-baseline/tasks.md) | 18/29；真实环境与异常/回退等仍有未勾项 | P1：在选定目标环境补全真实登录及 HTTP/WS turn、LightRAG、回退、安全与 release evidence；各环境分别标记 verified/unverified。 |
| [`add-c1-oms-operations-prototype`](../../openspec/changes/add-c1-oms-operations-prototype/tasks.md) | 18/29；开发态原型，非生产 OMS | P0：补浏览器审计、旧文档/提案重订；将未来生产依赖落实到正式 change，不用原型勾选替代真实验收。 |
| [`add-b2-tms-management-prototype`](../../openspec/changes/add-b2-tms-management-prototype/tasks.md) | 14/20；开发态原型，非生产 TMS | P0：补浏览器审计、文档/Skill 契约与实施提案衔接；保持生产原型路径 404。 |
| [`add-enterprise-oms-business-logic`](../../openspec/changes/add-enterprise-oms-business-logic/proposal.md) | 6/23；2026-09-26 已获实施授权，完成 PG/执行者/LightRAG 边界、当前管理入口审计及统一总账替代契约/基础迁移门禁 | 已有隔离合成 PG 六版基础迁移、内部赠送/充值授予及撤销、逐 attempt 预留/待核对/结算、Skill ZIP 纯校验与未装配的 OIDC 身份校验；受保护镜像缺配置/ASGI 覆写时失败关闭，旧云端管理路由负例和本地设置保留回归通过。旧费用/欠费目标获准退役但不归档。用户确认暂无 EduPlus2 OMS 平台权限契约，正式跨租户写 API 保持未开放。P3/P4/P5 真实执行者、权限、配置、API/前端闭环仍未实施，不把切片当上线验收。 |
| [`add-enterprise-tms-business-logic`](../../openspec/changes/add-enterprise-tms-business-logic/proposal.md) | 0/21；仅规划，未批准实施 | P0 与 OMS 固定共享 ID/授权/安全 DTO；获批后随 P2/P4 实施，配额视图依赖真实 OMS 授予和用量。 |
| [`add-b2-eduplus2-tenant-lifecycle-webhook`](../../openspec/changes/add-b2-eduplus2-tenant-lifecycle-webhook/proposal.md) | 1/11；2026-09-26 已获批准，新增签名 Webhook URL mock 接收切片 | 已完成隔离合成 HMAC/时效/大小/状态不变测试；测试 K8s Webhook Secret 已单字段更新并回读核对一致，Woodpecker tag Secret/preflight/deploy 同步链路已装配，但后端仍是旧镜像。尚未由 EduPlus2 控制台执行真实 demo。真实 `subscription.*` 版本/绑定/对账合同、PG inbox 和全入口准入仍待实现；OMS 额度不影响租户开停。 |
| [`add-b2-oms-platform-read-governance`](../../openspec/changes/add-b2-oms-platform-read-governance/proposal.md) | 0/8；2026-09-26 四份 artifact 已重订并获用户单独批准，未实施 | P3 先获得 EduPlus2 独立平台签发/权限契约及受控迁移，再实现跨租户 API；先于 Provider、权益写入及正式 OMS UI。 |
| [`add-enterprise-all-service-provider-settings`](../../openspec/changes/add-enterprise-all-service-provider-settings/proposal.md) | 0/9；2026-09-26 四份 artifact 已重订并获用户单独批准，未实施 | P3 先完成 EduPlus2 平台权限与 OMS attempt 准入，再实现版本化配置/逐执行者确认；本地 DeepTutor 设置不退化。 |
| [`add-enterprise-exact-token-usage-ledger`](../../openspec/changes/add-enterprise-exact-token-usage-ledger/proposal.md) | 0/9；2026-09-26 四份 artifact 已重订并获用户单独批准，未实施 | P3 完成硬上界预留、多服务执行证据与待核对；不依赖旧费用/欠费提案，供 P4 消耗结算。 |
| [`add-oms-token-billing-and-arrears`](../../openspec/changes/add-oms-token-billing-and-arrears/proposal.md) | 0/10；用户已批准退役旧目标，禁止按旧 tasks 实施 | 不归档、不同步冲突旧 spec；现行供给—权益—实际消耗以已批准 OMS change 为准。**不得沿用售价、费用或欠费字段。** |
| [`add-c1-c2-oms-operator-interface`](../../openspec/changes/add-c1-c2-oms-operator-interface/proposal.md) | 0/9；2026-09-26 四份 artifact 已重订并获单独批准 | P5 待平台权限和真实 API 稳定后接独立 OMS 正式前端，不把原型作为生产入口。 |

## 尚缺的实施 change 与当前阻断项

1. **B1/B2 完整接入与多租户底座：**已归档联邦访问 change 不等于 B1 最终接入、B2 真实多租户与 G2 完成。当前活跃列表没有覆盖完整可信租户绑定、资源隔离、租户自管理发布门禁的独立实施 change；需明确范围、与 lifecycle/TMS 的依赖并获批准。
2. **服务供给—租户权益/额度—实际消耗：**旧计费/欠费 change 已获准退役，不能重用为实施依据。已批准的 `add-enterprise-oms-business-logic` 与重订逐 attempt 用量 change 负责 OMS 独占写入、供给可授予量、赠送优先、并发预留、原生单位、未知用量待核对及跨入口服务准入；TMS 只读 DTO 需与尚未批准实施的 TMS 业务 change 对齐。G2 前须有安全可运营闭环，不能靠手工状态修补。
3. **旧实施文档冲突：**02/11/12 及旧路由说明仍需逐处重订；重订前使用本页和新 OMS/TMS 业务契约判断顺序，不能把旧里程碑文字当作权限或发布授权。
4. **外部与发布证据：**EduPlus2 发送端 lifecycle 契约、真实测试登录与 WS turn、各目标环境 G1 回退/异常、原型最后一轮浏览器审计均需对应证据；未验证项保持未完成。

## 更新规则

- 每次 proposal 获批、任务验证、被取代或归档时，同时更新本页日期、状态、依赖和下一动作；先核对 `openspec list --json` 与对应 `tasks.md`/执行证据，再更新数字。不得仅根据 `openspec status` 的 artifact `isComplete` 标记业务完成。
- 真正的任务勾选、验收标准和迁移/发布证据仍留在各 change；本页只维护跨 change 顺序和阻断项。归档、提交、推送或生产发布不因本页勾选而自动获得授权。
