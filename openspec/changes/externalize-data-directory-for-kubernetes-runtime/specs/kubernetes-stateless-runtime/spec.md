## Purpose

规定 DeepTutor 在 Kubernetes/production 部署中的无状态运行契约，确保 Pod 本地 `data/` 目录不再承载业务权威状态，Pod 重建、重调度或清空本地盘后仍能从 PostgreSQL、ObjectStore 和 Secret/Settings provider 恢复服务。

## ADDED Requirements

### Requirement: 生产 runtime 不得以本地 data 作为权威状态

系统在显式 Kubernetes/production runtime mode 下 SHALL 将 `data/` 视为非权威目录。业务状态、可变配置、持久文件、Secret、授权和后台任务 MUST 使用受支持的外置 provider；如果任何已启用功能仍需要本地 `data/` 才能保持权威状态，启动或 readiness MUST fail closed。

#### Scenario: 检测到本地权威 provider
- **WHEN** 生产 runtime 启动且附件、workspace、settings、notebook、persona、skill、grant 或业务后台任务仍配置为本地文件权威
- **THEN** readiness 返回未就绪并给出脱敏升级错误，不继续派发模型、后台任务或写入本地文件权威

#### Scenario: 仅使用 scratch 和投影目录
- **WHEN** 生产 runtime 只把本地目录用于 scratch、只读配置投影、临时下载缓存或离线导入输入
- **THEN** readiness 可以继续通过外置 provider 检查，且删除这些本地目录不会丢失已提交业务状态

### Requirement: Pod 重建后业务状态可恢复

系统 SHALL 支持在同一已授权 tenant/owner 下重建 backend Pod，且不依赖旧 Pod 的本地 `data/` 内容恢复已提交状态。恢复后 API/WS/CLI/SDK 读取 MUST 来自 PostgreSQL、ObjectStore 和 Secret/Settings provider。

#### Scenario: 清空本地 data 后重启
- **WHEN** 用户已创建会话、附件、workspace output、配置和授权，然后 backend Pod 被删除并以空本地 `data/` 目录重建
- **THEN** 用户仍能读取已提交业务状态和文件引用，未完成 scratch 任务按不确定/失败语义恢复，不出现静默空数据或新建本地权威库

#### Scenario: 默认 workspace 投影可重建
- **WHEN** backend Pod 本地 `data/user/workspace` 被清空，而用户没有显式选择外部自定义 workspace
- **THEN** 默认 workspace/scratch/projection 目录可在新 Pod 中重建并继续生成新的 outputs；系统不得把该目录缺失解释为用户失去权限，也不得把重建后的本地目录作为已提交业务文件的生产权威

#### Scenario: 自定义 workspace 缺失仍 fail closed
- **WHEN** 用户或管理员显式选择了非默认 workspace 路径，且该路径在 Pod 重建后不存在
- **THEN** 系统返回可理解的缺失错误并阻止写入，不能静默改用新的 `data/user/workspace` 目录来冒充原 workspace

#### Scenario: 多 Pod 不共享本地状态
- **WHEN** 两个 backend Pod 同时处理同一租户的读写请求
- **THEN** 它们通过外置 provider 和已批准的执行协调保持一致，不通过共享 PVC、本地文件锁或复制 `data/` 实现业务一致性

### Requirement: data 目录用途必须可审计分类

系统 SHALL 提供生产运行时 `data/` 用途 inventory 和启动期检查，将每个路径分类为 `forbidden-authority`、`externalized`、`projection`、`scratch`、`cache`、`offline-import-input` 或 `local-dev-only`。未知类别 MUST 阻断生产 readiness。

#### Scenario: 新增未分类路径
- **WHEN** 代码或配置新增对 `data/` 下路径的写入或持久读取，但该路径未登记生产类别
- **THEN** 生产检查失败并报告路径类别缺失，不能把未知文件默认当作缓存或用户数据

#### Scenario: 离线导入输入不进入业务 runtime
- **WHEN** 维护操作者提供旧 SQLite/PocketBase/data 快照作为离线导入输入
- **THEN** 该输入只在维护命令范围内可读，业务 runtime 不从该路径提供用户可见状态

### Requirement: 本地开发兼容不得削弱生产约束

系统 MAY 保留本机 PG-only 开发和 CLI 的 `data/` runtime-home 布局，但这种模式 MUST 显式区别于 Kubernetes/production mode。测试、文档和配置 MUST 避免把本地开发目录挂载为生产持久化方案。

#### Scenario: 本地模式继续使用 data runtime home
- **WHEN** 开发者在非 production mode 下运行本机 PG-backed Web/CLI/SDK
- **THEN** 非敏感本地配置、日志和 workspace 可以继续放在 `data/`，但已归档 PG-only 业务状态仍不得回退 SQLite/PocketBase

#### Scenario: 生产配置误用本地开发模式
- **WHEN** Kubernetes manifest、环境变量或启动参数请求 local data authority、SQLite/PocketBase backend 或无 ObjectStore 的持久文件功能
- **THEN** 系统拒绝启动或 readiness fail closed，并提示需要外置 provider 而不是自动创建本地目录
