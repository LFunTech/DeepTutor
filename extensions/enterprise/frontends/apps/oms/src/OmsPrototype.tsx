"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Activity, Blocks, CloudCog, LayoutDashboard, Layers3, LibraryBig, Link2, Network, PackageCheck, ScrollText, ShieldCheck, UsersRound, Sparkles } from "lucide-react";
import type { DisplayState, ServiceView } from "@deeptutor/api-contracts";
import { AdminShell, Button, ConfirmModal, FormModal, DataTable, DetailGrid, Drawer, MetricStrip, Notice, PageHead, Section, StatePanel, StatusBadge, Tabs, useLocationSearch, useSessionFilter } from "@deeptutor/admin-ui";
import { OcrServiceList, ServiceDetail, ServiceList } from "@deeptutor/service-components";
import ServiceConfigForm from "./ServiceConfigForm";
import OmsSkills from "./OmsSkills";
import OmsSupplyCatalog from "./OmsSupplyCatalog";
import OmsResourceCreate from "./OmsResourceCreate";
import type { ResourceDraft, ResourceKind } from "./OmsResourceCreate";
import OmsModelCreate from "./OmsModelCreate";
import DemoCredentialForm from "./DemoCredentialForm";
import OmsAuthorization, { initialOmsAuth, type OmsAuthState } from "./OmsAuthorization";
import type { ModelDraft, ProfileDraft } from "./OmsModelCreate";
import { connectionOptions, connectionService, connectionTarget, providerOption } from "./providerDescriptors";
import { audits, calls, grants as initialGrants, providerAttributes, resourceGroups, resourceServiceDependencies, schoolServiceAccess, services, supply as initialSupply, tenants } from "./fixtures";
import type { GrantRecord } from "./fixtures";

const base = "/oms/prototype";
const authRoots = new Set(["platform-people", "platform-roles", "school-permissions", "authz-audit"]);
const profileServiceIds = new Set(["llm", "task", "embedding", "tts", "stt", "imagegen", "videogen", "search"]);
const modelServiceIds = new Set(["llm", "task", "embedding", "tts", "stt", "imagegen", "videogen"]);
const connectableServiceIds = new Set(connectionOptions().flatMap(target => Object.keys(target.services)));
const nav = [
  { label: "工作台", items: [{ label: "运营概览", href: base, icon: <LayoutDashboard/> }] },
  { label: "学校与权益", items: [{ label: "学校列表", href: `${base}/tenants`, icon: <UsersRound/> }] },
  { label: "资源目录", items: [
    { label: "模型与服务", href: `${base}/services`, icon: <Blocks/> },
    { label: "供应商连接", href: `${base}/connections`, icon: <Link2/> },
    { label: "Agent 与能力", href: `${base}/agents`, icon: <Layers3/> },
    { label: "工具与集成", href: `${base}/tools`, icon: <Network/> },
    { label: "Skills", href: `${base}/skills`, icon: <Sparkles/> },
    { label: "知识基础能力", href: `${base}/knowledge`, icon: <LibraryBig/> },
    { label: "运行资源", href: `${base}/runtime`, icon: <CloudCog/> },
  ] },
  { label: "资源供给", items: [
    { label: "服务供给", href: `${base}/supply`, icon: <PackageCheck/> },
  ] },
  { label: "用量与运行", items: [
    { label: "用量与运行", href: `${base}/usage`, icon: <Activity/> },
  ] },
  { label: "审计与治理", items: [
    { label: "审计与治理", href: `${base}/audit`, icon: <ScrollText/> },
    { label: "平台人员", href: `${base}/platform-people`, icon: <UsersRound/> },
    { label: "角色与动作", href: `${base}/platform-roles`, icon: <Layers3/> },
    { label: "平台人员学校范围", href: `${base}/school-permissions`, icon: <ShieldCheck/> },
    { label: "授权审计", href: `${base}/authz-audit`, icon: <ScrollText/> },
  ] },
];

const initialConnections = [
  { id: "c-model", name: "演示模型连接", serviceIds: ["llm", "embedding"], scope: "llm / embedding", status: "已配置", provider: "dashscope", note: "凭据引用已关联（示意）", baseUrl: "" },
  { id: "c-voice", name: "演示语音连接", serviceIds: ["tts", "stt"], scope: "tts / stt", status: "草稿", provider: "dashscope", note: "尚未发布", baseUrl: "" },
  { id: "c-media", name: "演示图像连接", serviceIds: ["imagegen", "videogen"], scope: "imagegen / videogen", status: "已配置", provider: "dashscope", note: "凭据引用已关联（示意）", baseUrl: "" },
];
const connectionLabels: Record<string, string> = { llm: "对话模型", embedding: "向量服务", tts: "语音合成", stt: "语音识别", imagegen: "图片生成", videogen: "视频生成" };

function badge(value: string) {
  const tone = value.includes("不足") || value.includes("失败") || value.includes("用尽") ? "bad" : value.includes("待") || value.includes("受限") || value.includes("需") || value.includes("同步") || value.includes("草稿") ? "warn" : "good";
  return <StatusBadge tone={tone}>{value}</StatusBadge>;
}
function title(value: string, sub?: string) { return <><span className="cell-title">{value}</span>{sub && <span className="cell-sub">{sub}</span>}</>; }
function localToday() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`; }
function defaultExpiry() { const date = new Date(); date.setMonth(date.getMonth() + 3); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`; }

export default function OmsPrototype() {
  const pathname = usePathname();
  const locationSearch = useLocationSearch();
  const [route, setRoute] = useState(pathname);
  const [returnRoute, setReturnRoute] = useState<string | null>(null);
  useEffect(() => { const onPopState = () => { setReturnRoute(null); setRoute(window.location.pathname); }; window.addEventListener("popstate", onPopState); return () => window.removeEventListener("popstate", onPopState); }, []);
  const inOmsScope = route === base || route.startsWith(`${base}/`);
  const segments = inOmsScope ? route.slice(base.length).split("/").filter(Boolean) : ["invalid"];
  const root = segments[0] || "home";
  const go = (path: string, returning = false) => { const target = new URL(path, window.location.href); const targetSegments = target.pathname.startsWith(`${base}/`) ? target.pathname.slice(base.length + 1).split("/").filter(Boolean) : []; if (!returning) { if (targetSegments.length > 1 && (segments.length === 0 || segments.length > 1 && (root !== targetSegments[0] || (root === "supply" && ["plans", "batches"].includes(segments[1]) && ["plans", "batches"].includes(targetSegments[1]) && segments[1] !== targetSegments[1])))) setReturnRoute(route); else if (targetSegments.length <= 1) setReturnRoute(null); } setFormOpen(""); setMessage(""); setRoute(target.pathname); if (window.location.pathname + window.location.search !== target.pathname + target.search) window.history.pushState(null, "", target.pathname + target.search); };
  const [role, setRole] = useState("admin");
  const [authState, setAuthState] = useState<OmsAuthState>(initialOmsAuth);
  const [scenario, setScenario] = useState("normal");
  const [grants, setGrants] = useState<GrantRecord[]>(initialGrants);
  const [supply, setSupply] = useState(initialSupply);
  const [supplyHistory] = useState(initialSupply.map(row => ({ id: `origin-${row.id}`, supplyId: row.id, amount: row.acquired, source: "初始演示供给", time: "演示初始数据" })));
  const [connections, setConnections] = useState(initialConnections);
  const [serviceRows, setServiceRows] = useState(services);
  const [serviceDrafts, setServiceDrafts] = useState<Record<string, ResourceDraft>>({});
  const [profiles, setProfiles] = useState<ProfileDraft[]>([]);
  const [models, setModels] = useState<ModelDraft[]>([]);
  const [resourceRows, setResourceRows] = useState(resourceGroups);
  const [resourcePolicies, setResourcePolicies] = useState<Record<string, { note: string; scope: string }>>({});
  const [configDrafts, setConfigDrafts] = useState<Record<string, Record<string, string>>>({});
  const [releaseRequests, setReleaseRequests] = useState<{ id: string; serviceId: string; name: string; status: string }[]>([]);
  const [credentialDemos, setCredentialDemos] = useState<Record<string, boolean>>({});
  const [credentialTarget, setCredentialTarget] = useState<{ key: string; scope: string; label: "API Key" | "API Token" } | null>(null);
  const [formOpen, setFormOpen] = useState("");
  const [confirm, setConfirm] = useState<{ title: string; description: string; action: () => void } | null>(null);
  const [method, setMethod] = useState("赠送");
  const [quantity, setQuantity] = useState("1000");
  const [validDate, setValidDate] = useState(defaultExpiry);
  const [policyNote, setPolicyNote] = useState("");
  const [policyScope, setPolicyScope] = useState("获授权学校");
  const [connectionName, setConnectionName] = useState("");
  const [connectionProvider, setConnectionProvider] = useState("");
  const [connectionServiceIds, setConnectionServiceIds] = useState<string[]>(["llm"]);
  const [editingConnectionId, setEditingConnectionId] = useState<string | null>(null);
  const [connectionUrl, setConnectionUrl] = useState("");
  const [message, setMessage] = useState("");
  const [catalogTab, setCatalogTab] = useState("全部服务");
  const [quotaFilter, setQuotaFilter] = useSessionFilter("oms:tenant-quota-method", "all");
  const [authorized, setAuthorized] = useState<Record<string, string[]>>({});
  const [revokedAuth, setRevokedAuth] = useState<Record<string, string[]>>({});
  const [authService, setAuthService] = useState("ocr");
  const [grantService, setGrantService] = useState("llm");
  const canWrite = role === "operator" || role === "admin";
  const canConfigure = role === "admin";
  const credentialStatus = (key: string) => credentialDemos[key] ? "已录入演示值 · 未验证" : "未配置演示凭据";
  const openCredential = (key: string, scope: string, label: "API Key" | "API Token") => { setCredentialTarget({ key, scope, label }); setFormOpen("credential"); };
  const viewState: DisplayState = scenario === "loading" ? "loading" : scenario === "empty" ? "empty" : scenario === "error" ? "error" : scenario === "forbidden" || role === "limited" ? "forbidden" : "ready";

  const list = <T extends { id: string }>(rows: T[], columns: { key: string; label: string; render: (row: T) => React.ReactNode }[], route: (row: T) => string, searchLabel: string, extra?: React.ReactNode) => <><Section action={extra}><DataTable rows={viewState === "empty" ? [] : rows} columns={columns} searchLabel={searchLabel} persistKey={`oms:${root}`} onOpen={row => go(route(row))} state={viewState}/></Section></>;
  const crumbs = (section: string, parent: string, detail?: string) => [{ label: "工作台", onClick: () => go(base) }, { label: section, onClick: () => go(parent) }, ...(detail ? [{ label: detail }] : [])];
  const notice = message && <Notice>{message}</Notice>;
  const authorizedFor = (tenant: (typeof tenants)[number]) => services.filter(service => (
    (schoolServiceAccess[tenant.id] ?? []).includes(service.id) || (authorized[tenant.id] ?? []).includes(service.id)
  ) && !(revokedAuth[tenant.id] ?? []).includes(service.id));
  const openConnectionEditor = (id?: string, defaultServiceId?: string) => {
    const existing = connections.find(row => row.id === id);
    setEditingConnectionId(existing?.id ?? null);
    setConnectionName(existing?.name ?? "");
    setConnectionProvider(existing?.provider ?? "");
    setConnectionServiceIds(existing?.serviceIds ?? [defaultServiceId ?? "llm"]);
    setConnectionUrl(existing?.baseUrl ?? "");
    setMessage("");
    setFormOpen(id ? "connection" : "new-connection");
  };
  const connectionForm = (id?: string) => {
    const target = connectionTarget(connectionProvider);
    const supported = Object.keys(target?.services ?? {});
    const save = () => {
      if (!connectionName.trim() || !target) { setMessage("请选择连接名称与供应商。"); return; }
      if (!connectionServiceIds.length || connectionServiceIds.some(serviceId => !supported.includes(serviceId))) { setMessage("请从该供应商支持的服务中至少选择一项。"); return; }
      if (id) {
        const dependent = profiles.find(profile => profile.fields.connection_id === id && (
          !connectionServiceIds.includes(profile.serviceId) || profile.provider !== connectionService(connectionProvider, profile.serviceId)?.provider
        ));
        if (dependent) { setMessage(`已有 Profile 使用此连接的${services.find(row => row.id === dependent.serviceId)?.name ?? dependent.serviceId}；不能移除该服务或变更供应商。`); return; }
      }
      const row = { id: id ?? `c-demo-${Date.now()}`, name: connectionName.trim(), provider: connectionProvider, serviceIds: connectionServiceIds, scope: connectionServiceIds.join(" / "), baseUrl: connectionUrl.trim(), status: "草稿", note: "本地配置草稿，尚未发布" };
      setConnections(id ? connections.map(item => item.id === id ? row : item) : [...connections, row]);
      setFormOpen("");
      setMessage("连接草稿已保存至本地演示列表；真实配置未变更。");
    };
    return <div className="side-panel"><h3>{id ? "编辑连接草稿" : "新增连接"} · 本地演示</h3>
      <Notice>供应商与适用服务来自基座设置 descriptor 离线快照；不是实时连接测试。</Notice>
      <div className="form-grid">
        <label className="form-field">名称<input value={connectionName} onChange={event => setConnectionName(event.target.value)}/></label>
        <label className="form-field">供应商<select value={connectionProvider} onChange={event => {
          const next = connectionTarget(event.target.value);
          const previousDefault = connectionTarget(connectionProvider)?.default_base_url ?? "";
          setConnectionProvider(event.target.value);
          setConnectionServiceIds(current => {
            const valid = current.filter(serviceId => Boolean(next?.services[serviceId]));
            return valid.length ? valid : next?.services.llm ? ["llm"] : Object.keys(next?.services ?? {}).slice(0, 1);
          });
          if (!connectionUrl || connectionUrl === previousDefault) setConnectionUrl(next?.default_base_url ?? "");
          setMessage("");
        }}><option value="">请选择供应商</option>{connectionOptions().map(option => <option key={option.provider} value={option.provider}>{option.label}</option>)}</select></label>
        <fieldset className="connection-targets"><legend>适用服务</legend><div>{supported.map(serviceId => <label key={serviceId}><input type="checkbox" checked={connectionServiceIds.includes(serviceId)} onChange={event => setConnectionServiceIds(current => event.target.checked ? [...new Set([...current, serviceId])] : current.filter(id => id !== serviceId))}/>{connectionLabels[serviceId] ?? serviceId}</label>)}</div></fieldset>
        <label className="form-field">Base URL<input value={connectionUrl} onChange={event => setConnectionUrl(event.target.value)} placeholder={target?.default_base_url || "留空使用供应商默认端点"}/></label>
      </div>
      {connectionProvider && !supported.length && <Notice tone="warn">该供应商当前没有可共用凭据的服务。</Notice>}
      <Notice tone="warn">联网搜索使用独立 Profile，不在 connections 中创建。连接凭据在保存后通过独立操作配置；仅接受演示值。</Notice>{notice}
      <div className="form-actions"><Button variant="primary" onClick={save}>保存演示草稿</Button><Button onClick={() => setFormOpen("")}>取消</Button></div>
    </div>;
  };

  const providerSection = (service: ServiceView, view: "provider" | "models", itemId?: string) => {
    const supportsProfile = profileServiceIds.has(service.id);
    const supportsModel = modelServiceIds.has(service.id);
    const scopedProfiles = profiles.filter(row => row.serviceId === service.id);
    const scopedModels = models.filter(row => row.serviceId === service.id);
    const selectedProfile = view === "provider" ? scopedProfiles.find(row => row.id === itemId) : undefined;
    const selectedModel = view === "models" ? scopedModels.find(row => row.id === itemId) : undefined;
    const selectedProviderOption = selectedProfile ? providerOption(service.id, selectedProfile.provider) : undefined;
    const needsApiKey = Boolean(selectedProviderOption && (service.id === "search" ? selectedProviderOption.requires_api_key : selectedProviderOption.auth_mode !== "oauth"));
    return <>
      {itemId ? selectedProfile ? <>
          <PageHead eyebrow="Provider Profile" title={selectedProfile.name} breadcrumbs={[{ label: service.name, onClick: () => go(`${base}/services/${service.id}/provider`) }, { label: selectedProfile.name }]}/>
          <DetailGrid rows={[
            { label: "名称", value: selectedProfile.name },
            { label: "供应商", value: selectedProfile.provider },
            { label: "服务", value: service.name },
            { label: "状态", value: selectedProfile.status },
            { label: "凭据来源", value: selectedProfile.fields.connection_id ? "供应商连接" : "Profile 自有凭据" },
            { label: "供应商连接", value: selectedProfile.fields.connection_id ? connections.find(row => row.id === selectedProfile.fields.connection_id)?.name ?? "关联待核对" : "未关联" },
            { label: "凭据状态", value: selectedProfile.fields.connection_id ? credentialStatus(`connection:${selectedProfile.fields.connection_id}`) : (needsApiKey ? credentialStatus(`profile:${selectedProfile.id}`) : selectedProviderOption?.auth_mode === "oauth" ? "OAuth 授权待接入" : "无需 API Key") },
            { label: "关联模型数", value: String(scopedModels.filter(row => row.profileId === selectedProfile.id).length) },
            { label: "API 格式", value: selectedProfile.fields.api_format || "供应商默认" },
            { label: "额外请求头", value: `${Object.keys(selectedProfile.fields.extra_headers ?? {}).length} 个普通请求头` },
            { label: "真实生效", value: "待执行者确认" },
          ]}/>
          <div className="inline-list">
            <Button onClick={() => go(`${base}/services/${service.id}/models?profile=${encodeURIComponent(selectedProfile.id)}`)}>查看关联模型</Button>
            {selectedProfile.fields.connection_id ? connections.some(row => row.id === selectedProfile.fields.connection_id) && <Button onClick={() => go(`${base}/connections/${selectedProfile.fields.connection_id}`)}>查看供应商连接</Button>
              : canConfigure && needsApiKey && <Button onClick={() => openCredential(`profile:${selectedProfile.id}`, "Profile", "API Key")}>{credentialDemos[`profile:${selectedProfile.id}`] ? "轮换凭据" : "配置凭据"}</Button>}
          </div>
          {selectedProviderOption?.auth_mode === "oauth" && <Notice tone="warn">OAuth 授权流程待接入；请勿以 API Key 演示表单替代 OAuth 登录与令牌管理。</Notice>}
        </>
        : selectedModel ? <><PageHead eyebrow="模型详情" title={selectedModel.name} breadcrumbs={[{ label: service.name, onClick: () => go(`${base}/services/${service.id}/models`) }, { label: selectedModel.name }]}/><DetailGrid rows={[{ label: "名称", value: selectedModel.name }, { label: "模型标识", value: selectedModel.model }, { label: "所属 Profile", value: profiles.find(row => row.id === selectedModel.profileId)?.name ?? "待核对" }, { label: "服务", value: service.name }, { label: "上下文窗口／维度等", value: selectedModel.detail || "使用供应商默认" }, { label: "推理档位", value: selectedModel.fields.reasoning_effort || "自动" }, { label: "状态", value: selectedModel.status }]}/>{scopedProfiles.some(row => row.id === selectedModel.profileId) && <Button onClick={() => go(`${base}/services/${service.id}/provider/${selectedModel.profileId}`)}>查看所属 Profile</Button>}</>
        : <StatePanel state="empty" message="对象不存在或不可访问"/>
      : view === "provider" ? <Section title="Provider Profile" subtitle="草稿不代表真实配置生效" action={canConfigure && supportsProfile ? <Button onClick={() => setFormOpen("new-profile")}>新增 Provider profile</Button> : undefined}>
          <DataTable rows={scopedProfiles} searchLabel="搜索 Profile" onOpen={row => go(`${base}/services/${service.id}/provider/${row.id}`)} columns={[{ key: "name", label: "Profile", render: row => title(row.name, row.provider) }, { key: "status", label: "状态", render: row => badge(row.status) }]}/>
          {connectableServiceIds.has(service.id) && <Button onClick={() => go(`${base}/services/${service.id}/connections`)}>适用连接</Button>}
          {service.id === "search" && <Notice>联网搜索使用独立 Profile，不进入 connections，也没有模型列表。</Notice>}
        </Section>
      : <Section title="模型清单" subtitle="模型归属于本服务 Provider Profile" action={canConfigure && supportsModel ? <Button variant="primary" onClick={() => setFormOpen("new-model")}>新增模型</Button> : undefined}>
          <DataTable rows={scopedModels.filter(row => { const profileId = new URLSearchParams(locationSearch).get("profile"); return !profileId || row.profileId === profileId; })} searchLabel="搜索模型" onOpen={row => go(`${base}/services/${service.id}/models/${row.id}`)} columns={[{ key: "name", label: "模型", render: row => title(row.name, row.model) }, { key: "profile", label: "所属 Profile", render: row => profiles.find(item => item.id === row.profileId)?.name ?? "待核对" }, { key: "status", label: "状态", render: row => badge(row.status) }]}/>
        </Section>}
      {formOpen === "new-profile" && view === "provider" && supportsProfile && canConfigure && <FormModal title="新增 Provider profile" onClose={() => setFormOpen("")} suspended={!!confirm}><ServiceConfigForm serviceId={service.id} requireProvider connections={service.id === "search" ? [] : connections} existingNames={scopedProfiles.map(row => row.name)} onSave={values => { setProfiles(current => [{ id: `profile-${Date.now()}`, serviceId: service.id, name: values.name, provider: values.provider, fields: { credential_source: values.credential_source === "connection" ? "connection" : "own", connection_id: values.connection_id || undefined, base_url: values.base_url || undefined, api_format: values.api_format || undefined, api_version: values.api_version || undefined, proxy: values.proxy || undefined, extra_headers: values.extra_headers ? JSON.parse(values.extra_headers) as Record<string, string> : undefined }, status: "草稿" }, ...current]); setFormOpen(""); setMessage("Provider profile 已保存为本地草稿；尚未发布或连接真实 Secret。"); }} onCancel={() => setFormOpen("")}/></FormModal>}
      {formOpen === "new-model" && view === "models" && supportsModel && canConfigure && <FormModal title="新增模型" onClose={() => setFormOpen("")} suspended={!!confirm}><OmsModelCreate serviceId={service.id} profiles={scopedProfiles} models={scopedModels} onSave={row => { setModels(current => [row, ...current]); setFormOpen(""); setMessage("模型草稿已加入本服务；未发布且不可调用。"); }} onCancel={() => setFormOpen("")}/></FormModal>}
    </>;
  };

  const renderContent = (segments: string[]): React.ReactNode => {
  let content: React.ReactNode;
  if (authRoots.has(root)) {
    content = <OmsAuthorization section={root as "platform-people" | "platform-roles" | "school-permissions" | "authz-audit"} selectedId={segments[1]} view={segments[2]} state={authState} onChange={setAuthState} onOpen={(id, view) => go(`${base}/${root}/${encodeURIComponent(id)}${view ? `/${view}` : ""}`)} onClose={() => go(`${base}/${root}`)} role={role}/>;
  } else if (root === "home") {
    const alerts = [
      { id: "a-1", issue: "文档 OCR 服务供给接近可授予上限", object: "文档 OCR · 演示解析引擎", status: "需补充", to: `${base}/supply/s-ocr` },
      { id: "a-2", issue: "星河实验学校 OCR 额度已用尽", object: "星河实验学校 · 文档 OCR", status: "额度不足", to: `${base}/tenants/aurora/grants` },
      { id: "a-3", issue: "一条模型调用用量尚未确认", object: "北辰学校 · 对话模型", status: "待核对", to: `${base}/usage/use-7427` },
    ];
    content = <><PageHead eyebrow="平台概览" title="工作台" description="关注需要处理的供给、额度与用量事项。" actions={<div className="scenario-bar"><label htmlFor="scenario">审计场景</label><select id="scenario" value={scenario} onChange={e => setScenario(e.target.value)}><option value="normal">正常</option><option value="loading">加载中</option><option value="empty">空记录</option><option value="error">读取失败</option><option value="forbidden">无权限</option></select></div>}/>
      <MetricStrip items={[{ label: "服务目录", value: "11", note: "含模型、OCR、工具" }, { label: "运营学校", value: "4", note: "状态来自 EduPlus2" }, { label: "待处理事项", value: "3", note: "供给与用量" }, { label: "待核对调用", value: "1", note: "不能记作零消耗", tone: "warning" }]}/>
      <Section title="待处理事项" subtitle="按影响优先处理；查看详情后再做决定"><DataTable rows={viewState === "empty" ? [] : alerts} state={viewState} searchLabel="搜索待办" onOpen={row => go(row.to)} columns={[{ key: "issue", label: "事项", render: row => title(row.issue, row.object) }, { key: "status", label: "状态", render: row => badge(row.status) }]}/></Section>
      <div className="audit-note">演示数据仅用于界面审计，不代表平台服务已经部署或配置生效。</div></>;
  } else if (root === "tenants") {
    const selected = tenants.find(item => item.id === segments[1]);
    if (!selected) {
      content = <><PageHead eyebrow="学校运营" title="学校与权益" description="学校生命周期由 EduPlus2 同步；在详情中管理服务授权与额度。"/>
        <Section><DataTable rows={viewState === "empty" ? [] : tenants} state={viewState} searchLabel="搜索学校" persistKey="oms:tenants" rowActions={row => [
          { label: "学校资料", onClick: () => go(`${base}/tenants/${row.id}/info`) },
          { label: "服务授权", onClick: () => go(`${base}/tenants/${row.id}/access`) },
          { label: "额度清单", onClick: () => go(`${base}/tenants/${row.id}/grants`) },
        ]} columns={[{ key: "name", label: "学校", render: row => title(row.name, row.code) }, { key: "kind", label: "类型", render: row => row.kind }, { key: "services", label: "授权服务", render: row => `${authorizedFor(row).length} 项` }, { key: "status", label: "同步状态", render: row => badge(row.status) }]}/></Section></>;
    } else if (segments[2] === "grants" && segments[3]) {
      const grant = grants.find(item => item.id === segments[3]);
      content = grant ? <><PageHead eyebrow="额度详情" title={`额度 ${grant.id}`} breadcrumbs={[{ label: "工作台", onClick: () => go(base) }, { label: "学校与权益", onClick: () => go(`${base}/tenants`) }, { label: selected.name, onClick: () => go(`${base}/tenants/${selected.id}/grants`) }, { label: grant.id }]} description="授予记录与实际消耗分别呈现；赠送额度优先使用。" actions={canWrite && grant.remaining !== null ? <div className="inline-list"><Button onClick={() => { setQuantity("1000"); setFormOpen("adjust-grant"); }}>调整额度</Button><Button onClick={() => { if (!grant.remaining) { setMessage("该额度没有可撤销的未使用部分。"); return; } const unused = grant.remaining; setConfirm({ title: "确认撤销额度", description: `${selected.name} · ${grant.service}\n撤销未使用的 ${unused.toLocaleString()} ${grant.unit}，历史已消耗 ${grant.used?.toLocaleString()} ${grant.unit} 保留。仅更新本地演示。`, action: () => { setGrants(current => current.map(row => row.id === grant.id ? { ...row, remaining: 0, revoked: (row.revoked ?? 0) + unused, status: "已结束" } : row)); setSupply(current => current.map(row => row.id === grant.supplyId ? { ...row, committed: row.committed - unused, available: row.available + unused } : row)); setMessage("未使用额度已在本地演示中撤销；历史消耗保留。"); } }); }}>撤销未使用额度</Button></div> : undefined}/>
        <DetailGrid rows={[{ label: "服务", value: grant.service }, { label: "获取方式", value: grant.method }, { label: "状态", value: badge(grant.status) }, { label: "授予总量", value: `${grant.total.toLocaleString()} ${grant.unit}` }, { label: "已消耗", value: grant.used === null ? "待核对" : `${grant.used.toLocaleString()} ${grant.unit}` }, { label: "剩余额度", value: grant.remaining === null ? "待核对" : `${grant.remaining.toLocaleString()} ${grant.unit}` }, { label: "已撤销未用", value: grant.revoked ? `${grant.revoked.toLocaleString()} ${grant.unit}` : "未发生" }, { label: "有效期", value: grant.valid }, { label: "授予来源", value: "OMS 演示记录" }, { label: "所属学校", value: selected.name }]}/>
        {formOpen === "adjust-grant" && canWrite && <FormModal title="调整额度" onClose={() => setFormOpen("")} suspended={!!confirm}><div className="side-panel"><h3>增加未使用额度 · 本地演示</h3><label className="form-field">增加额度（{grant.unit}）<input type="number" min="1" value={quantity} onChange={event => setQuantity(event.target.value)}/></label><div className="form-actions"><Button variant="primary" onClick={() => { const amount = Number(quantity); const source = supply.find(row => row.id === grant.supplyId); if (!Number.isSafeInteger(amount) || amount <= 0) { setMessage("请输入有效的正整数额度。"); return; } if (!source || source.available < amount) { setMessage("平台可授予额度不足，请先登记并核对供给批次。"); return; } setConfirm({ title: "确认调整额度", description: `${selected.name} · ${grant.service}\n增加 ${amount.toLocaleString()} ${grant.unit} 未使用额度。仅更新本地演示。`, action: () => { setGrants(current => current.map(row => row.id === grant.id ? { ...row, total: row.total + amount, remaining: (row.remaining ?? 0) + amount, status: "生效中" } : row)); setSupply(current => current.map(row => row.id === source.id ? { ...row, committed: row.committed + amount, available: row.available - amount } : row)); setFormOpen(""); setMessage("本地演示额度调整已保存；历史消耗未改变。"); } }); }}>提交调整</Button><Button onClick={() => setFormOpen("")}>取消</Button></div></div>{notice}</FormModal>}{!formOpen && notice}
        <Button onClick={() => go(`${base}/usage?grant=${encodeURIComponent(grant.id)}`)}>查看消耗明细</Button>
      </> : <StatePanel state="empty" message="额度记录不存在。"/>;
    } else {
      const tenantGrants = grants.filter(item => item.tenantId === selected.id);
      const tenantAuthorized = authorizedFor(selected);
      const schoolView = segments[2] ?? "info";
      content = <><PageHead eyebrow="学校与权益" title={selected.name} description={({ info: "学校身份与同步状态", access: "本学校可使用的服务资格", grants: "本学校的赠送与充值额度" } as Record<string, string>)[schoolView]} breadcrumbs={crumbs("学校与权益", `${base}/tenants`, selected.name)} actions={canWrite && schoolView === "grants" ? <Button onClick={() => { setFormOpen(formOpen === "grant" ? "" : "grant"); setMessage(""); }} variant="primary">授予额度（演示）</Button> : undefined}/>
        {schoolView === "info" && <DetailGrid rows={[{ label: "学校编号", value: selected.code }, { label: "机构类型", value: selected.kind }, { label: "生命周期来源", value: selected.source }, { label: "同步状态", value: badge(selected.status) }]}/>}
        {schoolView === "info" && <Notice>学校开通、暂停与恢复只能由 EduPlus2 生命周期事件触发；OMS 不提供直接开停操作。</Notice>}
        {schoolView === "grants" && formOpen === "grant" && canWrite && <FormModal title="授予额度" onClose={() => setFormOpen("")} suspended={!!confirm}><div className="side-panel"><h3>新增授予 · 本地演示</h3><div className="form-grid"><label className="form-field">服务<select value={grantService} onChange={e => setGrantService(e.target.value)}>{supply.map(item => <option key={item.id} value={item.id.slice(2)}>{item.service} · {item.unit}</option>)}</select></label><label className="form-field">获取方式<select value={method} onChange={e => setMethod(e.target.value)}><option>赠送</option><option>充值</option></select></label><label className="form-field">授予数量<input type="number" min="1" value={quantity} onChange={e => setQuantity(e.target.value)}/></label><label className="form-field">有效期<input type="date" value={validDate} onChange={event => setValidDate(event.target.value)}/></label></div><div className="form-actions"><Button variant="primary" onClick={() => { const amount = Number(quantity); const source = supply.find(row => row.id === `s-${grantService}`); if (!Number.isSafeInteger(amount) || amount <= 0 || !source) { setMessage("请输入有效的服务与正整数额度。"); return; } if (!tenantAuthorized.some(row => row.id === grantService)) { setMessage("请先授权该服务，再授予额度。"); return; } if (!validDate || validDate < localToday()) { setMessage("请选择今天或之后的有效期。"); return; } if (amount > source.available) { setMessage("平台可授予额度不足，请先登记并核对供给批次。"); return; } const next = { id: `q-demo-${Date.now()}`, tenant: selected.name, tenantId: selected.id, service: source.service, serviceId: grantService, supplyId: source.id, method, total: amount, used: 0, remaining: amount, unit: source.unit, valid: validDate, status: "生效中" }; setConfirm({ title: "确认授予额度", description: `${selected.name} · ${source.service}\n${method} ${amount.toLocaleString()} ${source.unit}，有效期至 ${validDate}。此操作仅更新本地演示状态。`, action: () => { setGrants(current => [...current, next]); setSupply(current => current.map(row => row.id === source.id ? { ...row, committed: row.committed + amount, available: row.available - amount } : row)); setMessage("演示授予已加入本地列表；没有写入真实 OMS。"); setFormOpen(""); } }); }}>确认演示授予</Button><Button onClick={() => setFormOpen("")}>取消</Button></div></div>{notice}</FormModal>}
        {!formOpen && notice}
        {schoolView === "grants" && <DataTable rows={tenantGrants.filter(g => quotaFilter === "all" || g.method === quotaFilter)} searchLabel="搜索额度" persistKey={`oms:tenant:${selected.id}:grants`} filters={[{ label: "获取方式", value: quotaFilter, options: [{ value: "all", label: "全部方式" }, { value: "赠送", label: "赠送" }, { value: "充值", label: "充值" }], onChange: setQuotaFilter }]} onOpen={row => go(`${base}/tenants/${selected.id}/grants/${row.id}`)} columns={[{ key: "service", label: "服务", render: row => title(row.service, row.id) }, { key: "method", label: "获取方式", render: row => row.method }, { key: "remaining", label: "剩余额度", render: row => row.remaining === null ? "待核对" : `${row.remaining.toLocaleString()} ${row.unit}` }, { key: "status", label: "状态", render: row => badge(row.status) }]}/>}
        {schoolView === "access" && <><div className="section-head"><h2>已授权服务</h2>{canWrite && <div className="inline-list"><Button onClick={() => { setAuthService(services.find(row => !tenantAuthorized.some(item => item.id === row.id))?.id ?? ""); setFormOpen("authorize"); }}>授权服务（演示）</Button></div>}</div>{formOpen === "authorize" && <FormModal title="授权服务" onClose={() => setFormOpen("")} suspended={!!confirm}><div className="side-panel"><h3>添加学校服务资格 · 本地演示</h3><div className="form-grid"><label className="form-field">服务<select value={authService} onChange={e => setAuthService(e.target.value)}>{services.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label></div><div className="form-actions"><Button variant="primary" onClick={() => { const target = services.find(s => s.id === authService); if (!target) return; if (tenantAuthorized.some(s => s.id === authService)) { setMessage("该服务已在学校授权清单中。"); return; } setConfirm({ title: "确认服务授权", description: `${selected.name} · ${target.name}；此操作仅更新本地演示状态。`, action: () => { setAuthorized(current => ({ ...current, [selected.id]: [...(current[selected.id] ?? []), authService] })); setRevokedAuth(current => ({ ...current, [selected.id]: (current[selected.id] ?? []).filter(id => id !== authService) })); setMessage("演示服务资格已更新；实际授权未写入。"); setFormOpen(""); } }); }}>确认演示授权</Button><Button onClick={() => setFormOpen("")}>取消</Button></div></div>{notice}</FormModal>}<DataTable rows={tenantAuthorized} searchLabel="搜索授权服务" rowActions={row => [{ label: "服务资料", onClick: () => go(`${base}/services/${row.id}/info`) }, ...(canWrite ? [{ label: "撤销授权", onClick: () => { if (tenantGrants.some(grant => grant.serviceId === row.id && (grant.remaining === null || grant.remaining > 0))) { setMessage("该服务仍有关联有效或待核对额度，请先处理额度后再撤销授权。"); return; } setConfirm({ title: "确认撤销服务授权", description: `${selected.name} · ${row.name}；不会变更历史消耗。此操作仅更新本地演示状态。`, action: () => { setRevokedAuth(current => ({ ...current, [selected.id]: [...new Set([...(current[selected.id] ?? []), row.id])] })); setMessage("演示服务资格已撤销；历史记录保留。"); } }); } }] : [])]} columns={[{ key: "name", label: "服务", render: row => row.name }, { key: "category", label: "类别", render: row => row.category }, { key: "status", label: "状态", render: row => badge(row.status === "available" ? "已授权" : "需关注") }]}/></>}

      </>;
    }
  } else if (root === "services") {
    const service = serviceRows.find(item => item.id === segments[1]);
    const serviceView = segments[2] ?? "info";
    if (!service) {
      content = <><PageHead eyebrow="资源目录" title="模型与服务" description="按基座服务语义管理平台目录；配置与实际生效分离。" actions={canConfigure ? <Button variant="primary" onClick={() => setFormOpen("create-resource")}>新增服务接入</Button> : undefined}/><Tabs tabs={["全部服务", "文档识别与解析"]} active={catalogTab} onChange={setCatalogTab}/>{catalogTab === "全部服务" ? <ServiceList services={viewState === "empty" ? [] : serviceRows} state={viewState} showHeading={false} rowActions={row => [{ label: "服务概况", onClick: () => go(`${base}/services/${row.id}/info`) }, { label: "服务配置", onClick: () => go(`${base}/services/${row.id}/config`) }, ...(profileServiceIds.has(row.id) ? [{ label: "Provider 配置", onClick: () => go(`${base}/services/${row.id}/provider`) }] : []), ...(modelServiceIds.has(row.id) ? [{ label: "模型清单", onClick: () => go(`${base}/services/${row.id}/models`) }] : []), { label: "关联记录", onClick: () => go(`${base}/services/${row.id}/relations`) }, { label: "发布记录", onClick: () => go(`${base}/services/${row.id}/release`) }]}/> : <OcrServiceList services={serviceRows.filter(item => item.id === "ocr" || item.id === "rag")} state={viewState} showHeading={false} rowActions={row => [{ label: "服务概况", onClick: () => go(`${base}/services/${row.id}/info`) }, { label: "服务配置", onClick: () => go(`${base}/services/${row.id}/config`) }, ...(profileServiceIds.has(row.id) ? [{ label: "Provider 配置", onClick: () => go(`${base}/services/${row.id}/provider`) }] : []), ...(modelServiceIds.has(row.id) ? [{ label: "模型清单", onClick: () => go(`${base}/services/${row.id}/models`) }] : []), { label: "关联记录", onClick: () => go(`${base}/services/${row.id}/relations`) }, { label: "发布记录", onClick: () => go(`${base}/services/${row.id}/release`) }]}/>}</>;
    } else {
      const attr = providerAttributes[service.id] ?? { fields: ["适配器方案", "原生计量单位", "服务端 descriptor 待接入"], note: "外部服务草稿未接入基座执行者，不能发起真实调用。" };
      const parsing = configDrafts[service.id];
      const parsingCredential = (service.id === "ocr" || service.id === "rag") && parsing?.engine === "mineru" && parsing.mode === "cloud"
        ? { key: "parser:mineru", scope: "MinerU", label: "API Token" as const, action: "配置云端 Token" }
        : (service.id === "ocr" || service.id === "rag") && parsing?.engine === "docling" && parsing.mode === "remote"
          ? { key: "parser:docling", scope: "Docling", label: "API Key" as const, action: "配置远端 API Key" }
          : null;

      content = <><PageHead eyebrow="服务详情" title={service.name} description={service.description} breadcrumbs={crumbs("模型与服务", `${base}/services`, service.name)} actions={canConfigure && (serviceView === "config" || serviceView === "release") && !serviceDrafts[service.id] ? <div className="inline-list">{serviceView === "config" && <Button variant="primary" onClick={() => { setFormOpen("config"); setMessage(""); }}>编辑配置草稿</Button>}{serviceView === "release" && configDrafts[service.id] && <Button onClick={() => setConfirm({ title: "确认提交发布申请", description: `${service.name} · ${configDrafts[service.id].name}\n仅登记本地演示申请，真实配置仍须由执行者测试与确认。`, action: () => { setReleaseRequests(current => [...current, { id: `release-${Date.now()}`, serviceId: service.id, name: configDrafts[service.id].name, status: "待执行者确认" }]); setMessage("本地演示发布申请已登记；运行态未改变。"); } })}>提交发布申请（演示）</Button>}</div> : undefined}/>{serviceView === "info" && <ServiceDetail service={service}/>}
      {serviceView === "info" && serviceDrafts[service.id] && <Notice tone="warn">适配器方案：{serviceDrafts[service.id].detail}。此目录条目尚未接入执行者，不可调用或授予额度。</Notice>}{serviceView === "config" && formOpen === "config" && canConfigure && <FormModal title={`编辑${service.name}配置`} onClose={() => setFormOpen("")} suspended={!!confirm}><ServiceConfigForm serviceId={service.id} profiles={profiles} models={models} initialValues={configDrafts[service.id]} onSave={values => { setConfigDrafts({ ...configDrafts, [service.id]: values }); setMessage(`“${values.name}”演示草稿已保存；真实配置未变更。`); setFormOpen(""); }} onCancel={() => setFormOpen("")}/></FormModal>}
        {notice}
        {serviceView === "config" && <><Section title="配置概况"><DetailGrid rows={[{ label: "本地配置草稿", value: configDrafts[service.id]?.name ?? "尚无草稿" }, { label: "配置生效", value: badge(configDrafts[service.id] ? "未发布 · 待确认" : "待确认") }]}/></Section><div className="inline-list"><Button onClick={() => go(`${base}/services/${service.id}/supply`)}>关联供给</Button><Button onClick={() => go(`${base}/services/${service.id}/schools`)}>授权学校</Button><Button onClick={() => go(`${base}/services/${service.id}/grants`)}>关联额度</Button><Button onClick={() => go(`${base}/services/${service.id}/usage`)}>用量记录</Button></div></>}
        {serviceView === "config" && parsingCredential && <Section title="解析引擎凭据" action={canConfigure ? <Button onClick={() => openCredential(parsingCredential.key, parsingCredential.scope, parsingCredential.label)}>{credentialDemos[parsingCredential.key] ? (parsingCredential.label === "API Token" ? "轮换云端 Token" : "轮换远端 API Key") : parsingCredential.action}</Button> : undefined}><DetailGrid rows={[{ label: "凭据状态", value: credentialStatus(parsingCredential.key) }]}/><Notice>凭据作用于解析引擎；真实可用性仍以基座执行者返回的测试与 readiness 为准。</Notice></Section>}
        {serviceView === "relations" && <Section title="关联记录" subtitle="选择关系类型后查看当前服务的具体记录与操作"><div className="inline-list"><Button onClick={() => go(`${base}/services/${service.id}/supply`)}>关联供给</Button><Button onClick={() => go(`${base}/services/${service.id}/schools`)}>授权学校</Button><Button onClick={() => go(`${base}/services/${service.id}/grants`)}>关联额度</Button><Button onClick={() => go(`${base}/services/${service.id}/usage`)}>用量记录</Button>{connectableServiceIds.has(service.id) && <Button onClick={() => go(`${base}/services/${service.id}/connections`)}>适用连接</Button>}</div></Section>}
        {serviceView === "supply" && <Section title="关联供给"><DataTable rows={supply.filter(row => row.serviceId === service.id)} searchLabel="搜索关联供给" rowActions={row => [{ label: "供给资料", onClick: () => go(`${base}/supply/${row.id}/info`) }, { label: "取得记录", onClick: () => go(`${base}/supply/${row.id}/acquisition`) }]} columns={[{ key: "name", label: "供给项目", render: row => row.name }, { key: "available", label: "可授予量", render: row => `${row.available.toLocaleString()} ${row.unit}` }]}/></Section>}
        {serviceView === "schools" && <Section title="授权学校"><DataTable rows={tenants.filter(row => authorizedFor(row).some(item => item.id === service.id))} searchLabel="搜索授权学校" rowActions={row => [{ label: "服务授权", onClick: () => go(`${base}/tenants/${row.id}/access`) }, { label: "额度清单", onClick: () => go(`${base}/tenants/${row.id}/grants`) }]} columns={[{ key: "name", label: "学校", render: row => row.name }, { key: "status", label: "同步状态", render: row => badge(row.status) }]}/></Section>}
        {serviceView === "grants" && <Section title="关联额度"><DataTable rows={grants.filter(row => row.serviceId === service.id)} searchLabel="搜索关联额度" rowActions={row => [{ label: "额度详情", onClick: () => go(`${base}/tenants/${row.tenantId}/grants/${row.id}`) }, { label: "消耗明细", onClick: () => go(`${base}/usage?grant=${encodeURIComponent(row.id)}`) }]} columns={[{ key: "tenant", label: "学校", render: row => row.tenant }, { key: "remaining", label: "剩余额度", render: row => row.remaining === null ? "待核对" : `${row.remaining.toLocaleString()} ${row.unit}` }]}/></Section>}
        {serviceView === "usage" && <Section title="用量记录"><DataTable rows={calls.filter(row => row.serviceId === service.id)} searchLabel="搜索服务调用" rowActions={row => [{ label: "调用详情", onClick: () => go(`${base}/usage/${row.id}`) }]} columns={[{ key: "id", label: "调用", render: row => title(row.id, row.time) }, { key: "usage", label: "实际用量", render: row => row.usage }, { key: "status", label: "核对状态", render: row => badge(row.status) }]}/></Section>}
        {serviceView === "connections" && connectableServiceIds.has(service.id) && <Section title="适用连接" action={canConfigure ? <Button onClick={() => openConnectionEditor(undefined, service.id)}>新增适用连接</Button> : undefined}><DataTable rows={connections.filter(row => row.serviceIds.includes(service.id))} searchLabel="搜索适用连接" rowActions={row => [{ label: "连接资料", onClick: () => go(`${base}/connections/${row.id}`) }, ...(canConfigure ? [{ label: "编辑连接", onClick: () => openConnectionEditor(row.id) }] : [])]} columns={[{ key: "name", label: "连接", render: row => row.name }, { key: "status", label: "状态", render: row => badge(row.status) }]}/></Section>}
        {(serviceView === "provider" || serviceView === "models") && providerSection(service, serviceView, segments[3])}
        {serviceView === "config" && <div className="two-column"><Section title="智能体基座设置属性" subtitle="字段名以现有设置逻辑为准；条件值由后端提供"><div className="side-panel"><div className="inline-list">{attr.fields.map(field => <span className="mini-pill" key={field}>{field}</span>)}</div><p>{attr.note}</p></div></Section><div className="side-panel"><h3>配置边界</h3><p>个人偏好、私有知识内容与原始凭据不在这里维护。平台配置发布需要独立权限、测试和生效确认。</p></div></div>}
        {serviceView === "release" && <Section title="发布与生效记录" subtitle="演示申请不是已生效配置；需执行者测试并确认">{releaseRequests.some(row => row.serviceId === service.id) ? <DataTable rows={releaseRequests.filter(row => row.serviceId === service.id)} searchLabel="搜索发布申请" columns={[{ key: "name", label: "配置草稿", render: row => row.name }, { key: "status", label: "确认状态", render: row => badge(row.status) }]}/> : <StatePanel state="empty" message="尚无真实发布记录；演示草稿不会成为运行态配置。"/>}</Section>}
      </>;
    }
  } else if (root === "skills") {
    let selectedSkillId: string | undefined;
    try { selectedSkillId = segments[1] ? decodeURIComponent(segments[1]) : undefined; } catch { selectedSkillId = undefined; }
    content = (segments.length > 3 || (segments[1] && !selectedSkillId) || (segments[2] && !["info", "package", "release", "grants"].includes(segments[2]))) ? <StatePanel state="forbidden" message="Skill 专题不存在或不可访问"/> : <OmsSkills selectedId={selectedSkillId} view={segments[2] ?? "info"} onOpen={(id, view) => go(`${base}/skills/${encodeURIComponent(id)}/${view}`)} onOpenSchool={id => go(`${base}/tenants/${id}/info`)} onClose={() => go(`${base}/skills`)} canConfigure={canConfigure} state={viewState}/>;
  } else if (root === "connections") {
    const connection = connections.find(item => item.id === segments[1]);
    content = connection ? <>
      <PageHead eyebrow="连接详情" title={connection.name} breadcrumbs={crumbs("供应商连接", `${base}/connections`, connection.name)} description="连接元数据与凭据维护分开操作；凭据明文不在详情回显。" actions={canConfigure ? <div className="inline-list"><Button variant="primary" onClick={() => openConnectionEditor(connection.id)}>编辑连接草稿</Button><Button onClick={() => openCredential(`connection:${connection.id}`, "连接", "API Key")}>{credentialDemos[`connection:${connection.id}`] ? "轮换凭据" : "配置凭据"}</Button></div> : undefined}/>
      <DetailGrid rows={[{ label: "供应商", value: connection.provider }, { label: "适用服务", value: connection.scope }, { label: "状态", value: badge(connection.status) }, { label: "凭据状态", value: credentialStatus(`connection:${connection.id}`) }, { label: "Base URL", value: connection.baseUrl || "供应商默认端点" }, { label: "备注", value: connection.note }]}/>
      <Notice>基座连接配置目前支持 llm/task/embedding/tts/stt/imagegen/videogen；search 使用独立 Profile。演示凭据不是受控 Secret，也不能用于真实调用。</Notice>
      {!formOpen && notice}
      {formOpen === "connection" && canConfigure && <FormModal title={`编辑${connection.name}`} onClose={() => setFormOpen("")} suspended={!!confirm}>{connectionForm(connection.id)}</FormModal>}
    </> : <><PageHead eyebrow="供应商连接" title="供应商连接" description="连接与服务配置分层维护；凭据由高权限角色处理。" actions={canConfigure ? <Button variant="primary" onClick={() => openConnectionEditor()}>新增连接</Button> : undefined}/><Section><DataTable rows={connections} searchLabel="搜索连接" persistKey="oms:connections" rowActions={row => [{ label: "连接资料", onClick: () => go(`${base}/connections/${row.id}`) }, ...(canConfigure ? [{ label: credentialDemos[`connection:${row.id}`] ? "轮换凭据" : "配置凭据", onClick: () => openCredential(`connection:${row.id}`, "连接", "API Key") }] : [])]} columns={[{ key: "name", label: "连接", render: row => title(row.name, row.provider) }, { key: "scope", label: "适用服务", render: row => row.scope }, { key: "credential", label: "凭据状态", render: row => credentialStatus(`connection:${row.id}`) }, { key: "status", label: "状态", render: row => badge(row.status) }]}/></Section></>;
  } else if (["agents", "tools", "knowledge", "runtime"].includes(root)) {
    const data = resourceRows[root as keyof typeof resourceRows];
    const heading = ({ agents: "Agent 与能力", tools: "工具与集成", knowledge: "知识基础能力", runtime: "运行资源" } as Record<string, string>)[root] ?? "平台资源";
    const item = data.find(row => row.id === segments[1]);
    const policy = item ? resourcePolicies[`${root}:${item.id}`] : undefined;
    const resourceView = segments[2] ?? "info";
    content = item ? <><PageHead eyebrow="资源详情" title={item.name} breadcrumbs={crumbs(heading, `${base}/${root}`, item.name)} description="内置能力身份来自基座；OMS 维护平台使用策略，不在线改写注册表。" actions={canConfigure && resourceView === "policy" ? <Button variant="primary" onClick={() => { setPolicyNote(policy?.note ?? ""); setPolicyScope(policy?.scope ?? "获授权学校"); setFormOpen("policy"); }}>管理平台策略</Button> : undefined}/>{resourceView === "policy" && <Notice tone="warn">{root === "agents" ? "Agent 运行参数待接入：模型、推理档位、权限模式、沙箱和网络开关等仍以基座设置与执行者为准。" : root === "tools" ? "Tool 运行参数待接入：工具启用、授权与执行条件仍以基座设置与执行者为准。" : "平台运行参数待接入：此处仅演示策略说明，不修改基座实际配置。"}当前平台策略草稿不是完整运行参数配置，也不会改变运行态。</Notice>}{resourceView === "info" && <DetailGrid rows={[{ label: "资源类别", value: item.type }, { label: "运行状态", value: badge(item.status) }, { label: "依赖", value: item.dependency }, { label: "配置来源", value: item.status === "草稿" ? "OMS 本地平台草稿" : "基座现有能力 / 企业扩展演示" }, { label: "平台策略草稿", value: policy?.note ?? "尚无草稿" }, { label: "适用范围草稿", value: policy?.scope ?? "尚无草稿" }, { label: "真实生效", value: "待执行者确认" }]}/>}
    {resourceView === "policy" && <DetailGrid rows={[{ label: "平台策略草稿", value: policy?.note ?? "尚无草稿" }, { label: "适用范围", value: policy?.scope ?? "尚无草稿" }, { label: "真实生效", value: "待执行者确认" }]}/>}
    {resourceView === "policy" && !formOpen && notice}{resourceView === "policy" && formOpen === "policy" && canConfigure && <FormModal title={`管理${item.name}策略`} onClose={() => setFormOpen("")} suspended={!!confirm}><div className="side-panel"><h3>{heading} · 平台策略草稿</h3><Notice>这里不修改内置代码、学校私有资源或运行态。</Notice><div className="form-grid"><label className="form-field">适用范围<select value={policyScope} onChange={event => setPolicyScope(event.target.value)}><option>获授权学校</option><option>仅平台测试</option><option>暂不开放新调用</option></select></label><label className="form-field">策略说明<input value={policyNote} onChange={event => setPolicyNote(event.target.value)} placeholder="例如：仅供已授权学校使用"/></label></div>{notice}<div className="form-actions"><Button variant="primary" onClick={() => { if (!policyNote.trim()) { setMessage("请填写策略说明。"); return; } setResourcePolicies({ ...resourcePolicies, [`${root}:${item.id}`]: { note: policyNote.trim(), scope: policyScope } }); setFormOpen(""); setMessage("本地演示策略草稿已保存；真实运行状态未变更。"); }}>保存策略草稿</Button><Button onClick={() => setFormOpen("")}>取消</Button></div></div></FormModal>}{(resourceView === "dependencies" || resourceView === "related") && <Section title="依赖服务"><Notice>只显示已明确登记的本地演示依赖；说明文本不作为授权证据。</Notice>{resourceServiceDependencies[`${root}:${item.id}`] ? <DataTable rows={services.filter(row => resourceServiceDependencies[`${root}:${item.id}`].includes(row.id))} searchLabel="搜索依赖服务" rowActions={row => [{ label: "服务资料", onClick: () => go(`${base}/services/${row.id}/info`) }, ...(canConfigure ? [{ label: "服务配置", onClick: () => go(`${base}/services/${row.id}/config`) }] : [])]} columns={[{ key: "name", label: "服务", render: row => row.name }, { key: "status", label: "状态", render: row => badge(row.status) }]}/> : <Notice tone="warn">该资源的服务依赖关系待接入可信来源，不能由说明文字推断。</Notice>}</Section>}
    {resourceView === "school-scope" && <Section title="学校可用范围"><Notice tone="warn">尚无该资源面向学校的可信授权关系；平台策略草稿不等于学校授权。请到对应服务或 Skill 的授权专题核对，当前不能在此新增或撤销关系。</Notice></Section>}</> : <><PageHead eyebrow="资源目录" title={heading} description="以对象列表进入详情；获授权人员可维护平台策略。" actions={canConfigure ? <Button variant="primary" onClick={() => setFormOpen("create-resource")}>新增 {heading}</Button> : undefined}/><Section><DataTable rows={viewState === "empty" ? [] : data} state={viewState} searchLabel="搜索资源" persistKey={`oms:${root}`} rowActions={row => [{ label: "资源资料", onClick: () => go(`${base}/${root}/${row.id}/info`) }, { label: "平台策略", onClick: () => go(`${base}/${root}/${row.id}/policy`) }, { label: "依赖服务", onClick: () => go(`${base}/${root}/${row.id}/dependencies`) }, { label: "学校可用范围", onClick: () => go(`${base}/${root}/${row.id}/school-scope`) }]} columns={[{ key: "name", label: "资源", render: row => title(row.name, row.id) }, { key: "type", label: "类别", render: row => row.type }, { key: "dependency", label: "依赖或配置", render: row => row.dependency }, { key: "status", label: "状态", render: row => badge(row.status) }]}/></Section></>;
  } else if (root === "supply") {
    const selected = supply.find(item => item.id === segments[1]);
    const supplyView = segments[2] ?? "info";
    const invalidSupplyRecord = ["plans", "batches"].includes(segments[1]) && (segments.length !== 3 && !(segments[1] === "plans" && segments.length === 4 && segments[3] === "batches"));
    content = invalidSupplyRecord ? <StatePanel state="forbidden" message="对象不存在或不可访问"/> : selected ? <><PageHead eyebrow="服务供给详情" title={selected.name} breadcrumbs={crumbs("服务供给", `${base}/supply`, selected.name)} description="外部资源取得、学校承诺与实际消耗分开记录。"/>
      {supplyView === "info" && <DetailGrid rows={[{ label: "供应来源", value: selected.provider }, { label: "服务", value: selected.service }, { label: "计量单位", value: selected.unit }, { label: "累计取得", value: selected.acquired.toLocaleString() }, { label: "已承诺", value: selected.committed.toLocaleString() }, { label: "实际消耗", value: selected.used.toLocaleString() }, { label: "可继续授予", value: selected.available.toLocaleString() }, { label: "状态", value: badge(selected.status) }, { label: "记录类型", value: "供给批次（演示）" }]}/>}
      {supplyView === "acquisition" && <><Notice>供应商成本仅限 OMS 高权限查看；此原型不伪造金额。</Notice><DataTable rows={supplyHistory.filter(row => row.supplyId === selected.id)} searchLabel="搜索取得记录" columns={[{ key: "source", label: "来源说明", render: row => row.source }, { key: "amount", label: "取得额度", render: row => `${row.amount.toLocaleString()} ${selected.unit}` }, { key: "time", label: "记录时间", render: row => row.time }]}/></>}
      {supplyView === "commitments" && <DataTable rows={grants.filter(g => g.supplyId === selected.id)} searchLabel="搜索额度" rowActions={row => [{ label: "额度详情", onClick: () => go(`${base}/tenants/${row.tenantId}/grants/${row.id}`) }, { label: "消耗明细", onClick: () => go(`${base}/usage?grant=${encodeURIComponent(row.id)}`) }]} columns={[{ key: "tenant", label: "学校", render: row => row.tenant }, { key: "method", label: "获取方式", render: row => row.method }, { key: "remaining", label: "剩余", render: row => row.remaining === null ? "待核对" : `${row.remaining.toLocaleString()} ${row.unit}` }]}/>}
      {supplyView === "usage" && <Section title="实际消耗"><DataTable rows={calls.filter(row => row.supplyId === selected.id)} searchLabel="搜索供给调用" rowActions={row => [{ label: "调用详情", onClick: () => go(`${base}/usage/${row.id}`) }]} columns={[{ key: "id", label: "调用", render: row => title(row.id, row.time) }, { key: "usage", label: "实际用量", render: row => row.usage }, { key: "status", label: "状态", render: row => badge(row.status) }]}/><Notice>待核对调用未建立可信供给关联，不作为零用量。</Notice></Section>}
      </> : <><PageHead eyebrow="服务供给" title="服务供给" description="来源登记须核对，确认后才形成可授予供给；授予形成承诺，实际调用才产生消耗。"/><MetricStrip items={[{ label: "供给项目", value: `${supply.length}` }, { label: "需补充", value: `${supply.filter(item => item.status === "需补充").length}`, tone: "warning" }, { label: "待核对", value: "1", note: "不可记为零" }, { label: "计量单位", value: "多种", note: "不可混算 Token" }]}/><OmsSupplyCatalog supply={supply} canWrite={canWrite} selected={segments[1] === "plans" && segments[2] ? { type: "plan", id: segments[2], view: segments[3] === "batches" ? "batches" as const : undefined } : segments[1] === "batches" && segments[2] ? { type: "batch", id: segments[2] } : null} onSelectRecord={(type, id, view) => go(`${base}/supply/${type === "plan" ? "plans" : "batches"}/${encodeURIComponent(id)}${view ? `/${view}` : ""}`)} onCloseRecord={() => { if (segments[1] === "plans" && segments[3] === "batches") { go(`${base}/supply/plans/${segments[2]}`, true); return; } if (returnRoute) { const previous = returnRoute; setReturnRoute(null); go(previous, true); } else go(`${base}/supply`); }} onOpenService={id => go(`${base}/services/${id}/info`)} onOpen={(id, view) => go(`${base}/supply/${id}/${view}`)}/></>;
  } else if (root === "usage") {
    const call = calls.find(item => item.id === segments[1]);
    content = call ? <><PageHead eyebrow="用量详情" title={`调用 ${call.id}`} breadcrumbs={crumbs("用量与运行", `${base}/usage`, call.id)} description="逐次记录原生用量与额度分摊，未知结果需核对。"/><DetailGrid rows={[{ label: "发生时间", value: call.time }, { label: "学校", value: call.tenant }, { label: "用户", value: call.user }, { label: "服务", value: call.service }, { label: "实际用量", value: call.usage }, { label: "核对状态", value: badge(call.status) }, { label: "额度消耗", value: call.grant }, { label: "供应商供给", value: call.status === "待核对" ? "待确认" : "演示供给批次" }, { label: "幂等键", value: "演示调用编号" }]}/>{call.grantIds.length > 0 && <Section title="关联额度"><div className="inline-list">{call.grantIds.map(id => { const grant = grants.find(row => row.id === id && row.tenantId === call.tenantId); return grant ? <Button key={id} onClick={() => go(`${base}/tenants/${grant.tenantId}/grants/${grant.id}`)}>额度 {id}</Button> : null; })}</div></Section>}{call.supplyId && supply.some(row => row.id === call.supplyId && row.serviceId === call.serviceId) && <Button onClick={() => go(`${base}/supply/${call.supplyId}/info`)}>查看供给记录</Button>}{call.status === "待核对" && <Notice tone="warn">此调用结果尚未核实，不能按零消耗扣减或结算。</Notice>}
</> : <><PageHead eyebrow="用量与运行" title="用量与运行" description="按学校、服务和用户核对调用；复合 Agent 的底层用量不可重复计算。"/>{list(calls.filter(row => { const query = new URLSearchParams(locationSearch); return (!query.get("tenant") || row.tenantId === query.get("tenant")) && (!query.get("service") || row.serviceId === query.get("service")) && (!query.get("grant") || row.grantIds.includes(query.get("grant")!)); }), [{ key: "id", label: "调用", render: row => title(row.id, row.time) }, { key: "tenant", label: "学校 / 用户", render: row => title(row.tenant, row.user) }, { key: "service", label: "服务", render: row => row.service }, { key: "usage", label: "实际用量", render: row => row.usage }, { key: "status", label: "状态", render: row => badge(row.status) }], row => `${base}/usage/${row.id}`, "搜索用量")}</>;
  } else if (root === "audit") {
    const event = audits.find(item => item.id === segments[1]);
    content = event ? <>
      <PageHead
        eyebrow="审计详情"
        title={event.action}
        breadcrumbs={crumbs("审计与治理", `${base}/audit`, event.id)}
      />
      <DetailGrid rows={[
        { label: "事件编号", value: event.id },
        { label: "时间", value: event.time },
        { label: "操作者", value: event.actor },
        { label: "目标", value: event.target },
        { label: "状态", value: badge(event.status) },
        { label: "记录来源", value: "OMS 演示记录" },
      ]}/>
    </> : <>
      <PageHead
        eyebrow="审计与治理"
        title="审计与治理"
        description="授权、配置与供给变更均应形成可追溯记录。"
      />
      {list(audits, [
        { key: "action", label: "事件", render: row => title(row.action, row.id) },
        { key: "target", label: "目标", render: row => row.target },
        { key: "actor", label: "操作者", render: row => row.actor },
        { key: "time", label: "时间", render: row => row.time },
        { key: "status", label: "状态", render: row => badge(row.status) },
      ], row => `${base}/audit/${row.id}`, "搜索审计事件")}
    </>;
  } else { content = <StatePanel state="empty" message="该原型页面不存在。"/>; }
  return content;
  };

  const isDetail = segments.length > 1 && root !== "skills" && !authRoots.has(root) && !(root === "supply" && ["plans", "batches"].includes(segments[1]));
  const closeDetail = () => {
    const nestedParent = root === "services" && segments[3] && segments[1] && ["provider", "models"].includes(segments[2]) ? `${base}/services/${segments[1]}/${segments[2]}` : root === "tenants" && segments[2] === "grants" && segments[3] && segments[1] ? `${base}/tenants/${segments[1]}/grants` : null;
    if (nestedParent) { go(nestedParent, true); return; }
    if (returnRoute) { const previous = returnRoute; setReturnRoute(null); go(previous, true); return; }
    go(`${base}/${root}`);
  };
  let detailName: string | undefined;
  if (root === "services") detailName = (!segments[2] || ["info", "config", "provider", "models", "release", "relations", "supply", "schools", "grants", "usage", "connections"].includes(segments[2])) && (segments.length <= 3 || ((segments[2] === "provider" && profiles.some(row => row.serviceId === segments[1] && row.id === segments[3])) || (segments[2] === "models" && models.some(row => row.serviceId === segments[1] && row.id === segments[3])))) && segments.length <= 4 ? serviceRows.find(row => row.id === segments[1])?.name : undefined;
  else if (root === "connections") detailName = segments.length <= 2 ? connections.find(row => row.id === segments[1])?.name : undefined;
  else if (root === "tenants") {
    const tenant = tenants.find(row => row.id === segments[1]);
    detailName = segments[2] === "grants" && segments[3]
      ? (segments.length === 4 ? (tenant && grants.some(row => row.tenantId === tenant.id && row.id === segments[3]) ? `额度 ${segments[3]}` : undefined) : undefined)
      : tenant && (!segments[2] || ["info", "access", "grants"].includes(segments[2])) && segments.length <= 3 ? tenant.name : undefined;
  } else if (root === "supply") detailName = (!segments[2] || ["info", "acquisition", "commitments", "usage"].includes(segments[2])) && segments.length <= 3 ? supply.find(row => row.id === segments[1])?.name : undefined;
  else if (["agents", "tools", "knowledge", "runtime"].includes(root)) detailName = (!segments[2] || ["info", "policy", "related", "dependencies", "school-scope"].includes(segments[2])) && segments.length <= 3 ? resourceRows[root as keyof typeof resourceRows].find(row => row.id === segments[1])?.name : undefined;
  else if (root === "usage") detailName = segments.length <= 2 && calls.some(row => row.id === segments[1]) ? `调用 ${segments[1]}` : undefined;
  else if (root === "audit") detailName = segments.length <= 2 && audits.some(row => row.id === segments[1]) ? `事件 ${segments[1]}` : undefined;
  const listContent = renderContent(isDetail ? [root] : segments);
  const detailContent = isDetail ? (detailName ? renderContent(segments) : <StatePanel state="empty" message="对象不存在或不可访问"/>) : null;

  return <AdminShell product="OMS" subtitle="平台智能体运营后台" scope="平台运营空间" groups={role === "limited" ? nav.slice(0, 1) : nav} path={root === "home" ? base : `${base}/${root}`} onNavigate={go}>
    <div className="scenario-bar" style={{ justifyContent: "flex-end", marginBottom: 12 }}><span>演示角色</span><select aria-label="演示角色" value={role} onChange={event => { setRole(event.target.value); setFormOpen(""); setConfirm(null); }}><option value="admin">平台管理员</option><option value="operator">平台运营</option><option value="auditor">只读审计</option><option value="limited">无权限</option></select></div>
    {viewState === "forbidden" ? <StatePanel state="forbidden"/> : <>{listContent}{!isDetail && message && <Notice>{message}</Notice>}{isDetail && <Drawer title={`详情 · ${detailName ?? "未找到"}`} onClose={closeDetail} suspended={!!formOpen || !!confirm}>{detailContent}</Drawer>}{formOpen === "new-connection" && canConfigure && (!isDetail || (root === "services" && segments[2] === "connections")) && <FormModal title="新增连接" onClose={() => setFormOpen("")} suspended={!!confirm}>{connectionForm()}</FormModal>}{formOpen === "connection" && canConfigure && root === "services" && segments[2] === "connections" && editingConnectionId && <FormModal title={`编辑${connections.find(row => row.id === editingConnectionId)?.name ?? "连接"}`} onClose={() => setFormOpen("")} suspended={!!confirm}>{connectionForm(editingConnectionId)}</FormModal>}{formOpen === "create-resource" && canConfigure && !isDetail && ["services", "agents", "tools", "knowledge", "runtime"].includes(root) && <FormModal title={root === "services" ? "新增服务接入" : `新增 ${({ agents: "Agent 与能力", tools: "工具与集成", knowledge: "知识基础能力", runtime: "运行资源" } as Record<string, string>)[root]}`} onClose={() => setFormOpen("")}><OmsResourceCreate kind={root as ResourceKind} existingIds={root === "services" ? serviceRows.map(row => row.id) : resourceRows[root as keyof typeof resourceRows].map(row => row.id)} onSave={row => { if (root === "services") { setServiceRows(current => [{ id: row.id, name: row.name, category: "外部接入草稿", status: "unavailable", unit: row.unit ?? "", description: "适配器待接入，不可调用" }, ...current]); setServiceDrafts(current => ({ ...current, [row.id]: row })); } else { const key = root as keyof typeof resourceRows; setResourceRows(current => ({ ...current, [key]: [row, ...current[key]] })); } setFormOpen(""); setMessage("平台资源草稿已保存至本地目录；执行者未接入，尚未生效。"); }} onCancel={() => setFormOpen("")}/></FormModal>}</>}
    {formOpen === "credential" && canConfigure && credentialTarget && <FormModal title={`${credentialDemos[credentialTarget.key] ? "轮换" : "配置"}${/[A-Za-z]/.test(credentialTarget.scope) ? " " : ""}${credentialTarget.scope}${/[A-Za-z]/.test(credentialTarget.scope) ? " " : ""}凭据`} onClose={() => setFormOpen("")}><DemoCredentialForm label={credentialTarget.label} onCancel={() => setFormOpen("")} onSave={() => { setCredentialDemos(current => ({ ...current, [credentialTarget.key]: true })); setFormOpen(""); setMessage("仅记录演示凭据状态；输入值已丢弃，未托管、未验证，也未改变真实配置。"); }}/></FormModal>}
    {confirm && <ConfirmModal title={confirm.title} description={confirm.description} onCancel={() => setConfirm(null)} onConfirm={() => { confirm.action(); setConfirm(null); }}/ >}
  </AdminShell>;
}
