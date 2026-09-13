## Context

动机及本次批准范围见 [proposal](proposal.md)。同一产品连续替换 PG/S3 并对接 EduPlus2，仍须先单租户 K8s、再多租户和租户管理、最后统一运营；现有单个任务承载多个行为，且多副本被过度绑定于第二阶段。本次仅调整方案，新增企业包/外壳与 LightRAG Server 的实现边界，未实施。

## Goals / Non-Goals

对外按 M1/M2/M3 三个业务里程碑，对内按 A1/A2/A3、B1/B2、C1/C2 七个工作包推进；H 单列跨里程碑工作线。需求见四个 delta specs，技术细节由 [领域索引](../../../docs/eduplus2-integration/readme.md) 展开，主依赖和门禁见 [02](../../../docs/eduplus2-integration/02-rollout-testing-and-migration.md)。不创建平行 Superpowers 计划。领域文件按准备、M1、M2、两级管理和持续维护重排为 00–13；A3 内按环境/流水线开发→集成验收→生产放行→实际发布排序，业务范围和并行依赖不变。

不建设过渡部署、生产双写、临时认证网关、文件型多租户后端或每租户独立代码；不因拆分省略原有范围，也不把 C1 基础运营当作完整 M3。

## Decisions

1. **七个工作包而非七次上线**：A1 PG 真实行为、A2 文件/完整检索独立验收，A3 合并 G1 后发布；B1 单租户接入验证后 B2/G2 才放开多租户；C1 可发布基础运营，C1+C2/G3 才算 M3。相比只拆技术层，此划分能尽早发现链路失败。
2. **准备提前但发布不抢跑**：A3 的 Woodpecker 开发/K8s 清单/集成环境和 B1 的外部注册/测试账号/权限契约准备从 A1 并行。无需等待全部存储完成才首次部署，也不以测试环境半替换状态冒充生产版本。
3. **基础契约稳定以支持并行**：A1 先固定内部 tenant/user、resource/index namespace 和 Store/metadata 契约；A2 随后并行开发，最终验收依赖对应 PG 实现。外部 tid/eui 只作绑定，不改对象 key 或用户所有权。
4. **B1 是最终集成而非 POC**：使用同一 adapter，在一个真实租户验证认证/具体权限/业务访问/撤权/必要事件，再扩大租户集合。不能先放行 token、把权限或撤权安全依赖留到 B2。
5. **可靠性工作线 H 独立**：按已确认容量/可用性/恢复目标选择单执行或多执行模式。单租户 HA 可触发 G1 前置 G-H；多租户接受非 HA 且容量足够时不强制第二 Pod。多执行者（包括多 worker）前必须完成 durable commands、lease/fencing、跨 Pod 控制、故障/额度一致性及依赖可用性验证。
6. **运营安全先于报表**：B2 有带可信平台身份/具体能力/目标租户绑定及默认运维授权的管理 API、配额/模型执行与审计；C1 从首版具备完整操作权限和基本审计，C2 只扩展治理/查询/导出。租户与运营界面并存，平台人员无默认私有内容/冒充能力。
7. **行为闭环任务**：每个可独立审查任务包含适用迁移/约束、真实 UI/API/tool/worker、权限/失败/并发测试和切换；独立用户行为过多再拆。基础设施任务通过真实集成验证，不用演示或 mock 勾选。
8. **状态治理不变**：DeepTutor 迁移角色/运行角色分离；外部 OpenFGA/Keycloak 变更走 EduPlus2 provider migration。上游 local 模式仅独立使用，不新增企业 fallback，不为文档任务执行运行态变更。
9. **流水线是首发交付**：A3 内按接入、CI/生产镜像、制品发布、受控晋级、迁移、部署、smoke/回退细化，A1 并行启动，G1 前在目标 agent/集群真实验收。默认 Woodpecker + Kustomize/kubectl，不新增 GitOps 平台前置；后续复用同 digest 晋级，见 [05](../../../docs/eduplus2-integration/05-woodpecker-kubernetes-pipeline.md)。
10. **发布具备独立安全边界**：PR 不持有发布凭证；服务端批准绑定环境/digest/执行人，能力不足时采用受保护交付入口。环境互斥与当前版本检查覆盖迁移至回退/验证，agent 中断必须对账。迁移 Job 复用 A1 实现；单执行模式不能滚动重叠，多执行者/HA 先过 G-H。应用回退不能自动降库或恢复旧文件后端。
11. **配置与扩展优先，核心必要补丁**：复用 `deeptutor.extensions`、ToolRegistry、容器/SessionStore 注入；它们不接管全站直连 SQLite/文件或 auth。企业实现放 `extensions/enterprise/src/deeptutor_enterprise/`，核心只补通用 provider/scope/授权/application lifecycle 并收敛真实调用。不选全站 monkey patch、仅 SSO/iframe 或厚外壳重建全部应用层；不承诺固定补丁行数。
12. **LightRAG Server 保留为默认引擎**：保持 `/query` + `only_need_context=true`，DeepTutor 生成最终回答；企业 binding/client seam 从 PG/Secret 取连接及可信 scope，RagGateway 查询前授权。原版固定 workspace Server 由受控实例池提供隔离语料，多个 KB 名称/URL 别名不构成隔离，不假设 header 可动态切换一个实例的 workspace。实例池仅为检索子系统，不是按租户复制整套 DeepTutor；动态多 workspace 服务不在默认交付内。
13. **文档与索引分层负责**：企业 RagDocumentService 管理 S3 原文/解析物、PG binding/job/配额、远端 doc/track ID、索引完成对账、引用授权、托管删除与重建；非托管外部连接保留只解绑语义。当前原版 pipeline 只负责检索，不能把接通 URL 当作 A2 已完成。
14. **检索 PG 不等于自动隔离**：KV/vector/doc_status/graph 全部外置，锁定 Server 与图后端版本。应用表维持 tenant/RLS，独立检索 workspace 表/图另有受管隔离迁移、绑定实例凭证、低权运行/迁移角色和数据库拒绝验证。优先评估固定版本的 `PGTableGraphStorage`，不支持时评审 AGE 的 `PGGraphStorage`，不静默回退文件或降低数据库防线；完整约束见 [06](../../../docs/eduplus2-integration/06-postgresql-native-store-plan.md)。
15. **组合装配与升级门禁**：自有启动器在接流量前完成企业 providers/路由/lifecycle 装配和版本预检，禁止原生未适配入口旁路；core/企业包/前端/Server/存储和 binding 版本共同锁定与验收。租户 UI 必要微调，运营 UI 可独立构建但共用治理后端；补丁与包契约见 [13](../../../docs/eduplus2-integration/13-deployment-and-upstream-sync.md)。

## Risks / Trade-offs

- [A1/A2 并行接口漂移] → 先固定稳定 ID/metadata/Store 契约，再分工；双方共同完成对象状态/配额集成。
- [现有注入点被高估] → A1 登记真实调用和 core/企业包责任；direct SQLite、settings JSON、后台默认容器必须逐项接入，不能只替换工厂。
- [Server 接通被当作完整 KB] → A2 覆盖托管导入→状态→召回→授权源文→删除/重建、S3/PG/远端对账，不把 pgvector 当整套检索替代品。
- [固定 workspace 实例池成本] → A1 确认 KB/版本规模与连接/内存预算，A2/A3 验证开通/回收和单 workspace 写互斥；容量不足先评审，不把不同可见语料合图或直接启用未经验证的多 workspace 代码。
- [主分支图后端/权限假设] → 生产锁定版本，验证实际类/扩展、启动 DDL、低权账号、RLS/图权限和恢复；只有 workspace 参数不算数据库防线。
- [外部资源误删] → PG 明确托管权，旧外部连接仅解绑，显式核对移交后才允许生命周期管理。
- [首发功能无限扩张或被偷偷删减] → A1 明确上线能力清单和必需高级能力，未经确认不改变完整范围。
- [外部配置晚到] → 注册/契约准备从 A1 并行，不等 M1 上线才开始协调。
- [单执行模式被当作已满足 HA] → 记录业务/运维确认、维护窗口、恢复和压测证据；目标触发后 G-H 作为发布前置。
- [对象/数据库非原子] → A2 就完成 pending/ready、对象配额预留/核算/释放与补偿；B2 再扩 token/并发治理。
- [工作包发布被误标里程碑完成] → B1/G3a 只是中间交付，M2 要 G2，M3 要 C1+C2/G3；未做 H 任务保持待触发/未完成。
- [Docker 镜像与生产配置不匹配] → 适配现 JSON 入口与合并启动，验证独立前后端、PG/Secret、非 root 和 scratch；不以推镜像成功当作可部署。
- [CI 凭证泄露/伪造晋级] → 服务端来源/批准边界、环境隔离、最小权限及负例验收；不将可改 YAML 当作授权。
- [旧构建覆盖/迁移中断] → 环境锁、版本 CAS/状态校验、数据库迁移锁及 Job 对账；失败停止，兼容范围内回退。
- [官方更新带回旧写路径] → 全程执行已上线 G1/G2/G3 及适用 G-H 回归，检查新增 tools/capabilities，不等待上游合入才上线。

## Migration Plan

A1 同步固定通用 seam/企业包依赖及 LightRAG binding 契约，初始化稳定内部 ID；无存量直接初始化，有存量在 A3 使用只读导入、归属校验、备份、停旧写一次切换 PG/S3。B1 幂等绑定原 tenant/user，B2 添加其他租户但不迁移现有存储；C1/C2 复用治理/审计底座，仅增加所需运营能力。

目标有新写入后不得直接切回旧 SQLite。回滚兼容应用或停写按经演练的 PG/S3 成套备份恢复，记录 RPO/RTO。通过 Woodpecker 同一制品清单执行各次发布，批准/构建/迁移/rollout/smoke 可追溯；正式发布必须满足流水线 spec，不因文档校验通过而标记实现。各次发布记录工作包范围、镜像/upstream/schema、目标运行模式、门禁证据和回退兼容范围；使用多执行者的发布必须有有效 G-H，不因租户数量少而豁免。

LightRAG 存量按托管权确认：已有合规外置索引核对 namespace/模型/图后端/原文映射后登记，不无条件重建；本地文件索引按真实需要只读导入或从 S3 重建。Server 存储切换不能只换变量后假设旧数据自动出现，迁移/重建产生新 index-version，ready 验证后原子切 binding。回退同时考虑应用 PG、检索 PG/图、S3 和绑定/凭证/权限版本，不隐瞒重建耗时及模型成本；这些流程仍归 A1/A2/A3，不增加过渡发布。
