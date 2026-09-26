## Purpose

定义学校管理员使用的云端 TMS 高保真原型目标：产品名称为“学校智能体管理后台”，保留 TMS 缩写；独立部署、只管理可信当前学校，拥有本学校配额只读清单与消耗明细，配额全部由 OMS 配置；同时只读查看已授权平台 Skill、维护本学校 Skill，并与 OMS 复用同一管理业务组件而不共享平台敏感数据。教育业务中技术 `tenant` 即学校，技术标识和权限键保留。此规范是原型契约，不代表真实 TMS 管理 API 已交付。

## ADDED Requirements

### Requirement: TMS 必须是独立部署的云端租户管理前端

TMS SHALL 与 OMS 分别构建、部署和发布，不得以 DeepTutor 本地 Web 或 OMS 前端应用作为其生产构建。云端 `/tms` 或等价专属入口 SHALL 只向可信当前租户及获授权角色开放；DeepTutor 本地 Web 的设置和使用功能 SHALL 不因云端 TMS 拆分而被删除。

#### Scenario: 单独发布 TMS
- **WHEN** 云端 TMS 前端发布新版本
- **THEN** OMS 与 DeepTutor 本地 Web 的部署不被替换，TMS 使用的共享组件和 API 契约版本仍兼容

### Requirement: TMS 路由必须显式标识学校但不能以学校 code 授权

TMS SHALL 保留 `/tms` 技术入口，对外显示“学校智能体管理后台”；EduPlus2 教育业务中 `school_code` SHALL 作为学校 tenant code 用于规范学校路由 `/tms/{schoolCode}`。正式路由 SHALL 先从已验证管理员身份及学校绑定取得稳定学校 ID 和规范 code，再核对路径 code、管理权限与目标资源归属；路径、查询、前端 fixture 或品牌接口响应 MUST NOT 扩大该账号所属学校范围。一个管理员账号只对应其 EduPlus2 学校，不提供任意学校选择器。对象列表和唯一详情 SHALL 使用同一学校 code 路由前缀，详情采用可直达、刷新和浏览器前进/后退恢复的列表背景抽屉；维护动作使用模态框。开发原型目标 `/tms/prototype/{schoolCode}` 只核对受控演示上下文，不冒充真实账号同步；正式入口就绪前不得从合成数据切换，生产全部原型路径 SHALL 返回 HTTP 404。技术 `tenant_id`、`tenant.*`、Skill `owner=tenant` 不因业务称呼改变。

#### Scenario: 已验证学校管理员打开详情深链
- **WHEN** 学校 `jygjzx` 的管理员从侧栏打开 `/tms/jygjzx/services/{id}`，或刷新该详情 URL
- **THEN** 经学校身份绑定、具体权限和资源归属核对后，显示本学校服务列表及详情抽屉，链接、面包屑、筛选和返回上下文仍属于 `jygjzx`

#### Scenario: 将 URL 改为另一学校 code
- **WHEN** 学校 A 的管理员把路径 code 改成学校 B 的 code，或尝试用 URL 参数改变品牌与目标资源
- **THEN** TMS 不返回学校 B 的页面、品牌对应的私有上下文或业务数据；学校 code 不是授权凭据

#### Scenario: 原型仅使用受控演示学校
- **WHEN** 开发态原型访问与部署演示学校不符的 `/tms/prototype/{schoolCode}`，或在生产访问任何 `/tms/prototype` 路径
- **THEN** 不以 URL 猜测管理员身份或学校绑定；生产返回真实 HTTP 404，开发态拒绝不匹配的学校路径

### Requirement: TMS 品牌色必须跟随可信当前租户并与 OMS 共用主题 token

TMS SHALL 从按环境配置的 EduPlus2 认证服务公开品牌接口取得可信当前租户的 `palette`，与 OMS 使用同一校验及 CSS token 映射，但不得读取 OMS 平台主题作为已成功取得的租户主题。`school_code` 是租户 code，须与 EduPlus2 `tenant_id` 一起来自可信身份/租户绑定；页面查询参数、本地 fixture ID 和品牌响应本身 MUST NOT 作为租户授权依据。开发态原型可使用受控部署环境配置演示品牌上下文，不得将示例 `jygjzx`/`92` 或测试域名硬编码为所有租户。接口失败或颜色不合规时 SHALL 回退天蓝色，不阻断 TMS 登录和管理。

#### Scenario: 同一组件展示租户品牌
- **WHEN** TMS 的可信当前租户为 `jygjzx`/`92` 且接口返回有效的紫色 `palette`
- **THEN** 共用管理壳、按钮、导航和服务列表使用租户品牌 token；OMS 同时仍使用平台默认品牌 token
- **AND** 成功、警告、错误状态保留语义颜色，不被统一改成紫色

#### Scenario: 未取得可信租户上下文
- **WHEN** 开发态原型未配置配对的演示租户标识，或正式 TMS 的租户绑定尚未验证
- **THEN** 不从 URL 猜测 `school_code`/`tenant_id`，可显示平台默认或天蓝色兜底主题，且不宣称已取得租户品牌或业务授权

### Requirement: TMS 页面必须从列表逐级进入当前租户对象详情

TMS SHALL 以可信当前租户为唯一管理范围，提供工作台、成员与权限、应用与接入、服务与配额、知识与内容、用量与记录的可授权导航；“服务与配额” SHALL 将可用服务/能力列表、独立 Skills 列表与本租户配额清单设为并列入口，Agent、工具、OCR 等按获授权能力分类呈现，不拆成重复顶层目录。对象 SHALL 从列表进入唯一详情和关联记录，不得把成员、服务、Skill、KB、应用和调用明细全部堆在首页。列表 SHALL 提供适用的搜索、筛选、分页、返回上下文及加载/空/错误/无权限状态。当前租户的名称、外部状态来源和可执行动作 SHALL 清晰呈现。

#### Scenario: 管理员查看一个应用使用的 OCR 服务
- **WHEN** 获授权租户管理员从应用列表进入应用详情，再进入该应用可用的 OCR 服务
- **THEN** 每层展示当前对象及下一层关联列表，面包屑可返回原筛选位置
- **AND** 页面不会展示其他租户应用或平台供应商采购信息

#### Scenario: 从不同入口进入同一额度详情
- **WHEN** 管理员从本租户配额清单或从服务详情中的关联额度进入同一笔赠送额度
- **THEN** 两条路径打开同一个配额详情及同一用量事实，返回时分别保留原列表筛选，不生成两套额度记录页面

### Requirement: TMS 只能查看 OMS 配置的本租户配额

TMS SHALL 显示本租户获 OMS 授权的服务、能力、额度剩余和可核对用量。充值和赠送额度 SHALL 在**同一个一级只读列表**按获取方式筛选；配额详情 SHALL 显示 OMS 配置的来源、数量、单位、有效期、已用、剩余、关联服务和真实消耗明细。OMS SHALL 是租户配额的唯一配置方，包括授予、充值、赠送、调整和撤销；TMS MUST NOT 提供任何配额写入入口或 API，也不得通过应用/成员上限等变相方式配置配额。TMS MUST NOT 扩大平台授权、创建供应商供给、修改平台 Provider/Secret、设置租户售价或产生欠费账单。额度耗尽只影响对应服务的新调用，登录、管理、历史查询和其他服务保持可用。租户开通、暂停与恢复仍以 EduPlus2 权威事件为准，TMS 不提供直接改写入口。

#### Scenario: 查看 OMS 配置的本租户配额
- **WHEN** 获授权管理员打开一笔 OCR 配额详情
- **THEN** TMS 展示 OMS 配置的授予事实、剩余额度、关联服务和实际消耗，提供返回列表及钻取调用明细的路径
- **AND** 不出现创建、编辑、充值、赠送、调整、撤销配额或设置应用/成员配额上限的操作

#### Scenario: 统一筛选赠送和充值
- **WHEN** 管理员在本租户配额清单选择“赠送”或“充值”获取方式
- **THEN** 同一列表筛选出相应记录，并可查看每笔已用、剩余、有效期及真实消耗；不跳转到独立的财务购买或赠送管理系统

#### Scenario: 尝试修改配额或使用未获授权服务
- **WHEN** 租户管理员直调 TMS API 尝试增加额度、修改获取方式/有效期或为应用设置配额上限，或尝试使用 OMS 未授权的 OCR 服务
- **THEN** 服务端拒绝配额写入及未授权服务使用，不依赖前端隐藏按钮，并且不改变 OMS 授予或真实用量

#### Scenario: OCR 额度耗尽
- **WHEN** 当前租户 OCR 服务额度耗尽而其他服务仍有额度
- **THEN** TMS 显示 OCR 新调用受限和相应剩余量；租户仍可登录、管理、查看历史及使用其他获授权服务

### Requirement: TMS 配额与用量视图必须可信且不可写

TMS 的配额与用量视图 SHALL 仅来自可信租户范围内的 OMS 授予与 DeepTutor 真实执行记录；TMS 不得修改、手工核销或伪造任何授予、余额及实际消耗。真实调用按可信用量扣减租户额度一次并遵循赠送优先；租户额度不足、平台服务供给不足及用量待核对 SHALL 呈现不同状态，未知用量不能当零释放额度。

#### Scenario: 消耗尚待核对
- **WHEN** 一次 OCR 调用的最终消耗尚未可信确认
- **THEN** TMS 标记该调用及相关额度为待核对，不显示零消耗或虚假的精确剩余量

#### Scenario: TMS 不能改写消耗记录
- **WHEN** 管理员尝试通过 TMS 接口核销、删除或调整一条 OCR 消耗记录
- **THEN** 服务端拒绝写入，历史消耗和 OMS 授予记录均不改变

### Requirement: TMS 必须保留 EduPlus2 和个人资源的权威边界

TMS SHALL 只管理可信当前租户的应用/client 归口、租户资源 grant、知识库/文件实例及获授权 Agent/工具配置。EduPlus2 SHALL 继续作为用户、组织、身份和租户 lifecycle 的权威；TMS 不创建第二套学校组织、用户密码或租户开停流程。管理员角色本身 MUST NOT 自动授予他人的私有会话、记忆、笔记、文件正文或 KB 内容读取权；现有 owner/显式 grant 仍须生效。

#### Scenario: 跨租户 client 注册或私有资料访问
- **WHEN** TMS 用户伪造目标租户、注册不属于当前租户的 EduPlus2 client，或凭管理员身份读取未授权个人资料
- **THEN** 真实管理接口拒绝且不泄露目标资源是否存在；原型展示无权限状态而不模拟成功

### Requirement: TMS 必须分层管理本租户 Skills 而不改写平台 Skill

TMS SHALL 在“服务与配额”下提供独立 Skills 列表；云端 Skill owner SHALL 仅为 `global` 或当前 `tenant`，来源（内置、ZIP 提交、Hub 导入）独立标识。TMS SHALL 只读查看已发布且获 OMS 授权给当前租户的 `global` Skill，授权生效即可在该租户使用，无成员/应用二次分配。具备租户资源管理权限的管理员 SHALL 仅以包含 `SKILL.md` 的 ZIP 包创建或更新当前 `tenant` 的 Skill 草稿，或从受控 Hub 实际取得并校验同类包；不得接受单独 `SKILL.md`、纯文本正文或仅填写 Hub URL 作为完整 Skill。TMS SHALL 从包内 `SKILL.md` 解析并只读展示名称、说明、标签、依赖等内容元数据及正文；不得用表单输入或 ZIP 文件名覆写，tenant owner、来源、审核/发布状态和包摘要由可信平台上下文决定。管理员可查看包版本与审核状态，并在通过安全校验后发布供本租户使用；不得更改 global 内容或授权、提升为 global、写入配额。创建/导入/更新 SHALL 使用独立包预览模态框，列表详情 SHALL 使用抽屉；高影响发布/撤销 SHALL 使用确认模态框并在取消时保留文件及列表上下文。ZIP 解包 SHALL 形成一个 DeepTutor 可识别的 Skill 目录，包含唯一 `SKILL.md`；其有效 YAML frontmatter 须有符合规范的 `name`、非空 `description` 和非空 Markdown 正文，可带 `references/` 与受控支持文件。原型 SHALL 对完整包做格式、路径、目录名、重复/危险文件、体积、加密/损坏/膨胀检查，但浏览器预检不能冒充正式服务端安全审查；未经审查不得自动启用或设置不受控 `always` 注入。Skill 自身不单独产生 Token 配额/消耗，其执行调用的模型/工具仍受 OMS 授予的底层服务资格和额度约束。真实企业 owner 与运行时 `read_skill` 授权不是现有用户级 `/api/skills` 已具备的能力，须由后续实施提案交付。

DeepTutor builtin Skill SHALL 在云端作为 `owner=global, source=builtin` 的只读来源处理，不增加第三种 owner；默认未获租户授权时，TMS 不得把它列为可用、提供详情正文或通过客户端数据泄露内容。OMS 授权后，TMS SHALL 区分“已授权”与 `requires` 运行条件就绪；运行条件不满足时不得显示为可用。租户上传同名 Skill 的确认和 tenant 优先规则同样适用于 builtin；本地 DeepTutor 的 builtin 自动发现行为不变。原型只展示合成授权/就绪状态，不声称已拦截真实 `read_skill`。

#### Scenario: 租户管理员提交自用 Skill 包
- **WHEN** 获授权租户管理员从 Skills 列表提交 ZIP，包内唯一 `SKILL.md` 声明有效名称、说明、可选元数据与非空 Markdown 正文，并带有受控参考文件或脚本
- **THEN** TMS 从 `SKILL.md` 和文件树生成只读预览；经原型格式预检后作为当前 tenant owner 的待审查草稿回到原列表、可在详情抽屉回读；草稿不可被运行时读取或把浏览器预检冒充真实安全审查
- **AND** 发布后仅当前租户可用，不需 OMS 再授权或 TMS 再向成员/应用分配，且不改变服务授权、配额或实际用量

#### Scenario: 拒绝缺失或伪造包内元数据
- **WHEN** 管理员只填写正文、选择单个 `SKILL.md`、提交含缺失/无效 frontmatter、目录与 `name` 不符、重复 `SKILL.md`、危险路径、链接、加密、损坏或超限内容的 ZIP
- **THEN** TMS 不保存草稿，不用表单值、ZIP 文件名或包内自报的 owner/状态补全；展示可理解的具体错误，正式服务端须独立重验

#### Scenario: TMS 与 OMS 共用有分类的包错误提示
- **WHEN** 本租户管理员提交缺失 `SKILL.md`、YAML 格式无效、含辅助文件或路径不合规的 ZIP
- **THEN** TMS SHALL 使用与 OMS 同一预检与提示组件，指出问题类型、已知文件路径和修复建议；缺少文件或 YAML 错误不得被称作安全威胁
- **AND** 未通过预检时不保存 Skill；再次点击保存不得用笼统提示覆盖具体错误

#### Scenario: 更新本租户 Skill
- **WHEN** 租户管理员编辑非 builtin 的 tenant Skill
- **THEN** 只能提交 `name` 不变的新 ZIP 包版本，原包保留供审计，新版本重新待审核，不就地更改正文或发布状态

#### Scenario: 上传与已授权 global Skill 同名
- **WHEN** 租户管理员上传的 Skill 名称与当前租户已获授权的 global Skill 相同
- **THEN** 上传表单在提交前明确提示“发布后优先使用本租户 Skill，原 global 同名 Skill 在本租户不再被同名调用选中”，并展示两者 owner；只有管理员在独立确认模态框明确确认后才保存上传草稿
- **AND** 取消确认不保存；已发布 tenant Skill 对同名调用优先，即使 tenant Skill 暂不可用也不静默回退 global，其他租户仍使用其获授权的 global Skill

#### Scenario: 后授权或撤销引起同名解析变化
- **WHEN** 租户已有同名 tenant Skill 后 OMS 才授权 global Skill，或管理员撤销已发布的同名 tenant Skill
- **THEN** OMS/TMS 标出覆盖关系；撤销前提示 global Skill 将重新成为本租户的同名候选，运行时始终按 tenant 优先、其次已授权 global 的确定顺序解析，不发生无提示的优先级变化

#### Scenario: 查看已获授权的平台 Skill
- **WHEN** 租户管理员查看配对演示案例中已发布且获 OMS 授权给当前租户的平台 Skill
- **THEN** TMS 以只读安全投影展示其详情，不提供编辑平台内容或修改授权范围的动作；若无已发布同名 tenant Skill 即可直接使用
- **AND** 未发布草稿、未授权平台 Skill、其他租户 Skill 与内部审查材料不进入 TMS 数据投影；独立原型不宣称 OMS 本地草稿实时同步

#### Scenario: 授权或未授权的 builtin Skill
- **WHEN** 当前租户尚未获 OMS 授权 `pdf` builtin，或虽获授权但执行环境不满足其 `requires.sandbox: shell`
- **THEN** 前者不出现在 TMS 可用数据投影；后者显示“已授权·暂不可用”及缺失条件，而非误报可用
- **AND** tenant 管理员上传同名 `pdf` Skill 时，若该 builtin 已授权则仍须明确确认 tenant 版本发布后将优先使用

#### Scenario: 越权导入或访问 Skill
- **WHEN** 普通成员尝试管理租户 Skill，或管理员指定其他租户、导入未审查内容并请求自动启用
- **THEN** 原型拒绝并展示无权限或待审查状态；后续真实 API 必须按可信租户和动作权限拒绝，不能依赖前端隐藏

### Requirement: TMS 与 OMS 必须复用同一服务业务组件并隔离数据

OMS/TMS 共有的服务与 Skill 列表、状态、筛选、分页、详情导航和错误呈现 SHALL 来自同一共享前端业务组件与设计规范；TMS SHALL 通过自身应用容器和租户安全 DTO 提供数据及动作，不得复制 OMS 业务组件、直接 import OMS 应用页面，或将平台专有信息/未授权 Skill 内容传给共享组件后隐藏。共享组件变更 SHALL 同时验证 OMS/TMS 的构建、视觉与交互，并检查独立发布版本兼容。

#### Scenario: 两端展示 OCR 服务列表
- **WHEN** OMS 平台人员和 TMS 租户管理员分别打开 OCR 服务列表
- **THEN** 共用列、状态文案、搜索/筛选、分页和查看详情交互保持一致，均由同一业务组件渲染
- **AND** OMS 的采购成本、供应商凭据与跨租户记录不会出现在 TMS API 响应、页面状态或导出中

#### Scenario: 两端展示 Skill 列表
- **WHEN** OMS 平台人员和 TMS 租户管理员分别打开 Skills 列表
- **THEN** 共用列、来源/状态文案、搜索/筛选、分页和详情交互由同一业务组件呈现，写入动作分别由各自容器提供
- **AND** TMS 的安全视图模型不含 OMS 跨租户授权名单或内部审查材料

### Requirement: TMS 开发态原型不得冒充真实租户管理

目标云端 `/tms/prototype` SHALL 只在开发环境使用明确标注的合成租户/成员/应用/服务/配额/KB 数据及本地模拟动作；配额清单、详情与消耗明细仅可查看，不得提供模拟配额编辑。正式 `/tms` 在可信身份、真实接口、权限和租户隔离验收前保持未启用，生产原型路径 SHALL 返回真实 HTTP 404。旧 DeepTutor `web/app/tms` 占位页和其他旧演示 MUST NOT 被声明为 TMS 原型验收完成。

#### Scenario: 评审本租户配额只读流程
- **WHEN** 评审者在开发环境从本租户配额清单进入 OCR 额度详情及单次消耗明细
- **THEN** 原型展示统一赠送/充值列表、OMS 配置事实和真实消耗的合成样例，且没有配额写按钮或模拟配额写动作
- **AND** 在未授权、额度不足或跨租户样例下给出拒绝/受限状态，不把演示数据带入正式入口
