## 决策

已应用 SQL 永不原地修改。先在应用入口加入事务内校验、副作用和并发栅栏，并以隔离 PG 对比原行为；只有对应代码与负例通过后，下一版本前向迁移才 `DROP TRIGGER`、`DROP FUNCTION`、`DROP CONSTRAINT`。迁移 runner 的 verify 必须断言目标 schema 无用户定义函数、业务触发器及枚举值约束，不能仅靠源文件 grep。任何未接管的旧规则不得先移除。

## 范围与顺序

1. Core：学习路径删除时解除 operation FK，阅读材料删除时清除 active 指针，会话删除时解除 ObjectStore 对象引用；同一事务完成。
2. Webhook：actor 候选从 pending 到终态一次性迁移，不可删除或复活；幂等重试与迟到事件按程序 CAS。
3. OMS：仅迁移已存在的学校绑定版本栅栏、attempt 证据和审计只追加等数据库规则。新建 Skill 包、来源/owner、审核、发布、授权、运行时及 OMS 界面属于 `add-enterprise-oms-business-logic`（学校侧属于 TMS change），不在本 change 新增产品功能；本 change 只检查已有写入口在旧规则退役后仍保持原拒绝语义。
4. 管理授权：角色/动作/assignment/delegation 范围与版本、最后管理员、主体 policy_version bump、审计追加由统一服务控制；撤权与在途写入同序锁定。现有 migration 模板数据的插入仍由受控迁移执行，不以数据库触发器给在线主体提权。
5. 所有 schema 的枚举值合法性改为应用层枚举/验证器，覆盖 API、CLI、SDK、后台、Webhook、迁移维护入口；注入或意外出现的未知值须拒绝，不自动解释为合法状态。首次部署不承担旧业务行的修复。

## 首次部署与值域校验

用户已明确当前 DeepTutor 系统视作首次部署，目标库数据可清空，故不再为旧业务行设计 `GROUP BY` 修复、导入或双兼容切换。保留既有迁移文件并追加集中清理迁移，空库按版本应用后验证最终 catalog；不改变 EduPlus2 外部仓库。程序对未来写入和异常持久化读取仍拒绝未知业务值，不能用“空库”取代应用校验。此处仅改变发布前提，不授权本 change 直接清空目标库、部署或操作其他团队资源。

## 发布安全

首次部署采用空 DeepTutor 数据库一次应用到最终版本，不运行旧应用双写或数据回填。发布前在隔离合成 PG 完整 apply/verify 与回归；目标环境只在明确部署授权和目标库边界后执行一次性清空、apply/verify 和切流。数据库超级用户直接改库不属于应用授权；运行时数据库凭据必须维持最低权限，不能把移除触发器当作赋权。

## Core RLS 与单库用户

test-cn 只读 catalog 检查确认运行连接是 Core 表 owner，且 Core 既有 RLS 未 `FORCE`；表 owner 可绕过普通 RLS。曾在未应用的 `0016` 合成尝试中对全部 Core tenant 表启用 `FORCE ROW LEVEL SECURITY`，但现有离线导入维护连接也采用同一 owner，至少三项导入测试因此无法写入 `maintenance_locks`；该尝试已撤回，不能发布。应用身份、权限与状态判断仍须由程序负责；RLS 只是隔离防线，不能把当前 owner 连接当成受限角色证明。定向负例另以独立非 owner 合成角色验收。若未来要强化 Core RLS，须先完成运行/维护连接职责分离，或将离线导入改造成逐学校/逐 owner 作用域的程序流程，再以单独前向迁移和完整回归实施。
