import type { SkillView } from "@deeptutor/api-contracts";
import type { SkillPackageRevision } from "@deeptutor/service-components";

export type TenantSkill = SkillView & {
  tenantId?: string;
  requires: string;
  readiness: string;
  review: string;
  body: string;
  reference: string;
  archive?: File;
  packageFiles?: string[];
  license?: string;
  compatibility?: string;
  allowedTools?: string;
  origin?: string;
  history?: SkillPackageRevision[];
  revision?: number;
  frontmatter?: Record<string, unknown>;
  published: boolean;
  authorized: boolean;
  ready: boolean;
};

// 本学校安全投影；未授权 builtin (如 xlsx) 不进入 TMS 数据或浏览器状态。
export const initialTenantSkills: TenantSkill[] = [
  { id: "global:pdf", name: "pdf", description: "PDF 文档处理", owner: "global", source: "builtin", version: "演示包版本 1", tags: ["内置"], status: "已授权 · 可用", requires: "受控运行环境", readiness: "已就绪（演示）", review: "", body: "已授权 PDF Skill 内容（演示）", reference: "已授权 PDF 参考文件（演示）", published: true, authorized: true, ready: true },
  { id: "global:docx", name: "docx", description: "Word 文档处理", owner: "global", source: "builtin", version: "演示包版本 1", tags: ["内置"], status: "已授权 · 暂不可用", requires: "shell sandbox", readiness: "运行条件不足", review: "", body: "暂不可读取", reference: "暂不可读取", published: true, authorized: true, ready: false },
  { id: "tenant:aurora:lesson-notes", tenantId: "aurora", name: "lesson-notes", description: "校内备课记录", owner: "tenant", source: "created", version: "1.0 演示", tags: ["教学"], status: "本学校可用", requires: "对话模型", readiness: "已就绪（演示）", review: "学校管理员已审核", body: "校内备课内容（演示）", reference: "无参考文件", published: true, authorized: true, ready: true },
];
