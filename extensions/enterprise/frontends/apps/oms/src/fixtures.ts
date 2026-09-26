import type { ServiceView } from "@deeptutor/api-contracts";

// 原型数据独立于页面和共享组件；不模拟真实 API 或有效 Secret。
export const tenants = [
  { id: "aurora", name: "星河实验学校", code: "EDU-2048", kind: "学校", status: "正常", source: "EduPlus2", services: 9, grants: 4, usage: "42.8 万" },
  { id: "harbor", name: "海港职业学院", code: "EDU-1673", kind: "高校", status: "正常", source: "EduPlus2", services: 6, grants: 3, usage: "18.4 万" },
  { id: "north", name: "北辰研究院", code: "ENT-0932", kind: "企业", status: "同步延迟", source: "EduPlus2", services: 5, grants: 2, usage: "待核对" },
  { id: "willow", name: "青禾教育集团", code: "EDU-0811", kind: "教育集团", status: "正常", source: "EduPlus2", services: 9, grants: 5, usage: "51.2 万" },
];

export const services: ServiceView[] = [
  { id: "llm", name: "对话模型", category: "模型与服务", status: "available", unit: "Token", description: "对话、推理与工具调用" },
  { id: "task", name: "任务模型", category: "模型与服务", status: "available", unit: "Token", description: "后台任务，可回退对话模型" },
  { id: "embedding", name: "向量服务", category: "模型与服务", status: "available", unit: "Token", description: "知识索引与检索向量化" },
  { id: "search", name: "联网搜索", category: "工具服务", status: "limited", unit: "次", description: "外部搜索服务，不配置模型列表" },
  { id: "tts", name: "语音合成", category: "模型与服务", status: "available", unit: "字符", description: "语音输出和音色配置" },
  { id: "stt", name: "语音识别", category: "模型与服务", status: "available", unit: "分钟", description: "音频转文字" },
  { id: "imagegen", name: "图片生成", category: "模型与服务", status: "available", unit: "张", description: "文生图、尺寸与风格" },
  { id: "videogen", name: "视频生成", category: "模型与服务", status: "limited", unit: "次", description: "异步视频生成任务" },
  { id: "ocr", name: "文档 OCR", category: "知识处理", status: "available", unit: "页", description: "解析引擎中的文字识别能力" },
  { id: "rag", name: "文档解析与检索", category: "知识处理", status: "available", unit: "页", description: "解析引擎、知识检索与索引" },
  { id: "video-learning", name: "视频学习接入", category: "工具服务", status: "available", unit: "次", description: "视频来源与字幕获取" },
];

export const resourceGroups = {
  agents: [
    { id: "deep-solve", name: "深度解题", type: "Capability", status: "已发布", dependency: "对话模型 · 任务模型" },
    { id: "deep-research", name: "深度研究", type: "Capability", status: "已发布", dependency: "联网搜索 · 对话模型" },
    { id: "math-animator", name: "数学动画", type: "Capability", status: "受限", dependency: "渲染环境 · 对话模型" },
    { id: "external-agent", name: "外部 Agent 接入", type: "Agent", status: "草稿", dependency: "独立参数与权限" },
  ],
  tools: [
    { id: "web-search", name: "网页搜索工具", type: "Tool", status: "已发布", dependency: "联网搜索" },
    { id: "paper-search", name: "论文检索", type: "Tool", status: "已发布", dependency: "外部搜索" },
    { id: "sandbox", name: "代码执行", type: "Tool", status: "受限", dependency: "沙箱运行资源" },
    { id: "mcp", name: "MCP 集成", type: "集成", status: "草稿", dependency: "连接与授权" },
  ],
  knowledge: [
    { id: "parser", name: "文档解析引擎", type: "基础能力", status: "已发布", dependency: "Docling · MinerU · 本地解析" },
    { id: "retrieval", name: "知识检索", type: "基础能力", status: "已发布", dependency: "LightRAG 受控服务" },
    { id: "storage", name: "附件与存储策略", type: "基础能力", status: "已发布", dependency: "对象存储" },
  ],
  runtime: [
    { id: "workspace", name: "工作空间", type: "运行资源", status: "已发布", dependency: "隔离策略" },
    { id: "scheduler", name: "定时与后台任务", type: "运行资源", status: "已发布", dependency: "任务执行" },
    { id: "network", name: "网络访问策略", type: "高风险配置", status: "受限", dependency: "高级权限" },
  ],
};

export const supply = [
  { id: "s-llm", name: "对话模型资源", service: "对话模型", provider: "演示供应商 A", unit: "Token", acquired: 3000000, committed: 1800000, used: 680000, available: 520000, status: "充足" },
  { id: "s-ocr", name: "文档解析资源", service: "文档 OCR", provider: "演示解析引擎", unit: "页", acquired: 15000, committed: 11500, used: 2900, available: 600, status: "需补充" },
  { id: "s-search", name: "联网搜索资源", service: "联网搜索", provider: "演示供应商 B", unit: "次", acquired: 50000, committed: 31000, used: 18000, available: 1000, status: "需补充" },
];

export type GrantRecord = { id: string; tenant: string; tenantId: string; service: string; serviceId: string; method: string; total: number; used: number | null; remaining: number | null; revoked?: number; unit: string; valid: string; status: string };
export const grants: GrantRecord[] = [
  { id: "q-101", tenant: "星河实验学校", tenantId: "aurora", service: "对话模型", serviceId: "llm", method: "赠送", total: 300000, used: 120000, remaining: 180000, unit: "Token", valid: "2026-12-31", status: "生效中" },
  { id: "q-102", tenant: "星河实验学校", tenantId: "aurora", service: "对话模型", serviceId: "llm", method: "充值", total: 500000, used: 150000, remaining: 350000, unit: "Token", valid: "2027-06-30", status: "生效中" },
  { id: "q-103", tenant: "星河实验学校", tenantId: "aurora", service: "文档 OCR", serviceId: "ocr", method: "赠送", total: 1000, used: 1000, remaining: 0, unit: "页", valid: "2026-12-31", status: "已用尽" },
  { id: "q-104", tenant: "海港职业学院", tenantId: "harbor", service: "联网搜索", serviceId: "search", method: "充值", total: 5000, used: 840, remaining: 4160, unit: "次", valid: "2027-03-31", status: "生效中" },
  { id: "q-105", tenant: "北辰研究院", tenantId: "north", service: "对话模型", serviceId: "llm", method: "赠送", total: 200000, used: null, remaining: null, unit: "Token", valid: "2026-11-30", status: "待核对" },
];

export const calls = [
  { id: "use-7429", time: "09-26 14:32", tenant: "星河实验学校", user: "王同学", service: "对话模型", usage: "50 Token", status: "已核对", grant: "q-101 30 + q-102 20" },
  { id: "use-7428", time: "09-26 13:07", tenant: "海港职业学院", user: "李老师", service: "联网搜索", usage: "1 次", status: "已核对", grant: "q-104" },
  { id: "use-7427", time: "09-26 11:51", tenant: "北辰研究院", user: "陈研究员", service: "对话模型", usage: "待核对", status: "待核对", grant: "待确认" },
  { id: "use-7426", time: "09-25 16:22", tenant: "星河实验学校", user: "周老师", service: "文档 OCR", usage: "12 页", status: "已核对", grant: "q-103" },
];

export const audits = [
  { id: "evt-3201", time: "09-26 14:15", actor: "平台运营 · 林", action: "额度授予", target: "星河实验学校 · 对话模型", status: "已记录" },
  { id: "evt-3200", time: "09-25 10:21", actor: "平台配置管理员 · 许", action: "配置草稿", target: "文档解析服务", status: "未发布" },
  { id: "evt-3199", time: "09-24 17:46", actor: "平台运营 · 林", action: "服务授权", target: "海港职业学院 · 联网搜索", status: "已记录" },
];

export const providerAttributes: Record<string, { heading: string; fields: string[]; note: string }> = {
  llm: { heading: "对话模型配置", fields: ["active_profile_id", "active_model_id", "name", "model", "context_window", "reasoning_effort（按供应商条件）", "capabilities.tools / vision / json_output / reasoning"], note: "推理档位和 API 格式由供应商 descriptor 决定。" },
  task: { heading: "任务模型配置", fields: ["active_profile_id", "active_model_id", "name", "model", "capabilities"], note: "未单独配置时回退对话模型；不复制 LLM 专属控件。" },
  embedding: { heading: "向量服务配置", fields: ["name", "model", "dimension", "send_dimensions", "精确请求地址"], note: "维度能力取决于供应商，endpoint 不追加 /embeddings。" },
  search: { heading: "联网搜索配置", fields: ["name", "provider", "api_key（按供应商条件）", "base_url（按供应商条件）", "api_version（按供应商条件）", "proxy（按供应商条件）"], note: "搜索不使用连接目标或模型列表。" },
  tts: { heading: "语音合成配置", fields: ["name", "model", "voice", "response_format：mp3 / wav / opus / aac / flac / pcm"], note: "自动播放属于个人偏好，不进入 OMS。" },
  stt: { heading: "语音识别配置", fields: ["name", "model"], note: "language 是类型预留，当前编辑器没有维护控件。" },
  imagegen: { heading: "图片生成配置", fields: ["name", "model", "size", "quality", "style"], note: "尺寸、质量、风格可留空，沿用供应商默认。" },
  videogen: { heading: "视频生成配置", fields: ["name", "model", "aspect_ratio", "duration", "resolution"], note: "异步任务型服务，不能套用图片生成字段。" },
  ocr: { heading: "文档 OCR / 解析配置", fields: ["available_engines", "readiness", "解析引擎条件项", "OCR / 表格选项（按引擎）"], note: "现有 DeepTutor 是解析引擎 OCR 能力，不代表独立 OCR Provider。" },
  rag: { heading: "文档解析与检索配置", fields: ["available_engines", "readiness", "解析引擎条件项"], note: "LightRAG 为受控检索服务；学校知识库内容不进入 OMS。" },
  "video-learning": { heading: "视频学习接入配置", fields: ["youtube / invidious", "api_base_url", "public_base_url", "transcript provider"], note: "不等同于视频生成模型。" },
};
