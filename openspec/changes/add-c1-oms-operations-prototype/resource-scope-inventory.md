# DeepTutor 资源对象与 OMS/TMS 作用域盘点

本表依据 2026-09-26 工作树可见的本地 DeepTutor 设置导航、API router 和运行时 registry/services 制定**云端原型覆盖范围**。OMS/TMS 各自独立部署，服务列表等共享组件可复用但平台与租户 DTO/动作严格分离；本地 Web 不因此变为云服务用户端。列出资源不代表现有企业管理 API、租户隔离或配额执行已经实现；当前可否管理、能否计量须由后续实施 change 逐项实证。规范性归属以 `design.md` 为准。

| 资源组 | 当前 DeepTutor 证据 | OMS 平台对象 | TMS / DeepTutor 业务对象 | 额度与计量判断 |
| --- | --- | --- | --- | --- |
| 模型/外部服务 | `settings-nav.ts`、`SettingsStore.tsx`、`ServiceConfigEditor.tsx`、`deeptutor/api/routers/settings.py` | 服务目录、provider/profile/model、连接/Secret ref、诊断、发布、生效、供应商资源方案 | TMS 在 OMS 授权范围内分配本租户用户/应用可用服务；普通用户不改平台供应商 | 每项可调用服务有授权/额度；Token 仅在真实 usage 可核对时使用，其他保留原生单位或可信调用次数 |
| Agent/Capability | `deeptutor/runtime/registry/capability_registry.py`、`deeptutor/capabilities/`、`deeptutor/api/routers/capabilities.py`、`capabilities_settings.py` | 能力目录、平台参数、依赖模型/工具、可用范围与版本 | 租户选择获授权能力；用户会话和结果仍按 owner 保护 | Agent 顶层运行可有独立指标；底层模型/工具消耗不能重复计入同一服务额度 |
| 工具/Skills/MCP/CLI 应用 | `tool_registry.py`、`routers/tools.py`、`skills.py`、`mcp_settings.py`、`space_mcp.py`、`space_cli_apps.py` | 共享工具/技能/集成目录，管理员连接、准入与安全策略 | 租户/用户仅在授权范围内安装、选择或使用；个人 MCP 不自动变平台凭据 | 仅真实可调用且可计量的服务配置额度；纯目录/开关只做授权和版本 |
| 外部子智能体/伙伴/角色 | `routers/subagents.py`、`partners.py`、`partner_groups.py`、`personas.py`、`services/subagent/`、`services/partners/` | 可复用模板、平台接入、服务依赖与可用范围 | 伙伴实例、群组、私有角色及关联会话按既有 owner/租户授权管理 | 外部模型/渠道调用按真实底层服务计量；不得读取个人伙伴私有对话 |
| 知识与解析 | `routers/knowledge.py`、`services/parsing/`、`services/rag/`、`DocumentParsingSettingsSection.tsx` | 解析/检索服务、LightRAG 受控连接、容量/安全/引用策略 | 租户 KB、文档、索引授权和内容由 TMS/业务 owner 管理 | 解析/检索调用及容量按可核实单位；不得把 KB 文档内容变成 OMS 用量详情 |
| 文件、附件与内容存储 | `routers/attachments.py`、`resources.py`、`workspace.py`、`services/storage/` | 平台附件限额、对象存储/工作区策略与必要状态 | 具体文件、资源包、输出和访问权归租户/用户，遵守现有 ObjectStore 作用域 | 容量、请求等只有真实服务执行与存储记录能支撑时可建额度 |
| 记忆、学习资料和会话 | `routers/memory.py`、`sessions.py`、`notebook.py`、`book.py`、`courses.py`、`services/memory/` | 脱敏策略、容量/保留规则与运行健康 | 私有记忆正文、笔记、书籍、课程与会话按 owner/明确 grant 管理 | OMS 可看必要脱敏聚合，不看正文；不把个人内容视为平台采购资源 |
| 运行与后台任务 | `services/sandbox/`、`services/cron/`、`services/workspace/`、`routers/system.py` | 执行环境/安全策略、任务与容量状态、受控网络/部署配置 | 用户触发的任务与输出仍按 owner/租户隔离；TMS 管本租户允许范围 | 沙箱时长/任务次数等需明确执行者和不确定结果处理；高风险操作不直接暴露给普通运营 |
| 个人偏好 | `AppearanceSettingsSection.tsx`、`LearnerProfileSettingsSection.tsx`、`GuardianSettingsSection.tsx`、`settings.public_router` | 非 OMS 平台资源 | 留在个人/业务界面；仅最小非管理 API 保留 | 不建立租户服务额度 |

Skill 必须区分 **owner** 与来源：云端 owner 仅 `global` 或指定 `tenant`；来源可为内置、人工创建、受控 Hub 导入或租户上传。DeepTutor `SkillService` 当前区分 `builtin`（只读）与 `user`（本地用户可写）；`multi_user/skill_access.py` 将管理员分配 Skill 标记为 `source=admin, assigned=true, read_only=true`，但这不是云端 owner 模型。云端 builtin 映射为 `owner=global, source=builtin`，内容只读，首次接入/新增时默认零租户授权；OMS 仅可按租户授权/撤权及复核打包版本，TMS 获授权后直接使用但仍受 `requires` 限制。云端 Skill 是企业扩展的新增作用域，不能直接调用用户级创建接口并将结果改标来源。OMS 另管人工/Hub global Skill 创建与审查；TMS 可上传本租户 owner 的 Skill，与已授权 global（含 builtin）同名须管理员上传前确认，发布后同名调用仅用 tenant 版本，且仅本租户可用；个人 Skill 仍属于本地产品，不是云端第三种 owner。Skills 是指导内容而非独立模型计量服务；其执行所调用的底层服务才进入额度总账。

跨组原则：OMS 页面展示平台目录、影响、授权、供给与用量，不复制 DeepTutor 内部业务数据库或私有内容管理；TMS/用户端不得调用平台 Secret/采购/跨租户管理 API。服务采购资源单位与实际消费单位不一致、供应商 pay-as-you-go 或无法对账时，必须标记能力/供给模式并暂停精确可授予额度宣称，不用静态样例替代真实依据。
