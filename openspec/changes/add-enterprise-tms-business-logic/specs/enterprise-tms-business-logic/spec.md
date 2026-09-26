## Purpose

定义云端 TMS“学校智能体管理后台”在一个可信当前学校内管理应用接入、成员与资源访问、知识内容实例并查询 OMS 配额及 DeepTutor 真实用量时的正式业务规则；保护 EduPlus2 身份权威、个人资源归属和平台管理边界。教育业务中技术 tenant 即学校，保留 TMS、`/tms` 和底层技术契约。

## ADDED Requirements

### Requirement: TMS 只能作用于可信当前租户

TMS SHALL 由服务端已验证的身份和租户绑定确定唯一当前 tenant；URL、query、header、body 或前端状态中的 tenant ID 不得扩展目标范围。每个读写动作 MUST 校验当前租户、具体 `tenant.*` 能力、资源归属和必要的 owner/显式 grant；管理员角色本身不赋予跨租户或他人私有内容访问权。默认不得提供任意跨租户切换器。

#### Scenario: 伪造目标租户读取配额
- **WHEN** 租户 A 管理员在请求中伪造租户 B 的 ID 查询配额或资源
- **THEN** TMS 仍只按可信租户 A 处理或拒绝该请求，不能泄露租户 B 是否存在

### Requirement: 学校 code 路由必须与 EduPlus2 管理员学校绑定一致

TMS SHALL 保留技术缩写及 `/tms` 入口，并以“学校智能体管理后台”为对外名称。一个技术 tenant SHALL 在 EduPlus2 教育业务中对应一所学校，`school_code` SHALL 作为学校 tenant code 构成 `/tms/{schoolCode}` 规范路由；`tenant_id`、`tenant.*` 和 Skill `owner=tenant` 技术契约 SHALL 保留。`/tms` SHALL 在验证管理员账号的唯一学校绑定后跳转至其规范学校路径，不提供任意学校选择器。路径 code MUST 仅作为学校定位线索：所有页面、API、品牌与资源查询 MUST 先由已认证主体解析可信稳定学校 ID 与规范 code，再核对路径 code、具体权限和资源归属。列表及详情深链 SHALL 保留学校 code 与筛选上下文，详情通过可直达/刷新恢复的列表背景抽屉展示；维护动作使用模态框，不以 URL 中的 `/edit` 自动授予写权限。

#### Scenario: 管理员打开其学校的详情深链
- **WHEN** 学校 `jygjzx` 的管理员直接打开 `/tms/jygjzx/quotas/{id}` 或刷新页面
- **THEN** 服务端核对账号学校绑定、只读配额权限及配额归属后，展示该学校配额列表与同一笔配额的只读详情抽屉

#### Scenario: 猜测其他学校 code 或资源 ID
- **WHEN** 学校 A 的管理员改写路径为学校 B 的 code 或猜测学校 B 的资源 ID
- **THEN** 页面、API 与导出均不得泄露 B 的管理内容，品牌不能冒充当前已验证学校的主题；前端隐藏链接不能替代服务端拒绝

### Requirement: 学校管理员账号须由 EduPlus2 权威事件同步且独立验证登录

TMS 的学校管理员账号及学校/角色关联 SHALL 由 EduPlus2 权威的经签名 webhook 事件同步、更新和撤销；各学校账号 SHALL 隔离，不能以同名账号跨学校合并。登录凭证 SHALL 继续由 EduPlus2 掌管，收到 webhook 事件不得直接代表管理员已登录或已获得 TMS 动作权限。事件接收 MUST 验签、防重放、按稳定学校 ID + 用户 ID 幂等映射、处理乱序/撤权并可与权威快照对账；登录与每次管理操作 MUST 验证当前学校绑定、管理资格及对应 `tenant.*` 能力。发送端事件 schema、版本和对账能力尚待 EduPlus2 确认；在契约缺失或绑定不可信时，正式学校管理入口 MUST 保持未启用。既有学校生命周期 webhook 只处理开停事件，不能作为管理员账号同步已交付的证据。

#### Scenario: 撤销学校管理员资格
- **WHEN** EduPlus2 撤销某学校账号的管理员资格并通过权威事件或对账反映到 TMS
- **THEN** 该账号不能继续访问学校管理页面、API 或使用旧会话写入；学校生命周期状态和其他账号不被错误改写

#### Scenario: 学校身份事件缺少可信绑定
- **WHEN** 管理员事件没有可验证的学校或用户稳定 ID，或登录学校 ID 与同步绑定冲突
- **THEN** TMS 拒绝建立或使用管理员映射，不用 `school_code`、同名账号或页面路径补齐授权

### Requirement: EduPlus2 必须保留租户、身份和组织权威

TMS SHALL 展示来自 EduPlus2 的当前租户生命周期、成员与组织必要同步字段及来源/时效，但不得开通、暂停、恢复租户，不得创建第二套学校组织、外部用户密码或重置 EduPlus2 密码。未知或同步延迟状态不得伪装为 active；外部状态与本地隔离/资源就绪须分源呈现。TMS 可维护的 DeepTutor 应用内 grant 不改写 EduPlus2 主数据。

#### Scenario: 租户同步状态延迟
- **WHEN** EduPlus2 租户状态事件尚未核对完成
- **THEN** TMS 展示待同步/待核对及最后可信状态，不提供直接“启用租户”按钮，也不把未确认状态当可用

### Requirement: TMS 成员与资源授权必须有具体能力和资源范围

TMS SHALL 在 OMS 授权范围内对当前租户的成员、应用、共享资源管理访问 grant，记录授予者、目标、范围、版本、原因及撤销结果。服务访问 grant MUST 绑定对应 OMS 租户服务授权的 ID/代际；OMS 撤权后该 grant 失效，即使日后重新授权同一服务也不得自动复活。应用/成员服务访问资格只是权限，不是额度发放、预留、转移或成员/应用使用上限；任何 grant 不得扩大 OMS 租户级服务授权。对会话、记忆、笔记、私有文件和个人伙伴等私有对象，只有 owner 或持有**独立分享/授权能力**的主体可授予正文读取权；普通读取 grant 与 `tenant_admin` 元数据管理身份均不得自动转授权或读取正文。

#### Scenario: 给应用开放租户已有 OCR 服务
- **WHEN** 获授权 TMS 管理员给本租户应用开放已由 OMS 授权的 OCR 服务
- **THEN** 系统记录一条可撤销的服务访问 grant，不新建或扣减租户配额；真实调用仍须通过 OMS 授权与额度准入

#### Scenario: 管理员尝试读取成员私有笔记
- **WHEN** 管理员仅凭管理角色访问未获显式授权的成员私有笔记正文
- **THEN** 服务端拒绝且不因管理 UI 可见成员信息而扩大内容权限

#### Scenario: OMS 撤权后重新授权同一服务
- **WHEN** OMS 撤销租户 OCR 服务授权，随后重新授予 OCR
- **THEN** 绑定旧授权代际的 TMS 应用/成员访问 grant 不自动恢复，须重新显式授权后才能调用

#### Scenario: 持普通读取 grant 尝试转授权
- **WHEN** 某成员只有私有 KB 的读取 grant，却试图给他人分享正文或导出
- **THEN** 服务端拒绝转授权/未获准的导出，owner 与独立分享授权边界不被普通读取权替代

### Requirement: EduPlus2 client/app 注册必须归口本租户并可追溯

TMS SHALL 允许获 `tenant.clients.manage` 权限者为当前租户注册、查看与注销 EduPlus2 client/app；注册前 MUST 通过 EduPlus2 权威解析或等价可信校验获取 client 对应的外部 tenant、app ID 与状态，且 external tenant 必须与当前租户绑定完全一致。同一 provider 的 active client ID 与同租户同 app 的 active 注册 MUST 唯一，冲突明确返回；注销/retire 保留历史和审计，不物理抹掉访问记录。无权访问的 client 不得因用户输入名称而自动变成可信注册。

#### Scenario: 注册其他租户的 client
- **WHEN** 当前租户管理员输入的 client 经 EduPlus2 解析属于其他 external tenant
- **THEN** 注册被拒绝，系统不创建临时可用记录，也不泄露目标租户的私有信息

#### Scenario: 更换同一应用的 client
- **WHEN** 同租户同 app 已有 active client，管理员直接注册第二个 client
- **THEN** 系统返回冲突；旧注册受控注销后才允许新注册，旧审计仍可查询

### Requirement: 应用和成员的实际服务可用性必须取权限交集

应用/成员可见和可调用的服务 SHALL 取可信租户生命周期/资源就绪、OMS 租户级授权、TMS 适用访问 grant、平台配置 readiness、租户有效配额和兼容供给的交集。直接用户调用须有成员或显式群组 grant；应用委托用户须同时有应用及该成员的适用 grant；纯应用调用须有应用 grant；后台任务须有可信 job 归属和显式服务主体 grant，Agent 子调用继承原主体约束。缺少应有的主体或 grant MUST 拒绝，不得因 user/app 字段为空绕过。TMS 可以展示受限原因，但不得修改 OMS Provider、Secret、供给、配额或外部租户状态；应用权限变更不得绕过真实 CLI、HTTP/WS、SDK、后台调用边界。

#### Scenario: 应用有 grant 但租户配额耗尽
- **WHEN** 应用已获 OCR 访问 grant，OMS 授予的 OCR 有效配额耗尽
- **THEN** TMS 显示应用仍有访问资格但 OCR 新调用因额度不足受限；登录、TMS 管理、历史查询及其他服务继续可用

#### Scenario: 后台任务没有服务主体 grant
- **WHEN** 当前租户后台任务尝试调用 OCR，但没有可信服务主体及其显式访问 grant
- **THEN** 调用被拒绝，不能借没有交互用户或 app ID 绕过 TMS/OMS 准入

### Requirement: TMS 可上传 tenant Skill 且同名时必须确认 tenant 优先

云端 Skill owner SHALL 仅为 `global` 或可信当前 `tenant`，来源（内置/ZIP 提交/Hub 导入）独立标识。OMS 已发布且授权本租户的 global Skill SHALL 无需成员/应用二次分配即可供本租户使用；TMS 只读展示 global 内容。具备具体租户 Skill 管理权限的管理员 SHALL 仅能通过包含唯一 `SKILL.md` 的完整 ZIP 创建/更新当前 tenant owner Skill；受控 Hub 导入 MUST 取得并校验真实包，不接受单文件 `SKILL.md`、纯文本或仅 Hub URL。服务端 MUST 从 `SKILL.md` 有效 YAML frontmatter 与非空 Markdown 正文读取全部 Skill 内容元数据，校验名称/说明、目录匹配、路径、体积、重复/危险文件、加密/损坏/膨胀 ZIP；不得由表单、文件名或包内自报的 owner/状态覆写。可信 tenant owner、来源、审核/发布状态和不可变包摘要由服务端生成；审查前不执行脚本或启用 `always`，发布后仅本租户可用。与已授权 global Skill 同名时，上传操作 MUST 在持久化前显示两者 owner 与运行时影响，并由该管理员显式确认；取消不得保存。Skill 稳定身份 SHALL 包含 owner 和名称，允许跨 owner 同名，不允许同一 owner 的未审查覆盖。运行时清单、`read_skill` 正文和参考文件 SHALL 按当前租户中已发布 tenant Skill 优先、再按已发布且已授权 global Skill 解析；tenant Skill 暂不可用时不得静默回退 global，撤销 tenant Skill 前须告知 global 可能恢复。未授权 global 名称不得因上传冲突检查泄露。Skill 本身不建立独立 Token 配额，仍受底层服务授权和额度控制；现有用户级 `/api/skills` 不得作为云端 tenant 写入旁路。

#### Scenario: 上传与 global 同名的本租户 Skill
- **WHEN** 获授权租户管理员上传名称与当前已授权 global Skill 相同的 Skill 包
- **THEN** 系统先展示同名覆盖影响并等待明确确认；取消不创建 tenant Skill，确认后保存本租户草稿且通过安全审查/发布前不可运行
- **AND** 发布后该租户同名调用仅选 tenant 版本，其他租户的 global Skill 不受影响

#### Scenario: tenant Skill 不可用或被撤销
- **WHEN** 已发布 tenant Skill 暂因依赖缺失不可用，或管理员拟撤销它
- **THEN** 不可用期间同名请求失败而不回退 global；撤销前提示 global 可能重新成为当前租户同名候选，撤销后才按授权状态重新解析

### Requirement: TMS 只接收获授权的只读 builtin Skill 投影

DeepTutor builtin Skill 在云端 SHALL 作为 `owner=global, source=builtin` 的只读条目处理，而不是第三种 owner。TMS MUST NOT 接收未获 OMS 授权的 builtin 目录项、正文或参考文件；获授权后 SHALL 展示来源、打包版本与 `requires` 就绪状态，不能让租户修改包内内容或把授权误认作依赖已满足。与已授权 builtin 同名的 tenant Skill 上传 SHALL 遵守明确确认及 tenant 优先规则。服务端租户投影与运行时清单、`read_skill`、显式请求和 `always` 注入 MUST 采用相同的授权及 owner 解析；云端限制不得修改本地 DeepTutor 的自动发现行为。

#### Scenario: 内置 `pdf` 未授权或缺少运行条件
- **WHEN** 当前租户尚未获 OMS 授权 `pdf` builtin，或虽获授权但 shell sandbox 不可用
- **THEN** 未授权时 TMS 响应不含该条目/正文；已授权但缺条件时仅显示“暂不可用”，不得作为可执行 Skill 提供给运行时

### Requirement: 本租户配额清单与消耗明细必须严格只读

TMS SHALL 将 OMS 授予的赠送与充值记录呈现在同一个一级配额列表，支持按服务、获取方式、状态和有效期筛选；详情 SHALL 显示来源、单位、总量、已用、剩余、有效期、关联服务和逐供应商调用尝试的真实消耗。同一 attempt 可按 OMS 分摊结果关联多笔赠送/充值授予，TMS 按 attempt ID 去重、按授予 ID 展示各自份额，不把一次尝试显示为多次服务调用。所有配额数据须来自当前租户受控只读投影；TMS MUST NOT 提供新增、赠送、充值、调整、撤销、转移、成员/应用额度上限、手工核销或修改用量的页面动作或 API。缺可信用量 SHALL 显示待核对，不能假装零用量或精确余额。

#### Scenario: 从服务详情查看赠送额度
- **WHEN** 管理员从 OCR 服务详情进入本租户赠送额度详情和一次调用
- **THEN** TMS 展示与配额清单相同的 OMS 授予事实和 DeepTutor 消耗记录，仅可筛选/钻取/返回，不出现配额编辑按钮

#### Scenario: 单次尝试跨赠送和充值
- **WHEN** 一次已核对供应商尝试同时消耗一笔赠送额度和一笔充值额度
- **THEN** 两笔配额详情分别显示自己的消耗份额，服务用量列表只显示一次该 attempt，不重复累计真实用量

#### Scenario: 直调 TMS 配额写接口
- **WHEN** 租户管理员伪造请求尝试通过 TMS 增加配额、修改有效期或核销用量
- **THEN** 服务端不提供该写能力并拒绝请求，OMS 授予与用量总账均不变

### Requirement: 租户知识与内容管理不得越过 owner 和检索服务边界

TMS SHALL 只管理当前租户且获授权的 KB、文档、共享资源和业务任务；创建、导入、索引、失败、重试、删除及非托管外部连接解绑 MUST 呈现真实业务状态和不同后果。逻辑 KB/文档 ID 必须在服务端重新验证并解析受控资源绑定，不能由用户指定任意远端 URL、workspace、路径或凭据；检索返回的引用和派生文件读取须再次按 owner/grant 授权。TMS 不管理 LightRAG 内部 PG/图、Kubernetes 实例池或平台 Secret。

#### Scenario: 删除非托管连接
- **WHEN** 管理员请求移除一个非托管外部 KB 连接
- **THEN** TMS 只执行受控解绑，不擅自删除外部服务器上的语料；真实托管文档删除另按其资源/任务契约处理

#### Scenario: 私有文档引用越权
- **WHEN** 用户取得属于同租户他人私有 KB 的引用 ID 并尝试下载原文
- **THEN** 服务端重新校验 owner/显式 grant 后拒绝，不以同租户身份直接放行

### Requirement: TMS 用量、业务任务和审计必须按本租户投影

TMS SHALL 在已获授权的当前租户范围内按服务→成员/应用→单次调用展示真实原生单位用量、来源、关联配额和待核对状态，并展示本租户管理事件与业务任务状态。任务的“请求取消”不得显示为远端已停止；重试/取消仅由原业务归口且具具体权限的入口执行。跨租户、供应商采购成本、平台凭据、Secret 和个人未授权正文不得出现在 TMS API、导出、日志或浏览器状态。

#### Scenario: 远端任务状态未知
- **WHEN** KB 导入任务已请求取消但远端尚未确认停止
- **THEN** TMS 展示取消待确认和用量待核对，不把任务显示为已完成取消或释放可能产生的消耗

### Requirement: TMS 必须独立交付并安全复用业务组件

TMS SHALL 作为独立构建/部署的云端前端使用与 OMS 同源、兼容版本的服务列表/详情业务组件；共同列、状态、搜索、分页和详情交互保持一致，各端由自己的 API、权限和动作适配器提供数据。TMS 服务端 MUST 只返回本租户安全字段，不能将 OMS 的成本、Secret、采购和跨租户字段传到前端再隐藏。正式入口须在真实身份、权限、数据和隔离验证前保持不可用；开发原型数据不可进入生产路径，生产原型 URL 返回真实 HTTP 404。

#### Scenario: 两端复用 OCR 服务列表
- **WHEN** OMS 平台人员和 TMS 租户管理员分别查看 OCR 服务列表
- **THEN** 两端使用同一业务组件实现共用列与交互，TMS 只收到本租户可见服务和只读配额信息
- **AND** TMS API/导出/浏览器载荷均不含 OMS 供应商成本或 Secret

### Requirement: TMS 操作必须受后端动作权限和审计保护

TMS SHALL 对成员/资源 grant、client 注册与注销、KB/文档管理、用量/审计读取等动作分别授权；导航与按钮显示不得代替服务端校验。写操作 SHALL 记录可信操作者、当前租户、对象、前后版本、结果、关联请求 ID 和原因。撤权后旧会话、WS、SDK 和后台新操作仍须按既有检查点复验，不得仅依靠页面刷新。

#### Scenario: 普通成员直调管理 API
- **WHEN** 无相应 `tenant.*` 管理能力的普通成员绕过 TMS 页面直调 client 注册或 KB grant API
- **THEN** 后端拒绝且不会产生成功写入或跨租户泄露，并记录可审计的拒绝结果
