import type { SkillView } from "@deeptutor/api-contracts";
import type { SkillPackageRevision } from "@deeptutor/service-components";

export type PlatformSkill = SkillView & {
  requires: string;
  readiness: string;
  digest: string;
  review: string;
  grants: string[];
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
};

// 配对原型案例；这些版本、摘要和授权记录均为显式演示数据，不表示线上注册或同步。
export const initialPlatformSkills: PlatformSkill[] = [
  ...[
    ["docx", "Word 文档处理", "shell sandbox 未就绪", ["aurora"]],
    ["pdf", "PDF 文档处理", "shell sandbox 已就绪", ["aurora"]],
    ["pptx", "演示文稿处理", "shell sandbox 待核对", []],
    ["xlsx", "电子表格处理", "shell sandbox 待核对", []],
    ["skill-creator", "Skill 编写辅助", "能力依赖待核对", []],
  ].map(([name, description, readiness, grants]) => ({
    id: `global:${name}`, name: name as string, description: description as string,
    owner: "global" as const, source: "builtin" as const,
    version: "演示包版本 1", tags: ["内置"], status: "已发布",
    requires: "受控运行环境", readiness: readiness as string,
    digest: "原型摘要 · 接入后需核对真实内容", review: "打包条目只读 · 版本变化须复核",
    grants: grants as string[], body: "打包内容不可在线修改", reference: "仅在获授权且运行条件满足时读取",
  })),
  { id: "global:lesson-planner", name: "lesson-planner", description: "教学计划辅助", owner: "global", source: "created", version: "0.2 演示", tags: ["教学"], status: "已发布", requires: "对话模型", readiness: "待执行者核对", digest: "演示摘要 · 非真实哈希", review: "演示审查已通过", grants: ["harbor"], body: "教学计划辅助内容（演示）", reference: "无参考文件" },
];

// OMS 后授权案例：目标学校已有同名 tenant Skill，授权时需提示优先级。
export const tenantSkillNames: Record<string, string[]> = { aurora: ["pdf"] };
