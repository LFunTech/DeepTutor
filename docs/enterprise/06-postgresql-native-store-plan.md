# 06. 企业 PG/S3 Store 与 LightRAG Server 接入计划

## 现状与交付定义

当前显式企业 provider 已能提供 PG 身份/文本会话。用户已取消默认 local/SQLite 兼容；[全量 PG-only change](../../openspec/changes/migrate-all-sqlite-state-to-postgresql/proposal.md)已获准并正在逐项实施/验收，覆盖 SQLite 领域、默认入口与间接 SDK 存储，实际完成范围以该 change 的 tasks 与执行证据为准。**不是改 DATABASE_URL 或只建新增表就完成替换。**

本文件不再有 PG-0–5 独立路线：A1 替换结构化状态，A2 替换文件/检索并在 A3 汇总验收 M1；B1 验证首租户外部身份闭环，B2 完成多租户治理；C1/C2 分批增加统一运营能力。主顺序见 [02](02-rollout-testing-and-migration.md)。

## 实现位置与接入责任

通用 PG 连接/迁移/身份与业务 Store 从首切片提取到 core，目标目录 `deeptutor/persistence/postgres/`，默认发行物直接支持 PG；企业特有资源管理和 RAG adapter 仍位于独立 `extensions/enterprise/src/deeptutor_enterprise/`。复用同一 schema 历史/ID/数据，不让 core 反向依赖企业包，详见 [13](13-deployment-and-upstream-sync.md)。已有容器/SessionStore 注入优先复用，但不得漏掉直接 SQLite、JSON、PathService、默认单例和渠道间接存储路径。

**技术选型已确定：企业首发使用用户维护的 [LFunTech/LightRAG fork](https://github.com/LFunTech/LightRAG)（provider 仍为 `lightrag-server`），通过 `HugeGraphStorage` 将图存入现有 HugeGraph；KV/vector/doc_status 使用 PostgreSQL，持久文件使用 S3。保留图检索，由 DeepTutor 生成最终回答。生产集成与验收尚未完成。** WeKnora 不建设首发生产分支；PGTableGraphStorage 只保留历史评估与上游兼容，不是首发默认或故障 fallback。既有 [Docker 评估报告](evaluations/2026-09-13-rag-services.md) 保留为历史证据，不因选型决定将合成语料测试升级为教材质量或上线资格证明。

## 依赖层级与责任边界

**HugeGraph 是 LightRAG Server 的内部图存储依赖，不是 DeepTutor 业务层直接依赖。检索 PostgreSQL 同样由 LightRAG 管理；不可与 DeepTutor 应用 PostgreSQL 混为一套业务 Store。** 本文保留图技术细节，是为了说明检索服务的交付及验收责任，不是要求 `deeptutor_enterprise` 实现 HugeGraph client、Gremlin、图迁移或图运维后端。

下图限定持久存储与检索数据面；聊天/教学模型、M2 EduPlus2 身份集成等依赖另按各自契约接入。

```text
DeepTutor（含企业 backend、RagGateway、文档 worker）
├── 应用 PostgreSQL：业务状态、授权、binding、持久任务
├── S3 业务空间：权威原文、附件和 DeepTutor 持久产物
└── LightRAG Server API（用户 fork，固定 workspace 实例池）
    ├── 检索 PostgreSQL：KV、vector、doc_status
    ├── HugeGraphStorage → HugeGraph：实体、关系、图遍历
    ├── 检索模型：抽取、embedding、检索内部调用及可选 rerank
    └── 检索解析/任务组件 → S3 服务派生空间及实际必需队列
```

| 责任主体 | 管理范围 | 禁止越界 |
| --- | --- | --- |
| DeepTutor / 企业包 | tenant/owner/grant、业务 binding、S3 原文/产物、调用 LightRAG API 导入/查询/状态/删除/重建、引用授权和业务任务对账 | 不持有检索 PG/HugeGraph 运行凭证，不导入图 driver，不直连图/检索库读写或补偿；不执行 Gremlin、图 schema、图存储 drop 或屏障清理 |
| LightRAG Server / fork | 固定 workspace 的检索状态、文档级索引生命周期、PG/图适配、图查询/删除、内部一致性及错误/状态上报 | 不替代 DeepTutor 用户授权，不把图数据库连接暴露为调用参数，不把未完成索引返回为 ready |
| LightRAG 部署运维 | 检索 PG/HugeGraph 地址、graph locator、存储 Secret/ACL/schema、实例配置、初始化/迁移/备份恢复、图写不确定状态处理 | 使用独立身份/Job/网络边界；不把图高权操作放入 DeepTutor 业务进程或普通 OMS 任务按钮 |
| 联合交付流水线 | 编排各责任方的固定制品、独立迁移和备份恢复，核对业务 binding 与检索部署版本一致，执行端到端验收 | 共用发布清单不等于共用凭证或让应用直接管理所有数据库 |

应用 PG 与检索 PG 可以共享集群地址，但必须分离库/表授权和运行身份；数据库侧拒绝 DeepTutor 身份访问检索数据，不强制两者具有不同 TCP 地址。HugeGraph 则对 DeepTutor 业务工作负载关闭直连网络通路。

DeepTutor 的 `rag_bindings` 仅引用检索服务部署，不解析该部署内部的 PG DSN、HugeGraph URI/graph/graphspace 或图凭证。内部存储映射由 LightRAG 部署记录维护，发布时按受控引用核对；不在用户请求中动态切换进程环境。

健康、图故障及待恢复状态通过 LightRAG 已验证的服务 API/受控状态接口传递给 DeepTutor；状态缺失或不确定时保持业务任务未 ready 并阻断重试/发布。若当前 API 无法表达所需状态，在 LightRAG 服务边界补齐受控状态契约并验收，不通过 DeepTutor 直查 HugeGraph 绕过。图库探测和内部故障定位属于 LightRAG/运维。

### 跨系统责任矩阵

以下按业务协调、实际执行、状态权威和凭证划界，不要求每行新增一个微服务；缺少必需服务契约时在责任方补齐并验收，不让 DeepTutor 直连内部依赖代偿。

| 边界 | DeepTutor 责任 | 其他责任方与交接 | 禁止混用 |
| --- | --- | --- | --- |
| KB 原文与索引解析 | 原文资产、授权、提交及引用映射 | LightRAG 检索链执行解析/OCR、切块、索引；其解析组件唯一写删 S3 服务派生物并上报 manifest | 不维护两套索引解析权威；聊天附件等非 KB 解析仍归 DeepTutor |
| 聊天与检索模型 | 聊天/教学模型、业务可用范围和配额账本 | LightRAG 执行独立检索 profile、持有相应模型 Secret、执行内部限额并上报用量 | 聊天偏好不改变已有索引模型；入口 QPS 不替代内部限流 |
| 业务 job 与远端执行 | 授权、operation ID、业务状态、取消意图与对账 | LightRAG 掌握索引实际状态、内部队列/重试及取消确认 | 本地任务结束不等于远端停止；单文档取消不映射整 workspace 取消 |
| KB 与实例生命周期 | 业务 KB、资源申请、原子领取已登记部署并建立 binding | 独立部署运维预开实例、登记验收记录、补池与回收；交接服务契约/配置版本和分配结果 | 创建 KB 不获得 K8s、检索存储或部署 Secret 管理权 |
| 外部资格与本地启停 | 本地启停、初始化状态、最终准入判断 | EduPlus2 是外部资格/订阅权威；同步只更新对应来源字段，见 [03](03-tenant-scope-schema.md#租户状态的独立来源) | 外部 active 不能覆盖本地暂停；本地恢复不能改外部资格 |
| 租户身份与资源授权 | 所有入口校验 tenant/user scope、owner 或该资源已支持的显式 grant | EduPlus2 提供外部身份/业务权限，不能替代本地资源归属；见 [09](09-authorization-and-grants.md#权限检查策略) | tenant member、tenant_admin 或平台运营身份不默认获得个人内容 |

模型、内部预算和用量的完整契约见 [07](07-resource-isolation.md#聊天模型与检索模型分离)；租户状态与私有资源规则从底层 Store 到 API/工具/worker 一致执行。

## 已选路线、历史对比与上线门禁

### 当前代码兼容范围

`deeptutor/services/rag/factory.py` 注册了下列 8 个 provider，源码 `DEFAULT_PROVIDER` 仍为 `llamaindex`。它们是接入能力，不表示都已满足企业生产契约。

| Provider | 当前接入形态 | 本方案定位 |
| --- | --- | --- |
| `weknora` | 自托管服务，查询携带 knowledge_base_id | 历史对比对象；保留上游兼容，不建设首发企业实现 |
| `lightrag-server` | 外置 LightRAG，启动时固定 workspace | 企业首发已选服务，使用用户 fork 的 HugeGraphStorage |
| `llamaindex` | 本地向量/BM25 pipeline | 不是现成外置服务；服务化与企业存储适配需要另行投入 |
| `lightrag` | 本地 LightRAG 引擎 | 不等于 Server；不默认自建动态多 workspace 服务层 |
| `graphrag` | 本地 Microsoft GraphRAG | 不是现成托管知识库服务，不作为本轮优先候选 |
| `pageindex-oss` | 本地文档结构索引 | 特定文档场景候选，不直接承担通用企业 KB 底座 |
| `pageindex` | PageIndex Cloud | 外部服务连接，不符合本期自托管索引的默认方向 |
| `ima` | 腾讯 IMA 外部知识库连接 | 可保留外部资料源，不冒充自管 PG/S3 生产底座 |

RAGFlow/Dify 等未在该工厂注册，不列为现成兼容服务；本轮不扩大为全市场选型或新增适配开发。

### 选择理由与范围

1. **图检索进入实际调用路径**：固定 v1.5.7 + `PGTableGraphStorage` 已做真实导入、图上下文、固定 workspace 边界和空 scratch 恢复测试。WeKnora v0.8.0 的当前 `knowledge-search` 接口未走图，企业接入需额外改造；因此选择 LightRAG Server，不并行建设两个生产后端。质量失真反例与测试限制仍见 [评估报告](evaluations/2026-09-13-rag-services.md)。
2. **复用用户已经增加的 HugeGraph 支持**：本地 `~/Projects/LightRAG` 的用户 fork 已包含并注册 `HugeGraphStorage`，不再按“需从零开发适配器”排除 HugeGraph。企业层负责装配、发布和验收，不重新实现图适配。现有 HugeGraph 的连通记录与旧 PG 图测试不代表此新组合已通过权限、质量、容量或恢复验证；更换后端必须受控重建，不能只改配置或自动回退 PG 图。
3. **选型确定不降低验收标准**：最终用户授权、个人 KB 默认私有、撤权、S3 原文、数据库强制隔离、低权运行与完整删除/恢复仍必须交付。workspace/API key 不能替代 DeepTutor owner/grant、PG RLS 或 HugeGraph 服务端权限。实例池容量不达标须解决或显式评审架构变更，不能合图、禁图或自动换服务。
4. **保留兼容，不建设另一套企业实现**：上游其他 provider 与已有非托管连接可按明确范围保留，不删除现有 adapter，也不把既有 binding 自动改成 LightRAG；移交托管前验证语料归属。更换已选服务需另行批准，不作为 A2 的默认二选一任务。

### 生产验收证据与阻断条件

| 时点 | 必须记录和验证 |
| --- | --- |
| 已完成的决策 | 服务确定为用户 LightRAG fork + HugeGraphStorage；WeKnora/PG 图不建设首发实施分支。仅确认路线，不代表下列实现或门禁完成 |
| A1：需求与预算 | 建立真实教材/问答集，确认公式/表格/图片/跨文档、KB/保留索引版本规模、延迟/吞吐/成本及恢复目标；固定多租户/同租户私有 KB 的授权边界和图隔离方案，不凭空填写阈值 |
| A1–A2：质量与版本验证 | 锁定包含 HugeGraphStorage 的 fork release/commit/digest、HugeGraph 版本/schema/认证与模型和解析配置；验证引用定位、召回、图事实忠实性、摘要冲突、图检索消融、导入成本和查询负载，不能以五问字符串命中代替正确性 |
| A2：接入就绪评审 | 验证固定 workspace 实例池容量、PG 三类存储 + HugeGraph 图、初始化/受控迁移/低权运行和企业安全适配可行性，锁定最终集成配置及必需组件；不再比较并选择另一个 provider |
| A2：最终路径与完整契约 | 真实企业入口验证上传→索引 ready→图检索→授权源文→删除→新版本重建；双租户与同租户两用户负例、撤权、PG/图数据库拒绝、同名实体/跨库遍历、scope 删除边界、写超时/迟到提交、Pod/依赖故障和成套备份恢复；B2 完整 G2 复验 |
| A2 验收 → A3 发布 | 发布记录绑定已选服务、实际版本/图/解析及必要队列拓扑、原文/副本责任、质量/容量/权限/恢复证据。缺证据或硬约束不满足阻断 G1，修复后重验；不能因选型已确定直接发布或自动 fallback |

2026-09-13 旧版 LightRAG + PG 图的本地工程测试只是历史基线，四份合成短文不是真实教材评测，也不是 fork + HugeGraph 的新组合测试。固定版本、原始观测与局限见 [实测结果](evaluations/2026-09-13-rag-services-results.json)；A1/A2 的完整任务仍未完成。

## 接口边界：生产只有一套实现

| 接口 | 生产实现/责任 | 替换时点 |
| --- | --- | --- |
| SessionStore | PG sessions/messages/turns/turn_events、事件顺序/事务 | 阶段一 |
| IdentityStore | PG 内部用户、本地认证；阶段二附加外部身份映射 | 阶段一/二 |
| SettingsStore | PG 配置/model metadata/version，凭证仅 Secret 引用 | 阶段一 |
| GrantStore | PG 用户/资源授权，租户复合键 | 阶段一 |
| ResourceStore | PG memory/notebook 正文与各资源 metadata；可编辑 skills/personas 正文统一走 S3，不因大小切换权威 | 阶段一 |
| AuditStore | PG 脱敏业务审计；日志平台作检索副本 | 阶段一 |
| ObjectStore | S3-compatible 流式内容读写、短时 URL、对象状态补偿 | 阶段一 |
| RagBindingStore / RagGateway | PG 保存 tenant/KB/index-version→provider/受控服务 endpoint/远端租户及 KB 或 workspace、API Secret 引用/契约版本及部署引用；查询前授权 | 阶段一；B2 多租户复验 |
| RagDocumentService / IndexJobStore | 管理业务 S3 原文，经 LightRAG API 协调解析 manifest、远端导入/状态/引用/删除/重建，持久业务任务与补偿；不直读写服务派生空间 | 阶段一 |
| LightRAG Server 存储 | KV/vector/doc_status 在检索 PG，图在 HugeGraph；原文权威由企业 ObjectStore 管理，索引解析文件/服务副本由检索链唯一管理其 S3 派生空间 | 阶段一 |
| EduPlus2Store | PG profile/组织必要缓存、同步批次/Webhook 幂等 | 阶段二 |
| ObjectUsageStore | PG 对象存储额度、上传预留/核算/释放及幂等操作 | 阶段一 |
| Policy/UsageStore | PG token/并发治理配额、策略版本 | B2 完整治理；A2 先落实容量预算与按租户/KB 的基础限流，对象额度在 A2 |
| DistributedJob/CommandStore | PG turn/command/租约和协调 | H：多执行者前；基础 turn 状态在 A1 |

SQLite 仅保留独立离线导入读取及旧格式 fixture，不保留 local profile 或临时 SQLite cache；所有默认入口必须连接 PG，旧 PocketBase 设置不能成为备用业务库。不新增企业 FileIdentityStore、FileWebhookStore 等替代实现。默认与企业运行调用中的直接 SQLite 必须清除；企业 JSON 状态写入仍按完整 A1/A2 门禁替换，不能由本次全量 SQLite 退出推断已完成。

## 配置契约（拟新增）

```bash
DEEPTUTOR_STORAGE_BACKEND=postgres
DEEPTUTOR_DATABASE_URL=postgresql://<secret-reference>
DEEPTUTOR_OBJECT_STORE=s3
DEEPTUTOR_RAG_PROVIDER=lightrag-server
DEEPTUTOR_RAG_GATEWAY_URL=<internal-service-url>
DEEPTUTOR_DEPLOYMENT_MODE=single_tenant
DEEPTUTOR_DEFAULT_TENANT_ID=<internal-uuid>
```

以上是不可直接执行的企业配置契约示例，不是当前上游已识别的环境变量；企业首发默认值确定为 `lightrag-server`，但未修改源码默认 provider 或实际运行配置。每个 KB 仍由 PG binding 决定，不能用默认值覆盖既有非托管连接。LightRAG 的 PG、HugeGraph、模型和 scratch 配置与 DeepTutor 分开，S3 业务空间由企业 ObjectStore 接入，检索派生空间由 LightRAG 的解析/任务组件接入，凭证和写删权分离；缺失必需依赖拒绝启动或操作，不继承 local 默认值。

DeepTutor 的应用 PG/S3/LightRAG HTTP 连接、事务、超时和重试通过相应 provider 管理；检索 PG/HugeGraph 连接池及内部依赖检测由 LightRAG 管理，不通过企业 Store 统一接管。实际 driver 需与仓库同步/异步协议及并发模型验证后锁定版本；不为方案示例引入未验证的可运行配置。

## 数据模型契约

下表是后续版本化迁移的建模要求，不是完整可执行 DDL。所有表、索引、约束与回填必须在相应阶段交付 migration 和测试，不能把本文示例当作已支持功能。

| 表/领域 | 主键及关键约束 | 阶段 |
| --- | --- | --- |
| tenants | 内部 `id UUID`；`eduplus_tenant_id TEXT UNIQUE NULL`；独立 external_eligibility/local_enabled/provisioning_status 及来源版本；status 为派生展示值，见 [03](03-tenant-scope-schema.md#租户状态的独立来源)；阶段一仅一个配置租户 | 一预留；二验证外部资格 |
| users / local identities | `(tenant_id, user_id)`；稳定内部用户 ID；凭证 hash 与业务资料分离 | 一 |
| sessions | `(tenant_id, session_id)`；owner 复合 FK 指向 users | 一 |
| messages | `(tenant_id, message_id)`；`(tenant_id, session_id)` FK，序号/请求幂等约束 | 一 |
| turns / turn_events | turns 引用 session/owner；events `(tenant_id, turn_id, seq)` 主键及复合 FK，状态转换有并发保护 | 一 |
| settings / grants / resource metadata | tenant/owner 或 tenant/resource 复合键，version 防丢失更新；平台设置独立表 | 一 |
| object_assets | `(tenant_id, object_id)`；唯一 `(bucket, object_key)`；owner/KB/turn 引用校验，pending/ready/deleting 状态 | 一 |
| audit | 平台审计与租户审计分别控制读取；actor/target tenant/action/result/request ID/时间 | 一 |
| eduplus_identities | `(tenant_id, provider, eduplus_user_id)` 唯一，映射内部 user；tenant 对应外部 tid；eit 作为身份上下文 | 二 |
| webhook_events / sync_batches | `(tenant_id, event_id)` 或 batch 唯一；接收/处理状态、重试版本 | 二 |
| rag_bindings / rag_documents / index_jobs | tenant/KB/index-version 复合归属、provider、远端 tenant/KB 或 workspace、LightRAG endpoint/API Secret 引用、托管权、远端 doc/job ID、原文/解析物 object_id、服务派生副本 locator/责任方、状态与幂等 operation ID；受控检索部署引用及服务契约版本。另记录受控 retrieval_profile_id/version、分配 request_id/version、cancel_scope/cancel_state 与远端状态观察版本；此业务 binding 不保存或解析图连接、graph locator、图 schema 或图凭证 | 一 |
| object usage / reservations | tenant + 对象存储额度，原子预留/核算/释放；幂等 operation ID | 一 |
| tenant policies / token usage / concurrency limits | tenant + 时间/资源维度，扩展 token/并发治理；幂等 operation ID | 二 |
| turn commands / leases | tenant/turn/command ID、owner、lease expiry、fencing version；领取与状态更新原子 | H：启用多执行者前，不绑定 B2 |
| 平台治理 API 授权 | 可信平台身份、具体能力和目标租户绑定、默认运维授权及操作审计 | B2：开放治理 API 前完成 |
| 运营角色完善/聚合 | 复用既有平台授权，完善 admin/operator/auditor 入口和只读聚合；不授予任意私有内容读取 | C1/C2 |

`tenant_id` 是内部 UUID，不能把 EduPlus2 外部 tid 强转 UUID。S3 key 使用内部 tenant/user ID，详见 [03](03-tenant-scope-schema.md)。阶段一 `eduplus_tenant_id` 允许为空，阶段二绑定现有行，不插入一个新租户再迁移全部数据。

## RLS 与事务契约

租户表保留 RLS policy，但当前单库单数据库用户模型不强制依赖数据库角色隔离：应用连接可以是目标库/schema/table owner，但不能是 superuser、CREATEDB、CREATEROLE 或 BYPASSRLS，也不能经成员关系获得这些能力。业务权限必须由 DeepTutor 应用层鉴权、scope、owner guard、审计与受控入口执行；RLS policy 用于目录漂移校验和未来拆分运行角色时的防线。下面仅说明策略形状：

```sql
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_sessions ON sessions
  USING (tenant_id::text = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
```

每个业务事务使用可信 scope 设置事务局部上下文：

```sql
SELECT set_config('app.tenant_id', $1, true);
SELECT set_config('app.user_id', $2, true);
```

两条设置和业务 SQL 必须位于同一显式事务/同一连接；不能在 autocommit 设置后假设后续事务继承，也不能使用持久 session setting 造成连接池串租。RLS 不替代用户所有权与业务授权；后台任务也不使用全局超级连接。参考 [PostgreSQL 行安全](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)。

迁移角色与运行角色分离，迁移 Job 单执行并记录版本，不让多个 Pod 启动时竞相修改 schema。

## ObjectStore 与数据库一致性

接口覆盖 `put/get/head/delete`、流式上传下载、presigned upload/download，隐藏具体 SDK。对象 locator 只能由可信资源服务构造；接口接收 locator 并不表示任意调用方可绕过授权。

```text
PG pending + 配额预留 → 上传唯一 key → head/hash/size 校验
    → PG ready + 用量核算 → 发布成功事件
失败 → 标记失败/重试 + 清理对象 + 释放或修正预留
```

没有跨 PG/S3 分布式事务，使用持久化状态、幂等任务和补偿；不能假设上传与 metadata 写入天然原子。列表/下载只能看到已授权 ready 资源。正文删除、索引删除、metadata tombstone 需可重试并避免无记录孤儿。文件工具通过 scratch adapter 读写，不把 S3 key 当本地路径。

## 企业边界：可信 binding、对象归属与文档责任

所有 provider 都经企业 RagGateway 验证当前 tenant/user/KB/操作/policy_version，再解析平台受控 endpoint 和 Secret。浏览器不提交远端租户、KB、workspace 或任意 URL；服务 key 不下放。多 KB 查询先逐库验证全部语料可见性，不跨未授权语料召回再过滤；引用须再次授权。HTTP/WS、SDK、worker 和后台重试复用该边界，错误不可伪装成无结果或切换 provider fallback。

外壳到网关的调用凭证必须短期、audience 受限，并绑定 tenant/user/KB/index-version/操作/policy_version；网关复验当前状态，worker 执行与重试同样重新授权。所有 provider 的 endpoint 均由平台受控登记，限制出站地址和重定向；原始查询、文档、图管理及兼容 API 不向浏览器或普通租户直通，认证白名单和网络策略必须实测，不能仅隐藏管理页面。

企业 `RagDocumentService` 是**应用级文档生命周期的协调者**，不是重新实现解析/检索内核：

- 企业 ObjectStore 的 S3 原文是托管资料的权威恢复源，PG `object_assets/rag_documents` 保存内部归属、hash、解析/索引版本、引用和任务。需要持久保留的解析文件也进入 S3；检索文本块、向量及文档状态在检索 PG，实体/关系图在 HugeGraph；图数据库运行态不搬为 S3 文件，详见 [07 文件分类](07-resource-isolation.md)。
- 检索服务若因上传 API 必须保存原文副本或生成图片/解析物，其对象明确为**服务管理的派生副本**，登记内部 tenant、远端资源与 locator；仅该服务负责其写入/删除，企业层通过受控 API 协调并对账，不直接删改服务私有表或对象。
- 两边不能把同一可变文件各自当权威，不能并发覆盖同一 key；这种显式、可重建的索引输入副本不属于被禁止的业务双写过渡系统。配额覆盖实际保留的副本字节，同一物理对象只核算一次；删除/失败补偿覆盖全部副本和缓存。
- 业务对象继续采用私有业务 bucket 和内部 tenant 前缀，服务派生物使用独立受限子前缀与凭证。服务原生 key 使用自己的 tenant ID 时，必须在 A2 验证适配内部 namespace/locator 和授权规则，不能假定修改 `PATH_PREFIX` 就满足约束；不支持则列为上线阻断或必要适配，不默默放宽。
- LightRAG 不接管聊天附件、工作区产物、动态 skills/personas 等 DeepTutor 文件，也不替代 DeepTutor 身份、会话、TMS/OMS 或业务授权。应用与检索可共享存储基础设施，但不共享高权账号或默认公开下载地址。

### KB 解析与派生物的固定交接

首发采用**原始文件提交、检索侧统一解析、服务侧持久化派生物**，不同时维护“DeepTutor 预解析再由服务重复解析”的默认路径：

1. DeepTutor 验证格式、大小、上传安全与权限，将原文写入业务 S3 并置 ready；文档 worker 从该不可变 object/version 下载到隔离 scratch，按锁定文档 API 提交原始文件字节及 source object_id/hash、operation ID。LightRAG 不获得业务 bucket 的长期读取/写删凭证。
2. LightRAG 检索链是索引解析的执行权威。PDF/Office/图片的解析、OCR、页码映射、图片提取由其明确装配的解析组件完成，切块/embedding/建图仍在检索侧；组件随该侧制品锁定和运维。DeepTutor 不重写该内核，也不把聊天附件/工作区处理一并迁走。
3. 需要保留的文本/Markdown、OCR、图片和文件化来源映射由检索组件唯一写入独立受限 S3 派生前缀；上报带 source hash、parser/profile/index 版本、远端 doc ID、locator、hash/字节数、页码关系的 manifest。DeepTutor 仅登记业务映射及配额，不另写一份可编辑解析正文，不直接修改或删除服务对象。
4. 解析物必须先持久化并完成 manifest 对账，再把依赖这些引用的索引标 ready；检索组件在写入派生物前通过受控 API 向 DeepTutor 申请实际对象预算，由业务额度账本原子预留（不直连应用 PG），字节变化补充预留/核算，超额拒绝且补偿，不以事后统计替代准入。服务派生引用经 DeepTutor 重新授权后，使用已绑定服务的受控读取 API 获取；不扩大应用 S3 凭证、不返回服务私有任意路径/URL。删除由 DeepTutor 发起、检索组件执行并确认全部派生物/索引清理，业务原文仍由 ObjectStore 管理。
5. 这是 A2 必须实现和验证的契约，不声称当前 fork 原生提供 S3、manifest 或全部解析能力。缺接口在 LightRAG/解析组件边界补齐；格式、公式/表格/图片质量、scratch 丢失、上传中断、孤儿回收和额度对账均进入 G1，不能以仅文本输入替代已确认教材范围。

## LightRAG Server：首发唯一托管检索实现

下列实例池、存储类及接口是已选路线的交付要求，不再是“选择 LightRAG 时才实施”的条件分支。WeKnora 的对比结果和依赖留在 [历史评估](evaluations/2026-09-13-rag-services.md)，不作为首发实现任务。

```text
原有 rag Tool / Capability（保留查询与回答职责）
  → 企业 binding/client provider（PG/Secret、可信请求 scope）
  → RagGateway（校验 tenant/owner/grant/策略，解析受控 binding）
  → 固定 workspace 的用户 LightRAG fork Server 实例池
      ├→ 检索 PostgreSQL：KV + vector + doc_status
      └→ HugeGraphStorage → HugeGraph：实体 + 关系 + 图遍历

DeepTutor KB 上传/管理 UI 与 API
  → RagDocumentService / 持久化 worker
  → 应用 PG metadata/job + 业务 S3 原文
  → 授权提交原始文件/状态/引用/删除/重建 → 同一 Server/workspace
      → 检索解析组件 → 服务 S3 派生物/manifest（组件唯一写删，应用仅对账）
```

默认一个隔离 KB/index-version 绑定一个固定 workspace 的 Server 实例（进程/容器；不把 Deployment 数量与应用租户数量等同）。实例共享受管检索基础设施，应用前后端、身份和控制面仍为同一套；不是“每租户部署一套 DeepTutor”。A1 确认 KB 数量、索引规模和内存/连接数预算，A2/A3 验证实例开通、重启、回收与容量。同一目标 scope 的写入只允许一个受控协调域；未通过实际多执行者协调验收时保持单索引写执行者，更新时停旧启新。不能凭 PG/HugeGraph 外置或 adapter 内部锁就增加独立写部署。

当前用户 fork Server 仍在启动时绑定 workspace，当前 DeepTutor 客户端没有动态 workspace 参数。同一个 URL 创建两个 KB 名称不会分出两个语料库，网关改写 header 也不能令一个固定 workspace Server 动态切换。多个实例可由受控 endpoint/binding 路由，但不能把任意用户 URL、host/path 或 `workspace` 当作可信路由。HTTP 路径前缀是否保留须做契约测试，不能假定现有客户端无条件兼容任意代理前缀。

本期不同时建设另一套多 workspace Server。若实例池容量不符合目标，需在 A1/A2 明确评审改为基于 LightRAG core 的多 workspace 服务层，并重新验证存储/并发/隔离契约；这不是原版 Server 的配置开关，未完成不能削减 KB 范围或把资料混入一个图。

### 查询、身份与连接持久化

- 保留 `POST /query` + `only_need_context=true` 和现有 modes/references 语义，最终回答仍由 DeepTutor 生成；该参数不保证关键词提取、embedding 或索引过程完全不调用模型。
- 企业 binding provider 从 PG 加载连接，凭证通过 Secret provider 解析；旧 `kb_config.json` 和 `lightrag_server.json` 仅作受控导入来源，生产不在其中保存 key 或更新 binding。取消 SQLite profile 不豁免 A1/A2 的文件配置迁移。
- 当前静态 `X-API-Key` 客户端没有最终用户可信 scope；须通过通用 client/binding seam 接入企业适配，不能假定原版连接零改动已具备请求授权。外壳给网关签发短期、audience 受限、绑定 tenant/user/KB/index-version/操作/policy_version 的调用凭证，网关复验当前状态，再解析仅服务端可读的远端 key；导入 worker 同样重新授权。
- 远端 endpoint 来自平台受控登记，限制出站地址与重定向；租户不能任意修改 URL、指定 workspace 或获得 Server API key。网关/worker 使用受限内部身份，原始 Server 的查询、文档、图管理及兼容 API 不向浏览器或普通租户直通；认证白名单和网络策略须实测，不能只隐藏 WebUI。
- 查询失败、超时、鉴权失败返回明确检索错误，不回退其他租户、默认实例或本地索引，不伪装成“无结果”；非必要 KB 不可用按能力错误策略处理，不要求每个空闲实例都阻断整个应用 liveness。

### 多租户：M1 建底座并测试，M2 开放生产租户

M1 只开放固定租户，不等于可以推迟隔离设计。A1 固定模型与授权粒度，A2/G1 使用隔离测试环境中的两个合成租户、每租户管理员/普通用户及同租户两个普通用户验证负例；生产第二租户仍须通过 B1/B2/G2。多租户不改变既有内部 ID，不为每个租户部署整套 DeepTutor。

`tenant_id + kb_id + index_version` 使用不可复用的内部 ID，编码成无碰撞、符合锁定版本约束的 LightRAG workspace；storage namespace 保持各存储的既定职责，与该 workspace 一起稳定映射。DeepTutor 的 PG binding 只保存 provider、LightRAG 受控 endpoint/API 凭证引用、workspace/远端资源标识、服务契约版本与检索部署引用，并设唯一/归属约束。LightRAG 部署配置另行管理检索 PG、graph locator（服务/graphspace/graph）、storage namespace、schema/权限版本及存储 Secret，不能变成 DeepTutor 请求参数或业务连接配置。由受控部署记录将服务部署引用与内部 tenant/KB/index-version 对齐；LightRAG 部署预检核对实际后端 workspace，DeepTutor 校验服务 binding 和就绪结果，双方不默认回退。

个人 KB 默认私有，共享 KB 需要显式 grant；同租户身份、租户管理员角色或服务 key 不自动赋予他人私有资料读取权。不同可见范围不得混为同一可相互遍历的逻辑图再过滤 top-k；这不禁止经验证的共享物理 HugeGraph graph，后者必须隔离逻辑 scope、ACL 与遍历范围。跨 KB 检索先逐库验证完整语料可见性；查询/图遍历、KV、vector、文档状态、缓存、去重、后台任务、引用及删除统一使用同一 binding。撤权或租户暂停使缓存/旧调用凭证失效，worker 执行与重试重新授权。

以下是**联合隔离验收**：DeepTutor 验证业务授权与服务 API；LightRAG 及其部署运维验证内部存储隔离。直连 REST/Gremlin 的负例由隔离测试 Job 使用受限 LightRAG 身份执行，不给 DeepTutor 增加图访问通路；另验证 DeepTutor 身份无图 Secret 读取权且到 HugeGraph 的网络访问及对检索 PG 的数据库访问被拒绝。

| 防线 | 必须交付的保证 |
| --- | --- |
| 应用 PG | `tenant_id + FORCE RLS + owner/grant`；连接池不串租，应用账号非 owner/superuser/BYPASSRLS |
| 检索 PG | 对 PGKVStorage/PGVectorStorage/PGDocStatusStorage 的实际表、SQL 和 workspace 写检查实施数据库隔离；固定实例使用仅有绑定范围权限的运行身份，无应用私有表权限。不能声称上游已有企业 RLS |
| HugeGraph 逻辑分区 | fork 按 workspace + storage namespace 编码 `lightrag_scope`；scope/实体名决定物理 ID，读写/遍历/drop 限定专属标签与 scope。它避免正常适配路径串图，**不是 ACL** |
| HugeGraph 强制权限 | A1 选定、A2 实测 graph/graphspace 分隔配合受限身份，或共享 graph 的服务端资源 ACL；必须覆盖 KB 授权范围，只有 tenant 级账号可任读本租户私有 KB 不够。验证直接 REST/Gremlin 读写、遍历、删除及 schema 管理越权被拒绝，而不只验证 adapter 过滤 |
| 网络与凭证 | GraphServer/Gremlin、LightRAG 查询/图/文档及兼容 API 仅对受控内部服务开放；运行、迁移、查询/管理身份按用途最小授权，普通用户不获得图凭证或原始服务通路 |

**图隔离策略必须在接入就绪评审锁定，不能留到 M2 再补。** 若共享 graph 的资源 ACL 无法覆盖 adapter 实际查询/写入/遍历路径，应改用按授权边界划分的 graph 与独立受限身份；仍不满足则阻断 G1，不接受全权账号 + scope 过滤。非 HStore 的 graphspace 能力有限，本地 fork 文档约定只能使用 `DEFAULT`，不能未经目标部署验证强制“一租户一个 graphspace”。共享基础设施可行与否，以真实权限和容量证据判定，而不是 namespace 名称。

HugeGraph 官方描述了 `StandardAuthenticator` 的用户/组/操作/资源权限，并提醒默认不启用认证；**已有实例是否启用、具体策略能否覆盖当前 fork 尚未验证**。参考 [HugeGraph 认证授权](https://hugegraph.apache.org/docs/config/config-authentication/) 与 [Graphspace API](https://hugegraph.apache.org/docs/clients/restful-api/graphspace/)。这些是设计依据，不是现有实例安全证明。

### 存储后端、fork 制品与初始化门禁

2026-09-13 只读核对：`~/Projects/LightRAG` 的 origin 为 `LFunTech/LightRAG`；`lightrag/kg/__init__.py` 已注册 `HugeGraphStorage`，实现及契约位于工作区 `lightrag/kg/hugegraph_impl.py`、`hugegraph_client.py`、`docs/HugeGraphStorage.md`。当前 HEAD 为 `af6089f4e3781a092ec0a6f0d631e2135b650b2a`，但 HugeGraph 新增实现仍有未提交文件，**不能用这个 HEAD 冒充包含全部改动的可复现版本**。本轮未修改 fork，也未执行该组合的新集成测试。

生产发布必须锁定实际包含实现并验收通过的 fork release/commit/镜像 digest、上游基线及差异、HugeGraph 版本/存储拓扑/schema/权限策略版本、模型/解析和 binding 格式。不得使用缺少 HugeGraphStorage 的官方旧镜像、工作目录拷贝、移动分支或 latest 替代固定制品。升级后重跑受影响的接口、隔离、图质量、容量、迁移和恢复检查。

| 状态 | 首发实现 | 验收要点 |
| --- | --- | --- |
| 文档/文本块/KV/LLM cache | `PGKVStorage` | workspace、缓存授权、故障/恢复 |
| 向量 | `PGVectorStorage` | pgvector、模型/维度/索引版本与 namespace |
| 文档处理状态 | `PGDocStatusStorage` | durable job 对账、失败和重复导入 |
| 实体/关系图 | fork `HugeGraphStorage` | 实际图检索、属性/无向边语义、scope 与数据库权限、初始化、删除、写不确定性及恢复 |

下列为 **LightRAG 进程**的配置契约（占位符不可直接执行；不是 DeepTutor 根 `.env` 配置）：

```dotenv
LIGHTRAG_KV_STORAGE=PGKVStorage
LIGHTRAG_VECTOR_STORAGE=PGVectorStorage
LIGHTRAG_DOC_STATUS_STORAGE=PGDocStatusStorage
LIGHTRAG_GRAPH_STORAGE=HugeGraphStorage
HUGEGRAPH_URI=<受控 HTTP(S) 服务根地址，可含代理前缀，不带 graph/API 路径>
HUGEGRAPH_GRAPHSPACE=<目标部署已验证的 graphspace>
HUGEGRAPH_GRAPH=<已预置且受授权的 graph>
HUGEGRAPH_AUTO_CREATE_SCHEMA=false
```

检索 PG 与图认证仅向 LightRAG 工作负载及按用途授权的运维 Job 注入，不向 DeepTutor backend、RagGateway、文档 worker 或其 ServiceAccount 开放；HugeGraph 使用成对的 `HUGEGRAPH_USERNAME`/`HUGEGRAPH_PASSWORD` 或互斥的 `HUGEGRAPH_TOKEN`，不把 `.secrets` 内容写入方案/镜像/日志。`HUGEGRAPH_TIMEOUT`、`HUGEGRAPH_BATCH_SIZE`、`HUGEGRAPH_MAX_CONNECTIONS`、`HUGEGRAPH_RETRIES` 依据容量测试配置，其中 retries 仅用于可重试读取，不表示写请求可自动重试。

HugeGraph 的 graph/graphspace、账户及权限由受控运维预置；fork 不创建服务或授权。其专属 v1 schema 包含 `lightrag_entity_v1`、`lightrag_relation_v1` 及 `lightrag_scope`、`lightrag_name`、`lightrag_data` 属性，准确名称/索引以锁定 fork 定义为准。LightRAG 的检索 PG 与图 schema/权限初始化由其独立版本化 Job/维护身份执行，与 DeepTutor 应用 PG 迁移分开归属，记录历史、互斥与 drift 校验；运行设 `HUGEGRAPH_AUTO_CREATE_SCHEMA=false`，保留必要的 schema 读取和范围内业务权限。不兼容 schema 拒绝启动，不删除既有业务图/schema 自行修复，也不长期授予高权自动 DDL。

历史 [v1.5.7 Docker 评估](evaluations/2026-09-13-rag-services.md) 的四类 PG 存储测试只说明当时配置的观测；不证明新 fork + HugeGraph 或企业低权部署可用。首发不自动选择 PGTableGraphStorage/AGE/Neo4j/文件图，不静默禁图。文件输入和解析临时目录只作 scratch；PG/HugeGraph 索引不替代 S3 原文与解析物。

### LightRAG 写入协调与联合恢复责任

DeepTutor 仅根据 LightRAG API 状态暂停业务请求、记录待恢复任务及协调重建/切 binding；下面的图请求确认、屏障、内部重放及存储恢复由 LightRAG 和部署运维执行。恢复结果经服务契约及端到端验证确认，DeepTutor 不直接操作图数据库。

- 当前 fork 的 mutation 锁和 pending fence 只覆盖同一 `shared_storage` 协调域；同一 HugeGraph 目标 scope 的所有 writer 必须使用统一服务 URI，不通过 DNS/代理别名或独立部署绕过。不同独立 LightRAG 部署并发写同一 scope 不在当前安全支持范围；这不是跨部署持久 fencing，也不代表 G-H/HA 已完成。
- 写超时、取消、异常确认或 worker 异常退出可能留下服务端在途/已提交 mutation。fork 保留待确认写屏障并拒绝同 scope 后续写入/删除；企业 durable job 必须记录不确定状态并停止盲目重试/发布 ready，不把异常等同于未写入。受影响版本暂停查询发布，避免部分索引被当作一致结果。
- LightRAG 运维恢复先停止全部检索 writer 及自动重启调度，确认 HugeGraph 没有可能迟到提交的旧请求并审计已提交状态/批次及各存储恢复锚点；无法确认则保持停止。安全确认后按锁定 fork 契约重启整个协调域、受控重放确定性操作或执行文档恢复，核验全部存储后恢复流量。一次读回、等一个 timeout、单 worker 重启或换 URI 均不足以解除不确定性；不能删图或恢复锚点“解锁”。
- PG、HugeGraph、S3 之间没有分布式事务，一批请求也可能部分提交。DeepTutor 企业服务通过 LightRAG API、持久业务任务、幂等 operation ID 与状态对账协调生命周期；LightRAG 执行内部索引补偿，运维负责跨服务成套恢复；不能危险地删除已成功图对象来伪装事务回滚，不能由重试旧值覆盖后继写入。
- 从 PG 图迁移或变更模型/schema 时，停止旧范围写入并保留恢复锚点，成套备份后从 S3/PG 在新 workspace/index-version 重建匹配的 PG 三类状态与 HugeGraph 图。验证 ready、引用和图召回后以 PG 事务/版本检查原子切换 binding；这只原子切换路由，不让跨存储写入变成原子事务。回退窗口内保留旧版本；清理只针对旧 binding 的 scope，测试 `drop()` 不影响其他 KB/版本、业务图或 schema。
- 图查询/遍历/导出、索引吞吐及同名实体压力测试必须覆盖真实图规模；子串搜索和热门度排名可能扫描整个 scope，`limit`/`max_nodes` 不是成本上限。备份/恢复、连接数、图容量、查询/导入并发与模型费用均纳入租户预算和 G1/G-H 证据。

### KB 申请与预开实例池交接

首发使用**独立运维预开、受控登记、应用原子分配**，不在 DeepTutor 中实现 Kubernetes provisioner。部署运维按容量预算预置空的固定 workspace 实例及内部存储/模型/S3 配置，验证后以受控身份登记部署引用、endpoint/API Secret 引用、契约/profile 版本、隔离验收和 API 就绪记录；普通租户不能登记任意 endpoint。

- 创建 KB 或新 index-version 时，DeepTutor 先持久化带 tenant/KB/index-version/profile、request_id 的资源申请；原子领取一个兼容且未分配的部署记录，并记录唯一分配版本。重试同一 request_id 返回同一结果，不重复开通或混用其他 KB 的 workspace。
- 无兼容实例时保持 `provisioning` 并呈现等待原因，由受控运维流程补池后重试；超过已配置申请期限标记失败并允许授权重试。只有绑定、隔离记录、profile 和服务 API 就绪均通过才允许导入；不能伪报 ready、自动合图或给应用集群权限。
- 应用提交回收意图并 tombstone 停止新请求；LightRAG 确认在途操作结束及目标范围索引/派生物删除，应用核对引用/回退保留期，运维再销毁或重置该分配。失败保留 `retiring`/待对账，不把超时实例放回空闲池。跨 KB/租户再分配须新 workspace 身份并验证无残留，不复用旧 binding 或凭证授权。
- 池分配记录的权威在应用 PG，实际 Deployment/Secret/存储配置及维护结果的权威在部署运维；双方通过带 request_id/分配版本的受控登记与结果对账衔接。A2/A3 验证重复领取、池耗尽、半开通、状态丢失及回收失败；不要求新增独立开通微服务。

### 业务任务、远端索引与取消边界

业务 job 保存提交意图和授权审计，LightRAG 是远端执行状态的权威；DeepTutor 保存可追踪的观察状态，不直接消费/改写检索内部队列、锁或任务表。队列即使共用基础设施，也分离账号、namespace、消费者、重投和恢复责任。

拟定服务级契约至少包含 operation ID、tenant/KB/index-version binding、远端 doc/track ID、状态版本、支持的 `cancel_scope`（document/batch/workspace/none）、取消结果和用量关联。 解析额度申请、用量/manifest/状态回传同样使用绑定服务部署、operation 与分配版本的受限身份；DeepTutor 复验对象范围并去重，拒绝过期分配改变当前 binding 或新派发；已登记旧 operation 的迟到用量/清理回执只按原 scope 对账，不修改当前分配。清理/核算可用独立受控任务身份继续，不因用户撤权丢失账本或补偿。提交、查询、重试和取消均校验当前权限；响应丢失先按 operation/doc ID 对账，不由两边各自启动新索引任务。

- 取消状态单列 `not_requested → cancel_requested → cancel_confirmed`，并可明确返回 `unsupported`/冲突；这不是索引成功/失败状态的替代品。未派发任务可经原子禁止派发后本地确认；已提交任务须远端确认其范围内执行停止。取消不自动撤销已索引内容，删除走文档生命周期。
- 2026-09-13 本地 fork 源码核对：`lightrag/api/routers/document_routes.py` 的 `/cancel_pipeline` 无 doc ID 参数，修改当前 workspace 的 pipeline 取消标志；不能当成单文档取消，也不能仅凭返回 `cancellation_requested` 认定执行已停止。发布时对固定 commit 重验，不把此次静态核对当运行测试。
- 普通 job 取消只能作用于该 job 的实际范围。服务不支持所需粒度时，API/页面明确显示不支持且不发送扩大范围的请求；C2 的单任务取消交付须在 LightRAG 边界补齐并验收，不用隐藏按钮或整 workspace 取消代替完成。整 workspace 停止仅走覆盖全部受影响任务的独立运维授权/确认，不复用单 job 按钮。
- HTTP 超时、本地 worker/turn 结束、租约到期不证明远端执行结束。业务可停止等待，但远端执行和对应资源预留保持待确认；用量按 [07](07-resource-isolation.md#聊天模型与检索模型分离) 对账，重试不得重复执行或漏计量。图写不确定时仍执行前述停全部 writer/服务端确认/恢复屏障规则；取消确认也不替代图一致性验收。

## 文档全生命周期：企业服务协调，不改变旧连接所有权

当前 LightRAG Server 的 DeepTutor pipeline 拒绝本地导入、删除不操作远端数据。企业版必须通过受保护 KB API/文档服务实现以下完整闭环，不能让租户去原始 Server 管理页绕过应用权限。

1. **创建/绑定**：PG 保存 KB 归属、托管权、provider、远端 workspace/KB、index-version 和 Secret 引用；LightRAG 的存储隔离验收记录与服务 API 就绪检查通过后才允许导入，不由 DeepTutor 直连检索 PG/HugeGraph 预检。现有外部 Server 先核对版本、存储、语料归属及备份；同意移交后才成为企业托管资源。
2. **上传/导入**：复用 ObjectStore 的额度预留、pending→ready；S3 原文 ready 后持久化 index job，授权 worker 从 S3 下载到 scratch，使用锁定版本已验证的文档 API 提交原始文件，由检索侧解析并持久化派生 manifest。保存远端 doc/track ID、source object_id、hash/解析版本和 operation ID，不把 HTTP 接收成功当作索引成功。
3. **状态/重试**：持久化 queued/indexing/ready/failed/deleting 等业务观察状态与独立取消状态；以 LightRAG 为执行状态权威，轮询或对账远端完成结果，网络超时先核对远端 doc/job 状态，涉及图写不确定性时先完成上节停写/服务端确认/对账及屏障恢复，再受控重试。只有索引可查询后标 ready；同一 KB/index-version 的写操作有租约/互斥或已验证的服务协调及重启恢复，不能宣称外部 API exactly-once。
4. **引用/读源文**：把远端 doc/knowledge/chunk ID、file_path 或 resource handle 映射受控 source object_id，再按当前 tenant/owner/grant 下载/预览。不能把远端绝对路径、任意 URL 或跨租户引用原样当作可读文件；解析物需保留页码/来源映射，旧引用按明确版本策略解析。
5. **删除**：企业托管 KB/文档先 tombstone 并阻止新查询，再按责任方幂等删除远端索引/缓存、S3 原文/解析物/服务派生副本及 metadata，失败持久化对账；图写不确定时先完成上节停写/确认/屏障恢复，不凭一次读回放行重试。完成后不得残留可召回正文。DeepTutor 只提交 LightRAG 文档删除请求；由 LightRAG 文档生命周期清除来源贡献并重算受影响的共享实体/关系与描述；不得对整个 KB/index-version 调用 drop。验收同 KB 两文档共享实体：剩余文档可查询、引用有效且不含已删除来源的派生事实；只有删除整个 KB/索引版本才清理对应完整 scope。原有非托管外部连接仍只解除绑定，不能静默删除用户服务器；明确展示“解除连接”与“删除托管内容”的区别，非托管连接不冒充完整企业 KB 管理验收。
6. **重建/恢复**：DeepTutor 从业务 S3 原文和应用 PG metadata 发起请求，由 LightRAG 经受控服务契约复用兼容的服务派生物或重新解析，重建新 index-version；应用不直读写服务派生空间，验证引用/召回后原子切换 binding，保留受控回退窗口并清理旧索引。禁止就地修改 embedding 维度或用新路径创建身份不同的索引；备份记录应用 PG、检索 PG、HugeGraph 数据/schema/权限配置、必要队列状态、S3 原文/派生物和 binding 版本一致性。允许明确停机重建，但不能隐瞒重建耗时/模型成本或超出 RPO/RTO。

导入/embedding/检索内部模型调用的用量须与聊天用量区分，按可验证遥测记录和对账，不把 DeepTutor turn 的 `cost_summary` 当作包含所有远端费用。对象额度和按租户/KB 的导入/查询并发上限、队列公平性及超时在 A2 生效，防止共享 PG/HugeGraph/模型连接被单一租户耗尽；B2 扩展可管理的 tenant token/并发策略时覆盖相关工具和受管索引任务，配额失败可见且不重复核算。

## 七个工作包的存储交付映射

| 工作包 | 存储职责 | 验收边界 |
| --- | --- | --- |
| A1 | 稳定 ID/PG/RLS/核心 Store/结构化真实读写 | 不以新增表代替全部调用替换 |
| A2 | ObjectStore、scratch、LightRAG binding/授权路由/文档管理、全状态外置及生产验收 | 原文→索引→召回→引用→删除/重建完整闭环，含实例/权限/故障恢复 |
| A3 | 同构 K8s 集成/备份恢复/一次切换 | 准备从 A1 并行，G1 后发布 M1 |
| B1 | 一个真实租户的外部身份/权限/profile/必要事件 | 不重写内部 ID，不开放未绑定租户 |
| B2 | 多租户生命周期/grants/策略/token与并发治理/必要同步 | G2 前不开放多租户生产；租户管理 UI 与后端同批完成 |
| C1 | 运营能力授权、管理服务、基本审计查询 | 不另建控制后端，不等 C2 才补权限 |
| C2 | 运营聚合/任务状态/审计筛选导出 | C1+C2 才算完整 M3 |

分布式 turn/job/command 的存储由 H 工作线按目标实施；G-H 是所有实际多执行模式的前置，不由 B2 自动触发。单执行模式的持久化、基本任务状态、故障可见性和租户隔离仍必须完成。

## 存量导入与验收

无存量直接初始化，不开发通用迁移平台。确有存量才提供一次性只读 SQLite/file 业务状态与文件导入 PG/S3、检索状态按上节成套重建 PG/HugeGraph 的 dry-run/apply/verify，先明确归属、备份、校验、停止旧写，切换后不双写。阶段二身份绑定同样需要显式 dry-run/幂等验证，防止账号合并造成权限扩大。

验收至少覆盖：生产所有 Store 调用、无默认 scope 拒绝、连接池复用、租户内 owner、跨租户外键、并发事件排序、对象补偿、Pod 重建、备份恢复及当前运行模式任务状态；多执行者/HA 目标另须 G-H。具体门禁见 [02](02-rollout-testing-and-migration.md)。

### Resource metadata extension

The application PG schema includes `enterprise.resource_objects` and `enterprise.resource_cleanup_jobs` for durable ObjectStore-backed resources. Resource metadata records tenant/owner, kind, resource id, bucket/key, hash, size, mime, version, retention and state. Reads must resolve through PG metadata first; ObjectStore key possession is never authorization.
