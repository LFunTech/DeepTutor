> **2026-09-27 Webhook 权威修订稿实施中**：用户已明确“学校接入与生命周期只采信已验签 Webhook，不再 online resolve 二次核验”。本清单重新评估旧勾选项；旧版 online resolve 实现与合成测试不等于新版通过。仅 DeepTutor；不修改 EduPlus2/Keycloak/OpenFGA。`rc.51` 已部署到 test-cn；首次真实订阅重试因运行时缺接收器配置仍为 503，现已受控补齐 test-cn 配置并重启，但**尚无新的非 mock 成功投递证据**。不自动授权再次真实重试、提交或归档。用户进一步要求彻底退役静态目标应用 ID 参数；本地代码与发布清理流程已修订，但未发布，不能据已启用配置宣称新契约通过。

## A. 已保留的接收基础
- [x] 0.1 控制台签名 mock 接收路径：HMAC、时效、大小、event/header、mock 标记与 ID 校验；mock 不改变业务状态。
- [x] 0.2 test-cn URL 上 EduPlus2 控制台 8 类签名 mock demo 均返回 204；只证明 URL/签名联调，不代表真实事件。
- [x] 2.2 真实事件的安全最小投影、PG inbox、同 event ID 幂等/冲突与提交后 2xx 在隔离合成数据中已实现；默认开关关闭，目标环境真实投递尚未通过。学校自动映射及生命周期投影属于下列任务，不能用本项冒充接校完成。

## B. 重订合同与持久状态
- [ ] 1.1 只读核对八类真实 `subscription.*` 的学校/应用/订阅 ID、tenant_type、status、client、actor 与投递/重试合同；在隔离环境取得脱敏非 mock 证据。同步修订 B1/B2 学校绑定与管理授权提案，明确 Webhook 业务权威、OIDC 仅认证、无来源版本/快照的漏送和迟到风险；分别完成变更审阅。
- [x] 1.2 新增不可变 DeepTutor PG 迁移和受控自动接校：稳定外部 `tenant.id`↔内部学校唯一映射、按学校—应用的接收 generation/投影位置、冲突隔离，以及学校 PG 数据空间 onboarding 标记；所有步骤同事务，故障整体回滚后由发送端重试，无本地待处理初始化任务。旧 0005–0007、固定租户、actor 终态保守保留。隔离双校 PG 验证重复 apply/verify、漂移、回退、RLS/应用访问，不手工补真实学校数据。AI 多学校运行时/资源 ready 属 B1/B2/OMS/TMS，不能在此假置 ready。
- [x] 1.3 移除生命周期对 online resolver/证明 TTL 的启动依赖，保留当前/上一签名 Secret、独立稳定 inbox 摘要密钥和默认关闭开关；从验签 body 读取正整数 `app.id`，验证缺配置、非法应用 ID、跨应用身份、密钥轮换与学校映射冲突失败关闭。仅本地合成配置验收，目标环境配置仍属 3.1。

## C. Webhook 投影与产品门禁
- [x] 2.1 测试先行覆盖签名、重放、同 ID 冲突、不同 ID 迟到/乱序、重订、学校码变化、双校并发、跨应用、首次 created 自动接校、暂停/恢复、未知状态、事务中断/重试及本地隔离；明确“本地接收顺序不等于来源时间”的可接受风险，不假定在线核验纠正。
- [x] 2.2a 已验签 created.actor 的最小待核验候选随自动学校映射可靠交接；合成 JWT/TMS Bearer 入口核验 issuer/sub/tid/azp、学校/应用 client/绑定/投影及 PG onboarding；本人一次性激活与主体/角色/终态/审计同事务。覆盖 system/null、重复、迟到、引导消费/撤销及错人/停用负例；Webhook 回调不授予 `tenant.*`。真实 actor↔JWT sub 的 test 证据另属 1.1/3.1，不因本地合成通过而宣称已验收。
- [x] 2.3 提供 Webhook 学校—目标应用数据库资格与本地隔离交集门禁：TMS 管理入口不因 AI local_enabled/ready=pending 被挡，AI 新调用仍须叠加本地 enabled/ready；保留旧固定租户兼容。B1/B2 负责各校登录/exchange/HTTP/WS/session/下载/后台的正式多学校运行时装配，OMS/TMS 负责正式界面及逐动作授权；逐服务额度归 OMS，不能由 Webhook 生成 lifecycle 事件。用隔离集成测试明确两层边界，不以 B1/B2 尚未完成阻断 Webhook 数据库链路。
- [x] 2.4 实现学校—应用持久串行事务内投影、generation 栅栏、失败整体回滚/5xx 重试、2xx 后无本地待处理状态、处理指标和告警、保留/清理策略及授权人工冻结/诊断/恢复。不再周期调用 online resolve 或依赖证明 TTL；明确漏送/迟到不能自动识别外部最终状态。

## D. 受控联调与完成证据
- [ ] 3.1 隔离合成双学校 PG/Webhook-TMS 管理入口集成；在另获发布/投递授权的 test 环境以独立测试学校做非 mock Webhook 投递，脱敏核对 204/inbox、学校 PG onboarding、暂停/恢复、本地隔离和真实 actor 本人激活。AI 资源 ready、跨校会话/HTTP/WS/下载/后台、单服务额度及短 TTL URL 由 B1/B2/OMS/TMS 分别联调，不作为 Webhook PG 链路的前置。现有首校仅在隔离与授权门禁通过后受控重试，不手工补数。
- [ ] 3.2 完整回归、迁移重复执行/漂移、上游中立 seam 的认证/HTTP/WS/session owner/审计关联审查、OpenSpec strict validation；记录 Webhook-only 残余风险、真实 actor 本人一次性激活和真实学校放行证据。未完成不得标记 change 完成、宣称强一致或归档。
