## Purpose

规定 DeepTutor 生产环境中文件类持久资源的外置存储契约，将附件、知识库原文、阅读材料、workspace outputs、动态 skills/personas 和导出物从 Pod 本地 `data/` 迁移到 S3-compatible ObjectStore，并由 PostgreSQL 保存元数据与授权边界。

## ADDED Requirements

### Requirement: 持久文件资源必须使用 ObjectStore 与 PG 元数据

系统在 production mode 下 SHALL 将需跨 Pod 保留的文件资源写入 S3-compatible ObjectStore，并在 PostgreSQL 中保存 tenant、owner、resource kind、object key、content hash、size、mime type、version、retention、状态和授权引用。PG 元数据 MUST 是资源可见性和生命周期的权威，ObjectStore key 或本地路径不得单独授予访问权。

#### Scenario: 创建附件资源
- **WHEN** 用户上传聊天附件或生成需要保留的输出文件
- **THEN** 后端生成不可猜测 object key，完成授权和配额检查后写入 ObjectStore，并只有在 PG 元数据提交为 ready 后才向用户返回可用引用

#### Scenario: 仅有对象 key 无 PG 元数据
- **WHEN** 请求尝试通过已知 bucket/key 或旧本地路径读取对象，但没有匹配的已授权 PG 元数据
- **THEN** 系统拒绝访问，不能因对象存在、路径可读或调用者是管理员而绕过资源授权

### Requirement: 上传、提交和删除必须具备补偿语义

系统 SHALL 对文件资源使用可恢复的状态机，例如 pending/reserved/uploaded/ready/delete-pending/deleted/failed。PG 状态与 ObjectStore 写删之间没有跨系统事务时，系统 MUST 记录可重试补偿任务并避免向用户暴露部分提交成功。

#### Scenario: 上传成功但 PG 提交失败
- **WHEN** ObjectStore 已写入对象但 PG ready 提交失败或连接中断
- **THEN** 用户不可见该资源，系统记录待清理对象或 pending 状态，后台补偿可安全重试且不删除其他租户对象

#### Scenario: 删除引用资源
- **WHEN** 用户删除会话、阅读材料、workspace output、persona 或 skill 包引用的对象
- **THEN** 系统按资源生命周期更新 PG 元数据并异步/同步清理 ObjectStore；删除失败必须可查询和重试，不能留下可绕过权限读取的悬空对象

### Requirement: ObjectStore 凭证和预签名 URL 必须受控

系统 MUST 不向浏览器、普通 CLI、SDK 响应、日志或 settings 文件暴露长期 ObjectStore 凭证。需要直传或下载时，后端 SHALL 在完成应用授权后生成短 TTL presigned URL，且 object key 必须由后端控制。

#### Scenario: 生成下载 URL
- **WHEN** 已授权用户请求下载附件或 workspace output
- **THEN** 后端先校验 PG 元数据和 owner/grant，再返回短 TTL URL 或代理内容；响应不包含 access key、secret key 或可枚举 bucket 权限

#### Scenario: 客户端提交任意 object key
- **WHEN** 客户端请求把资源保存到自定义 bucket/key 或跨 tenant prefix
- **THEN** 系统拒绝该请求或忽略客户端 key，使用后端生成的 key 与当前 tenant/owner 元数据

### Requirement: 旧 data 文件迁移必须显式清单化

系统 SHALL 提供本地 `data/` 中文件资源的只读 inventory、plan、import、verify/report 流程。迁移 MUST 记录源路径、hash、目标 object key、owner/tenant 映射、引用重写和失败项；未知归属、缺文件、hash 漂移或路径逃逸 MUST 阻断受影响批次。

#### Scenario: 规划 data 文件迁移
- **WHEN** 操作者对旧 `data/user/workspace`、`data/knowledge_bases`、`data/postgres-resources` 或 notebook/persona/skill 文件执行迁移 plan
- **THEN** 系统输出每类资源的目标 provider、owner 映射、对象数量、大小、冲突和不可迁移项，不修改源文件或生产 PG

#### Scenario: 迁移后验证引用
- **WHEN** 文件资源已导入 ObjectStore 并写入 PG 元数据
- **THEN** verify/report 检查所有业务引用能通过授权路径读取目标对象，且旧本地路径不再作为生产读取来源

### Requirement: 外部连接知识库必须显式只读

系统 SHALL 区分 DeepTutor 托管的可写知识库与指向外部资源的连接型知识库。`lightrag_server`、WeKnora、Obsidian、linked folder 等外部连接 KB 的原文、索引或派生状态不由 DeepTutor 本地 `data/knowledge_bases` 管理；列表/API/UI MUST 显示其为只读，并阻止本地上传、建文件夹、移动、删除本地文件和 reindex 操作。

#### Scenario: 外部 LightRAG Server KB 不开放本地上传
- **WHEN** 用户连接一个 `lightrag_server` KB，并打开知识库详情或通过旧/新前端发起本地文件上传、建文件夹或 reindex
- **THEN** 列表 API 返回 `read_only=true`，前端不得提供可写入口；若旧客户端仍调用写 API，后端返回 409 且不创建 `data/knowledge_bases/<name>` 本地存储目录

#### Scenario: 内置 LightRAG KB 才是可写托管 KB
- **WHEN** 用户需要在 DeepTutor 内上传原文并建立索引
- **THEN** 应创建 `rag_provider=lightrag` 的托管 KB；其原文/业务 metadata 按 ObjectStore + PG 契约管理，外部 `lightrag-server` 连接只作为远端检索指针保留
