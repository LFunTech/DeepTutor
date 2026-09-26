import type { ServiceView } from "@deeptutor/api-contracts";

// 仅含当前演示学校可见数据。这里没有平台 Secret、供给采购、供应商成本或其他学校。
export const tenant = { id: "aurora", name: "演示学校（合成数据）", source: "EduPlus2", status: "正常", synced: "2026-09-26 14:28" };

export const members = [
  { id: "m-01", name: "林老师", role: "学校管理员", department: "教务处", status: "正常", source: "EduPlus2" },
  { id: "m-02", name: "周老师", role: "资源管理员", department: "数学教研组", status: "正常", source: "EduPlus2" },
  { id: "m-03", name: "王同学", role: "普通成员", department: "高二（3）班", status: "正常", source: "EduPlus2" },
  { id: "m-04", name: "陈同学", role: "普通成员", department: "高一（2）班", status: "待同步", source: "EduPlus2" },
];

export const apps = [
  { id: "app-01", name: "校园学习助手", owner: "教务处", status: "运行中", services: "对话模型、文档 OCR", last: "今天 14:22" },
  { id: "app-02", name: "数学教研工作台", owner: "数学教研组", status: "运行中", services: "深度解题、联网搜索", last: "今天 11:40" },
  { id: "app-03", name: "资料归档助手", owner: "图书馆", status: "待接入", services: "文档解析", last: "尚无调用" },
  { id: "app-04", name: "外部课程接入", owner: "教务处", status: "归口待核对", services: "未授权", last: "尚无调用" },
];

export const services: ServiceView[] = [
  { id: "llm", name: "对话模型", category: "模型与服务", status: "available", unit: "Token", description: "对话与学习辅导" },
  { id: "task", name: "任务模型", category: "模型与服务", status: "available", unit: "Token", description: "应用后台任务" },
  { id: "search", name: "联网搜索", category: "工具服务", status: "available", unit: "次", description: "公开资料检索" },
  { id: "ocr", name: "文档 OCR", category: "知识处理", status: "limited", unit: "页", description: "资料文字识别与解析" },
  { id: "rag", name: "文档解析与检索", category: "知识处理", status: "available", unit: "页", description: "知识库文档处理" },
  { id: "deep-solve", name: "深度解题", category: "Agent 与能力", status: "available", unit: "次", description: "分步分析与解题" },
  { id: "web-search", name: "网页搜索工具", category: "工具服务", status: "available", unit: "次", description: "Agent 工具调用" },
];

export const grants = [
  { id: "q-101", serviceId: "llm", service: "对话模型", method: "赠送", total: "300,000", used: "120,000", remaining: "180,000", unit: "Token", valid: "2026-12-31", status: "生效中" },
  { id: "q-102", serviceId: "llm", service: "对话模型", method: "充值", total: "500,000", used: "150,000", remaining: "350,000", unit: "Token", valid: "2027-06-30", status: "生效中" },
  { id: "q-103", serviceId: "ocr", service: "文档 OCR", method: "赠送", total: "1,000", used: "1,000", remaining: "0", unit: "页", valid: "2026-12-31", status: "已用尽" },
  { id: "q-104", serviceId: "search", service: "联网搜索", method: "充值", total: "5,000", used: "840", remaining: "4,160", unit: "次", valid: "2027-03-31", status: "生效中" },
];

export const knowledge = [
  { id: "kb-01", name: "高二数学课程资料", owner: "数学教研组", files: "126 份", index: "已就绪", updated: "今天 10:21" },
  { id: "kb-02", name: "校园管理手册", owner: "教务处", files: "42 份", index: "处理中", updated: "昨天 16:42" },
  { id: "kb-03", name: "历史试题归档", owner: "图书馆", files: "213 份", index: "索引失败", updated: "09-24 09:16" },
];

export const documents = [
  { id: "doc-101", kbId: "kb-01", name: "函数与导数教学讲义.pdf", owner: "数学教研组", status: "已就绪", updated: "今天 10:21" },
  { id: "doc-102", kbId: "kb-01", name: "高二期中复习提纲.docx", owner: "数学教研组", status: "已就绪", updated: "昨天 17:09" },
  { id: "doc-201", kbId: "kb-02", name: "学生手册.pdf", owner: "教务处", status: "处理中", updated: "昨天 16:42" },
  { id: "doc-301", kbId: "kb-03", name: "历史试题扫描件.pdf", owner: "图书馆", status: "索引失败", updated: "09-24 09:16" },
];

export const processingTasks = [
  { id: "job-001", kbId: "kb-01", name: "索引更新", status: "已完成", updated: "今天 10:21" },
  { id: "job-002", kbId: "kb-02", name: "文档解析", status: "处理中", updated: "昨天 16:42" },
  { id: "job-003", kbId: "kb-03", name: "扫描件索引", status: "失败", updated: "09-24 09:16" },
];

export const calls = [
  { id: "use-7429", time: "今天 14:32", member: "王同学", app: "校园学习助手", service: "对话模型", usage: "50 Token", status: "已核对", grant: "赠送 30 + 充值 20" },
  { id: "use-7426", time: "昨天 16:22", member: "周老师", app: "数学教研工作台", service: "文档 OCR", usage: "12 页", status: "已核对", grant: "q-103" },
  { id: "use-7422", time: "09-24 11:15", member: "林老师", app: "校园学习助手", service: "对话模型", usage: "待核对", status: "待核对", grant: "待确认" },
];

export const events = [
  { id: "evt-221", time: "今天 12:14", actor: "林老师", action: "应用授权", target: "校园学习助手", status: "成功" },
  { id: "evt-220", time: "昨天 15:08", actor: "周老师", action: "知识库更新", target: "高二数学课程资料", status: "成功" },
];
