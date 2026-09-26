import { inspectSkillPackage } from "@deeptutor/service-components";

// 浏览器预检只为操作员即时反馈；正式接入时服务端仍需独立验证与安全审查。
export async function validateSkillFile(file: File): Promise<string | null> {
  try {
    await inspectSkillPackage(file);
    return null;
  } catch (error) {
    return error instanceof Error ? error.message : "无法读取 Skill ZIP 包。";
  }
}
