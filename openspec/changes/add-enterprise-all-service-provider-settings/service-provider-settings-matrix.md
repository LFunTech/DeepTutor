# 服务设置字段/descriptor/执行者矩阵（2026-09-28）

> 本矩阵用于任务 1.1：把现有 DeepTutor 设置 descriptor、OMS 原型离线快照、真实执行者加载点与企业计费/测试边界对齐。它不是实时供应商发现结果，也不包含 Secret 明文；正式写入和执行者确认仍由后续任务 1.3、2.x、3.x 验收。

## 源码证据

- descriptor 源：`deeptutor.api.routers.settings._provider_choices()` 与 `_connection_targets()`。
- OMS 快照：`extensions/enterprise/frontends/apps/oms/src/provider-descriptors.generated.json`，`source_revision=fa56c40d1866`，`reasoning_source_revision=995e22861401`。
- 快照生成/漂移检查：`extensions/enterprise/frontends/scripts/generate-provider-descriptors.py --check`。
- 安全投影：`extensions/enterprise/src/deeptutor_enterprise/oms/resource_status.py` 只输出描述符、readiness 与条件字段，不输出 Secret、endpoint Secret ref 或租户正文。

## 服务矩阵

| 服务 | descriptor 覆盖 | 主要条件字段 | 真实执行者/加载点 | 计费测试边界 | 未支持/门禁 |
| --- | --- | --- | --- | --- | --- |
| LLM 对话 | 40 个 provider 候选；含 OpenAI-compatible `api_format` 与 base URL 候选 | `provider`、`base_url`、`model`、API 格式、reasoning effort、tools/vision/json/reasoning 能力 | core 模型 provider/deployment profile；OMS `model_catalog_config` active 发布后由企业 runtime 读取 | 可计费测试必须指定已核验学校、school-scope 操作人和测试服务主体 grant，再进入 OMS 服务授权/额度/attempt 预留 | 无学校/无额度/无可信上界时只允许静态校验，不发供应商请求 |
| task 模型 | 与 LLM 同源 40 个候选；允许未配置时回退 LLM | task profile/model、回退目标、API 格式、能力 | task executor / model catalog active；回退需保留来源 | 回退仍按实际发出服务记账；不可把 task 测试冒充 LLM 免费健康检查 | 未单独配置时不生成虚假 active task 供应商 |
| embedding | 13 个候选，含维度默认值与新增 Lemonade embedding | model、endpoint、dimension、`send_dimensions` | embedding adapter / KB 索引入口 | 必须有已授权 embedding 服务、硬上界和 attempt 证据 | 不完整 endpoint 或未知维度组合不得标记 ready |
| search / web fetch | 18 个候选；无模型列表语义 | provider、API key 条件、base URL、proxy/API version/额外 header | search tool/web fetch adapter | 按请求次数或供应商返回 usage 结算；无上界时 fail closed | 不允许显示模型候选或复用 LLM 字段 |
| TTS | 9 个候选，含 Volcengine Speech | model、voice、response_format、base URL | TTS adapter / voice endpoint | 以字符或供应商可信 usage 结算；测试需学校服务授权 | 自动播放等个人偏好不进入 OMS |
| STT | 9 个候选，含 Volcengine Speech | model、language 预留、base URL | STT adapter | 以分钟/秒或可信 usage 结算 | 语言字段无执行者支持前不得宣称可维护 |
| imagegen | 8 个候选 | model、size、quality、style | image generation adapter | 以张/任务计；异步失败需待核对 | 不套用视频异步状态字段 |
| videogen | 3 个候选 | model、aspect_ratio、duration、resolution | video generation task adapter | 异步任务以可核验完成/失败证据结算；取消未知保持待核对 | 无可信任务回执时不开放硬额度调用 |
| 文档 OCR/解析 | 现有解析引擎与 OCR 能力在资源状态 API 投影；不是通用 provider 表 | engine readiness、OCR/table 选项、解析条件 | document parsing worker / LightRAG 协调链 | 以页数/任务或解析回执结算；cache hit 需不重复扣 | DeepTutor 不直连 LightRAG 内部 PG/图 |
| RAG/LightRAG | 受控 endpoint/API Secret、workspace binding、index version 只在后端配置 | endpoint readiness、workspace/index、contract version | LightRAG API adapter；图/检索库属于 LightRAG 部署 | 检索/索引用量按 operation ID 对账；缺远端确认保持待核对 | OMS 只看平台元数据，不读取租户正文或内部图连接 |
| 外部 Agent / 工具 / video-learning | 原型仅展示安全状态；运行参数待正式 descriptor | endpoint、API key 条件、公共 base URL、受控能力开关 | 对应 tool/capability adapter 或外部 agent runtime | 每个工具按服务授权和原生单位单独接入；不能套 LLM Token | 未有稳定 adapter/usage 合同时标 unsupported |
| 个人偏好/本地设置 | 不纳入平台 provider 配置 | appearance、memory、learner 等 | 本地/用户作用域 | 不计入 OMS 供应商用量 | 不得提升为平台 Secret 或全局配置 |

## 漂移处理

本轮重新生成 descriptor 快照，吸收上游/当前 core 新增的 Cheaper Inference、Unifically、Lemonade embedding、Volcengine Speech TTS/STT 等候选。后续每次 core settings descriptor 变化，必须先运行快照检查并审阅差异，再开放 OMS 配置草稿。
