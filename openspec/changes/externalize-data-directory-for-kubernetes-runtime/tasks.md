## 1. A1 — 生产 data 目录清单、PG/Provider 基础与门禁

- [x] 1.1 冻结 `data/` 读写 inventory：覆盖 settings/system/postgres-resources/workspace/notebooks/knowledge_bases/memory/partners/logs/runtime、PathService、OwnerResourceProvider、NotebookManager、settings/grants/model APIs、CLI/SDK/后台；逐路径标注 `forbidden-authority`/`externalized`/`projection`/`scratch`/`cache`/`offline-import-input`/`local-dev-only`，并记录真实入口与 owner/tenant 权限边界。
- [x] 1.2 增加显式 production/kubernetes runtime mode 与启动/readiness gate；真实容器环境验证未分类 `data/` 写入、本地权威 provider、SQLite/PocketBase/backend fallback、缺 PG/schema/Secret 时均 fail closed 且错误脱敏，本地 PG-only 开发模式不被误拒。
- [x] 1.3 设计并追加应用 PG resource metadata 与 settings/policy/secret-reference schema migration，复用现有 `enterprise.schema_history`/MigrationRunner/运行角色权限；真实 PG 验证空库、已有 PG-only 数据升级、漂移、并发 apply、运行角色 DDL/staging 权限拒绝。
- [x] 1.4 实现 ObjectStore/SettingsProvider/SecretResolver/ResourceHandle 的 core seam 与 no-op/local-dev 实现边界；单元和集成测试证明生产 mode 不能实例化本地权威 provider，CLI/SDK/import/help 不提前连接外部服务或读取 Secret 明文。
- [x] 1.5 为 production data gate 增加静态和运行期测试：新进程禁止创建本地权威文件，`data/` 删除后已提交 PG-only 会话仍可读，未知路径写入导致 readiness fail；测试报告列出每个例外的类别和原因。
- [x] 1.6 更新 OpenSpec 执行证据模板与迁移 report 格式，要求记录每个切片的 DB migration、真实入口、权限/异常测试、Pod 重建证据、Secret 脱敏证据和未完成本地路径清单。

## 2. A2 — S3-compatible ObjectStore 与文件资源外置化

- [x] 2.1 实现 S3-compatible ObjectStore provider（endpoint、region、bucket、path-style、TLS、SSE、timeout、retry、hash/size verify），凭证仅来自 SecretResolver；按 S3-compatible 契约测试覆盖缺 bucket、权限不足、hash mismatch、网络中断和错误脱敏，不要求针对具体存储产品建立额外验收矩阵。
- [x] 2.2 将 `OwnerResourceProvider`/附件 store 改为生产 ObjectStore + PG metadata；真实 Web/API/WS/SDK 聊天附件上传、下载、删除、重启恢复、跨 owner 拒绝、PG 提交失败补偿和 ObjectStore 删除失败重试均通过。
- [x] 2.3 将 reading materials、workspace outputs、generated artifacts、导出文件和持久中间产物接入 ObjectStore；覆盖页面/API/工具读取、排序/版本、删除、presigned/proxy 下载、空本地盘重建和旧本地路径伪造拒绝。
- [x] 2.4 将 KB 原文与 DeepTutor 业务空间对象 metadata 接入 ObjectStore，同时保持 LightRAG 派生空间责任边界；验证 KB 导入/删除/引用、RAG binding、缺 LightRAG 状态、跨 tenant/KB 访问和服务派生副本不由 DeepTutor 直连图库补偿。
- [x] 2.5 将 dynamic personas、skills 正文及资源包从生产本地 workspace 迁到 ObjectStore/PG metadata；验证 agent/tool 自动装配、编辑/版本、权限、回滚和本地 dev 目录兼容，不让用户路径决定资源归属。
- [x] 2.6 迁移 notebook 普通文件正文/索引的生产权威到 PG 或 PG metadata + ObjectStore；验证 `list_notebook`/`write_note`、Web notebook 引用、聊天上下文、权限、损坏旧文件、空本地盘重建和旧 `data/user/notebooks` 不再作为生产读取来源。
- [x] 2.7 实现 ObjectStore cleanup/reconciliation job：pending/uploaded/delete-pending/dangling 对象扫描、幂等清理、租户/owner 限制、失败可查询；验证不会跨 tenant 删除、不会删除仍被 PG 引用的对象。
- [x] 2.8 对 A2 文件资源执行容量与重尾样本验证：大附件、批量 workspace outputs、persona/skill 包、KB 原文、删除风暴、对象生命周期；记录实测吞吐/延迟/成本边界，不用本地文件性能冒充生产结果。

## 3. A3 — K8s/镜像/部署、迁移工具与发布验收

- [x] 3.1 更新 Docker/K8s manifests、Helm/Kustomize 或部署示例：backend Deployment 不挂载可写持久 `data/` 权威，只挂 scratch/只读投影；ConfigMap/Secret/ExternalSecret/S3/PG env refs 完整，前端不含 DSN/Secret。
- [x] 3.2 实现 `data/` 文件与 settings 的离线 inventory/plan/import/verify/report CLI：只读扫描源、hash、owner 映射、目标 provider、冲突、Secret 明文阻断、引用重写和 report 脱敏；隔离 fixture 覆盖路径逃逸、symlink、hash 漂移、未知 owner、重复导入和中断重跑。
- [x] 3.3 增加生产 readiness/status API：报告 PG/ObjectStore/Settings/Secret provider、data gate、cleanup backlog、migration version 和外部依赖状态；权限控制和脱敏测试覆盖普通用户、tenant_admin、ops 角色和匿名访问。
- [x] 3.4 在 K8s-like 集成环境跑完整空本地盘 smoke：创建会话/附件/reading/workspace/persona/skill/notebook/settings/grants，删除 Pod 和本地 `data/` 后重建，验证 API/WS/CLI/SDK/background 恢复一致且无本地 fallback。
- [x] 3.5 增加双 Pod 读写与排空验证：两个 backend Pod 共享 PG/ObjectStore/Secret provider 读取一致；写入竞争按当前执行协调和单执行模式拒绝/排队，不依赖共享 PVC、本地文件锁或 rsync。
- [x] 3.6 更新 README、docs/postgresql-runtime-runbook.md、docs/enterprise/04/06/07/13、compose/K8s 文档，明确 local-dev 与 production mode 差异、`data/` 分类、S3/Secret 配置、迁移步骤、回退策略和不可用 PVC 方案。
- [x] 3.7 构建最终 wheel/镜像并在全新环境安装运行，验证无 `.secrets`/本地 data 权威依赖；记录镜像 digest、migration version、ObjectStore provider、Secret refs、smoke 结果和未发布/未 cutover 边界。

## 4. B1 — 单租户 K8s 集成与外部身份前准备

- [x] 4.1 在固定单租户 production mode 中接通现有 PG identity/session 与 Settings/ObjectStore provider，验证登录、撤权、改密、模型配置、附件/KB/workspace 访问和空本地盘恢复与当前本地 PG 行为一致。
- [x] 4.2 将租户/owner/resource binding 与未来 EduPlus2 外部身份字段对齐：不自动按用户名/路径归属，真实 API/WS/CLI/SDK 负例覆盖伪造 tenant、跨 owner object key、管理员读取私有资源和旧 local path anchor。
- [x] 4.3 验证 settings/grants/model policy 的版本缓存失效：撤权或模型访问变更后 HTTP/WS/CLI/SDK/background 均按新版本拒绝；旧 Pod、连接池和本地投影不能继续使用旧授权。
- [x] 4.4 单租户维护流程演练：停写、data inventory、ObjectStore/settings import、verify/report、Pod 重建 smoke、失败回退；记录实际数据量、耗时和人工确认点，不连接用户真实业务数据。

## 5. B2 — 多租户与租户管理边界复验

- [x] 5.1 使用两个测试租户、同租户两用户和 tenant_admin 运行 ObjectStore/Settings/Secret provider 权限矩阵；验证相同 object key 后缀、同名 KB/persona/skill/notebook、缓存复用和批量 cleanup 均不串租户/owner。
- [x] 5.2 将 TMS 可管理的模型/工具/KB/workspace/object 配置接入 Settings/Policy provider；验证 `/tms` 入口、API 权限、菜单状态、生效版本、失败状态和普通用户不可写。
- [x] 5.3 多租户导入/迁移 report 增加 tenant scope、source fingerprint、owner mapping、Secret 引用和对象前缀校验；坏映射、目标已有冲突、跨租户引用和旧源重放必须阻断。
- [x] 5.4 复验 LightRAG binding 与 ObjectStore 原文权限：共享 KB、个人 KB、同名实体、跨 KB 删除/查询、服务派生副本状态和直接对象/图旁路负例，不把固定 workspace 当作 tenant 内全员可读。

## 6. C1 — 运营配置、Secret 治理与审计闭环

- [x] 6.1 建立平台/租户配置与 Secret 引用的运营 API 契约：desired/saved/active/failed/draining 状态、版本、操作者、脱敏摘要、审计事件；验证 admin/operator/auditor/tenant_admin 权限边界。
- [x] 6.2 实现 Secret 轮换与执行者生效确认：模型、ObjectStore、PG、LightRAG API、cookie/signing/auth epoch 等引用更新后不泄露明文；失败回滚、旧版本排空和状态展示可审计。
- [x] 6.3 将配置/资源变更审计写入 PG/日志平台：object create/delete、settings change、grant change、Secret ref change、migration import/promotion；验证审计查询不展示私有正文或 Secret。
- [x] 6.4 更新前端 Settings/Admin/TMS 显示：managed/locked/draft/active/failed 状态、Secret 引用缺失、provider readiness、ObjectStore 配额/错误；不再把本地 settings 文件写失败显示成普通 500。

## 7. C2 — 运营治理、用量、清理与恢复完善

- [x] 7.1 聚合 ObjectStore 用量、pending/failed cleanup、导入任务、配置生效失败、Secret 轮换失败和外部资源错误；OMS 只展示脱敏 metadata，不展示私有文件正文或长期下载 URL。
- [x] 7.2 实现运营侧重试/取消/补偿边界：只允许对授权 tenant/resource/job 操作，不能扩大为整个 workspace 或直接操作 bucket prefix；验证操作幂等和审计。
- [x] 7.3 完成 PG + ObjectStore + Secret binding 成套备份/恢复演练：恢复旧快照后重验身份世代、撤权、对象引用、pending cleanup、未确认外部副作用；不得只回滚 PG 后开放业务。
- [x] 7.4 执行生产级失败演练：ObjectStore 部分不可用、Secret provider 延迟、PG 连接中断、Pod 驱逐、cleanup job 重启、presigned URL 过期；验证 fail closed、补偿和用户可理解错误。
- [x] 7.5 完成最终范围审查：逐 `data/` inventory、spec、enterprise docs 和真实入口核对无生产本地权威路径；运行 change/all strict、适用 lint/type/test/build/K8s smoke，记录不可验证项和后续 G/H 边界。

## H. 多执行者 / HA 条件性门禁

- [x] H.1 若目标发布启用多 backend/worker 竞争执行，先通过 G-H：turn/background/cleanup/import/settings propagation 使用持久协调、租约和 fencing；验证旧 worker、网络分区、时钟偏差和重复补偿不造成双写或对象误删。
- [x] H.2 若目标声明 HA/RPO/RTO，必须对 PG、ObjectStore、Secret provider、LightRAG binding 和日志/审计执行成套故障演练并记录实测值；不能仅因 backend Deployment 有多个副本就宣称 HA。
- [x] H.3 单执行模式发布时记录非 HA 边界、维护窗口、恢复步骤和操作者确认；readiness/leader/lease 配置不得让第二执行者在旧执行者未确认停止时自动接管不确定副作用。
## 8. Post-completion correction — dynamic skill/persona 本地权威缺口

- [x] 8.1 将用户创建与 hub 导入的 dynamic skill package 从生产本地 `data/user/workspace/skills` 权威迁到 PG `resource_objects` + S3-compatible ObjectStore package；验证 Pod 本地空盘重建、跨 tenant 拒绝、`read_skill` runtime provider、hub provenance、`always` 安全剥离和 builtin skill 镜像只读边界。
- [x] 8.2 将动态 persona 正文从生产本地 `data/user/workspace/personas` 权威迁到 PG `resource_objects` + S3-compatible ObjectStore package；验证 turn persona context/runtime provider、Pod 本地空盘重建和跨 tenant 拒绝。
- [x] 8.3 复查所有直接/间接 `data/` 读写入口，补显式 `skills`/`personas` inventory 与入口静态回归测试；记录仍属于 local-dev/cache/scratch/offline/import 或已由既有 forbidden/externalized 声明覆盖的路径，不再把本地目录作为生产 skill/persona 权威。
- [x] 8.4 更新 proposal 与执行证据，说明本修正不新增 PG schema，不新增 OpenFGA/Keycloak 迁移，生产持久层仍仅要求 PostgreSQL + S3-compatible ObjectStore + Secret/Settings provider。

## 9. Post-completion correction — 删除 `data/` 后 tenant_admin 权限与 grants/workspace 权威

- [x] 9.1 统一 PG `tenant_admin` 部署级管理员语义：settings/model catalog/system status/skills/personas/partners/tool policy 等后端检查使用 `can_manage_deployment()`，避免前端已识别为管理员但后端仍按 legacy local `CurrentUser.is_admin` 拒绝；同时保留 legacy `admin` 对本地文件工作区的旧语义，避免把租户管理员误绑定到 `data/user` 本地权威。
- [x] 9.2 将用户 grants 在 PG provider 绑定时迁到 `enterprise.runtime_policies(policy_kind='user_grant')` 作为权威，`data/system/grants` 仅作为 local-dev fallback；`multi-user` 分配目标优先从 PG `enterprise.users` 解析，删除 `data/system/auth/users.json` 后不再 404。
- [x] 9.3 修正默认 workspace scratch/projection 恢复：默认工作区目录在本地 `data/` 被清空后可自动重建 outputs；显式选择的自定义 workspace 仍必须存在并继续 fail closed，不能静默改写到新本地权威。
- [x] 9.4 更新 OpenSpec proposal/spec/evidence，记录本修正不新增 PostgreSQL schema，不新增 OpenFGA/Keycloak migration；使用既有 PG `runtime_policies`、现有 users 表和默认 workspace 投影语义完成。
- [x] 9.5 将默认 PostgreSQL 部署配置路径从 `data/user/settings/postgres.json` 移到 runtime home 的 `config/postgres.json`，并更新 `.env.example`/runbook，避免删除 `data/` 时连启动所需 PG Secret 引用配置一起删除；K8s 仍通过显式 `/etc/deeptutor/postgres.json` projection 配置。

## 10. Post-completion correction — 删除 `data/` 后知识库/LightRAG 可用性

- [x] 10.1 将 legacy `main.yaml` 改为可缺省 runtime config：删除本地 `data/user/settings/main.yaml` 后新进程导入知识库/题目等 router 不崩溃，只注入 runtime paths；未知非 main YAML 仍返回 FileNotFound，避免隐藏真实配置缺失。
- [x] 10.2 保留 `/api/knowledge-bases/upload-policy` 兼容别名并回归测试其与 `/supported-file-types` 返回一致，避免旧前端 bundle 或缓存请求被 `/{kb_name}` 动态路由误判为 KB 详情。
- [x] 10.3 外部连接知识库（`lightrag_server`/WeKnora/Obsidian/linked 等）在列表 API 中标记 `read_only=true`，前端不得展示本地上传/建文件夹/reindex 的可写语义；后端写操作仍按 `_assert_not_connected_kb()` 返回 409。
- [x] 10.4 本地开发环境配置并创建可写内置 `lightrag` KB（`local-lightrag`）作为默认知识库，保留既有 `test` LightRAG Server 外部连接为只读资源；记录不新增 PG schema、OpenFGA/Keycloak migration 或具体存储产品依赖。
- [x] 10.5 修正 Knowledge Files/Add Documents 前端只读传播：`KbFilesTab`/`KbDocumentList`/upload helper 必须尊重 `kb.read_only`，不显示新建文件夹、移动、删除、本地上传等写入口；回归测试证明外部只读 KB 不再向本地文件 API 发起写请求。
