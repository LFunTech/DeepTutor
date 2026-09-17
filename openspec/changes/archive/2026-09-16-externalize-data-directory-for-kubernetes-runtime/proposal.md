## Why

`migrate-all-sqlite-state-to-postgresql` 已将 SQLite/PocketBase 业务状态迁到 PostgreSQL，但当前默认运行仍有配置、文件资源、workspace、notebook/persona/skill、日志与部分目录约定落在 `data/`。未来目标环境是 Kubernetes `Deployment`：Pod 本地文件系统不可作为持久层，继续依赖 `data/` 会导致重建丢数据，也与 `docs/enterprise/04/06/07/13` 中“无状态 backend + PostgreSQL + S3-compatible + Secret/Settings provider”的生产方案不一致。

## What Changes

- **生产/K8s runtime 明确无状态化。** 在显式 production/kubernetes runtime mode 下，backend Pod 不得把 `data/` 作为 source-of-truth；本地目录仅可用于 scratch、只读配置投影、临时缓存或离线导入输入。
- **外置持久文件与资源。** 聊天附件、阅读材料、KB 原文/导入制品、workspace outputs、生成/导出物、动态 skills/personas 正文及需跨 Pod 保留的中间产物使用 S3-compatible ObjectStore，PG 保存元数据、owner/grant、版本、hash、size、retention 与 object key。
- **外置配置与 Secret。** 用户/租户可变 settings、model catalog metadata、grants、feature/tool policy、runtime binding 等进入 PG/Settings provider；敏感值仅以 Secret 引用保存，实际 DSN/API key/token 由 Kubernetes Secret / External Secrets / Vault 注入后端或维护 Job，不写入 `data/user/settings`、前端、日志或 report。
- **保留本地开发边界。** 本机开发和 CLI 可以继续以 `data/` 作为 runtime home 的文件布局，但业务状态仍遵守已归档 PG-only specs；生产模式必须 fail closed，不能静默退回 local file provider 或 PVC 文件型权威。
- **补齐迁移与验证制品。** 提供现有 `data/` 内容 inventory、迁移/导入计划、兼容投影策略、Pod 重建/空本地盘 smoke、权限与回退手册。真实用户数据迁移、生产 cutover、发布和提交仍需单独授权。
- **补充修正 DeepTutor dynamic skill/persona 本地权威缺口。** 2026-09-16 复查发现 `SkillService`/`PersonaService`、`read_skill`、turn manifest 与 API 仍可能落到 `data/user/workspace/{skills,personas}`；本 proposal 明确补入 post-completion correction：用户/导入 skills 与动态 personas 在绑定 PG + S3-compatible ObjectStore 时必须走 `resource_objects` metadata + ObjectStore package，builtin skills/persona presets 仅作为镜像内只读资源，Pod 本地目录不得作为生产权威。
- **补充全 `data/` 读写排查要求。** 排查不只 grep `data/` 字符串，还覆盖 `PathService`、`get_path_service()`、`get_admin_path_service()`、partner workspace copy、settings/model/grants、KB/RAG、notebook/memory/workspace outputs、runtime/cache/logs 等间接路径；新增显式 `skills`/`personas` inventory 条目，后续新增未分类生产本地权威路径必须被 gate/test 阻断。
- **补充修正删除 `data/` 后 PG 管理员权限丢失问题。** 2026-09-16 本地复现发现：PG 默认管理员以 `tenant_admin` 登录后，前端认为其是管理员，但部分后端权限判断仍只认 legacy local `CurrentUser.is_admin` / 本地 `data/system/*`，导致 settings/model catalog/grants/skill/persona/partner 等管理能力在删除 `data/` 后表现为无权限或空授权；本 proposal 补入 post-completion correction：部署级管理员语义统一为 `tenant_admin` 可管理部署，普通用户 grant 在 PG provider 绑定时以 `enterprise.runtime_policies` 为权威，默认 workspace scratch/projection 可在本地盘清空后重建，PG 部署配置默认位置移出 `data/`，不能依赖 `data/` 中的本地 grants/users/workspace/config 文件。
- **补充修正删除 `data/` 后知识库/LightRAG 可用性问题。** 2026-09-16 继续本地验证发现：`main.yaml` 仍被知识库等 legacy router 作为必需本地 YAML 导入，删除 `data/` 后新进程会在导入阶段失败；旧前端 bundle 仍可能请求 `/api/knowledge-bases/upload-policy` 并被动态 KB 名路由吞掉；用户创建的 `lightrag-server` 外部连接 KB 被列表标成可写，导致前端开放上传/建文件夹但后端按外部只读连接返回 409。本 proposal 补入 post-completion correction：`main.yaml` 缺失时按空 runtime config 注入路径且不写回 `data/`，保留非 main YAML 缺失 fail closed；保留 upload-policy 兼容别名；外部连接 KB 在列表层明确 `read_only=true`，内置 `lightrag` KB 才作为可写/可上传知识库。

## Capabilities

### New Capabilities

- `kubernetes-stateless-runtime`: 规定 Kubernetes/production runtime 下 `data/` 只能是 scratch/projection/cache，业务 source-of-truth 必须外置并可通过 Pod 重建恢复。
- `externalized-resource-store`: 规定文件类持久资源通过 S3-compatible ObjectStore + PG metadata/authorization 管理，替换本地 OwnerResourceProvider/PathService 的生产权威职责。
- `externalized-runtime-configuration`: 规定可变 settings、grants、model catalog metadata、feature/tool policy 与 Secret 引用的 PG/Settings provider 契约，以及 Kubernetes Secret/ConfigMap 投影边界。

### Modified Capabilities

- 无。本 change 在已归档 PG-only 能力之上新增生产/K8s 无状态化要求；不倒改 `postgres-only-runtime` 对本机 PG-only 开发模式和离线导入例外的定义。

## Impact

- 后端启动/lifespan、readiness、配置加载、ApplicationContainer、PathService、OwnerResourceProvider、附件/阅读/KB/workspace/persona/skill/notebook 服务、settings/admin/model/grants API、CLI/SDK provider 装配、后台任务、导入/导出与删除清理。
- 新增或扩展 ObjectStore 抽象、S3-compatible provider、PG metadata schema、Settings/Secret provider schema、migration/import/report 工具、K8s/compose 部署模板和 runbook。
- 前端 Settings/Workspace/Knowledge/Reading/Chat attachments 需显示外置化状态与只读/受管限制，不暴露 Secret 值。
- 需要真实 PostgreSQL、S3-compatible 对象存储和 Secret 注入的集成验证；不连接或迁移用户真实业务数据，除非另获授权。
