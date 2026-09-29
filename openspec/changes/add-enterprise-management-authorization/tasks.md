> **实施中；任务 1.1 受影响修订版审批、1.3 入口盘点与 3.1 PG 事实迁移已完成，其余完整任务未完成，证据见 surface-inventory.md 与 implementation-evidence.md。** 2026-09-27 用户进一步明确：DeepTutor Enterprise 程序负责授权决策，PG 只保存事实并提供隔离/一致性兜底，EduPlus2 在权限链路中仅负责认证及身份识别。OMS 仅管平台人员；首位 TMS 管理员来自签名真实 `subscription.created.actor.user_id` 并须本人登录激活，旧 OMS/学校侧双人首位开通与外部负责人权限依赖撤销。只修改 DeepTutor；测试仅用隔离合成数据，真实租户数据、生产发布、提交、归档另行授权。此轮权威再修订需同步受影响提案并复核 1.1，不授权真实数据、外部系统修改或发布。

> **当前执行焦点（非勾选项）**：本 change 是 OMS/TMS 的唯一授权底座。后续实现按“外部认证证据 → 独立 OMS/TMS 会话 → 程序 PEP 与权限事实 → Webhook actor 首管本人激活 → 两端 UI/API 负例”的顺序推进；Provider、Skill、额度和用量 proposal 只能消费这里的授权结果，不能另建平行权限表、复用 `tenant_admin` 或通过数据库权限直接放行业务操作。

## P0 契约与证据

- [x] 1.1 请用户审阅并分别批准本 proposal/design/spec/tasks 及被本 change 影响的 OMS/TMS 提案；明确旧 TMS 外部管理员权限事件/双负责人开通不是本产品授权实现依据，旧版批准不自动适用。此前 PG 事实库版曾逐项获批；最新用户要求把决策权明确放在 DeepTutor Enterprise 程序，并以真实订阅事件 `actor` 作为一次性首位管理员身份来源，须同步受影响修订版后复核，不以旧勾选代替当前合同。
- [ ] 1.2 建立脱敏外部**认证与身份识别**能力证据矩阵：复用 test-cn Webhook 8/8 mock、已验证 discovery/JWKS/M2M/resolve；区分文档可见、用户指定配置与真实 API 可用。以 `eduplus-platform-admin` 为 OMS 指定 Client ID，实测目标环境的授权码登录、issuer、`azp`、audience、稳定平台主体与身份有效性；另核 TMS 当前学校身份及条件性第三方应用授权码用户令牌的学校成员目录/策略范围。核对真实 `subscription.created` 的 HMAC、应用/学校 ID、`actor.type`/`actor.user_id` 与后续 OIDC `sub` 匹配语义；8/8 mock 不能算真实首位管理员证据。`/me/profile` 不是他人查询，Webhook Client/M2M `/api/v1/users` 示例不是已验收的成员目录；**不向 EduPlus2 索取本产品动作授权或负责人角色判定**。身份合同缺失时保留相关写路由未装配，不修改 EduPlus2。
  - [x] 1.2.1 已建立脱敏身份证据矩阵 [identity-evidence-matrix.md](identity-evidence-matrix.md)，明确 `code-verified`、`test-cn-demo`、`test-cn-real` 与 `missing` 的采信边界。
  - [x] 1.2.2 已用合成 OIDC/JWKS 覆盖 OMS 平台 token 验签、错 issuer/audience/client、篡改签名、非 RS256、账号状态 mismatch 等失败关闭。
  - [x] 1.2.3 已用合成签名 Webhook 与 TMS bearer 覆盖当前学校身份、学校绑定、client 注册、actor candidate 与本人激活逻辑。
  - [ ] 1.2.4 尚需 test-cn 真实 `eduplus-platform-admin` 授权码登录、真实 `subscription.created.actor` 与后续 OIDC `sub` 匹配、学校目录策略范围证据。
    - [x] 1.2.4.1 已在本地 `local-ssl` 经真实 test-cn Keycloak 授权码登录 `eduplus-platform-admin`：`access_token` 脱敏 claim 为 issuer=`https://eduplus-auth-test.f123.pub/realms/eduplus`、aud=`account`、azp=`eduplus-platform-admin`、typ=`Bearer`、稳定 subject hash；EduPlus2 `/api/v1/me/profile` 对该 client token 返回 401，故 OMS 显式改为 token-only 身份状态策略，DeepTutor 本地 `ops.*` 仍失败关闭。
- [x] 1.3 盘点全部 OMS/TMS 菜单、按钮、API、导出、旧 router、CLI/HTTP/WS/SDK/后台及 owner/grant；固定动作 key、`platform`/`school` 范围、默认角色、自定义角色上限和“旧入口 404”清单，并审阅通用 core seam 的上游合并风险。证据见 [surface-inventory.md](surface-inventory.md)；正式新路由逐条权限验收仍归 3.2、4.3、5.1。

## B1 身份与学校绑定

- [ ] 2.1 将已核实的外部 OIDC/身份适配器接入独立 OMS/TMS 会话：OMS `(issuer,sub)`，TMS `(issuer,sub,school)`；验证错 issuer/audience、普通租户 token 冒充 OMS、身份失效、学校身份错配、过期/错学校 token、CSRF/Origin、会话互换与接口故障失败关闭。学校停用由独立 lifecycle 业务状态阻断，不使用外部权限决定 `ops.*`/`tenant.*`。
  - [x] 2.1.1 已装配 OMS 专用 Bearer 分流和平台身份适配器；普通租户 token/未配置 OMS verifier 不可进入 OMS。
  - [x] 2.1.2 已装配 TMS `(issuer,sub,school)` 身份适配器；只接受已签名 Webhook 注册的当前学校 client 和学校投影，不信任 body/header/query 切校。
  - [x] 2.1.3 已在本地 API/合成数据覆盖 Origin/CSRF、学校停用/lifecycle 状态、身份失效和会话互换的核心失败关闭路径。
  - [ ] 2.1.4 尚需目标环境真实授权码登录、真实账号状态、过期/错学校 token、双学校正负例和浏览器会话隔离证据。
    - [x] 2.1.4.1 已通过 `https://deeptutor.lfun.pub` local-ssl 回调验证真实浏览器 Cookie：`/api/v1/oms/auth/status` 返回 200；同一会话访问 `/api/v1/oms/me` 因未登记本地 `ops.oms.access` 返回 403，证明认证成功但本产品授权仍由 Enterprise 程序 fail closed。
- [ ] 2.2 对 `oms.school_bindings` 增量添加经权威核验的创建/撤权/版本栅栏及外部 ID 类型适配；不改已应用 `0011`，不从 `schoolCode`、`external_tid` 或 header 猜测绑定。隔离合成数据验证一对一、改码、解绑、漂移与双学校负例。
  - [x] 2.2.1 已以前向迁移为 `oms.school_bindings` 增加版本栅栏，验证重绑/改码后旧授权不复活，不改已应用 `0011`。
  - [x] 2.2.2 已实现签名 Webhook 创建/更新学校绑定、外部 client 注册、绑定版本投影与 lifecycle 状态联动；不从 header 或 `schoolCode` 猜测绑定。
  - [ ] 2.2.3 尚需目标环境真实外部 ID 类型、双学校绑定漂移/解绑、真实学校码变更和 test-cn 负例证据。

## B2 本产品权限与安全开通

- [x] 3.1 测试先行并新增 DeepTutor 企业 PG 后续版本**权限事实**迁移：主体、两应用域、角色/动作目录版本、授予委托上界、范围/有效期/assignment、policy version、审批请求和追加审计；验证默认零权、RLS 隔离兜底、唯一性、幂等、重复 apply/verify、drift、旧管理员不自动提升、最后管理员保护和回退。迁移不等于程序授权服务交付。
- [ ] 3.2 实现 **DeepTutor Enterprise 统一 PEP/授权服务**与 `require_management_permission(app,action,scope,object)`：由程序按 OMS/TMS 域、已认证身份、本地授权事实、学校绑定、业务状态和 owner/grant 判定；PG role/GRANT/RLS 只做兜底，不能直接放行业务。写事务锁定复核权限/绑定/业务版本并与撤权串行。跨 CLI、HTTP/WS、SDK、后台无直写旁路；未装配旧核心管理 router。test-cn 首个 Agent 的正式 OMS Skill 管理还需以**后续不可变迁移**增加 `ops.skills.read/manage/review/publish/grant` 动作、显式模板与目标学校范围，API/前端同 key 验收；不得改写已应用的 0001 目录或复用 Provider 权限冒充 Skill 授权。
  - [x] 3.2.1 已实现 Python 应用层 `require_management_permission`/delegation/grant/revoke 基础 PEP：按应用域、动作、scope、主体版本、assignment、委托上界、学校绑定与业务状态判定；PG role/GRANT/RLS 仅作兜底。证据见 implementation-evidence 2026-09-27 管理决策/授予/撤权切片。
  - [x] 3.2.2 已以前向迁移和应用逻辑加入学校绑定版本与 lifecycle 可用性栅栏；旧学校授权不会因重绑复活，TMS/OMS 写入按事务锁序复核。
  - [x] 3.2.3 已装配 `/api/v1/oms/me`、`/api/v1/oms/me/permissions`、`/api/v1/tms/me/permissions`、OMS/TMS 权限目录只读 DTO，并验证无本产品授权时失败关闭。
  - [x] 3.2.4 已新增 OMS Skill `ops.skills.*` 动作目录后续迁移及 `/api/v1/oms/skills`、`/api/v1/tms/skills` 安全只读 DTO；Skill 存储 key/正文/Secret 不回显。
  - [ ] 3.2.5 尚需闭合真实 `eduplus-platform-admin` 授权码/平台账号状态证据、正式 OMS 写 API 全链路、CLI/WS/SDK/后台旁路审计、当前 upstream mergeability smoke。
    - [x] 3.2.5.1 已装配正式 OMS 授权写 API：`/api/v1/oms/approvals*`、`/api/v1/oms/principals/{principal_id}/roles`、`/api/v1/oms/assignments/{assignment_id}/revoke`、`/api/v1/oms/principals/{principal_id}/disable`，均复用 DeepTutor Enterprise 程序 PEP、委托上界、学校绑定/版本、命令幂等和审计；不使用 EduPlus2 权限或数据库函数/触发器。
    - [ ] 3.2.5.2 尚需真实 `eduplus-platform-admin` 授权码/平台账号状态证据、CLI/WS/SDK/后台旁路审计、真实环境写 API 联调和当前 upstream mergeability smoke。
      - [x] 3.2.5.2.1 已新增 OMS 授权码登录会话、CSRF 写入保护、显式 token-only 状态策略和正式页面 fail-closed 初始态；本地验证真实登录后无 `ops.*` 时仍 403，不自动授予任何平台权限。
      - [x] 3.2.5.2.2 已用可执行旁路审计测试固定：企业 CLI/通用 SDK 不提供 OMS/TMS/Provider/额度管理写入口，WS turn 协议拒绝管理写命令和管理写字段，core/CLI/SDK/后台代码不直接导入企业管理授权模块或写 `management.*` 授权事实表。
      - [x] 3.2.5.2.3 已执行只读 upstream mergeability smoke：当前 `HEAD` 与本地 `upstream/main` 的 merge-base 为 `upstream/main`，`git merge-tree` 未发现文本冲突标记；未执行 merge/rebase/reset。
- [ ] 3.3 实现 **Webhook 一次性首位管理员登记与本人激活**：仅真实、已验签、非 mock、目标应用/学校及订阅 ID 结构校验通过的 `subscription.created`，且 `actor.type=user`、`actor.user_id` 非空，才写入该校待激活 `(issuer,sub)` 与一次性消费栅栏；事件 ID 幂等、学校绑定版本及已消费/撤销引导不得复活。事件订阅 ID 仅作审计/冲突依据，不作为本产品当前订阅 ID 比对门禁。本人 TMS 登录后须精确匹配已登记身份和当前学校，Enterprise 程序在事务内复核当前学校—应用有效及本地版本，激活唯一 `school_admin` assignment、追加审计。`actor` 缺失/system/null/错校或身份不匹配保持零权；OMS 无学校账号/开通入口。真实事件合同及联调未通过时正式写接口保持关闭。
  - [x] 3.3.1 已实现并验证签名 Webhook `subscription.created` 直接初始化学校绑定、外部 client 注册、actor candidate 与一次性本人激活路径；mock 不计入正式开通。
  - [x] 3.3.2 已实现 `/api/v1/tms/school-bootstrap/status` 与 `/api/v1/tms/school-bootstrap/activate`，本人 TMS bearer 精确匹配 candidate 后激活唯一 `school_admin` assignment 并追加审计。
  - [ ] 3.3.3 尚需补 test-cn 真实 `subscription.created.actor.user_id` 与后续 OIDC `sub` 的脱敏证据、错校/重放/恢复/撤销在真实环境的联调矩阵；正式开闸仍归 5.1。
- [ ] 3.4 实现 TMS 当前学校 `tenant.permissions.manage` 的角色/成员/应用/服务访问管理，模板扩权须显式确认、高风险授权双人审批、委托能力与业务执行权分离、收缩与撤权立即生效；服务 grant 不带额度数量、不越过 OMS 授权，个人正文仍按 owner/显式 grant。
  - [x] 3.4.1 已实现 TMS 当前学校权限目录只读 DTO `/api/v1/tms/permissions`，仅 `tenant.permissions.manage` 可读，且只返回 `tenant.*`。
  - [x] 3.4.2 已实现本人零权登记 `/api/v1/tms/me/register` 与当前学校成员只读列表 `/api/v1/tms/members`；不创建/同步 EduPlus2 用户。
  - [x] 3.4.3 已实现低风险角色授予 `/api/v1/tms/members/{principal_id}/roles`，固定当前学校、要求本人登记和委托上界，拒绝 `school_admin`/敏感角色/自授。
  - [x] 3.4.4 已实现当前学校自定义角色发布 `/api/v1/tms/roles/custom`，仅低风险 `tenant.*`，拒绝 `ops.*` 与敏感动作。
  - [x] 3.4.5 已实现 assignment 撤权 `/api/v1/tms/assignments/{assignment_id}/revoke`，复核版本、命令幂等、撤权即时影响和最后管理员保护。
  - [x] 3.4.6 已实现授权审计只读 DTO `/api/v1/tms/authz-audit`，只读当前学校本地授权事件，不回显 Secret/成本/私有正文。
  - [x] 3.4.7 已实现高风险审批请求生命周期 `/api/v1/tms/approvals*`：创建、列表、独立复核、撤回、自批拒绝与终态冲突。
  - [ ] 3.4.8 尚需实现审批通过后的受控 apply（授予 `school_admin`/敏感角色或扩展委托上界）、模板版本扩权显式确认、学校目录搜索策略与空范围/故障区分、正式 UI 接线及双学校真实登录验收。
    - [x] 3.4.8.1 已实现审批通过后的受控 apply API `/api/v1/tms/approvals/{approval_id}/apply`：仅当前学校、已批准请求、独立管理员当前权限、目标版本与命令幂等全部通过后，授予 `school_admin` 并推进目标 policy version。
    - [ ] 3.4.8.2 尚需补真实学校目录搜索策略与空范围/故障区分、正式 UI 完整可访问性及双学校真实登录验收。
      - [x] 3.4.8.2.1 已实现学校目录搜索失败关闭 DTO `/api/v1/tms/directory/users`：未核实外部目录合同时返回 `not_enabled/external_directory_contract_missing`，不返回合成用户。
      - [x] 3.4.8.2.2 已以前向迁移 `management/0009_approval_apply_payload.sql` 和应用层服务 `apply_approved_management_approval` 实现审批通过后的通用 apply：OMS `platform_grant` 按已确认角色模板版本授予敏感/管理员角色，`delegation_expand` 按审批载荷扩展委托上界，均在事务内复核治理权限、委托上界、目标 policy version、命令幂等并追加审计；不使用 DB 函数、触发器或枚举 CHECK。
      - [ ] 3.4.8.2.3 尚需真实学校目录策略合同、正式 TMS/OMS 完整可访问性和双学校真实登录验收。
        - [x] 3.4.8.2.3.1 已用程序级并发测试覆盖审批 apply 竞态：同一已批准 OMS 平台授权被两个不同 command 并发 apply 时，只允许一个 assignment 生效，另一个因目标 policy version/既有授权冲突失败关闭。

## C1/C2 独立正式 UI 与原型

- [ ] 4.1 修订 OMS 开发原型的平台人员/角色/学校操作范围/审计合成场景，删除旧学校后台开通入口及直达深链；平台候选仅来自可信 OMS 登录登记，目录未核实时显示未启用。正式 OMS 接真实平台权限 API 的列表、聚焦详情、操作模态框、权限差异、原因/审批/版本、状态 descriptor 和审计回读。无数据源显示未启用，生产原型路径 404。
  - [x] 4.1.1 已新增正式 `/oms` 受控入口壳：只读取 `/api/v1/oms/me`、`/api/v1/oms/me/permissions`、`/api/v1/oms/skills` 安全 DTO；真实平台登录或本地 `ops.*` 授权缺失时失败关闭，不回退开发原型、不显示学校账号开通或写按钮。
  - [x] 4.1.2 已在正式 `/oms` 受控入口接入模型草稿与 Provider 设置只读 DTO：仅在 `ops.providers.read` 下读取 `/api/v1/oms/models/draft` 与 `/api/v1/oms/provider-settings`，显示脱敏模型/连接，不提供保存、发布、回滚或测试写按钮。
  - [x] 4.1.3 已在正式 `/oms` 受控入口接入 OMS 总览、平台资源状态、学校范围、供给批次、审计与 OMS-only 成本只读 DTO；按本地 `ops.*` 动作决定读取面，不显示补充、授权、调整、成本导出或密钥按钮。
  - [x] 4.1.4 已在正式 `/oms` 受控入口按首个已授权学校接入用量 attempt 与待核对任务只读 DTO；不显示学校私有正文或结算/释放/核销写按钮。
  - [ ] 4.1.5 尚需正式 OMS 写入/审批/审计回读 UI 全链路、真实平台目录候选和按钮级验收。
    - [x] 4.1.5.1 已在正式 `/oms` 中按 `ops.providers.manage` 接入模型与 Provider 草稿测试/发布/回滚按钮，按 `ops.skills.review/publish/grant` 接入 Skill 审查、发布和首个授权学校 grant 按钮；payload 使用后端 DTO 的 version/revision/sha256/school_id，不从页面输入切校或 Secret。
    - [ ] 4.1.5.2 尚需平台人员/角色/学校操作范围写 UI、真实平台目录候选、审批/审计回读详情和真实账号按钮级验收。
      - [x] 4.1.5.2.1 已在正式 `/oms` 平台授权治理区接入平台人员、角色、学校操作范围、assignment 撤权、主体停用、审批创建/复核/apply 与审计回读；按钮仅在 `ops.permissions.manage` 下显示，payload 均来自安全 DTO 的 principal/role/assignment/approval/school/version。
      - [ ] 4.1.5.2.2 尚需真实平台目录候选、真实账号按钮级验收和完整键盘/窄屏可访问性矩阵。
        - [x] 4.1.5.2.2.1 已用正式 OMS 前端测试覆盖桌面与窄屏视口下的语义 `main`、关键 section heading、搜索框 label、平台授权治理按钮可命名且可键盘触发。
- [ ] 4.2 修订 TMS 开发原型的 Webhook actor 待激活/本人登录匹配、缺 actor 待核对、成员/角色/访问关系/撤权状态，并演示“搜索可见已有账号→本人登录登记→匹配后授权”及目录无权/空范围/空结果/故障的区别；不得把合成目录伪装成真实 EduPlus2 同步，旧双人首位开通按钮不得保留为正式入口。正式 TMS 仅在第三方应用用户令牌及策略范围获证实时接学校目录，且只接当前学校安全 DTO；双向关系回读同一事实，额度/用量保持只读，不共享 OMS 会话、API client 或专有字段。生产原型路径 404。
  - [x] 4.2.1 已修订开发态 TMS 原型的真实订阅 actor 待匹配/本人匹配/其他人/缺 actor/mock 五态，移除旧双负责人正式开通按钮并通过浏览器审计。
  - [x] 4.2.2 已在原型中收敛学校角色直授：只展示低风险角色，敏感角色和管理员角色进入复核提示，不把合成数据伪装成真实目录。
  - [ ] 4.2.3 尚需将正式 TMS UI 接入当前 `/api/v1/tms/*` 安全 DTO，并补齐目录无权/空范围/空结果/故障、审批 apply、撤权即时生效和可访问性验收。
    - [x] 4.2.3.1 已提供正式 TMS 目录未启用安全 DTO，可供 UI 区分“外部目录合同缺失”与“学校无用户/空结果”。
    - [ ] 4.2.3.2 尚需正式 TMS UI 接入全部 `/api/v1/tms/*` DTO，并完成目录无权/空范围/空结果/故障、审批 apply、撤权即时生效和可访问性验收。
      - [x] 4.2.3.2.1 已新增正式 `/tms/{schoolCode}` 受控入口壳：只读取当前学校 `/api/v1/tms/me/permissions`、`school-bootstrap/status`、`directory/users`、`members`、`approvals`、`authz-audit`、`skills` 安全 DTO；当前学校身份/绑定/`tenant.*` 授权缺失时失败关闭，不使用合成目录兜底、不显示写按钮。
      - [x] 4.2.3.2.2 已把正式 TMS 写入 UI 接到低风险角色授予、assignment 撤权和已批准审批 apply 安全 API；payload 固定当前学校 DTO 的 principal/assignment/approval ID 与期望版本，不从页面输入切校。
      - [x] 4.2.3.2.3 已接入正式 TMS 额度/用量与服务访问只读 DTO：按权限摘要读取 `/api/v1/tms/quotas` 与 `/api/v1/tms/service-access`，只显示当前学校额度、逐 attempt 用量和访问资格，不展示 OMS 成本、供给来源或 Secret，且不提供额度写按钮。
      - [x] 4.2.3.2.4 已在正式 TMS UI 区分目录未启用、无权、空范围、空结果和外部失败状态；目录不可用时不回退合成用户，本地成员列表与外部目录显示分离。
      - [ ] 4.2.3.2.5 尚需真实目录策略合同、桌面/窄屏/键盘可访问性、审批竞态与双学校真实登录验收。
        - [x] 4.2.3.2.5.1 已用正式 TMS 前端测试覆盖桌面与窄屏视口下的语义 `main`、当前学校/目录/成员/审批 section heading、搜索框 label、成员授权按钮可命名且可键盘触发。
- [ ] 4.3 验证菜单/深链/按钮/API key 一致：无权 403、默认管理员与自定义角色 200、学校码篡改、自己给自己授权、学校 grant 冒充平台 grant、高风险单人授予/越委托上界、成本/Secret/私有正文泄漏、过期/停用/撤权旧页面和审批竞态；桌面/窄屏、键盘、加载/空/无权/外部失败/冲突可访问性。
  - [x] 4.3.1 已在后端 API 层覆盖 TMS 只读/写入/审批切片的无权 403、默认管理员正例、自定义角色正例、自己给自己授权拒绝、敏感角色单人授予拒绝与 Secret/ops 字段不泄漏。
  - [ ] 4.3.2 尚需完成正式前端菜单/深链/按钮与 API key 的逐项绑定、学校码篡改、跨学校真实负例、审批竞态、桌面/窄屏/键盘/加载/空/外部失败等 UI 验收。
  - [x] 4.3.2.1 已用前端测试覆盖正式 OMS/TMS 入口的 DTO fetch、缺授权失败关闭、开发原型不回退、Secret/学校账号开通/写按钮不暴露，以及 TMS 目录未启用与本地成员/审批/审计/Skill 只读渲染。
  - [x] 4.3.2.2 已用前端测试覆盖正式 TMS 低风险授予、撤权、审批 apply 按钮分别调用 `/api/v1/tms/members/{principal_id}/roles`、`/api/v1/tms/assignments/{assignment_id}/revoke`、`/api/v1/tms/approvals/{approval_id}/apply`，并携带 DTO 期望版本。
  - [x] 4.3.2.3 已用前端测试覆盖正式 TMS 额度/用量/服务访问只读 DTO 接线，并验证不暴露授予额度、调整额度、成本或 Secret 写入口。
  - [x] 4.3.2.4 已用前端测试覆盖正式 OMS 模型草稿与 Provider 设置只读 DTO 接线，验证脱敏凭据展示、不泄露 `env:`/`sk-` Secret 且不暴露保存、发布、回滚或测试写按钮。
  - [x] 4.3.2.5 已用前端测试覆盖正式 TMS 目录空范围、空结果与外部失败三态展示，验证不使用合成目录兜底。
  - [x] 4.3.2.6 已用前端测试覆盖正式 OMS 资源、学校、供给、审计、成本只读 DTO 接线，验证只读页面不暴露补充、授权、调整、成本导出或密钥按钮。
  - [x] 4.3.2.7 已用前端测试覆盖正式 OMS 学校用量 attempt 与待核对任务只读 DTO 接线，验证不显示学校私有正文和结算/释放/核销写入口。
  - [ ] 4.3.2.8 尚需学校码篡改/跨学校真实负例、审批竞态和完整可访问性矩阵。
    - [x] 4.3.2.8.1 已用前端测试覆盖正式 OMS 模型/Provider 写按钮与 Skill review/publish/grant 按 `ops.*` key 调用对应 `/api/v1/oms/*` 写 API，验证 version/revision/sha256/school_id 取自安全 DTO。
    - [ ] 4.3.2.8.2 尚需真实跨学校负例、审批竞态、桌面/窄屏/键盘完整可访问性矩阵和 test-cn 真实账号验收。
      - [x] 4.3.2.8.2.1 已用后端与前端合成测试覆盖 OMS 平台授权审批创建/独立复核/apply、显式模板版本确认、低风险学校范围授予、assignment 撤权、主体停用、未委托学校 403 和正式 UI API key/payload 绑定。
      - [ ] 4.3.2.8.2.2 尚需真实跨学校负例、审批并发竞态、桌面/窄屏/键盘完整可访问性矩阵和 test-cn 真实账号验收。
        - [x] 4.3.2.8.2.2.1 已用后端合成 PG 验证审批复核并发与审批 apply 并发均只有一个终态/写入胜出，失败方不会绕过 policy version 或重复写入。
        - [x] 4.3.2.8.2.2.2 已用前端合成 DTO 验证 OMS/TMS 正式入口在桌面/窄屏下的关键 heading、搜索框和写按钮可访问名称及键盘触发路径。

## G/H 验收与受控切换

- [ ] 5.1 仅在既存外部接口、权限迁移、双学校正负例和测试环境独立 OMS/TMS 管理登录通过后，按受控门禁开启对应正式路由；保留 test-cn 脱敏证据、回退、审计关联及当前 upstream mergeability 检查，不把 Webhook mock 或合成 JWT 计作管理权限验收。
- [ ] 5.2 若启用多执行者，先通过 G-H 的跨实例撤权/会话/缓存和审批并发一致性验证；单实例明确非 HA，不为容灾声称静态 UI/单 Pod 通过即可。
