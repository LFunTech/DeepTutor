## Why

用户明确要求数据库不保留用户定义函数、存储过程、触发器业务逻辑，也不使用 PostgreSQL ENUM、`CHECK ... IN/ANY` 枚举约束或以条件表达式编码枚举业务状态的 `CHECK`。当前已应用的 core、Webhook、OMS、管理授权迁移含这些机制；直接删掉会破坏删除清理、最后管理员保护、撤权版本与状态合法性，必须在应用事务接管后以前向迁移退役。

## What Changes

- 在 `AGENTS.md` 固定程序逻辑唯一权威与不可改写已应用迁移的规则。
- 保持现有业务行为与拒绝语义，逐个把 14 个历史用户定义数据库函数、18 个触发器及所有枚举型数据库约束的校验/副作用转移到 Python 应用代码。
- 在同一仓库的 core、EduPlus2 接收端、OMS、管理授权 schema 中追加前向 SQL 迁移，删除旧函数/触发器/枚举约束；不触碰 EduPlus2 外部仓库或真实学校数据。
- **首次部署数据库治理**：目标 DeepTutor 数据库可清空重建；本 change 不承担旧应用/旧数据双兼容或历史业务数据修复。仍以本仓库版本化集中清理迁移产出无数据库业务函数与枚举约束的最终 schema；未获发布授权前不执行清库或切换。

## Capabilities

### New Capabilities

- `application-owned-database-rules`: 程序层拥有业务校验与状态副作用，数据库仅保留物理结构、非枚举约束和 RLS 隔离。

### Modified Capabilities

- 无；对外业务语义保持不变。

## Impact

`deeptutor/persistence/postgres/`、`extensions/enterprise/src/deeptutor_enterprise/{eduplus2,oms,management,migrations}/`、对应隔离 PG 测试与版本化迁移；不修改发送端仓库，不发布或操作真实学校数据。
