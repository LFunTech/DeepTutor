## Purpose
定义普通运营人员使用的 OMS 界面、真实数据呈现和前后端一致权限边界。

## ADDED Requirements

### Requirement: OMS 必须用真实 API 提供普通运营工作流
独立部署 OMS SHALL 按五类平台资源与列表→详情工作流提供总览、资源/配置、服务供给、租户授权和统一赠送/充值额度、真实 Token/非 Token 原生用量、异常核对、OMS-only 有证据供应商成本及审计/任务视图；SHALL 优先呈现影响对象、状态和建议动作，使用后端 display descriptor。未交付的数据源 MUST 显示未启用/不可用，不得以 mock、静态数字或空数据伪装实时结果；生产原型路径 MUST 保持 404。

#### Scenario: 首次进入运营总览
- **WHEN** 获授权 platform_operator 打开 OMS
- **THEN** 页面显示真实待处理事项与可钻取对象，并明确区分配置待生效、额度/供给不足、已结算和待核对

### Requirement: OMS 路由和动作必须按平台能力授权
系统 SHALL 在前端按能力控制菜单及动作，在后端对每次查询/变更验证 EduPlus2 既存 OIDC 身份、DeepTutor OMS 当前 `ops.*` 动作权限及经核验的目标学校范围。`tenant_admin`、普通用户或伪造能力 MUST NOT 读取跨租户 OMS 数据；仅有读权限的运营或审计人员 MUST NOT 修改配置/Secret、供给、额度或核对，也不能读取成本。TMS 只复用安全 DTO/组件，不复用 OMS 专有 API client 或权限会话。

#### Scenario: 本产品平台授权已撤销
- **WHEN** 已登录 OMS 的运营人员被撤销某动作或学校范围
- **THEN** 菜单/按钮按刷新后的权限隐藏，直接 API 调用立即由后端拒绝，旧页面数据不继续显示该学校敏感内容

#### Scenario: 应用权限管理与外部身份边界
- **WHEN** 有 `ops.permissions.manage` 的平台管理员维护 OMS 应用角色和目标学校授权
- **THEN** 仅写 DeepTutor 审计化权限记录；不创建、停用或改写 EduPlus2 账号、学校、OpenFGA 或 Keycloak

#### Scenario: 学校账号管理入口被拒绝
- **WHEN** OMS 主体访问旧首位学校管理员开通路径或提交学校候选主体
- **THEN** 页面与 API 均不提供该能力，学校侧开通由 TMS 独立负责

#### Scenario: 租户管理员直接请求隐藏页面 API
- **WHEN** tenant_admin 绕过页面直接调用 OMS 跨租户 API
- **THEN** 后端拒绝且不返回目标租户存在性或成本数据

### Requirement: 原生单位用量与供应商成本必须可追溯且不误导
OMS SHALL 支持租户→用户/应用→service/provider/model→operation/attempt 明细，显示可信原生单位、预留/已结算/待核对与证据；usage 缺失 SHALL 显示待核对，不以零或前端估算代替。供应商成本只向具有 `ops.cost.read` 的平台主体显示，无可信合同显示未核定；MUST NOT 生成租户售价、费用、账单或欠费。

#### Scenario: 用户有未核算调用
- **WHEN** 某用户有 settled 调用和无 usage 的 pending 调用
- **THEN** 页面分别显示已结算原生单位与待核对 attempt 数，并能钻取待核对原因，不推算租户费用

### Requirement: OMS 负责平台资源/权益而不接管租户生命周期
OMS SHALL 作为云端平台配置、Secret 引用、供给、服务授权/额度及核对的获授权写入口；MUST NOT 提供 EduPlus2 租户开停/恢复、TMS client/任何学校账号或租户私有正文管理入口；首位 TMS 管理员仅由 TMS／学校侧受控开通。OMS SHALL 分别呈现租户 lifecycle、服务额度、平台供给和配置 readiness，不得把单服务额度不足误报为整个租户停用，并应提示登录、管理和其他服务是否仍可用。本地 DeepTutor Web 设置 SHALL 保持原有功能。

#### Scenario: 配置部分确认
- **WHEN** OMS 发布配置但部分目标执行者尚未确认
- **THEN** 页面显示“待生效/部分失败”及处理建议，而不是“已生效”

#### Scenario: 单服务额度耗尽但可登录管理
- **WHEN** 租户 lifecycle 正常且图像服务额度耗尽
- **THEN** OMS 只显示图像服务新调用受限，并明确登录、管理、历史及其他服务仍可用
