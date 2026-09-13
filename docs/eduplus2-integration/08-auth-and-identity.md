# 08. 认证与身份对接方案

## 阶段边界

阶段一保留已有受保护本地认证，将账号/凭证 hash 与会话状态持久化到 PG，服务器绑定固定内部 tenant；不依赖 EduPlus2 上线。EduPlus2 app 注册、测试账号和契约准备与 A1/A2 并行；以下最终入口先在 B1 完成一个真实租户的登录/权限/撤权闭环，B2 再开放多个租户，不采用“先登录后补权限”的放行模式。阶段二正常租户登录统一走外部身份；本地认证如保留仅限审计化平台应急入口，不能成为租户绕过停用/撤权的旁路。

外部 tid/eui 经 [03 身份映射](03-tenant-scope-schema.md) 转换内部 tenant_id/user_id；原单租户账号只显式绑定，不按同名自动合并。

## EduPlus2 认证入口

EduPlus2 支持 OAuth2/OIDC，并提供工作台 Handoff。DeepTutor 作为 EduPlus2 工作台应用时，推荐优先支持 Handoff：

1. 用户从 EduPlus2 工作台点击 DeepTutor 应用。
2. EduPlus2 跳转到 DeepTutor，并带上 `eduplus_handoff_code` 和 `eduplus_state`。
3. DeepTutor 后端使用 client secret 对 handoff code 请求签名。
4. DeepTutor 调用 EduPlus2 `/api/v1/app-handoff/token` 换取 token。
5. DeepTutor 校验 token，调用 `/api/v1/me/profile` 获取业务态。
6. DeepTutor 生成自己的 `dt_token`，供现有 API 和 WebSocket 使用。

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

## EduPlus2 claims 使用规则

EduPlus2 access token 中关键 claims：

| claim | 含义 | DeepTutor 使用方式 |
| --- | --- | --- |
| `tid` | EduPlus2 外部租户 ID | 映射为 DeepTutor 内部 `tenant_id` |
| `eui` | EduPlus2 用户 ID | 保存外部 ID，映射为 DeepTutor 内部 `user_id` |
| `eit` | 当前激活身份类型，如 `stu/tch/par/adm` | feature mode 和初步 role mapping |
| `sub` | Keycloak 用户 UUID | 外部认证主体 ID，可用于审计 |
| `azp` | OAuth client id | 校验 token 是否签发给当前应用 |
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
  "azp": "deeptutor-client-id",
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
  handoff.py      # Handoff 签名、code 换 token
  profile.py      # /api/v1/me/profile 调用和缓存
  mapping.py      # EduPlus2 profile -> TokenPayload/CurrentUser
```

新增路由：

```text
extensions/enterprise/src/deeptutor_enterprise/api/eduplus2.py
```

通过企业应用 factory/启动器注册 router，核心 `require_auth/ws_require_auth` 只增加 provider-aware 身份/通用授权 seam，不内嵌大量 EduPlus2 业务。自有 cookie/token 需要相应 verifier/provider 实际支持新增字段，不能仅在外部签一个 token 就假定原生解码保留 tenant 或新角色。企业入口必须关闭未适配本地 auth/admin 旁路；代理头只能由可信组件产生且不能替代每 turn/敏感操作重验。

候选接口：

```text
GET  /api/v1/eduplus2/handoff/callback
POST /api/v1/eduplus2/logout
GET  /api/v1/eduplus2/session
```

## Token 校验要求

DeepTutor 后端校验 EduPlus2 JWT 时至少检查：

1. signature：使用 EduPlus2 JWKS。
2. `iss`：必须匹配 EduPlus2 issuer。
3. `aud` / `azp`：必须匹配当前应用配置。
4. `exp` / `iat`：过期和时间偏移。
5. `tid/eui/eit`：EduPlus2 模式下必须存在。
6. `nonce/state`：Handoff / OAuth callback 防重放。

## Cookie 策略

DeepTutor `dt_token` 建议：

- `HttpOnly=true`
- `Secure=true`，本地开发可配置关闭
- `SameSite=Lax` 或按 EduPlus2 工作台嵌入场景调整
- Path 限制为 DeepTutor 应用路径

如果 DeepTutor 作为 iframe/嵌入式应用运行，需要单独评估第三方 cookie、SameSite=None、CSRF 和 postMessage 安全策略。

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

阶段二必须支持用户/租户停用、撤权与身份切换后的 token/缓存失效；长连接每次新 turn、敏感操作及 worker 派发重新检查当前授权状态。平台运营角色来自可信平台授权，与学校管理员分开；阶段三仅新增运营界面，不把身份安全延期。cookie 认证的写接口校验 CSRF/Origin，WebSocket 校验 Origin，日志不记录 token 或签名 URL。

## B1 验收与 B2 放量

B1 使用 M1 存储基线，验证身份绑定、工作台进入、聊天、KB/附件访问、退出/撤权和未绑定租户拒绝；采用最终 adapter，不开发临时 token 透传。权限和停用所需事件链路不能推迟至 B2。B2 复用 B1 服务验证多个租户，不重做认证、不重新分配内部 ID。
