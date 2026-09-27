# 设计：B1/B2 可信学校绑定与隔离

## Context

已归档的联邦访问 change 提供第三方 JWT、resolve、profile、普通 `dt_token` 与部分 HTTP/WS/SDK guard；M1/PG scoped persistence 已提供稳定内部 ID 与 RLS 底座。这些均不证明最终学校 ID 合同、独立管理会话、双学校资源隔离或真实 G2。当前 `oms/0011_school_binding.sql` 是未完成的学校绑定基础迁移，不得原位改写；管理权限迁移 `management/0001` 只有未装配的事务原语。现有 test-cn Webhook 8/8 为 mock 签名 demo，真实生命周期合同未确认。

## Goals / Non-Goals

**Goals:** 用既存外部接口证明首校身份/学校归属，建立可撤权的内部绑定；将同一可信 scope 传至所有适用数据面；按 B1→B2/G2 的证据门禁开放学校。

**Non-Goals:** 不修改或代建 EduPlus2、Keycloak、OpenFGA；不在此 change 实现 OMS/TMS 角色、两名学校负责人审批、生命周期 inbox、服务额度、Provider 或独立前端业务页；不借此创建管理员、迁入真实旧数据或开放生产流量。

## Decisions

### 1. 外部证据与本地授权分层

EduPlus2 OIDC 只证明 `issuer/sub`、client/app 与已签名学校身份字段；学校接入和订阅开停的业务权威由 `add-b2-eduplus2-tenant-lifecycle-webhook` 已验签 Webhook 提供。DeepTutor 内部 `tenant_id` 是资源和 RLS 的唯一稳定主键。B1 普通用户绑定复用现有 `eduplus2.identity_bindings` 与注册/换票链；`oms.school_bindings` 的首次学校 ID 映射/版本由 Webhook 的真实 created 事务创建，管理授权模块只消费该绑定并控制本产品人员权限，不再建立第二套学校接入权威。学校码仅用于路由定位并须与当前可信绑定核对。相对方案“由 URL code 或未经验签的 `tid` 直接推内部学校”会使改码、错类型和跨校写入不可审计，故拒绝。

外部 API **适用性矩阵**先记录接口版本、调用身份、环境、脱敏样例、响应中的稳定学校 ID 类型/状态、失效与故障模式；未知处保持未装配管理写入口。既存 `/me/profile` 仅本人，M2M 客户端或 Webhook Secret 不能推导学校成员目录或负责人资格。任何接口未交付时不伪造响应，也不要求本项目改发送端。

### 2. 绑定及撤权版本栅栏

新增 DeepTutor 后续版本 PG 迁移，而非改 `0011` 或已应用身份迁移：消费 Webhook 已建的内部学校 UUID、稳定外部数字 ID、学校展示 code、当前绑定版本和 PG onboarding 标记；不扫描旧 admin/tenant 数据，不以普通 JWT 或 code 补建学校。改码仅更新 locator，绑定撤销/重核验增加版本且不改资源 owner。多学校 AI 资源初始化/撤权/任务用 expected_version、幂等键和审计，重复 apply/verify、drift/失败回退按企业迁移 runner 规则。Webhook 负责 PG 学校接入，管理授权 change 负责本产品人员的逐动作/目标范围判定，本 change 负责各校运行时隔离，三者不得互相冒充。

写请求在外部状态复核后，用受限 PG 事务读取绑定及 epoch，随后再取业务版本和资源锁；同一事务中执行权限检查与业务变更。撤权走相同绑定锁，避免旧会话在撤权提交后继续写。读、下载、WS 新命令与后台派发用当前 epoch 门禁；缓存只加速非敏感展示，不作为状态未知时的允许依据。若远端状态/版本不确定，拒绝新敏感副作用并留下脱敏审计。

### 3. 单一可信 scope 跨入口传播

可信 scope 由验签会话、当前绑定和本地准入交集生成，包含内部 `tenant_id`、主体、绑定 epoch、client/app 和 request correlation。HTTP/WS/SDK 与后台均通过同一通用 provider/seam 注入；CLI 本地模式不获取企业跨校特权。**2026-09-27 用户确定迁移与运行使用同一个 PG 账号，不拆分。**每次业务 PG 操作仍在显式事务中 `SET LOCAL` 学校/owner scope，结束或取消后清除；对象、缓存、任务和 LightRAG 调用复用同一 tenant/owner/KB/index-version。资源授权仍按 owner/显式 grant，不能把 TMS 学校管理角色转成个人私有正文访问。core 只接受上游中立的上下文与 guard seam，企业学校语义留在 `extensions/enterprise/`。

在此单账号约束下，**拟采用的后续版本 `FORCE RLS` 只能是正常应用 SQL 的纵深防御，不能宣称数据库凭据本身具备独立跨校安全边界**：表 owner 可变更策略，同一连接身份也可自行设置当前自定义 `app.tenant_id`/`app.user_id`。受控入口、可信 scope 生成、owner/grant 与禁止任意 SQL/DDL 暴露仍是必要前提；若 G2 要求抵御持有该 PG 账号的恶意直连，则当前单账号决策与该验收目标冲突，须单独确认风险边界，不能靠 `FORCE` 测试宣称达标。改动核心迁移前的影响面与替代方案否决理由见[单账号严格审阅](external-contract-and-path-audit-2026-09-27.md#单账号-force-rls-严格审阅及实施门禁)。

### 4. 外部生命周期、管理权限和额度正交

生命周期由 `add-b2-eduplus2-tenant-lifecycle-webhook` 持有签名 inbox、本地持久接收 generation 和 PG onboarding 标记；**来源没有单调版本或受信快照，本系统不以 online resolve 周期对账覆写 Webhook 投影**。本 change 负责把已投影外部资格、AI 本地 enabled/ready、绑定版本和受限资源 scope 组合进各校运行时入口；它不反向成为 Webhook 数据库初始化或 TMS 首管激活的前置。OMS/TMS 权限由 `add-enterprise-management-authorization` 决策；服务额度由 OMS 权益/逐 attempt 总账持有，不反写学校生命周期。相对方案“一个 admin 或 active 标志放行全部能力”会抹掉权威边界，故拒绝。

### 5. 验收与放量是独立状态机

B1 仅能在一个受控学校实测 OIDC/resolve/profile/学校状态、普通换票、HTTP/WS turn、资源、重新登录和撤权后标为通过；测试环境的 mock Webhook 或合成 token 不算外部合同。B2 在相同实现上完成双学校与同校双用户的 PG/RLS、S3、LightRAG/图、缓存/任务、owner/grant、TMS/OMS 交叉负例，G2 有回退/恢复和当前 upstream 审阅记录后才开放第二所真实学校。部署本身不改变验收状态；若多执行者启用则 G-H 先行，单执行者标明非 HA。

## Risks / Trade-offs

- [既存外部接口不具备在线学校/账号状态或稳定 ID] → 对应绑定、管理写和 B1 验收保持关闭；记录缺口交由所属团队提供，不在本仓库伪造权威。
- [撤权与长运行任务竞态] → 在新副作用检查点比较 epoch，持久任务保留绑定版本；已发生的远端副作用进入待核对而不虚报回滚。
- [多后端无分布式事务] → PG 中持久化任务/对象状态与幂等对账，LightRAG/S3 失败保持 pending；不假设一次 PG 事务能原子回滚远端。
- [当前上游差异较大] → 优先企业扩展与通用 seam，逐 core patch 记录受影响入口/合并风险；G2 前验证当前 `upstream/main` 兼容性。
- [单库表 owner 连接绕过 core RLS] → 双校合成测试已复现，Store 显式条件只提供应用层隔离；用户已排除迁移/运行账号分离。后续上游中立的 `FORCE RLS` 迁移需覆盖 core 与企业扩展中尚未 FORCE 的租户表、历史版本目录验证、维护/离线导入/切换路径及回退，且**不能**把同账号 `FORCE` 当作防凭据恶意直连的边界。`03`/`04` 的非 owner 目标与 `06` 的单 owner 说明仍需在 G2 前正式收敛；未完成严格审阅与风险边界确认前不修改已应用迁移或宣称数据库强隔离。证据见[单账号严格审阅](external-contract-and-path-audit-2026-09-27.md#单账号-force-rls-严格审阅及实施门禁)。

## Migration Plan

1. 不接入真实学校，先以临时 PG/对象/检索隔离合成数据验证新迁移、默认拒绝、双校与失败回退；校验旧 `0011` checksum 不变。
2. 对已交付 EduPlus2 只读合同做受控 test 环境验证，固定配置与证据；用同一 PG 账号经受控维护命令登记首所学校的明确映射，应用 HTTP/WS/SDK 入口不得暴露任意 SQL/DDL 或直接创造权威绑定。单账号无法在数据库层阻止该凭据持有者 DDL，须把此剩余风险写入验收与运维控制，不以措辞暗示运行身份是非 owner。
3. 完成 B1 首校真实登录/撤权证据，再在测试环境以两校做全入口 G2；获单独发布批准后按明确 allowlist/feature gate 放量。未通过时保持第二校关闭。
4. 回退优先关闭新入口/allowlist、排空任务和恢复兼容应用版本；不删除已写入的新业务数据、不切回 SQLite，不靠改旧学校 ID 回退。外部状态不确定时停写并对账。
