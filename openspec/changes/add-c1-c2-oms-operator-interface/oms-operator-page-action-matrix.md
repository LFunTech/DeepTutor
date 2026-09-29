# 独立 OMS 正式界面页面/API/动作矩阵（2026-09-28）

## 后端能力基线

| 页面/模块 | 后端 API | 动作 key | 范围 | 状态 |
| --- | --- | --- | --- | --- |
| 工作台总览 | `GET /api/v1/oms/summary` | `ops.oms.access` + 逐学校 `ops.tenants.read` | platform + school | 已有最小正式 API；只聚合已授权学校。 |
| 平台资源状态 | `GET /api/v1/oms/resources/status`、`/status/catalog` | `ops.providers.read` / `ops.oms.access` | platform | 已有脱敏状态 API 与后端 descriptor。 |
| 模型配置 | `GET/POST /models/draft`、`POST /models/test|publish|rollback`、`GET /models` | `ops.providers.read/manage` | platform | 模型切片已有；全服务 Provider 草稿仍待 all-service proposal。 |
| 学校治理列表/详情 | `GET /tenants`、`GET /tenants/{school_id}` | `ops.tenants.read` | school | 已有最小正式 API；不使用 tenant_admin。 |
| 供给总览 | `GET /supply` | `ops.supply.read` | platform/custom | 已有脱敏读 API；写补充仍走后续供给操作。 |
| 学校权益/额度 | `GET /schools/{school_id}/quota` 与写路由 | `ops.entitlements.*`、`ops.quotas.*` | school | 已有后端写路由与总账。 |
| 用量/任务 | `GET /schools/{school_id}/usage`、`/jobs` | `ops.usage.read`、`ops.jobs.read` | school | 已有按学校只读 API；筛选分页/导出待 UI。 |
| 审计 | `GET /audit?school_id=...` | `ops.audit.read` | school/platform | 已有脱敏读 API；导出待 `ops.audit.export`。 |
| 成本 | `GET /cost` | `ops.cost.read` | platform | 仅返回未配置，不伪造成本。 |
| Skill | `/skills/draft|review|publish|grant` | `ops.skills.*` | platform/school | 后端切片已有；列表/详情 UI 待接。 |
| 平台人员/角色/学校范围 | 管理授权服务/未来 OMS UI API | `ops.permissions.manage` | platform/school | PEP/PG 事实已有；正式管理 UI/API 仍待实现。 |

## 菜单与按钮规则

- 顶层进入 OMS 必须先通过 `ops.oms.access`；页面再按 API 返回的权限/403 安全降级。
- 学校级菜单项（学校详情、权益、额度、用量、任务、审计）只针对已授权 `school_id` 展示。
- Provider/Secret/成本/平台人员角色属于 platform 范围，不得由任一学校授权显示。
- 所有写动作必须带 expected_version、幂等键和原因；危险操作（Secret、成本导出、权限管理）需二次确认和审计回读。
- OMS 不显示学校账号、首位 TMS 管理员开通、学校角色/成员维护；旧“学校后台开通”深链/API 必须 404/隐藏。

## 外部依赖状态

- EduPlus2 只提供既存 OIDC/在线账号/学校身份；本产品 `ops.*` 权限均来自 DeepTutor Enterprise PG 事实。
- `eduplus-platform-admin` 授权码登录与真实账号状态端点尚缺 test-cn 脱敏证据；前端正式登录放行仍阻断。
- 学校生命周期和首位 TMS actor 候选来自 Webhook；OMS 不参与学校账号激活。
