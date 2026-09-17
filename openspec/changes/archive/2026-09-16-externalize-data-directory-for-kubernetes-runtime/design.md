## Context

见 [proposal](proposal.md) 的动机。当前已归档的 PG-only specs 解决了 SQLite/PocketBase 业务状态问题，但 `data/` 仍承载多类非 SQLite 文件：settings、system/user-secrets 目录结构、postgres-resources、workspace、notebooks、personas/skills、knowledge_bases、logs/runtime 等。`docs/enterprise/04-kubernetes-postgresql-architecture.md`、`06-postgresql-native-store-plan.md`、`07-resource-isolation.md` 与 `13-deployment-and-upstream-sync.md` 已明确生产目标是 backend Deployment 无状态，持久状态进入应用 PG、S3-compatible ObjectStore 和 Secret/Settings provider。

本 change 是对归档 PG-only 结果的后续补齐：它不重开 SQLite 迁移范围，而是将 `data/` 目录中的生产持久职责外置化，并让 K8s production mode 对仍依赖本地权威的路径 fail closed。

## Goals / Non-Goals

**Goals:**

- 定义并实现显式 Kubernetes/production runtime mode，使 Pod 本地 `data/` 不作为业务 source-of-truth。
- 将持久文件资源统一到 S3-compatible ObjectStore + PG metadata/authorization；本地 provider 仅用于 local-dev、scratch、cache、projection 或离线输入。
- 将生产可变 settings/grants/model catalog/policy/binding 移到 PG/Settings provider；Secret 明文仅由 Secret provider 注入。
- 提供 `data/` inventory、迁移 plan/import/verify/report、K8s Pod 重建 smoke 与回退手册。
- 与企业文档保持一致：应用不直连 HugeGraph/检索 PG，不把对象存储凭证暴露给前端，不以 PVC 复制 `data/` 作为生产解法。

**Non-Goals:**

- 不把所有文件内容塞进 PostgreSQL；大文件和可编辑资源包走 ObjectStore，PG 保存 metadata/引用。
- 不替代 LightRAG 内部的检索 PG/HugeGraph/解析队列；DeepTutor 只管理业务 binding、原文/附件/产物和对账。
- 不自动迁移真实用户 `data/`；真实迁移、cutover、发布、提交仍需单独授权。
- 不删除本地开发 runtime-home 布局；只要求 production/K8s 模式 fail closed。
- 不以 Kubernetes PVC、共享 NFS 或 sidecar rsync 作为新的生产权威存储。

## Decisions

### 1. 显式 runtime mode 与 `data/` 分类门禁

新增受控运行模式（实施时可采用 `DEEPTUTOR_RUNTIME_MODE=production` / `kubernetes` 或等价配置字段），默认本地开发仍保持现有 runtime-home 行为；K8s 部署清单必须显式启用 production mode。

生产启动前执行 `data/` inventory gate。每个路径/服务声明类别：

- `forbidden-authority`：生产禁止，如本地 settings 写入权威、本地附件权威、本地 notebook 权威。
- `externalized`：已由 PG/ObjectStore/Secret provider 接管。
- `projection`：由权威 provider 生成的只读投影，可删除重建，不反向同步。
- `scratch`：任务临时目录，可丢弃。
- `cache`：可重建缓存，无业务唯一状态。
- `offline-import-input`：维护命令只读输入，业务 runtime 不读取。
- `local-dev-only`：只允许非 production mode。

替代方案：继续挂载整个 `data/` 到 PVC。拒绝原因：与 Deployment 无状态目标冲突，也无法解决多 Pod 一致性、备份/审计、Secret 分离和跨租户授权问题。

### 2. ObjectStore 是文件权威，PG 是可见性和生命周期权威

新增通用 ObjectStore/provider seam，并提供 S3-compatible 实现。生产 OwnerResourceProvider/PathService 不返回可直接信任的本地路径，而是通过 PG metadata 校验 owner/grant 后代理读取或生成短 TTL URL。

PG metadata 至少记录：tenant_id、owner_id、resource_kind、resource_id/object_id、bucket/key、hash、size、mime、state、version、retention、created_by、created_at、updated_at、引用计数或来源引用。实际 schema 复用已有 `enterprise` schema_history，追加版本化 migration；不引入第二套迁移工具或另一个业务数据库。

写入采用 `PG pending/reserved -> ObjectStore put -> hash/size verify -> PG ready`。删除采用 `delete-pending -> object delete -> deleted`，失败记录可重试补偿。跨 PG/S3 无事务，因此用户可见状态只能以 PG ready 为准。

替代方案：把文件以 bytea/JSON 存 PG。拒绝原因：容量、备份/WAL、流式下载和对象生命周期成本不可控，且企业文档明确文件走 S3-compatible。

### 3. Settings/Policy provider 与 Secret 引用分离

生产可变 settings 进入 PG-backed Settings/Policy provider 或企业平台 Settings 服务；Secret 明文仅通过 Kubernetes Secret / External Secrets / Vault 等 provider 注入运行进程。PG/settings 中只保存引用名、scope、版本、desired/active 状态和脱敏摘要。

本地 `data/user/settings/*.json` 在 production 中只可作为只读 bootstrap 投影或完全禁用；任何 UI/API 保存都必须写受控 provider。已有前端提示 “Model configuration is managed by an administrator” 需要与 provider 状态一致：明确显示 managed/locked/draft/active/failed，而不是本地文件写失败或 403 混淆。

替代方案：继续把 `postgres.json`、`model_catalog.json`、`integrations.json` 放在 mounted `data/`。拒绝原因：Secret 引用与权限状态无法集中审计，Pod 重建和多 Pod 生效状态不可验证。

### 4. Workspace、Notebook、Persona、Skill 分层外置

- 用户可见持久 workspace outputs、导出物、生成制品、可编辑 persona/skill 正文和资源包走 ObjectStore + PG metadata。
- `exec`、解析、临时下载、格式转换使用 scratch；只有提交成功并写入 ObjectStore/PG 后才对用户可见。
- notebook 普通正文若属于用户业务内容，进入 PG 或 PG metadata + ObjectStore；不能长期留在 `data/user/notebooks` 作为生产权威。
- local development 的文件 workspace 继续保留，但 production UI 应展示“受管对象工作区”或“外部持久 workspace binding”，不把 Pod 本地路径暴露给用户选择。

替代方案：把整个 workspace 目录同步到对象存储并保持 POSIX 语义。拒绝原因：对象存储不是 POSIX 文件系统；同步双写会制造冲突、删除语义和审计漏洞。

### 5. 迁移与回退使用显式维护流程

本 change 复用上一轮离线导入原则：真实迁移必须先停写/冻结、inventory、plan、import、verify/report，再由授权操作者 cutover。对本地 `data/` 文件不做启动时自动迁移，不在业务请求路径中“发现旧文件并顺手上传”。

迁移报告必须列出：源路径、hash、目标 provider、object key、owner/tenant 映射、引用重写、失败项、敏感字段处理、是否需要人工 Secret 映射。Secret 明文不写入 report。

回退策略：一旦生产已对 PG/ObjectStore 产生新写，禁止切回旧本地 `data/` 权威。只能使用兼容当前 PG/ObjectStore schema 的旧应用，或经批准成套恢复 PG/ObjectStore/Secret binding 备份并记录损失窗口。

### 6. 验收以空本地盘和多 Pod 行为为准

完成验收不能只看单进程 API smoke。必须在隔离 K8s-like 或容器环境中：

1. 启动 production mode，禁止 writable persistent `data/` authority。
2. 创建会话、附件、workspace output、settings/policy、persona/skill 或 notebook 样本。
3. 删除/重建 Pod，并以空本地 `data/` 启动。
4. 验证所有已提交状态从 PG/ObjectStore/Secret provider 恢复。
5. 验证本地 provider/路径 fallback 被拒绝，错误脱敏。
6. 验证两个 Pod 不依赖本地共享文件即可读取一致状态；写竞争仍按现有执行协调和未来 H/G-H 约束处理。

## Risks / Trade-offs

- **本地开发与生产模式分叉导致回归遗漏** → 增加 production mode 专用测试矩阵，同时保留 local-dev PG-only smoke；文档明确两者差异。
- **PG/S3 无跨系统事务** → 所有文件状态以 PG metadata 为用户可见权威，ObjectStore 操作失败进入补偿队列，report 展示 dangling/pending 对象。
- **Secret 迁移可能误写明文** → importer 默认阻断明文 Secret，要求显式 Secret provider 映射；日志/report 只输出引用和脱敏摘要。
- **workspace POSIX 语义无法完全复制到对象存储** → production 中把“持久工作区”建模为对象集合/资源包，scratch 才提供临时 POSIX 目录；UI/API 明确 managed state。
- **容量和对象生命周期成本上升** → 设计中纳入 hash、size、retention、lifecycle、配额和清理 job；容量测试不把小样本结果外推为生产保证。
- **现有代码 PathService 直接返回 Path 的调用面大** → 先做 inventory 和 fail-closed gate，再逐域替换为 ResourceHandle/ObjectRef，避免一口气用全局 monkey patch 隐藏漏洞。

## Migration Plan

1. **Inventory 与分类**：扫描 `data/` 读写调用、PathService/OwnerResourceProvider/NotebookManager/settings/grants/persona/skill/workspace/K中心/reading/attachments/outputs；生成生产类别清单和门禁测试。
2. **Provider 基础**：实现 ObjectStore 抽象、S3-compatible provider、PG resource metadata schema、Settings/Policy provider schema、Secret reference model 和 readiness 检查。
3. **调用方替换**：按附件/reading/KB/workspace/notebook/persona/skill/settings/model/grants/后台任务顺序迁移到 provider seam；本地 provider 仅保留 local-dev 和离线 fixture。
4. **离线迁移工具**：实现 `data/` 文件和 settings inventory/plan/import/verify/report，不自动处理真实数据。
5. **部署与文档**：更新 Docker/K8s manifests、ConfigMap/Secret 示例、runbook、README 与 enterprise docs，明确 `data/` 在 production 中不是持久层。
6. **验收**：运行 PG+S3+Secret 集成测试、空本地盘重建、多 Pod read smoke、旧 local fallback 负例、Secret 脱敏、delete/cleanup/retry 和 OpenSpec strict validation。

## Open Questions

- 生产只面向 S3-compatible Storage 契约：endpoint、region、bucket、path-style、TLS、SSE、timeout、retry、hash/size verify 和 SecretResolver 凭证来源。具体存储实现的专属能力、默认值调优和供应商矩阵不进入本 change 验收范围。
- settings provider 首版是否仅实现应用 PG，还是同时预留企业平台 Settings 服务 adapter；两者都必须满足相同 spec。
- 动态 persona/skill 大小阈值：小正文可直接 PG，大资源包走 ObjectStore；阈值可在实现阶段按容量测试确定。
