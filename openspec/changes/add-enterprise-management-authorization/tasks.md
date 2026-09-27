> **实施中；任务 1.3 入口盘点与 3.1 PG 事实迁移已完成，其余完整任务未完成，证据见 surface-inventory.md 与 implementation-evidence.md。** 2026-09-27 用户进一步明确：DeepTutor Enterprise 程序负责授权决策，PG 只保存事实并提供隔离/一致性兜底，EduPlus2 在权限链路中仅负责认证及身份识别。OMS 仅管平台人员；首位 TMS 管理员来自签名真实 `subscription.created.actor.user_id` 并须本人登录激活，旧 OMS/学校侧双人首位开通与外部负责人权限依赖撤销。只修改 DeepTutor；测试仅用隔离合成数据，真实租户数据、生产发布、提交、归档另行授权。此轮权威再修订需同步受影响提案并复核 1.1，不授权真实数据、外部系统修改或发布。

## P0 契约与证据

- [ ] 1.1 请用户审阅并分别批准本 proposal/design/spec/tasks 及被本 change 影响的 OMS/TMS 提案；明确旧 TMS 外部管理员权限事件/双负责人开通不是本产品授权实现依据，旧版批准不自动适用。此前 PG 事实库版曾逐项获批；最新用户要求把决策权明确放在 DeepTutor Enterprise 程序，并以真实订阅事件 `actor` 作为一次性首位管理员身份来源，须同步受影响修订版后复核，不以旧勾选代替当前合同。
- [ ] 1.2 建立脱敏外部**认证与身份识别**能力证据矩阵：复用 test-cn Webhook 8/8 mock、已验证 discovery/JWKS/M2M/resolve；区分文档可见、用户指定配置与真实 API 可用。以 `eduplus-platform-admin` 为 OMS 指定 Client ID，实测目标环境的授权码登录、issuer、`azp`、audience、稳定平台主体与身份有效性；另核 TMS 当前学校身份及条件性第三方应用授权码用户令牌的学校成员目录/策略范围。核对真实 `subscription.created` 的 HMAC、应用/学校 ID、`actor.type`/`actor.user_id` 与后续 OIDC `sub` 匹配语义；8/8 mock 不能算真实首位管理员证据。`/me/profile` 不是他人查询，Webhook Client/M2M `/api/v1/users` 示例不是已验收的成员目录；**不向 EduPlus2 索取本产品动作授权或负责人角色判定**。身份合同缺失时保留相关写路由未装配，不修改 EduPlus2。
- [x] 1.3 盘点全部 OMS/TMS 菜单、按钮、API、导出、旧 router、CLI/HTTP/WS/SDK/后台及 owner/grant；固定动作 key、`platform`/`school` 范围、默认角色、自定义角色上限和“旧入口 404”清单，并审阅通用 core seam 的上游合并风险。证据见 [surface-inventory.md](surface-inventory.md)；正式新路由逐条权限验收仍归 3.2、4.3、5.1。

## B1 身份与学校绑定

- [ ] 2.1 将已核实的外部 OIDC/身份适配器接入独立 OMS/TMS 会话：OMS `(issuer,sub)`，TMS `(issuer,sub,school)`；验证错 issuer/audience、普通租户 token 冒充 OMS、身份失效、学校身份错配、过期/错学校 token、CSRF/Origin、会话互换与接口故障失败关闭。学校停用由独立 lifecycle 业务状态阻断，不使用外部权限决定 `ops.*`/`tenant.*`。
- [ ] 2.2 对 `oms.school_bindings` 增量添加经权威核验的创建/撤权/版本栅栏及外部 ID 类型适配；不改已应用 `0011`，不从 `schoolCode`、`external_tid` 或 header 猜测绑定。隔离合成数据验证一对一、改码、解绑、漂移与双学校负例。

## B2 本产品权限与安全开通

- [x] 3.1 测试先行并新增 DeepTutor 企业 PG 后续版本**权限事实**迁移：主体、两应用域、角色/动作目录版本、授予委托上界、范围/有效期/assignment、policy version、审批请求和追加审计；验证默认零权、RLS 隔离兜底、唯一性、幂等、重复 apply/verify、drift、旧管理员不自动提升、最后管理员保护和回退。迁移不等于程序授权服务交付。
- [ ] 3.2 实现 **DeepTutor Enterprise 统一 PEP/授权服务**与 `require_management_permission(app,action,scope,object)`：由程序按 OMS/TMS 域、已认证身份、本地授权事实、学校绑定、业务状态和 owner/grant 判定；PG role/GRANT/RLS 只做兜底，不能直接放行业务。写事务锁定复核权限/绑定/业务版本并与撤权串行。跨 CLI、HTTP/WS、SDK、后台无直写旁路；未装配旧核心管理 router。
- [ ] 3.3 实现 **Webhook 一次性首位管理员登记与本人激活**：仅真实、已验签、非 mock、目标应用/学校及订阅 ID 结构校验通过的 `subscription.created`，且 `actor.type=user`、`actor.user_id` 非空，才写入该校待激活 `(issuer,sub)` 与一次性消费栅栏；事件 ID 幂等、学校绑定版本及已消费/撤销引导不得复活。事件订阅 ID 仅作审计/冲突依据，不作为本产品当前订阅 ID 比对门禁。本人 TMS 登录后须精确匹配已登记身份和当前学校，Enterprise 程序在事务内复核当前学校—应用有效及本地版本，激活唯一 `school_admin` assignment、追加审计。`actor` 缺失/system/null/错校或身份不匹配保持零权；OMS 无学校账号/开通入口。真实事件合同及联调未通过时正式写接口保持关闭。
- [ ] 3.4 实现 TMS 当前学校 `tenant.permissions.manage` 的角色/成员/应用/服务访问管理，模板扩权须显式确认、高风险授权双人审批、委托能力与业务执行权分离、收缩与撤权立即生效；服务 grant 不带额度数量、不越过 OMS 授权，个人正文仍按 owner/显式 grant。

## C1/C2 独立正式 UI 与原型

- [ ] 4.1 修订 OMS 开发原型的平台人员/角色/学校操作范围/审计合成场景，删除旧学校后台开通入口及直达深链；平台候选仅来自可信 OMS 登录登记，目录未核实时显示未启用。正式 OMS 接真实平台权限 API 的列表、聚焦详情、操作模态框、权限差异、原因/审批/版本、状态 descriptor 和审计回读。无数据源显示未启用，生产原型路径 404。
- [ ] 4.2 修订 TMS 开发原型的 Webhook actor 待激活/本人登录匹配、缺 actor 待核对、成员/角色/访问关系/撤权状态，并演示“搜索可见已有账号→本人登录登记→匹配后授权”及目录无权/空范围/空结果/故障的区别；不得把合成目录伪装成真实 EduPlus2 同步，旧双人首位开通按钮不得保留为正式入口。正式 TMS 仅在第三方应用用户令牌及策略范围获证实时接学校目录，且只接当前学校安全 DTO；双向关系回读同一事实，额度/用量保持只读，不共享 OMS 会话、API client 或专有字段。生产原型路径 404。
- [ ] 4.3 验证菜单/深链/按钮/API key 一致：无权 403、默认管理员与自定义角色 200、学校码篡改、自己给自己授权、学校 grant 冒充平台 grant、高风险单人授予/越委托上界、成本/Secret/私有正文泄漏、过期/停用/撤权旧页面和审批竞态；桌面/窄屏、键盘、加载/空/无权/外部失败/冲突可访问性。

## G/H 验收与受控切换

- [ ] 5.1 仅在既存外部接口、权限迁移、双学校正负例和测试环境独立 OMS/TMS 管理登录通过后，按受控门禁开启对应正式路由；保留 test-cn 脱敏证据、回退、审计关联及当前 upstream mergeability 检查，不把 Webhook mock 或合成 JWT 计作管理权限验收。
- [ ] 5.2 若启用多执行者，先通过 G-H 的跨实例撤权/会话/缓存和审批并发一致性验证；单实例明确非 HA，不为容灾声称静态 UI/单 Pod 通过即可。
