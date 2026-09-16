# A1 首个子切片实施任务（已实施，隔离验证完成）

范围以 [proposal](proposal.md)、[design](design.md) 和四个 [specs](specs/) 为准。以下均属 **A1**，按包内真实行为顺序细分；不复制 A2/A3/B1/B2/C1/C2 的执行任务，H 保持总纲独立工作线。用户于 2026-09-13 明确批准执行本 proposal；34 项子任务现有实现和隔离验证证据，见 [执行证据](execution-evidence.md)。未合并/发布，不表示完整 A1/G1 完成。

每项实现遵循：先增加对应失败测试，再实现真实调用及适用 migration/权限/异常处理，实际验证后记录命令、结果和证据才勾选。模拟模型/故障可用于确定性测试，不能代替真实 PG 和真实模型入口验收。新增 scope/表/默认数据使用版本化迁移，纯 hook/文档任务注明无需数据迁移；全程不改用户现有 DB/集群或提交代码，除非另获授权。

## 1. A1：企业装配、可信身份与 PG 会话子切片

### 契约与依赖锁定

- [x] 1.1 固定本切片的 HTTP/WS/SDK/CLI 入口→服务→持久化/隐式文件调用清单；登记 core seam、企业实现及未交付依赖的拒绝行为，关联总纲 1.1/1.3/1.7 的剩余项，验证无隐式扩展为完整 A1 或删减 M1。
- [x] 1.2 在隔离环境验证并锁定 core/Python、PG driver/连接池和迁移工具版本：现有异步协议、同步边界、事务取消回滚、参数化 SQL、版本历史与互斥；交付可重跑兼容测试和依赖锁，不在业务 event loop 阻塞或嵌套 asyncio.run。
- [x] 1.3 定稿固定 tenant/user/会话 ID、可信 scope/cache key、auth session/version、operation ID/请求指纹和事件兼容契约，测试同名/同 ID 跨租户、整数 message ID 与原 HTTP/WS 数据格式；不空建检索/外部身份领域表。

### 企业包与应用 PG 基础

- [x] 1.4 建立独立可构建企业包和显式 bootstrap，声明 core 兼容范围；验证安装/导入及缺 hook/版本不符失败，core 不反向依赖企业包、默认 local 安装不需要 PG 依赖。
- [x] 1.5 实现连接池/事务执行边界和受限运行身份验证；使用真实 PG 测试同连接事务级 tenant/user 设置、复用、超时/取消回滚及缺 scope 拒绝，错误中不泄露 DSN/Secret。
- [x] 1.6 交付应用迁移历史/互斥/漂移检查及 plan/apply/verify 入口；真实 PG 验证重复/并发执行、失败中断和运行身份 DDL 拒绝；应用启动只验证 schema，不逐进程迁移。
- [x] 1.7 版本化创建 tenant/user/local credential/auth session 与最小审计约束，启用租户 RLS/复合归属；验证分源准入、缺 scope/跨 tenant 写入及直接 SQL 负例，不使用 owner/superuser/BYPASSRLS 运行。
- [x] 1.8 将 session/message/turn/event/operation 及会话版本约束纳入版本化迁移；验证跨 tenant、同 tenant 错 owner/session/parent 的关联拒绝、序号唯一与事务回滚，保留原消息 ID 和事件格式兼容。

### 固定租户身份闭环

- [x] 1.9 实现 PG 固定租户与首位 tenant_admin 的受控初始化入口，一次性 bootstrap Secret 不落库/日志；验证重复初始化、并发创建、同名提权/密码覆盖拒绝与原子审计。
- [x] 1.10 接通受保护账号运维命令的普通用户创建、密码更新、禁用/启用与 auth session 撤销；逐操作验证权限、幂等/冲突及身份版本，账号维护不赋予操作者他人会话读取权。
- [x] 1.11 接通企业本地认证 provider 与 `/api/auth` 对应登录/状态/退出契约，PG 凭证 hash、Secret 签名及认证会话持久化一致；验证普通用户正例和签名/issuer/audience/过期/旧 local token 负例。
- [x] 1.12 完成 cookie 属性、CSRF/Origin、WS Origin、登录失败限流与账号枚举防护；验证退出后原 bearer/cookie/WS 拒绝、禁用/密码变化实际失效，审计/响应无 token 或凭证。

### 通用装配与实际聊天依赖

- [x] 1.13 扩展通用 application factory/auth/provider/lifespan，企业显式选择本切片路由；验证无重复覆盖，未适配 auth/admin/Plugin/其他 WS 不可绕过，import/start/stop 不触发旧文件迁移或本地 Secret 初始化。
- [x] 1.14 将 StoreScope、runtime registry、ContextVar 和进程内事件/命令 namespace 接入 tenant+owner；真实交错 HTTP/WS 测试两测试租户/同租户双用户，不复用可变单例身份、不回退默认 scope。
- [x] 1.15 接入只读版本化部署配置、Secret 和模型/工具授权 provider，使实际文本 chat 可调用授权模型；验证普通用户及管理员均不能越过允许范围，不提供假保存接口、不写 settings/grants JSON、不取得检索密钥。
- [x] 1.16 改造文本 turn 的上下文/工具装配与隐式 notebook/附件/skill/persona/memory 依赖访问，保留内置只读 prompts 和 ask_user；未交付参数在写入/模型派发前明确拒绝，运行测试禁止读取或创建本地权威服务。
- [x] 1.17 接通 SDK 与受控企业 CLI 的 container/auth/scope，惰性获取尚未交付的 notebook 等服务；验证发起、读取、取消会话走 PG 与相同 owner guard，拒绝任意 tenant override，保留 local CLI/SDK 回归。

### PG 会话与真实入口

- [x] 1.18 实现 PG 创建/读取/列表/继续会话，接通原 HTTP/WS 主链路；真实 PG 验证分页、个人 owner、未知/他人 session ID 不被 ensure_session 接管及缺 scope 负例。
- [x] 1.19 实现消息/turn/event 追加、单调序号与最终消息/终态关联事务；验证并发批次、失败回滚和 PG 中断不发持久化成功信号，保留事件信封及 cost_summary。
- [x] 1.20 接通可选 operation ID 的 start 重试与请求指纹冲突，派发前原子持久化原请求/turn；公布保留期并保存删除标记，验证重复仅一次模型派发、中断不自动重跑/删除不复活、同 key 异内容冲突、无 key 旧客户端语义与重连已知 turn。
- [x] 1.21 接通历史/消息 trace、标题及摘要写读，保留 provider 私有 metadata 脱敏与显示截断；验证 HTTP/SDK、分页/游标、跨用户 message ID 拒绝和摘要 PG 故障。
- [x] 1.22 接通会话自身偏好、置顶/归档、合法父子会话/分支选择，替换相关直连 SQLite；验证并发版本冲突、跨 owner/session 引用拒绝，课程/学习关联明确待后续且不访问原文件服务。
- [x] 1.23 接通 regenerate/edit branch 的原父子消息语义与上下文选择；真实 PG/WS 验证旧分支保留、最终消息不重复、错误 owner/非法父节点及 PG 提交失败。
- [x] 1.24 接通订阅/resume_from/事件重放与 check_active_turn，覆盖 HTTP/WS/SDK 当前身份重验；验证同 tenant 他人/管理员订阅拒绝、身份撤销后不能继续读取事件、游标顺序和无事件丢失。
- [x] 1.25 接通原 ask_user waiting→submit_user_reply→继续执行，持久化交互状态；验证断线后原进程仍可回复、非 waiting/重复/错误 owner 回复拒绝，真实模型 smoke 覆盖交互而非另建演示 capability。
- [x] 1.26 接通 cancel 与完成/回复竞争状态转换；验证重复取消幂等、只有一个终态、最终消息与用量一致，以及失效 token/他人 turn 无控制权。
- [x] 1.27 接通无外部依赖的会话/消息删除，明确运行停止、与新 turn 原子互斥及消息冲突语义；验证无残余可读历史/事件、最小审计、外部资源依赖前置拒绝且原记录不变，移除本切片 LearningStore/附件清理旁路而不吞错。

### 单执行运行与切片验收

- [x] 1.28 以受限 PG 执行登记/锁和配置预检约束单执行者；验证第二进程拒绝、DB/执行权丢失停止派发和提交，旧进程未确认停止不自动接管，不将锁测试冒充 G-H。
- [x] 1.29 将后台账号/非终态 turn 枚举和恢复接入 PG 受控 scope，完成排空、停止/超时清理及中断终态；验证重启后 running/waiting 不无限挂起、旧回复不进入新 turn、无自动模型重跑。
- [x] 1.30 使用两个测试租户、各自普通用户及同租户双用户/管理员，验证全部已纳入 HTTP/WS/SDK/CLI 的正负向矩阵；覆盖假 tenant、相同 ID、owner、连接池及缓存复用，记录 401/403/404 和冲突结果。
- [x] 1.31 执行全进程无本地权威路径验证：import→bootstrap→登录→chat/标题/摘要→history/branch/reply/cancel/delete→stop/restart；结合静态扫描和运行期禁止写入验证本切片无 SQLite/JSON/默认容器旁路，并输出后续领域未适配清单。
- [x] 1.32 在隔离环境执行真实模型文本聊天/继续/regenerate/ask_user 的 HTTP/WS/SDK smoke，归档脱敏 PG 状态/事件/真实用量与预算证据；无模型凭证或 PG 时保持本项未完成，不用模拟测试代替。
- [x] 1.33 实现并演练本切片 PG 失败、全新 scratch/进程重建及隔离 PG 备份恢复；恢复时关闭登录/执行、撤销旧认证会话并更新不随快照回退的认证世代，核对/重置或保持账号禁用。验证“备份→退出/禁用/改密→恢复”旧凭证仍拒绝及历史/事件引用、中断语义，记录实测值/schema 回退范围，不宣称完整 RPO/RTO 或 PG/S3/检索成套恢复通过。
- [x] 1.34 运行受影响 core/local 回归、企业 PG 契约/入口测试及适用 lint/格式/架构检查，审查最终 diff 与覆盖矩阵；更新相应 OpenSpec 证据和总纲映射，strict validation 通过后仅申请子切片验收，不勾选剩余 A1/G1。

## 2. 后续工作包与 H 的交接（不在本 change 勾选）

本子切片只归 A1。剩余 A1 另立配置/授权、个人内容与学习状态、资源元数据/检索契约及全量审计/验收 proposal；参见 [总纲映射](design.md#总纲映射与剩余责任)。A2 消费后续稳定的 object/KB/binding 契约，本次不承诺这些接口全部定稿。

A3 的 3.1–3.4、B1 的 4.1 和 H 的 8.1/8.2 按[总纲任务](../replace-rollout-with-three-production-stages/tasks.md)从 A1 起并行准备，本切片提供企业包/配置/迁移/测试接口，但不代替 CI/K8s、外部契约或全系统可用性验收。H 的 8.3–8.6 在多执行者前另行完成；单执行实现不能将这些任务勾选。

## 3. 验证入口与证据要求

本切片测试实现后，使用企业包的独立测试入口执行真实 PG/auth/HTTP/WS/SDK 契约。现有回归重点包括 `tests/services/session/`、`tests/api/test_unified_ws_turn_runtime.py`、`tests/api/test_sessions_trace.py`、`tests/api/test_auth_contextvar.py`、`tests/api/test_auth_logout_cookie.py`、`tests/multi_user/`、`tests/app/`、`tests/cli/` 和 runtime/coordinator 测试；受核心 seam 影响的其余测试同样不能略过。具体测试文件随真实实现新增，不能将路径草案视为已有可运行测试。

完成证据至少记录：core/企业包/依赖与 schema 版本、测试 PG 角色、已纳入入口与负例、运行模式、实际命令/结果、模型 smoke 预算/用量、无本地写路径检查及仍未交付领域。总纲原项仅在完整范围均有证据时更新，不能凭 OpenSpec planning complete 推断业务完成。
