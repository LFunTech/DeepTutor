# application-owned-database-rules Specification

## Purpose
确保 DeepTutor 的业务状态与权限决策仅由程序逻辑管理，数据库只承担持久化和非业务性的隔离/结构约束，同时在移除历史数据库程序逻辑后维持现有安全语义。

## Requirements

### Requirement: 数据库不得拥有业务过程或枚举值目录

DeepTutor 已迁移后的 schema SHALL 不包含用户定义数据库函数、存储过程、应用定义的业务触发器、PostgreSQL ENUM 类型、枚举值 `CHECK ... IN/ANY` 约束或按枚举业务状态分支的条件 `CHECK` 约束。程序 SHALL 在所有受支持写入路径验证业务值、状态迁移、权限和跨表一致性；RLS、主外键、唯一性及非枚举物理约束仍可保留。

#### Scenario: 非法状态请求
- **WHEN** API、CLI、SDK、后台或 Webhook 提交非法状态/来源/类型
- **THEN** 程序在事务提交前拒绝，数据库中无部分业务状态或审计成功记录

### Requirement: 前向退役保持原有安全语义

已应用迁移 MUST 保持原始 checksum；任何旧数据库函数、触发器或枚举约束只可由新的版本化迁移退役。首次部署从空 DeepTutor 数据库应用至最终版本，不要求旧数据修复、旧应用双版本兼容或线上数据切换。删除清理、不可变事实、最后管理员、撤权版本与主体 policy_version 的行为 SHALL 在应用层同事务实现并经并发、幂等、回退负例验证；未接管前不得删除旧保护。

#### Scenario: 最后管理员被并发撤权
- **WHEN** 两个合法操作者同时撤销同一范围内仅剩的管理员能力
- **THEN** 事务串行后至少保留一名有效管理员，或两笔都安全拒绝；不依赖触发器
