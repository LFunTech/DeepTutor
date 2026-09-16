# 07. 资源存储替换与租户隔离

## 阶段职责

- **M1 / A1–A3**：A1 结构化状态、A2 文件/检索分别闭环，A3 集成验收；固定生产 tenant、多用户所有权生效；双租户测试 namespace 与图权限负例进入 G1，不等 M2 再设计。
- **M2 / B1–B2**：B1 先验证首租户最终接入/权限，B2 完成多租户、租户管理 UI、配额及后台隔离。
- **M3 / C1–C2**：C1 运营管理闭环，C2 查询/任务治理完善，不再换存储。

本方案不再提供新的租户文件目录作为企业部署模式，用户已取消 local/SQLite 运行 profile。默认本机/CLI/SDK 同样使用 PG；SQLite 只允许独立只读导入与旧格式 fixture。普通已有文件载荷与企业 S3/scratch 分类仍按本领域契约处理，不把 PG-only 等同于全部文件已经迁移。

本表是全系统资源去向，不等于 DeepTutor 直连所有存储：DeepTutor 操作应用 PG/S3 并通过 LightRAG API 管理检索资源；检索 PG 和 HugeGraph 由 LightRAG 写读/删除/恢复。文档删除的图来源清理由 LightRAG 执行，DeepTutor 不直接调用图 API 或 drop。

## 替换清单

| 资源 | 最终持久化 | 阶段一必须覆盖的调用 | M1 应交付基础隔离，M2 扩展/复验 |
| --- | --- | --- | --- |
| sessions/messages/turns/events | PostgreSQL | HTTP、WS、SDK、历史、resume/regenerate/cancel、后台清理 | tenant + owner；跨 Pod 状态归 H，启用多执行者前验收 |
| memory/notebook | PG 内容/metadata；文件附件 S3 | agent 读写工具、管理 API、快照/搜索 | tenant + owner；共享需 grant |
| settings/model catalog | PG metadata + Secret 引用 | 页面保存、运行时加载、缓存失效 | 平台默认、租户策略、用户偏好分层 |
| identities/grants/audit | PostgreSQL | 登录、授权读取与写入、管理审计 | 外部映射、tenant scoped grants/审计 |
| KB | 应用 PG metadata/binding/job + S3 原文/解析文件/服务派生副本 + 已选 RAG 的外置索引 | A2 按已选 LightRAG 接通完整生命周期并完成生产验收；非托管连接只解绑 | 个人/共享 KB、检索前授权、provider namespace 及数据库防线 |
| attachments/workspace/生成物 | S3 + PG object_assets | 上传、工具文件输入输出、引用、预览/下载、过期清理 | tenant + owner/grant；无任意 key |
| 可编辑 skills/personas | PG metadata + S3 正文 | 编辑、加载、版本与执行读取 | 平台只读模板、租户分发/用户授权 |
| partners/MCP/cron/exec/subagents | 启用时 metadata/job 入 PG，文件 S3，凭证 Secret | 所有回调、执行和调度路径 | tenant context、沙箱、配额、网络权限 |

仓库内随镜像分发的只读 prompts、内置 tools/skills 不属于用户可变状态，可以继续随镜像发布。生产资源/Store 实现位于独立企业包，核心服务、API、agent 工具和后台任务通过通用 seam 调用，禁止只替换页面请求而遗漏工具直写；职责清单见 [13](13-deployment-and-upstream-sync.md)。

## S3 内容清单与权威归属

分类依据是**业务语义和持久化需求**，不是原文件扩展名或所在目录。下列清单覆盖全部已启用功能；首发未启用的可选能力不因此变成必交付，但既有必需能力不能静默删除。

| 内容 | 权威存储与管理者 | 保留、引用和删除规则 |
| --- | --- | --- |
| KB 原始资料 | 企业 ObjectStore 的 S3 原文；PG 保存内部归属/hash/object_id | 教材 PDF、Office、图片、需要留存的网页/导入文件；按资源生命周期保存，是重建及原文引用的恢复源 |
| KB 解析文件 | LightRAG 检索解析组件唯一写删 S3 服务派生空间；业务 PG 登记 manifest/版本/来源 | 文本/Markdown、OCR、提取图片及文件化页码映射；保留引用/恢复所需版本，与原文联动删除；可查询文本块/向量/文档状态在检索 PG，实体/关系图在 HugeGraph |
| RAG 服务派生副本 | 服务管理的 S3 受限子前缀；企业 PG 登记远端 locator/责任 | 上传 API 必须保存的原文副本、图片及解析物可重建；只由服务写删，企业层授权协调/对账，额度涵盖实际副本字节，不让两边并发覆盖同一 key |
| 聊天及笔记附件 | S3 文件 + PG attachment/object metadata | 文档/图片及已启用的音视频输入；保存期间预览、下载和后续引用均重新授权 |
| 持久工作区文件 | S3 文件 + PG 所有权和版本 | 用户主动保存、后续 turn 需复用的文件；不整体上传含凭证/缓存的 workspace |
| 生成与导出物 | S3 文件 + PG turn/resource 引用 | 研究报告、PDF/PPT、SVG/HTML/图表、Manim 视频、音频、代码执行产物及按需导出文件；上传完成且 PG ready 后才能返回成功 |
| 可编辑 skills/personas | S3 正文、脚本/模板/附属文件和版本对象；PG metadata/当前版本指针 | 正文无论大小都采用此固定规则；编辑发布后原子切版本指针，运行按已授权版本读取，不同时维护 PG 可编辑正文 |
| 需保留的中间文件 | S3 临时/缓存对象 + PG 保留期限/引用 | 大文件导入暂存、昂贵解析缓存或恢复检查点；按 TTL 清理，但不得删除在用引用或唯一恢复副本；任务状态本身不放 S3 |
| partners/MCP/cron/exec 等文件 | 启用时按输入/输出类别进入 S3 | 调度、配置、用量及任务状态在 PG，凭证在 Secret；仅受授权的持久文件进入对象存储 |

**统一正文规则**：memory/notebook 的内容及结构化业务数据进 PG，关联文件进 S3；动态 skills/personas 正文和资源包进 S3。ResourceStore 的“小正文”不再包含后者，不能按文件大小任意选择两个权威。保存为下载文件的笔记/会话导出可进 S3，但不是业务主记录。

### 不上传为业务权威的内容

| 内容 | 去向 |
| --- | --- |
| sessions/messages/turn_events、身份/grants、settings、同步/Webhook、配额、任务状态 | PostgreSQL；即使现在是 JSON/YAML 文件，也不直接迁为 S3 文件主库 |
| 检索向量、图、KV、文档处理状态 | 按 06：KV/vector/doc_status 在受管 PG，图在 HugeGraph；不把运行态图导出 JSON 当 S3 索引后端；服务必要队列需持久化/对账，不能当作可丢弃 scratch |
| 模型/S3/DB/OAuth 凭证、访问/刷新 token | Secret 或专用受控凭证机制；不进入普通业务对象或导出包 |
| 内置只读 prompts、skills、程序及静态资源 | 代码/镜像随版本发布，不复制成用户可变对象 |
| 下载副本、解压/编译目录、普通缓存、临时执行文件 | 隔离 scratch；可丢弃，无需为了“上 S3”全量上传 |

### 备份与 CI 制品另行隔离

PG 备份/WAL、HugeGraph 数据/schema/权限配置备份、脱敏审计归档、CI 报告和发布证据可以使用 S3，但不是租户业务主存储的替代。若采用对象存储，使用独立 bucket/权限、加密、生命周期和恢复策略，不放入普通用户可下载空间；数据库备份不是让运行中的 PG 数据目录挂载到 S3。容器镜像仍由 registry 管理。这里的独立 bucket 是运维/CI 信任域隔离，不是新增业务 bucket-per-tenant 路线。

应用备份、检索状态/必要队列恢复、S3 原文与派生物版本应成套校验；采用 LightRAG 不能取消 DeepTutor 的附件、产物和动态资源存储。详细原文/服务副本责任见 [06](06-postgresql-native-store-plan.md)。

## 配置与模型

```text
用户偏好（仅允许覆盖的字段） > 租户配置 > 平台默认值 > 内置默认值
```

安全策略与配额不能用上述偏好覆盖规则提权：最终权限是平台上限、租户策略和用户 grants 的交集。平台模型凭证存 Secret 系统，PG 存引用、可用模型与版本；租户管理员只管理已分配模型的使用授权，不读取/导出 provider key。

第一阶段必须把原 settings JSON/model catalog 的管理写入和 runtime 读取一起替换。多副本启用前补版本化缓存失效，不能页面显示已修改而 agent 仍读旧文件。

### 聊天模型与检索模型分离

上述偏好优先级只覆盖 DeepTutor 明确允许的聊天/教学配置字段，不能用它覆盖检索实例的模型配置。模型目录必须标注用途，不能把“租户可选聊天模型”直接下发成 LightRAG embedding 配置。

| 项目 | 配置与执行权威 | 生效方式 |
| --- | --- | --- |
| 聊天/推理/教学工具模型 | DeepTutor runtime；仅持有对应模型 Secret 引用/调用权 | 已授权偏好/策略按版本失效并在相应新调用生效 |
| 检索 profile | LightRAG 部署配置；包含解析、抽取、embedding/维度、检索内部模型与可选 rerank 及配置版本 | DeepTutor 只选择已获授权且就绪的 profile 引用，不传任意 provider URL/key、不在请求内改服务环境 |
| 检索 profile 变更 | LightRAG 执行受控配置发布，DeepTutor 协调 binding 切换 | 影响解析/切块/抽取/embedding 的变更建立新 index-version、重建验证后切换；仅查询参数/兼容 rerank 变更亦须版本化验收，不重写旧索引 |
| 租户预算与费用账本 | DeepTutor Policy/UsageStore | 原子准入/预留/幂等记账；既校验聊天模型，也校验 KB 检索 profile 的业务可用范围 |
| 检索内部限额与用量 | LightRAG 及其模型/任务组件 | 执行导入/解析/LLM/embedding/rerank 的内部并发、队列和调用预算，通过服务契约上报实际消耗 |

两侧 Secret 按执行者隔离：LightRAG 不读取聊天模型密钥，DeepTutor 不获得检索模型 provider 密钥；如使用同一模型供应商，也分离调用身份或可验证的用量归属。平台可管理目录与受控 Secret 引用，但租户配置页面不能直接修改 LightRAG 部署配置。界面区分业务策略已保存、检索配置待发布/重建和实际生效版本。

每次远端操作关联 operation ID、tenant/KB/index-version/profile/version、用量事件 ID/序号、执行状态和观察时间；重复上报幂等，迟到用量仍核算。未上报标记“待核算”，不能填零或假定包含在 turn `cost_summary`。DeepTutor 不直查检索数据库或模型私有账表补数。

业务请求/本地 worker 的并发槽与远端执行预留分开：本地结束可释放本地槽，只有确认远端已停止/完成才释放其执行预留；网络超时或租约到期仅触发对账。已消耗 token 不因取消退款，未使用预留在可验证终态/核算后释放；人工修复也须持久证据和审计，不能超时盲目放行。费用待核算与执行槽释放是独立状态。

A2 就交付固定 profile、基础准入、服务内部限额/状态/遥测以及取消不确定时的预留对账；B2 增加可管理的租户 token/并发策略。超出内部预算拒绝或停止继续派发并上报原因；入口 QPS、仅 OMS 显示限额或缺失遥测均不算实际执行。验收聊天模型切换不改变索引、未授权 profile 拒绝、重复/迟到用量、取消/超时远端仍运行及重建切换。

### 模型 Secret 轮换的生效与失败契约

Secret 引用保存和模型配置生效是两回事。每个执行组件分别维护 `desired_secret_version`、`active_secret_version`、生效确认/失败原因，业务侧只记录脱敏引用和确认元数据，不读取检索模型密钥。A1/A2 提供受控版本装配和验证，C1 的轮换 UI 复用该流程。

- 授权管理操作创建期望版本；DeepTutor 模型执行方或 LightRAG 部署运维分别通过其 Secret provider 装配、验证新凭证。目标执行者全部就绪且新调用路由切换确认后，以版本比较更新 active；只有保存成功不得显示“轮换已生效”。单执行实例按排空/停旧启新完成，多执行者仍须 G-H，不能为轮换产生未验证的竞争 writer。
- 新聊天调用/远端操作在开始时绑定该执行方的 active credential/profile 版本。在途调用不被静默改写；正常轮换仅在旧凭证仍有效、未被安全撤销且允许重叠时保留有限排空窗口，停止旧版本新派发、确认在途结束后撤销旧凭证。不支持重叠时使用受控维护窗口，不承诺无中断。
- 新版本验证/切换失败保持 pending/failed；旧版本仍有效且未撤销时，可按审计和版本检查继续或回退至旧 active。旧凭证已失效、泄露或被撤销则停止使用并显式失败，禁止自动回退；受影响在途任务按服务实际状态对账，重试须重新授权并明确绑定当前 active，不重复索引/扣费。
- 验收两侧新调用确实使用确认版本、在途旧版本排空、部分执行者失败、并发轮换、强制撤销和回退拒绝。只换模型凭证、不改变模型/索引语义时不重建索引；profile 兼容性仍按上一节验证。

## S3-compatible ObjectStore


目标实现 `S3ObjectStore` 支持所选服务商的 endpoint、region、path-style、TLS、签名及加密配置。所谓兼容不能只靠配置名判断：必须在实际目标端完成 put/get/head/delete、multipart（如启用）、presigned URL、生命周期和恢复验证。

```text
tenants/{tenant_id}/users/{user_id}/attachments/{object_id}
tenants/{tenant_id}/shared/kb/{kb_id}/source/{object_id}
tenants/{tenant_id}/turns/{turn_id}/outputs/{object_id}
```

规则：

1. 后端从可信内部 scope 生成 key，查 PG 归属并授权；前缀不是安全边界本身。
2. 私有 bucket、TLS、Secret/工作负载身份、不向用户暴露长期存储凭证。
3. PG 预建 pending 记录→上传唯一 key→校验大小/hash/MIME→ready；消费者只读 ready，失败/超时有补偿清理。
4. 直传需先预留配额、完成时重新确认权限/大小/hash；多副本下同一额度不能重复消费。
5. 删除先 tombstone/标记，再异步删除并可重试；源文件删除联动解析物、PG 文本块/向量/状态/缓存及 HugeGraph 图中的文档来源贡献及受影响实体/关系，失败持久化对账；保留同 KB 其他文档/共享实体的有效来源，不把文档删除变成整个 scope 的 drop。图写不确定按 06 停写/确认后恢复，不能盲目重试。
6. 预签名 URL 是 bearer 凭证，短 TTL、日志脱敏；需要即时撤权时走后端代理。

## 不可忽略的文件路径依赖

`PathService` 不能仅把 `/data/...` 改成 `s3://...`。解析器、RAG 工具、exec、可视化等可能需要真实文件路径：

```text
授权 → 下载到隔离 scratch → 本地处理 → 上传结果至 S3 → 提交 PG 引用/状态 → 发布成功事件 → 清理 scratch
```

下载/上传超时、Pod 中断、重复任务、磁盘空间不足均要显式失败；结果未持久化不能返回成功。scratch 可重建但不能成为唯一副本。不采用挂载 S3 模拟 POSIX 来逃避接口替换。

## KB、向量与共享资源

企业首发已选 LightRAG Server，图检索必需，图后端采用用户 fork 的 HugeGraphStorage；A1/A2 完成接入与生产验收，不重写本地 pipeline 作为另一套引擎。企业 RagDocumentService/RagGateway 完成 PG/Secret binding、固定 workspace 实例分配、查询前授权和文档生命周期协调；应用管理 S3 原文，检索解析组件管理 S3 解析物/服务副本并上报 manifest。WeKnora 不在首发实施范围；HugeGraph 由用户 fork 接入；实现与数据库防线以 [06](06-postgresql-native-store-plan.md) 为准。

建立“原文→解析→索引→召回→授权源文→删除→重建”契约测试；远端接收成功不等于索引 ready，file_path 不等于可下载对象。托管删除联动远端索引和缓存；旧非托管连接只解除绑定，移交托管前不得删除其服务器数据。

阶段一固定生产租户也须个人/共享 KB 授权，并在测试环境完成双租户及同租户两用户隔离负例；阶段二复验真实外部身份及多个租户治理。每次召回先校验整个 KB 的可见性，再路由到 binding 中的受控远端 KB/workspace，结果引用再次授权；不能把不同可见范围混成一个图再过滤 top-k。缓存、去重、文本块、向量、状态和已启用图共用内部 tenant/KB/index-version 映射；同 URL 别名、静态 API key、服务 RBAC 或仅网关过滤不构成完整隔离，也不能把固定 workspace 当作个人 KB 默认私有授权。

共享 KB 是租户资源，不是租户管理员个人目录。管理员变更不会改变 KB 所有权。普通用户只有显式授权后才能读取，写入需独立权限。不得把旧全局 `admin:kb:*` 自动分享给全部新租户。

HugeGraph scope 不等于 ACL，运行身份与图资源权限必须覆盖 KB 边界；同 scope 不允许多个独立部署竞争写入。导入/查询按租户/KB 限制并发、队列、图遍历和连接预算，图大小/扫描成本纳入容量验证；M1 先提供基础保护，B2 完成可管理配额及用量治理。企业托管删除和恢复成套覆盖 PG/HugeGraph/S3，不能只删向量或只切图后端变量。

## 高风险能力

partners/MCP/cron/exec/subagents 默认关闭外部访问。启用前必须覆盖：租户所有权、Secret 引用、显式授权、执行时 scope 校验、任务幂等/恢复、沙箱与网络限制、资源配额及审计。

这是能力发布开关，不是额外的第四/第五实施阶段。已有必需功能不得默默删除；如果首发必须使用，就在阶段一完成持久化与安全替换，多租户开放前在阶段二完成隔离。cron 的计划和执行状态写 PG/受控调度系统，不建设租户 `jobs.json` 后端。

## 验收

存储故障/Pod 重建属于 [G1](02-rollout-testing-and-migration.md)，多租户底座与跨用户负例在 G1 即验收，真实外部身份、多租户治理配额及隔离复验属于 G2；跨 Pod 协调属于启用多执行模式前的 G-H，运营界面变更真实影响资源策略属于 G3。所有 API、agent 工具、后台任务和文件下载都在验证范围内。

### ObjectStore isolation

Object keys are backend generated under tenant and hashed-owner namespaces. Tests cover same suffixes across owners, old local path forgery, cross-owner reads, and cleanup retry isolation. Operators must not use bucket prefix deletion as an authorization primitive; use PG cleanup jobs.
