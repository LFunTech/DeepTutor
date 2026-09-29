"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Activity, Blocks, CloudCog, LayoutDashboard, Layers3, LibraryBig, Link2, Network, PackageCheck, ScrollText, ShieldCheck, Sparkles, UsersRound } from "lucide-react";
import { AdminShell, Button, DataTable, DetailGrid, Drawer, MetricStrip, Notice, PageHead, Section, StatePanel, StatusBadge } from "@deeptutor/admin-ui";

type LoadState = "loading" | "ready" | "blocked";
type ApiError = { status: number; detail: string };
type OmsMe = { principal_id?: string; subject?: string; display_name?: string; status?: string };
type OmsPermissions = { actions?: string[]; platform_actions?: string[]; school_actions?: { school_id?: string; actions?: string[] }[]; scopes?: { kind?: string; school_id?: string; school_name?: string }[] };
type OmsSkill = {
  id?: string;
  name?: string;
  status?: string;
  revision_id?: string;
  published_revision_id?: string;
  latest_revision?: number;
  published_revision?: number;
  latest_version?: number;
  published_version?: number;
  sha256?: string;
  description?: string;
};
type OmsModelItem = { id?: string; profile_id?: string; model_id?: string; model?: string; provider?: string; status?: string; source?: string };
type ProviderConnection = { id: string; provider?: string; base_url?: string; api_key?: string };
type StatusLike = string | { code?: string; label?: string; tone?: string };
type OmsResource = { id: string; category?: string; kind?: string; status?: StatusLike; managed?: boolean; display_name?: string; safe_fields?: Record<string, unknown> };
type OmsSummary = { authorized_school_count?: number; resource_count?: number; notices?: { code?: string; label?: string; description?: string }[] };
type OmsSchoolProjection = { school_id?: string; external_binding?: { status?: StatusLike }; lifecycle?: { external_eligibility?: StatusLike; provisioning_status?: StatusLike; recovery_state?: StatusLike } };
type OmsSupplyDefinition = { service_id?: string; unit_code?: string; resource_category?: string; enabled?: boolean; version?: number };
type OmsSupplyLot = { service_id?: string; provider_id?: string; pool_id?: string; unit_code?: string; status?: StatusLike; hard_ceiling?: string | null; committed_unspent?: string; reserved_inflight?: string };
type OmsAuditEvent = { id?: string; action?: string; result?: StatusLike; request_id?: string; reason?: string };
type OmsCostProjection = { costs?: unknown[]; status?: StatusLike; notice?: string };
type OmsUsageAttempt = { attempt_id?: string; operation_id?: string; service_id?: string; unit_code?: string; status?: StatusLike; reserved_units?: string; settled_units?: string };
type OmsJob = { attempt_id?: string; operation_id?: string; service_id?: string; unit_code?: string; status?: StatusLike; reserved_units?: string; settled_units?: string };
type OmsPermissionRole = { id?: string; role_key?: string; version?: number; scope_kind?: string; actions?: string[] };
type OmsPrincipal = { id?: string; principal_id?: string; subject?: string; status?: string; policy_version?: number };
type OmsAssignment = { id?: string; assignment_id?: string; principal_id?: string; role_key?: string; role_version?: number; scope_kind?: string; school_id?: string; status?: string; version?: number };
type OmsApproval = { id?: string; approval_id?: string; operation?: string; target_principal_id?: string; status?: string; expected_target_policy_version?: number; target_role_key?: string; target_role_version?: number; target_action_keys?: string[] };
type OmsPermissionCatalog = { roles?: OmsPermissionRole[]; principals?: OmsPrincipal[]; assignments?: OmsAssignment[] };

const REQUEST_TIMEOUT_MS = 10_000;
const OMS_BASE = "/oms";
const OMS_NAV = [
  { label: "工作台", items: [{ label: "运营概览", href: OMS_BASE, icon: <LayoutDashboard/> }] },
  { label: "学校与权益", items: [{ label: "学校列表", href: `${OMS_BASE}/tenants`, icon: <UsersRound/> }] },
  { label: "资源目录", items: [
    { label: "模型与服务", href: `${OMS_BASE}/services`, icon: <Blocks/> },
    { label: "供应商连接", href: `${OMS_BASE}/connections`, icon: <Link2/> },
    { label: "Agent 与能力", href: `${OMS_BASE}/agents`, icon: <Layers3/> },
    { label: "工具与集成", href: `${OMS_BASE}/tools`, icon: <Network/> },
    { label: "Skills", href: `${OMS_BASE}/skills`, icon: <Sparkles/> },
    { label: "知识基础能力", href: `${OMS_BASE}/knowledge`, icon: <LibraryBig/> },
    { label: "运行资源", href: `${OMS_BASE}/runtime`, icon: <CloudCog/> },
  ] },
  { label: "资源供给", items: [{ label: "服务供给", href: `${OMS_BASE}/supply`, icon: <PackageCheck/> }] },
  { label: "用量与运行", items: [{ label: "用量与运行", href: `${OMS_BASE}/usage`, icon: <Activity/> }] },
  { label: "审计与治理", items: [
    { label: "审计与治理", href: `${OMS_BASE}/audit`, icon: <ScrollText/> },
    { label: "平台人员", href: `${OMS_BASE}/platform-people`, icon: <UsersRound/> },
    { label: "角色与动作", href: `${OMS_BASE}/platform-roles`, icon: <Layers3/> },
    { label: "平台人员学校范围", href: `${OMS_BASE}/school-permissions`, icon: <ShieldCheck/> },
    { label: "授权审计", href: `${OMS_BASE}/authz-audit`, icon: <ScrollText/> },
  ] },
];

type OmsModel = {
  me: OmsMe;
  permissions: OmsPermissions;
  skills: OmsSkill[];
  models: OmsModelItem[];
  modelDraftVersion: number;
  providerConnections: ProviderConnection[];
  providerStatus: string;
  providerSettingsVersion: number;
  resources: OmsResource[];
  summary: OmsSummary;
  schools: OmsSchoolProjection[];
  supplyDefinitions: OmsSupplyDefinition[];
  supplyLots: OmsSupplyLot[];
  auditEvents: OmsAuditEvent[];
  cost: OmsCostProjection;
  usageDetails: OmsUsageAttempt[];
  jobs: OmsJob[];
  inspectedSchoolId: string;
  authzCatalog: OmsPermissionCatalog;
  approvals: OmsApproval[];
};

async function fetchWithTimeout(path: string, init: RequestInit): Promise<Response> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new Error("request timeout"));
    }, REQUEST_TIMEOUT_MS);
  });
  try {
    return await Promise.race([
      fetch(path, { ...init, signal: controller.signal }),
      timeout,
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function refreshOmsSession() {
  const csrf = cookieValue("dt_oms_csrf");
  const response = await fetchWithTimeout("/api/v1/oms/auth/refresh", {
    method: "POST",
    credentials: "include",
    headers: { accept: "application/json", ...(csrf ? { "x-csrf-token": csrf } : {}) },
  });
  if (!response.ok) throw { status: response.status, detail: "oms session refresh failed" } satisfies ApiError;
}

async function readJson<T>(path: string, retryOnUnauthorized = true): Promise<T> {
  const response = await fetchWithTimeout(path, { credentials: "include", headers: { accept: "application/json" } });
  let body: unknown = {};
  try { body = await response.json(); } catch { body = {}; }
  if (response.status === 401 && retryOnUnauthorized) {
    await refreshOmsSession();
    return readJson<T>(path, false);
  }
  if (!response.ok) {
    const detail = typeof body === "object" && body && "detail" in body ? String((body as { detail?: unknown }).detail) : response.statusText;
    throw { status: response.status, detail } satisfies ApiError;
  }
  return body as T;
}

function cookieValue(name: string) {
  if (typeof document === "undefined") return "";
  const prefix = `${name}=`;
  return document.cookie.split(";").map(item => item.trim()).find(item => item.startsWith(prefix))?.slice(prefix.length) ?? "";
}

async function writeJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const csrf = cookieValue("dt_oms_csrf");
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { accept: "application/json", "content-type": "application/json", ...(csrf ? { "x-csrf-token": csrf } : {}) },
    body: JSON.stringify(body),
  });
  let data: unknown = {};
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) {
    const detail = typeof data === "object" && data && "detail" in data ? String((data as { detail?: unknown }).detail) : response.statusText;
    throw { status: response.status, detail } satisfies ApiError;
  }
  return data as T;
}

function blockedMessage(error?: ApiError) {
  const suffix = error ? `（${error.status} ${error.detail}）` : "";
  return `eduplus-platform-admin 授权码登录、账号状态或 ops.* 本地授权未通过${suffix}。`;
}

function toApiError(error: unknown): ApiError {
  if (typeof error === "object" && error !== null && "status" in error && "detail" in error) {
    const status = Number((error as { status?: unknown }).status);
    return {
      status: Number.isFinite(status) ? status : 0,
      detail: String((error as { detail?: unknown }).detail ?? "request failed"),
    };
  }
  return { status: 0, detail: error instanceof Error ? error.message : String(error || "request failed") };
}

function permissionActions(permissions: OmsPermissions) {
  return Array.from(new Set([
    ...(permissions.actions ?? []),
    ...(permissions.platform_actions ?? []),
    ...(permissions.school_actions ?? []).flatMap(item => item.actions ?? []),
  ])).sort();
}

function statusText(status?: StatusLike) {
  if (!status) return "unknown";
  if (typeof status === "string") return status;
  return status.label ?? status.code ?? "unknown";
}

function commandId() {
  return globalThis.crypto?.randomUUID?.() ?? "00000000-0000-4000-8000-000000000001";
}

function farFutureIso() {
  return "9998-01-01T00:00:00Z";
}

function currentOmsPath() {
  if (typeof window === "undefined") return OMS_BASE;
  const pathname = window.location.pathname;
  return pathname === OMS_BASE || pathname.startsWith(`${OMS_BASE}/`) ? pathname : OMS_BASE;
}

function omsRoot(path: string) {
  if (path === OMS_BASE) return "home";
  return path.slice(OMS_BASE.length).split("/").filter(Boolean)[0] ?? "home";
}

function omsSegments(path: string) {
  return path === OMS_BASE ? [] : path.slice(OMS_BASE.length).split("/").filter(Boolean).map(segment => {
    try { return decodeURIComponent(segment); } catch { return segment; }
  });
}

function encodeRoutePart(value: string) {
  return encodeURIComponent(value);
}

export default function OmsFormalApp() {
  const [state, setState] = useState<LoadState>("blocked");
  const [error, setError] = useState<ApiError | undefined>();
  const [model, setModel] = useState<OmsModel | undefined>();
  const [commandMessage, setCommandMessage] = useState("");
  const [bootstrapMessage, setBootstrapMessage] = useState("");
  const [loginHref, setLoginHref] = useState("/api/v1/oms/auth/start");
  const [route, setRoute] = useState(currentOmsPath);

  useEffect(() => {
    const onPopState = () => setRoute(currentOmsPath());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = (href: string) => {
    setRoute(href);
    if (typeof window !== "undefined" && window.location.pathname !== href) {
      window.history.pushState(null, "", href);
    }
  };
  const shell = (children: ReactNode, scope = "正式受控入口") => <AdminShell
    product="OMS"
    subtitle="平台智能体运营后台"
    scope={scope}
    groups={OMS_NAV}
    path={route}
    onNavigate={navigate}
    environmentLabel="正式受控入口"
    footerLabel="正式入口 · 安全 DTO"
    mainLabel="OMS 正式管理入口"
  >
    {children}
  </AdminShell>;

  useEffect(() => {
    if (typeof window !== "undefined") {
      setLoginHref(`/api/v1/oms/auth/start?return_to=${encodeURIComponent(window.location.href)}`);
    }
    let cancelled = false;
    async function load() {
      setState("loading");
      try {
        const me = await readJson<OmsMe>("/api/v1/oms/me");
        const permissions = await readJson<OmsPermissions>("/api/v1/oms/me/permissions");
        const actions = permissionActions(permissions);
        const skillsResult = await readJson<{ skills?: OmsSkill[] }>("/api/v1/oms/skills");
        const authzCatalog = actions.includes("ops.permissions.manage")
          ? await readJson<OmsPermissionCatalog>("/api/v1/oms/permissions")
          : { roles: [], principals: [], assignments: [] };
        const approvals = actions.includes("ops.permissions.manage")
          ? await readJson<{ approvals?: OmsApproval[] }>("/api/v1/oms/approvals")
          : { approvals: [] };
        const modelDraft = actions.includes("ops.providers.read")
          ? await readJson<{ version?: number; models?: OmsModelItem[] }>("/api/v1/oms/models/draft")
          : { version: 0, models: [] };
        const providerSettings = actions.includes("ops.providers.read")
          ? await readJson<{ version?: number; status?: string; settings?: { connections?: Record<string, Omit<ProviderConnection, "id">> } }>("/api/v1/oms/provider-settings")
          : { version: 0, status: "not_loaded", settings: { connections: {} } };
        const resourceStatus = actions.includes("ops.providers.read")
          ? await readJson<{ resources?: OmsResource[] }>("/api/v1/oms/resources/status")
          : { resources: [] };
        const summary = actions.includes("ops.oms.access")
          ? await readJson<OmsSummary>("/api/v1/oms/summary")
          : {};
        const schools = actions.includes("ops.tenants.read")
          ? await readJson<{ tenants?: OmsSchoolProjection[] }>("/api/v1/oms/tenants")
          : { tenants: [] };
        const inspectedSchoolId = schools.tenants?.find(item => item.school_id)?.school_id ?? "";
        const inspectedSchoolPath = inspectedSchoolId ? encodeURIComponent(inspectedSchoolId) : "";
        const usage = actions.includes("ops.usage.read") && inspectedSchoolPath
          ? await readJson<{ details?: OmsUsageAttempt[] }>(`/api/v1/oms/schools/${inspectedSchoolPath}/usage`)
          : { details: [] };
        const jobs = actions.includes("ops.jobs.read") && inspectedSchoolPath
          ? await readJson<{ jobs?: OmsJob[] }>(`/api/v1/oms/schools/${inspectedSchoolPath}/jobs`)
          : { jobs: [] };
        const supply = actions.includes("ops.supply.read")
          ? await readJson<{ service_definitions?: OmsSupplyDefinition[]; supply_lots?: OmsSupplyLot[] }>("/api/v1/oms/supply")
          : { service_definitions: [], supply_lots: [] };
        const audit = actions.includes("ops.audit.read")
          ? await readJson<{ management_events?: OmsAuditEvent[]; oms_events?: OmsAuditEvent[] }>("/api/v1/oms/audit")
          : { management_events: [], oms_events: [] };
        const cost = actions.includes("ops.cost.read")
          ? await readJson<OmsCostProjection>("/api/v1/oms/cost")
          : {};
        const connections = Object.entries(providerSettings.settings?.connections ?? {}).map(([id, value]) => ({ id, ...value }));
        if (!cancelled) {
          setModel({
            me,
            permissions,
            skills: skillsResult.skills ?? [],
            models: modelDraft.models ?? [],
            modelDraftVersion: modelDraft.version ?? 0,
            providerConnections: connections,
            providerStatus: providerSettings.status ?? "unknown",
            providerSettingsVersion: providerSettings.version ?? 0,
            resources: resourceStatus.resources ?? [],
            summary,
            schools: schools.tenants ?? [],
            supplyDefinitions: supply.service_definitions ?? [],
            supplyLots: supply.supply_lots ?? [],
            auditEvents: [...(audit.management_events ?? []), ...(audit.oms_events ?? [])],
            cost,
            usageDetails: usage.details ?? [],
            jobs: jobs.jobs ?? [],
            inspectedSchoolId,
            authzCatalog,
            approvals: approvals.approvals ?? [],
          });
          setState("ready");
        }
      } catch (caught) {
        if (!cancelled) {
          setError(toApiError(caught));
          setState("blocked");
        }
      }
    }
    void load();
    return () => { cancelled = true; };
  }, []);

  if (state === "loading") return shell(<StatePanel state="loading" message="正在读取正式 OMS 安全 DTO。"/>);
  const bootstrapFirstAdmin = async () => {
    setBootstrapMessage("正在提交首位 OMS 管理员初始化请求…");
    try {
      await writeJson("/api/v1/oms/bootstrap/first-admin", {
        command_id: commandId(),
        reason: "OMS 首位平台管理员初始化",
      });
      setBootstrapMessage("首位 OMS 管理员已初始化，正在重新读取正式入口。");
      window.location.reload();
    } catch (caught) {
      const detail = toApiError(caught);
      setBootstrapMessage(`初始化被拒绝：${detail.status} ${detail.detail}`);
    }
  };

  if (state === "blocked") return shell(<>
    <PageHead title="正式入口未开放" description={blockedMessage(error)}/>
    <Notice tone="warn">该页面不会回退到开发原型，不暴露授权、发布、审批或学校开通写按钮。</Notice>
    {bootstrapMessage && <Notice tone={bootstrapMessage.includes("被拒绝") ? "bad" : "info"}>{bootstrapMessage}</Notice>}
    <div className="inline-list">
      <Button onClick={() => { window.location.href = loginHref; }}>使用 eduplus-platform-admin 登录</Button>
      {error?.status === 403 && <Button variant="primary" onClick={() => { void bootstrapFirstAdmin(); }}>激活首位 OMS 管理员</Button>}
    </div>
    <Section title="等待的验收证据"><DetailGrid rows={[
      { label: "OMS Client", value: "eduplus-platform-admin 授权码登录" },
      { label: "身份状态", value: "OIDC issuer/aud/azp/sub 与在线账号 active" },
      { label: "本地授权", value: "DeepTutor Enterprise ops.* 权限事实；零管理员时可由已认证平台主体初始化" },
    ]}/></Section>
  </>);

  const actions = model ? permissionActions(model.permissions) : [];
  const modelRows = (model?.models ?? []).map((item, index) => ({ ...item, id: item.id ?? `${item.profile_id ?? "profile"}:${item.model_id ?? index}` }));
  const providerRows = model?.providerConnections ?? [];
  const resourceRows = model?.resources ?? [];
  const schoolRows = (model?.schools ?? []).map((school, index) => ({ ...school, id: school.school_id ?? `school-${index}` }));
  const supplyDefinitionRows = (model?.supplyDefinitions ?? []).map((definition, index) => ({ ...definition, id: definition.service_id ?? `service-${index}` }));
  const supplyLotRows = (model?.supplyLots ?? []).map((lot, index) => ({ ...lot, id: `${lot.service_id ?? "service"}:${lot.pool_id ?? index}` }));
  const auditRows = (model?.auditEvents ?? []).map((event, index) => ({ ...event, id: event.id ?? event.request_id ?? `audit-${index}` }));
  const usageRows = (model?.usageDetails ?? []).map((attempt, index) => ({ ...attempt, id: attempt.attempt_id ?? `usage-${index}` }));
  const jobRows = (model?.jobs ?? []).map((job, index) => ({ ...job, id: job.attempt_id ?? `job-${index}` }));
  const skillRows = (model?.skills ?? []).map((skill, index) => ({
    ...skill,
    id: skill.id ?? skill.revision_id ?? skill.name ?? `skill-${index}`,
  }));
  const authzPrincipalRows = (model?.authzCatalog?.principals ?? []).map((principal, index) => ({
    ...principal,
    id: principal.id ?? principal.principal_id ?? `principal-${index}`,
  }));
  const authzRoleRows = (model?.authzCatalog?.roles ?? []).map((role, index) => ({
    ...role,
    id: role.id ?? `${role.role_key ?? "role"}:${role.version ?? index}`,
  }));
  const authzAssignmentRows = (model?.authzCatalog?.assignments ?? []).map((assignment, index) => ({
    ...assignment,
    id: assignment.id ?? assignment.assignment_id ?? `assignment-${index}`,
  }));
  const approvalRows = (model?.approvals ?? []).map((approval, index) => ({
    ...approval,
    id: approval.id ?? approval.approval_id ?? `approval-${index}`,
  }));
  const canManageProviders = actions.includes("ops.providers.manage");
  const canReviewSkills = actions.includes("ops.skills.review");
  const canPublishSkills = actions.includes("ops.skills.publish");
  const canGrantSkills = actions.includes("ops.skills.grant");
  const canManagePermissions = actions.includes("ops.permissions.manage");
  const configRole = authzRoleRows.find(row => row.role_key === "platform_config_admin");
  const schoolAuditRole = authzRoleRows.find(row => row.role_key === "platform_auditor");
  const reason = "正式 OMS 受控操作";
  const runCommand = async (label: string, path: string, body: Record<string, unknown>) => {
    setCommandMessage(`${label} 已提交，等待审计回读。`);
    try {
      await writeJson(path, body);
      setCommandMessage(`${label} 已提交；请在审计区按 request_id 回读确认。`);
    } catch (caught) {
      const detail = caught as ApiError;
      setCommandMessage(`${label} 被拒绝：${detail.status} ${detail.detail}`);
    }
  };
  const providerCommand = (path: string, label: string) => runCommand(label, path, {
    expected_version: model?.providerSettingsVersion ?? 0,
    reason,
  });
  const modelCommand = (path: string, label: string) => runCommand(label, path, {
    expected_version: model?.modelDraftVersion ?? 0,
    reason,
  });
  const root = omsRoot(route);
  const segments = omsSegments(route);
  const detailRoot = segments[0] ?? "home";
  const detailId = segments[1];
  const openDetail = (section: string, id: string) => navigate(`${OMS_BASE}/${section}/${encodeRoutePart(id)}`);
  const closeDetail = () => navigate(detailRoot === "home" ? OMS_BASE : `${OMS_BASE}/${detailRoot}`);
  const detailTitle = (() => {
    if (!detailId) return "";
    if (detailRoot === "tenants") return detailId;
    if (detailRoot === "services") return modelRows.find(row => row.id === detailId)?.model_id ?? modelRows.find(row => row.id === detailId)?.model ?? detailId;
    if (detailRoot === "connections") return providerRows.find(row => row.id === detailId)?.provider ?? detailId;
    if (detailRoot === "supply") return supplyDefinitionRows.find(row => row.id === detailId)?.service_id ?? supplyLotRows.find(row => row.id === detailId)?.service_id ?? detailId;
    if (detailRoot === "usage") return usageRows.find(row => row.id === detailId)?.attempt_id ?? jobRows.find(row => row.id === detailId)?.attempt_id ?? detailId;
    if (detailRoot === "audit") return auditRows.find(row => row.id === detailId)?.action ?? detailId;
    if (detailRoot === "skills") return skillRows.find(row => row.id === detailId)?.name ?? detailId;
    return detailId;
  })();
  const detailContent = (() => {
    if (!detailId) return null;
    if (detailRoot === "tenants") {
      const school = schoolRows.find(row => row.id === detailId || row.school_id === detailId);
      if (!school) return <StatePanel state="empty" message="对象不存在或不可访问。"/>;
      return <>
        <PageHead eyebrow="学校投影" title="学校详情" description="只读学校绑定、生命周期和平台 school-scope 范围；不读取学校账号。"/>
        <Notice tone="warn">OMS 不管理学校账号或 TMS tenant.* 角色；这里只展示平台人员 school-scope 可见的学校投影。</Notice>
        <DetailGrid rows={[
          { label: "学校 ID", value: school.school_id ?? school.id },
          { label: "外部绑定", value: statusText(school.external_binding?.status) },
          { label: "生命周期", value: statusText(school.lifecycle?.external_eligibility) },
          { label: "供给状态", value: statusText(school.lifecycle?.provisioning_status) },
          { label: "恢复状态", value: statusText(school.lifecycle?.recovery_state) },
        ]}/>
        <Section title="关联只读入口">
          <div className="inline-list">
            <Button onClick={() => navigate(`${OMS_BASE}/usage`)}>查看该学校用量入口</Button>
            <Button onClick={() => navigate(`${OMS_BASE}/supply`)}>查看供给与额度底座</Button>
            <Button onClick={() => navigate(`${OMS_BASE}/school-permissions`)}>查看平台人员学校范围</Button>
          </div>
        </Section>
      </>;
    }
    if (detailRoot === "services") {
      const row = modelRows.find(item => item.id === detailId);
      return row ? <>
        <PageHead eyebrow="模型与服务" title="模型详情" description="服务端 DTO 的模型草稿投影；凭据与 Secret 不在前端回显。"/>
        <DetailGrid rows={[
          { label: "模型", value: row.model_id ?? row.model ?? row.id },
          { label: "Profile", value: row.profile_id ?? "—" },
          { label: "供应商", value: row.provider ?? "—" },
          { label: "状态", value: row.status ?? "unknown" },
          { label: "来源", value: row.source ?? "正式 DTO" },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "connections") {
      const row = providerRows.find(item => item.id === detailId);
      return row ? <>
        <PageHead eyebrow="Provider" title="供应商连接详情" description="只显示后端脱敏后的连接摘要。"/>
        <DetailGrid rows={[
          { label: "连接", value: row.id },
          { label: "供应商", value: row.provider ?? "—" },
          { label: "Base URL", value: row.base_url ?? "后端默认或未返回" },
          { label: "凭据", value: row.api_key ?? "<redacted>" },
          { label: "状态", value: model?.providerStatus ?? "unknown" },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (["agents", "tools", "knowledge", "runtime"].includes(detailRoot)) {
      const row = resourceRows.find(item => item.id === detailId);
      return row ? <>
        <PageHead eyebrow="资源目录" title="资源详情" description="平台资源状态来自安全 descriptor；策略和运行参数由后续正式 DTO 承接。"/>
        <DetailGrid rows={[
          { label: "资源", value: row.display_name ?? row.id },
          { label: "类别", value: row.category ?? row.kind ?? "unknown" },
          { label: "状态", value: statusText(row.status) },
          { label: "托管", value: row.managed ? "是" : "否" },
        ]}/>
        <Notice>未返回的运行参数不以原型合成数据补齐。</Notice>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "supply") {
      const definition = supplyDefinitionRows.find(item => item.id === detailId);
      const lot = supplyLotRows.find(item => item.id === detailId);
      return definition || lot ? <>
        <PageHead eyebrow="服务供给" title="供给详情" description="服务定义和供给批次只读；TMS 不能修改额度，OMS 写入另走受控 API。"/>
        <DetailGrid rows={[
          { label: "服务", value: definition?.service_id ?? lot?.service_id ?? detailId },
          { label: "单位", value: definition?.unit_code ?? lot?.unit_code ?? "unit" },
          { label: "资源类别", value: definition?.resource_category ?? lot?.provider_id ?? "—" },
          { label: "状态", value: definition ? (definition.enabled ? "enabled" : "disabled") : statusText(lot?.status) },
          { label: "剩余额度", value: lot?.committed_unspent ?? "—" },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "usage") {
      const attempt = usageRows.find(item => item.id === detailId) ?? jobRows.find(item => item.id === detailId);
      return attempt ? <>
        <PageHead eyebrow="用量与运行" title="调用详情" description="逐 attempt 只读投影；未知结果不得在前端按零处理。"/>
        <DetailGrid rows={[
          { label: "Attempt", value: attempt.attempt_id ?? attempt.id },
          { label: "Operation", value: attempt.operation_id ?? "—" },
          { label: "服务", value: attempt.service_id ?? "unknown" },
          { label: "状态", value: statusText(attempt.status) },
          { label: "单位", value: `${attempt.settled_units ?? "0"}/${attempt.reserved_units ?? "0"} ${attempt.unit_code ?? "unit"}` },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "audit" || detailRoot === "authz-audit") {
      const event = auditRows.find(item => item.id === detailId || item.request_id === detailId);
      return event ? <>
        <PageHead eyebrow="审计详情" title="授权与操作审计" description="审计回读只显示脱敏动作、结果与 request ID。"/>
        <DetailGrid rows={[
          { label: "事件", value: event.id ?? event.request_id ?? detailId },
          { label: "动作", value: event.action ?? "—" },
          { label: "结果", value: statusText(event.result) },
          { label: "请求", value: event.request_id ?? "—" },
          { label: "原因", value: event.reason ?? "—" },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    if (detailRoot === "skills") {
      const row = skillRows.find(item => item.id === detailId || item.name === detailId);
      return row ? <>
        <PageHead eyebrow="Skill" title="Skill 详情" description="Skill 正式维护只显示包状态、发布版本和脱敏校验信息。"/>
        <DetailGrid rows={[
          { label: "Skill", value: row.name ?? row.id },
          { label: "状态", value: row.status ?? "unknown" },
          { label: "最新版本", value: String(row.latest_version ?? row.latest_revision ?? 0) },
          { label: "已发布版本", value: String(row.published_version ?? row.published_revision ?? 0) },
          { label: "校验摘要", value: row.sha256 ? `${row.sha256.slice(0, 12)}…` : "未返回" },
        ]}/>
      </> : <StatePanel state="empty" message="对象不存在或不可访问。"/>;
    }
    return null;
  })();

  return shell(<>
    <PageHead title="平台智能体运营后台" description="正式入口使用已验签 OMS 会话与 DeepTutor 本地 ops.* 授权；不接学校账号或 TMS 首管开通。"/>
    <Notice tone="info">当前页面只渲染后端安全 DTO；Secret、对象存储 key、成本明细和学校私有正文不会在这里出现。</Notice>
    {commandMessage && <Notice tone={commandMessage.includes("被拒绝") ? "bad" : "info"}>{commandMessage}</Notice>}
    <MetricStrip items={[
      { label: "可见学校", value: String(model?.summary.authorized_school_count ?? schoolRows.length), note: "显式 school-scope" },
      { label: "资源", value: String(model?.summary.resource_count ?? resourceRows.length), note: "安全状态投影" },
      { label: "待审批", value: String(approvalRows.filter(item => item.status === "pending" || item.status === "approved").length), note: "本地授权事实" },
      { label: "Skill", value: String(skillRows.length), note: "首个 Agent 接入" },
    ]}/>
    {root === "home" && <>
      <Section title="当前平台身份"><DetailGrid rows={[
        { label: "主体", value: model?.me.display_name ?? model?.me.subject ?? model?.me.principal_id ?? "已认证平台主体" },
        { label: "状态", value: <StatusBadge tone="good">{model?.me.status ?? "active"}</StatusBadge> },
        { label: "动作", value: actions.length ? actions.join("、") : "无本地授权" },
      ]}/></Section>
      <Section title="OMS 总览" subtitle="只聚合当前平台主体本地 ops.* 范围内可见的学校与资源。">
        <DetailGrid rows={[
          { label: "可见学校", value: String(model?.summary.authorized_school_count ?? 0) },
          { label: "资源数量", value: String(model?.summary.resource_count ?? resourceRows.length) },
          { label: "治理提示", value: model?.summary.notices?.map(item => item.label ?? item.code).filter(Boolean).join("、") || "—" },
        ]}/>
      </Section>
    </>}
    {(root === "home" || root === "services" || root === "agents" || root === "tools" || root === "knowledge" || root === "runtime") && <Section title="平台资源状态" subtitle="安全状态投影只展示 descriptor 与脱敏字段。">
      <DataTable rows={resourceRows} searchLabel="搜索资源" columns={[
        { key: "name", label: "资源", render: row => row.display_name ?? row.id },
        { key: "category", label: "类别", render: row => row.category ?? row.kind ?? "unknown" },
        { key: "status", label: "状态", render: row => statusText(row.status) },
      ]} onOpen={row => openDetail(root === "home" ? "runtime" : root, row.id)} openLabel={row => `查看 ${row.display_name ?? row.id} 详情`}/>
    </Section>}
    {(root === "home" || root === "tenants") && <Section title="学校范围" subtitle="仅列出当前 OMS 主体已获本产品 school-scope 授权的学校。">
      <DataTable rows={schoolRows} searchLabel="搜索学校" columns={[
        { key: "school", label: "学校", render: row => row.school_id ?? row.id },
        { key: "binding", label: "绑定", render: row => statusText(row.external_binding?.status) },
        { key: "lifecycle", label: "生命周期", render: row => statusText(row.lifecycle?.external_eligibility) },
      ]} onOpen={row => openDetail("tenants", row.school_id ?? row.id)} openLabel={row => `查看 ${row.school_id ?? row.id} 详情`}/>
    </Section>}
    {canManagePermissions && (root === "home" || root === "platform-people" || root === "platform-roles" || root === "school-permissions" || root === "authz-audit") && <Section title="平台授权治理" subtitle="平台人员、角色、学校操作范围和审批均接入正式 OMS 本地授权 API；候选只来自已登记平台主体。">
      <div className="section-grid">
        <DataTable rows={authzPrincipalRows} searchLabel="搜索平台人员" columns={[
          { key: "subject", label: "平台主体", render: row => row.subject ?? row.principal_id ?? row.id },
          { key: "status", label: "状态", render: row => row.status ?? "unknown" },
          { key: "version", label: "Policy", render: row => String(row.policy_version ?? 0) },
        ]} rowActions={row => {
          const principalId = row.principal_id ?? row.id ?? "";
          const targetPolicyVersion = row.policy_version ?? 1;
          return [
            ...(row.status === "pending" && configRole?.role_key && configRole.version ? [{
              label: "提交平台授权审批",
              onClick: () => runCommand("提交平台授权审批", "/api/v1/oms/approvals", {
                operation: "platform_grant",
                target_principal_id: principalId,
                expected_target_policy_version: targetPolicyVersion,
                expires_at: "9998-12-31T00:00:00Z",
                idempotency_key: commandId(),
                reason,
                external_qualification_ref: "oms-formal-ui",
                external_qualification_version: "ui-v1",
                target_role_key: configRole.role_key,
                target_role_version: configRole.version,
                confirmed_role_version: configRole.version,
                target_expires_at: farFutureIso(),
              }),
            }] : []),
            ...(row.status === "active" && schoolAuditRole?.role_key && schoolAuditRole.version && model?.inspectedSchoolId ? [{
              label: "授予学校只读范围",
              onClick: () => runCommand("授予学校只读范围", `/api/v1/oms/principals/${encodeURIComponent(principalId)}/roles`, {
                role_key: schoolAuditRole.role_key,
                role_version: schoolAuditRole.version,
                target_school_id: model.inspectedSchoolId,
                expected_target_policy_version: targetPolicyVersion,
                expires_at: farFutureIso(),
                command_id: commandId(),
                reason,
              }),
            }] : []),
            ...(row.status === "active" ? [{
              label: "停用平台主体",
              onClick: () => runCommand("停用平台主体", `/api/v1/oms/principals/${encodeURIComponent(principalId)}/disable`, {
                expected_target_policy_version: targetPolicyVersion,
                reason,
              }),
            }] : []),
          ];
        }}/>
        <DataTable rows={authzRoleRows} searchLabel="搜索角色" columns={[
          { key: "role", label: "角色", render: row => row.role_key ?? row.id },
          { key: "scope", label: "范围", render: row => `${row.scope_kind ?? "unknown"} · v${row.version ?? 0}` },
          { key: "actions", label: "动作", render: row => row.actions?.join("、") || "—" },
        ]}/>
      </div>
      <div className="section-grid">
        <DataTable rows={authzAssignmentRows} searchLabel="搜索授权范围" columns={[
          { key: "role", label: "角色", render: row => row.role_key ?? row.id },
          { key: "scope", label: "范围", render: row => row.school_id ? `学校 ${row.school_id}` : row.scope_kind ?? "platform" },
          { key: "status", label: "状态", render: row => `${row.status ?? "unknown"} · v${row.version ?? 0}` },
        ]} rowActions={row => {
          const assignmentId = row.assignment_id ?? row.id ?? "";
          const principal = authzPrincipalRows.find(item => item.principal_id === row.principal_id || item.id === row.principal_id);
          return row.status === "active" ? [{
            label: "撤销 OMS 授权",
            onClick: () => runCommand("撤销 OMS 授权", `/api/v1/oms/assignments/${encodeURIComponent(assignmentId)}/revoke`, {
              target_school_id: row.school_id || null,
              expected_assignment_version: row.version ?? 1,
              expected_target_policy_version: principal?.policy_version ?? 1,
              command_id: commandId(),
              reason,
            }),
          }] : [];
        }}/>
        <DataTable rows={approvalRows} searchLabel="搜索审批" columns={[
          { key: "operation", label: "审批", render: row => row.operation ?? row.id },
          { key: "target", label: "目标", render: row => row.target_role_key ? `${row.target_role_key} v${row.target_role_version ?? 0}` : (row.target_action_keys?.join("、") || row.target_principal_id || "—") },
          { key: "status", label: "状态", render: row => row.status ?? "unknown" },
        ]} rowActions={row => {
          const approvalId = row.approval_id ?? row.id ?? "";
          const targetPolicyVersion = row.expected_target_policy_version ?? 1;
          return [
            ...(row.status === "pending" ? [{
              label: "批准授权审批",
              onClick: () => runCommand("批准授权审批", `/api/v1/oms/approvals/${encodeURIComponent(approvalId)}/review`, {
                decision: "approved",
                expected_target_policy_version: targetPolicyVersion,
                reason,
              }),
            }] : []),
            ...(row.status === "approved" ? [{
              label: "应用授权审批",
              onClick: () => runCommand("应用授权审批", `/api/v1/oms/approvals/${encodeURIComponent(approvalId)}/apply`, {
                expected_target_policy_version: targetPolicyVersion,
                command_id: commandId(),
                reason,
              }),
            }] : []),
          ];
        }}/>
      </div>
    </Section>}
    {(root === "home" || root === "services" || root === "connections") && <Section title="模型与 Provider" subtitle="草稿、测试、发布和回滚均调用正式 OMS 写 API；Secret 仅允许后端脱敏值。" action={canManageProviders ? <div className="table-actions" aria-label="模型与 Provider 操作">
      <button type="button" className="table-link" onClick={() => modelCommand("/api/v1/oms/models/test", "测试模型草稿")}>测试模型草稿</button>
      <button type="button" className="table-link" onClick={() => modelCommand("/api/v1/oms/models/publish", "发布模型草稿")}>发布模型草稿</button>
      <button type="button" className="table-link" onClick={() => modelCommand("/api/v1/oms/models/rollback", "回滚模型草稿")}>回滚模型草稿</button>
      <button type="button" className="table-link" onClick={() => providerCommand("/api/v1/oms/provider-settings/test", "测试 Provider 草稿")}>测试 Provider 草稿</button>
      <button type="button" className="table-link" onClick={() => providerCommand("/api/v1/oms/provider-settings/publish", "发布 Provider 草稿")}>发布 Provider 草稿</button>
      <button type="button" className="table-link" onClick={() => providerCommand("/api/v1/oms/provider-settings/rollback", "回滚 Provider 草稿")}>回滚 Provider 草稿</button>
    </div> : undefined}>
      <div className="section-grid">
        <DataTable rows={modelRows} searchLabel="搜索模型" columns={[
          { key: "model", label: "模型", render: row => row.model_id ?? row.model ?? row.id },
          { key: "profile", label: "Profile", render: row => row.profile_id ?? "—" },
          { key: "provider", label: "供应商", render: row => row.provider ? `${row.provider} · ${row.status ?? "unknown"}` : "—" },
        ]} onOpen={row => openDetail("services", row.id)} openLabel={row => `查看 ${row.model_id ?? row.model ?? row.id} 详情`}/>
        <DataTable rows={providerRows} searchLabel="搜索 Provider" columns={[
          { key: "id", label: "连接", render: row => row.id },
          { key: "provider", label: "供应商", render: row => row.provider ? `${row.provider} · ${model?.providerStatus ?? "unknown"}` : "—" },
          { key: "secret", label: "凭据", render: row => row.api_key ?? "<redacted>" },
        ]} emptyText={`Provider 设置：${model?.providerStatus ?? "未读取"}`} onOpen={row => openDetail("connections", row.id)} openLabel={row => `查看 ${row.provider ?? row.id} 详情`}/>
      </div>
    </Section>}
    {(root === "home" || root === "supply") && <Section title="供给与额度底座" subtitle="只读服务定义与供给批次，不执行补充、授权或额度调整。">
      <div className="section-grid">
        <DataTable rows={supplyDefinitionRows} searchLabel="搜索服务定义" columns={[
          { key: "service", label: "服务", render: row => row.service_id ?? row.id },
          { key: "unit", label: "单位", render: row => row.unit_code ?? "unit" },
          { key: "enabled", label: "状态", render: row => row.enabled ? "enabled" : "disabled" },
        ]} onOpen={row => openDetail("supply", row.id)} openLabel={row => `查看 ${row.service_id ?? row.id} 详情`}/>
        <DataTable rows={supplyLotRows} searchLabel="搜索供给批次" columns={[
          { key: "provider", label: "Provider", render: row => row.provider_id ?? "—" },
          { key: "pool", label: "Pool", render: row => row.pool_id ?? "—" },
          { key: "status", label: "状态", render: row => `${statusText(row.status)} · ${row.committed_unspent ?? "0"} ${row.unit_code ?? "unit"}` },
        ]} onOpen={row => openDetail("supply", row.id)} openLabel={row => `查看 ${row.service_id ?? row.id} 供给详情`}/>
      </div>
    </Section>}
    {(root === "home" || root === "usage") && <Section title="学校用量与任务" subtitle={`只读首个已授权学校 ${model?.inspectedSchoolId || "（无）"} 的 attempt 与待核对任务；不展示学校私有正文。`}>
      <div className="section-grid">
        <DataTable rows={usageRows} searchLabel="搜索用量 attempt" columns={[
          { key: "attempt", label: "Attempt", render: row => row.attempt_id ?? row.id },
          { key: "service", label: "服务", render: row => row.service_id ?? "unknown" },
          { key: "status", label: "状态", render: row => statusText(row.status) },
          { key: "units", label: "单位", render: row => `${row.settled_units ?? "0"}/${row.reserved_units ?? "0"} ${row.unit_code ?? "unit"}` },
        ]} onOpen={row => openDetail("usage", row.id)} openLabel={row => `查看 ${row.attempt_id ?? row.id} 详情`}/>
        <DataTable rows={jobRows} searchLabel="搜索待核对任务" columns={[
          { key: "attempt", label: "Attempt", render: row => row.attempt_id ?? row.id },
          { key: "service", label: "服务", render: row => row.service_id ?? "unknown" },
          { key: "status", label: "状态", render: row => statusText(row.status) },
          { key: "units", label: "单位", render: row => `${row.settled_units ?? "0"}/${row.reserved_units ?? "0"} ${row.unit_code ?? "unit"}` },
        ]} onOpen={row => openDetail("usage", row.id)} openLabel={row => `查看 ${row.attempt_id ?? row.id} 任务详情`}/>
      </div>
    </Section>}
    {(root === "home" || root === "audit" || root === "authz-audit") && <Section title="审计与成本" subtitle="成本为 OMS-only 只读状态；不得从租户额度或用量推导。">
      {model?.cost.notice && <Notice tone="info">{model.cost.notice}</Notice>}
      <div className="section-grid">
        <DataTable rows={auditRows} searchLabel="搜索审计" columns={[
          { key: "action", label: "动作", render: row => row.action ?? row.id },
          { key: "result", label: "结果", render: row => statusText(row.result) },
          { key: "request", label: "请求", render: row => row.request_id ?? "—" },
        ]} onOpen={row => openDetail("audit", row.id)} openLabel={row => `查看 ${row.action ?? row.id} 审计详情`}/>
        <DetailGrid rows={[
          { label: "成本状态", value: statusText(model?.cost.status) },
          { label: "成本记录", value: String(model?.cost.costs?.length ?? 0) },
        ]}/>
      </div>
    </Section>}
    {(root === "home" || root === "skills") && <Section title="Skill 清单" subtitle="用于首个 Agent 接入前的 OMS 维护视图；review、publish、grant 均按 ops.skills.* 权限显隐。">
      <DataTable rows={skillRows} searchLabel="搜索 Skill" columns={[
        { key: "name", label: "Skill", render: row => row.name ?? row.id ?? "unknown" },
        { key: "status", label: "状态", render: row => row.status ?? "unknown" },
        { key: "revision", label: "版本", render: row => `r${row.published_version ?? row.published_revision ?? row.latest_version ?? row.latest_revision ?? 0}` },
        { key: "desc", label: "说明", render: row => row.description ?? "—" },
      ]} rowActions={(canReviewSkills || canPublishSkills || canGrantSkills) ? row => {
        const name = row.name ?? row.id ?? "";
        const revisionId = row.revision_id ?? row.published_revision_id ?? row.id ?? "";
        const sha = row.sha256 ?? "";
        const latestVersion = row.latest_version ?? row.latest_revision ?? row.published_version ?? row.published_revision ?? 0;
        return [
          ...(canReviewSkills && revisionId && /^[0-9a-f]{64}$/.test(sha) ? [{
            label: "批准 Skill",
            onClick: () => runCommand("批准 Skill", `/api/v1/oms/skills/revisions/${encodeURIComponent(revisionId)}/review`, {
              expected_sha256: sha,
              approved: true,
              reason,
              code_review_evidence: "oms-formal-ui",
            }),
          }] : []),
          ...(canPublishSkills && revisionId ? [{
            label: "发布 Skill",
            onClick: () => runCommand("发布 Skill", `/api/v1/oms/skills/revisions/${encodeURIComponent(revisionId)}/publish`, {
              expected_version: latestVersion,
              reason,
            }),
          }] : []),
          ...(canGrantSkills && name && model?.inspectedSchoolId ? [{
            label: "授权首个学校 Skill",
            onClick: () => runCommand("授权首个学校 Skill", `/api/v1/oms/skills/${encodeURIComponent(name)}/schools/${encodeURIComponent(model.inspectedSchoolId)}/grant`, {
              expected_grant_version: 0,
              expires_at: "9998-01-01T00:00:00Z",
              reason,
            }),
          }] : []),
        ];
      } : undefined} onOpen={!(canReviewSkills || canPublishSkills || canGrantSkills) ? row => openDetail("skills", row.id) : undefined} openLabel={row => `查看 ${row.name ?? row.id} 详情`}/>
    </Section>}
    {detailId && detailContent && <Drawer title={`详情 · ${detailTitle || detailId}`} onClose={closeDetail}>
      {detailContent}
    </Drawer>}
  </>);
}
