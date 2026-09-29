# 智能体基座 OMS/TMS 双应用域权限体系

> **实施中，完整任务尚未验收；局部结果见 implementation-evidence.md。** 2026-09-27 用户进一步明确：**权限由 DeepTutor Enterprise 程序控制**；PG 只保存权限事实、版本和审计，数据库权限/RLS 不是操作者授权决策器；EduPlus2 在权限链路中只提供认证及稳定身份识别，不提供本产品角色或动作许可。OMS 仅管理平台人员；首位 TMS 管理员的身份由已验签的真实 `subscription.created.actor.user_id` 提供，并在接收该真实订阅 Webhook 的同一业务事务中即时开启，不走旧学校侧双负责人开通，也无需学校管理员再单独开通。用户后续指定事件所属订阅是否仍为当前订阅由 EduPlus2 处理，本产品不额外查询当前订阅 ID。本代理不得修改 EduPlus2 仓库、Keycloak 或 OpenFGA；本文不授权真实数据操作、部署、归档或提交。

## Why

目前 OMS 的 `ops.*` 与 TMS 的 `tenant.*` 权限权威不一致：OMS 已改为 DeepTutor 本地授权，TMS 仍假设 EduPlus2 管理员事件和权限接口会提供完整授权。test-cn 已有签名 Webhook 的 mock 与真实 created/terminated 投递及学校 PG 绑定，**仍不是**两端管理登录、真实首管 actor/sub 合同、在线账号状态或撤权闭环。若继续分别补权限，会出现跨应用继承、首位学校管理员无人开通、菜单与 API 不一致以及撤权竞态。

## What Changes

- 建立一套仅限**智能体基座**的 **DeepTutor Enterprise 应用层授权服务**：它按已认证外部主体 `(issuer,sub)`、独立 `oms`/`tms` 域、动作、对象、`platform`/`school` 范围、有效期、撤权版本及委托上界作决定，默认零权；PG 版本化保存角色模板、自定义角色、assignment、审批与追加审计等事实，并用约束/RLS 作数据完整性和隔离兜底，**不以 PG 用户/角色/GRANT/RLS 命中代替程序鉴权**。OMS `ops.*` 与 TMS `tenant.*` 不互继承，资源 owner/显式 grant 仍独立检查。
- OMS 只负责平台人员、OMS 角色及平台人员在指定学校的 `ops.*` 操作范围；学校账号、学校成员角色与首位 TMS 管理员开通全部归 TMS／学校侧。OMS 不提供学校账号候选、首位管理员审批或学校人员读写 API。TMS 不发放服务权益或额度。
- OMS 对接的 EduPlus2 OAuth Client ID 按用户提供的合同固定为 `eduplus-platform-admin`；实施时须在目标环境核对其授权码登录能力、issuer、实际 token `azp`/`aud`、平台人员身份及账号状态接口。指定 Client ID 不等于已取得平台人员目录，也不自动授予智能体基座 `ops.*` 权限。
- 区分“查找外部用户”与“给已核验主体授权”：TMS 可在第三方应用授权码用户令牌、有效应用凭证/学校订阅和数据访问策略均获证实后，按当前学校的最小范围检索已有账号；目录记录不能直接成为授权主体；普通后续被授权对象仍须本人登录完成 `(issuer,sub,school)` 绑定。OMS 的平台候选只来自可信 OMS 登录登记或另行验证的平台人员合同，不借学校用户目录或通用机器令牌查询。Webhook 下发的 OAuth Client 凭据本身不赋予两端人员目录权限。
- **首位 TMS 管理员来源**：仅接受目标应用、学校绑定和 HMAC 签名均核验通过的真实 `subscription.created` 事件中 `actor.type=user` 且非空的 `actor.user_id`，将其按配置的 OIDC issuer 作为该校初始管理员主体，并在接收 Webhook 的事务内直接创建/激活唯一 `school_admin` assignment；该映射是 DeepTutor Enterprise 的产品策略，不声称 EduPlus2 `actor` 本身就是外部管理员角色。事件订阅 ID 只作审计/幂等，不作本产品当前订阅 ID 比对。`actor` 缺失、system/null、mock、错应用/学校、重复/恢复/重订不得产生新的可用管理权；已消费或已撤销的学校引导不得因重复、恢复或重订事件自动重发。发送端对迟到旧事件的保证尚待真实合同验收；真实 actor 与后续 OIDC `sub` 的等值/映射仍需 test-cn 证据。后续学校角色由 TMS 本校授权服务管理，OMS 不管理学校账号。
- 为 OMS 的“平台人员／角色与动作／平台人员学校范围／授权审计”和 TMS 的“Webhook 首位管理员状态／成员与权限／角色／应用及服务访问／资源授权”设计完整入口、列表→聚焦详情→独立操作模态框、有效权限预览、变更确认、审批、撤权回读和失效状态。两端独立构建、会话和 API；共用组件只接安全 DTO，不共享授权缓存。
- 每条管理 API 和已启用的 CLI、HTTP/WS、SDK、后台路径必须调用同一 DeepTutor Enterprise 授权服务；认证得到的身份标识仅用于定位本产品主体，写事务由程序重新核验主体、动作、对象、范围、学校绑定和业务版本。PG 事务锁/约束只保障并发和隔离，不自行决定操作者是否有权；EduPlus2 权限 API、旧管理 router、请求 header、JWT role、`eit=adm`、Webhook secret、原型 fixture 均不得授予本产品权限。
- **BREAKING**：撤销旧 `ops.tms.bootstrap`、OMS `/tms-bootstrap-requests` 及 TMS 学校侧双负责人首位开通规划；改由签名真实 `subscription.created.actor` 在 Webhook 接收事务内触发 DeepTutor Enterprise 一次性初始学校管理员授权。现有 8/8 mock 204 仅证明接收，绝不创建管理员。OMS 从不接触学校管理员账号或本产品 `tenant.*` 授权。

## Capabilities

### New Capabilities

- `enterprise-management-authorization`：OMS/TMS 双应用域权限、首位 TMS 管理员开通、服务端鉴权与两端权限 UI 契约。

### Modified Capabilities

无。现有活跃 OMS/TMS change 的 proposal/design/spec/tasks 同步引用本 change，不在归档正式 spec 上作未批准修改。

## Impact

实施时仅在 `extensions/enterprise/` 增加本仓库 Enterprise 授权服务、PG 事实迁移和 `/api/v1/oms/*`、`/api/v1/tms/*` 适配器；core 如有改动仅限 upstream-neutral 认证/权限/上下文 seam 并单独记录合并风险。EduPlus2 仅提供适用的 OIDC/稳定身份识别，学校生命周期另按 Webhook 业务合同处理，均不作为本产品权限决策器；可信学校绑定、初始学校侧管理员授权仍须由本系统在真实订阅 Webhook 中受控建立。现有身份合同不满足时对应正式写入口继续关闭，不由本代理改动发送端。开发原型仅用标注的合成数据演示，生产原型路径保持 404。
