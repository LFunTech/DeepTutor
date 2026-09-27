# OMS / TMS 独立前端原型

此目录交付两个**仅供开发环境审计**的前端应用，不是 DeepTutor 本地 Web 的云端管理功能，也不连接真实 OMS/TMS API。业务契约以 `openspec/changes/add-c1-oms-operations-prototype` 与 `add-b2-tms-management-prototype` 为准。

OMS/TMS 面向操作人员统一展示平台名**智能体基座**；在提示、来源等语境中可简写为“基座”。OMS 的后台名称仍为“平台智能体运营后台”，TMS 仍为“学校智能体管理后台”。`DeepTutor` 仅保留为本地产品、源码/执行语义来源及技术标识，不作为两个云端后台的界面品牌；包名、接口字段、存储键与路由不因展示名称变更。

## 运行

```bash
cd extensions/enterprise/frontends
npm ci --legacy-peer-deps
npm run dev:oms  # http://127.0.0.1:4310/oms/prototype
npm run dev:tms  # http://127.0.0.1:4311/tms/prototype/demo-school
```

两个应用的 `turbopack.root` 均固定为此前端 workspace，避免误把用户目录下的 `yarn.lock` 当项目根目录。开发错误叠层中的 `next-code-frame` 多字节 panic 也可能出现在 Webpack 模式，切换打包器不能代替排查真正的渲染错误；原型的服务端首屏渲染有独立回归测试。

两个应用可分别 `npm run build:oms`、`npm run build:tms`，分别构建与部署。共享 `@deeptutor/admin-ui`、`@deeptutor/service-components`、`@deeptutor/api-contracts`、`@deeptutor/branding` 使用同一 `0.1.0` 契约版本；TMS 不导入 OMS 应用代码。开发态访问旧 `/tms/prototype` 会跳转到受控演示学校路径；生产构建的 `/oms/prototype`、`/tms/prototype` 及其全部子路径在 Proxy 渲染前返回 HTTP 404；正式 `/oms`、`/tms` 尚未启用。

## EduPlus2 品牌主题

两个独立前端各自在服务端使用部署环境变量 `EDUPLUS2_BRANDING_BASE_URL`，其值是**当前环境的 EduPlus2 认证服务根地址**，例如测试环境 `https://eduplus-auth-test.f123.pub`；代码只拼接固定的 `/api/v1/public/branding`，不把测试域名写成默认值。OMS 不附带学校参数，读取平台默认品牌。TMS 原型可额外配置 `TMS_DEMO_SCHOOL_CODE`（学校 code，即 EduPlus2 `school_code`）与 `TMS_DEMO_TENANT_ID`（EduPlus2 学校 ID）；仅两个值齐全、格式有效且为开发环境时，才按该配对请求学校品牌并启用对应路径。例如测试环境的 `jygjzx` 与 `92` 对应 `/tms/prototype/jygjzx`，可预览学校紫色；业务记录仍是合成数据，页面有提示。其他学校 code 的开发路径不展示业务内容。正式 TMS 不使用演示变量，必须由后续真实身份集成提供并验证学校绑定；URL code 只定位页面，不提供授权或跨学校切换。

```bash
# 分别在两个终端启动；预发布/生产环境替换成各自的认证服务域名。
EDUPLUS2_BRANDING_BASE_URL=https://eduplus-auth-test.f123.pub npm run dev:oms
EDUPLUS2_BRANDING_BASE_URL=https://eduplus-auth-test.f123.pub TMS_DEMO_SCHOOL_CODE=jygjzx TMS_DEMO_TENANT_ID=92 npm run dev:tms
```

修改环境变量后须重启对应前端进程；不要在已占用 4310/4311 端口时再启动第二份实例。TMS 对外名称为**学校智能体管理后台**；保留 `TMS`、`tenant_id`、`tenant.*` 与 Skill `owner=tenant` 等技术契约，面向操作人员的界面统一称“学校”。

接口的完整 `palette` 在首屏映射到两端共用的导航、按钮、链接、焦点与页面背景；请求超时、域名缺失或颜色不合规时回退可读的天蓝色，不阻断页面。服务端缓存目标为 5 分钟，品牌变化在缓存到期后的下次加载生效；已打开的页面不承诺实时换色。`logo_url`、学校名称和登录文案不在本次颜色切换范围内。域名与演示学校标识均不可从页面 URL 覆盖，也不构成授权证据。

## 审计边界

- OMS：以列表为主工作区，详情在抽屉中逐级查看，关闭后保留列表；新增、编辑、平台策略、授权、额度和供给等维护表单弹出独立模态框，不在列表或详情中撑开空间。需复核的操作再进入确认框，取消复核返回已填写表单。五类平台目录提供类型化新增；服务可分别登记 Provider Profile 与模型草稿，资源供给可登记方案与待核对批次。草稿可回读，但未接入执行者前不冒充可用资源。
- TMS：当前演示学校的合成成员、应用、服务、**只读配额清单**、知识资源与用量；列表详情使用抽屉，应用与成员访问维护使用模态框。“查找本校账号”是独立的合成目录模态框，用来演练可见范围、无权、失效与故障状态；未本人登录并完成本校登记的账号不能从搜索结果直接授权。赠送/充值是同一额度列表的获取方式；TMS 不配置、充值、调整或撤销额度，也不设置成员/应用额度上限。演示路径与配对配置核对，但不代表已接入真实身份授权。
- Skills：OMS 管理只读基座内置 Skill 与平台 `global` Skill 的草稿、审查、发布申请和学校授权；TMS 仅看到配对演示中已授权的 global 安全投影，可维护本学校 `tenant` Skill。TMS 同名上传须确认，发布后的本学校版本优先；取消确认保留表单和文件。文件/ZIP 校验只是浏览器侧预检，真实安全提取、审核、授权及运行时 `read_skill` 尚未实施。两个原型状态**不会实时同步**。
- 两端使用完全相同的 OCR、其他服务与 Skill 列表业务组件，包括共用列、搜索、分类筛选、分页、状态与详情交互。各自 fixture 与动作留在应用内，安全共用 DTO 只含双方都可见的字段。
- OMS 设置字段参考 DeepTutor 现有 `settings-attribute-inventory.md`；OCR 是文档解析引擎中的能力示例，不宣称已有独立 OCR Provider。所有供应商、学校、用量和凭据状态均为合成演示，不代表后端配置已发布或执行者已生效。
- OMS 供应商连接、独立 Profile 及 MinerU 云端/Docling 远端有独立凭据操作模态框，仅平台管理员可见；只接受 `demo-` 开头的演示值，不要粘贴真实密钥。提交后输入值即丢弃，只在当前页面生命周期内回读“已录入演示值 · 未验证”；没有真实 Secret 托管、连接测试或模型/OCR 调用。绑定连接的 Profile 只能到连接维护凭据，TMS 没有平台凭据入口。
- 额度不足只影响对应服务新调用；登录、管理和其他服务仍可使用。未知用量标记待核对，不当作零。无学校价格、账单、欠费或虚构供应商成本金额。
- 原型没有生产 OMS/TMS 业务 API 请求、数据库、OpenFGA、Keycloak 或 Secret 写入；品牌色只读请求是对 EduPlus2 公开接口的独立展示依赖。OMS 身份抽屉展示用户指定的预期 Client ID `eduplus-platform-admin`，但没有真实授权码换票或平台人员目录。平台管理员可维护配置与策略草稿，平台运营可演示权益与供给操作，审计角色只读；学校开停、真实用量和审计事实仍不可直接改写。演示角色只是视觉/交互状态，**不能替代真实服务端授权**。首位学校管理员须按另行验证的学校侧双负责人合同受控开通；学校生命周期 Webhook 不提供此授权。后续生产实施需经独立 OpenSpec proposal、权限、迁移和上游兼容验收。

## 验证

```bash
npm test
npm run lint
npm run typecheck:oms
npm run typecheck:tms
npm run build:oms
npm run build:tms
```

2026-09-27 本轮原型回归：前端 25 个测试文件／247 项通过，两应用 typecheck、lint、build 和 Provider descriptor 快照检查通过；OpenSpec 两个原型 change 与全量严格校验通过。浏览器在桌面/窄屏访问 OMS 16 个、TMS 12 个顶层开发路由，并逐个操作首行的全部具名动作；还演练了 Qwen 模型、Docling OCR 草稿与 TMS 应用服务关系。审计矩阵、视觉检查及生产 404 证据见 [双端浏览器记录](../../../openspec/changes/add-c1-oms-operations-prototype/prototype-browser-audit-2026-09-27.md)。**合成原型的验收不替代真实 API、身份、权限或执行者验收。**

本地 DeepTutor Web 的旧 `/oms/prototype` 开发入口会跳转到独立 OMS 原型；旧正式 `/oms`、`/tms` 入口退役。保留在 `web/features/oms-prototype/` 的旧演示源码仅作历史迁移参考，不再被路由引用，不属于新原型构建。
