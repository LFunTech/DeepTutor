## Purpose
EduPlus2 权威租户状态通过可信 webhook 进入 DeepTutor，决定租户级准入；OMS 仅查询脱敏状态，不写开停。逐服务额度准入归 OMS 独立业务总账。

## ADDED Requirements
### Requirement: 租户状态事件必须认证、持久化、按版本处理
系统 SHALL 验证 EduPlus2 签名、时间戳、明确的订阅生命周期事件类型和租户/应用绑定，先持久化再确认；重复事件幂等，旧版本不得覆盖新版本，同版本冲突须拒绝。恢复事件 MUST NOT 进入仅设置撤销的处理器；OMS 额度耗尽 MUST NOT 生成 `subscription.suspended`、旧 `tenant.suspended` 或旧欠费模型资格事件。仅用于控制台 URL 联调的已验签 mock 事件 MUST NOT 改变业务状态；真实事件未具备持久化与版本处理能力时不得成功确认。
#### Scenario: 乱序恢复与停机
- **WHEN** 较新的恢复事件先于旧停机事件到达
- **THEN** 旧停机事件被标记过期，不再次停机
#### Scenario: 伪签名或错误租户
- **WHEN** 无效签名或目标外部租户无法绑定
- **THEN** 系统拒绝且不更新业务状态

### Requirement: DeepTutor 必须在所有新业务准入入口执行外部状态
系统 SHALL 对新登录、token exchange、新 HTTP/WS turn、下载授权和后台派发检查 EduPlus2 外部租户资格、本地启停与资源就绪的交集；OMS MUST NOT 改写权威状态。历史会话、审计、用量与资源保留。某服务额度耗尽不得触发本要求的全入口停用。
#### Scenario: 停机生效
- **WHEN** 有效停机 webhook 提交成功
- **THEN** 新业务准入被拒绝，历史只读数据仍可按授权查询
#### Scenario: 恢复但本地隔离
- **WHEN** 外部恢复而本地恢复隔离仍存在
- **THEN** 不允许新业务准入

### Requirement: 漏送事件必须可对账
系统 SHALL 使用受控 EduPlus2 权威快照与租户状态版本对账；外部资格无法确认时按现有租户级准入 fail closed，不从 OMS 配额推断外部状态。
#### Scenario: webhook 丢失
- **WHEN** 对账发现外部版本高于本地
- **THEN** 原子更新状态、留审计并使权限缓存失效

### Requirement: 服务额度不足不得改变租户生命周期
系统 SHALL 将 OMS 服务授权、额度和供给作为独立逐服务新调用准入，MUST NOT 因某服务额度不足改写 EduPlus2 外部租户资格、本地启停、撤销状态或既有会话；登录、授权管理、历史查询及其他仍获授权的服务继续可用。业务错误和运营状态 MUST 与“租户停用”明确区分。

#### Scenario: 单服务额度耗尽
- **WHEN** 租户 lifecycle 有效而图像服务额度耗尽
- **THEN** 登录、管理、历史和其他服务保持可用，图像服务新调用返回明确的额度错误
- **AND** 不生成 `subscription.suspended`、旧 `tenant.suspended`、模型资格事件或会话撤销

#### Scenario: 管理操作触发已耗尽服务
- **WHEN** 租户在保存知识库配置后请求依赖已耗尽 embedding 服务的索引任务
- **THEN** 配置管理仍可用，embedding 子调用在执行前被拒并清晰标记服务额度原因，不伪报整个租户停用

#### Scenario: 补充额度但租户仍暂停
- **WHEN** OMS 补充某服务额度，而 EduPlus2 租户状态仍为 suspended
- **THEN** 仍不得发起受暂停限制的新业务调用，补额度不能覆盖租户停用

#### Scenario: 外部资格快照过期
- **WHEN** EduPlus2 租户资格快照已过期且尚未完成对账
- **THEN** 按现有租户级失联策略拒绝新业务准入并告警，OMS 不以配额状态代替外部资格
