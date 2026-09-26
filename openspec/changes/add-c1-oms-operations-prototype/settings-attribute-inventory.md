# DeepTutor 现有设置语义 → OMS 平台配置对照

审计范围：2026-09-26 当前工作树。此表是**本地 DeepTutor 设置字段与条件规则的来源清单**，不是宣称 OMS 已有企业配置、PG desired/active、Secret ref 或执行者确认。新 OMS 独立云端前端必须遵守这些语义并以逐级管理页面承接；不能把本地 `/settings` 整页复制，也不能用原页面作云端管理旁路。本地部署仍保留该设置页面。OMS/TMS 的共同服务列表交互归共享前端包，不意味着平台 Secret/采购字段可流入 TMS。

## 来源与作用域

- 服务目录/可见性：`web/features/settings/navigation/settings-nav.ts`；catalog shape：`web/features/settings/store/SettingsStore.tsx`。
- 当前连接、服务与任务模型编辑条件：`web/components/settings/ConnectionsEditor.tsx`、`ServiceConfigEditor.tsx`、`TaskModelsEditor.tsx`；**类型里有字段不等于当前表单已支持维护**。
- Provider 候选、默认 endpoint/模型、搜索要求与能力：`deeptutor/api/routers/settings.py`、`deeptutor/services/provider_registry.py`、`deeptutor/services/config/provider_runtime.py`；OMS 不硬编码第二份 provider 列表，后端 descriptor 负责适用条件及显示。
- 当前本地 JSON/草稿/应用路径不是未来企业运行态权威。企业扩展需按平台、租户、个人作用域审计，配置发布只有执行者真实确认才能显示 active。平台维护入口在 OMS；租户内部分配在 TMS；个人偏好留个人界面。

## 模型目录服务：现有属性与 OMS 归口

| DeepTutor 对象 | 当前可见属性/规则 | OMS 管理层级与边界 |
| --- | --- | --- |
| 连接 `connections` | `provider`、`name`、`api_key`、`base_url` 及目标服务各自的 `model`；只覆盖 `llm/task/embedding/tts/stt/imagegen/videogen`，**不含 search**。`base_url` 可留空用默认端点；关联 profile 凭据由连接供给，profile 内不可独立改。`api_version`、`extra_headers` 在 catalog 类型中存在，但当前连接编辑器未暴露。 | “连接与凭据列表 → 连接详情 → 关联服务”；仅授权高权限人员维护，Secret 只用引用/受控解析，普通运营不见明文。 |
| 通用 profile | `name`、`provider`/`binding`、`base_url`、`api_key`；高级 `api_version`、非搜索服务的 `extra_headers`；关联 `connection_id` 只读来源。LLM/task 的 `api_format` 仅在 provider 返回多个选项时可选；`wire_api` 为推导值。OAuth/CodeBuddy、managed/read_only profile 不可按统一 API Key 必填处理。 | “服务 → 供应商配置列表 → 配置详情”；条件字段来自 descriptor，草稿/测试/发布与生效反馈分开；无权限者只读安全状态。 |
| `llm` 对话模型 | `active_profile_id`、`active_model_id`；模型 `name/model/context_window`、条件性 `reasoning_effort`、`capabilities.{tools,vision,json_output,reasoning}`。窗口检测与选项随 provider。 | 对话模型服务详情 → profile → 模型/能力详情；不得硬编码通用推理档位。 |
| `task` 任务模型 | profile/model 基础项与能力；**未单独配置时回退 LLM**。当前编辑器没有 LLM 专属 context-window/默认 reasoning-effort 控件。 | 任务模型独立服务详情；明确当前配置或回退来源，不假装与 LLM 表单完全相同。 |
| `embedding` 向量服务 | `name/model/dimension/send_dimensions`；endpoint 是精确请求地址，不额外拼 `/embeddings`；维度支持由后端/供应商决定。 | 向量服务详情 → 模型/维度条件；不提供未经核实的固定维度候选。 |
| `search` 联网搜索 | profile `name/provider`，按 provider 条件显示 `api_key/base_url/api_version/proxy`；**无模型列表和 active_model_id**，亦非 connections 目标。是否需要凭据/URL 及 soft fallback 由 descriptor 决定。 | 搜索服务独立配置详情；不显示虚构模型或 Token 配额单位。 |
| `tts` 语音合成 | 模型 `name/model/voice/response_format`；当前格式为 `mp3/wav/opus/aac/flac/pcm`；voice 为供应商相关自由文本。`voice_autoplay` 是个人播放偏好。 | 语音合成详情维护现有服务字段，播放偏好不进 OMS。 |
| `stt` 语音识别 | 当前编辑器仅有模型 `name/model`；catalog 类型预留 `language`，**现有编辑器没有此控件**。 | 语音识别详情不画“已有语言设置”表单。 |
| `imagegen` 文生图 | 模型 `name/model/size/quality/style`；大小/质量/风格自由文本，留空采用供应商默认；类型中的 `response_format` 当前编辑器不展示。 | 图片服务详情按现有字段和条件，不照抄语音/LLM 表单。 |
| `videogen` 文生视频 | 模型 `name/model/aspect_ratio/duration/resolution`；异步任务型服务。 | 视频服务详情独立展示任务型配置、测试与生效状态；时长/分辨率不套图片字段。 |

通用目录现有 profile/model 增删、选择、草稿保存、单服务应用和诊断测试；新 OMS 高保真原型应按列表→详情演示这些管理流程，但不能声称模拟保存已让真实执行者 active。每项服务的**配额单位和可信用量来源**须另经真实调用路径审计，不能从存在 model/profile 字段推出 Token 计量。

## 模型目录之外的服务与设置

### Skill 属性与设置页边界

Skill 不是 Provider profile，也不是可直接创建的 Tool/Capability 注册表条目。当前 `deeptutor/api/routers/skills.py` 的用户级创建字段为 `name`（1–64 字符）、`description`、`content`、`tags`；更新支持说明、内容、重命名和标签；Hub 导入使用 `ref`、可选名称及受控导入选项。`multi_user/skill_access.py` 对管理员分配给用户的 Skill 标记 `source=admin`、`assigned=true`、`read_only=true`；内置 Skill 只读。OMS/TMS 原型可复用这些**字段语义与只读规则**，但云端 `global`/`tenant` owner、版本、审核、发布与 global 按租户授权属于后续企业扩展契约，不可称作 DeepTutor 当前设置字段或调用用户级 `/api/skills` 冒充企业写入。授权生效后不增加成员/应用二次分配；TMS 上传是新增企业能力，当前用户级 API 不支持；与已授权 global 同名须管理员确认并按 tenant 优先解析。平台/租户导入与上传不得以演示开关绕过安全审查，Skill 调用底层服务才进入配额消耗。

当前打包 builtin 位于 `deeptutor/skills/builtin/{docx,pdf,pptx,skill-creator,xlsx}/SKILL.md`，`SkillService` 本地/用户层默认自动发现 builtin，运行时把可见 Skill 放入 manifest，`read_skill` 按需读取，`always` 是自动注入例外；部分 builtin 通过 frontmatter `requires.sandbox: shell` 约束执行环境。云端将 builtin **逻辑映射**为 `owner=global, source=builtin`，不复制为可编辑内容；云端默认零租户授权，OMS 只管理授权、就绪与打包版本复核。若企业运行时仍直接使用默认 `SkillService` 清单，未授权 builtin 会绕过 OMS，故正式实施必须在清单、`read_skill`、显式请求与 `always` 注入的共同边界过滤，必要核心 seam 先严格审阅；本地 DeepTutor 不改变。

| 范围 | DeepTutor 现有语义 | OMS / TMS / 个人边界 |
| --- | --- | --- |
| 文档解析/RAG | `DocumentParsingSettingsSection.tsx` 使用后端 `available_engines/readiness`；引擎 ID 为 `text_only`、`mineru`、`docling`、`markitdown`、`pymupdf4llm`、`liteparse`、`tika`。纯文本没有 OCR/表格开关；MinerU 的 `local/cloud`、Docling 的 `local/remote`、Tika 远端地址及各自 OCR/表格字段不同。LightRAG 为受控检索服务，不得由 OMS 直连其内部 PG/图或伪造 ready。 | OMS 维护平台解析/检索供给与服务配置；TMS/业务 owner 管租户 KB 和文档正文。原型字段按引擎条件显示，不宣称本地列出的所有引擎都已 ready。现有下载/安装操作不能未经权限/执行审计直接迁入普通运营 UI。 |
| 视频学习 | `VideoLearningSettingsSection.tsx`：`youtube/invidious` 播放来源、Invidious `api_base_url/public_base_url`，YouTube transcript provider。 | OMS 管共享外部服务配置；不等同于 `videogen` 模型，也不默认有 Token 用量。 |
| 外部 Agent | `AgentsSettingsSection.tsx` 使用各 `SubagentSettingsEditor`，admin-only 项及各 agent 参数不同。 | OMS 管平台可用 Agent/外部接入与测试；TMS/个人只在获授权范围内使用，不杜撰统一 model/key/endpoint 表单。 |
| 工具、能力、附件、起始建议、记忆策略 | `/settings` 中各有不同存储与作用域，并非全是 Provider。 | 平台默认/安全策略归 OMS；租户允许范围与内部使用归 TMS；个人偏好/私有记忆正文不进 OMS。逐项审计实际执行者后才能宣称生效。 |
| 网络、workspace、外观、学习档案、监护、关于 | 网络和 workspace 含运维风险；外观/学习档案/监护属个人或业务界面；“关于”不是管理资源。 | 网络/workspace 仅 OMS 高权限受控配置或只读部署状态；个人/业务页面保留非管理能力，不开旧 `/settings` 管理旁路。 |

## 原型验收约束

- 服务目录逐项覆盖八种现有 `CatalogService`；连接和目录外的解析、视频学习、Agent/工具另列，不伪装成 LLM profile。
- 管理字段/候选只来自源码和后端 descriptor；Secret 值、原始敏感 endpoint、个人内容不进入演示数据或普通运营详情。
- 平台配置动作在原型中明确为本地模拟。真实发布、租户授权、供给/额度和用量只有后续企业 API、权限与执行者确认完成才能上线。
