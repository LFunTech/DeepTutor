> **重订已获单独批准（2026-09-26）**：本版仅保留 EduPlus2 租户 lifecycle 与对账，旧欠费模型资格任务已移除。用户明确先做 Webhook URL demo 再完成发送端配置；真实事件的权威版本/对账契约仍须锁定。

## B2.-1 控制台 Webhook URL 验证（不触碰租户状态）
- [x] 0.1 提供企业组合的签名 mock 接收路径，使用 `timestamp.event.raw-body`、secret ref、大小/时效/事件校验；仅对 `X-EduPlus-Mock: true` 且 `mock_` event ID 的请求返回 204，真实事件未就绪时 503，隔离合成测试证明状态不变。见 `implementation-evidence.md`。
- [x] 0.2 在已配置的测试 URL 上由 EduPlus2 控制台实际触发 Webhook demo，核对其投递记录、响应和目标环境；不在文档/日志记录 Secret。2026-09-26 `智能体基座` 的 test-cn 环境 8 类订阅事件均由发送端记录为 HTTP 204，见 `implementation-evidence.md`；此项仅证明 mock URL 联调，不代表真实生命周期事件已开放。

## B2.0 权威契约与迁移
- [ ] 1.1 与 EduPlus2 锁定 `subscription.*` 对 DeepTutor 租户级资格的准确映射、单调版本、签名、租户/应用绑定、对账 API 和恢复时序；保存双方契约证据，OMS 额度耗尽不得发订阅停用或模型资格事件。
- [ ] 1.2 增加 DeepTutor PG 版本化 migration：inbox、外部租户状态/版本、约束、索引、RLS、旧数据保守映射；从 EduPlus2 获取可信初始快照，dry-run/apply/verify 与重复执行。
- [ ] 1.3 发送端若变更 EduPlus2/OpenFGA/Keycloak，登记独立迁移入口；不得手工补事件或角色。
## B2.1 接收与执行
- [ ] 2.1 测试先行：租户停用/恢复、重复 ID、乱序、冲突 payload、伪签名/过期/跨租户和未知事件均按合同处理。
- [ ] 2.2 实现独立 lifecycle webhook/inbox 与审计；现有撤销语义不被激活事件误用。
- [ ] 2.3 测试先行覆盖租户暂停的全入口准入与本地隔离；另验证 OMS 单服务额度不足只拦对应服务新调用，登录/exchange/管理/历史/其他服务不受影响、不生成 lifecycle 事件。
- [ ] 2.4 实现外部租户状态对账、缓存失效、故障重试与指标；资格未知按原租户级规则处理。
## B2.2 验证
- [ ] 3.1 双租户 PG 集成与真实 EduPlus2 合同 smoke；恢复、本地隔离、已有会话、管理路径、单服务额度与短 TTL URL 边界有证据。
- [ ] 3.2 运行相关测试、upstream seam 兼容审查及 OpenSpec strict validation；未确认发送端不得标记完成。
