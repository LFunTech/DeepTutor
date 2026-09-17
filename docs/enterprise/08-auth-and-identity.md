# 08. 认证与身份对接方案

## 阶段边界

阶段一保留已有受保护本地认证，将账号/凭证 hash 与会话状态持久化到 PG，服务器绑定固定内部 tenant；不依赖 EduPlus2 上线。EduPlus2 app 注册、测试账号和契约准备与 A1/A2 并行；以下最终入口先在 B1 完成一个真实租户的登录/权限/撤权闭环，B2 再开放多个租户，不采用“先登录后补权限”的放行模式。阶段二正常租户登录统一走 EduPlus2；本地认证如保留仅限审计化平台应急入口，不能成为租户绕过停用/撤权的旁路。普通用户注册、学校/组织归属和账号生命周期不在 DeepTutor 中实现，均由 EduPlus2 负责。

外部 tid/eui 经 [03 身份映射](03-tenant-scope-schema.md) 转换内部 tenant_id/user_id；原单租户账号只显式绑定，不按同名自动合并。DeepTutor 可在首次合法访问时做 identity binding / JIT provisioning（创建内部映射和会话），但这不是注册入口，也不能让用户自行创建 EduPlus2 账号或租户。

### 当前实现状态（2026-09-17）

已归档的 [`enterprise-eduplus2-federated-access`](../../openspec/specs/enterprise-eduplus2-federated-access/spec.md) 覆盖的是**无 TMS/OMS 的 API-only 联邦访问闭环**：第三方应用持有 EduPlus2 user JWT 后调用 DeepTutor exchange，DeepTutor 验签、resolve、allowlist/registration、JIT binding 并换发短期 `dt_token`，后续 HTTP/WS/SDK 仍走 DeepTutor 自身 token、owner/resource guard 和审计。该切片还提供通用 WS `auth_refresh` seam、可选 profile/permission/webhook 增强以及独立审计导出 UI。

尚未实现的是 `/tms`、`/oms` 的 EduPlus2 交互式登录、Handoff/OIDC callback、在线 client 治理页面和实时撤权 SLA。打开 DeepTutor、refresh 时用户合法性校验以及周期合法性校验由前置应用负责；当前 repo 不把这些周期检查作为自身后台任务实现。

## 身份与登录边界

DeepTutor 不作为用户身份主系统：

- **不提供普通用户注册**：注册、开户、学校绑定、身份分配、停用和撤权均在 EduPlus2 完成。
- **只有 TMS/OMS 需要 DeepTutor 登录入口**：`/tms` 面向租户管理员，`/oms` 面向平台运营/审计人员；两者登录均对接 EduPlus2。
- **普通第三方应用调用不再次登录**：用户已经在前置业务系统或 EduPlus2 完成登录时，调用方只传递 EduPlus2 user JWT，DeepTutor 静默验签/换发短期 `dt_token`。
- **DeepTutor 只负责资源服务职责**：验证外部身份结果、建立内部 tenant/user/app 映射、执行能力与资源授权、记录审计和追踪。

## EduPlus2 认证入口（TMS/OMS 直接登录）

EduPlus2 支持 OAuth2/OIDC，并提供工作台 Handoff。DeepTutor 作为 EduPlus2 工作台应用时，推荐优先支持 Handoff。该入口仅用于 `/tms`、`/oms` 等需要 DeepTutor 自身交互式登录的管理界面，不用于普通第三方应用对 DeepTutor 能力的后台调用：

1. 用户从 EduPlus2 工作台点击 DeepTutor 应用。
2. EduPlus2 跳转到 DeepTutor，并带上 `eduplus_handoff_code` 和 `eduplus_state`。
3. DeepTutor 后端使用自身应用的 `client_secret`（运行时从 Secret Provider 读取 `secret_ref`）对 handoff code 请求签名。
4. DeepTutor 调用 EduPlus2 `/api/v1/app-handoff/token` 换取 token。
5. DeepTutor 校验 token，调用 `/api/v1/me/profile` 获取业务态。
6. DeepTutor 生成自己的短期 `dt_token`，供现有 API 和 WebSocket 使用。

参考：

- <https://eduplus-test.f123.pub/docs/oauth-oidc/>
- <https://eduplus-test.f123.pub/docs/oauth-oidc/workbench-handoff/>
- <https://eduplus-test.f123.pub/docs/oauth-oidc/jwt-verification/>

## 为什么不直接使用 EduPlus2 access token 作为 DeepTutor session

推荐 DeepTutor 换发自己的 `dt_token`：

1. 可以兼容现有 `require_auth()` / `ws_require_auth()`。
2. 可以把 EduPlus2 claims 映射成 DeepTutor 需要的 `role/scope`。
3. 可以控制 DeepTutor session 生命周期和 cookie 参数。
4. 可以避免前端长期处理 EduPlus2 refresh token。
5. 可以在 token 中写入最小必要的租户上下文。

EduPlus2 access token / refresh token 应只在后端处理，不写入普通前端可读存储。

## 被调用方模式：第三方应用已登录用户的静默换票

当 DeepTutor 作为被调用方对外开放能力时，不要求用户再次进入 DeepTutor 登录页：

1. 用户在第三方应用完成 EduPlus2 登录。
2. 第三方应用调用 DeepTutor `POST /api/v1/auth/eduplus2/exchange`，在 `Authorization: Bearer <eduplus2_user_jwt>` 中传递 EduPlus2 user JWT。
3. DeepTutor 使用 EduPlus2 JWKS 或受保护校验接口验证 JWT 签名和 claims，禁止信任 body/query/header 中未验签的 `tenant_id/user_id`。
4. DeepTutor 提取 `tid/eui/azp` 等信息，将 JWT `azp` 作为权威 `client_id`，查找已注册且 active 的外部 client/app 记录；`aud` 可做兼容校验或记录，但第三方调用不依赖 `aud` 作为主校验项。
5. DeepTutor 校验 JWT `tid` 与 client 注册记录的外部租户完全一致，校验 app、tenant、client 未暂停/撤销，并结合 EduPlus2 返回的权威应用与租户信息判断来源合法。
6. DeepTutor 将 `(provider, tid, eui)` 映射为内部 `(tenant_id, user_id)`，记录 `client_id/external_app_id/external_app_name/external_tenant_name` 作为审计上下文。
7. DeepTutor 静默换发短期 `dt_token`，第三方前端/SDK 后续用该 token 调用 HTTP/WS。

建议换票响应包含：`access_token`、`expires_in`、`tenant_id`、`user_id`、`client_id`、`app_id`、`app_name`、`tenant_name`。用户不感知该过程，不出现 DeepTutor 二次登录页面。

## Client ID / Client Secret 使用边界

`client_id` 是必需的，用于判断调用来源、应用是否已获准访问目标租户、策略匹配和审计归属。`client_secret` 不应成为普通第三方调用 DeepTutor 的默认依赖：

- **JWT 本地验签通常不需要第三方 `client_secret`**：需要的是 EduPlus2 issuer、JWKS、JWT `azp`、租户/app 注册记录和状态；`aud` 只做兼容或附加校验，不作为第三方调用主依赖。
- **需要 `client_secret` 的场景**：DeepTutor 自身作为 EduPlus2 应用执行 Handoff/OIDC code 换 token、token introspection、refresh token、M2M 管理 API 或其他受保护 EduPlus2 API。
- **默认不保存第三方应用的 `client_secret`**：如必须保存 DeepTutor 自身 secret，只保存 `secret_ref`，明文进入 Secret Provider，不落业务表或日志。
- **Webhook 不是登录主链路**：Webhook 可用于应用安装、租户授权、client 配置变更、secret 轮换或状态同步，但每次登录/换票仍必须以实时 token 校验和注册状态为准。

## EduPlus2 claims 使用规则

EduPlus2 access token 中关键 claims：

| claim | 含义 | DeepTutor 使用方式 |
| --- | --- | --- |
| `tid` | EduPlus2 外部租户 ID | 映射为 DeepTutor 内部 `tenant_id` |
| `eui` | EduPlus2 用户 ID | 保存外部 ID，映射为 DeepTutor 内部 `user_id` |
| `eit` | 当前激活身份类型，如 `stu/tch/par/adm` | feature mode 和初步 role mapping |
| `sub` | Keycloak 用户 UUID | 外部认证主体 ID，可用于审计 |
| `azp` | OAuth client id / authorized party | TMS/OMS 登录时校验是否为 DeepTutor 自身 client；第三方调用时校验是否匹配已注册外部 client/app |
| `aud` | token 受众 | 可做兼容或附加校验；第三方调用场景以 `azp` 作为 client id 主校验项 |
| `ees/eei` | 外部身份来源/外部用户 ID | 可用于展示或调试，不作为主键 |

注意：业务态和权限列表不应从 token roles 推断。需要调用 `/api/v1/me/profile` 和权限 API。

## DeepTutor dt_token payload 建议

```json
{
  "sub": "<internal-user-id>",
  "uid": "<internal-user-id>",
  "tenant_id": "<internal-tenant-uuid>",
  "role": "tenant_admin",
  "auth_provider": "eduplus2",
  "tid": "1",
  "eui": "12345",
  "eit": "adm",
  "school_code": "SCHOOL-001",
  "k_user_id": "keycloak-user-uuid",
  "azp": "deeptutor-client-id-or-external-client-id",
  "client_id": "eduplus2-client-id",
  "client_registration_id": "external-client-registration-id",
  "external_app_id": "eduplus2-app-id",
  "external_app_name": "Alpha App",
  "external_tenant_name": "A School",
  "exp": 1234567890,
  "iat": 1234560000
}
```

`role` 映射规则见 [09-authorization-and-grants.md](09-authorization-and-grants.md)。

## 企业包服务模块建议

实现位于独立包而非上游 `deeptutor/` 内；目标布局如下（拟新增），装配和通用 hook 见 [13](13-deployment-and-upstream-sync.md)：

```text
extensions/enterprise/src/deeptutor_enterprise/integrations/eduplus2/
  config.py       # issuer、client_id、client_secret、base_url、enabled
  client.py       # HTTP client，token 缓存、重试、错误规范化
  jwt.py          # JWKS 获取、签名和 claims 校验
  verifier.py     # JWT/introspection 统一校验、issuer/azp/aud 兼容策略
  handoff.py      # Handoff 签名、code 换 token
  token_exchange.py # EduPlus2 user JWT -> DeepTutor dt_token
  client_registry.py # 外部 client/app 注册、状态、唯一性校验
  profile.py      # /api/v1/me/profile 调用和缓存
  mapping.py      # EduPlus2 profile/JWT -> TokenPayload/CurrentUser
  refresh.py      # WS/HTTP 短期 dt_token 刷新与 session 绑定
```

新增路由：

```text
extensions/enterprise/src/deeptutor_enterprise/api/eduplus2.py
```

通过企业应用 factory/启动器注册 router，核心 `require_auth/ws_require_auth` 只增加 provider-aware 身份/通用授权 seam，不内嵌大量 EduPlus2 业务。自有 cookie/token 需要相应 verifier/provider 实际支持新增字段，不能仅在外部签一个 token 就假定原生解码保留 tenant 或新角色。企业入口必须关闭未适配本地 auth/admin 旁路；代理头只能由可信组件产生且不能替代每 turn/敏感操作重验。

候选接口：

```text
GET  /api/v1/eduplus2/handoff/callback
POST /api/v1/auth/eduplus2/exchange
POST /api/v1/eduplus2/logout
GET  /api/v1/eduplus2/session
```

## Token 校验要求

DeepTutor 后端校验 EduPlus2 JWT 时至少检查：

1. signature：使用 EduPlus2 JWKS。
2. `iss`：必须匹配 EduPlus2 issuer。
3. `azp` / `client_id`：TMS/OMS 登录匹配 DeepTutor 自身应用配置；第三方调用以 JWT `azp` 作为权威 client id，匹配已注册 active client/app 及 EduPlus2 通用 resolve API 返回；`aud` 仅做兼容或附加校验。
4. `exp` / `iat`：过期和时间偏移。
5. `tid/eui/eit`：EduPlus2 模式下必须存在；`tid` 必须等于注册记录的 `external_tenant_id`。
6. `nonce/state`：Handoff / OAuth callback 防重放。
7. app/tenant/client 状态：注册记录、租户绑定、本地启停和外部资格均有效。

## Cookie 策略

DeepTutor `dt_token` 建议：

- `HttpOnly=true`
- `Secure=true`，本地开发可配置关闭
- `SameSite=Lax` 或按 EduPlus2 工作台嵌入场景调整
- Path 限制为 DeepTutor 应用路径

如果 DeepTutor 作为 iframe/嵌入式应用运行，需要单独评估第三方 cookie、SameSite=None、CSRF 和 postMessage 安全策略。

## `dt_token` 有效期与 WS 静默刷新

`dt_token` 推荐短 TTL（15–30 分钟）并在剩余 3–5 分钟时刷新。已经被服务端接受的单个 `start_turn` 不应因为 token 在生成过程中自然到期而中断；但新 turn、cancel、`submit_user_reply`、订阅新 turn、下载 artifact/source、读历史和敏感工具操作必须重新校验。

推荐 WS 刷新协议：

1. server 向 client 发送 `auth_expiring`。
2. client 通知宿主第三方应用获取新的 EduPlus2 user JWT。
3. client 调 `POST /api/v1/auth/eduplus2/exchange` 换取新的 `dt_token`。
4. client 通过 WS 发送 `auth_refresh(new_dt_token)`。
5. server 重验身份、租户、client/app 状态和 session owner 后返回 `auth_ack`。

备用恢复路径是使用新 `dt_token` 重连 WS，并通过 `resume_from turn_id + after_seq` 恢复事件流。刷新过程对最终用户透明。

## Logout

推荐流程：

1. DeepTutor 清理本地 `dt_token`。
2. 如需单点登出，跳转 EduPlus2 logout endpoint。
3. 不在日志中打印 access token、refresh token、handoff code、client secret。

## 错误处理

| 场景 | DeepTutor 行为 |
| --- | --- |
| handoff code 缺失 | 返回 400，并提示从 EduPlus2 工作台重新进入 |
| 签名失败/换 token 失败 | 返回 401/502，记录脱敏错误 |
| JWT 校验失败 | 返回 401 |
| 缺少 `tid/eui` | 返回 401，标记为 invalid identity assertion |
| `/me/profile` / 必需权限依赖失败 | 登录/敏感操作 fail closed，不单凭 claims 临时放行；已验证缓存也必须受过期和撤权策略约束 |
| 租户未开通 DeepTutor | 返回 403 |

## 生命周期与平台身份

阶段二必须支持用户/租户停用、撤权与身份切换后的 token/缓存失效；长连接每次新 turn、敏感操作及 worker 派发重新检查当前授权状态。DeepTutor 不提供普通用户注册或密码找回入口；需要注册/开户时跳转或提示到 EduPlus2 完成。平台运营角色来自可信平台授权，与学校管理员分开；阶段三仅新增运营界面，不把身份安全延期。cookie 认证的写接口校验 CSRF/Origin，WebSocket 校验 Origin，日志不记录 token 或签名 URL。

登录/换票和恢复已有身份均使用 [03 的分源租户准入](03-tenant-scope-schema.md#租户状态的独立来源)。外部资格有效不覆盖本地暂停，运营恢复不覆盖外部停订；外部模式禁止沿用 M1 的 not_required。用户认证后仍逐资源检查 owner/已支持的 grant，不能把租户成员资格视为私有内容访问权。

## B1 验收与 B2 放量

B1 使用 M1 存储基线，验证身份绑定、工作台进入、聊天、KB/附件访问、退出/撤权和未绑定租户拒绝；采用最终 adapter，不开发临时 token 透传。权限和停用所需事件链路不能推迟至 B2。B2 复用 B1 服务验证多个租户，不重做认证、不重新分配内部 ID。
