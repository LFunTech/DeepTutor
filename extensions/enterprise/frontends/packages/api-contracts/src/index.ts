export const CONTRACT_VERSION = "0.1.0";

export type ServiceStatus = "available" | "limited" | "unavailable";
export interface ServiceView {
  id: string;
  name: string;
  category: string;
  status: ServiceStatus;
  unit: string;
  description: string;
}

// 共用组件只接收白名单投影，不将平台供给、成本或凭据藏在租户组件属性中。
export function projectService(source: ServiceView & Record<string, unknown>): ServiceView {
  const { id, name, category, status, unit, description } = source;
  return { id, name, category, status, unit, description };
}

export type DisplayState = "ready" | "loading" | "empty" | "error" | "forbidden" | "pending";

export type SkillOwner = "global" | "tenant";
export type SkillSource = "builtin" | "created" | "hub" | "upload";
export interface SkillView {
  id: string;
  name: string;
  description: string;
  owner: SkillOwner;
  source: SkillSource;
  version: string;
  tags: string[];
  status: string;
}

// 白名单投影：正文、内部审查材料和跨租户授权绝不进入共用列表。
export function projectSkill<T extends SkillView>(source: T): SkillView {
  const { id, name, description, owner, source: origin, version, tags, status } = source;
  return { id, name, description, owner, source: origin, version, tags: [...tags], status };
}

export function resolveSkillForTenant<T extends { id: string; name: string; owner: SkillOwner; published: boolean; authorized: boolean; ready: boolean; tenantId?: string }>(rows: T[], name: string, tenantId: string): T | undefined {
  const candidates = rows.filter(row => row.name === name && row.published && row.authorized);
  return candidates.find(row => row.owner === "tenant" && row.tenantId === tenantId)
    ?? candidates.find(row => row.owner === "global");
}
