# 设计：普通运营 OMS 工作台

## 信息架构
独立 OMS 前端按“平台资源（模型与外部服务、Agent/能力、工具与集成、知识/内容基础能力、运行资源）→详情→服务供给→租户授权/额度→真实使用→异常核对”逐级进入；总览只展示真实待处理事项、配置待生效、供给不足、额度待处理和核对异常，卡片都指向筛选列表。租户详情只读 EduPlus2 lifecycle/本地隔离及对应服务权益，不显示独立欠费模型资格。Provider 配置/Secret 引用、供给补充和配额赠送/充值在授权后可写。用量按租户→用户/应用→service/provider/model→operation/attempt 展示真实原生单位、预留/已结算/待核对与来源；OMS-only 成本按有证据规则显示已核定/未核定，不展示租户售价、费用、账单或欠费。审计/任务仅返回安全摘要。

普通运营首先看到业务影响和建议动作，不显示内部主键、RLS、Webhook raw payload 或 provider 原始报错；需要排查时才可展开脱敏技术信息。所有状态/原因/操作文案从后端 descriptor 获取，缺失时统一显示“状态说明缺失，请联系支持”；不在前端硬编码后端 enum 映射。日期、币种、原生单位和时区有清晰标签，已结算与待核对明确分列。

## 权限与路由
进入独立 OMS 需 EduPlus2 可信平台主体和 `ops.oms.access`；菜单/按钮按 `ops.tenants.read`、`ops.providers.read/manage`、`ops.credentials.manage`、`ops.supply.read/manage`、`ops.entitlements.read/manage`、`ops.quotas.read/manage`、`ops.usage.read`、`ops.reconciliation.manage`、`ops.cost.read`、`ops.audit.read/export`、`ops.jobs.read` 等具体动作控制。前端显隐不是授权边界：API 再校验相同或更严格的权限与目标范围。无权限时不预取敏感 API，不把上一租户数据残留到下一租户。

默认平台管理员仅按 EduPlus2 受控权限模板获得必要写权；普通运营员按显式读/动作能力操作，审计员只读被授予的报表和审计；`tenant_admin`/普通用户不可进入 OMS，但原有登录、TMS 与业务管理入口不因某服务额度耗尽受阻。EduPlus2 lifecycle、平台供给、租户额度和配置 readiness 分栏：供给不足/额度耗尽不能渲染成“租户已停用”，待确认/待核对不能渲染成已生效/已结算。

## 数据与交互
仅消费真实企业 OMS API，服务端分页、筛选、排序和导出遵守同一授权与过滤；大明细不全量加载。API 错误显示可操作的重试/联系支持，不把空结果解释为零消耗。待核对显示原因和远端状态；成本只格式化后端已核定数据，不在前端估算。写操作先展示对象、当前/新值、影响时间、原因及二次确认，使用版本/幂等键，处理后回读并显示审计编号。禁止在浏览器持久化 Secret、完整请求正文、provider 原始敏感错误。

## 发布与验收
C1 可先交付真实只读资源/供给/权益状态，C2 再接获授权配置、供给、额度和核对写动作，但整个 change 未完成所有任务前不得标记 C1/C2/G3 完成。若后端 API 缺失，相关页面必须继续标记未启用或隐藏，不允许 mock/静态统计上线；生产原型路径 404。OMS 与 TMS 分别构建/部署，仅共享安全业务组件，不共享专有 API client。移动/窄屏可查看，键盘与屏幕阅读器可完成查询及获授权写操作。E2E 覆盖管理员、运营员、审计员、tenant_admin、普通用户、跨租户、成本/Secret 泄露、版本冲突、待生效/待核对及 API 失败。上游兼容检查聚焦认证、HTTP/WS turn、session ownership、audit correlation 不因新增 OMS 路由回归。
