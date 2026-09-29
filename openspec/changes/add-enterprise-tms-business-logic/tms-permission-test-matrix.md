# TMS 分层权限测试矩阵（2026-09-28）

| 层级 | 入口 | 必需授权 | 正例 | 负例 |
| --- | --- | --- | --- | --- |
| 管理元数据读取 | `/api/v1/tms/quotas`、成员/应用/服务列表 | `tenant.tms.access` + 对应 `tenant.*.read` | 已激活 `school_admin`/auditor 读取本校脱敏 DTO | 普通成员、旧 `tenant_admin`、错校 URL、伪造 header、学校停用、外部身份失效。 |
| 管理写入 | 成员/角色/服务访问 grant、应用访问 | `tenant.permissions.manage` 或 `tenant.access.manage` + 委托上界 | `school_admin` 授权本校已本人登录主体 | 自授、自批、越委托、撤销最后管理员、跨学校、OMS 服务未授权/已撤销。 |
| 私有正文读取 | session/message/resource body、KB 文档原文、引用下载 | owner 或显式 resource grant | owner 本人下载/查看；被分享者按 grant 读取 | 学校管理员仅凭管理角色读他人正文、长期 URL 复用、S3 key 暴露、跨租户资源 ID 猜测。 |
| 资源写入 | KB/文档上传、删除、重试、tenant Skill ZIP | 当前学校资源管理动作 + owner/grant 约束 | 有权管理员提交本校 ZIP/文档，服务端重验 `school_id` | 单文件/危险 ZIP、伪造 owner/status、任意 LightRAG workspace/URL、未审核脚本执行。 |
| 用量/配额只读 | 配额详情、attempt 明细、待核对 | `tenant.quotas.read` + `tenant.usage.read` | 当前学校按 service/provider/model/subject 过滤 | 成本/采购/Secret/跨校字段、直接写 quota/usage、把额度耗尽显示为学校停用。 |
| HTTP/WS/SDK/下载 | REST、WS turn、SDK facade、文件下载 | 同一 Enterprise PEP + owner/grant | 当前学校用户正常发起受权服务调用 | CLI/SDK/后台直连绕过、session owner 不一致、Agent 子调用归属缺失、防双扣失败。 |

验证策略：

1. 每个正式 API 至少覆盖 401、403、409/版本冲突和 200；写 API 必须有审计和 expected_version/幂等键。
2. 私有正文负例必须跨 HTTP、WS、SDK 或下载入口至少两类覆盖，不能只靠前端隐藏。
3. 共享组件测试必须证明 TMS DTO 不含 OMS `ops.*`、Secret、成本、供应商采购或跨学校字段。
4. 真实外部接口缺失时，对应写入口保持 fail closed，并在测试中固定 503/未启用状态。
