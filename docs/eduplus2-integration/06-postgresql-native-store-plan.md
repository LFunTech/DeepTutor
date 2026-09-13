# 06. 企业 PG/S3 Store 与 LightRAG Server 接入计划

## 现状与交付定义

当前 `get_session_store()` 选择 PocketBase 或 SQLite，大量 settings、grants、memory、KB、workspace 仍依赖文件。**不是改 DATABASE_URL 就能使用 PG，也不是创建新增 EduPlus2 表就完成了生产替换。**

本文件不再有 PG-0–5 独立路线：A1 替换结构化状态，A2 替换文件/检索并在 A3 汇总验收 M1；B1 验证首租户外部身份闭环，B2 完成多租户治理；C1/C2 分批增加统一运营能力。主顺序见 [02](02-rollout-testing-and-migration.md)。

## 实现位置与接入责任

生产 Store、资源管理和 RAG adapter 位于独立 `deeptutor_enterprise` 包，默认源码位置为 `extensions/enterprise/src/deeptutor_enterprise/`。核心只保留通用协议/provider、可信 scope 与必要调用收敛，详见 [13](13-deployment-and-upstream-sync.md)。已有容器/SessionStore 注入优先复用，但不得漏掉直接 SQLite、JSON、PathService 和默认单例路径。

生产默认 RAG provider 为 **`lightrag-server`**，不是本地 `lightrag`，也不是自行用 pgvector 重写检索。LightRAG Server 保留算法和 HTTP 查询契约；本文件定义企业侧新增的 binding、文档管理、存储与隔离职责。

## 接口边界：生产只有一套实现

| 接口 | 生产实现/责任 | 替换时点 |
| --- | --- | --- |
| SessionStore | PG sessions/messages/turns/turn_events、事件顺序/事务 | 阶段一 |
| IdentityStore | PG 内部用户、本地认证；阶段二附加外部身份映射 | 阶段一/二 |
| SettingsStore | PG 配置/model metadata/version，凭证仅 Secret 引用 | 阶段一 |
| GrantStore | PG 用户/资源授权，租户复合键 | 阶段一 |
| ResourceStore | PG memory/notebook/KB/skills/personas metadata 或小正文 | 阶段一 |
| AuditStore | PG 脱敏业务审计；日志平台作检索副本 | 阶段一 |
| ObjectStore | S3-compatible 流式内容读写、短时 URL、对象状态补偿 | 阶段一 |
| RagBindingStore / RagGateway | PG 保存 tenant/KB/index-version→受控 Server/workspace、Secret 引用与版本；查询前授权 | 阶段一；B2 多租户复验 |
| RagDocumentService / IndexJobStore | S3 原文/解析物→远端导入/状态/引用/删除/重建，持久任务与补偿 | 阶段一 |
| LightRAG Server 存储 | KV、向量、文档状态和图持久化到受管 PG；不是 DeepTutor 另写检索内核 | 阶段一 |
| EduPlus2Store | PG profile/组织必要缓存、同步批次/Webhook 幂等 | 阶段二 |
| ObjectUsageStore | PG 对象存储额度、上传预留/核算/释放及幂等操作 | 阶段一 |
| Policy/UsageStore | PG token/并发治理配额、策略版本 | B2；对象额度在 A2 |
| DistributedJob/CommandStore | PG turn/command/租约和协调 | H：多执行者前；基础 turn 状态在 A1 |

上游现有 SQLite/local 实现只保留独立本地 profile/只读导入用途；不新增企业 FileIdentityStore、FileWebhookStore 等替代实现。工厂不静默 fallback；生产调用中残留 `get_sqlite_session_store()` 或 JSON 状态写入必须清除。

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

以上是企业启动器拟新增配置，不是当前上游可直接识别的环境变量；最终 provider 仍由每个 KB 的 PG binding 决定，不能用部署默认值覆盖既有绑定。LightRAG 的存储变量由检索服务独立读取，不与 DeepTutor 配置混用。

连接池、事务、超时、重试和依赖检测通过统一 provider 管理。实际 driver 需与仓库同步/异步协议及并发模型验证后锁定版本；不为方案示例引入未验证的可运行配置。

## 数据模型契约

下表是后续版本化迁移的建模要求，不是完整可执行 DDL。所有表、索引、约束与回填必须在相应阶段交付 migration 和测试，不能把本文示例当作已支持功能。

| 表/领域 | 主键及关键约束 | 阶段 |
| --- | --- | --- |
| tenants | 内部 `id UUID`；`eduplus_tenant_id TEXT UNIQUE NULL`；状态/version；阶段一仅一个配置租户 | 一；二绑定外部 ID |
| users / local identities | `(tenant_id, user_id)`；稳定内部用户 ID；凭证 hash 与业务资料分离 | 一 |
| sessions | `(tenant_id, session_id)`；owner 复合 FK 指向 users | 一 |
| messages | `(tenant_id, message_id)`；`(tenant_id, session_id)` FK，序号/请求幂等约束 | 一 |
| turns / turn_events | turns 引用 session/owner；events `(tenant_id, turn_id, seq)` 主键及复合 FK，状态转换有并发保护 | 一 |
| settings / grants / resource metadata | tenant/owner 或 tenant/resource 复合键，version 防丢失更新；平台设置独立表 | 一 |
| object_assets | `(tenant_id, object_id)`；唯一 `(bucket, object_key)`；owner/KB/turn 引用校验，pending/ready/deleting 状态 | 一 |
| audit | 平台审计与租户审计分别控制读取；actor/target tenant/action/result/request ID/时间 | 一 |
| eduplus_identities | `(tenant_id, provider, eduplus_user_id)` 唯一，映射内部 user；tenant 对应外部 tid；eit 作为身份上下文 | 二 |
| webhook_events / sync_batches | `(tenant_id, event_id)` 或 batch 唯一；接收/处理状态、重试版本 | 二 |
| rag_bindings / rag_documents / index_jobs | tenant/KB/index-version 复合归属、稳定 workspace、endpoint/Secret 引用、托管权、远端 doc/track ID、原文 object_id、状态与幂等 operation ID | 一 |
| object usage / reservations | tenant + 对象存储额度，原子预留/核算/释放；幂等 operation ID | 一 |
| tenant policies / token usage / concurrency limits | tenant + 时间/资源维度，扩展 token/并发治理；幂等 operation ID | 二 |
| turn commands / leases | tenant/turn/command ID、owner、lease expiry、fencing version；领取与状态更新原子 | H：启用多执行者前，不绑定 B2 |
| 平台治理 API 授权 | 可信平台身份、具体能力和目标租户绑定、默认运维授权及操作审计 | B2：开放治理 API 前完成 |
| 运营角色完善/聚合 | 复用既有平台授权，完善 admin/operator/auditor 入口和只读聚合；不授予任意私有内容读取 | C1/C2 |

`tenant_id` 是内部 UUID，不能把 EduPlus2 外部 tid 强转 UUID。S3 key 使用内部 tenant/user ID，详见 [03](03-tenant-scope-schema.md)。阶段一 `eduplus_tenant_id` 允许为空，阶段二绑定现有行，不插入一个新租户再迁移全部数据。

## RLS 与事务契约

租户表必须启用并强制 RLS；应用角色不能是 owner/superuser/BYPASSRLS。下面仅说明策略形状：

```sql
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions FORCE ROW LEVEL SECURITY;
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

## LightRAG Server：默认拓扑与职责

```text
原有 rag Tool / Capability（保留查询与回答职责）
  → 企业 binding/client provider（PG/Secret、可信请求 scope）
  → RagGateway（校验 tenant/owner/grant/策略，解析受控 binding）
  → 固定 workspace 的原版 LightRAG Server 实例池
  → 检索 PostgreSQL：KV + vector + doc_status + graph

DeepTutor KB 上传/管理 UI 与 API
  → RagDocumentService / 持久化 worker
  → PG metadata/job + S3 原文/解析物
  → 授权导入/状态轮询/引用映射/删除/重建 → 同一 Server/workspace
```

默认一个隔离 KB/index-version 绑定一个固定 workspace 的 Server 实例（进程/容器；不把 Deployment 数量与应用租户数量等同）。实例共享受管检索基础设施，应用前后端、身份和控制面仍为同一套；不是“每租户部署一套 DeepTutor”。A1 确认 KB 数量、索引规模和内存/连接数预算，A2/A3 验证实例开通、重启、回收与容量。未实现同 workspace 多实例写协调时，只允许一个索引写执行者；不能凭 PG 外置就扩写副本。

原版 Server 在启动时绑定 workspace，当前 DeepTutor 客户端没有动态 workspace 参数。同一个 URL 创建两个 KB 名称不会分出两个语料库，网关改写 header 也不能令一个固定 workspace Server 动态切换。多个实例可由受控 endpoint/binding 路由，但不能把任意用户 URL、host/path 或 `workspace` 当作可信路由。HTTP 路径前缀是否保留须做契约测试，不能假定现有客户端无条件兼容任意代理前缀。

本期不同时建设另一套多 workspace Server。若实例池容量不符合目标，需在 A1/A2 明确评审改为基于 LightRAG core 的多 workspace 服务层，并重新验证存储/并发/隔离契约；这不是原版 Server 的配置开关，未完成不能削减 KB 范围或把资料混入一个图。

### 查询、身份与连接持久化

- 保留 `POST /query` + `only_need_context=true` 和现有 modes/references 语义，最终回答仍由 DeepTutor 生成；该参数不保证关键词提取、embedding 或索引过程完全不调用模型。
- 企业 binding provider 从 PG 加载连接，凭证通过 Secret provider 解析；旧 `kb_config.json` 和 `lightrag_server.json` 仅作本地模式/只读导入来源，生产不在其中保存 key 或更新 binding。
- 当前静态 `X-API-Key` 客户端没有最终用户可信 scope；须通过通用 client/binding seam 接入企业适配，不能假定原版连接零改动已具备请求授权。外壳给网关签发短期、audience 受限、绑定 tenant/user/KB/index-version/操作/policy_version 的调用凭证，网关复验当前状态，再解析仅服务端可读的远端 key；导入 worker 同样重新授权。
- 远端 endpoint 来自平台受控登记，限制出站地址与重定向；租户不能任意修改 URL、指定 workspace 或获得 Server API key。网关/worker 使用受限内部身份，原始 Server 的查询、文档、图管理及兼容 API 不向浏览器或普通租户直通；认证白名单和网络策略须实测，不能只隐藏 WebUI。
- 查询失败、超时、鉴权失败返回明确检索错误，不回退其他租户、默认实例或本地索引，不伪装成“无结果”；非必要 KB 不可用按能力错误策略处理，不要求每个空闲实例都阻断整个应用 liveness。

### Namespace、数据库防线与授权

`tenant_id + kb_id + index_version` 使用稳定内部 ID，编码成目标 LightRAG 支持且无碰撞的 workspace（例如固定格式 UUID hex 与版本，不依赖绝对路径/可变名称）。映射存 PG 且有唯一约束；缺失、指向错误租户、版本未 ready、租户停用或授权撤销一律拒绝。后端专用的 workspace 环境覆盖也须核对实际解析结果，禁止启动多个实例却意外落入同一默认 workspace。

个人 KB 与租户共享 KB 按资源授权访问；不同可见范围不能先合并成同一图再过滤结果。多 KB 查询先逐个验证完整 KB 可见性，再在授权语料内召回，缓存、去重、向量、KV、文档状态、图与任务均使用同一 namespace。

**workspace 不是 RLS。** DeepTutor 应用表继续执行 `tenant_id + FORCE RLS + owner/grant`；LightRAG 独立索引表由其 schema 管理，不能声称原版自带应用的 tenant 列或 RLS。企业部署需为受管索引交付数据库隔离迁移和独立运行/迁移角色，固定实例凭证绑定允许的 workspace，PG 表使用覆盖 workspace 的 RLS/写入检查，验证错误 SQL/跨 workspace 读写被数据库拒绝。检索账号无权访问 DeepTutor 私有业务表；不能给运行账号 schema owner/BYPASSRLS 后宣称隔离成立。

图后端也必须有可验证的数据库权限防线。AGE/图查询不能套用一条普通表 RLS 示例就宣布安全；所选实现不支持要求时必须在上线前解决并评审，不能仅保留网关过滤作为等价替代。禁止为兼容原版启动 DDL 长期授予高权运行角色；须把实际初始化/升级迁移纳入受控 Job，并验证原版低权启动可行，不可行时登记必要通用 seam。

### LightRAG 的 PostgreSQL 后端与版本门禁

以下为 2026-09-13 对官方主分支的接口核查，不是已部署版本声明。实施时固定 release/commit 与镜像 digest，验证本表实现、初始化、低权运行、备份/恢复和查询结果后再选择；不在启动时按可用类名静默降级。

| 状态 | PostgreSQL 实现 | 验收要点 |
| --- | --- | --- |
| 文档/文本块/KV/LLM cache | `PGKVStorage` | workspace 完整覆盖、故障/恢复与缓存授权 |
| 向量 | `PGVectorStorage` | pgvector 扩展、模型/维度/索引版本兼容、namespace |
| 文档处理状态 | `PGDocStatusStorage` | 持久任务映射、超时/失败与重复导入 |
| 图 | 优先评估固定版本中的 `PGTableGraphStorage`；支持性不足时评审 `PGGraphStorage` | 前者为普通 PG 表，当前主分支有实现；后者依赖 AGE，二者均须单独验证权限、迁移和恢复 |

图实现是上线前必须锁定的部署依赖，不要求实现两套生产图后端。不把尚未包含 `PGTableGraphStorage` 的旧镜像按该主分支能力部署，也不默认新增 Neo4j/另一条企业存储路线。只有向量进入 PG、KV/图/状态仍在 JSON/Nano/NetworkX 时不通过 G1。

LightRAG 自有表/graph 与 DeepTutor 应用表分开管理和授权，可共享 PG 集群但不共享超级账号。文件输入目录和解析临时目录只能作 scratch；PG 索引不替代 S3 原文/解析物保存，清空 Server 临时盘后须验证现存查询、引用和失败导入恢复。

官方依据：[存储实现注册](https://github.com/HKUDS/LightRAG/blob/main/lightrag/kg/__init__.py)、[配置与图后端说明](https://github.com/HKUDS/LightRAG/blob/main/env.example)、[Server workspace 初始化](https://github.com/HKUDS/LightRAG/blob/main/lightrag/api/lightrag_server.py)。发布记录应以实际锁定版本的相同文件/接口为证据，而非长期依赖可变 main。

### 文档全生命周期：由企业服务补齐，不改变旧连接的所有权

当前 `LightRagServerPipeline.initialize/add_documents` 拒绝导入、`delete` 不删除远端数据。企业版必须通过受保护 KB API/文档服务实现以下完整闭环，不能让租户去原始 Server 管理页绕过应用权限。

1. **创建/绑定**：PG 保存 KB 归属、托管权、稳定 workspace、index-version 和 Secret 引用；受管 Server 就绪及数据库防线通过后才允许导入。现有外部 Server 先核对版本、存储、语料归属及备份；同意移交后才成为企业托管资源。
2. **上传/导入**：复用 ObjectStore 的额度预留、pending→ready；S3 原文 ready 后持久化 index job，授权 worker 从 S3 下载到 scratch，使用锁定版本已验证的文档 API 提交。保存远端 doc/track ID、source object_id、hash/解析版本和 operation ID，不把 HTTP 接收成功当作索引成功。
3. **状态/重试**：持久化 queued/indexing/ready/failed/deleting 等状态；轮询或对账远端完成结果，网络超时先核对远端 doc/job 状态再重试。只有索引可查询后标 ready；同一 KB/index-version 的写操作有租约/互斥及重启恢复，不能宣称外部 API exactly-once。
4. **引用/读源文**：把 references 中的远端 doc ID/file_path 映射受控 source object_id，再按当前 tenant/owner/grant 下载/预览。不能把远端绝对路径、任意 URL 或跨租户引用原样当作可读文件；解析物需保留页码/来源映射，旧引用按明确版本策略解析。
5. **删除**：企业托管 KB/文档先 tombstone 并阻止新查询，再幂等删除远端索引/缓存、S3 内容及 metadata，失败可重试/对账，完成后不得残留可召回正文。原有非托管外部连接仍只解除绑定，不能静默删除用户服务器；明确展示“解除连接”与“删除托管内容”的区别，非托管连接不冒充完整企业 KB 管理验收。
6. **重建/恢复**：从 S3 原文/解析物和 PG metadata 重建新 index-version，验证引用/召回后原子切换 binding，保留受控回退窗口并清理旧索引。禁止就地修改 embedding 维度或用新路径创建身份不同的索引；备份记录应用 PG、检索 PG/图、S3 和 binding 版本一致性。允许明确停机重建，但不能隐瞒重建耗时/模型成本或超出 RPO/RTO。

导入/embedding/检索内部模型调用的用量须与聊天用量区分，按可验证遥测记录和对账，不把 DeepTutor turn 的 `cost_summary` 当作包含所有远端费用。对象额度在 A2 生效；B2 扩展 tenant 的 token/并发策略时覆盖相关工具和受管索引任务，配额失败可见且不重复核算。

## 七个工作包的存储交付映射

| 工作包 | 存储职责 | 验收边界 |
| --- | --- | --- |
| A1 | 稳定 ID/PG/RLS/核心 Store/结构化真实读写 | 不以新增表代替全部调用替换 |
| A2 | ObjectStore、scratch、LightRAG binding/授权路由/文档管理及全部 PG 索引状态 | 原文→索引→召回→引用→删除/重建完整闭环，含实例/权限/故障恢复 |
| A3 | 同构 K8s 集成/备份恢复/一次切换 | 准备从 A1 并行，G1 后发布 M1 |
| B1 | 一个真实租户的外部身份/权限/profile/必要事件 | 不重写内部 ID，不开放未绑定租户 |
| B2 | 多租户生命周期/grants/策略/token与并发治理/必要同步 | G2 前不开放多租户生产；租户管理 UI 与后端同批完成 |
| C1 | 运营能力授权、管理服务、基本审计查询 | 不另建控制后端，不等 C2 才补权限 |
| C2 | 运营聚合/任务状态/审计筛选导出 | C1+C2 才算完整 M3 |

分布式 turn/job/command 的存储由 H 工作线按目标实施；G-H 是所有实际多执行模式的前置，不由 B2 自动触发。单执行模式的持久化、基本任务状态、故障可见性和租户隔离仍必须完成。

## 存量导入与验收

无存量直接初始化，不开发通用迁移平台。确有存量才提供一次性只读 SQLite/file 导入 PG/S3 的 dry-run/apply/verify，先明确归属、备份、校验、停止旧写，切换后不双写。阶段二身份绑定同样需要显式 dry-run/幂等验证，防止账号合并造成权限扩大。

验收至少覆盖：生产所有 Store 调用、无默认 scope 拒绝、连接池复用、租户内 owner、跨租户外键、并发事件排序、对象补偿、Pod 重建、备份恢复及当前运行模式任务状态；多执行者/HA 目标另须 G-H。具体门禁见 [02](02-rollout-testing-and-migration.md)。
