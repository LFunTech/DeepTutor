# 04. Kubernetes 与 PostgreSQL-first 生产架构

## 与三阶段实施对齐

- M1：A1 结构化状态、A2 文件/检索、A3 生产验收；已启用功能使用 PG/HugeGraph/S3，运行模式按已确认目标选择。
- M2：B1 先验证首租户 EduPlus2 最终接入，B2 再开放多租户和租户管理界面；多副本不是第二租户的必然依赖。
- M3：C1 运营管理闭环、C2 运营治理完善，不再迁库或替换对象存储。H 工作线独立决定多执行模式的 G-H 门禁。

不再安排“先 PG 控制面、后迁会话/文件”的生产过渡发布，详细门禁见 [02](02-rollout-testing-and-migration.md)。

## 决策结论

DeepTutor 企业版面向 Kubernetes 的持久存储与检索形态如下；聊天模型和 M2 身份集成等依赖仍按各自领域契约接入：

```text
DeepTutor core/企业包无状态应用
  → 应用 PostgreSQL + S3-compatible + LightRAG Server API
LightRAG Server（用户 fork）
  → 检索 PostgreSQL + HugeGraph + 检索模型 + 解析/任务组件（S3 服务派生空间及实际必需队列）
```

最新目标是本仓库所有默认 Web/CLI/SDK/后台均为 PG-only，取消独立 local/SQLite 及临时 SQLite cache。SQLite 只允许独立离线导入读取一致旧快照或旧格式测试 fixture；本机开发和 CLI-only 同样连接 PG。该全量迁移由[当前 change](../../openspec/changes/migrate-all-sqlite-state-to-postgresql/proposal.md)逐项实施/验收，实际完成范围以 tasks 与执行证据为准。

**SQLite 不再是任何运行 profile 的主库、备用库或缓存，不新增企业文件型后端。**

职责与凭证按 [06 责任矩阵](06-postgresql-native-store-plan.md#跨系统责任矩阵) 分离：LightRAG 的解析组件写删服务 S3 派生空间，DeepTutor ObjectStore 写删业务空间；两侧模型调用身份独立。实例池由独立运维预开/补池/回收，DeepTutor 只原子领取已登记服务，不因创建 KB 持有 K8s 管理权。上述解析/S3/状态接口为待交付契约，不能假称当前镜像原生具备。

## 为什么 Kubernetes 下不应使用 SQLite 作为主库

Kubernetes 生产部署通常要求：

- 应用 Pod 可水平扩缩容；
- Pod 可被重调度；
- 节点可能故障；
- 服务多副本；
- 状态外置；
- 可观测、备份、恢复、审计集中化。

SQLite 的天然模型是单机本地文件。将 SQLite 放到 K8s 生产主路径会带来问题：

| 问题 | 影响 |
| --- | --- |
| Pod 本地文件系统不持久 | Pod 重建后数据丢失 |
| PVC + 多副本访问复杂 | RWO/RWX 与 SQLite 文件锁模型不匹配 |
| 多个 backend Pod 写同一个 SQLite | 高并发写入、锁等待、损坏风险上升 |
| 缺少数据库级租户隔离 | 难以使用 RLS 等数据库防线 |
| 备份/恢复/审计弱 | 不符合企业多租户交付预期 |

参考：

- SQLite 使用场景：<https://sqlite.org/whentouse.html>
- Kubernetes Persistent Volumes：<https://kubernetes.io/docs/concepts/storage/persistent-volumes/>
- PostgreSQL Row Level Security：<https://www.postgresql.org/docs/current/ddl-rowsecurity.html>

## 目标拓扑

```text
Kubernetes Cluster
  ├── DeepTutor core + 企业包 backend Deployment（自有组合入口）
  │     replicas: 单执行模式受限；启用多执行者前通过 G-H（任意里程碑）
  │     stateless
  │
  ├── DeepTutor frontend Deployment
  │     stateless
  │
  ├── PostgreSQL
  │     tenants
  │     identities
  │     sessions
  │     messages
  │     turn_events
  │     grants
  │     webhook_events
  │     profile_cache
  │     master_data
  │     audit_logs
  │
  ├── S3-compatible Object Storage（DeepTutor 业务空间）
  │     KB 原文件
  │     attachments
  │     workspace outputs
  │     generated artifacts
  │
  ├── 企业 RAG Gateway / 文档管理 worker
  │     查询前授权、PG/Secret binding、导入/删除/引用/重建
  │
  ├── LightRAG Server API（用户 fork，生产验收待完成）
  │   固定 workspace 实例池，不按租户复制整套 DeepTutor
  │   ├── 检索 PostgreSQL（仅 LightRAG/运维可访问）
  │   │     KV/vector/doc_status；与应用库/角色隔离
  │   ├── HugeGraphStorage → 现有 HugeGraph
  │   │     实体/关系/图遍历；图身份、schema、恢复由 LightRAG 运维管理
  │   ├── 检索模型 provider（独立 profile/调用身份）
  │   └── 检索解析/任务组件
  │         S3 服务派生空间、manifest 及实际必需队列；按锁定契约交付
  │
  ├── 分布式运行时协调（H：多执行者前必须；可基于 PG，Redis/Queue 可选）
  │     websocket fanout
  │     turn coordination
  │     background jobs
  │     distributed locks
  │
  └── Kubernetes Secret / External Secrets
        EduPlus2 client_secret
        provider API keys
        应用数据库凭证；检索 PG/HugeGraph Secret 仅授权 LightRAG/运维
```

## 状态分类

| 状态类型 | 生产存储 | 说明 |
| --- | --- | --- |
| 租户、身份、授权 | PostgreSQL | source of truth |
| sessions/messages/turn_events | PostgreSQL | 支持多副本和集中查询 |
| grants | PostgreSQL JSONB + 结构化索引 | 替代 `data/system/grants/*.json` |
| settings / model catalog metadata | PostgreSQL + Secret 管理 | secret 不直接写入普通表响应 |
| EduPlus2 profile cache | PostgreSQL | 带 TTL / version |
| EduPlus2 master data | PostgreSQL | 租户级同步副本 |
| webhook events | PostgreSQL | 幂等、重试、审计 |
| audit logs | PostgreSQL / 日志平台 | 可按租户查询 |
| KB 原文件 | S3-compatible object storage | PG 保存 metadata/object key |
| attachments | S3-compatible object storage | PG 保存 metadata/object key |
| workspace outputs | S3-compatible object storage | 避免 Pod 本地状态 |
| RAG binding / 文档任务 | 应用 PG + Secret 引用 | tenant/KB/index-version、远端 doc/job ID 与对象映射 |
| LightRAG 文档/向量状态 | 受管 PostgreSQL | PGKVStorage / PGVectorStorage / PGDocStatusStorage，独立低权角色与 RLS/写检查 |
| LightRAG 图状态 | 现有 HugeGraph | 用户 fork HugeGraphStorage；scope 逻辑分区 + 服务端图权限，不自动回退 PG 图/Neo4j/AGE |
| 服务必要队列/解析任务 | 所选服务持久化机制 + 应用 PG job 对账 | 按实际 LightRAG 企业解析/任务方案锁定组件并验证恢复，不能按可丢弃缓存处理 |
| local scratch | ephemeral volume | 可丢弃，不作为 source of truth |


## S3-compatible 对象存储要求

生产环境对象存储必须通过 S3-compatible API 接入，而不是绑定单一云厂商 SDK。目标是让同一套 `S3ObjectStore` 可以适配 AWS S3、MinIO、Ceph RGW 以及其他提供 S3-compatible endpoint 的对象存储。

### 存储内容

S3 保存需跨 Pod/任务保留的文件：KB 原文/解析文件、登记的检索服务派生副本、聊天/笔记附件、持久工作区文件、生成/导出物、可编辑 skills/personas 正文及资源包，以及需保留的大文件导入暂存/昂贵中间产物。完整内容、权威归属和保留规则以 [07](07-resource-isolation.md) 为准；不是整个 `data/` 或 workspace 直接上传。

会话、grants、配置、任务、memory/notebook 正文进 PG；向量/图等按 06 存储契约外置，凭证进 Secret，普通临时文件留 scratch。备份/WAL、审计归档及 CI 制品如使用 S3，使用独立运维/CI bucket 与权限，不混入租户业务空间；不改变业务单 bucket + tenant prefix 规则。

对于文件对象，PostgreSQL 保存 metadata，不复制一份可独立编辑的文件正文：

```text
tenant_id, owner_user_id, object_key, bucket, content_hash, size, mime_type, encryption, retention, created_at
```

### Bucket 与 key 规则

推荐单 bucket + tenant prefix：

```text
s3://deeptutor-prod/tenants/{tenant_id}/shared/kb/{kb_id}/source/{object_id}
s3://deeptutor-prod/tenants/{tenant_id}/users/{user_id}/attachments/{attachment_id}
s3://deeptutor-prod/tenants/{tenant_id}/users/{user_id}/workspace/{artifact_id}
s3://deeptutor-prod/tenants/{tenant_id}/turns/{turn_id}/outputs/{object_id}
```

当前交付统一单 bucket + 内部 tenant prefix，不建设 bucket-per-tenant 另一条路线；未来有明确监管隔离要求再单独评估。

### 配置项（拟新增，需在目标 S3-compatible 服务验收）

建议通过环境变量/Secret 注入：

```bash
DEEPTUTOR_OBJECT_STORE=s3
DEEPTUTOR_S3_ENDPOINT_URL=https://s3.example.com
DEEPTUTOR_S3_REGION=<目标服务商要求的 region>
DEEPTUTOR_S3_BUCKET=deeptutor-prod
DEEPTUTOR_S3_ACCESS_KEY_ID=...
DEEPTUTOR_S3_SECRET_ACCESS_KEY=...
DEEPTUTOR_S3_FORCE_PATH_STYLE=true
DEEPTUTOR_S3_USE_SSL=true
DEEPTUTOR_S3_SERVER_SIDE_ENCRYPTION=<目标服务支持的 SSE 策略>
```

说明：

- `FORCE_PATH_STYLE` 对 MinIO、Ceph RGW 等私有化 S3-compatible endpoint 通常很重要。
- access key / secret key 必须来自 Kubernetes Secret / External Secrets / Vault。
- 不允许把 S3 credential 写入租户可见 settings 或 grants。

### 访问模式

默认推荐后端代理上传/下载，避免前端直接接触对象存储凭证。需要大文件直传时，可以由后端生成短时效 presigned URL：

- upload URL TTL 建议 5-15 分钟；
- download URL TTL 建议 1-10 分钟；
- presigned URL 生成前必须完成 app-level authorization；
- object key 必须由后端生成，禁止客户端提交任意 key。

### 安全要求

1. bucket 不公开。
2. 所有 object key 必须带 tenant prefix。
3. 后端写入前校验 `tenant_id` 与 key prefix 一致。
4. 开启 TLS。
5. 启用 server-side encryption；如客户要求可接入 KMS。
6. 开启 bucket lifecycle，清理临时对象和过期中间产物。
7. 启用访问日志或审计事件，至少记录 `tenant_id/object_key/request_id`。

### 一致性与幂等

- 统一使用 `PG pending + 对象配额预留 -> 上传并校验 -> PG ready + 核算`；失败持久化补偿、清理对象并释放预留。对象配额基础能力在阶段一完成。
- 失败清理通过后台 job 扫描 dangling objects。
- object key 建议包含不可猜测 `object_id`，避免覆盖。
- 同一内容可用 content hash 做去重，但去重不得跨租户暴露存在性信息。

## PostgreSQL 多租户模式

从阶段一固定租户开始采用：

```text
shared database + shared tables + tenant_id + Row Level Security
```

不推荐第一阶段使用 schema-per-tenant，原因：

- 多 schema 迁移成本更高；
- connection pool/search_path 管理复杂；
- 查询和跨租户运维更复杂；
- DeepTutor 当前还需要先完成 store abstraction。

### 基础原则

1. DeepTutor 应用业务表包含 `tenant_id`，平台级表除外；独立检索库按所选服务 schema 管理，不擅自假设已支持应用 tenant 字段；使用 [06](06-postgresql-native-store-plan.md) 的 namespace/受限身份/数据库强制隔离，不能把服务 RBAC 当 RLS。
2. 所有租户级表启用并强制 RLS；应用角色非 owner/superuser/BYPASSRLS。
3. 应用连接每个 request/transaction 设置当前 tenant：

```sql
SELECT set_config('app.tenant_id', $1, true);
SELECT set_config('app.user_id', $2, true);
```

4. RLS policy 使用 `current_setting('app.tenant_id', true)` 限制行可见性。
5. 应用层仍必须做权限判断；RLS 是防线之一，不替代业务权限。

## Kubernetes 配置建议

### Deployment

- backend 使用 `Deployment`，不是 StatefulSet。
- 单执行模式控制排空及实际执行者数量；如发布目标要求 HA 或启用多 Pod/多 worker 竞争执行，先完成 H/G-H，不绑定某一里程碑。
- 不挂载可写共享 SQLite 数据卷。
- 只挂载临时 scratch volume 或只读配置。
- 企业启动器与独立镜像配置位于包外/部署目录，按 [13](13-deployment-and-upstream-sync.md) 装配 core 与企业服务；默认镜像/启动器也必须接通 PG，不能绕过企业策略或落回原 local SQLite。
- 检索组件按 A1/A2 的 LightRAG 固定版本验收记录部署；应用/检索可共享 PG 集群但不共享高权账号。固定 workspace 绑定受限 PG/HugeGraph 身份，验证实例池容量、开通/回收、索引写互斥及受控迁移。HugeGraphStorage scope 不是 ACL；直接 REST/Gremlin 跨 KB/租户访问须拒绝。外置存储或 shared_storage pending fence 不等于跨部署多写/HA，写不确定性恢复、URI 一致性与数据库防线见 06。

### Secret / ConfigMap

- 非敏感配置使用 ConfigMap。
- DeepTutor 仅获应用 PG、S3、LightRAG API 及自身外部集成所需凭证；检索 PG、HugeGraph Basic/Bearer 凭证只授权 LightRAG 工作负载和对应运维 Job。两层 Secret/ServiceAccount/RBAC 分离，网络拒绝 DeepTutor 直连 HugeGraph，数据库权限拒绝其访问检索 PG；应用/检索 PG 共集群时不要求不同 TCP 地址，原始图与 Server API 不向租户开放旁路。
- 不把 secret 写入 `data/user/settings/*.json`。

### Job / CronJob

以下任务建议使用 K8s Job/CronJob：

- DeepTutor 应用 PostgreSQL migration；
- LightRAG 部署运维独立执行检索 PG 迁移及 HugeGraph 专属 schema/权限预置与 drift 校验（维护身份、互斥/版本历史；运行 `HUGEGRAPH_AUTO_CREATE_SCHEMA=false`，不删既有 schema）；
- EduPlus2 master data sync；
- webhook retry processor；
- backfill / migration from SQLite；
- stale turn cleanup。

### Probes

backend 至少提供：

- readiness：企业 provider/schema/版本与数据库、必要 S3/RAG Gateway 依赖可用；探测有超时/缓存，不静默回退；单个 KB Server 故障使对应操作明确失败，不能把所有空闲实例都作为全应用 liveness 依赖；
- DeepTutor 不设置直连 HugeGraph/检索 PG 的探针；对应 KB 的图依赖、schema/权限由 LightRAG 及其运维探测，经服务 API 就绪/错误状态反馈。图失败不禁图或切 PG，不让空闲 KB 阻断整个应用 liveness；联合恢复与容量仍进入 G1。
- liveness：进程健康；
- startup：模型/配置初始化完成。

## 内部 namespace 与运行时协调

对象 key、RLS、job/cache scope 使用内部 tenant_id/user_id，阶段二绑定外部 tid/eui 后保持不变；不建设新 local 多租户目录或 SQLite profile，企业 PathService 仅用于受控 scratch/只读资源。

H 工作线在启用多执行者前必须外置 turn/command/job 状态并实现原子领取、owner lease/fencing、事件游标重放、跨 Pod cancel/reply、幂等及失效清理。PG 持久化可以实现协调，Redis/队列是可选实现组件，但不能省略协调本身。所有运行模式的在途失败都要可见，不宣称 PG/S3 自动恢复 agent 执行。

Pod 生命周期与删除时的终止行为应纳入排空/故障测试，参考 [Kubernetes Pod 生命周期](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)。

## 禁止项

Kubernetes 生产环境禁止：

1. 多个 backend Pod 共享同一个 SQLite 主库文件。
2. 将 `data/user/chat_history.db` 作为生产会话 source of truth。
3. 将 grants/source of truth 放在 Pod 本地文件系统。
4. 将 provider secret 写入可被租户管理员下载的 settings 文件。
5. 依赖 RWX 网络盘解决 SQLite 多写问题。

## 可接受的 SQLite 用法

| 场景 | 是否接受 |
| --- | --- |
| 本地开发业务运行 | 不接受，使用 PG |
| 单机 demo / CLI-only 业务 | 不接受，使用 PG |
| 旧格式自动化测试 fixture | 接受，仅离线导入测试 |
| 独立导入工具读取一致旧快照 | 接受，只读且获授权 |
| 临时 cache / 内存 SQLite | 不接受 |
| K8s 生产主库 | 不接受 |

## 运维要求

1. 应用/检索 PostgreSQL、HugeGraph 数据/schema/权限与 S3/binding 必须有成套备份和恢复演练，记录一致性、RPO/RTO 与重建成本。
2. 支持 point-in-time recovery 的环境优先。
3. migration 通过 Job 单次执行，并有版本表记录。
4. 所有 tenant 数据访问日志带 `tenant_id/request_id`。
5. Object storage bucket 开启生命周期、加密、访问日志。
6. 所有 secret 通过 Secret/External Secret/Vault 管理。

## Woodpecker 交付入口

[05](05-woodpecker-kubernetes-pipeline.md) 定义 M1/A3 必交付流水线：从 A1 并行开发，可信镜像按 digest 晋级，先执行受控版本化 PG/图 schema 与权限迁移流程，再发布应用并通过真实 HTTP/WS/资源 smoke。采用版本化 Kustomize 清单与环境差异；PG/HugeGraph/S3、namespace、RBAC 和 Secret 由受控基础设施流程准备，普通应用发布不重建或删除这些依赖。

保留现上游 Dockerfile，通过 `deploy/images/` 独立企业镜像/启动器适配其前后端合并启动、本地 JSON 配置限制，再按组合制品交付，不能仅增加环境变量。单执行发布先排空并确认旧执行者退出，再启新执行者，不能只设置 replicas=1；实际更新产生竞争执行或要求 HA 时先通过 G-H。部署与回退共用环境锁，CI 中断后核对 Job/rollout，不能盲目重跑。

## K8s 集成提前与可靠性门禁

Woodpecker 流水线、部署清单、同构 PG/HugeGraph/S3 测试环境、Ingress/WS、Secret/probes 从 A1 与业务改造并行，A3 是生产总验收。测试集群能启动不是正式上线；不得借提前部署交付 SQLite 过渡生产版本。

单租户 HA 要求可使 G-H 成为 G1 前置；多租户在确认容量足够并接受非 HA/维护窗口时可先通过单执行模式 G2。未确认运行目标不能自行宣称已满足生产可用性。每次发布重审目标，扩容前执行 G-H，详情见 [02](02-rollout-testing-and-migration.md)。

### Externalized data directory rule

M1 Kubernetes backend pods must not mount a writable persistent `data/` PVC as business authority. Persistent files use S3-compatible ObjectStore with PostgreSQL `resource_objects` metadata. Local directories are limited to scratch/cache/projection/offline-import-input and are safe to lose during Pod rebuild.

Use `deploy/kubernetes/deeptutor-backend.yaml` as the reference shape: backend receives PG/ObjectStore/Secret references through ConfigMap/Secret/ExternalSecret, mounts only `emptyDir` scratch plus read-only config projection, and exposes readiness through `/health/ready`.
