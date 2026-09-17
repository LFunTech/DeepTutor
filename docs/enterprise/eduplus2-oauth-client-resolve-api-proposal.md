# EduPlus2 通用 OAuth Client Resolve API 需求建议

> 面向 EduPlus2 项目组的通用接口需求草案。本文描述的是平台级开放能力，不绑定任何特定第三方产品或调用方。

## 1. 背景

第三方服务端应用在接入 EduPlus2 OAuth/OIDC 后，经常需要根据一个已知 `client_id` 判断：

- 该 OAuth Client 是否存在、是否有效、是否被撤销；
- 它属于哪个 EduPlus2 应用、开发者和租户；
- 该应用/租户/订阅是否处于可用状态；
- 是否允许被用于登录、客户端凭证、JWT `azp` 校验、开放 API 调用或后续网关策略；
- 应写入审计日志的权威 `app_id/app_name/tenant_id/tenant_name` 是什么。

如果每个第三方系统自行维护这些映射，会导致：

1. `client_id -> app/tenant` 归属不一致；
2. 应用改名、凭证轮换、租户停用、订阅变化后无法及时同步；
3. 审计字段不统一；
4. 第三方系统容易错误保存或暴露 `client_secret`；
5. 不同系统重复实现 client 校验逻辑。

因此建议 EduPlus2 提供一个通用的 OAuth Client 解析接口，供服务端调用方按 `client_id` 获取权威元数据和可用状态。

## 2. 目标

提供一个通用 API：

```http
POST /api/v1/open/oauth-clients/resolve
```

用于服务端应用根据 `client_id` 解析并校验 OAuth Client 的权威归属、状态、应用、租户、订阅与策略信息。

该接口应适用于：

- 第三方服务端应用；
- API 网关；
- 审计系统；
- 数据同步服务；
- 业务平台之间的集成校验；
- 需要验证 JWT `azp` 与 client/app/tenant 关系的被调用方系统。

## 3. 非目标

该接口不应承担以下职责：

- 不返回 `client_secret`；
- 不签发 access token / refresh token；
- 不替代 OAuth/OIDC token endpoint；
- 不替代权限 API / OpenFGA 授权判断；
- 不提供 client 列表枚举；
- 不做第三方业务系统的领域授权；
- 不承载任何特定第三方产品或调用方的专有字段、专有用途或专有命名。

## 4. API 概览

```http
POST /api/v1/open/oauth-clients/resolve
Authorization: Bearer <m2m_access_token>
Content-Type: application/json
Accept: application/json
```

建议使用 `POST` 而不是 `GET`：

- 避免 `client_id` 和约束条件出现在 URL、代理日志或浏览器历史中；
- 便于携带 `expected_tenant_id`、`expected_app_id`、`include` 等结构化请求；
- 便于后续增加可选约束，不破坏 URL 语义。

## 5. 调用方认证与权限

该接口只允许服务端到服务端调用。调用方必须使用 EduPlus2 M2M access token。

建议 scope：

| Scope | 含义 |
| --- | --- |
| `oauth-client.resolve` | 允许按明确 `client_id` 解析 client 是否存在及基础状态 |
| `oauth-client.metadata.read` | 允许返回 app、tenant、developer 等展示/审计元数据 |
| `oauth-client.policy.read` | 允许返回 OAuth grant、scope、usage policy 等策略信息 |

如果需要更细粒度，也可以拆分为：

```text
oauth-client.status.read
oauth-client.app.read
oauth-client.tenant.read
oauth-client.policy.read
```

权限原则：

- 调用方只能按明确 `client_id` 查询；
- 不提供无条件列表接口；
- 返回字段受调用方 scope 和 `include` 控制；
- 无权限时返回 403，或业务响应中 `verified=false, reason=permission_denied`，两种模式需在 EduPlus2 API 规范中统一。

## 6. Request

### 6.1 JSON Schema（草案）

```json
{
  "client_id": "alpha-client-001",
  "expected_tenant_id": 20001,
  "expected_app_id": 10001,
  "include": ["app", "tenant", "oauth", "policy"]
}
```

### 6.2 字段说明

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `client_id` | string | 是 | 待解析的 OAuth Client ID。 |
| `expected_tenant_id` | number/string | 否 | 调用方期望该 client 归属的 EduPlus2 租户 ID；不匹配时 `verified=false`。类型以 EduPlus2 现有 tenant id 契约为准。 |
| `expected_app_id` | number/string | 否 | 调用方期望该 client 归属的 EduPlus2 应用 ID；不匹配时 `verified=false`。 |
| `include` | string[] | 否 | 控制返回哪些扩展对象。建议支持 `app`、`tenant`、`oauth`、`policy`。缺省返回最小安全集合。 |

不建议增加 `purpose=<specific_product>_xxx` 这类定制字段。若 EduPlus2 需要区分调用用途，应优先通过 M2M scope、调用方 client、网关策略和审计实现。

## 7. Success Response

### 7.1 正常解析且校验通过

```json
{
  "code": 0,
  "message": "success",
  "request_id": "req_20260916_abcdef",
  "data": {
    "verified": true,
    "reason": "ok",
    "client": {
      "client_id": "alpha-client-001",
      "credential_id": 30001,
      "status": "active",
      "deprecated": false,
      "created_at": "2026-09-16T10:00:00Z",
      "updated_at": "2026-09-16T10:00:00Z"
    },
    "app": {
      "app_id": 10001,
      "app_code": "alpha",
      "app_name": "Alpha 应用",
      "app_type": "web",
      "developer_id": "dev_org_xxx",
      "developer_name": "Alpha Developer",
      "status": "active"
    },
    "tenant": {
      "tenant_id": 20001,
      "tenant_code": "school-a",
      "tenant_name": "A 学校",
      "status": "active",
      "subscription_status": "active"
    },
    "oauth": {
      "issuer": "https://eduplus-auth-test.f123.pub/realms/eduplus",
      "jwks_uri": "https://eduplus-auth-test.f123.pub/realms/eduplus/protocol/openid-connect/certs",
      "token_endpoint": "https://eduplus-auth-test.f123.pub/realms/eduplus/protocol/openid-connect/token",
      "allowed_scopes": ["openid", "profile", "email"],
      "allowed_grant_types": ["authorization_code", "client_credentials"]
    },
    "policy": {
      "allowed_usages": [
        "authorization_code",
        "client_credentials",
        "jwt_azp_verification"
      ]
    },
    "version": 12
  }
}
```

### 7.2 字段返回规则

| 对象 | 返回条件 | 说明 |
| --- | --- | --- |
| `client` | 最小集合默认返回 | 不含 secret；用于状态判断。 |
| `app` | `include` 包含 `app` 且调用方有权限 | 用于审计、展示、唯一性判断。 |
| `tenant` | `include` 包含 `tenant` 且调用方有权限 | 用于租户归口、审计、状态判断。 |
| `oauth` | `include` 包含 `oauth` 且调用方有权限 | 用于 verifier 配置发现和兼容性校验。 |
| `policy` | `include` 包含 `policy` 且调用方有权限 | 用于判断该 client 可用于哪些 OAuth/开放 API 场景。 |

## 8. Business Failure Response

当调用方认证通过，但目标 client 不存在、状态无效、租户/app 不匹配或策略不允许时，建议返回 HTTP 200 + `verified=false`，便于调用方区分“查询成功但业务不通过”和“接口调用失败”。

```json
{
  "code": 0,
  "message": "success",
  "request_id": "req_20260916_abcdef",
  "data": {
    "verified": false,
    "reason": "tenant_mismatch",
    "client": null,
    "app": null,
    "tenant": null,
    "oauth": null,
    "policy": null,
    "version": null
  }
}
```

推荐 `reason`：

| reason | 含义 | 调用方建议处理 |
| --- | --- | --- |
| `ok` | 校验通过 | 继续业务流程。 |
| `client_not_found` | `client_id` 不存在 | 401/404 或提示重新配置。 |
| `client_inactive` | client 未激活 | 401/403。 |
| `client_revoked` | client 已撤销 | 401/403，要求更换凭证。 |
| `client_deprecated` | client 已废弃但可能尚未撤销 | 按业务策略警告或拒绝。 |
| `tenant_mismatch` | `expected_tenant_id` 与实际归属不一致 | 403/409。 |
| `app_mismatch` | `expected_app_id` 与实际归属不一致 | 403/409。 |
| `app_inactive` | 应用停用 | 403。 |
| `tenant_inactive` | 租户停用 | 403。 |
| `subscription_inactive` | 应用订阅无效 | 403。 |
| `policy_not_allowed` | policy 不允许该 usage | 403。 |
| `permission_denied` | 调用方无权解析该 client 或请求的 include | 403。 |
| `temporarily_unavailable` | 平台依赖暂不可用 | 503 或稍后重试。 |

## 9. Protocol Error Response

协议层错误仍使用 HTTP 状态码：

| HTTP 状态码 | 场景 |
| --- | --- |
| 400 | JSON 格式错误、`client_id` 缺失、字段类型错误。 |
| 401 | 调用方 M2M token 缺失、无效、过期。 |
| 403 | 调用方无所需 scope。 |
| 429 | 调用方超过限流。 |
| 500 | EduPlus2 内部错误。 |
| 503 | 依赖服务不可用。 |

示例：

```json
{
  "code": 40001,
  "message": "client_id is required",
  "request_id": "req_20260916_abcdef"
}
```

## 10. 安全要求

1. 只允许服务端 M2M 调用，不开放浏览器匿名调用。
2. 不返回 `client_secret`、refresh token、access token、HMAC secret 或任何可复用密钥。
3. 不支持无条件枚举所有 client。
4. `include` 请求的字段必须受调用方 scope 控制。
5. 响应可包含 `credential_id` 用于审计和问题定位，但不能返回密钥材料。
6. 建议对调用方、目标 `client_id`、结果、reason、request_id 记录审计。
7. 建议提供限流，防止按 client_id 暴力探测。
8. 建议对不存在和无权限的返回信息做最小化，避免泄露过多租户/app 信息。
9. 响应中的 `version` 用于调用方缓存和变更检测；client/app/tenant/policy 变化时应递增或提供可比较版本。
10. 如存在跨网络访问限制，应在文档中明确 allowlist、内网域名或网关路径。

## 11. 缓存建议

调用方可缓存解析结果，但必须遵守状态时效：

| 数据 | 建议 TTL |
| --- | --- |
| client/app/tenant 元数据 | 5–30 分钟 |
| active/revoked/suspended 状态 | 1–5 分钟 |
| policy/allowed_usages | 1–5 分钟 |
| JWKS/OIDC discovery | 按 EduPlus2 OIDC/JWKS 缓存建议，通常可更长 |

如果 EduPlus2 已有 Webhook 事件，可在 client 状态、应用订阅、租户状态、secret 轮换等变更时通知调用方失效缓存。

## 12. 调用示例

### 12.1 按 client_id 解析基础信息

```bash
curl -X POST 'https://eduplus-test.f123.pub/api/v1/open/oauth-clients/resolve' \
  -H 'Authorization: Bearer <m2m_access_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "client_id": "alpha-client-001",
    "include": ["app", "tenant"]
  }'
```

### 12.2 校验 client 是否属于指定租户

```bash
curl -X POST 'https://eduplus-test.f123.pub/api/v1/open/oauth-clients/resolve' \
  -H 'Authorization: Bearer <m2m_access_token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "client_id": "alpha-client-001",
    "expected_tenant_id": 20001,
    "include": ["app", "tenant", "policy"]
  }'
```

如果实际 tenant 不等于 `20001`，返回：

```json
{
  "code": 0,
  "message": "success",
  "request_id": "req_20260916_abcdef",
  "data": {
    "verified": false,
    "reason": "tenant_mismatch",
    "client": null,
    "app": null,
    "tenant": null,
    "oauth": null,
    "policy": null,
    "version": null
  }
}
```

## 13. JWT `azp` 校验用法

第三方系统或被调用方系统在验证 EduPlus2 user JWT 后，可以将 JWT 中的 `azp` 作为 OAuth client id，再通过本接口或本地缓存确认 `azp` 的权威归属。

推荐校验链路：

```text
JWT signature valid
AND iss valid
AND exp/iat valid
AND tid/eui/sub present
AND azp present
AND resolve(azp).verified = true
AND resolve(azp).tenant.tenant_id == JWT.tid
AND client/app/tenant/subscription active
```

如果调用方已经通过 Webhook 或后台注册流程保存了 `azp -> app/tenant` 的 active 注册记录，可优先查本地注册记录，并定期或在缓存失效时调用本接口刷新权威元数据。

## 14. 调用方使用示例

以下示例仅说明通用调用模式，不代表特定产品定制语义。

### 租户管理系统注册 client

```text
租户管理系统当前 external_tenant_id = 20001
管理员输入 client_id = alpha-client-001
调用方调用 resolve(client_id, expected_tenant_id=20001, include=[app, tenant, policy])
EduPlus2 返回 verified=true 且 tenant_id=20001
调用方检查同 tenant+same app active 唯一性
调用方写入本地 client registration
```

### 平台运营系统注册 client

```text
平台运营系统输入 client_id = alpha-client-001
调用方调用 resolve(client_id, include=[app, tenant, policy])
EduPlus2 返回 app/tenant 权威信息
调用方按 tenant_id 查找或创建本地 tenant binding
调用方注册 client 并归口到对应租户管理范围
```

### 被调用方系统进行 JWT token exchange

```text
第三方应用传 EduPlus2 user JWT
被调用方系统验签并提取 azp = alpha-client-001
被调用方系统查 active client registration
必要时调用 resolve(azp) 刷新权威 app/tenant 状态
被调用方系统校验 registration.external_tenant_id == JWT.tid
被调用方系统签发自身短期会话 token
被调用方系统写入 token exchange 审计
```

## 15. EduPlus2 验收建议

接口上线前建议至少覆盖：

1. active client resolve 成功；
2. 不存在 client 返回 `verified=false, reason=client_not_found`；
3. inactive/revoked client 返回对应 reason；
4. `expected_tenant_id` 不匹配返回 `tenant_mismatch`；
5. `expected_app_id` 不匹配返回 `app_mismatch`；
6. app/tenant/subscription 非 active 返回对应 reason；
7. 无 M2M token 返回 401；
8. M2M token 缺少 scope 返回 403；
9. include 超出授权范围不返回未授权字段；
10. 响应不包含 `client_secret` 或任何可复用密钥；
11. 调用审计包含 caller client、target client、result、reason、request_id；
12. 高并发/重复查询有稳定限流与缓存策略；
13. client/app/tenant 状态变化后 `version` 或缓存失效行为可验证。

## 16. 与现有 EduPlus2 能力的关系

- 与 OAuth/OIDC token endpoint：本接口不签发 token，只解析和校验 client 元数据。
- 与 JWT 验证：JWT 验证确认 token 真实性；本接口确认 JWT `azp` 对应 client 的权威归属和状态。
- 与权限 API/OpenFGA：本接口不判断具体业务资源权限；调用方仍需按业务对象调用权限系统或执行本地授权策略。
- 与 Webhook：Webhook 可向调用方推送 client/app/tenant 状态变化；本接口用于实时查询或缓存刷新。
- 与委托验签：委托验签验证请求签名是否有效；本接口解析 client 元数据和归属，两者职责互补。

## 17. 参考文档

- EduPlus2 OAuth/OIDC：<https://eduplus-test.f123.pub/docs/oauth-oidc/>
- EduPlus2 JWT 验证：<https://eduplus-test.f123.pub/docs/oauth-oidc/jwt-verification/>
- EduPlus2 Token 管理：<https://eduplus-test.f123.pub/docs/oauth-oidc/token-management/>
- EduPlus2 工作台 Handoff：<https://eduplus-test.f123.pub/docs/oauth-oidc/workbench-handoff/>
- EduPlus2 权限集成：<https://eduplus-test.f123.pub/docs/permission/>
- EduPlus2 Webhook：<https://eduplus-test.f123.pub/docs/webhook/>
