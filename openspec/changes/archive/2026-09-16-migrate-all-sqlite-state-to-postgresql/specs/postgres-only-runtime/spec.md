## Purpose

规定本仓库完整应用与 CLI-only 发行物的 PostgreSQL-only 运行契约，统一默认 Web、CLI、SDK、工具和后台的持久化与可信身份边界，取消无 PG 的 local/SQLite 兼容模式，同时保留原有业务能力而非退化为文本聊天演示。

## ADDED Requirements

### Requirement: 默认业务入口必须使用 PostgreSQL

本仓库支持的默认 Web/API/WS、CLI、SDK 与后台业务 SHALL 使用应用 PostgreSQL，不提供 SQLite/PocketBase/文件或内存业务数据库替代 profile。远程客户端 SHALL 通过认证连接已使用 PG 的服务，不要求向浏览器或远程 CLI 分发数据库凭证。系统 MUST 允许本机部署连接 PG，但不得继续提供无需 PG 的 local 业务模式。

#### Scenario: 默认入口完成业务
- **WHEN** 用户经默认 Web、CLI 或 SDK 创建并读取同一已授权资源
- **THEN** 各入口看到同一 PG 已提交状态，重启或换工作目录不创建另一份本地数据库

#### Scenario: 请求旧存储模式
- **WHEN** 旧配置指定 SQLite、PocketBase 或仅提供 local 数据目录来启动业务
- **THEN** 入口返回明确升级错误，不接受旧存储配置、不自动搬文件或回落另一后端

### Requirement: PG 预检失败不得产生业务副作用

系统 MUST 在提供业务服务、派发模型/工具或启动调度前校验必需配置、PG 连接、schema 与运行权限。失败时 SHALL 提供脱敏诊断并保持未就绪；执行中失去数据库或执行权时 MUST 停止相关派发/提交，不返回未持久化成功。纯 import、帮助/版本和离线检查不要求创建业务连接。

#### Scenario: PG 不可用或 schema 漂移
- **WHEN** 默认应用缺少 PG 配置、连接失败或 schema/运行角色不合约
- **THEN** 业务启动失败且 readiness 不通过，不生成 SQLite、不派发模型、不泄露 DSN/Secret

#### Scenario: 无数据库获取帮助
- **WHEN** 用户运行帮助、版本命令或仅导入 SDK 模块
- **THEN** 操作可完成而不创建数据库、生成默认身份或访问业务库

### Requirement: 核心和企业入口共享同一数据库契约

完整应用及 CLI-only 包 SHALL 独立包含所需 PG 运行支持，不要求安装企业业务包才能使用默认业务。企业入口 SHALL 复用相同身份/业务记录与迁移历史，保留其部署/治理约束；升级 MUST 保留首切片已提交数据和标识，不建立第二套身份或会话权威。

#### Scenario: 未安装企业包
- **WHEN** 从独立完整应用或 CLI-only 制品安装并提供合法 PG 配置
- **THEN** 默认业务能够使用 PG，且不因缺少企业包而退回 SQLite或只能调用 chat-only 入口

#### Scenario: 首切片 PG 数据升级
- **WHEN** 对包含首切片身份/会话数据的受控 PG 应用版本化升级
- **THEN** 原 tenant/user/session 和事件引用保持可验证，迁移历史连续，企业与默认入口不产生分叉记录

### Requirement: 默认入口保持可信身份和资源隔离

默认入口 MUST 从受保护认证或受控执行身份取得 tenant/owner，不能因取消 local profile 而开放全局 admin 或接受客户端自定租户。个人资源读取/操作 SHALL 复验 owner 或既有明确 grant；管理员角色不等于读取他人内容的权利。账号、撤权与恢复世代 SHALL 使用同一 PG 身份契约。

#### Scenario: 旧无认证配置或伪造租户
- **WHEN** 用户用旧无认证 admin 模式、伪造租户参数或他人的资源 ID 发起请求
- **THEN** 请求在资源访问前拒绝，不绑定默认管理员或从本地账号文件恢复权限

#### Scenario: 跨入口撤权
- **WHEN** 用户禁用、改密或认证会话撤销后继续通过 WS、CLI、SDK 或后台操作
- **THEN** 后续敏感读写/控制及执行均按当前身份状态拒绝，不能凭缓存令牌继续使用 PG 数据

### Requirement: 全量迁移保留现有业务能力

数据库替换 SHALL 保持现有受支持功能的真实默认入口、工具/能力装配、API 数据结构及异常语义。系统 MUST NOT 通过关闭题库/学习/阅读/调度/渠道、移除可选 E2EE、只挂载文本 chat、返回假空数据或移除测试来满足 PG-only 指标。资源文件与检索依赖 SHALL 遵守原已支持契约，PG-only 不等于把文件/图改存数据库。

#### Scenario: 默认应用使用非 chat 功能
- **WHEN** 已授权用户通过原页面/API/CLI/SDK 使用题库、学习、阅读或已配置渠道
- **THEN** 原业务可完成且所有原 SQLite 状态读写转为 PG，引用和用户可见结果保持正确

#### Scenario: 导入或查询仍需文件载荷
- **WHEN** 原功能依赖教材、附件或导出文件
- **THEN** 继续通过相应受控资源契约读取真实载荷，不以失效路径、占位内容或把 SQLite 文件存入 PG 替代业务迁移

### Requirement: 运行态零 SQLite 验收

所有受支持应用进程、后台、内置/可选渠道和受控子进程 MUST 不访问文件或内存 SQLite，包括第三方 SDK 间接存储和所谓临时缓存。SQLite 仅限独立离线导入源读取及旧格式测试 fixture；这些例外 MUST 不被业务运行路径调用。

#### Scenario: 全进程禁止 SQLite
- **WHEN** 从安装制品在禁止 SQLite 连接的隔离环境启动默认 Web/CLI/SDK/后台并执行完整业务矩阵
- **THEN** 所有纳入行为正常通过真实 PG，且无隐藏 SQLite/C-native/子进程访问或为测试改用另一业务后端

#### Scenario: 依赖新增隐式 SQLite
- **WHEN** 支持的渠道或 SDK 升级引入新的 SQLite 运行访问
- **THEN** 兼容验证失败并阻止发布，必须适配 PG 后重验，不能把该路径临时加入运行白名单
