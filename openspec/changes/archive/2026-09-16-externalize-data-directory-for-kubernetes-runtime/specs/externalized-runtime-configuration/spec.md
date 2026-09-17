## Purpose

规定 Kubernetes/production 环境中运行配置、模型目录、授权策略、feature/tool policy 与 Secret 引用的外置化契约，避免 `data/user/settings`、`data/system` 或 Pod 本地文件成为可变配置和敏感信息的权威来源。

## ADDED Requirements

### Requirement: 可变运行配置必须由受控 provider 持久化

系统在 production mode 下 SHALL 使用 PostgreSQL-backed Settings/Policy provider 或平台配置服务保存可变运行配置，包括模型目录 metadata、默认模型选择、工具/能力开关、tenant/user grants、feature policy、workspace binding 和部署 binding。Pod 本地 settings 文件 MAY 是只读启动投影或缓存，但 MUST NOT 成为写入权威。

#### Scenario: 管理员保存模型配置
- **WHEN** 租户管理员或平台管理员通过设置界面/API 修改模型 profile、默认模型或工具策略
- **THEN** 修改写入受控 provider 并按权限/版本生效，Pod 重建后仍可读取；系统不把该修改只写入 `data/user/settings/model_catalog.json`

#### Scenario: production 下尝试写 settings 文件
- **WHEN** production runtime 中的业务 API 或后台任务尝试把可变配置写入 `data/user/settings` 或 `data/system`
- **THEN** 系统拒绝或改写到受控 provider，并记录脱敏诊断；不能静默落盘后返回保存成功

### Requirement: Secret 只保存引用和值分离

系统 SHALL 将 DSN、模型 API key、ObjectStore credential、LightRAG API Secret、cookie/signing/auth epoch secret、外部集成 token 等敏感值保存在 Kubernetes Secret / External Secrets / Vault 或等价 Secret provider 中。PG/settings 只保存 Secret 引用、版本、作用域和生效状态；任何用户可读 API、前端 settings、日志、report 或 OpenSpec 证据 MUST NOT 输出 Secret 明文。

#### Scenario: 使用 Secret 引用启动
- **WHEN** backend Pod 启动并读取 PG、ObjectStore、模型或身份签名配置
- **THEN** 它通过环境/挂载/Secret provider 解析引用到内存，readiness 只报告引用名、版本或缺失原因，不打印 Secret 值

#### Scenario: PG 部署配置不在 deletable data 目录
- **WHEN** backend 使用默认 runtime home 或 Kubernetes projection 加载 PostgreSQL 部署配置
- **THEN** 默认配置路径位于 runtime home 的 `config/postgres.json` 或显式 `DEEPTUTOR_POSTGRES_CONFIG` 指向的 Secret/ConfigMap 投影；删除 `data/` 不会删除启动所需的 Secret 引用配置

#### Scenario: legacy main.yaml 缺失不阻断新进程导入
- **WHEN** backend Pod 或本地 PG runtime 在 `data/user/settings/main.yaml` 缺失的空本地盘上启动，并导入仍调用 `load_config_with_main("main.yaml")` 的 legacy router/module
- **THEN** loader 将 `main.yaml` 视为可缺省空 runtime config 并注入 canonical runtime paths，不写回 `data/` 作为新权威；未知非 main YAML 缺失仍 fail closed，避免把真实配置缺失伪装成默认值

#### Scenario: Secret 缺失或版本不匹配
- **WHEN** 配置引用的 Secret 不存在、权限不足、版本不符合或与 active policy 冲突
- **THEN** 相关功能 fail closed，返回脱敏错误并阻止模型调用、对象写入或认证签发，不创建本地 fallback Secret 文件

### Requirement: 配置变更必须具备版本、审计和生效状态

系统 SHALL 为生产可变配置记录操作者、scope、版本、变更摘要、生效目标和状态。配置保存成功不等于所有执行者已生效；系统 MUST 区分 draft/saved/active/failed/draining 等状态，并提供可审计查询。

#### Scenario: 模型配置保存后等待执行者生效
- **WHEN** 管理员保存新的模型 profile 或默认模型
- **THEN** 系统记录 desired version，并在执行者确认或失败后更新 active/failed 状态；前端不能仅因文件保存成功就显示所有 Pod 已生效

#### Scenario: 撤销权限后缓存失效
- **WHEN** grants、feature policy 或模型访问权限被撤销
- **THEN** 后续 HTTP/WS/CLI/SDK/background 操作按新版本拒绝，连接池、缓存或旧 Pod 不得继续使用旧授权访问资源

### Requirement: 部署级管理员权限和用户 grants 不得依赖本地 data

系统 SHALL 区分 legacy local workspace `admin` 与 PostgreSQL-backed `tenant_admin`。在 PG provider 绑定的 production/runtime 中，`tenant_admin` SHALL 具备租户/部署级 settings、model catalog、tool policy、skill/persona/partner 管理权限；普通用户 grants SHALL 由受控 provider 持久化。本地 `data/system/auth`、`data/system/grants` 或 `data/user/settings` 文件 MAY 仅作为 local-dev fallback，MUST NOT 成为 PG 管理员权限或用户授权的生产权威。

#### Scenario: 删除本地 data 后 tenant_admin 仍有管理权限
- **WHEN** PG 默认管理员以 `tenant_admin` 身份登录，且 backend Pod 以空本地 `data/` 目录重建
- **THEN** auth/status、settings/model catalog、tool policy、skill/persona/partner 管理 API 仍按 `tenant_admin` 授权；后端不得因 `CurrentUser.is_admin == false` 或缺少本地 `data/system` 文件而返回无权限

#### Scenario: 用户 grant 从 PG provider 读取
- **WHEN** 租户管理员为普通用户保存工具、模型、KB、skill 或 learning policy grant
- **THEN** grant 写入 PG/settings-policy provider，并在删除 `data/system/grants` 后仍可读取和执行；只有未绑定 PG provider 的 local-dev 模式可回退本地 JSON

#### Scenario: PG 用户分配不依赖本地 users.json
- **WHEN** 租户管理员为同租户 PG 用户分配资源，而本地 `data/system/auth/users.json` 不存在
- **THEN** assignment target 从 PG identity provider 解析；系统不得因本地身份 JSON 缺失而把有效 PG 用户视为 404

### Requirement: 旧配置文件升级必须可计划和回退

系统 SHALL 提供 `data/user/settings`、`data/system/grants`、`data/system/user-secrets`、旧 model catalog 和相关 JSON/YAML 的迁移 plan/import/verify/report。迁移 MUST 区分非敏感配置、Secret 引用、不可导入明文和本地开发专用项；不得把明文 Secret 写入 PG 或报告。

#### Scenario: 规划 settings 迁移
- **WHEN** 操作者对旧 runtime home 执行配置迁移 plan
- **THEN** 系统报告哪些字段进入 PG/settings provider、哪些转换为 Secret 引用、哪些保留为本地开发配置，以及缺失/冲突/敏感项处理建议

#### Scenario: 导入包含明文 API key 的旧文件
- **WHEN** 旧 settings 或 system 文件包含模型 API key、DSN、token 或 cookie secret 明文
- **THEN** importer 不把明文写入 PG/report；必须要求操作者提供 Secret provider 映射或将该项标为阻断/待处理
