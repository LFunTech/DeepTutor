## Purpose
定义普通运营人员使用的 OMS 界面、真实数据呈现和前后端一致权限边界。

## ADDED Requirements

### Requirement: OMS 必须用真实 API 提供普通运营工作流
独立部署 OMS SHALL 按五类平台资源与列表→详情工作流提供总览、资源/配置、服务供给、租户授权和统一赠送/充值额度、真实 Token/非 Token 原生用量、异常核对、OMS-only 有证据供应商成本及审计/任务视图；SHALL 优先呈现影响对象、状态和建议动作，使用后端 display descriptor。未交付的数据源 MUST 显示未启用/不可用，不得以 mock、静态数字或空数据伪装实时结果；生产原型路径 MUST 保持 404。

#### Scenario: 首次进入运营总览
- **WHEN** 获授权 platform_operator 打开 OMS
- **THEN** 页面显示真实待处理事项与可钻取对象，并明确区分配置待生效、额度/供给不足、已结算和待核对

### Requirement: OMS 路由和动作必须按平台能力授权
系统 SHALL 在前端按能力控制菜单及动作，在后端对每次查询/变更验证 EduPlus2 平台身份、目标租户和对应 `ops.*` 动作权限。`tenant_admin`、普通用户或伪造能力 MUST NOT 读取跨租户 OMS 数据；仅有读权限的运营或审计人员 MUST NOT 修改配置/Secret、供给、额度或核对，也不能读取成本。TMS 只复用安全 DTO/组件，不复用 OMS 专有 API client。

#### Scenario: 租户管理员直接请求隐藏页面 API
- **WHEN** tenant_admin 绕过页面直接调用 OMS 跨租户 API
- **THEN** 后端拒绝且不返回目标租户存在性或成本数据

### Requirement: 原生单位用量与供应商成本必须可追溯且不误导
OMS SHALL 支持租户→用户/应用→service/provider/model→operation/attempt 明细，显示可信原生单位、预留/已结算/待核对与证据；usage 缺失 SHALL 显示待核对，不以零或前端估算代替。供应商成本只向具有 `ops.cost.read` 的平台主体显示，无可信合同显示未核定；MUST NOT 生成租户售价、费用、账单或欠费。

#### Scenario: 用户有未核算调用
- **WHEN** 某用户有 settled 调用和无 usage 的 pending 调用
- **THEN** 页面分别显示已结算原生单位与待核对 attempt 数，并能钻取待核对原因，不推算租户费用

### Requirement: OMS 负责平台资源/权益而不接管租户生命周期
OMS SHALL 作为云端平台配置、Secret 引用、供给、服务授权/额度及核对的获授权写入口；MUST NOT 提供 EduPlus2 租户开停/恢复、TMS client/成员或租户私有正文管理入口。OMS SHALL 分别呈现租户 lifecycle、服务额度、平台供给和配置 readiness，不得把单服务额度不足误报为整个租户停用，并应提示登录、管理和其他服务是否仍可用。本地 DeepTutor Web 设置 SHALL 保持原有功能。

#### Scenario: 配置部分确认
- **WHEN** OMS 发布配置但部分目标执行者尚未确认
- **THEN** 页面显示“待生效/部分失败”及处理建议，而不是“已生效”

#### Scenario: 单服务额度耗尽但可登录管理
- **WHEN** 租户 lifecycle 正常且图像服务额度耗尽
- **THEN** OMS 只显示图像服务新调用受限，并明确登录、管理、历史及其他服务仍可用
