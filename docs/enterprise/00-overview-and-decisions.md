# 00. 总体方案与决策记录

## 本次修订

2026-09-13：在三个业务里程碑、七个实施工作包基础上，明确采用“配置/现有扩展点优先 + 必要通用核心改造 + 独立企业扩展包/外壳”，RAG 已确定使用 LightRAG Server 并保留图检索，首发图后端采用用户 fork 的 HugeGraphStorage，A1/A2 完成生产实现与验收。目录统一为 `docs/enterprise/`，覆盖完整企业化而非仅 EduPlus2 对接，并明确 S3/PG/Secret/scratch 及知识库派生副本责任。已确认的企业管理入口为 `/tms`（租户管理）与 `/oms`（平台运营），专属管理 API 分别为 `/api/v1/tms/*`、`/api/v1/oms/*`；角色及 `tenant.*` / `ops.*` 能力 key 不改名。取消旧 Phase 0–5 / PG-0–5 过渡路线的决策不变，交付主线为：

```text
M1：A1 结构化状态 → A2 文件/检索 → A3 单租户 K8s 验收
    ↓ 复用相同存储、内部 ID、部署与 Store 接口
M2：B1 EduPlus2 单租户闭环 → B2 多租户及租户管理界面
    ↓ 复用已有租户治理 API 和权限模型
M3：C1 运营管理闭环 → C2 运营治理完善（管理所有租户）
```

**本文描述目标方案，不表示完整 PG/S3、多租户或集群部署已完成。** 首个身份/PG 会话切片已隔离验证；2026-09-13 用户进一步确认取消全部 local/SQLite 运行模式，默认 Web/CLI/SDK 必须连接 PG，见[全量迁移 proposal](../../openspec/changes/migrate-all-sqlite-state-to-postgresql/proposal.md)。该 change 已获准并处于实施/验收阶段，实际完成范围以 tasks 与执行证据为准。OpenSpec 是需求和验收主记录，[02](02-rollout-testing-and-migration.md) 是实施导航。

## 目标与边界

1. 先让现有单租户、多用户 DeepTutor 在 Kubernetes 上可用、可恢复，不等待 EduPlus2 接入或新运营后台。
2. 第一阶段直接替换上线功能使用的 SQLite/文件型持久化为 PostgreSQL/S3-compatible，不先做一个稍后扔掉的 PVC/SQLite 生产版本。
3. 第二阶段在同一套部署、数据与代码上完成多租户隔离和租户自管理；管理界面基于现有 DeepTutor 页面微调，不为每个租户维护一套代码或 Deployment。
4. 第三阶段新增跨租户运营管理后台，与租户管理界面并存。
5. EduPlus2 是外部身份、组织和业务权限主数据来源；DeepTutor 管理自己的 AI 资源、使用策略和运行状态。
6. 保持官方 upstream 可更新性；通用 PG 基础/Store 下沉 core，企业特有集成/S3 资源治理保持独立包；不反向依赖企业包或复制数据库，不为追求源码零 diff 新增文件型存储或运行时补丁体系。
7. 首发包含 Woodpecker 自动交付：A1 起并行开发，A3/G1 实跑验收；后续复用同一镜像晋级、迁移、部署和回退流程。

不纳入本次交付路线：POC、复合 user_id 软隔离、每租户独立 DeepTutor 部署、新的 `data/tenants` 多租户文件后端、schema-per-tenant、生产双写、整套 EduPlus2 管理功能重建。取消 local/SQLite 存储 profile，但保留连接 PG 的本机/CLI/SDK 使用方式。企业托管检索确定使用 LightRAG Server，按固定 workspace 使用受控实例池；WeKnora 不在首发实施范围；复用用户 fork 的 HugeGraph 支持。自建 LightRAG 动态多 workspace 服务层不在默认范围，不建设两个完整生产后端。

**依赖关系**：DeepTutor 直接依赖应用 PostgreSQL、S3 和 LightRAG Server API；LightRAG 内部依赖检索 PostgreSQL 与 HugeGraph。图连接/凭证/schema/图操作归 LightRAG 及其部署运维，不进入 DeepTutor 业务 Store、binding 或 API client。下文 PG/HugeGraph/S3 的并列仅指联合交付与恢复范围，详见 [06](06-postgresql-native-store-plan.md#依赖层级与责任边界)。

## 已采纳决策

| 决策 | 约束 | 落地阶段 |
| --- | --- | --- |
| D1 直接替换、逐阶段发布 | 每个领域按“新实现→接入真实调用→验证→一次切换”执行，不把半替换状态发布生产 | 全阶段 |
| D2 单一生产存储底座 | PG 存业务状态及检索 KV/vector/doc_status，HugeGraph 存图，S3-compatible 存文件；普通 scratch/cache 可丢弃；禁止自动回退 SQLite | 阶段一 |
| D3 单租户先上线 | 固定一个内部 `tenant_id`，可有多个本地用户；不提供租户切换、批量开通或 EduPlus2 登录 | 阶段一 |
| D4 身份 ID 稳定 | 内部 tenant/user ID 与外部 `tid/eui` 分离；阶段二只绑定映射，不搬存储或重写对象 key | 阶段一预留，阶段二绑定 |
| D5 PG shared tables | 应用租户表从第一阶段带 `tenant_id` 与 RLS；平台表分开；独立 RAG 索引按 06 的 provider namespace/数据库防线管理，不采用应用 schema-per-tenant | 阶段一 |
| D6 认证权限不后补 | 阶段一保留受保护本地登录；阶段二完成 Handoff/OIDC、业务态、权限 API、撤权和租户隔离再开放第二租户 | 阶段一/二 |
| D7 两级管理界面 | TMS `/tms` 复用现有页面：M1 固定租户，B2 完成多租户自管理；OMS `/oms` 在 C1/C2 交付，治理 API 在 B2 先到位；共用服务，不共用越权角色 | 阶段一至三 |
| D8 管理员边界 | 学校管理员只能成为 `tenant_admin`；运营角色明确区分 `platform_admin/operator/auditor`，不默认读取租户私有对话和文件 | 阶段二/三 |
| D9 可更新性 | 通用 PG 实现/迁移在 core，企业逻辑/资源治理位于独立 `deeptutor_enterprise` 包；共用数据与协议，受控 fork 补丁可贡献 upstream | 全阶段 |
| D10 可用性独立于租户数 | H 按容量/可用性目标触发；多执行者/HA 发布前必须 G-H，单执行模式需明确非 HA 与恢复目标 | 跨里程碑 |
| D11 里程碑与工作包分开 | A1/A2/A3、B1/B2、C1/C2 七个集成验收包，不等于七次生产上线 | 全阶段 |
| D12 准备活动提前并行 | K8s 集成环境、外部注册/契约从 A1 开始；B1 验证最终接入后 B2 才开放多个租户 | M1/M2 |
| D13 首发包含 CI/CD | Woodpecker 归 A3 必交付子环节，从 A1 并行；同 digest 晋级、受控批准、迁移/部署/smoke/回退验收 | M1 交付，全阶段复用 |
| D14 扩展而非厚重重写 | 配置→现有注入/插件→通用核心 seam；不把代理/SDK/同名插件视为完整接管，不采用全站 monkey patch | 全阶段 |
| D15 已选 LightRAG，验收后上线 | 企业首发使用用户 LightRAG fork + HugeGraphStorage，保留图检索；WeKnora 不在首发范围。真实教材、成本/容量、生命周期、安全与恢复未验收通过不得发布 | A1/A2，G1 阻断门禁 |
| D16 显式检索隔离 | 授权后按内部 tenant/KB/index-version binding 解析远端租户/KB 或 workspace；服务 RBAC、名称、workspace 不能替代 owner/grant 或数据库防线 | M1 契约/双租户与跨用户负例，M2 放量 |
| D17 文件权威与分类 | S3 存持久文件及动态 skills/personas 正文，PG 存业务状态和 memory/notebook 正文；服务派生副本登记责任/配额/删除，凭证与临时文件分别进 Secret/scratch | A1 契约，A2 闭环 |

### 跨系统边界收敛

本轮进一步确定六类职责，完整责任矩阵见 [06](06-postgresql-native-store-plan.md#跨系统责任矩阵)：

- 业务任务由 DeepTutor 协调，LightRAG 负责远端执行/队列/取消确认；单任务操作不得扩大为 workspace 操作。
- 聊天模型与检索 profile、Secret 和内部限额分离，业务账本按远端遥测对账；取消/超时不盲目释放远端预留。
- 企业 S3 原文为权威输入，原始文件交给检索侧统一解析；索引解析组件唯一管理 S3 派生空间，应用只协调/登记/授权。
- 首发由独立运维预开并登记固定 workspace 实例，应用原子分配和绑定；池不足显式等待/失败，不新增应用 K8s 管理权。
- 外部资格、本地启停和初始化状态独立保存，最终准入取交集；事件同步不得覆盖本地暂停。
- 租户成员身份必须叠加个人资源 owner/已支持的显式 grant 校验，不以角色或 RLS 代替用户级授权。

这些是待实现契约；不改变三个里程碑、七工作包和 90 项未完成任务，也不把当前 fork 静态源码核对或历史评估当作新能力已交付。

### 多租户从首发设计，不等于首发开放多个租户

A1 固定 tenant/KB/index-version、私有/共享资源授权及图权限粒度，A2/G1 在测试环境验证双租户及同租户两用户负例；B1/B2/G2 才开放真实多租户。HugeGraph 的 scope 是逻辑分区，不是 ACL；受限图身份、REST/Gremlin 越权拒绝和 PG/S3/图成套恢复是首发阻断项。已有 fork 代码不等于通过生产验收，详细门禁见 [06](06-postgresql-native-store-plan.md)。

### 单租户不等于过渡部署

第一阶段的 PG、HugeGraph、S3、部署清单、内部租户 ID、Store 接口和用户数据全部保留到后续阶段。改变的是允许的租户数量、身份来源及管理界面，而不是重新建设底座。保留一个固定租户是发布范围约束，不是按租户复制实例。

是否单执行者取决于已确认容量与可用性目标，不取决于是否单租户。单执行模式必须声明非 HA、维护窗口与在途 turn 中断行为。若首发或后续任一发布需要高可用/多执行者，H 工作线先完成 G-H；不能依赖 sticky session 冒充正确性，也不能因为“还没到第二阶段”推迟必要可靠性。

### 核心与企业包职责

[13](13-deployment-and-upstream-sync.md) 统一定义包布局、现有扩展点和必要核心变更。`deeptutor_enterprise` 首切片包已存在；后续通用 PG 下沉 core，默认入口与企业外壳共用数据/协议，企业治理独立。原有教学能力和 HTTP/WS 产品语义须保持。租户 UI 做必要适配，运营 UI 可以独立构建，但两者共用治理服务。不以完全重建应用层换取上游文件零修改。

[06](06-postgresql-native-store-plan.md) 统一定义已选 LightRAG 路线、上线门禁、授权/文档责任与实例池；[07](07-resource-isolation.md) 定义文件分类。历史评估不再作为二选一实施分支，选型决定也不代表完整产品交付；PG/S3、个人默认私有、源文下载、故障恢复和 G1/G2 标准不降低。

### 管理入口命名

TMS 为 Tenant Management System（租户管理系统），OMS 为 Operations Management System（平台运营管理系统），后者不指订单管理。企业目标入口、专属 API 与阶段边界以 [11](11-api-and-entrypoints.md) 为准，权限矩阵见 [12](12-platform-operations-admin.md)。现有 `web/app/(admin)/admin` 仍按源码基线引用，不能误写为已存在的新路由；路径调整不新增角色、不改变可信 scope，也不迁移聊天/资源等通用 API。

### 存储接口的价值不是维护双轨

`SessionStore/SettingsStore/GrantStore/IdentityStore/ResourceStore/ObjectStore` 隔离业务与后端技术，是最终架构的一部分。生产应用状态/文件仅选择 PG/S3，检索图使用 HugeGraph；不新增 `FileIdentityStore`、文件 Webhook 缓存等企业 fallback。SQLite 只允许独立离线导入源读取/旧格式 fixture，默认入口和运行态临时缓存均不例外。

## 里程碑范围

| 阶段 | 必须交付 | 明确不等待 | 发布门禁 |
| --- | --- | --- | --- |
| 一：单租户 K8s | 存储全链路替换、固定租户、认证、多用户原有功能、K8s 清单、Woodpecker 流水线、备份恢复、故障可观测 | EduPlus2、多租户 UI、统一运营后台 | G1：已启用功能无本地持久化依赖，重建 Pod 数据保留且受控流水线实跑通过 |
| 二：多租户 | EduPlus2 对接、隔离、撤权、租户共享资源、现有管理 UI 微调、配额执行；多执行模式另受 G-H 约束 | 统一运营后台 | G2：B1 首租户闭环 + B2 两租户正负向端到端通过 |
| 三：统一运营 | 租户生命周期、套餐/配额/模型分配、用量、审计、运行任务治理、运营角色 | 重建用户组织主数据系统 | G3：运营操作与实际执行一致，角色/入口/API/审计闭环 |

权限、配额、审计以及必要管理 API 在 B1/B2 先落地；C1/C2 负责运营产品化，不把关键安全控制延期。C1 可发布运营基础能力，但 M3 完成仍要求 C2；不以中间工作包验收替代全部发布门禁。详细任务和并行依赖见 [02](02-rollout-testing-and-migration.md)。

## 成功标准

- 每阶段有独立可发布版本；下一阶段复用上一阶段数据与基础设施。
- 第一阶段无 PG/S3 不可用时静默降级、无共享 SQLite 主库、无明文凭证下放。
- 第二阶段一个部署服务多个租户，每租户原有界面只显示和管理自己的资源，伪造 ID/跨 Pod/后台任务不能越权。
- 第三阶段统一后台管理所有租户，但不成为绕过 EduPlus2 或租户隐私权限的超级入口。
- 每次替换有验证、数据切换、回退兼容说明；旧写路径退出生产，迁移工具只按真实存量需要提供。

流水线领域设计、接入契约、子环节及故障门禁见 [05](05-woodpecker-kubernetes-pipeline.md)。不新增业务阶段，也不将流水线开发留到统一运营后台之后。
