## Context

动机及用户确认的子切片范围见 [proposal](proposal.md)。本设计基于 2026-09-13 工作区（core HEAD `b96589df`），不是功能已完成声明；已有企业文档和总纲的未提交修改作为输入保留。

### 已核查的真实缺口

| 代码位置 | 现状 | 本切片的处理边界 |
| --- | --- | --- |
| `services/session/__init__.py` | PocketBase 或默认 SQLite，无企业 provider | 注入显式 Store，企业失败不走原默认分支 |
| `services/session/protocol.py` | 已有异步 Session/Turn/Message repository，但未覆盖会话路由全部方法 | 补会话分支、消息删除等实际协议；不把题库全部方法塞进 SessionStore |
| `services/session/scope.py`、`app/container.py` | StoreScope 无 tenant；runtime/recovery 以 cache key 索引，并枚举本地账号 | 显式 tenant/owner scope；PG 账号/非终态记录枚举，不按路径推断身份 |
| `services/auth.py`、`multi_user/identity.py` | 模块级配置/Secret 初始化、本地用户 JSON | 企业 auth provider 在副作用前装配，身份持久化 PG、签名密钥由 Secret 注入 |
| `multi_user/{models,context,paths}.py` | admin/user + Path scope，部分缺省返回 local admin | 保留 local 兼容，企业 scope 缺失拒绝且不触发目录创建/迁移 |
| `api/main.py` | 模块级 FastAPI/router 装配及本地迁移 lifespan | 提供通用 factory/lifespan seam；显式路由清单，避免导入默认 app 后再覆盖 |
| `api/routers/sessions.py` | 分支/删除消息/quiz 直连 SQLite；删除还调用 LearningStore/附件清理 | 迁移纯会话操作；quiz/课程关联留后续，资源依赖不能吞错后假报删除成功 |
| `app/facade.py` | SDK 构造时即创建 notebook manager | 改为按已装配服务获取/惰性初始化；企业 SDK 的会话不触发文件 notebook |
| `services/session/turns/{request_preparer,executor}.py` | 文本 turn 也读 settings/model/grants、skills/personas，涉及 notebook/附件 | 按显式 provider 和依赖清单装配，不能只改 turn_runtime facade |
| `agents/_shared/tool_composition.py` | 自动挂载探测直接查询 SQLite/本地学习与 notebook | 以已安装资源能力参与装配；缺依赖是明确不可用，不靠异常返回 False 掩盖旧写路径 |

其余直连已定位于 question_notebook、imports、book、question/history、question_bank、learning、reading、cron、partners 和 memory/snapshot；登记到后续 A1/A2，不在本次声称全部收敛。

## Goals / Non-Goals

**设计目标**：一个最终架构内可独立验收的纵向切片，不是一个独立临时产品；从已认证文本请求到 PG 持久事件和重连控制均使用真实 core 路径。

**实现边界**：复用会话服务/编排而非复制 HTTP/WS；新增企业基础设施实现位于包外。只读启动配置是最终部署配置入口，不是临时 SettingsStore；所有用户可编辑配置仍等后续 PG 服务，不提供写后丢失或假成功接口。

**发布边界**：仅在隔离集成环境验收本切片。服务健康与“完整企业产品可发布”分别表达；未经后续 A1+A2+A3/G1，不能向普通生产流量开放，也不新增一个过渡生产 profile。

## Decisions

### 1. 选择完整身份—会话切片，不做空底座，也不展开整个 A1

- **采用**：企业组合根、PG/RLS、受保护本地身份和文本会话一起交付；开发内部按 tasks 分段验证。
- **不采用纯协议/DDL proposal**：无法发现真实 auth/WS/SDK/启动副作用和所有权问题。
- **不采用完整 A1 proposal**：用户明确选择更小变更，配置、个人内容和检索元数据有独立闭环，留后续提案。

### 2. 显式依赖装配，原生 local 模式单独保留

实现目录（已新增，不要求每个目录成为独立进程）：

```text
extensions/enterprise/
  pyproject.toml
  src/deeptutor_enterprise/
    bootstrap.py
    api/application.py
    identity/                 # 身份、账号运维、认证及授权适配
    stores/postgres/          # 连接、事务、Identity/Session/最小 Audit Store
    migrations/               # 仅应用 PG schema/默认数据
  tests/                      # 契约、真实 PG、入口及隔离测试
```

core 提供通用 application factory、auth/provider 和生命周期 seam；不 import 企业包。企业组合根在原路由/服务产生文件副作用之前完成装配。实例生命周期负责连接池 start/close、runtime 排空；schema migration 不在 app lifespan 执行。不得依赖路由先后顺序覆盖同路径、全站 monkey patch 或请求内环境切换。

企业进程明确声明已支持的入口、能力和依赖。已纳入的必需 provider 缺失使启动失败；未纳入的功能请求在持久化和模型调用之前拒绝。旧 `/admin`、未适配 auth/user-management、Plugin API、其他 WS 不因共用模块自动暴露。完整 `/tms` 路由组合仍归后续；本切片不建管理页面或旧 URL 重定向。

### 3. 文本聊天所需配置不扩成完整配置/授权管理

复用最终配置/模型授权 provider seam，读取运维受控、版本化、只读的非敏感部署描述及 Secret 引用。描述显式给出固定 tenant、聊天模型/profile、允许的普通用户/模型范围、文本 `chat` 和 `ask_user` 交互工具范围；不是硬编码一个测试用户、假模型或隐式“所有人允许所有模型”。后续 PG Settings/Grant provider 在同一边界接入。

- 所有普通用户和管理员经过相同模型/工具允许范围检查，不给管理员全局 bypass。
- 本切片不提供模型目录、grants 或可变 settings 的管理写接口；企图写入明确不可用，而不是写临时文件。
- 聊天模型调用使用实际 LLM provider，保持真实 usage/cost 信封。模型 Secret 只在执行者内存解析；无检索模型密钥或检索 profile 修改接口。
- 工具装配、persona/skill/notebook/memory/attachment 上下文只在已安装相应资源 provider 时访问。内置只读 prompts 可随镜像使用；动态资源、RAG、文件生成和高风险工具在本切片无入口。显式请求这些功能必须返回明确错误，不静默忽略参数继续跑文本聊天。
- 完整性扫描覆盖 import、启动、一次 turn、标题/摘要生成、历史和停止恢复；不因没有传附件就允许无条件创建本地 AttachmentStore。

### 4. scope 显式化，连接池不持有可变的当前租户

新增通用可信 scope 字段，不把 `UserScope.root` 改成 S3 URL，也不增加 `data/tenants`。企业执行上下文至少包含内部 tenant/user、认证会话/身份版本和 request ID；资源 scope 包含 tenant + owner + session/turn。

`StoreScope` 和 runtime/cache/coordinator namespace 使用无凭证的后端资源标识 + tenant + owner。共享连接池可复用，scoped Store/请求上下文必须不可变；不得在单例 Store 上赋值“当前 tenant”。ContextVar 在 HTTP/WS 处理结束后恢复；异步任务显式捕获可信上下文，后台从 PG 记录重建并重验。来自客户端 metadata/header/query 的 tenant/user 不得覆盖它。

PG 每次显式事务在同一连接设置事务局部 tenant/user 上下文，异常与取消也确保回滚/归还；不使用 session 级租户设置。租户表 ENABLE/FORCE RLS，覆盖 SELECT/INSERT/UPDATE/DELETE；应用角色不是 owner/superuser/BYPASSRLS。前台正常数据读取还必须限定 owner，RLS 不是同租户个人授权。

身份登录尚无用户时，只能在可信固定 tenant 内通过专用身份 repository 查询凭证；这不授予普通会话 Store 一个“无 owner 可查所有数据”的分支。恢复/账号维护使用用途受限、可审计的系统操作，普通请求不能构造该身份。

### 5. 先迁移应用 PG，保留后续身份和资源的稳定边界

| 数据领域 | 本切片契约 |
| --- | --- |
| tenants | 内部 UUID；外部 tid 可空；external_eligibility/local_enabled/provisioning_status 及独立版本、policy_version；effective_access 派生 |
| users/local_credentials | 稳定不透明 user ID；tenant 内用户名唯一；凭证 hash 与公开资料分离；disabled/auth_version；已有 ID 不按用户名重算 |
| auth_sessions | tenant/user、不可猜测会话标识、到期/撤销/身份版本；PG 不保存明文 token |
| sessions | tenant/session/owner 复合归属，标题、摘要、偏好和版本；个人内容不自动共享 |
| messages | tenant/message、session/owner 归属、parent 引用、原协议 metadata；保留现有整型 message ID 的会话 API 兼容 |
| turns/events | turn→session/owner 复合约束；事件 `(tenant_id, turn_id, seq)` 唯一；终态与最终消息关联原子提交 |
| operation records | tenant/user/client operation ID、请求指纹、结果引用；重放幂等及不同内容冲突 |
| identity/session audit | 仅本切片的账号维护、身份失效、会话删除与拒绝事件；actor/target/request/result，禁止密码/token/正文 |

关系约束不能只检查两个对象“在同租户”，还要验证 parent_message、parent_session 和 message/turn 属于相同合法 owner/session。消息序号在事务内原子分配；不能无锁 `max(seq)+1`。初始只建本切片真实使用的表，不提前空建 KB/图/webhook/grants 全模型。

M1 的 `not_required` 只能由固定单租户部署初始化；本地暂停和资源未就绪仍拒绝。初始 `ready` 只表示本切片明确需要的身份/会话基础资源已初始化，不是完整 M1 已发布；后续扩展租户初始化契约时重新检查必要资源。B1 接入外部身份必须显式迁移，不携带 not_required 旁路。

PG driver/迁移工具的具体发行版本在任务 1.2 的兼容试验后锁定：必须满足现有异步 session 协议、同步调用的显式边界、连接池取消回滚、参数化 SQL、版本历史/互斥/漂移拒绝。工具选择不改变上述 schema/事务或任务分工；不照搬其他 Java 仓库的目录、注解或启动修库。只有通过试验的依赖进入企业包，不改变 core 默认安装依赖。禁止在活动事件循环中嵌套 `asyncio.run()`，阻塞 DB 操作不直接运行于异步请求；同步配置读取使用不可变部署快照，不能每次同步查 PG。

### 6. 本地认证是 M1 最终路径的一部分，不是临时身份网关

通过受控运维命令（确切命令在实现时随 CLI 测试固化）交付固定租户初始化、首位 tenant_admin、普通用户创建、密码更新、禁用/启用与会话撤销。首位管理员初始化使用一次性 bootstrap Secret，幂等且不能在重启时覆盖密码或提升同名用户；新增/变化默认状态走版本化迁移或受控事务，不依赖手工改库。

保留 bcrypt 验证兼容性；新 token 使用稳定内部 user/tenant、auth session ID、issuer/audience、iat/exp 与身份版本。旧 local token 不因签名碰巧有效而被企业入口接受。每个敏感请求、新 turn、订阅/重放及 cancel/reply 验证当前身份/租户有效性和资源所有权；WS 不只握手检查一次。退出撤销当前 auth session，账号停用/密码更改推进身份版本并拒绝旧会话；不承诺撤回已经返回的内容。

登录/状态/退出沿用对应 `/api/auth/*` 产品路径；写请求 cookie/Origin 与 CSRF 防护、WS Origin 校验、登录失败限流及日志脱敏纳入本切片。匿名 status 只暴露登录所需信息，不回传用户目录或 Secret。学校/外部身份映射、设备凭证和应急平台角色留后续，企业入口不自动开放旧实现。

### 7. 会话全链路，但只接通不依赖未交付领域的操作

| 已纳入行为 | 真实接入与约束 |
| --- | --- |
| 新建/继续文本聊天 | 原 WS → TurnApplicationService/TurnRuntimeManager → ChatOrchestrator → 已装配真实模型 → PG events/messages |
| 历史与 trace | `/api/sessions` 列表/详情/分页/消息事件；保持原 provider 私有 metadata 脱敏和 trace 截断，不影响模型上下文 |
| 会话编辑 | 标题、会话自身摘要/偏好、置顶/归档、合法 parent/branch；跨用户/跨会话引用拒绝 |
| regenerate/edit branch | 使用原父子消息语义与最后用户消息，不重排历史、不重复最终消息 |
| ask_user/reply/cancel | 保留原 WS 命令；reply 只作用 waiting turn，cancel 与完成竞争仅一个合法终态，重复命令幂等 |
| 重放/重连 | 已提交事件按 seq 游标重放，先查身份/owner；不能把另一用户的 turn 通过订阅暴露 |
| 删除 | 无外部资源的会话/消息完整删除；运行中消息按原冲突规则拒绝，会话删除先确认取消/停止再提交 |
| SDK/CLI | SDK/受控企业 CLI 同一 container/auth/scope；普通调用不接受任意 tenant override，不误建 notebook；local CLI 行为不变 |

兼容客户端未提供 operation ID 时沿用一次请求语义；新客户端可用可选 operation ID 进行同一请求重试，服务端以 tenant/user/op 及请求指纹查结果。原请求登记与 turn 创建在派发模型前原子提交；相同 key 不同内容返回冲突，中断后的同 key 只返回原中断状态，不重新执行模型，用户显式重试/regenerate 创建新操作。会话删除事务同时将幂等记录转换为无正文、无悬空结果引用的删除标记，保留至已配置保留期，旧 key 不重新创建已删除会话；不承诺超出已公布保留期的去重。未带 key 的请求不承诺跨断线重复提交可去重。对于未知/他人的 session ID，不能通过 ensure_session 将其接管为本人新会话。

课程绑定、quiz 结果生成/题库联动、带附件或学习依赖的删除属于后续领域。含未适配依赖的请求/既有记录必须返回明确“依赖未接通/冲突”，保持原记录，不先删 PG 再吞掉 LearningStore/对象清理错误。无外部依赖的删除与新 turn 派发通过会话行锁/删除状态和版本检查互斥：先阻断新派发、确认停止，再提交删除；失败保留可解释状态，不让检查后新启动的 turn 写回已删除资源。本切片既不伪造外部资源清理，也不提前建设 S3 outbox；后续引入文件的 proposal 必须同时接通删除补偿再开放文件功能。

### 8. 单执行语义与故障边界

复用已有 coordinator/recovery，而不宣称它已满足企业 G-H。集成配置限制一个实际执行进程；维护先排空再停旧启新。使用用途受限的 PG 排他执行登记/锁和进程配置预检拒绝第二个企业执行者；锁/DB 连通丢失停止新派发、在权限/持久化边界停止提交并保留不确定状态。故障后新进程只有确认旧执行者停止才进入恢复；不以租约超时推断外部模型调用或进程必然结束。

start/stop、cancel、waiting、失败和终态均持久化。进程重启后历史和已提交事件可读；旧 running/waiting 且无法恢复内存执行状态的 turn 以明确可重试中断终态结束，用户可重新发起或 regenerate，不自动重跑模型/工具。旧 ask_user 回复不得误送给新 turn。

本切片不实现跨 Pod fanout/自动接管/HA；如果实施验收要求这些行为，应先按 H 另立对应工作，不能把此限制解释为已通过 G-H。单执行锁也不是网络分区下分布式执行正确性证明。

## 权限与真实入口矩阵

| 入口 | 后端要求 | 默认主体 | 验证 |
| --- | --- | --- | --- |
| 登录及匿名状态 | 固定 tenant、凭证验证/限流；状态最小公开 | 匿名只能登录/查看最小状态 | 错误凭证、禁用、未知 tenant、枚举泄露负例 |
| 退出/认证状态 | 有效 auth session；cookie 写入 Origin/CSRF | 当前用户 | 退出重放旧 token、过期/撤销 WS |
| session HTTP/WS/SDK/CLI | 成员有效 + tenant + owner + 具体操作 | user、tenant_admin 仅自己的会话 | 同租户他人/跨租户/管理员均拒绝 |
| 模型/工具执行 | 部署配置授权交集 + 已装配能力 | 受授权本地用户 | 参数伪造、动态资源/未授权模型拒绝 |
| 账号初始化/维护命令 | 运维执行身份/一次性 bootstrap 或受保护维护凭证 + 固定 tenant + 审计 | 经授权部署维护者 | 重复初始化、未授权提权、凭证泄露负例 |
| TMS/OMS、旧管理/其他入口 | 不纳入路由注册，禁止回落原本地服务 | 本切片无人获此入口 | 直调、旧深链接及插件/其他 WS 旁路负例 |

本切片不新增 `tenant.*` / `ops.*` 管理能力或外部 OpenFGA/Keycloak 状态；会话 owner 约束不是引入个人共享。管理导航不假称已具备，完整两级管理仍以总纲为准。

## Migration Plan

1. 仅针对隔离应用 PG 提供版本化 schema/角色和固定租户初始化制品，执行 plan/apply/verify、重复执行、漂移和失败恢复；运行服务只检查版本，不自动迁移。默认本地数据库、现有 HugeGraph/集群保持不动。
2. 本次不导入真实存量。若发现需要保存的旧数据，先记录归属、ID/格式与备份要求交接后续导入 proposal；不得自动扫描 `data/` 并迁入、按用户名合并或重写 ID。
3. schema 有新写入后仅允许兼容当前 schema 的应用回退，不能回退 SQLite。隔离 PG 备份恢复验证本切片账号/历史/事件引用与权限；完整 PG/S3/检索成套恢复仍由 A2/A3 验收。**数据库恢复不是单纯重启**：恢复全过程关闭普通登录/执行，只开放受控维护入口；恢复后先撤销快照内全部 auth session，并更换由 Secret 管理、不会随该 PG 快照回退的认证恢复世代。账号和租户默认保持禁用；核对恢复点之后的停用/密码变更等身份记录，只有获得受控确认并完成必要密码重置的账号才重新启用，无法核实的状态继续拒绝。不能使用旧快照 enabled/hash 推断当前授权，更不能仅换 token 签名就让旧密码重新登录。该规则只适用于受控数据库恢复，不要求普通进程重启重置密码。
4. 后续切片复用本包、scope 和迁移历史。扩展迁移保留兼容窗口，合并前重跑本切片 PG/权限/入口回归；不创建第二套 tenant ID 或另一条企业生产存储。

**迁移判断**：后续实施需要 DeepTutor 应用 DB schema/default-data migration；本轮未执行。OpenFGA/Keycloak 均不需要本切片迁移；检索 PG/HugeGraph/S3 状态不在本次写权限范围。

## 总纲映射与剩余责任

| 总纲任务 | 本切片承担 | 本切片完成后仍不能推定完成的范围 |
| --- | --- | --- |
| 1.1 | 文本身份/会话入口、旁路和单执行限制清单 | 全部 M1 能力/高级能力、真实存量、图隔离与全量容量确认 |
| 1.2 | 保留路线/证据缺口，不承担检索评测 | 真实教材、fork 制品、HugeGraph/质量/成本及恢复目标全部仍待完成 |
| 1.3 | 内部 tenant/user/session scope 和核心 Store 接口 | KB/index-version、binding/manifest/profile/实例池与六类交接全契约 |
| 1.4–1.6 | 连接/迁移/身份及会话 PG 主要实现 | 按总纲原验收逐项核对；基础设施扩展仍需后续领域验证 |
| 1.7 | 文本会话 history/trace/branch/regenerate/reply/cancel、SDK 和单执行恢复 | 题库/学习/导入/文件依赖与全量后台旁路 |
| 1.8–1.12 | 仅提供必要 seam，不承诺领域已实现 | settings、目录/grants、memory/notebook、资源 metadata 完整闭环 |
| 1.13 | 本切片身份/会话操作审计及验收 | 全部管理/资源审计及 A1 汇总验收 |
| 3.1–3.4、4.1、8.1/8.2 | 输出包/配置/测试命令、scope 与运行限制供并行准备 | CI/K8s/外部接入及 H 全系统目标/可靠性由总纲继续跟踪 |

后续 A1 按依赖规划：① settings/模型 Secret/Grant 管理；② memory/notebook 与已确认的题库/学习/阅读状态；③ KB/动态资源 metadata、LightRAG 服务契约/真实教材与预算；④ A1 全调用/审计汇总。③中的 ID/服务契约应尽早与①②并行明确，使 A2 不必等所有 A1 代码结束才设计；检索实测需要固定制品和授权资源，不能用本次 PG 验收代替。

总纲 90 项编号/checkbox 保留。本 change tasks 是此子切片细项证据源，总纲是包级汇总；两个层级不对同一工作分别维护相反状态。完成某原任务时必须关联本切片及其他必要后续证据；不自动勾选含剩余范围的原项。

## Risks / Trade-offs

- [纯文本 turn 仍隐式访问未适配文件服务] → provider/能力显式装配；禁止本地权威路径写入的运行测试覆盖整个进程生命周期，不只扫描 import。
- [PG 替换暴露同步/异步和事务边界缺口] → 先做连接/协议兼容测试并锁依赖，再逐真实行为接入；不全局改同步函数为 async 造成无界重构。
- [限制子切片被误当成删减 M1 范围] → 入口能力清单与总纲映射明确标记未交付；A1/G1 保持未通过。
- [账号初始化/恢复变成全局管理员旁路] → 独立运维用途、固定 tenant、最小数据权限、审计与普通用户不可构造的 scope。
- [会话删除牵涉文件/学习状态] → 本切片仅允许无外部依赖的删除，前置检查失败不修改原记录；后续开放资源前补齐补偿。
- [单执行被误当成 HA] → 限制实际执行数量，旧进程停止后才恢复；只承诺历史/事件持久和中断可见，不承诺自动接管。

## 实施前输入与验证记录

用户已于 2026-09-13 批准 apply，本切片已实施并完成隔离验证，见 [执行证据](execution-evidence.md)。实施第一组任务已确认包兼容的 core SHA、隔离 PG 的版本/身份、真实聊天模型 Secret 引用与调用预算；缺失外部资源时可完成静态/单元工作，但不能把真实 PG 或模型 smoke 标记通过。首发教材、图权限、KB 容量、RPO/RTO 和生产 CI 参数不是本切片已解决事项，继续由对应总纲任务取得确认，不虚填数值。

规划验收：OpenSpec strict、相对链接、proposal/spec/tasks 对应与范围自查。业务验收另需真实 PG 的迁移/权限/并发/恢复、HTTP/WS/SDK/CLI 及真实模型文本 turn；测试替身可用于确定性异常注入，不能替代该集成证据。

### 规划校验记录（2026-09-13，以下为实施前历史记录）

- 新 change 和全仓活动 changes 的 OpenSpec strict 校验通过（2 个 changes），四个 capability 与 spec 文件对应一致。
- 新提案及登记文件相对链接目标检查通过；总纲保留 90 项、本切片 34 项实施任务，均未勾选。
- 独立读者检查确认子切片/总纲及后续领域边界；已补齐“删除后幂等重放”和“备份恢复不得复活旧身份”的契约及验收任务。
- 历史检索证据的离线一致性脚本通过，仅说明保存结果一致；该规划轮次未执行模型、PG、HTTP/WS、容器或生产业务测试；本次实施的独立验证以执行证据为准。
