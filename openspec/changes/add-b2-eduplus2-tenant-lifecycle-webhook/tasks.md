> **2026-09-27 用户已批准按重订版实施**：从“单调来源版本事件投影”改为“持久通知 + 现有 online resolve 当前态核验”。不修改 EduPlus2/Keycloak/OpenFGA；不授权发布或写入真实学校数据。已完成的 mock URL demo 任务保持历史事实，不代表真实 Webhook 完成。

> **后续决策**：首位 actor 的事件当前订阅性由 EduPlus2 处理；DeepTutor 保留 `subscription.id` 作为事件事实，不再独立查询当前订阅 ID 作为激活门禁。此前相关任务文字以本版为准；真实事件合同、本地一次性授权和本人同校校验仍须验收。

## B2.-1 已完成：控制台 Webhook URL 验证
- [x] 0.1 提供企业组合的签名 mock 接收路径，使用 `timestamp.event.raw-body`、secret ref、大小/时效/事件校验；仅对 `X-EduPlus-Mock: true` 且 `mock_` event ID 的请求返回 204，真实事件未就绪时 503，隔离合成测试证明状态不变。见 `implementation-evidence.md`。
- [x] 0.2 在已配置的测试 URL 上由 EduPlus2 控制台实际触发 Webhook demo，核对其投递记录、响应和目标环境；不在文档/日志记录 Secret。2026-09-26 `智能体基座` 的 test-cn 环境 8 类订阅事件均由发送端记录为 HTTP 204；只证明 mock URL 联调。

## B2.0 既存合同与 DeepTutor 迁移
- [ ] 1.1 只读锁定现有八类 `subscription.*`、online resolve 的 active/denied/异常语义、目标应用/client/学校 ID、调用身份、时效/重试，以及真实 `subscription.created` 的 `actor`/订阅 ID 投递合同；按环境保存脱敏证据。无需为 DeepTutor 首位激活另查当前订阅 ID，真实事件和本人同校资格未证实时仍保持写入口关闭。
- [x] 1.2 增加 DeepTutor PG 不可变版本 migration：最小 inbox/待绑定队列、事件 ID/完整性冲突、学校—应用本地 generation、在线证明及 TTL、重试/审计、actor 待核验交接，约束、RLS/应用访问、旧数据保守映射；隔离数据 dry-run/apply/verify、重复运行和回退验证。仅隔离合成 PG 验收；目标环境迁移属 3.1，保留/清理运营策略属 2.4。
- [x] 1.3 配置目标应用 ID、Secret 当前/上一版本轮换窗口、独立稳定 inbox 摘要密钥、在线核验 client 与证明 TTL；验证缺配置、错误应用、缺可用绑定时 fail closed，且不对 EduPlus2/Keycloak/OpenFGA 做任何迁移或写入。仅本地合成配置验收，目标环境配置/启用仍属 3.1 发布门禁。

## B2.1 接收、对账与准入
- [x] 2.1 测试先行：签名/过期/超限、真实与 mock、同 ID 不同投递时间幂等/业务事实冲突、错误应用/学校、乱序/重订、并发 generation、client 轮换、online resolve 拒绝/超时/矛盾、未知事件均按新版合同处理。合成回归已覆盖；双学校与目标环境联调另由 3.1 验收。
- [x] 2.2 实现真实 Webhook 的最小安全投影、PG inbox、事务后 2xx 与持久重试状态；2xx 仅为可靠接收，未落库 5xx；不存/记 OAuth Secret 或原始 payload，旧 revocation 处理器不接恢复。仅隔离合成测试验收，正式接收开关默认关闭；其他任务及 test 真实联调仍未完成，见 `implementation-evidence.md`。
- [ ] 2.2a 随安全 inbox 保存真实 `subscription.created.actor` 最小未绑定来源事实，核验学校绑定后可靠交给管理授权服务的待核验候选；补迟到事件、system/null、重复、已消费/撤销引导以及本人 issuer/sub/学校不匹配的负例。`subscription.id` 只作为事件事实，不做 DeepTutor 当前订阅 ID 比对；真实事件、学校当前有效和本人同校验证未通过前不得装配首位激活写入口。
- [ ] 2.3 测试先行并实现全入口租户级准入、本地隔离与旧固定租户兼容；另验证 OMS 单服务额度不足只拒对应服务新调用，登录/exchange/管理/历史/其他服务不受影响、不生成 lifecycle 事件。
- [ ] 2.4 实现按学校—应用串行的 online resolve 当前态对账、本地 generation 栅栏、启动/周期复核、缓存失效、证明 TTL、故障重试与指标；未知/过期/矛盾均 fail closed。

## B2.2 验证与放行
- [ ] 3.1 合成双学校 PG 集成和既有 EduPlus2 接口的目标环境脱敏只读 smoke；分别核对 Webhook 持久 2xx、状态在线证明、学校绑定、恢复/本地隔离、已有会话、管理路径、单服务额度及短 TTL URL。test 首校只有在安全绑定与授权门禁均过后才受控重试，不手工补数。
- [ ] 3.2 运行相关测试、迁移重复执行/漂移、upstream seam 兼容审查、OpenSpec strict validation；明确 actor 事件当前性归 EduPlus2、DeepTutor 的真实事件/本人同校/一次性授权证据和未开放写入口。未完成这些证据不得标记 change 完成或宣称真实学校已接入。
