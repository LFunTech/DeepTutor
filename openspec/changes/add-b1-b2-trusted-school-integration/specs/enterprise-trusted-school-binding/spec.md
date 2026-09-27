## Purpose

规定智能体基座消费既存 EduPlus2 身份、账号和学校权威时，如何将首所学校及其用户安全绑定到内部稳定标识，并使所有新业务操作受当前学校状态与撤权约束。

## ADDED Requirements

### Requirement: 外部证明必须先于内部绑定

系统 SHALL 只在已核实的 EduPlus2 OIDC/JWKS、client/app resolve、本人状态及权威学校归属一致时建立或续用 `(issuer,subject,external-school-id)` 到内部稳定学校/用户 ID 的绑定。外部 ID 类型和学校状态 SHALL 以已交付接口实测合同为准；学校码、显示名称、JWT role、`eit=adm`、请求参数或 Webhook mock MUST NOT 单独创建绑定或授予管理能力。缺外部合同或接口失败时，新绑定和敏感写入 MUST 失败关闭。

#### Scenario: 首所学校合法登录
- **WHEN** 用户证明、client/app、本人账号状态及学校权威 ID 均有效且与受控登记的首所学校一致
- **THEN** 系统幂等绑定稳定内部 ID，并只签发该用户该学校的普通会话；管理权限仍为零，另由本产品权限检查决定

#### Scenario: 学校码或外部 ID 不一致
- **WHEN** URL 学校码、客户端租户参数、JWT `tid`、client resolve、本人归属或权威学校绑定不一致
- **THEN** 系统拒绝登录/换票及新敏感操作，不合并同名账号、不改写已有资源归属

### Requirement: 绑定变更必须版本化且可撤权

系统 SHALL 将内部学校与外部权威学校 ID 的有效绑定、状态、证据版本及撤权栅栏持久化；创建、改码、解绑和重新绑定 SHALL 有唯一约束、预期版本、幂等和审计。既有已应用迁移 MUST NOT 原位修改；真实旧数据不得在迁移中推断归属或自动迁入。

#### Scenario: 旧会话遇到解绑
- **WHEN** 学校绑定已撤销或版本改变，旧会话、WS 连接或后台任务继续发起新操作
- **THEN** 系统拒绝该操作并要求重新取得可信身份，不通过短缓存、旧学校码或本地管理员身份恢复授权

### Requirement: 普通能力与管理会话不得互用

普通第三方 `dt_token` SHALL 只代表其已验收的普通用户能力；独立 OMS/TMS 管理会话及其应用权限由管理授权契约核验。任何普通用户 token、学校角色标签或首所学校绑定 MUST NOT 自动签发 OMS/TMS 会话或授权 `ops.*`、`tenant.*`。

#### Scenario: 学校管理员标签请求 OMS
- **WHEN** 仅持普通换票令牌或 `tenant_admin` 标签的请求调用 OMS/TMS 管理写 API
- **THEN** 请求被拒绝，且不创建平台主体、学校管理员授权或审批记录

### Requirement: B1 全入口在当前状态下复核

系统 SHALL 在 token exchange、HTTP/WS 新 turn、敏感读取/下载、SDK 与后台派发的适用检查点，复核可信内部学校/用户 scope、外部学校状态、当前绑定和本地隔离；owner/显式 grant 继续独立执行。已接受的 turn 的自然 token 到期处理 SHALL 遵循现有 WS 契约，但不得让撤权后的新命令、新下载或新任务继续执行。

#### Scenario: 用户或学校失效
- **WHEN** 外部账号停用、学校暂停、绑定撤销或本地隔离在旧 token 有效期内生效
- **THEN** 新 HTTP/WS/SDK 敏感操作及后台派发拒绝；个人私有资源不会因学校成员身份或管理员名称而对其他用户开放

### Requirement: B1 放行必须有真实首校闭环证据

系统 SHALL 在指定测试学校用既存已交付接口完成登录→普通换票→HTTP/WS turn→资源访问→重新登录/撤权及第三方应用用户 JWT→`dt_token` 的正负例；隔离合成测试和签名 Webhook demo 只能作为单元/连通性证据，不能替代真实账号、学校及撤权验证。未经该门禁不得开放第二所真实学校。

#### Scenario: 仅有 Webhook mock 成功
- **WHEN** 环境仅有 8/8 签名 mock 204 或合成 JWT 测试，而没有真实首校及撤权闭环
- **THEN** B1 保持未验收，B2 多学校放量保持关闭
