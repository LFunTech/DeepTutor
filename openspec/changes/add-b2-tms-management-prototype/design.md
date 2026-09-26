# 设计：云端 TMS 信息架构、独立部署与共享组件

## Context

范围和动机见 [proposal](proposal.md)，可观察行为见 [delta spec](specs/enterprise-tenant-management-prototype/spec.md)。当前 `web/app/tms/page.tsx` 是 DeepTutor 本地 Web 中的英文占位页，`web/app/(admin)/admin` 只有局部源码可参考；不能将它们改名或套壳后宣称云端 TMS 已实现。云端 OMS 的业务边界、共享包所有权和供给—授权—用量关系见 [`add-c1-oms-operations-prototype`](../add-c1-oms-operations-prototype/design.md)。旧 `docs/enterprise/02-*`、`11-*`、`12-*` 的单体前端和只读 OMS/欠费假设已过时，不能作为本原型的验收依据。

## Goals / Non-Goals

- 目标：让学校/企业管理员在一个租户范围内完成对象列表→详情的管理路径，并直接查看 OMS 为本租户配置的配额清单与消耗明细；分层查看平台 Skill、维护本租户 Skill；与 OMS 共享服务和 Skill 业务组件及管理 UI 规范，同时拥有独立部署和严格的数据权限边界。
- 非目标：本 change 不交付真实 TMS API、EduPlus2 client 注册、PG grant/配额迁移、真实采购/消费或生产发布；不把 DeepTutor 本地 Web 改造成云端用户端，不建立租户价格、账单或欠费逻辑。

## Decisions

### 0. 学校域术语与路由上下文（待原型实施）

TMS 对外名称为**学校智能体管理后台**，保留技术缩写 TMS、独立应用及 `/tms` 路径。在 EduPlus2 教育业务中，技术 tenant 恰对应一所学校，`school_code` 即学校的 tenant code；界面及业务文档称“学校”，但现有 `tenant_id`、`tenant.*` 权限键和 Skill `owner=tenant` 是技术契约，不因改称而批量改名。`school_code` 是可读路由标识，不等于内部或 EduPlus2 稳定学校 ID，更不是授权凭据。

正式页面以 `/tms/{schoolCode}` 为当前学校工作台，下设 `/members`、`/apps`、`/services`、`/skills`、`/quotas`、`/knowledge`、`/usage`、`/events` 的列表和 `/{resourceId}` 唯一详情路径。详情路径始终以原列表为背景打开抽屉，直接访问、刷新、前进/后退均可恢复；新增、编辑、发布等动作仍使用模态框，不通过猜测 `/edit` 等子路径取得写入能力。筛选、分页和 tab 可使用白名单查询参数，仅保存界面状态。侧栏、面包屑和关联链接保留已核对的 `schoolCode`，关闭抽屉返回来源上下文；直接深链无来源时回本对象列表。开发原型目标为 `/tms/prototype/{schoolCode}/…`，现有 `/tms/prototype` 是尚待迁移的旧开发路径；生产全部 prototype 路径真实 404，正式路径在可信身份/API 就绪前不启用。

`/tms` 仅在完成登录和学校绑定后跳转至该账号的唯一规范 `schoolCode`，不提供跨学校选择器。EduPlus2 每所学校的管理员账号相互隔离；学校管理员记录及其学校/角色变更应来自经签名校验的 EduPlus2 webhook 同步，凭证与交互式登录仍由 EduPlus2 掌管。服务端先验证登录主体及其稳定学校 ID 绑定，再核对路径 code、具体 `tenant.*` 能力和资源 owner/grant；不以 URL、品牌响应、前端 fixture 或 webhook 事件本身替代认证。跨学校 code 与不可见资源不返回目标内容；学校 code 变更、唯一性、管理员事件 schema/版本/撤权/对账须由 EduPlus2 契约明确，未确认前不得宣称真实路由可用。现有 `add-b2-eduplus2-tenant-lifecycle-webhook` 只覆盖学校 lifecycle，不覆盖管理员账号同步。品牌请求只使用核对后的学校 code 和 EduPlus2 tenant ID；原型仅能把 code 与受控演示配置核对，不模拟真实身份已接入。

### 1. 两个独立前端应用，共享包而非共享构建

TMS 与 OMS 使用同一 React、TypeScript、Next.js 技术基线，同仓但各自构建、部署、发布；目标组织可采用 `extensions/enterprise/frontends/apps/{oms,tms}` 和 `packages/{admin-ui,service-components,api-contracts}`。具体包管理器/目录、Ant Design 或定制 headless 控件的选择在原型实施前与 CI/视觉验收一并审阅，但两端不得混用不同基础组件体系。每个前端必须有独立入口、构建产物和发布证据；可经云端入口 `/tms` 或独立域名路由，不挂靠 DeepTutor 本地 Web。`admin-ui` 持有视觉 token、后台框架、列表/筛选/分页/面包屑/表单/反馈；`service-components` 持有 OCR 等服务列表/详情组合组件，避免只有低层按钮共享、业务列表仍各复制一份。TMS 不 import OMS 应用源码。

拒绝的方案：直接复用 DeepTutor `/settings` 会混淆本地/云端的管理对象和权限；OMS/TMS 合成一个前端构建违背独立部署；复制 OCR 列表 JSX 会使状态文案、筛选和详情交互漂移。

**EduPlus2 租户品牌**：共享主题解析和 token 映射由 [OMS 设计](../add-c1-oms-operations-prototype/design.md#eduplus2-品牌主题契约) 定义；TMS 服务端只用可信当前租户的 `school_code`（租户 code）及 EduPlus2 `tenant_id` 请求 `/api/v1/public/branding`，不接受页面查询参数覆盖租户，也不能将本地原型 `aurora` 等 fixture ID 当作 EduPlus2 租户 ID。独立部署配置 `EDUPLUS2_BRANDING_BASE_URL`；原型尚无真实云端身份，只能由受控环境变量 `TMS_DEMO_SCHOOL_CODE`、`TMS_DEMO_TENANT_ID` 指定演示主题身份，并须与页面展示的演示租户一致或明确标为独立主题预览。正式 TMS 切换真实数据前，主题标识须改从受验证的身份/租户绑定取得；主题不是授权凭据。用户提供的 `jygjzx`/`92` 响应为 `palette.primary=#7C3AED`，即该租户显示紫色，不被“默认天蓝色”覆盖。无可信租户主题上下文时可使用 EduPlus2 无参数的平台主题；品牌接口失败或响应不合规则整套回退天蓝色，不影响管理操作。

### 2. 共用业务组件接受安全的共同视图模型

共享 `ServiceList`/`OcrServiceList` 和 `SkillList` 负责各自的共用列、搜索、筛选、分页、状态、详情导航和响应状态。OMS/TMS 容器各自从专属 API 取数、校验当前主体动作能力、映射到共用视图模型；只有可在两端安全显示的字段才能进入组件。Skill 共用视图只含安全的标识、名称、说明、标签、owner、来源、版本与可见状态；内容正文仅在获授权详情中按 owner 读取，global Skill 的跨租户授权名单/内部审查材料留 OMS 容器，tenant Skill 的维护动作留 TMS 容器。平台供给、采购成本、Secret 就绪细节和跨租户指标由 OMS 专有容器/受控 API 展示，不能作为带 `hidden` 标记的 TMS 数据传入共享组件。TMS 自有资源归属、成员/应用关联和其他资源的使用分配动作留在 TMS 容器/组件插槽，不在共用组件内增加 `isOms` 条件分支；Skill 不增加成员/应用二次分配。共享包升级须运行两端构建与 OCR、Skill 列表视觉、键盘和交互回归；不同步部署时固定兼容的包/API 版本。

OCR 示例取自 DeepTutor 现有解析引擎 OCR 设置能力，不表示当前已有独立 OCR Provider。新增独立 OCR 服务的字段、供应商和计量单位须以后端 descriptor/真实执行为准；前端原型只展示明确标注的合成目录信息，不伪造真实配置已生效。

### 3. TMS 对象信息架构：一个租户、六组导航、唯一详情

```text
工作台
└─ 当前租户状态 / 待处理事项列表 → 事项详情
成员与授权
└─ 已同步成员列表 → 成员详情 → 应用内资源权限 / 服务使用资格 / 使用记录
应用与接入
└─ 应用列表 → 应用详情 → 接入记录 / 可用服务 / 成员与资源权限 / 调用记录
服务与配额
├─ 本租户可用服务与能力列表 → 服务详情 → 关联配额 / 使用对象 / 用量
├─ Skills 列表（已授权 global / 本租户 tenant）→ Skill 详情 → owner / 版本 / 标签 / 可用状态
└─ 本租户配额清单（赠送/充值同一列表）→ 配额详情
   ├─ 来源、总量、已用、剩余、有效期（OMS 授予事实，只读）
   ├─ 关联服务与 OMS 配置记录（只读）
   └─ 实际消耗列表 → 单次调用详情
知识与内容
└─ KB 列表 → KB 详情 → 文档/索引状态；租户共享资源列表 → 资源详情
用量与记录
├─ 服务用量列表 → 服务 → 成员/应用 → 单次调用详情
├─ 处理任务列表 → 任务详情
└─ 本租户管理事件列表 → 事件详情
```

首页只展示必要状态和待办，不把所有模块卡片堆叠。成员、应用、服务、Skill、单条配额、KB 与单次调用各只有一个规范详情；其他列表以关系链接进入该详情，不复制“配额页”“应用服务页”两套事实。列表详情在原列表上方使用抽屉，新增与访问关系等维护动作使用独立表单模态框，不在列表行间撑开表单；关闭抽屉保留筛选与列表位置。每级一张主要列表，详情关联对象另设 tab/二级列表；筛选、分页和返回上下文保留。面向普通学校/企业管理员使用“应用”“可用服务”“Skills”“剩余额度”“消耗明细”等业务话术，`client_id`、签名、绑定版本等技术字段只在有权限的高级详情出现。Agent、工具、OCR 等获授权对象作为服务与能力目录的分类/筛选，不另建平行顶层导航；Skill 在该组独立成清单，不混入可计量服务或 Tool 条目。TMS 不显示 OMS 的跨租户目录或供应商采购；个人会话、记忆/笔记和私有文件内容仍受 owner/显式 grant 保护。EduPlus2 同步用户/组织只展示必要只读字段，TMS 不创建学校组织或重置外部密码。租户开停由 EduPlus2 权威事件决定，界面仅展示来源与同步异常。默认只有一个可信当前租户，不因 TMS 名称增加任意租户切换器；如未来主体合法管理多个租户，须另立显式身份/切换契约。

### 4. 本租户配额清单的只读边界

“服务与配额”包含两个并列一级列表：**可用服务与能力**、**本租户配额清单**。后者只有一个只读列表，以“获取方式=赠送/充值”、服务、状态、有效期筛选，不拆成两个账本；列表行进入单条配额详情，再查看关联服务和真实消耗。服务详情也能进入同一条配额详情。配额的 OMS 授予编号、来源、总量、单位、获取方式、有效期、已用和剩余均展示为受控事实；“充值”仅表示获得方式，不是 TMS 财务支付或创建额度按钮。

配额的创建、赠送、充值、调整、撤销及总量、来源、有效期等属性配置只能由 OMS 发起。TMS 不提供配额编辑入口，也不提供应用/成员配额上限等变相配额写入；任何 TMS API 均不得写入配额授予、余额或真实消耗。若在应用/成员页面管理独立的资源访问权限，须依 OMS 授权范围另行校验，不得借此改写配额。真实调用在 DeepTutor 可信执行路径按赠送优先扣减租户额度一次；TMS 只呈现结果和相关记录。

若未来要求用户/应用独立额度、硬预留或 TMS 直接发起购买/自增总量，须另行设计并获批准；当前原型不得伪装成已有这些能力。租户总额度耗尽只阻断对应服务的新调用，登录、管理、历史查询和其他服务仍可用；OMS 供给不足须显示为另一种状态，不混同为租户额度不足。缺可信实际用量则标记待核对，不显示零消耗。

### 5. Skill 作用域、审核与租户内维护

DeepTutor 现有 `/api/skills`、`SkillService` 与 `multi_user/skill_access.py` 只证明用户层创建/标签/Hub 导入、内置只读及管理员分配给用户时只读；它们不是云端平台/租户 Skill 的现成写入 API。云端 Skill owner **只有 `global` 与指定 `tenant` 两类**，来源（内置/ZIP 提交/Hub）是另一维度。OMS 管 global Skill、审查发布与按租户授权；TMS 只读呈现**已发布且授权当前租户**的 global Skill，并由具备租户资源管理权限的管理员提交本租户 ZIP 包、受控 Hub 导入、提交新版本与审核发布；标签等内容元数据跟随包内 `SKILL.md`，不能在线单独修改。本地个人 Skill 仍由本人管理，不进入云端租户清单或成为第三种 owner。内置 Skill 保持只读。租户管理员不得修改 global Skill 内容、扩大 OMS 授权或把 tenant Skill 提升为 global。

`source=builtin` 不新增 owner：它在云端属于只读 global，首次接入/新增打包 Skill 时默认无租户授权；TMS 只接收 OMS 已复核版本且授权当前租户的安全投影，未授权 builtin 不出现在可用清单、详情或运行时。授权不等于运行就绪，`requires` 条件不足（例如 shell sandbox 不可用）时 TMS 显示“已授权·暂不可用”，不得误报可用。租户上传与已授权 builtin 同名时沿用 global 同名确认规则，发布后 tenant 版本优先；本地 DeepTutor 的 builtin 自动发现不受云端授权影响。

tenant Skill 流程为 Skills 列表“提交 Skill ZIP/从 Hub 导入”→共享包预检与只读元数据预览模态框→本租户待审查草稿回到列表→详情抽屉查看版本、文件清单、审核及可用状态；编辑动作改为上传同名的新 ZIP 包版本，不提供正文、名称、说明、标签或依赖的在线覆写表单。高影响发布/撤销需确认模态框，取消后保留所选文件及列表上下文。ZIP 是提交/分发载体，解包后必须是 DeepTutor 可识别的单个 Skill 目录：根级 `SKILL.md` 或唯一命名目录下的 `SKILL.md`，后者目录名与 frontmatter `name` 一致；可包含 `references/` 及受控文本脚本等资源。`SKILL.md` 的有效 YAML frontmatter 是 `name`、`description`、可选 `tags`/`requires`/`always` 等内容元数据的唯一来源，Markdown 正文须非空。文件名、表单内容、Hub URL 或包内自报 owner 均不得代替这些值。可信 tenant owner、来源、审核/发布状态、包摘要与平台修订号属于服务端治理数据，不由 `SKILL.md` 决定。原型须真正读取并校验包内 `SKILL.md` 与完整文件清单，检查结构、体积、路径、重复条目、危险文件、加密/损坏/膨胀 ZIP；不得仅扫描 ZIP 中央目录后用手填文本/占位符保存。浏览器预检不等于真实安全审查，原型不上传或执行包；未来企业 API 必须服务端重验、留存不可变包并审查后发布。Hub 导入在原型只接受实际 ZIP 包（配对 fixture 或操作员手动选取的本地包）；填写的 Hub URL 只登记为“来源未核验”，不声称已由服务端拉取，不能仅填 URL 就产生具有伪造元数据的 Skill。参照 [Agent Skills 规范](https://agentskills.io/specification) 和 DeepTutor 现有 `hub.py`/`service.py` 导入语义。

官方可选的 `license`、`compatibility`、`metadata`、`allowed-tools` 及 DeepTutor 可选的 `tags`、`requires`、`always` 等若显示，也只能读自 frontmatter；包未声明语义版本时不得用平台修订号伪装作者版本。导入/上传须展示来源与安全审查状态，未通过审核不得自动启用或使用不受控 `always` 注入。tenant Skill 经本租户获授权管理员发布后仅本租户可用，不需 OMS 再授权；global Skill 在 OMS 发布且对该租户授权生效后即对该租户可用。**两类 Skill 均不要求 TMS 再做成员/应用二次分配**。Skill 本身不独立计 Token 或配置额度，实际模型/工具调用只按底层服务可信用量核销。跨租户查询、普通成员管理、未获授权 global Skill 内容和只读 global Skill 修改均应拒绝，不能靠隐藏按钮。

同名不等于同一 Skill：稳定身份必须包含 owner（global 或当前 tenant）及 Skill 名称，租户之间可重名。上传 tenant Skill 时，仅对**当前租户已获授权且可见**的同名 global Skill 做冲突提示，不泄露未授权 global 目录；管理员在独立确认模态框看到“本租户版本发布后将覆盖同名 global 版本的运行时选择”，明确确认前不得保存上传草稿，取消后保留表单及所选文件。列表保留两条记录并标明 owner、来源及“本租户版本优先/已被覆盖”；不是覆盖或删除 global 内容。运行时在当前租户范围内先解析已发布 tenant Skill，再解析已发布且已授权 global Skill；tenant 版本存在但依赖暂不可用时也不得静默回退 global。若 OMS 后续授权的 global Skill 与现有 tenant Skill 同名，OMS 授权操作给出覆盖告知，TMS 标记状态，但 tenant 优先级不变；撤销 tenant Skill 前提示 global 会重新成为同名候选。此解析规则须覆盖清单、`read_skill` 正文和参考文件，不能只做前端标签。

原型 OMS 与 TMS 是独立本地状态，不假装 OMS 浏览器中的草稿会实时同步到 TMS。跨端授权案例使用配对的合成 fixture：OMS 展示 global Skill 的审查/发布/授权记录，TMS 仅展示同一案例中**预置已发布且授权**的安全投影；新建草稿及仅申请授权的项不出现在 TMS 可用列表。真实 owner、发布、按租户授权及运行时 `read_skill` 校验须由后续企业实施提案在 `extensions/enterprise/` 建立服务端权威与独立 DTO，并审计 CLI/HTTP/WS/SDK 路径；未经批准不改核心注册表。

### 6. 权限与后端装配

TMS API 只接受可信身份绑定的当前 tenant，不接受 URL/query/header/body 改写目标租户；每次操作验证 `tenant.*` 具体读/资源管理动作、资源归属和 OMS 的有效授权/额度。配额配置仅有 OMS 写接口与权限，TMS 只暴露当前租户的配额/用量只读投影，不存在 TMS 配额写动作；共享前端组件不得把 OMS 的“编辑额度”能力传给 TMS。OMS 平台权限与 TMS 租户权限不因共享组件而互通。API 前缀继续规划为 `/api/v1/tms/*`，通用聊天/WS/资源协议保持原有契约。后端可先在 `extensions/enterprise/` 采用同一服务进程内的独立模块、路由和事务边界；是否拆多服务以实际的隔离、扩缩容、部署和故障域证据裁决，不能让前端部署选择替代后端授权。原型只展示权限状态，不接真实授权 API。

### 7. 演示与正式路径分离

目标 TMS 应用的开发态 `/tms/prototype` 装配合成 fixture/本地动作适配器，覆盖已授权 OCR、未授权服务、已授权 global Skill（含 builtin）的只读投影、builtin 已授权但 `requires` 不足、本租户 tenant Skill 创建/导入/文件上传/编辑/发布及待审核、上传同名确认与 tenant 优先、单一配额清单中的赠送/充值筛选、只读配额详情与消耗明细、租户服务额度耗尽、用量待核对、同步延迟、client 归口不匹配、KB 索引失败、无权限及空/错误。配额页面无任何模拟写动作；其他允许的资源操作须标注“演示”，不调用真实 API；生产同路径返回 HTTP 404。正式 `/tms` 在身份、API、权限、隔离和数据面验收前保持未启用。旧 DeepTutor `web/app/tms` 占位页须在实施时按入口策略退役/阻断，不能成为生产旁路。

## Risks / Trade-offs

| 风险 | 缓解 |
| --- | --- |
| 两个独立应用共享包升级产生版本错位 | 共享组件/DTO 明确版本与兼容测试；两端分别构建、视觉和交互回归 |
| 共享组件过度抽象变成大量 OMS/TMS 条件分支 | 只抽真实共用的列/行为；专有数据/动作留各自容器，不在组件里判定角色或读取会话 |
| TMS 通过共用 DTO 或浏览器状态得到 OMS 敏感字段 | 服务端按租户白名单投影；负例检查 API、导出、日志与浏览器载荷，不以隐藏列作为保护 |
| TMS 只读配额清单误出现写按钮或写 API | 配额动作能力仅由 OMS 装配；TMS 服务端不注册配额写路由，验证直调拒绝且余额仅来自可信总账 |
| 平台 Skill 草稿或未审核导入项被误认为可用 | 原型配对 fixture 分清草稿、审核、发布和授权；真实路径以服务端发布及运行时授权校验为准，TMS 不从 OMS 浏览器本地状态推断可用 |
| 同名 tenant Skill 上传或后授权导致运行时选错版本 | 上传前明确冲突与管理员确认；owner+名称确定身份，租户运行时 tenant 优先，清单与 `read_skill` 同一解析规则；后授权/撤销标出解析变化，不静默回退 global |
| 现有 DeepTutor 本地设置与云端 OCR 配置字段不一致 | 以后端真实 descriptor 与执行语义为准；仅扩展通用 seam 时先做上游合并风险和本地回归审阅 |

## Migration Plan

1. 先评审本 proposal 与 OMS 原型的共享组件契约；调整旧企业路线文档/实施提案，锁定独立前端构建和云端入口。
2. 在独立 TMS 工程中消费 OMS 原型沉淀的共享包，保留 OMS/TMS 各自的 fixture 和容器；不迁移 DeepTutor 本地 Web 的整个管理页。
3. 验证两个应用分别构建与 OCR 列表/详情交互一致、TMS 敏感字段不可达、开发原型可评审且生产 404；正式 API/迁移/发布另由 B2 实施提案批准并验证。
4. 任何云端切换均保留可回退的上一版前端产物/API 契约；不靠回滚 DeepTutor 本地产品来回滚 TMS。
