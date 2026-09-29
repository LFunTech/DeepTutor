"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Activity, AppWindow, BookOpenCheck, ClipboardList, LayoutDashboard, ScrollText, ShieldCheck, Sparkles, UsersRound } from "lucide-react";
import { AdminShell, DataTable, DetailGrid, Drawer, MetricStrip, Notice, PageHead, Section, StatePanel, StatusBadge } from "@deeptutor/admin-ui";

type LoadState = "loading" | "ready" | "blocked";
type ApiError = { status: number; detail: string };
type TmsPermissions = { school_id?: string; school_code?: string; actions?: string[]; scopes?: { kind?: string; school_id?: string }[] };
type TmsBootstrap = { status?: string; actor_candidate?: { subject?: string; event_id?: string } | null };
type DirectoryState = { status?: string; reason_code?: string; message?: string; users?: { id: string; display_name?: string }[] };
type TmsRoleAssignment = { assignment_id?: string; role_key?: string; role_version?: number; status?: string; version?: number };
type TmsMember = { id?: string; principal_id?: string; display_name?: string; subject?: string; status?: string; policy_version?: number; assignments?: TmsRoleAssignment[]; roles?: TmsRoleAssignment[] };
type TmsApproval = { id?: string; approval_id?: string; status?: string; operation?: string; expected_target_policy_version?: number };
type TmsAudit = { id: string; action?: string; result?: string; reason_code?: string };
type TmsSkill = { id: string; name?: string; status?: string; publication_revision?: number };
type TmsQuotaGrant = { grant_id?: string; service_id?: string; unit_code?: string; quantity?: string; status?: string };
type TmsUsage = { attempt_id?: string; service_id?: string; unit_code?: string; status?: string; settled_units?: string; reserved_units?: string };
type TmsServiceAccessGrant = { grant_id?: string; service_id?: string; subject_kind?: string; subject_id?: string; status?: string; sync_status?: string };

function tmsBase(schoolCode: string) {
  return `/tms/${encodeURIComponent(schoolCode)}`;
}

function tmsNavigation(base: string) {
  return [
    { label: "工作台", items: [{ label: "学校概览", href: base, icon: <LayoutDashboard/> }] },
    { label: "成员与权限", items: [
      { label: "成员列表", href: `${base}/members`, icon: <UsersRound/> },
      { label: "学校角色", href: `${base}/roles`, icon: <ShieldCheck/> },
      { label: "访问关系", href: `${base}/access-grants`, icon: <AppWindow/> },
      { label: "授权记录", href: `${base}/authz-records`, icon: <ScrollText/> },
    ] },
    { label: "应用与接入", items: [{ label: "应用列表", href: `${base}/apps`, icon: <AppWindow/> }] },
    { label: "服务与配额", items: [
      { label: "可用服务", href: `${base}/services`, icon: <ClipboardList/> },
      { label: "配额清单", href: `${base}/quotas`, icon: <ShieldCheck/> },
      { label: "Skills", href: `${base}/skills`, icon: <Sparkles/> },
    ] },
    { label: "知识与内容", items: [{ label: "知识库列表", href: `${base}/knowledge`, icon: <BookOpenCheck/> }] },
    { label: "用量与记录", items: [
      { label: "调用用量", href: `${base}/usage`, icon: <Activity/> },
      { label: "管理事件", href: `${base}/events`, icon: <ScrollText/> },
    ] },
  ];
}

type TmsModel = {
  permissions: TmsPermissions;
  bootstrap: TmsBootstrap;
  directory: DirectoryState;
  members: TmsMember[];
  approvals: TmsApproval[];
  audits: TmsAudit[];
  skills: TmsSkill[];
  quotaGrants: TmsQuotaGrant[];
  usage: TmsUsage[];
  serviceAccess: TmsServiceAccessGrant[];
};

async function readJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: "include", headers: { accept: "application/json" } });
  let body: unknown = {};
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) {
    const detail = typeof body === "object" && body && "detail" in body ? String((body as { detail?: unknown }).detail) : response.statusText;
    throw { status: response.status, detail } satisfies ApiError;
  }
  return body as T;
}


async function writeJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  let payload: unknown = {};
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) {
    const detail = typeof payload === "object" && payload && "detail" in payload ? String((payload as { detail?: unknown }).detail) : response.statusText;
    throw { status: response.status, detail } satisfies ApiError;
  }
  return payload as T;
}

function newCommandId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "00000000-0000-4000-8000-" + Math.random().toString(16).slice(2, 14).padEnd(12, "0");
}

function memberId(row: TmsMember) { return row.principal_id ?? row.id ?? ""; }
function approvalId(row: TmsApproval) { return row.approval_id ?? row.id ?? ""; }
function memberRoles(row: TmsMember) { return row.roles ?? row.assignments ?? []; }
function oneYearLater() {
  const date = new Date();
  date.setUTCFullYear(date.getUTCFullYear() + 1);
  return date.toISOString();
}

function blockedMessage(error?: ApiError) {
  const suffix = error ? `（${error.status} ${error.detail}）` : "";
  return `当前学校登录、Webhook 学校绑定或 tenant.* 本地授权未通过${suffix}。`;
}

function directoryStatusLabel(status?: string) {
  switch (status) {
    case "not_enabled": return "目录未启用";
    case "no_permission": return "目录无权";
    case "empty_scope": return "目录空范围";
    case "empty": return "目录空结果";
    case "failed": return "目录外部失败";
    case "enabled": return "目录已启用";
    default: return "目录状态未知";
  }
}

function currentTmsPath(base: string) {
  if (typeof window === "undefined") return base;
  const pathname = window.location.pathname;
  return pathname === base || pathname.startsWith(`${base}/`) ? pathname : base;
}

function tmsRoot(route: string, base: string) {
  if (route === base) return "home";
  return route.slice(base.length).split("/").filter(Boolean)[0] ?? "home";
}

function tmsSegments(route: string, base: string) {
  if (route === base) return [];
  return route.slice(base.length).split("/").filter(Boolean).map(segment => {
    try { return decodeURIComponent(segment); } catch { return segment; }
  });
}

function encodeRoutePart(value: string) {
  return encodeURIComponent(value);
}

export default function TmsFormalApp({ schoolCode }: { schoolCode: string }) {
  const base = tmsBase(schoolCode);
  const [route, setRoute] = useState(() => currentTmsPath(base));
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<ApiError | undefined>();
  const [model, setModel] = useState<TmsModel | undefined>();
  const [message, setMessage] = useState("");

  useEffect(() => {
    const onPopState = () => setRoute(currentTmsPath(base));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [base]);

  const navigate = (href: string) => {
    setRoute(href);
    if (typeof window !== "undefined" && window.location.pathname !== href) {
      window.history.pushState(null, "", href);
    }
  };
  const shell = (children: ReactNode) => <AdminShell
    product="TMS"
    subtitle="学校智能体管理后台"
    scope={`${schoolCode} · 正式受控入口`}
    groups={tmsNavigation(base)}
    path={route}
    onNavigate={navigate}
    environmentLabel="正式受控入口"
    footerLabel="正式入口 · 安全 DTO"
    mainLabel="TMS 正式管理入口"
  >
    {children}
  </AdminShell>;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setState("loading");
      try {
        const permissions = await readJson<TmsPermissions>("/api/v1/tms/me/permissions");
        if (!permissions.school_code) {
          throw { status: 403, detail: "后端权限摘要未返回可信学校码" } satisfies ApiError;
        }
        if (permissions.school_code !== schoolCode) {
          throw { status: 403, detail: "学校码与当前登录学校不一致" } satisfies ApiError;
        }
        const bootstrap = await readJson<TmsBootstrap>("/api/v1/tms/school-bootstrap/status");
        const directory = await readJson<DirectoryState>("/api/v1/tms/directory/users");
        const permissionActions = permissions.actions ?? [];
        const quotaResult = permissionActions.includes("tenant.quotas.read") || permissionActions.includes("tenant.usage.read")
          ? await readJson<{ grants?: TmsQuotaGrant[]; usage?: TmsUsage[]; usage_details?: TmsUsage[] }>("/api/v1/tms/quotas")
          : { grants: [], usage: [], usage_details: [] };
        const serviceAccessResult = permissionActions.includes("tenant.access.manage")
          ? await readJson<{ service_access_grants?: TmsServiceAccessGrant[] }>("/api/v1/tms/service-access")
          : { service_access_grants: [] };
        const membersResult = await readJson<{ members?: TmsMember[] }>("/api/v1/tms/members");
        const approvalsResult = await readJson<{ approvals?: TmsApproval[] }>("/api/v1/tms/approvals");
        const auditsResult = await readJson<{ events?: TmsAudit[] }>("/api/v1/tms/authz-audit");
        const skillsResult = await readJson<{ skills?: TmsSkill[] }>("/api/v1/tms/skills");
        if (!cancelled) {
          setModel({
            permissions,
            bootstrap,
            directory,
            members: membersResult.members ?? [],
            approvals: approvalsResult.approvals ?? [],
            audits: auditsResult.events ?? [],
            skills: skillsResult.skills ?? [],
            quotaGrants: quotaResult.grants ?? [],
            usage: quotaResult.usage_details?.length ? quotaResult.usage_details : quotaResult.usage ?? [],
            serviceAccess: serviceAccessResult.service_access_grants ?? [],
          });
          setState("ready");
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught as ApiError);
          setState("blocked");
        }
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [schoolCode]);

  const patchMember = (principalId: string, updater: (member: TmsMember) => TmsMember) => {
    setModel(current => current ? { ...current, members: current.members.map(member => memberId(member) === principalId ? updater(member) : member) } : current);
  };
  const patchApproval = (targetApprovalId: string, updater: (approval: TmsApproval) => TmsApproval) => {
    setModel(current => current ? { ...current, approvals: current.approvals.map(approval => approvalId(approval) === targetApprovalId ? updater(approval) : approval) } : current);
  };
  const grantAuditor = async (member: TmsMember) => {
    const principalId = memberId(member);
    if (!principalId) return;
    try {
      const result = await writeJson<{ assignment_id?: string }>(`/api/v1/tms/members/${principalId}/roles`, {
        role_key: "school_auditor",
        role_version: 1,
        expected_target_policy_version: member.policy_version ?? 1,
        expires_at: oneYearLater(),
        command_id: newCommandId(),
        reason: "正式 TMS UI 低风险只读角色授予",
      });
      patchMember(principalId, current => ({ ...current, roles: [...memberRoles(current), { assignment_id: result.assignment_id, role_key: "school_auditor", role_version: 1, status: "active", version: 1 }] }));
      setMessage("已提交低风险学校只读角色授予。");
    } catch (caught) {
      const error = caught as ApiError;
      setMessage(`授予失败：${error.status} ${error.detail}`);
    }
  };
  const revokeAssignment = async (member: TmsMember, assignment: TmsRoleAssignment) => {
    const principalId = memberId(member);
    if (!principalId || !assignment.assignment_id) return;
    try {
      await writeJson(`/api/v1/tms/assignments/${assignment.assignment_id}/revoke`, {
        expected_assignment_version: assignment.version ?? 1,
        expected_target_policy_version: member.policy_version ?? 1,
        command_id: newCommandId(),
        reason: "正式 TMS UI 撤销当前学校角色",
      });
      patchMember(principalId, current => ({ ...current, roles: memberRoles(current).map(role => role.assignment_id === assignment.assignment_id ? { ...role, status: "revoked" } : role) }));
      setMessage(`已提交撤销 ${assignment.role_key ?? "角色"}。`);
    } catch (caught) {
      const error = caught as ApiError;
      setMessage(`撤销失败：${error.status} ${error.detail}`);
    }
  };
  const applyApproval = async (approval: TmsApproval) => {
    const id = approvalId(approval);
    if (!id) return;
    try {
      await writeJson(`/api/v1/tms/approvals/${id}/apply`, {
        expected_target_policy_version: approval.expected_target_policy_version ?? 1,
        command_id: newCommandId(),
        reason: "正式 TMS UI 应用已批准审批",
      });
      patchApproval(id, current => ({ ...current, status: "applied" }));
      setMessage("已提交审批 apply。");
    } catch (caught) {
      const error = caught as ApiError;
      setMessage(`审批应用失败：${error.status} ${error.detail}`);
    }
  };

  if (state === "loading") return shell(<StatePanel state="loading" message="正在读取当前学校 TMS 安全 DTO。"/>);
  if (state === "blocked") return shell(<>
    <PageHead title="学校入口未开放" description={blockedMessage(error)}/>
    <Notice tone="warn">该页面不会使用开发原型或合成目录兜底，也不会渲染授予、撤销、审批、新增等写按钮。</Notice>
    <Section title="当前学校"><DetailGrid rows={[
      { label: "学校 code", value: schoolCode },
      { label: "身份来源", value: "已验签 TMS bearer + 本地学校绑定" },
      { label: "授权来源", value: "DeepTutor Enterprise tenant.* 权限事实" },
    ]}/></Section>
  </>);

  const actions = model?.permissions.actions ?? [];
  const canManage = actions.includes("tenant.permissions.manage");
  const directoryMessage = model?.directory.message ?? model?.directory.reason_code ?? "目录状态未返回";
  const directoryRows = (model?.directory.users ?? []).map((user, index) => ({ ...user, id: user.id ?? `directory-${index}` }));
  const memberRows = (model?.members ?? []).map(member => ({ ...member, id: memberId(member) }));
  const approvalRows = (model?.approvals ?? []).map(approval => ({ ...approval, id: approvalId(approval) }));
  const quotaRows = (model?.quotaGrants ?? []).map((grant, index) => ({ ...grant, id: grant.grant_id ?? `quota-${index}` }));
  const usageRows = (model?.usage ?? []).map((usage, index) => ({ ...usage, id: usage.attempt_id ?? `usage-${index}` }));
  const serviceAccessRows = (model?.serviceAccess ?? []).map((grant, index) => ({ ...grant, id: grant.grant_id ?? `access-${index}` }));
  const root = tmsRoot(route, base);
  const segments = tmsSegments(route, base);
  const detailRoot = segments[0] ?? "home";
  const detailId = segments[1];
  const openDetail = (section: string, id: string) => navigate(`${base}/${section}/${encodeRoutePart(id)}`);
  const closeDetail = () => navigate(detailRoot === "home" ? base : `${base}/${detailRoot}`);
  const detailTitle = (() => {
    if (!detailId) return "";
    if (detailRoot === "members") {
      const member = memberRows.find(row => row.id === detailId);
      return member?.display_name ?? member?.subject ?? detailId;
    }
    if (detailRoot === "quotas") return quotaRows.find(row => row.id === detailId)?.service_id ?? detailId;
    if (detailRoot === "usage") return usageRows.find(row => row.id === detailId)?.attempt_id ?? detailId;
    if (detailRoot === "services" || detailRoot === "access-grants" || detailRoot === "apps") return serviceAccessRows.find(row => row.id === detailId)?.service_id ?? detailId;
    if (detailRoot === "skills") return model?.skills.find(row => row.id === detailId)?.name ?? detailId;
    if (detailRoot === "events" || detailRoot === "authz-records") return model?.audits.find(row => row.id === detailId)?.action ?? detailId;
    return detailId;
  })();
  const detailContent = (() => {
    if (!detailId) return null;
    if (detailRoot === "members") {
      const member = memberRows.find(row => row.id === detailId);
      if (!member) return <StatePanel state="empty" message="对象不存在或不可访问。"/>;
      const roles = memberRoles(member);
      return <>
        <PageHead eyebrow="成员与权限" title="成员详情" description="正式 TMS 只显示本校已登记主体和本产品授权关系；外部目录记录不直接赋权。"/>
        <DetailGrid rows={[
          { label: "主体", value: member.display_name ?? member.subject ?? member.id },
          { label: "Principal", value: member.principal_id ?? member.id },
          { label: "状态", value: member.status ?? "unknown" },
          { label: "Policy", value: String(member.policy_version ?? 0) },
          { label: "当前学校", value: model?.permissions.school_id ?? schoolCode },
          { label: "本地角色", value: roles.map(item => `${item.role_key ?? "unknown"} · ${item.status ?? "unknown"} · v${item.version ?? 0}`).join("、") || "—" },
        ]}/>
        <Section title="访问关系">
          <Notice>成员、应用、服务和共享资源应从同一授权事实回读；未返回的关系不使用原型合成数据补齐。</Notice>
        </Section>
      </>;
    }
    if (detailRoot === "quotas") {
      const quota = quotaRows.find(row => row.id === detailId);
      return quota ? <>
        <PageHead eyebrow="配额清单 · 只读" title="配额详情" description="额度由 OMS 授予；TMS 只读当前学校额度与消耗。"/>
        <DetailGrid rows={[
          { label: "服务", value: quota.service_id ?? "unknown" },
          { label: "额度", value: `${quota.quantity ?? "0"} ${quota.unit_code ?? "unit"}` },
          { label: "状态", value: quota.status ?? "unknown" },
          { label: "所属学校", value: model?.permissions.school_id ?? schoolCode },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "usage") {
      const usage = usageRows.find(row => row.id === detailId);
      return usage ? <>
        <PageHead eyebrow="调用用量" title="用量详情" description="当前学校逐 attempt 用量；未知用量不得按零处理。"/>
        <DetailGrid rows={[
          { label: "Attempt", value: usage.attempt_id ?? usage.id },
          { label: "服务", value: usage.service_id ?? "unknown" },
          { label: "状态", value: usage.status ?? "unknown" },
          { label: "已结算", value: `${usage.settled_units ?? "0"} ${usage.unit_code ?? "unit"}` },
          { label: "预留", value: `${usage.reserved_units ?? "0"} ${usage.unit_code ?? "unit"}` },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "services" || detailRoot === "access-grants" || detailRoot === "apps") {
      const grant = serviceAccessRows.find(row => row.id === detailId);
      return grant ? <>
        <PageHead eyebrow="服务访问" title="访问关系详情" description="只读成员/应用/服务主体访问资格；不包含额度数量。"/>
        <DetailGrid rows={[
          { label: "服务", value: grant.service_id ?? "unknown" },
          { label: "主体", value: `${grant.subject_kind ?? "subject"} · ${grant.subject_id ?? "—"}` },
          { label: "状态", value: grant.status ?? "unknown" },
          { label: "同步状态", value: grant.sync_status ?? "—" },
          { label: "所属学校", value: model?.permissions.school_id ?? schoolCode },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "skills") {
      const skill = model?.skills.find(row => row.id === detailId);
      return skill ? <>
        <PageHead eyebrow="Skill" title="Skill 授权详情" description="TMS 只读当前学校可见 Skill；发布、审查和学校授权归 OMS。"/>
        <DetailGrid rows={[
          { label: "Skill", value: skill.name ?? skill.id },
          { label: "状态", value: skill.status ?? "unknown" },
          { label: "发布版本", value: skill.publication_revision ? `r${skill.publication_revision}` : "—" },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "events" || detailRoot === "authz-records") {
      const event = model?.audits.find(row => row.id === detailId);
      return event ? <>
        <PageHead eyebrow="管理事件" title="授权记录详情" description="只读当前学校本地授权事件，不回显 token、Secret 或私有正文。"/>
        <DetailGrid rows={[
          { label: "事件", value: event.id },
          { label: "动作", value: event.action ?? "—" },
          { label: "结果", value: event.result ?? event.reason_code ?? "unknown" },
          { label: "所属学校", value: model?.permissions.school_id ?? schoolCode },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    return null;
  })();
  return shell(<>
    <PageHead title="学校智能体管理后台" description="正式入口固定当前已订阅学校，不从 URL、header 或 body 切校。"/>
    <Notice tone="info">学校 code：<strong>{schoolCode}</strong>；当前页面只消费 `/api/v1/tms/*` 安全 DTO，不显示 OMS Secret、成本或跨学校数据。</Notice>
    {message && <Notice tone={message.includes("失败") ? "bad" : "info"}>{message}</Notice>}
    <MetricStrip items={[
      { label: "本地成员", value: String(memberRows.length), note: "仅本校已登记主体" },
      { label: "待处理审批", value: String(approvalRows.filter(item => item.status === "approved" || item.status === "pending").length), note: "当前学校" },
      { label: "可用服务访问", value: String(serviceAccessRows.length), note: "只读资格" },
      { label: "Skill", value: String(model?.skills.length ?? 0), note: "按 tenant.* 可见" },
    ]}/>
    {root === "home" && <Section title="当前学校权限"><DetailGrid rows={[
      { label: "学校", value: model?.permissions.school_id ?? schoolCode },
      { label: "开通状态", value: <StatusBadge tone={model?.bootstrap.status === "active" ? "good" : "warn"}>{model?.bootstrap.status ?? "unknown"}</StatusBadge> },
      { label: "可用动作", value: actions.length ? actions.join("、") : "无本地授权" },
    ]}/></Section>}
    {(root === "home" || root === "members") && <Section title="学校目录" subtitle="仅展示后端当前学校目录 DTO；目录不可用时不回退合成用户。">
      <DetailGrid rows={[
        { label: "目录状态", value: <StatusBadge tone={model?.directory.status === "enabled" ? "good" : model?.directory.status === "failed" ? "bad" : "warn"}>{directoryStatusLabel(model?.directory.status)}</StatusBadge> },
        { label: "说明", value: directoryMessage },
      ]}/>
      <DataTable rows={directoryRows} searchLabel="搜索学校目录" columns={[
        { key: "name", label: "目录用户", render: row => row.display_name ?? row.id },
        { key: "id", label: "外部 ID", render: row => row.id },
      ]}/>
    </Section>}
    {(root === "home" || root === "members") && <Section title="成员列表" subtitle="DeepTutor 本地当前学校授权成员；不等同外部目录同步。">
      <DataTable rows={memberRows} searchLabel="搜索成员" columns={[
        { key: "name", label: "成员", render: row => row.display_name ?? row.subject ?? row.id },
        { key: "status", label: "状态", render: row => row.status ?? "unknown" },
        { key: "roles", label: "本地角色", render: row => memberRoles(row).filter(item => item.status !== "revoked").map(item => item.role_key).filter(Boolean).join("、") || "—" },
      ]} rowActions={row => {
        const details = [{ label: "成员资料", onClick: () => openDetail("members", row.id) }];
        if (!canManage || row.status !== "active") return details;
        const activeRoles = memberRoles(row).filter(item => item.status === "active");
        const revokable = activeRoles.find(item => item.assignment_id && item.role_key !== "school_admin");
        const canGrantAuditor = !activeRoles.some(item => item.role_key === "school_auditor");
        return [
          ...details,
          ...(canGrantAuditor ? [{ label: "授予只读角色", onClick: () => void grantAuditor(row) }] : []),
          ...(revokable ? [{ label: `撤销 ${revokable.role_key ?? "角色"}`, onClick: () => void revokeAssignment(row, revokable) }] : []),
        ];
      }}/>
    </Section>}
    {(root === "home" || root === "quotas" || root === "usage") && <Section title="额度与用量" subtitle="只读当前学校额度和逐 attempt 用量，不展示 OMS 成本、供给来源或 Secret。">
      <div className="section-grid">
        <DataTable rows={quotaRows} searchLabel="搜索额度" columns={[
          { key: "service", label: "服务", render: row => row.service_id ?? "unknown" },
          { key: "quantity", label: "额度", render: row => `${row.quantity ?? "0"} ${row.unit_code ?? "unit"}` },
          { key: "status", label: "状态", render: row => row.status ?? "unknown" },
        ]} onOpen={row => openDetail("quotas", row.id)} openLabel={row => `查看 ${row.service_id ?? row.id} 配额详情`}/>
        <DataTable rows={usageRows} searchLabel="搜索用量" columns={[
          { key: "service", label: "服务", render: row => row.service_id ?? "unknown" },
          { key: "settled", label: "已结算", render: row => `${row.settled_units ?? "0"} ${row.unit_code ?? "unit"}` },
          { key: "status", label: "状态", render: row => row.status ?? "unknown" },
        ]} onOpen={row => openDetail("usage", row.id)} openLabel={row => `查看 ${row.attempt_id ?? row.id} 用量详情`}/>
      </div>
    </Section>}
    {(root === "home" || root === "apps" || root === "services" || root === "access-grants") && <Section title="服务访问" subtitle="只读成员/应用/服务主体访问资格；不包含额度数量。">
      <DataTable rows={serviceAccessRows} searchLabel="搜索服务访问" columns={[
        { key: "service", label: "服务", render: row => row.service_id ?? "unknown" },
        { key: "subject", label: "主体", render: row => row.subject_id ?? "—" },
        { key: "status", label: "状态", render: row => `${row.status ?? "unknown"}${row.sync_status ? ` · ${row.sync_status}` : ""}` },
      ]} onOpen={row => openDetail(root === "apps" ? "apps" : root === "home" ? "services" : root, row.id)} openLabel={row => `查看 ${row.service_id ?? row.id} 访问详情`}/>
    </Section>}
    {(root === "home" || root === "skills") && <Section title="Skill 授权"><DataTable rows={model?.skills ?? []} searchLabel="搜索 Skill" columns={[
      { key: "name", label: "Skill", render: row => row.name ?? row.id },
      { key: "status", label: "状态", render: row => row.status ?? "unknown" },
      { key: "revision", label: "版本", render: row => row.publication_revision ? `r${row.publication_revision}` : "—" },
    ]} onOpen={row => openDetail("skills", row.id)} openLabel={row => `查看 ${row.name ?? row.id} 详情`}/></Section>}
    {root === "knowledge" && <Section title="知识与内容" subtitle="正式知识库 DTO 未完成前只显示失败关闭状态。">
      <StatePanel state="empty" message="知识库正式 DTO 尚未启用；当前不会回退到原型合成数据，也不会读取私有正文。"/>
    </Section>}
    {root === "apps" && serviceAccessRows.length === 0 && <Section title="应用与接入" subtitle="应用正式 DTO 未启用前只显示安全空态。">
      <StatePanel state="empty" message="应用列表正式 DTO 尚未启用；当前不会回退到原型合成应用。"/>
    </Section>}
    {root === "roles" && <Section title="学校角色" subtitle="角色目录由后端安全 DTO 提供；未返回时保持只读治理空态。">
      <Notice>角色授予仍必须走当前学校 `tenant.permissions.manage` 与审批/委托上界；前端不会自填 ops.* 或跨校动作。</Notice>
    </Section>}
    {(root === "home" || root === "roles" || root === "access-grants" || root === "authz-records" || root === "events") && <Section title={root === "events" ? "管理事件" : "审批与审计"} subtitle="当前学校本地授权事实" >
      <div aria-label="TMS 审批与审计" className="section-grid">
        <DataTable rows={approvalRows} searchLabel="搜索审批" columns={[
          { key: "op", label: "审批", render: row => row.operation ?? row.id },
          { key: "status", label: "状态", render: row => row.status ?? "unknown" },
        ]} rowActions={row => canManage && row.status === "approved" ? [{ label: "应用审批", onClick: () => void applyApproval(row) }] : []}/>
        <DataTable rows={model?.audits ?? []} searchLabel="搜索审计" columns={[
          { key: "action", label: "动作", render: row => row.action ?? row.id },
          { key: "result", label: "结果", render: row => row.result ?? row.reason_code ?? "unknown" },
        ]} onOpen={row => openDetail("events", row.id)} openLabel={row => `查看 ${row.action ?? row.id} 事件详情`}/>
      </div>
    </Section>}
    {detailId && detailContent && <Drawer title={`详情 · ${detailTitle || detailId}`} onClose={closeDetail}>
      {detailContent}
    </Drawer>}
  </>);
}
