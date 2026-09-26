# 云端 TMS 高保真原型与 OMS 共享组件规划

## Why

现有 `web/app/tms` 只是 DeepTutor 本地 Web 构建内的规划页，`web/app/(admin)/admin` 也不是学校管理员可直接使用的云端管理产品。用户已确认 OMS/TMS 前端应独立部署，且同类服务组件必须复用；需要先规划 TMS 的学校内信息架构、权限和与 OMS 的组件共享，再开发高保真原型，避免复制 OMS 页面或将学校管理员提升为平台管理员。

## What Changes

- 规划独立构建/部署的云端 TMS 前端，对外名称为**学校智能体管理后台**，面向学校管理员和获授权角色；保留 TMS 技术缩写及 `/tms` 路径。EduPlus2 教育业务中一个 `tenant` 即一所学校，`school_code` 即学校 tenant code；技术 `tenant_id`、`tenant.*`、Skill `owner=tenant` 不整体重命名。DeepTutor 本地 Web 保留本地使用与设置功能，不被视作云端“用户端”，也不作为 TMS 生产构建。
- 规划学校 code 路由 `/tms/{schoolCode}` 及列表、详情子路径；根入口 `/tms` 在验证管理员账号后跳转至其唯一学校，不提供任意学校切换。URL code 仅定位页面，须与可信管理员身份的学校 ID/code 绑定核对，不接受路径改写作为授权。开发原型采用开发态专用的 `/tms/prototype/{schoolCode}`，与正式入口和生产 404 分离。
- 学校管理员账号及学校/角色关联由 EduPlus2 权威同步；目标是经签名 webhook 接收变更与撤销，登录凭证仍由 EduPlus2 管理，不能因收到账号事件就跳过登录校验。现有 B2 lifecycle webhook 只规划学校开停，不代表管理员账号同步已实现；事件字段、幂等、对账和撤权须在正式 TMS 身份实施中另行确认。
- 以**一个可信当前租户**为顶层上下文，重订为工作台、成员与权限、应用与接入、服务与配额、知识与内容、用量与记录六组导航。各组从对象列表进入唯一详情及关联记录；Agent、工具、OCR 等获授权能力归“服务与配额”，不另设重复目录。TMS 管本租户应用/client、明确授权范围内的资源 grant、KB/文件实例和服务使用资格；不得创建第二套 EduPlus2 用户/组织权威或直接开停租户。
- **本租户配额清单是一级只读列表**，与可用服务列表并列，而非藏在服务详情下。赠送/充值是同一清单的获取方式筛选；管理员可进入配额详情，查看 OMS 配置的获取方式、来源、总量、已用、剩余、有效期和真实消耗明细。TMS 配额页面没有新增、编辑、撤销、充值、赠送或调整上限等写入动作。
- **Skills 是服务与配额下的独立清单**：云端 Skill owner 仅为 `global` 或当前 `tenant`。DeepTutor builtin 是只读 global 来源，云端默认未授权；OMS 授权给当前租户后，TMS 才能查看，并在运行条件满足时使用，无成员/应用二次分配。获授权的租户管理员仅通过提交符合 Skill 目录规范的 ZIP 包创建或更新本租户 Skill；受控 Hub 导入也必须取得并校验真实包，不接受单文件 `SKILL.md` 或纯文本创建。名称、说明、标签与依赖等 Skill 内容元数据均从包内 `SKILL.md` 读取，不在 TMS 表单手填；可信 tenant owner、来源、审核状态和包摘要由平台确定。上传与已授权 global（含 builtin）同名时必须预先提醒并由管理员明确确认；运行时 tenant 同名 Skill 优先，global 版本不被删除。个人 Skill 保留在 DeepTutor 本地产品，不成为云端第三种 owner；Skill 本身不单独形成 Token 配额。
- OMS 是租户级服务授权及全部配额配置（总量、获取方式、来源、有效期和调整/撤销）、供应商供给的唯一写入权威。TMS 不提供配额写 API，不采购供给、不设租户价格/账单，也不管理平台 Provider/Secret。有效可用量不能超过 OMS 授予的剩余额度；额度耗尽只影响相应服务的新调用，不阻断登录、管理、历史和其他服务。
- 与 [`add-c1-oms-operations-prototype`](../add-c1-oms-operations-prototype/proposal.md) 共用管理后台设计规范和可复用业务组件。OCR 服务列表与 Skill 列表均是必验样例：OMS 与 TMS 使用同一组件的共用列、搜索、分页、状态和详情交互，但由各自应用装配 API、权限与专有操作；TMS 接口不能把 OMS 的平台 Secret、成本、跨租户数据或未授权 Skill 内容先返回再隐藏。
- TMS 的管理 UI 品牌色从 EduPlus2 公开品牌接口读取当前可信租户的 `palette`，与 OMS 共用主题 token 和校验规则，但不共用 OMS 的平台主题实例。认证服务域名由环境配置，原型租户标识由部署演示配置提供；真实 TMS 必须改为可信身份上下文，不以 URL 查询或本地 fixture ID 充当授权来源。接口失败时有天蓝色兜底，成功、警告、错误仍按语义区分。
- 交付仅开发态高保真原型的目标、演示数据边界和验证任务；不宣称 TMS 真实 API、EduPlus2 client 注册、用户 grant、KB 操作、企业级 Skill 作用域/执行授权或云端部署已完成。现有 `web/app/tms` 占位页须标为旧基线。

## Capabilities

### New Capabilities

- `enterprise-tenant-management-prototype`：云端 TMS 独立前端、租户内逐级 IA、本租户只读配额清单及消耗明细、平台 Skill 只读与租户 Skill 维护、OMS/TMS 组件复用、权限与开发态原型契约。

### Modified Capabilities

无。当前只建立新原型目标；后续真实 TMS API、身份及租户数据变更由相应实施 change 补充正式 delta。

## Impact

- 规划目标是独立 TMS 应用及 OMS/TMS 同仓共享组件包；保留云端 `/tms` 入口并以 `/tms/{schoolCode}` 为学校上下文，不得让 TMS 从 OMS 应用目录 import 页面或依附 DeepTutor `web/` 构建。现有 `/tms/prototype` 是旧开发原型入口，待实施时迁至 `/tms/prototype/{schoolCode}`；fixture 不得进入正式入口，生产全部原型路径须返回 HTTP 404。
- 后端继续以 DeepTutor 核心语义与企业扩展为来源，TMS 专属接口在可信当前租户上下文授权；采用一个云端后端服务还是多个部署留待 API/安全实施提案按隔离和发布需求决定，不因前端分开复制业务逻辑。
- 与 B2 的 EduPlus2 生命周期、身份/应用归口、TMS 租户授权及 KB/资源权限方案互相依赖；与 OMS 原型的共享组件契约、服务授权/额度方案协同。后续真实 API 须分离 OMS 的配额写入能力与 TMS 的当前租户只读配额投影，并为企业平台/租户 Skill 新增受控作用域及运行时授权；本原型不宣称这些 API 已存在。旧 `docs/enterprise/02-*`、`11-*`、`12-*` 中“微调 DeepTutor 管理页即可交付 TMS”的表述须重订，并统一配额只读边界。
- 本 change 仅规划文档；不修改生产路由、DB、OpenFGA、Keycloak、运行代码或真实租户数据，也不授权后续实施提案绕过各自审批。
