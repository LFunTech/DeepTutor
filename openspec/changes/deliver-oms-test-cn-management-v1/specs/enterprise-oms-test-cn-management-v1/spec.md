## Purpose

定义 test-cn 可交付的 OMS v1 范围、验收口径和与旧横向 proposal 的收敛边界。

## ADDED Requirements

### Requirement: OMS v1 必须成为唯一当前执行主线

项目 SHALL 使用 `deliver-oms-test-cn-management-v1` 跟踪 test-cn OMS v1 的剩余实现、验收、部署和证据。旧 OMS 横向 proposal 的已完成任务 MAY 作为证据来源；其未完成任务 MUST NOT 在未重订范围的情况下继续作为当前执行主线或被伪装成完成。

#### Scenario: 新增 OMS 验收任务
- **WHEN** 发现 OMS v1 仍缺少本地、test-cn 或 UI 验收任务
- **THEN** 该任务写入本 proposal 的 tasks/evidence，而不是继续分散到旧授权、业务、前端或用量 proposal

### Requirement: OMS v1 必须通过正式入口和本地真实域名链路验收

OMS v1 SHALL 通过正式 `/oms` 入口提供受控后台，不得展示调试页、fixture 或原型回退。所有本地浏览器验收 MUST 经过 `local-ssl` 的 `https://deeptutor.lfun.pub/oms` 链路；裸 `localhost` 或单端口验证不得作为浏览器-facing 完成证据。

#### Scenario: 本地打开 OMS
- **WHEN** 用户访问 `https://deeptutor.lfun.pub/oms`
- **THEN** 未登录时进入 OMS 授权码登录流程，已登录且有本地 `ops.*` 时进入正式后台
- **AND** 无效 `_next/static` chunk 返回 404，有效 chunk 返回 JavaScript 200，不进入 OMS 会话鉴权或返回 500/502

### Requirement: OMS v1 必须使用 DeepTutor Enterprise 本地权限事实失败关闭

OMS v1 SHALL 只根据 EduPlus2 既存认证身份和 DeepTutor Enterprise 本地 `ops.*` 权限事实判定平台动作及目标学校范围。`tenant_admin`、EduPlus2 role、JWT 任意 claim、客户端 header、数据库 role/GRANT/RLS 或 URL 学校码 MUST NOT 直接授予 OMS 权限。写操作 MUST 复核 CSRF/Origin、幂等键、对象版本、学校绑定版本和审计。

#### Scenario: 已认证但无本地授权
- **WHEN** 平台主体完成 EduPlus2 OMS 授权码登录但没有本地 `ops.oms.access`
- **THEN** OMS API 返回失败关闭，前端不得显示调试页、学校账号开通入口或写按钮

### Requirement: OMS v1 必须覆盖核心运营后台功能

OMS v1 SHALL 至少覆盖学校列表/详情、模型与服务、供应商连接、Agent/工具/知识基础能力/运行资源安全状态、Skills、服务供给、学校服务授权、额度、用量/任务、审计/成本和平台授权治理。未实现写管理能力的资源类别 MUST 明确呈现为安全状态投影，不得暗示完整管理闭环。

#### Scenario: 查看知识基础能力
- **WHEN** 运营人员打开 OMS 的知识基础能力页面
- **THEN** 页面只展示后端安全 DTO 返回的脱敏资源状态；没有正式 DTO 时显示未启用/不可用，不回退原型知识库或私有正文

### Requirement: OMS v1 必须按 admin-only test-cn 口径验收

test-cn OMS v1 SHALL 仅使用 `.secrets/.login-credentials` 中 admin 账号作为当前真实账号验收范围。验收 MUST 覆盖正式入口、核心菜单、授权按钮、失败关闭、无学校账号开通入口、Secret/成本/私有正文不泄露及静态资源错误路径。更大的多角色、多学校、TMS 或 provider adapter 矩阵 SHALL 后续重订，不阻塞 v1 的 admin-only 交付判断。

#### Scenario: test-cn admin 验收
- **WHEN** test-cn 部署完成且 admin 登录 OMS
- **THEN** admin 能按本地 `ops.*` 权限访问 v1 范围内后台功能，并且无权或未纳入 v1 的功能明确失败关闭或显示未启用
