# 设计：持久通知、当前状态核验与保守准入

## 依据与方案选择

现行 Webhook 的 `SubscriptionWebhookRequest` 有事件 ID、投递时间、学校/应用/订阅 ID 与状态，但**无单调订阅版本**；online resolve 的 `version` 是快照哈希，停用时 `verified=false` 不返回完整绑定；现有 `/v1/app-subscriptions/check` 无版本/订阅 ID 且调用身份受限。详见 [契约核对](external-contract-audit-2026-09-27.md)。曾批准的“按来源版本更新状态”无法在当前接口上兑现。拒绝按事件到达时间/`timestamp` 排序，也不要求本代理修改发送端。选用“Webhook 通知 + online resolve 当前态 + 本地代次栅栏”：**本地代次只保证本系统并发顺序，绝非外部状态版本**。代价是外部不可用或证明过期时拒绝新业务，且首位 actor 激活需另行证明当前订阅 ID。

| 方案 | 收益 | 取舍/结论 |
| --- | --- | --- |
| 来源单调版本 + 带版本快照 | 可作确定性事件投影 | 现有接口不提供；不得由本代理改发送端，故不作为本版实施前提 |
| **持久通知 + 在线当前态核验** | 可只使用既存接口处理已验证学校的停用/恢复和乱序 | 需要保守失联策略、周期复核；首位 actor 当前订阅 ID 单独设门禁，**本版选用** |
| 按接收时间/事件 `timestamp` 覆盖 | 代码简单 | 投递重试和乱序会误开通或误停用，拒绝 |

## 1. 传输入口与可靠接收

保留现有 `POST /api/v1/eduplus2/webhooks` 的原始 body 上限 128 KiB、`X-EduPlus-Signature: sha256=...`、`X-EduPlus-Timestamp`、`X-EduPlus-Event` 与 `timestamp.event.raw-body` HMAC-SHA256、5 分钟时间窗和常数时间比较；支持配置化的当前/上一个 Secret ref 与明确轮换截止，不复用旧 revocation 两段式 HMAC。验签后区分 mock 与真实事件：mock 沿用已验证的 `X-EduPlus-Mock:true`/`mock_` ID/顶层 event 匹配规则，不要求其具备完整真实学校/应用字段；真实事件再严格校验 `event_id`、学校/应用/订阅正整数 ID、目标应用 ID 与配置一致、事件白名单及对应必要字段。签名无效 401；真实结构/未知事件 422；错误目标 403；PG 接收事务失败 503。拒绝只记录脱敏原因，不打印 body、OAuth Secret、签名或 Secret ref 值。

控制台 `X-EduPlus-Mock:true` 且 `mock_` ID 只在上述 HMAC 与 mock 校验成功后 204，**不写 inbox、资格、管理员事实**。真实事件在一个 PG 事务内保存 event ID、外部目标 ID、订阅 ID、事件类型、投递时间、接收时间、**不含 Secret 的业务字段白名单**、处理状态及告警信息。以独立稳定的 inbox 摘要密钥对规范化业务投影做 HMAC：投递 `timestamp`、签名、OAuth Secret 和可变展示字段不参与幂等摘要，避免同一事件合法重投或 Secret 轮换被误判冲突；学校/应用/订阅 ID、事件类型、状态及 created actor 等关键字段不同则同 ID 拒绝为 409 并告警。绝不保存原始 body、`oauth_client.client_secret`、签名或 bearer token。只有事务已提交才 204；204 表示通知可靠入队，不代表在线核验/业务开通成功。若安全入队能力尚未部署，真实事件仍 503；已经持久接收但后续对账失败由持久重试而非要求发送端无限重投。

未知内部学校但目标应用正确的合法通知可入**隔离的待绑定队列**，不获得内部 tenant ID 或业务资格。该队列只存最小外部 ID 与去敏事实，受服务端访问控制、PG 约束/RLS 和保留/清理策略保护；RLS 不代替应用权限。当前迁移/运行共用表 owner 的环境可能绕过普通 RLS，须服从 B1 的 FORCE RLS 审阅门禁，不能仅因建了 policy 宣称平台队列隔离。错误目标应用或与已验证绑定冲突不能入可处理队列。不能凭 `school_code`、URL、JWT 标签、Webhook 单一字段或旧 `external_tid` 猜内部学校。

## 2. 当前态对账与乱序

事件仅使对应学校—应用的本地核验状态变为 `unknown`、递增**本地 generation**，并唤醒持久 worker。`created/renewed/expiring/plan_changed` 不直接开通；`suspended/terminated/expired` 也不单凭 payload 作最终当前态，所有类型均触发相同在线复核。Webhook 到达时应使旧允许证明立即失效；若已绑定且有拒绝类事件，可在新证明前保持拒绝。worker 按学校—应用串行，使用已验证 client 候选调用现有 online resolve；失败或超时按 `unknown` 拒绝新业务并重试/告警。若明确 `verified=false`，只能对**事先已验证**的 client↔学校↔应用绑定记为不可用，不可用来绑定未知学校；`verified=true` 时必须交叉核对 client ID、稳定学校 ID、目标应用 ID、client/tenant/app/subscription 当前状态与已验证内部绑定。多个旧/新 client 候选应逐一核验，不能让一个旧 client 的失败覆盖另一个当前有效证明；有相互矛盾结果时保持 `unknown`。查询返回后必须复核本地 generation，已被更新则丢弃旧结果并重查。

online resolve 的哈希仅记为诊断 etag，不用于 `>`/`<` 比较或同版本冲突判定。对账覆盖启动时、事件通知、重试、周期轮询和新准入前证明过期；丢事件依赖周期核验和受控全量已绑定学校扫描弥补。允许状态有配置化的短有效期，过期、无法核验或学校绑定撤权立即 fail closed；不对未绑定学校自动回填 `allowed`。外部恢复只改变外部资格，不能覆盖本地隔离、撤权或资源未就绪。迁移中的 `not_required` 固定租户不得凭历史 `active` 自动转为外部 `allowed`。

## 3. 首位 TMS 管理员身份事实

真实 `subscription.created` 的 `actor.type=user` 与非空 `actor.user_id`（Keycloak `sub`，不是 `eduplus_user_id`）可随安全 inbox 投影形成**尚未绑定的事件来源事实**，以免未知内部学校时 2xx 后丢失该事实；只有目标应用、稳定外部学校与内部学校绑定均核验后，才以同事务/持久 outbox 向管理授权服务交付**待核验候选**。mock、system/null、其他事件、错误应用/学校不产生候选。**在线 resolve 只证明当前学校—应用可用，不返回当前订阅 ID**；旧 `created` 延迟到新订阅之后时，不能因此把旧 actor 激活。管理授权服务只有在既有受权只读接口经目标环境验证可比对当前 `subscription.id`，且学校绑定、issuer/sub、本人 TMS 登录、一次性引导及本地版本栅栏都满足时才激活 `school_admin`。目前可见的 `/v1/tenants/{tenantId}/subscriptions` 需要 `subscription_view`，不能预设 Webhook 服务凭证可调；可在候选本人登录后验证调用身份适用性。无可靠订阅 ID 证明时保持 `pending_verification`，不得用人工填库、URL、角色声称或仅凭首次收到的事件绕过。激活与撤权属于 `add-enterprise-management-authorization`，本接收器不授予角色、不管理学校账号。

## 4. 租户与逐服务准入

新登录、token exchange、新 HTTP/WS turn、下载授权和后台派发统一检查 `外部资格在线证明在有效期且 allowed ∧ 本地 enabled ∧ 资源 ready ∧ 其他独立策略`。证明未知/过期、订阅暂停或学校绑定撤权均拒绝新业务并给稳定生命周期业务码；必要的历史、审计、管理路径按独立授权继续可用。已签发短 TTL URL 不能即时撤回，要求即时撤权的资源用代理授权。OMS 供给/服务授权/额度是另一道**逐服务新调用**门禁，额度耗尽不改外部资格、不产生生命周期事件、不注销会话；服务额度与学校停用使用不同错误码/后端 display descriptor。旧 `/auth/eduplus2/revocations` 只保留撤销语义，绝不承接恢复。

权限—入口边界：Webhook POST 无交互用户会话，但必须通过独立 HMAC、目标应用及 schema 门禁，不能映射为匿名管理写权限；mock 无业务写入。OMS 外部状态仅脱敏只读，仍按本产品 `ops.*`/目标学校范围授权，不提供租户开停按钮/API。TMS 首位管理员候选状态与本人激活由管理授权 change 的 `tenant.school.bootstrap` 内部流程及 TMS 会话保护，本 change 不新增默认管理员、菜单或角色。数据库迁移只在 DeepTutor，OpenFGA/Keycloak 与 EduPlus2 不迁移。

## 5. 迁移、失败与验证

新增不可变的 DeepTutor PG 版本化 migration：平台级最小 inbox/待绑定队列、事件唯一与冲突约束、按学校—应用的本地 generation/在线证明/TTL、审计/重试、actor 待核验事实/交接状态；tenant-scoped 事实继续有租户约束和 RLS，平台队列仅服务端受控访问。旧外部资格保守映射，dry-run/apply/verify 与重复执行，回退保留已确认事实且回到 fail closed。**不做 EduPlus2/OpenFGA/Keycloak 迁移**。

测试以双学校合成数据覆盖伪签名、过期、跨应用/学校、过大包、Secret 轮换、重复/冲突 ID、旧事件晚到、并发 worker、client 轮换、online resolve 拒绝/超时/矛盾、失联过期、恢复不覆盖本地隔离、actor 旧订阅/缺失/本人匹配及单服务额度隔离。真实 test smoke 必须分别证明：204 已持久接收、worker 核验的绑定/状态、租户级准入正负例、首位 actor 当前订阅 ID 证明与本人激活（若该接口适用），不能将 204 或外部“已启用”单独当成学校已接入。上游中立 core seam 另留认证、HTTP/WS turn、session ownership 和审计关联的兼容证据。
