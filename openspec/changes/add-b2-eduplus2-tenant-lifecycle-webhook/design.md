# 设计：外部状态 inbox、版本及准入

现有 `eduplus2/service.py:720-842` 只将撤销状态设为 active；恢复事件不能复用。当前 EduPlus2 发送端和开发者文档实际使用 `subscription.created|suspended|reactivated|terminated|expired` 等订阅事件，而非此前暂拟的 `tenant.enabled|suspended|resumed`。这些订阅事件是否可直接作为 DeepTutor **租户级**资格仍需明确订阅/应用/租户绑定和权威版本；不能因 `status_reason=billing` 推断 OMS 服务准入，也不接收独立欠费模型资格事件。未知真实事件拒绝。新入口使用 EduPlus2 现行 `X-EduPlus-Signature: sha256=...`、`X-EduPlus-Timestamp`、`X-EduPlus-Event`，签名原文为 `timestamp.event.raw-body`，不复用旧撤销入口的两段式 HMAC。正式接收还需 payload schema、大小限制、密钥轮换和可审计拒绝。真实事件仅在 PG 事务提交后确认。

为先完成控制台 URL demo，企业组合在同一 `/api/v1/eduplus2/webhooks` 路径验证签名/时间戳/事件与原始 body，并只对带 `X-EduPlus-Mock: true`、`event_id=mock_...` 的控制台 mock 返回 204；不写 inbox、租户资格或撤销状态。未配置 secret、伪签名、过期或不匹配 payload 均拒绝；真实事件在单调版本/绑定/对账契约未实施前返回可重试 503。此联调前置切片不是生命周期处理器完成，且不能通过伪造 mock header 改变任何业务状态。

PG inbox 记录 event_id、external_tenant_id、authority_version、event_type、occurred_at、processed_at、safe summary 与结果；外部租户资格单独保存最后版本与状态，不保存原始敏感 payload。先验证 external tenant↔internal tenant 绑定，再在同一事务比较单调版本、更新外部状态与审计；重复 ID 幂等，旧版本忽略并告警，同版本冲突 payload 拒绝。若权威版本不可比较，必须先与 EduPlus2 定义有序版本，不能按到达时间猜测。对账 API 通过受控服务凭证获取租户权威快照，版本比较后补齐，不允许 OMS 手工覆写，也不覆盖本地隔离。

租户级准入为 `外部租户资格有效 ∧ 本地 enabled ∧ 资源 ready ∧ 其他独立策略允许`，按租户暂停语义检查登录/session、exchange、HTTP/WS、下载授权和后台派发。OMS 服务授权、额度与供给是**独立的逐服务新调用准入**，不能写入这个租户级资格状态，也不能触发撤销。某服务额度耗尽时，登录、管理、历史和其他服务仍按原权限可用；已发出的 attempt 仍依其用量/待核对规则结算。不得以旧模型资格快照替代 OMS 供给/额度验证。

外部租户资格缺少可信初始快照或超过约定时效时按现有租户级 fail closed 规则并告警，不用 OMS 额度决定登录资格。已签发短 TTL URL 无法立即撤回，需即时撤权的资源走代理授权。生命周期拒绝与服务额度/供给不足须使用不同稳定业务码和后端 display descriptor，不能把“某服务额度耗尽”伪装为“租户已停用”。

迁移：DeepTutor PG 扩展 tenant external status/version、inbox/索引并按明确映射保守回填；旧 `active` 不可推断外部启用，重复迁移幂等并验证 RLS。EduPlus2 发送端/签名/事件模型需其仓库受控变更；若涉及 OpenFGA/Keycloak 则单列 provider migration。回退不得擦除已处理的更高权威版本。用合成双租户验证签名错误、重放/乱序、错误 tenant、激活保留本地隔离、额度耗尽不产生 lifecycle 事件。
