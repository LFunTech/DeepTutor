## Purpose

规定 DeepTutor 在不实现 TMS/OMS、暂不要求实时撤权传播的前提下，与 EduPlus2 建立第三方联邦访问闭环：通过 EduPlus2 user JWT 静默换取短期 `dt_token`，并在 exchange、refresh、打开/新命令/周期安全检查点持续依赖 EduPlus2 resolve、profile、permission 和 DeepTutor owner/resource guard 控制访问；同时提供最小审计查询/导出 UI，确保调用可追溯、可按校验窗口撤销、可脱敏导出。

## ADDED Requirements

### Requirement: EduPlus2 作为普通用户与租户身份权威

系统 SHALL 不提供普通用户注册、学校/组织创建、密码找回或账号生命周期管理；这些能力由 EduPlus2 完成。系统 MAY 对已通过校验的外部身份执行内部 identity binding / JIT provisioning，但不得暴露为用户自助注册入口，也不得授予超出外部身份、client/app 策略、EduPlus2 权限和本地 grant 的权限。

#### Scenario: 普通用户尝试本地注册
- **WHEN** 普通用户或第三方应用调用当前系统注册、开户、找回密码或创建学校/组织的入口
- **THEN** 系统拒绝或引导至 EduPlus2，不创建本地账号凭证、不生成可登录身份、不绕过 EduPlus2 生命周期

#### Scenario: 首次合法访问创建内部映射
- **WHEN** EduPlus2 JWT、resolve、profile、permission、client registration 和本地授权均验证通过，但内部尚无对应 identity binding
- **THEN** 系统可幂等创建内部映射和审计记录；该映射只服务授权和资源归属，不代表本地注册能力

### Requirement: 本 change 不交付 TMS/OMS 但交付联邦访问闭环

系统 SHALL 不在本 change 范围内开放 `/tms`、`/oms` 页面、Handoff/OIDC callback 或 TMS/OMS client 管理面。系统 SHALL 在无 TMS/OMS 的前提下交付第三方 exchange、profile/permission 复核、WS refresh、前置应用合法性校验和最小审计导出 UI；实时撤权推送与复杂事件对账不作为本 change 门禁。

#### Scenario: 第三方应用调用换票入口
- **WHEN** 第三方应用携带 EduPlus2 user JWT 调用 `POST /api/v1/auth/eduplus2/exchange`
- **THEN** 系统静默完成 token exchange 或返回明确认证/授权错误，不展示当前系统登录页、不要求用户重复输入凭证

#### Scenario: 请求 TMS/OMS 管理能力
- **WHEN** 调用方请求 `/tms`、`/oms` 或 TMS/OMS client 注册管理能力
- **THEN** 系统不得因本 change 自动放行；未由后续 proposal 实现并授权前应保持未启用或 fail closed

### Requirement: 配置和密钥边界可审计且不泄露 secret

系统 SHALL 通过环境配置、Secret Provider 或 `.secrets` 注入 EduPlus2 discovery、issuer、JWKS、token endpoint、resolve endpoint、M2M client id/secret ref、allowlist、refresh TTL 和 `dt_token` TTL。若启用可选 profile/permission 增强，还 SHALL 注入 profile endpoint、permission endpoint；若启用可选 webhook，还 SHALL 注入 revocation webhook secret/ref。明文 client secret、M2M token、EduPlus2 user JWT、refresh proof 和 `dt_token` MUST NOT 写入业务表、OpenSpec、普通日志、审计正文或响应。

#### Scenario: 配置缺失或 secret 不可读取
- **WHEN** 必需 endpoint、issuer、allowlist、profile/permission 配置或 Secret Provider 配置缺失
- **THEN** 相关 exchange/refresh/周期校验/export fail closed，并返回脱敏错误；不得回退到本地注册、本地登录或未校验 token 路径

### Requirement: EduPlus2 user JWT 必须由 OIDC/JWKS 验证

系统 SHALL 使用 EduPlus2 discovery/JWKS 验证第三方传入的 user JWT，校验签名、`iss`、`exp`、`iat`、`nbf` 和必要 claims：`tid`、`eui`、`sub`、`azp`。`azp` SHALL 作为 OAuth client id 主校验项；`aud` MAY 作为兼容或附加校验，但不得替代 `azp`。

#### Scenario: JWT 无效或缺少 `azp`
- **WHEN** JWT 篡改、`kid/alg` 不受信、issuer 不匹配、过期、`iat/nbf` 不合法，或缺少 `tid/eui/sub/azp`
- **THEN** 系统拒绝 exchange/refresh，并不得用 `aud`、body、query 或 header 中的 client/tenant/user 替代主校验

### Requirement: resolve API 是 client/app/tenant/status/policy 权威来源

系统 SHALL 使用 EduPlus2 `POST /api/v1/open/oauth-clients/resolve` 按 `client_id` 获取 client/app/tenant/oauth/policy/status 权威信息。只有 resolve 返回 verified 且 client/app/tenant/subscription/policy 状态允许时，系统才可继续 exchange/refresh。resolve 调用 MUST 使用 M2M token、超时、短缓存、错误规范化和脱敏日志。

#### Scenario: resolve 失败或状态不可用
- **WHEN** resolve 返回 unknown、tenant mismatch、inactive/revoked、policy 不允许，或 EduPlus2 token/resolve endpoint 不可用且无允许的短缓存
- **THEN** 系统拒绝 exchange/refresh，记录脱敏 reason，不签发或续期 `dt_token`

### Requirement: 仅允许受控预注册或白名单 client 换票

系统 SHALL 只允许受控导入、配置 allowlist 或 allowlist 命中后自动 upsert 的 EduPlus2 client 参与 exchange。active `client_id` MUST 全局唯一；active `(provider, external_tenant_id, external_app_id)` MUST 全局唯一。自动 upsert MUST 要求 allowlist expected tenant/app 与 resolve 结果一致。

#### Scenario: client 未白名单或 registration inactive
- **WHEN** JWT `azp` 未在 allowlist/registration 中，或 registration 为 suspended、revoked、pending_verification
- **THEN** 系统拒绝 exchange，不尝试自助注册或用第三方请求字段覆盖 registration 状态

### Requirement: Profile API 必须复核外部用户状态

系统 SHALL 在 exchange 和 refresh 时调用或使用短 TTL 缓存的 EduPlus2 profile API，校验 profile 的 external user、subject、tenant、identity type 和状态与 JWT/registration/resolve 一致。系统 SHALL 只保存最小脱敏 profile snapshot，不保存不必要隐私字段。

#### Scenario: profile 有效
- **WHEN** profile API 返回 active 用户，且 `tid/eui/sub` 与 JWT 和注册上下文一致
- **THEN** 系统可更新 profile snapshot、identity binding 摘要和审计，然后继续 exchange/refresh

#### Scenario: profile 不可用或不匹配
- **WHEN** profile API 不可用、用户 disabled/deleted/inactive，或 profile tenant/user/subject 与 JWT 不一致
- **THEN** 系统拒绝 exchange/refresh，不创建或续期内部会话，并记录脱敏 reason

### Requirement: 权限 API 必须限定普通能力边界

系统 SHALL 在 exchange、refresh 和敏感操作前根据 EduPlus2 permission API 或短 TTL permission snapshot 校验用户在当前 client/app/tenant 下是否允许使用 DeepTutor 普通能力。权限 API 结果 MUST NOT 自动授予 TMS/OMS/ops 管理能力，也不得绕过 DeepTutor owner/resource guard。

#### Scenario: 权限允许普通能力
- **WHEN** permission API 返回允许当前 usage，且版本/TTL 有效
- **THEN** 系统可签发或续期普通能力 `dt_token`，并保存 permission snapshot 和审计

#### Scenario: 权限拒绝或撤销
- **WHEN** permission API 返回 denied/revoked、版本过期，或调用不可用且无允许短缓存
- **THEN** 系统拒绝 exchange/refresh/新敏感操作，不得继续使用旧 permission snapshot 扩权

### Requirement: JWT exchange 签发短期 `dt_token` 且不返回 refresh token

系统 SHALL 在 JWT、allowlist/registration、resolve、profile、permission、tenant/app/client/policy 全部验证通过后，幂等创建或读取内部 identity binding 和 auth session，并签发短期 `dt_token`。响应 MUST 只包含最小必要字段，不得返回 EduPlus2 token、raw JWT claims、DeepTutor refresh token、client secret 或私密正文。

#### Scenario: tenant 不匹配
- **WHEN** JWT `tid` 与 allowlist expected tenant、registration tenant、resolve tenant、profile tenant 或 permission tenant 任一不一致
- **THEN** 系统拒绝 exchange，禁止 JIT binding，并记录 `tenant_mismatch` 类 reason

### Requirement: WS refresh 必须重验外部状态且不扩大授权

系统 SHALL 支持短期 `dt_token` 的 WS refresh。服务端 SHOULD 在 token 即将过期时发送 `auth_expiring`；客户端 MAY 通过 `auth_refresh` 提交新的 EduPlus2 user JWT 或新 `dt_token`。refresh MUST 重验 JWT、registration、resolve、profile、permission、auth session 和连接 owner 上下文。

#### Scenario: 长对话 refresh 成功
- **WHEN** WS token 即将过期，客户端提交新的有效证明且外部状态仍允许
- **THEN** 系统返回 `auth_ack`，更新连接认证上下文，后续命令使用新身份且权限不扩大

#### Scenario: refresh 失败或过期后提交新命令
- **WHEN** 新证明无效、外部状态被撤销、permission denied 或 refresh deadline 已过
- **THEN** 系统拒绝新 turn/reply/cancel/订阅/下载/敏感工具操作，必要时发送 `auth_revoked` 或断开连接

### Requirement: 前置应用合法性校验必须覆盖新操作、WS 和缓存

系统 SHALL 在 exchange、refresh、HTTP/WS/SDK 打开或新敏感操作、以及后台任务安全检查点重验当前 user/client/app/tenant/subscription/permission 是否仍合法。系统 SHALL 使用短 TTL profile/permission/resolve snapshot；当 snapshot 超过配置窗口时 MUST 重新调用 EduPlus2 profile/permission/resolve。实时 webhook/事件传播 MAY 作为增强能力启用，但不作为本 change 的生产门禁。

#### Scenario: 打开或周期校验发现权限失效
- **WHEN** 用户打开 DeepTutor、WS 提交新命令、HTTP/SDK 执行敏感操作、或后台任务到达安全检查点，且 profile/permission/resolve 重验发现用户、client/app/tenant/subscription/permission 不再合法
- **THEN** 系统拒绝新 exchange/refresh/敏感操作；活跃 WS 在下一次新命令或 refresh 时收到错误或被关闭；后台任务 fail closed

#### Scenario: snapshot 超过周期校验窗口
- **WHEN** 本地 profile/permission/resolve snapshot 已超过配置的周期校验窗口
- **THEN** 系统重新调用 EduPlus2 profile/permission/resolve；调用不可用且无仍在 TTL 内的安全缓存时 fail closed

#### Scenario: 可选撤权事件重放或签名错误
- **WHEN** 部署启用 webhook，且 webhook 签名错误、timestamp 过期、event id 重放或目标环境不匹配
- **THEN** 系统拒绝事件，不改变授权状态，并记录安全审计

### Requirement: 后续 HTTP/WS/SDK 访问必须经过 tenant scope 与 owner/resource guard

系统 SHALL 将 exchange/refresh 得到的内部 tenant/user/session/client registration/profile/permission 上下文用于后续 HTTP/WS/SDK 鉴权。租户成员身份或 EduPlus2 登录成功 MUST NOT 自动授予个人 session、memory、notebook、artifact/source 或敏感工具访问权；访问仍需 owner、显式 grant 或对应 resource guard 通过。

#### Scenario: 同租户但非 owner 访问私有资源
- **WHEN** 同一租户内另一个用户仅凭 EduPlus2 成员身份访问他人的私有会话、记忆、笔记或 artifact
- **THEN** 系统拒绝访问，不把租户成员或 tenant_admin 身份等同于个人内容授权，并记录脱敏 authz denied 审计

### Requirement: 审计记录和导出 UI 必须可追溯且脱敏

系统 SHALL 对 resolve、profile、permission、registration upsert、token exchange、refresh、周期合法性重验、可选 revocation、权限拒绝、敏感能力调用和 audit export 记录持久审计。系统 SHALL 提供不依赖 TMS/OMS 的最小审计查询/导出 UI，并强制租户范围、权限、脱敏和导出审计。

#### Scenario: 查询审计
- **WHEN** 有权限用户打开最小企业审计页面并按时间/client/user/result 过滤
- **THEN** 系统只返回该用户被授权范围内的脱敏审计记录，不包含 raw token、secret、完整 profile、私密正文或上游敏感响应

#### Scenario: 导出审计
- **WHEN** 有权限用户发起 CSV/JSONL 导出
- **THEN** 系统创建导出 job、输出脱敏文件引用、记录导出审计；无权限或跨租户导出请求被拒绝

### Requirement: 实现形态保持 upstream 可合并

系统 SHALL 将 EduPlus2 verifier、resolve/profile/permission client、registration、exchange、refresh、周期合法性重验、可选 revocation、audit export 和 allowlist 逻辑放在企业扩展包或明确 provider 实现中；core 只新增最小必要 seam。实现 MUST NOT 复制上游大文件、依赖全局 monkey patch、改变本地默认行为或把 EduPlus2 业务硬编码进教学内核。

#### Scenario: 未启用 EduPlus2 的本地模式运行
- **WHEN** 未启用企业 EduPlus2 provider 的本地 CLI/SDK/Web 运行
- **THEN** 不需要 EduPlus2 配置即可保持既有本地行为；企业功能缺依赖时 fail closed，而不是修改上游默认路径
