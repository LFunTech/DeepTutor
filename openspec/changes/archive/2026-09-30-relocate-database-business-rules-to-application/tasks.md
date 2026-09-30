> 2026-09-28 将原 8 项总任务拆成独立验收的叶子任务。历史函数、业务触发器、原生 ENUM、枚举型及按枚举分支的条件 CHECK 均须由程序接管，并以集中版本化清理迁移形成干净的最终 schema。用户已明确 DeepTutor 目标库可按首次部署清空；本 change 不做旧数据回填/双版本兼容，但在未获部署授权前不清库、不发布；不修改 EduPlus2 外部仓库。
>
> 当前盘点见 `synthetic-schema-inventory.md`：剩余 7 个用户函数、8 个触发器、当前 120 个 CHECK 候选（已补记阅读材料 ready/progress、单值 provider 和 OMS 绑定条件；最终数量仍需复核）。每个候选还须在 `constraint-disposition.md` 记录分类、程序入口、未知值策略、负例与退役结果。只有证据真实成立才勾选；4–6 的程序接管先于 7 的迁移，8 最后验收。

## 1. 清单与边界（原任务 1）

- [x] 1.1 盘点 Core、Webhook、OMS、Management 的函数、触发器、ENUM、枚举/条件 CHECK。
- [x] 1.2 建立相关表 Python 调用方与动态 SQL 封闭映射。
- [x] 1.3 对 test-cn 仅作 catalog/schema_history 只读盘点，记录 owner 绕过普通 RLS 的限制。
- [x] 1.4 固定首次部署空库边界、程序未知值拒绝策略和既有迁移保留规则。

## 2. Core 删除副作用（原任务 2）

- [x] 2.1 学习路径删除、阅读材料 active 指针清除移入同事务程序代码。
- [x] 2.2 会话删除及 ObjectStore 引用解绑移入同事务程序代码。
- [x] 2.3 回滚、跨 owner、受限非 owner 角色与离线导入定向回归通过。
- [x] 2.4 Core 前向迁移退役上述旧函数/触发器，保留历史 checksum。

## 3. Webhook actor 终态（原任务 3）

- [x] 3.1 pending→consumed/revoked 由应用 CAS/锁实现，拒绝删除、复活及非法终态。
- [x] 3.2 乱序、重投、并发首管理员激活与回滚负例通过。
- [x] 3.3 接收端前向迁移退役 actor 旧函数/触发器，runner 拒绝重新引入。

## 4. OMS 已有数据库规则的程序接管（原任务 4）

> 原 4.5–4.11 的 Skill 包、来源、审核、发布、授权和运行时功能归 `add-enterprise-oms-business-logic` / TMS change；此前实施与测试证据保留为历史记录，但不是本 change 的叶子任务或退役前置。这里不新建 OMS 产品写命令，只处理既有数据库触发器/约束及其真实写入口。

- [x] 4.1 Webhook 新绑定写入版本 1；已有绑定版本非法时投影 fail closed。
- [x] 4.2 OMS 迁移 runner 校验绑定不删除、物质变更加一和核验证据，恶意迁移回滚。
- [x] 4.3 封闭现有绑定写入口：Webhook 初始绑定保持版本 1；当前无可信在线撤权/改指向命令时程序拒绝该操作，不为退役触发器新建 OMS 产品功能；受控迁移逐版本校验物质变更和旧授权失效。将来新增 OMS 命令必须另按 OMS 提案接入版本 CAS 与可信依据；旧触发器物理退役归 7.4。
- [x] 4.4 attempt 证据/审计事实仅由在线应用追加，旧事实函数退役定向测试通过。
- [x] 4.12 绑定、证据、审计的并发、重放、回滚和非 owner/RLS 负例完整验收。

## 5. 管理授权程序权威（原任务 5）

- [x] 5.1 动作目录逐迁移校验应用前缀、范围、敏感性、版本和单向退役。
- [x] 5.2 角色目录逐迁移校验旧版本/动作不可改删或扩权，新版本仅关联有效且范围匹配的动作。
- [x] 5.3 自定义角色创建、版本发布、动作变更只经程序服务，覆盖敏感和退役动作负例。
- [x] 5.4 assignment 创建/调整跨全部写入口校验应用、主体学校、角色范围、有效期、绑定版本与并发。
- [x] 5.5 角色撤销应用锁保留最后平台/学校管理员，旧触发器禁用后互撤负例通过。
- [x] 5.6 主体停用应用锁保留最后管理员、推进版本并审计，旧触发器禁用后 OMS/TMS 并发负例通过。
- [x] 5.7 已实现授予、撤销、Webhook 首管理员激活由应用保证 policy_version 恰好加一。
- [x] 5.8 将 `validate_delegation_policy` 的主体学校、动作范围和有效状态校验迁到程序；当前没有 delegation 在线写入口，不为退役触发器新建产品命令。受控迁移逐版本核验，已有读取路径拒绝异常事实；将来创建/扩大/撤销命令由管理授权提案负责，并须先接程序校验与版本推进。旧函数/触发器的物理退役归 7.5。
- [x] 5.9 敏感授权、委托扩大、学校激活的双人审批覆盖独立身份、目标版本、有效期、幂等、拒绝/撤回和竞态。
- [x] 5.10 主体停用、assignment、delegation 与在途写入的锁顺序/撤权竞态组合负例。
- [x] 5.11 管理审计只追加、未知状态拒绝、运行角色低权及跨应用/跨学校 RLS 负例。
- [x] 5.12 管理 API、OMS/TMS 入口和受控 CLI 统一调用本产品权限服务，不信任 JWT role 或 URL/header 自报权限。

## 6. 全部候选 CHECK 的程序值域（原任务 6）

- [x] 6.1 逐项判定当前 120 个候选为枚举、条件枚举或纯物理，并登记表/列、入口、未知值、负例和迁移；最终 catalog 审阅继续补漏。
- [x] 6.2 Core 账号 role/preset 登录、已有 session、管理读取/变更及未知值负例。
- [x] 6.3 Core courses.status 读写未知值和离线导入 turn status 拒绝。
- [x] 6.4 Core cron schedule kind/形状、execution/last_status/完成时间程序校验。
- [x] 6.5 已覆盖的 executor、Partner 运行状态与 Matrix 信任状态程序校验/未知值负例。
- [x] 6.6 已覆盖的 session turn/message/operation 读写、摘要/活动列表/replay 状态校验。
- [x] 6.7 阅读材料、MarginNote、笔记来源/趋势及条件字段逐项校验。
- [x] 6.8 mastery topic/source/interaction/operation/lease 状态、kind 和条件形状逐项校验。
- [x] 6.9 resource object/retention/cleanup/session object/reference 状态、kind 和条件形状逐项校验。
- [x] 6.10 tenant lifecycle、runtime policy/settings/audit/secret、turn command 尚未覆盖值域与条件；已做治理切片不足以代替。
- [x] 6.11 会话域其它写入口及注入未知值的拒绝负例，含 CLI/SDK/WS/离线导入；不做旧业务行预检。
- [x] 6.12 EduPlus2 接收端 client/identity/profile/revocation/audit/export 值域、目标 kind 条件及未知值。
- [x] 6.13 Webhook inbox/target/actor/school projection 状态与 proof 条件、重投、乱序和撤权负例。
- [x] 6.14 OMS service/supply/entitlement/grant/command/attempt/evidence/audit/binding 值域和条件。
- [x] 6.15 Management principal/action/role/assignment/delegation/approval/audit 值域和条件。
- [x] 6.16 维护迁移、后台任务、离线导入契约；无在线写入口的表也证明只由受控迁移写入。
- [x] 6.17 API、CLI、SDK、HTTP/WS、后台、Webhook 真入口拒绝负例；候选约束逐对象均有证据。

## 7. 依赖 4–6 的集中前向迁移（原任务 7）

- [x] 7.1 空库集中迁移前后核对四套 schema 的对象清单、物理约束保留和目标库范围；不做可删除旧业务行的值分组/修复。
- [x] 7.2 Core 前向迁移移除剩余函数/触发器及经程序接管的枚举/条件 CHECK。
- [x] 7.3 EduPlus2 接收端前向迁移移除枚举/条件 CHECK，不改外部仓库。
- [x] 7.4 OMS 前向迁移移除绑定函数/触发器及枚举/条件 CHECK，保留物理完整性。
- [x] 7.5 Management 前向迁移移除授权函数/触发器及枚举/条件 CHECK，保留物理完整性。
- [x] 7.6 四套 runner 校验最终零目标对象、重新引入和 schema 漂移。
- [x] 7.7 既有 migration checksum 不变、集中清理迁移失败回滚、空库重复 apply 与 verify。

## 8. 隔离验收与发布条件（原任务 8）

- [x] 8.1 隔离合成 PG 四套迁移 apply→verify→repeat apply→verify；最终 catalog 零目标对象。
- [x] 8.2 注入函数、触发器、ENUM、枚举 CHECK、权限漂移和未知值，程序/runner fail closed。
- [x] 8.3 完整 Core、Enterprise、Webhook、OMS/TMS、离线导入及 API/CLI/SDK/WS 回归；本变更失败须修复。
- [x] 8.4 跨学校/跨应用、最后管理员、双人审批、撤权在途写、RLS/低权角色和审计安全审查。
- [x] 8.5 上游 mergeability 审阅及身份、HTTP/WS turn、session owner、审计关联 smoke。
- [x] 8.6 记录 DeepTutor 目标库专属边界、一次性清空/重建/切流的明确授权与回退方案；未经授权不清库或发布。
- [x] 8.7 对照全部叶子任务和最终约束矩阵复核证据、运行 OpenSpec strict validation；不自动归档或提交。
