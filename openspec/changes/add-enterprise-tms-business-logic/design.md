# 设计：TMS 正式业务逻辑与租户边界

## Context

范围见 [proposal](proposal.md)，行为验收见 [delta spec](specs/enterprise-tms-business-logic/spec.md)。[TMS 原型](../add-b2-tms-management-prototype/design.md)已决定六组列表→详情 IA、独立云端前端和一级只读配额清单，但不是生产身份、API、grant 或 KB 实现。[OMS 业务契约](../add-enterprise-oms-business-logic/design.md)定义平台资源、服务授权、配额与真实消耗的写入权威；TMS 不建立平行总账。现有 `docs/enterprise/11-*`、`12-*` 中“微调 DeepTutor 管理页面”“TMS 管配额”“OMS 只读/Token 欠费”的历史段落仅作旧方案证据，不可直接实施。原型里“使用分配”等模糊话术一律解释为**服务访问 grant**，不是额度分配；正式开发前应同步原型文案。

## 对话决策的业务落点

| 已确认原则 | 此前落点/缺口 | 本 change 补足的正式开发基础 |
| --- | --- | --- |
| TMS 面向学校/企业租户，独立部署并复用 OMS 业务组件 | 原型确定六组导航与 OCR 列表共享，未交付真实 API | 当前租户 DTO/权限、独立入口、组件版本及生产隔离 |
| 租户开停由 EduPlus2 管，TMS 管本租户应用与成员 | 旧文档有 client 规则，尚无正式单租户动作契约 | 权威 resolve、active 唯一/注销、分源状态和审计 |
| OMS 授权租户服务，TMS 只能在其范围内配置内部使用资格 | 原型有原则，但容易误称“分配额度” | 绑定 OMS 授权代际的成员/应用/后台访问 grant；无配额数量字段 |
| TMS 配额清单是一级列表，但**只能查看** | 原型已订正，缺真实投影与拒绝写入规则 | 同一赠送/充值列表、跨授予 attempt 明细、只读 API/直调负例 |
| 知识、内容、运行资源有平台/租户/个人作用域 | 资源清单仅盘点，旧管理页不足以隔离 owner | KB/文档/引用/任务真实状态、私有 owner 与分享权限 |
| 用量需精确可追溯且服务耗尽不阻断管理 | OMS 原型有展示原则，TMS 无正式数据契约 | 当前租户只读用量、待核对/供给不足/额度不足区分及安全导出 |

## Goals / Non-Goals

- 目标：使学校/企业租户管理员在**一个可信当前租户**内安全管理应用、成员访问权限、知识资源，并看懂 OMS 配额及真实使用；每个 TMS 动作可映射到后端校验和审计。
- 非目标：TMS 不管理租户 lifecycle、平台 Provider/Secret、供应商采购、租户服务总授权或任何配额写入；不自动读取个人私有内容，不另建 EduPlus2 用户/组织主数据。

## Decisions

### 0. 学校智能体管理后台的命名、入口与管理员来源

TMS 技术缩写、独立部署和 `/tms` 路径保持不变，对外产品名称为**学校智能体管理后台**。在当前 EduPlus2 教育业务里，一个 `tenant` 就是一所学校，`school_code` 是学校 tenant code；界面和学校/运营人员使用的业务术语称“学校”，而 `tenant_id`、`tenant.*`、Skill `owner=tenant` 是保留的底层技术契约。`school_code` 不是稳定学校 ID，不能单凭 code 授予学校权限；其唯一性、规范化及改码处理须由 EduPlus2 权威契约确认。

正式入口 `/tms` 在认证且绑定唯一学校后跳转至 `/tms/{schoolCode}`。该前缀下有成员、应用、服务、Skills、配额、知识库、用量和事件的列表路由及稳定资源 ID 详情路由；详情在列表背景上以抽屉呈现，直接打开或刷新仍恢复同一列表与抽屉，维护动作使用模态框。筛选/分页/tab 只作为界面查询参数。侧栏、面包屑、关联对象跳转保留已核对的学校 code 和返回上下文，禁止任意 `returnTo` 跳向别的学校或域名。开发原型目标为 `/tms/prototype/{schoolCode}`，与正式数据和生产 404 隔离；现有 `/tms/prototype` 是待迁移的开发路径。

EduPlus2 各学校管理员账号完全隔离，一个管理员账号只归属其学校，不建立跨学校选择器。学校管理员记录及其学校/角色关联应由签名 webhook 同步/变更/撤销，以外部学校稳定 ID + 外部用户稳定 ID 建立受控映射；密码和登录凭证不复制到 TMS。登录须独立验证 EduPlus2 身份、学校绑定与实际管理权限；收到 webhook 不是已登录或已授权。管理员事件需定义签名、版本/幂等、乱序、对账、撤权和登录时失效判断，事件 schema 与发送端能力尚待 EduPlus2 确认，未知或超时绑定按 fail closed 处理。现有 `add-b2-eduplus2-tenant-lifecycle-webhook` 只处理学校开停，不承载账号同步。账号同步所需 PG 身份映射/inbox 走版本化迁移；OpenFGA/Keycloak 如确需变更关系或 claim 才各走受控迁移，不因业务改称就迁移既有技术键。

路由请求必须先由服务端取得可信学校 ID 和规范 code，再核对 URL code、具体 `tenant.*` 读写能力、资源学校归属及 owner/grant；不符合时不返回目标学校数据。主题查询同样使用核对后的学校 code 和 EduPlus2 tenant ID，不让路径或品牌接口响应充当认证。学校服务额度耗尽只限制相应服务新调用，不阻断管理员登录、管理路由或历史查询。

### 1. 一个可信租户上下文，角色不能代替资源授权

TMS 后端从已验证主体/会话取得 `internal_tenant_id` 和绑定的 `external_tenant_id`；路由、筛选和写入体里的 tenant 字段仅作为一致性检查，不作为授权依据。入口、菜单、按钮、API、导出、WS/SDK 后续业务操作都用同一租户 scope 与具体 `tenant.*` 动作能力。`tenant_admin` 可管理其被明确允许的租户资源，但不因角色默认读取他人的 session、memory、notebook、私有文件或 KB 正文。共享资源的读取仍由 owner/显式读取 grant 定义；**转授权**仅由 owner 或另获分享/授权能力的主体执行，读取 grant 本身不能转授权。管理元数据、读取正文、导出与分享是不同动作。拒绝“前端锁定租户下拉框即可隔离”以及“同租户管理员拥有所有内容”。

EduPlus2 继续权威维护外部租户、组织、用户、client/app 身份；TMS 展示必要同步信息与最后可信版本。外部资格、DeepTutor 本地隔离、资源就绪状态分源，不把某个旧 active 字段当全部准入事实。生命周期 webhook 的签名/重放/对账由重订后的独立 B2 change 交付；TMS 仅订阅可信投影并展示异常，不提供开停租户按钮。

### 2. 将“服务访问 grant”与“OMS 配额授予”拆开

服务对应用/成员/受控后台主体的允许使用关系建为作用于当前 tenant 的访问 grant；必须引用 OMS 已授权的 service ID **及该租户服务授权 ID/代际**，并受目标主体、资源范围、版本、操作者和撤销记录约束。它只有布尔或具体能力范围语义，**没有数量、余额、上限、充值、赠送、来源批次**等配额字段。OMS 撤销租户级服务授权后，绑定旧代际的 TMS grant 立即失效；即使后来重新授权同一 service ID，也须 TMS 重新显式授予，不能复活旧 grant。额度调整本身不改变访问 grant，但影响实时可调用性。新增 service 类型时从共同安全 descriptor 映射到相同服务列表，OCR 必须是真实解析服务而非前端虚构 provider。

调用交集：租户外部资格与本地资源就绪 ∧ OMS 租户服务授权 ∧ TMS 适用访问 grant ∧ 资源 owner/grant ∧ 平台配置 readiness ∧ OMS 租户额度 ∧ 兼容供给。直接用户需成员/显式群组 grant；应用委托用户需应用和成员两者的 grant；纯应用需应用 grant；后台任务需可信 job 归属及独立服务主体 grant；Agent 子调用继承原主体。相应主体或 grant 缺失即拒绝，不因 user/app ID 为空跳过授权。TMS 只负责访问 grant 与自身资源权限，配置、额度、供给由 OMS/DeepTutor 执行链校验。拒绝在 TMS 新增“成员额度/应用额度/内部上限”以规避只读原则；未来需要硬预留/子配额时必须另提变更。

### 3. Client/app 注册遵循权威解析与生命周期

注册流程：校验 `tenant.clients.manage` → 绑定当前 tenant → 接受 `client_id` → 通过 EduPlus2 resolve/等价权威契约取 external tenant/app/client ID 与状态 → 与当前绑定完全比对 → 检查同 provider active client ID 和同 tenant/app active 唯一性 → 幂等写入注册与审计。外部调用的 token exchange 仍须独立验签、状态复核与归口判断；TMS 的一条记录不能让未经验证的 JWT 自动可信。注销/retire 保留历史、请求 ID 与影响说明；换 client 要先使旧注册不再 active。外部解析失败显示不可验证，不允许仅凭人工填入名称先激活。与 [既有入口契约](../../../docs/enterprise/11-api-and-entrypoints.md)保持 URL 兼容，但旧文档的配额/OMS 权责段须重订。

### Skill 的 tenant owner、上传与同名选择

TMS 使用可信当前 tenant 作为提交包的唯一 owner；管理员只能通过完整 ZIP 创建/更新 tenant Skill，受控 Hub 导入须实际取得并校验同类包，不接受单文件 `SKILL.md`、手填正文或仅凭 URL 建立 Skill。服务端必须独立解析 ZIP 与 `SKILL.md`：唯一包根、有效 YAML frontmatter（`name`、`description` 必填）与非空正文、目录名匹配、资源白名单及危险路径/链接/重复/加密/损坏/膨胀限制。名称、说明、标签、依赖及 `always` 等内容元数据只从该文件读取；owner、来源、审核/发布状态和不可变包摘要由可信上下文生成，不接受请求或包内自报覆盖。脚本与自动注入须先安全审查，不能把浏览器预检当审查结论；不能直接复用当前用户级 `/api/skills` 冒充企业租户写入。与当前租户**已获授权**的 global Skill 同名时，提交前显示两条 owner 与 tenant 发布后优先的影响，独立确认模态框由管理员明确确认；取消不保存，未获授权 global 名称不泄露。发布后的 tenant Skill 仅本租户使用，不经 OMS 再授权，也没有成员/应用二次分配。

tenant/global 可同名但不能混为同一记录；运行时 manifest、`read_skill` 正文与参考文件统一按 tenant 已发布版本优先，其次已发布且已授权 global 版本解析。tenant 版本暂不可用不回退 global；撤销 tenant 版本前提醒 global 将可能恢复。OMS 后授权同名 global 时也标明被本租户版本覆盖。Skill 自身不形成独立额度，实际服务调用仍走服务授权与配额准入。

DeepTutor builtin 在云端只是 `owner=global, source=builtin` 的只读来源，默认无租户授权；TMS 不应接收未授权 builtin 的目录或正文数据。OMS 授权后 TMS 展示其打包版本/说明和运行条件，`requires` 缺失时标为暂不可用；与之同名的 tenant 上传仍须管理员确认并由 tenant 版本优先。云端运行时对 manifest、`read_skill`、显式请求与 `always` 注入使用相同过滤，不能因本地 DeepTutor 默认自动发现 builtin 就在企业入口绕过 OMS。TMS 不修改 builtin 内容，程序升级引起的版本变化由 OMS 复核；本地产品行为不变。

### 4. 配额只是当前租户的受控只读投影

TMS `QuotaList` 消费 OMS 授予和 DeepTutor 用量的当前租户投影：同一列表中 `gift|recharge` 筛选，服务→配额详情→单次消耗通过授予 ID 与 attempt ID 关联。一个供应商 attempt 可分摊至多笔授予；配额详情各显示自身份额，服务用量按 attempt 去重而不把分摊行当多次调用。列表和详情展示总量、已用、剩余、有效期、来源/状态及待核对标识；金额、供应商成本、Secret 和其他租户记录从服务端 DTO 白名单中排除。**配额与用量**只提供 GET 类查询与受控导出，不存在 TMS 配额/用量写路由；**服务访问 grant**另有具体权限保护的写路由，两者不得混用。配额页面没有模拟写按钮。权限拒绝、数据缺失、同步延迟和额度用尽使用不同状态，不将“没有记录”当作“零余额”。

若 OMS 配额/计量尚未正式交付，TMS 不能用浏览器 fixture 冒充生产额度；可只显示“数据暂不可用/待核对”并阻断依赖精确额度的正式承诺。配额耗尽只拦对应服务的新调用，TMS 登录和管理仍可用。OMS 对配额的调整须通过版本化事件/查询一致性机制进入投影；TMS 无本地余额权威，不直接修改投影以制造即时成功。

### 5. KB、文档和任务仍以业务 owner 为中心

TMS 管当前租户获授权的 KB、文档、共享资源及业务任务的元数据与允许的动作。受控资源 ID 在服务端验证归属后解析到已登记的 LightRAG binding；TMS 不接图/检索内部数据库，不传任意 Server URL、workspace、密钥或原文路径。KB 申请/池领取与索引 ready 是不同状态；文档导入、失败/重试、托管删除和非托管连接解绑也各有不同后果。引用和派生文件读取仍须重新校验 owner/显式 grant。业务任务取消只产生意图，远端确认和用量对账另由原业务归口完成；TMS 管理界面不升级为运维控制台。

### 6. 共用业务组件，独立部署与安全 API

云端 OMS/TMS 分别构建和发布，共用 `admin-ui` 与 `service-components` 的兼容版本；OCR 服务列表/详情的列、筛选、分页、状态、键盘和导航行为在两端一致。共用视图模型只含安全的交集字段，OMS 供给/成本/配置动作和 TMS 成员/应用关系由各自容器装配，不在组件内塞 `isOms/isTms` 权限分支。两个前端可以共用一个模块化后端进程，也可拆部署；后端仍须分别暴露 OMS 平台权限 API 和 TMS 当前租户 API，不能用单一无范围通用 admin API 加前端隐藏字段。DeepTutor 本地 Web 独立于这两个云端构建，保留其本地设置与个人使用体验。

## Risks / Trade-offs

| 风险 | 缓解 |
| --- | --- |
| TMS 服务访问 grant 被误认作成员额度 | grant 契约不含数量/余额/上限；配额 API 只读、写入直调负例 |
| EduPlus2 状态延迟或 resolve 故障时错绑 client | 注册 fail closed，保留待核对/失败状态与重试审计，不接受手工猜测 tenant |
| 同租户管理员越权读取个人内容 | 管理元数据与正文分别授权，owner/显式 grant 的 HTTP/WS/SDK/下载负例 |
| 共用组件把 OMS Secret/成本投到浏览器 | 服务端 DTO 白名单和导出/日志/浏览器载荷检查，两端独立构建回归 |
| OMS 配额、TMS 投影和调用准入短时不一致 | 版本/时效标记、服务端真实准入权威、待核对而非本地乐观扣余额 |

## Migration Plan

1. 用户审阅本 proposal 与 OMS 业务契约；B1/B2 实施提案及 `docs/enterprise/02-*`、`11-*`、`12-*` 重订单体 Web、配额写入和 OMS 只读的旧内容。不得因文档校验就把 TMS 当作已批准生产实现。
2. 先落可信身份/当前租户、成员及资源 owner/grant，再落 EduPlus2 client 注册/注销与服务访问 grant；采用版本化 PG migration，外部 OpenFGA/Keycloak 关系或 claim 真有变化才按各自受控迁移流程执行。原数据回填应保留 owner、client 历史与撤权，不把旧 admin 标记提升为跨租户权限。
3. 接入 OMS 只读配额投影、DeepTutor 逐调用用量及 KB/文档任务服务；分别验收正常、跨租户、失联、待核对、额度耗尽和权限撤销。前端迁入独立 TMS 构建，只在真实 API/权限/数据验收后开启正式 `/tms`；开发 `/tms/prototype` 与生产 404 保持隔离。
4. 切换/回退保留上版兼容前端和 API 契约，client/grant/审计及用量历史不得因回滚删除；多实例前另经 H/G-H。若必须调整 DeepTutor 核心，仅提交 upstream-neutral seam 经严格审阅，未获批准不修改。
