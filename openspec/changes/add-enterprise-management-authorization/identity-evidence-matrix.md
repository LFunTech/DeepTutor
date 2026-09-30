# 外部认证与身份识别证据矩阵
> **真实账号测试范围（2026-09-29 用户确认）**：当前仅以 `.secrets/.login-credentials` 中 admin 账号做真实登录/fail-closed 验收；actor 本人、双学校/错校、撤权/恢复、目录策略和正式写 API 等综合矩阵，等管理后台功能完成后在 5.1 前统一测试。

> 范围：本文件只记录 DeepTutor Enterprise 在**不修改 EduPlus2**前提下可采信的认证、身份识别与学校绑定证据。EduPlus2 角色、权限 API、JWT role 或学校码不作为本产品 `ops.*` / `tenant.*` 授权依据。

## 证据等级

| 等级 | 含义 | 是否可用于正式放行 |
| --- | --- | --- |
| `code-verified` | 本仓库合成 OIDC/Webhook/PG 测试已验证逻辑、失败模式和 DTO 红线 | 只能证明 DeepTutor 逻辑；不能替代 test-cn 真实身份合同 |
| `test-cn-demo` | test-cn demo/mock 或控制台模拟调用成功 | 只能证明集成通道；不能作为首位管理员或正式登录授权证据 |
| `test-cn-real` | test-cn 真实授权码/OIDC/Webhook 事件、真实 actor 与本人登录脱敏证据 | 可作为 5.1 开闸前置之一 |
| `missing` | 真实接口/策略范围/目录语义尚未核实 | 相关正式入口保持失败关闭 |

## OMS 平台身份

| 项 | 当前证据 | 等级 | 结论 |
| --- | --- | --- | --- |
| OIDC discovery/JWKS 验签 | `test_oms_platform_identity.py` 覆盖 RS256、JWKS 同源、篡改签名、HS256 伪造拒绝 | `code-verified` | DeepTutor 验签逻辑已具备 |
| issuer/audience/client/azp 合同 | `test_platform_verifier_rejects_wrong_identity_contract` 覆盖错 `aud`、错 `azp`、错 `iss`、空 `sub`、非 Bearer、未来 `iat` | `code-verified` | 错合同失败关闭 |
| 账号在线状态 / token-only 策略 | `BearerAccountStatusClient` 合成测试覆盖本人 active、subject mismatch、缺 status 失败关闭；`TokenOnlyAccountStatusClient` 覆盖 EduPlus2 仅提供 OIDC 认证/身份、未开放 OMS profile 状态端点时的显式策略 | `code-verified` | 在线状态检查器和 token-only 备选策略均已具备；二者都不授予 `ops.*` |
| `eduplus-platform-admin` 真实授权码登录 | 2026-09-29 通过 `https://deeptutor.lfun.pub` local-ssl 与 test-cn Keycloak 完成真实授权码登录；脱敏 claim：issuer=`https://eduplus-auth-test.f123.pub/realms/eduplus`、access token `aud=account`、`azp=eduplus-platform-admin`、`typ=Bearer`、subject hash=`6ec5e9eff16714a0`；同批 `id_token aud=eduplus-platform-admin` 但 `typ=ID`。EduPlus2 `/api/v1/me/profile` 对该 OMS client access token 返回 401，因此本产品显式使用 token-only 身份有效性策略。2026-09-29 rc.69 公网浏览器复测：`/api/v1/oms/auth/status` 返回 200，`/api/v1/oms/me` 因无本地 `ops.*` 返回 403，未调用写 API。 | `test-cn-real` | OMS 认证与稳定身份来源已验证；本地 `ops.*` 仍由 DeepTutor Enterprise 判定，未登记授权时 `/api/v1/oms/me` 返回 403 |
| `eduplus-platform-admin` 非浏览器直连限制 | 2026-09-29 只读探测确认该 client 不允许 Resource Owner Password Grant（Keycloak 返回 `unauthorized_client`），HTTP 表单自动化也未取得授权码；未取得 token、未调用写 API、未输出敏感数据。 | `test-cn-real` 限制说明 | 后续真实验收必须通过授权码浏览器会话/BFF 或人工配合完成，不能以密码直连、合成 JWT 或脚本登录失败替代。 |
| 普通租户 token 冒充 OMS | `test_oms_me_rejects_tenant_token_and_unconfigured_platform_identity` 等 API 测试覆盖无 OMS verifier/租户 token 被拒 | `code-verified` | 不能复用普通租户换票为 OMS |

## TMS 学校身份

| 项 | 当前证据 | 等级 | 结论 |
| --- | --- | --- | --- |
| TMS bearer 来源 | `trusted_tms_identity_from_token` 仅接受 OIDC 签名 token + Webhook 登记的 active school client + 当前学校投影 | `code-verified` | 不信任 body/header/query 切校 |
| 学校绑定与 client 注册 | `test_signed_created_directly_creates_school_without_online_resolve` 覆盖签名 created 直接创建学校绑定、client 注册与 actor candidate | `code-verified` | DeepTutor 可基于已验签 Webhook 初始化本地资源 |
| TMS HTTP 身份适配器 | `test_tms_bootstrap_http_uses_verified_token_and_signed_school_binding` 覆盖 TMS bearer 与已签名学校绑定 | `code-verified` | 当前学校身份路径已装配 |
| 学校停用/恢复状态阻断 | lifecycle/webhook 与 PEP 相关测试覆盖 suspended/reactivated、local_enabled/provisioning/recovery 栅栏 | `code-verified` | 学校状态是业务门禁，不是人员授权 |
| 第三方应用授权码用户令牌目录 | 尚未核实 EduPlus2 当前学校目录 API 是否对智能体基座 OAuth client 开放、策略范围与空范围语义 | `missing` | TMS 成员目录搜索保持未启用；只能依赖本人登录登记的本地 principal |

## 首位 TMS 管理员 actor

| 项 | 当前证据 | 等级 | 结论 |
| --- | --- | --- | --- |
| Webhook 签名与事件结构 | 已实现 HMAC 验签、事件 ID 幂等、mock 过滤、inbox digest；test-cn mock 8/8 只作通道证据 | `test-cn-demo` + `code-verified` | mock 不可作为首位管理员证据 |
| 真实 `subscription.created.actor` 登记 | 本地合成测试覆盖 `actor.type=user` 与 `actor.user_id` 登记 candidate | `code-verified` | 逻辑可用，但需真实事件脱敏证据 |
| test-cn PostgreSQL 快照中的 actor candidate | 2026-09-29 按用户授权只读复制 test-cn PG 到本地隔离库；脱敏计数显示 `eduplus2.webhook_school_state` 有 3 个真实学校投影且 `school_code` 均非空，但 `eduplus2.lifecycle_actor_candidates` 为 0 行 | `test-cn-real` 限制说明 | 可证明当前 DB 有真实学校绑定/学校码投影；不能证明真实 actor 与后续 OIDC `sub` 匹配，也不能据此开放首位 TMS 管理员 |
| rc.69 真实 Webhook actor 即时首管事实 | 2026-09-29 对 test-cn rc.69 当前运行库做 RLS-aware 只读聚合：`webhook_school_state_total=14`、`lifecycle_inbox_total=9`、`actor_candidates_total=7`、`management_principals_total=4`、`management_assignments_total=4`、`school_admin_active_total=4`，4 个学校各有唯一 active `school_admin` 且无多首管。 | `test-cn-real` | 真实订阅 Webhook 即时首管事实仍存在；但是否能由后续本人 OIDC 登录识别为管理员，还取决于 actor 与 OIDC token 字段合同 |
| `.secrets` admin 账号与 actor / TMS 失败关闭 | 2026-09-29 按用户要求将正式真实账号验收范围收敛为 `.secrets/.login-credentials` 中 admin 账号。该 admin 可完成 OMS `eduplus-platform-admin` 授权码登录，但不是当前 4 个 school_admin actor；用该 admin 访问 rc.69 当前 4 个 school code 时，页面均显示“学校入口未开放”，`/api/v1/tms/me/permissions` 均返回 401。 | `test-cn-real` 限制说明 | admin 账号不是当前 Webhook actor，TMS 保持失败关闭；需要 EduPlus2 提供 actor 对应账号或 `actor.user_id` ↔ OIDC `sub/eui/eei/ees` 的正式映射合同后才能闭合 TMS 本人登录验收 |
| `.secrets` 多账号脱敏比对（额外非门槛） | 2026-09-29 曾对 `.secrets/.login-credentials` 中 20 个去重账号做 demo 登录脱敏比对：17 个成功取得 DeepTutor `dt_token`，3 个失败/无 token；成功 token 的 `external_subject`/`external_user_id`/`eui`/`eei`/`ees`/`external_tenant_id` 哈希均未匹配当前 4 个 school_admin actor subject hash。 | `test-cn-real` 非门槛补充 | 用户已明确后续只需测试 admin 账号；本行只保留为额外排查背景，不作为正式验收范围，也不要求继续扩展账号矩阵 |
| 本人 TMS 登录激活 | `school-bootstrap/activate` 合成测试覆盖本人匹配后激活唯一 `school_admin`，错人/重放失败关闭 | `code-verified` | 真实 test-cn actor 与 OIDC `sub` 匹配仍待补 |
| 订阅 ID 门禁 | 按用户决策，事件 `subscription.id` 当前用于审计/冲突，不作为登录/首位激活在线复核门禁 | `approved-design` | 不再调用 EduPlus2 online resolve 复核订阅 |

## 仍需 test-cn 真实验收

1. OMS：已补 `eduplus-platform-admin` 授权码登录与脱敏 `iss/aud/azp/sub` 证据；真实账号验收范围按用户要求收敛为 `.secrets` 中 admin 账号；仍需补过期/错 token、会话隔离、正式写 API 联调与回退审计证据。
2. TMS：真实学校订阅事件 `subscription.created.actor.type=user` / `actor.user_id` 与该本人后续 TMS OIDC `sub` 的匹配证据。按用户确认，等管理后台功能完成后统一测试。
3. 双学校：A/B 学校 token、client、学校绑定和 URL/body/header 篡改负例。按用户确认，等管理后台功能完成后统一测试。
4. 学校目录：若要启用搜索，需证明第三方应用授权码用户令牌、DataAccessPolicy/UserAccessPolicy、空范围/空结果/故障语义；缺失时正式目录搜索保持未启用；按用户确认，等管理后台功能完成后统一测试。
