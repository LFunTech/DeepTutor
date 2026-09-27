# 执行证据（2026-09-27）

## 审批与边界

用户已单独批准本版 proposal/design/spec/tasks 按现版实施（任务 1.1）。本轮仅完成规划、依赖盘点和现有实现只读核对；B1/B2 的学校绑定迁移、真实外部适配器、双学校全入口验收和 G2 放量均未完成。隔离合成验证之外，不修改 EduPlus2、Keycloak、OpenFGA，不触碰真实学校数据，不发布或归档。

## 既存合同证据矩阵（任务 1.2 尚未完成）

| 能力 | 已有证据 | 对本 change 的结论 |
| --- | --- | --- |
| OIDC/JWKS、普通 user JWT 与 client resolve | 已归档 `enterprise-eduplus2-federated-access` 及 2026-09-18 test/本地只读证据；当前 `eduplus2/client.py` 验 JWT，`service.py` 校验注册/resolve/profile/permission | 可复用普通换票机制；不是 OMS/TMS 独立管理会话或权威学校绑定验收。 |
| 本人 Profile / 学校目录 | 开发者文档只读证明 `/api/v1/me/profile` 是本人；学校成员目录另需授权码用户令牌、订阅和策略范围 | 不能把本人 Profile、M2M `/api/v1/users` 示例或目录结果直接当作外部学校权威/学校负责人资格。 |
| 账号在线状态、学校稳定 ID/类型/状态、改码与解绑 | 本仓库现无可脱敏引用的已交付管理适用性实测合同；`oms/0011_school_binding.sql` 仅假设数字外部 ID、表内尚无当前权威接口证明 | 学校绑定创建/撤权、管理敏感写和真实 B1 门禁保持关闭；不改变 `0011` checksum，也不从 `school_code`/`external_tid` 推断。 |
| 生命周期 Webhook | test-cn `智能体基座` 控制台签名 mock 8/8 HTTP 204；真实事件未受理 | 只证明 demo URL/验签，不提供稳定学校 ID、账号状态、管理员资格或 G2 撤权证据。 |

后续核验必须记录接口版本、环境、调用身份、脱敏响应、学校 ID 类型、失效/故障及撤权窗口；未验证项不得用 fixture 代替。

## 当前入口与数据面盘点（任务 1.3 进行中）

- `api/application.py` 的 `AuthenticationMiddleware` 对 HTTP/WS 检查 Origin/CSRF、禁止租户 header/query override、在已签发普通 token 后调用 `ensure_token_allowed`；正式 OMS/TMS 路由未装配。因此普通换票 guard 可复用，不能据此宣称管理登录或双学校资源隔离已完成。
- `eduplus2.identity_bindings` 已按内部 `tenant_id` 存 `(external_tenant_id,external_user_id,external_subject)` 与本地用户；表的现有主键只在一个内部 tenant 内唯一，不是外部学校 ID 对内部 tenant 的全局权威一对一绑定。`eduplus2.external_client_registrations` 的 active client 与 `(provider,external_tenant_id,external_app_id)` 有唯一索引，但 client 注册不是学校状态权威。
- `oms.school_bindings` 的后续权威创建/撤权/版本迁移由 `add-enterprise-management-authorization` 任务 2.2 持有；本 change 不再建第二套 OMS 学校表。其外部 ID 类型尚须按已交付接口确认，不能现在通过重复的 `eduplus2` 学校表掩盖该缺口。
- 管理授权 change 后续已加 `oms/0012` 绑定版本保护和 `management/0003` 学校 assignment 版本栅栏：重绑后旧 OMS 学校授权在本地决策中失效，但这仍是隔离合成迁移验证，不证明 EduPlus2 稳定学校 ID、真实绑定登记或 B1/B2 双学校接入已验收。
- 仍需逐项盘点 PG/RLS、S3 下载、LightRAG workspace/图、缓存、事件订阅、SDK/CLI 与后台任务的调用者、owner/grant 和双学校负例。盘点未完，任务 1.3 保持未勾选。

### 2026-09-27 源码级路径矩阵补充

| 路径 | 当前可信边界/已有负例 | B1/B2 尚需补齐 |
| --- | --- | --- |
| 企业 HTTP/WS | `api/application.py` 仅白名单装配普通 exchange、资源、session、WS、审计、health；`AuthenticationMiddleware` 拒绝租户 header/query override，`SocketAuthentication` 对新命令重新校验，`test_isolation_matrix.py` 已有同租户 owner 与两个固定部署同名 ID 负例。core `api/main.py` 仍有旧治理 router，但未挂企业 app。 | 真正多学校来自同一个企业部署时的可信 binding epoch；单独两个固定部署的测试不等于 B2。管理 router 在合同/权限通过前保持 404，普通 token 不复用 OMS/TMS 会话。 |
| SDK/CLI | `runtime.py` 的 `StoreProvider.get()` 从企业身份上下文取固定部署学校，`TurnEnvironment.authorize_request()` 走同一企业 `authorize()`；`test_oms_management_entrypoints.py` 确认企业 CLI 和通用 SDK 不发布 OMS/TMS 写命令。 | 若以后增加管理命令必须复用逐动作授权；普通 SDK 在动态多学校下仍需每操作 epoch/当前学校复验。 |
| PG/RLS 与个人资源 | `persistence/postgres/connection.py` 对显式 `TenantScope` 用事务局部 scope，`session.py`/对象与 `test_isolation_matrix.py` 覆盖固定部署 owner/租户负例。 | 多学校同部署的身份→scope 派生、连接复用/取消/后台并发及跨 owner 显式 grant 需独立验收；不能只靠业务查询条件。 |
| S3/下载 | `persistence/postgres/object_resources.py` 的对象 key 带内部学校和 owner hash，PG 元数据查当前 owner；`api/application.py` 仅装配 `resources` 受控路由。 | 短期上传/下载 URL 撤权窗口、跨校 key 猜测和资源二次检查仍需目标 ObjectStore 实测。 |
| KB/LightRAG/图 | `knowledge_bases.py` 先按当前 owner 的 PG 资源清单筛选 KB；但 `EnterpriseLightRAGTool.execute()` 调用 `LightRagServerClient.query_context(query, mode)`，调用本身**未携学校/KB/index-version**，只使用配置的部署 binding。 | 不能把“PG 列表里只看到本校 KB”当作远端检索隔离；须由服务端可信 workspace/KB binding、受限检索身份及双校图事实负例补齐，未验证前不得开放同一检索部署多校查询。 |
| 任务/协调 | `services/cron/postgres.py` 按固定 `tenant_id` 枚举 owner scope，`cron/executor.py` 从持久 owner 恢复执行；Redis coordinator 的 `key_prefix` 是部署配置，底层 turn key 主要按 turn/session ID。 | 动态多校时任务须携学校 binding epoch 并在派发前重验；Redis 键空间/碰撞与跨实例撤权需双校/G-H 验证，不能把固定部署或单实例测试外推。 |

**上游可合并 seam 判断**：优先在企业扩展中派生可信学校与检索 binding，core 只新增一般化的 scope/任务 checkpoint/协调 namespace 接口（若现有 provider 无法表达时）；不得在 `ChatOrchestrator`、检索工具通用实现或核心 session 存储中硬编码 EduPlus2 `school_code`。尚未形成所有资源/后台路径和旧路由的穷尽清单，任务 1.3 仍未完成。

## 本轮验证

- `openspec validate add-b1-b2-trusted-school-integration --strict` 和 `openspec validate --all --strict`：本轮全量 **28 passed、0 failed**。这是文档/契约有效性，不是 B1/B2 业务验收。
- 同轮企业后端全量测试 **376 passed、3 skipped**；这些测试覆盖固定部署下既有部分隔离路径，但**不**计作动态双学校、外部权威学校合同或远端检索隔离通过。
