## Purpose
定义 OMS 以 DeepTutor 真实 Token 用量计算费用、限制供应商成本可见性、并将欠费处理交由 EduPlus2 权威确认的契约。

## ADDED Requirements

### Requirement: 费用必须来自真实已核算 Token 与历史有效价格
系统 SHALL 仅对真实 provider usage 已结算的逐调用 `total_tokens`，按调用时有效的租户每百万 Token Decimal 单价计算费用并绑定价格版本。系统 MUST 按 tenant/user/call 关联明细；缺 usage 或价格时 MUST 标为待核算而非零费用，价格后来变更 MUST NOT 静默改变旧费用。

#### Scenario: 价格更新不影响历史费用
- **WHEN** 一次调用已经以旧版价格结算，随后运营人员设置新单价
- **THEN** 历史调用保留旧价版本和金额，新调用依新生效时间选价

#### Scenario: 供应商流未返回 usage
- **WHEN** 调用中断且没有可核验的最终 usage
- **THEN** 明细显示待核算，已核算费用合计不包含该调用

### Requirement: 成本拆分只能在授权 OMS 中展示
系统 SHALL 以独立版本化 provider/model 成本价格和可信用量单位计算供应商成本；缺价格、单位或汇率时 MUST 显示待核算。成本和毛利 MUST 仅对具有 `ops.billing.cost.read` 的平台主体通过 OMS 显示，不得进入 TMS、租户/用户响应或普通导出。

#### Scenario: 运营审计员无成本权限
- **WHEN** platform_auditor 查询租户用量或费用
- **THEN** 后端响应不包含成本价、成本金额或毛利字段

### Requirement: 计费写操作必须逐动作鉴权和审计
系统 SHALL 区分费用读取、租户单价管理、成本价管理、欠费处置，要求 `ops.billing.manage` 与对应 action 权限共同授权，并记录操作者、时间、原因及前后版本。tenant_admin 与普通用户 MUST NOT 通过租户身份获得平台计费写权限。

#### Scenario: 欠费处理者尝试改成本价
- **WHEN** 仅获欠费处置授权的 platform_operator 提交成本价更新
- **THEN** 后端拒绝且原价格版本不变

### Requirement: 欠费只能限制模型使用且必须由 EduPlus2 webhook 确认
OMS MAY 记录欠费及向 EduPlus2 发出幂等**模型资格**处置请求，但 MUST NOT 改变 DeepTutor 租户生命周期、`local_enabled`、用户身份或已有会话。模型限制/恢复 SHALL 仅以已验签、按独立版本处理的 EduPlus2 模型资格 webhook 为准；请求未获确认时显示待外部确认，超时/拒绝进入需处理状态。受限时系统 MUST 仅拒绝该租户新发起的实际模型调用，MUST 保持登录、授权管理、历史查询和纯非模型操作可用。

#### Scenario: 发送限制请求但未收到权威事件
- **WHEN** OMS 发起欠费模型限制请求且 EduPlus2 尚未发送有效模型资格 webhook
- **THEN** 模型资格显示待外部确认，DeepTutor 不得仅凭 OMS 请求拒绝模型调用

#### Scenario: 模型限制已生效
- **WHEN** 欠费模型资格受限事件生效且租户仍正常启用
- **THEN** 新的 LLM、embedding、语音、图像/视频等模型调用被拒并返回明确业务原因
- **AND** 用户仍可登录、管理、查看历史与账务、执行不调用模型的操作

#### Scenario: 欠费结清并恢复模型资格
- **WHEN** 已验签的模型资格恢复事件提交成功且租户未因其他原因停用
- **THEN** 新模型调用可恢复，既有登录/管理会话无需重新开通

#### Scenario: 重复或乱序确认
- **WHEN** 同一请求收到重放或旧版本 webhook
- **THEN** 不重复改变状态或费用，保留异常/重放审计
