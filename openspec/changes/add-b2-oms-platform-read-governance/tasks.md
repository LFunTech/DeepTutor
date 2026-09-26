> **实施已获批准（2026-09-26）**：以下任务已替换旧“只读 OMS”目标，用户已单独批准按现版实施，任务仍未完成。EduPlus2 OMS client/权限契约未锁定前不得装配跨租户写路由。

## B2.0 权限模型与迁移
- [ ] 1.1 与 EduPlus2 固定独立平台 issuer/audience/client、主体 ID、`ops.*` 动作、撤权/权限版本及默认/自定义角色发送端契约；核对其 OpenFGA/Keycloak/DB 受控迁移。
- [ ] 1.2 增加 DeepTutor 企业 PG 版本化平台主体绑定、权限快照/版本和审计迁移；合成数据验证 RLS、幂等、drift，`tenant_admin` 不继承。
- [ ] 1.3 测试先行：无 token、租户 token、错 issuer/audience/签名/撤权、伪造 scope/目标 tenant 均拒绝，平台默认及自定义动作正例，operator/auditor 高权限写 403。
## B2.1 真实分级治理 API
- [ ] 2.1 实现 `require_platform_permission(action)`、目标租户/动作范围绑定与受审计事务；企业 app 不挂核心旧 OMS `require_admin` 旁路，CLI/SDK/后台无直写。
- [ ] 2.2 实现总览、资源/配置、供给、权益/额度、用量、核对、成本、审计与任务的最小化治理 API 和后端 display catalog；具体写事务调用 OMS 业务唯一总账，不复制实现。
- [ ] 2.3 独立 OMS 前端入口/按钮/路由守卫与后端同 key，缺 descriptor 安全降级；TMS 仅当前租户安全投影，无后端数据时显示未启用。
## B2.2 验收
- [ ] 3.1 双租户 PG + HTTP/API 正负例、Secret/成本/私有内容泄露及导出负例、TMS/OMS 边界与 upstream seam 检查。
- [ ] 3.2 运行 CLI、HTTP/WS、SDK、后台、session owner、审计关联测试与 OpenSpec strict validation，留外部权限/PG 迁移和入口证据。
