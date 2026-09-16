# WeKnora / LightRAG Server 本地选型评估（2026-09-13）

> **评估后的决策更新**：现行路线为用户 `LFunTech/LightRAG` fork + `HugeGraphStorage`，PG 存 KV/vector/doc_status，HugeGraph 存图；多租户底座及隔离负例在 M1 验收，B1/B2/G2 才开放真实多租户。用户 fork 已增加图适配代码，但固定生产制品、权限、容量与恢复仍待验证。**本报告实测的是当时官方版本 + PG 图，不是新 fork + HugeGraph 的验收证据。** 下文保留评估时措辞和原始结论；现行方案以 [06](../06-postgresql-native-store-plan.md) 为准。

## 结论与适用边界

**图检索必须保留、DeepTutor 负责最终回答的前提下，当前建议优先接入 LightRAG Server；若最终选定该路线，建议首发图后端使用 `PGTableGraphStorage`。** WeKnora 保留为需补齐图检索接入的候选，而非继续无条件优先。此建议来自固定版本源码与真实 Docker 接口验证，**不代表真实教材质量胜出或生产定型**。

用户已提供可用 HugeGraph；只读检查确认其为 **1.7.0**，版本接口和配置图接口均返回 200，未写入现有图。用户没有要求必须复用 HugeGraph，也没有确认图只能在 PG。推荐 PG 图后端是为了降低首发自维护适配成本，不是把 PG-only 当成用户硬约束。

| 路线 | 当前判断 | 主要原因 |
| --- | --- | --- |
| **LightRAG Server + PGTableGraphStorage** | **首选待接入路线** | 现有 DeepTutor client 可获得图检索上下文，原生存储类可用；代价是固定 workspace 实例池与企业文档管理、权限补齐 |
| LightRAG Server + HugeGraph | 有明确复用需求时单独评审 | 没有原生后端，需要图存储实现及注册/加载扩展、隔离和恢复验证；本轮未开发 |
| WeKnora + Neo4j | 需额外图检索接口适配 | 原生多 KB、文档管理较完整，但当前 DeepTutor 调用的 `knowledge-search` 不走图检索；额外维护图数据库及服务依赖 |
| WeKnora + HugeGraph | 当前不优先 | 不仅需要更换图 repository，还要补齐 DeepTutor 所需的纯检索图路径；不能只换连接地址 |

本轮仅新增评估证据并同步建议，不修改生产代码、生产配置或现有 HugeGraph 数据，不勾选企业实施任务。A1/A2 的完整门禁仍按 [06 方案](../06-postgresql-native-store-plan.md) 执行。

## 固定版本与真实环境

| 项目 | WeKnora | LightRAG Server |
| --- | --- | --- |
| Release | [v0.8.0](https://github.com/Tencent/WeKnora/releases/tag/v0.8.0)，2026-09-03 发布 | [v1.5.7](https://github.com/HKUDS/LightRAG/releases/tag/v1.5.7)，2026-09-02 发布 |
| 源码 commit | `1edcd54b43606d9079bb36650efe3f68707a79ea` | `28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c` |
| 镜像 | `wechatopenai/weknora-app:v0.8.0` | `ghcr.io/hkuds/lightrag:v1.5.7` |
| 镜像 digest | `sha256:14953fcb990c59b2546f00e94673d2a4c88689e3319bfcf2b06f82feaccec9b4` | `sha256:5bdbd524931b011df246fe20888d110cef691e6804c12cde636a2b746d7de27e` |
| 依赖 | ParadeDB `v0.22.2-pg17`、Redis `7.4-alpine`、docreader `v0.8.0`、Neo4j `5.26-community` + APOC、MinIO S3 | `pgvector/pgvector:pg17`，KV/vector/doc_status/graph 全 PG；S3 原文由测试程序另外管理 |

- Docker Desktop `desktop-linux`，原生 arm64，12 CPU、31.29 GiB 可用内存。独立 Compose project `local-debug-rag-eval`，宿主端口仅绑定 `127.0.0.1`。
- 两套 LightRAG 实例使用同一 PG、不同固定 workspace `eval_a` / `eval_b` 与 API key。WeKnora 单服务创建两个测试账号/空间和 KB。
- 真实调用阿里百炼 `qwen-plus` 与 `text-embedding-v4`（1024 维），统一非思考、chat 最大输出 4096 tokens，无 rerank 模型。代理只记录 model/status/usage，不记录凭证和 prompt。
- WeKnora 图启用且成功建图；本轮 Neo4j 是 5.26，并非该 release 官方 compose 的 2025.10.1 组合，不把此结果外推到另一版本。
- MinIO 同一 release 的 Docker Hub 拉取失败后，使用官方 Quay 镜像 `RELEASE.2025-09-07T16-13-09Z`。完整依赖 digest、语料与观测数据见[脱敏结果 JSON](2026-09-13-rag-services-results.json)。

## 测试方法与结果

没有现成教材集，因此构造 4 个中文 Markdown，共 **1015 bytes**：A 范围三篇含跨文档机构关系、计算规则及识别串 `AURORA-731`，B 范围一篇含同名实体、相反规则与 `BOREAL-926`。这些是虚构识别串，不是真实口令。五个问题覆盖直接事实、跨文档关系、计算依据、周期、项目归属。

查询使用仓库当前的真实 HTTP client，而非 mock；模型请求不是桩。另单独执行两个 adapter 的既有单元测试，**27 passed**，不能将这些 MockTransport 测试算作 Docker 实测。

| 验证项 | LightRAG Server | WeKnora |
| --- | --- | --- |
| 导入与索引完成 | 四文档 processed | 四文档 completed，摘要完成、图启用 |
| 五问的预期证据是否出现在 context | 5/5；未见 B 识别串 | 5/5；未见 B 识别串 |
| 当前接入路径的图检索 | `/query` `mix` 返回图上下文；另 `/query/data` `local` 返回 15 entities、15 relationships、3 chunks、3 references | Neo4j 实际有 19 nodes、14 edges；但 `/api/v1/knowledge-search` 未执行图检索 |
| 两个独立范围 | A/B 固定实例分别返回自己的识别串 | A/B 空间分别返回自己的识别串 |
| 错误调用身份/范围 | B key 请求 A 实例：403 | 无认证：401；限 KB key 跨空间 KB、混合 A+B：403；retrieve key 写入：403 |
| workspace 请求头 | 对 A 发 `LIGHTRAG-WORKSPACE: eval_b` 仍返回 A，不能动态切换检索范围 | 使用接口 KB 参数与服务端空间授权，不依赖该 header |
| 同空间个人私有语义 | 未验证企业 owner/grant | 加入空间的 Viewer 能检索 owner 的 KB；这是空间权限语义，不等于个人默认私有 |
| key 撤销 | 未验证企业撤权链路 | scoped key 撤销后查询：401 |
| 新空 scratch + 原存储恢复 | 重建容器并挂全新 `/app/data` volume，原资料查询成功 | 重建容器并挂全新 `/data/files` volume，同 PG/S3 查询成功 |
| 删除一个测试文档 | 异步删除后文档列表、引用与公式 context 均消失；S3 原文由测试程序另删 | 删除后文档 GET 404，检索无旧引用/公式；原生 S3 副本同步消失 |
| 原文/重解析 | S3 独立测试程序验证字节一致、签名读 200、匿名读 403 | API 下载字节一致；原地 reparse 完成；恢复/重解析后下载仍一致 |
| PostgreSQL 默认 RLS | public 普通表 0/13 开启 RLS | public 普通表 0/66 开启 RLS |

### 为什么 WeKnora 建图成功仍不满足当前接入要求

固定版本 `SearchKnowledge` 的事件列表只有 `CHUNK_SEARCH`、`CHUNK_RERANK`、`CHUNK_MERGE`、`FILTER_TOP_K`，没有 `ENTITY_SEARCH`。本轮停止 Neo4j 后，该接口仍 200、返回 5 个结果；结合源码确认当前检索路径未使用图，**不是仅凭停机成功推断没有图能力**。[固定版本查询实现](https://github.com/Tencent/WeKnora/blob/1edcd54b43606d9079bb36650efe3f68707a79ea/internal/application/service/session_knowledge_qa.go#L812-L941)

WeKnora 的其他聊天流水线有实体检索实现；若选择它，需要增加/暴露受保护的图检索或向量+图上下文接口，并适配 DeepTutor，不能用服务自己的最终问答替换 DeepTutor 回答职责。也不能仅开启 `NEO4J_ENABLE` 就宣称当前 adapter 已支持图检索。[实体检索实现](https://github.com/Tencent/WeKnora/blob/1edcd54b43606d9079bb36650efe3f68707a79ea/internal/application/service/chat_pipeline/search_entity.go)

### 质量、延迟与费用：能说明什么，不能说明什么

- 五问仅检查预期证据字符串出现，不是答案准确率、关系正确率或真实教材召回基准。LightRAG 每次带三份文件引用，WeKnora 返回五个片段（含摘要），检索预算和流程不同。
- **人工复核发现派生文本失真**：原文只说两机构独立，LightRAG 关系描述却追加“无隶属或协作关系”，同时保留“提供资金支持”；WeKnora 摘要扩写为“技术体系上均无关联”。两者都出现无依据扩写，必须把图事实忠实性、摘要与原文冲突纳入后续质量验收，不能因 5/5 命中就称质量合格。
- 五次单次查询的中位耗时：LightRAG **1.560 s**，WeKnora **0.301 s**。前者包含图/关键词模型流程，后者本接口未走图；这是本机流程观测，**不能据此说 WeKnora 的同等图检索更快**，也没有 p95、并发或 SLA 结论。
- 代理记录 69 次成功模型请求：chat 26 次，输入 28,632 / 输出 4,447 tokens；embedding 43 次，输入 3,702 tokens。另有代理外预检：chat 输入 15 / 输出 3，embedding 输入 13。未查账，不给费用金额，不据此比较两服务生产成本。
- 单次空闲样本：LightRAG 每实例约 317–318 MiB；WeKnora app 约 195 MiB，另需 Neo4j 约 671 MiB、docreader 约 150 MiB、PG 约 128 MiB、Redis 约 12 MiB。两套还使用 PG/S3 等依赖，不能只比主进程内存。大规模 KB 实例池、共享服务吞吐均未测试。

## HugeGraph 接入评估

通过 `.secrets` 的测试配置只读请求 `/versions` 与配置图路径，均为 200；不在文档或结果中保存地址、用户名、密钥。HugeGraph 1.7 使用含 graphspace 的 REST 路径，提供 Gremlin/遍历及 OpenCypher HTTP API；这些不等于 Neo4j Bolt + APOC 的可直接替换实现。[官方 REST API](https://hugegraph.apache.org/docs/clients/restful-api/)

两套固定版本源码均未发现 HugeGraph/Gremlin 后端。LightRAG 容器内执行 `verify_storage_implementation("GRAPH_STORAGE", "HugeGraphStorage")` 明确抛出不兼容的 `ValueError`；其注册表有 PGTableGraphStorage，但没有 HugeGraphStorage。[固定版本存储注册](https://github.com/HKUDS/LightRAG/blob/28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c/lightrag/kg/__init__.py)

- **LightRAG 路线**：实现 `BaseGraphStorage` 对应的节点/边、度数/邻接、批量、遍历/子图、删除和 namespace 语义，补齐注册/加载扩展；验证共享实体删除、并发幂等、重试、版本恢复及数据库授权。可复用现有图检索编排，但不是只加环境变量。
- **WeKnora 路线**：替换 graph repository 并调整依赖装配；固定实现使用 neo4j-go-driver/v6 及 `apoc.merge.node`、`apoc.merge.relationship`、`apoc.periodic.iterate`。即使 repository 接口方法较少，也不能省略语义验证；还须解决上述 DeepTutor 检索接口没有图步骤的问题。[Neo4j repository](https://github.com/Tencent/WeKnora/blob/1edcd54b43606d9079bb36650efe3f68707a79ea/internal/application/repository/retriever/neo4j/repository.go)

因此，**已有 HugeGraph 不会自动让 WeKnora 更适合**。若必须统一使用 HugeGraph，更倾向评审 LightRAG 存储扩展；但本轮没有 HugeGraph 写入、算法效果、容量或安全实测，不能宣布这一组合可投产。采用非 PG 图存储前，须同步修改企业规范、部署拓扑及权限/备份恢复门禁，不运行时自动切后端。

## 接入工作量与 S3 责任

1. **LightRAG 最大约束是固定 workspace。** 当前 Server 启动构造单个 `LightRAG(workspace=args.workspace)`；某些接口识别 workspace header 不意味着查询引擎可切换。按内部 tenant/KB/index-version 绑定受控实例池，必须测实例生命周期、连接/内存预算和索引写互斥。容量不达标时应重新评审动态服务层，不能合并不同可见范围的图。[Server 初始化](https://github.com/HKUDS/LightRAG/blob/28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c/lightrag/api/lightrag_server.py)
2. **WeKnora 文档管理与多 KB 是真实优势。** 上传、状态、下载、删除、原地重解析、限能力/限 KB key 已验证，但企业个人私有授权、图检索路径、版本原子切换仍需补齐。固定版本 scoped key 以 capabilities/KB allowlist 配置，登录返回 `active_tenant`；不能直接照搬旧文档的角色参数或 `tenant` 字段。
3. **WeKnora PG 模式不只是 pgvector。** 固定迁移还要求 `pg_search`、`pg_trgm`；本轮使用 ParadeDB，不能把普通 PG+pgvector 配置作为已验证部署。镜像其他预装扩展不意味着全部必需。[固定版本 embeddings 迁移](https://github.com/Tencent/WeKnora/blob/1edcd54b43606d9079bb36650efe3f68707a79ea/migrations/versioned/000002_embeddings.up.sql)
4. **两者均未通过企业数据库防线。** 本轮使用镜像默认初始化 DB 权限，观察到默认表无 RLS；尚未交付低权运行/迁移角色或企业受限身份。容器进程 UID=1000 不等于数据库最小权限。HTTP 隔离负例通过不等于 G1/G2 通过。
5. **S3 不因图后端变化而改变核心责任。** 权威原文、需保留的解析文件/图片、附件和生成物仍进 S3；图、向量、业务 metadata 不作为活动 JSON 文件全量搬上 S3。备份归档另按备份策略管理。LightRAG 没有在本轮实现原生 S3：测试程序另外保存/删除原文，并非企业入口完整链路。WeKnora 原生 S3 副本实测前缀为 `derived/{远端 tenant ID}/{knowledge ID}/{uuid}.md`，不是企业内部 UUID namespace，仍需 locator、额度和唯一写删责任适配。

## 未验证项与后续验收

- 真实教材 PDF/OCR、公式/表格/图片、页码引用、跨章节复杂问答；需建立人工标注集，加入关系抽取忠实性及图检索消融对照。
- 双租户/同租户个人私有的完整企业授权与撤权、PG RLS/图权限、低权启动和受控迁移。
- 从 S3 重建全新 index-version 并原子切 binding、备份恢复、失败任务对账、并发索引/多执行者和 HA。
- 等价图检索配置下的负载、p95、容量与实际费用；HugeGraph 存储扩展及其全部读写测试。

**空 scratch 恢复不是数据库备份恢复；WeKnora 原地 reparse 不是新索引版本原子切换；测试程序完成 S3 删除不是企业 RagDocumentService 已实现。** 本轮证据只支持工程候选排序，不替代这些门禁。

## 证据与本机复验

公开保留[脱敏结果 JSON](2026-09-13-rag-services-results.json)，包含版本/digest、完整合成语料、五问的脱敏请求/预期字符串/匹配规则、去重保存的完整检索 context 与结构化图结果、HTTP 负例、生命周期结果、用量、资源样本及原始证据 SHA-256。原始响应与本轮 Compose/随机凭证保留在本机临时目录，路径可从 `/tmp/deeptutor-rag-eval-path` 读取；临时目录可能被系统清理，不作为长期档案。含凭证 Compose、原始日志和模型 Secret 不进入仓库。

无需密钥的[离线复核脚本](verify_rag_evidence.py)可重新计算保存结果的语料/context hash、字符串命中、中位耗时与图计数；它不调用模型，也不冒充重新执行 Docker 测试：

```bash
python3 docs/enterprise/evaluations/verify_rag_evidence.py
```

既有 adapter 单元测试执行命令（pytest 依赖装在本轮临时目录，未安装进项目 venv）：

```bash
WORK=$(cat /tmp/deeptutor-rag-eval-path)
PYTHONPATH="$WORK/testdeps:$PWD" .venv/bin/python -m pytest -p no:cacheprovider \
  tests/services/rag/test_weknora_pipeline.py \
  tests/services/rag/test_lightrag_server_pipeline.py -q
```

本轮容器在收尾后停止，镜像/测试 volumes 保留，不清理用户其他资源。需要人工复验时可恢复本轮项目（测试 key 撤销、文档删除等状态也被保留，不应直接重跑非幂等初始化脚本）：

```bash
WORK=$(cat /tmp/deeptutor-rag-eval-path)
docker compose -p local-debug-rag-eval -f "$WORK/stack/compose.json" start
# 复验结束后停止，不使用 down -v 删除证据
docker compose -p local-debug-rag-eval -f "$WORK/stack/compose.json" stop
```
