# 04. Kubernetes 与 PostgreSQL-first 生产架构

## 与三阶段实施对齐

- M1：A1 结构化状态、A2 文件/检索、A3 生产验收；已启用功能使用 PG/S3，运行模式按已确认目标选择。
- M2：B1 先验证首租户 EduPlus2 最终接入，B2 再开放多租户和租户管理界面；多副本不是第二租户的必然依赖。
- M3：C1 运营管理闭环、C2 运营治理完善，不再迁库或替换对象存储。H 工作线独立决定多执行模式的 G-H 门禁。

不再安排“先 PG 控制面、后迁会话/文件”的生产过渡发布，详细门禁见 [02](02-rollout-testing-and-migration.md)。

## 决策结论

如果 DeepTutor × EduPlus2 的目标部署环境是 Kubernetes，则生产形态应采用：

```text
PostgreSQL-first + DeepTutor core/企业包无状态应用 + S3-compatible
+ 企业授权适配/固定 workspace LightRAG Server 实例池 + optional Redis/queue
```

上游已有 SQLite 仅在独立本地模式保留，生产无 fallback：

- 本地开发；
- CLI-only / 单机 demo；
- 测试 fixture；
- 兼容旧数据的迁移来源；
- 非关键临时 cache。

**SQLite 不作为 Kubernetes 单租户或多租户生产主库，也不新增企业文件型后端。**

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
  ├── S3-compatible Object Storage
  │     KB 原文件
  │     attachments
  │     workspace outputs
  │     generated artifacts
  │
  ├── 企业 RAG Gateway / 文档管理 worker
  │     查询前授权、PG/Secret binding、导入/删除/引用/重建
  │
  ├── 固定 workspace LightRAG Server 实例池
  │     只开放受控内部服务，不按租户复制整套 DeepTutor
  │
  ├── LightRAG 检索 PostgreSQL（与应用库/角色隔离）
  │     PGKVStorage / PGVectorStorage / PGDocStatusStorage / 已锁定 PG 图后端
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
        database credentials
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
| LightRAG 全部索引状态 | 受管 PostgreSQL | KV/vector/doc_status/graph 全覆盖；pgvector 不替代检索引擎，图后端与数据库防线见 [06](06-postgresql-native-store-plan.md) |
| local scratch | ephemeral volume | 可丢弃，不作为 source of truth |


## S3-compatible 对象存储要求

生产环境对象存储必须通过 S3-compatible API 接入，而不是绑定单一云厂商 SDK。目标是让同一套 `S3ObjectStore` 可以适配 AWS S3、MinIO、Ceph RGW 以及其他提供 S3-compatible endpoint 的对象存储。

### 存储内容

以下内容进入 S3-compatible 对象存储：

- KB 原文件、解析产物、大文件导入缓存；
- chat attachments；
- workspace outputs；
- generated artifacts；
- 可重建但成本较高的中间产物。

PostgreSQL 只保存 metadata：

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

1. DeepTutor 应用业务表包含 `tenant_id`，平台级表除外；独立 LightRAG 索引不擅自追加上游不认识的 tenant 字段，使用 [06](06-postgresql-native-store-plan.md) 的 workspace/受限角色/数据库强制隔离。
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
- 企业启动器与独立 Dockerfile 位于包外/部署目录，按 [13](13-deployment-and-upstream-sync.md) 装配 core 与企业服务；不要求重写上游 Dockerfile，不允许绕过企业入口启动默认本地模式。
- LightRAG 实例绑定固定 workspace/受限数据库身份，应用/检索可共享 PG 集群但不共享高权账号。实例池容量、单 workspace 写互斥、故障恢复和服务回收独立验证；不承诺原版 Server 多写副本自动安全。

### Secret / ConfigMap

- 非敏感配置使用 ConfigMap。
- `DATABASE_URL`、EduPlus2 client secret、LLM provider key 使用 Secret 或 External Secrets。
- 不把 secret 写入 `data/user/settings/*.json`。

### Job / CronJob

以下任务建议使用 K8s Job/CronJob：

- PostgreSQL migration；
- EduPlus2 master data sync；
- webhook retry processor；
- backfill / migration from SQLite；
- stale turn cleanup。

### Probes

backend 至少提供：

- readiness：企业 provider/schema/版本与数据库、必要 S3/RAG Gateway 依赖可用；探测有超时/缓存，不静默回退；单个 KB Server 故障使对应操作明确失败，不能把所有空闲实例都作为全应用 liveness 依赖；
- liveness：进程健康；
- startup：模型/配置初始化完成。

## 内部 namespace 与运行时协调

对象 key、RLS、job/cache scope 使用内部 tenant_id/user_id，阶段二绑定外部 tid/eui 后保持不变；不建设新 local 多租户目录，PathService 仅用于独立本地模式或 scratch。

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
| 本地开发 | 接受 |
| 单机 demo | 接受 |
| 自动化测试 fixture | 接受 |
| 从旧版本迁移读取源 | 接受 |
| 临时 cache，可丢失 | 可接受 |
| K8s 生产主库 | 不接受 |

## 运维要求

1. PostgreSQL 必须有备份和恢复演练。
2. 支持 point-in-time recovery 的环境优先。
3. migration 通过 Job 单次执行，并有版本表记录。
4. 所有 tenant 数据访问日志带 `tenant_id/request_id`。
5. Object storage bucket 开启生命周期、加密、访问日志。
6. 所有 secret 通过 Secret/External Secret/Vault 管理。

## Woodpecker 交付入口

[05](05-woodpecker-kubernetes-pipeline.md) 定义 M1/A3 必交付流水线：从 A1 并行开发，可信镜像按 digest 晋级，先执行版本化 PG 迁移 Job，再发布应用并通过真实 HTTP/WS/资源 smoke。采用版本化 Kustomize 清单与环境差异；PG/S3、namespace、RBAC 和 Secret 由受控基础设施流程准备，普通应用发布不重建或删除这些依赖。

保留现上游 Dockerfile，通过 `deploy/images/` 独立企业镜像/启动器适配其前后端合并启动、本地 JSON 配置限制，再按组合制品交付，不能仅增加环境变量。单执行发布先排空并确认旧执行者退出，再启新执行者，不能只设置 replicas=1；实际更新产生竞争执行或要求 HA 时先通过 G-H。部署与回退共用环境锁，CI 中断后核对 Job/rollout，不能盲目重跑。

## K8s 集成提前与可靠性门禁

Woodpecker 流水线、部署清单、同构 PG/S3 测试环境、Ingress/WS、Secret/probes 从 A1 与业务改造并行，A3 是生产总验收。测试集群能启动不是正式上线；不得借提前部署交付 SQLite 过渡生产版本。

单租户 HA 要求可使 G-H 成为 G1 前置；多租户在确认容量足够并接受非 HA/维护窗口时可先通过单执行模式 G2。未确认运行目标不能自行宣称已满足生产可用性。每次发布重审目标，扩容前执行 G-H，详情见 [02](02-rollout-testing-and-migration.md)。
